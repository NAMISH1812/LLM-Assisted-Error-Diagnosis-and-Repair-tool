"""Regex -> NFA -> DFA construction used to build the lexer.

Pipeline (the classic textbook route, implemented from scratch):

    regex string --(recursive-descent regex parser)--> regex AST
    regex AST    --(Thompson's construction)-------->  epsilon-NFA
    epsilon-NFA  --(subset construction)------------>  DFA
    DFA          --(Moore partition refinement)----->  minimal DFA

Several token patterns can be combined into one automaton.  Each pattern's
NFA accept state is tagged with ``(priority, token_name)``; when a DFA state
contains several accepting NFA states, the pattern listed *first* wins.  This
is how keywords beat identifiers (``if`` vs ``[a-zA-Z_]...``), while maximal
munch in the lexer makes ``iffy`` an identifier.

Supported regex syntax:
    literals, ``\\`` escapes (``\\n \\t \\r`` and escaped metacharacters),
    ``.`` (any character except newline), ``[abc]``, ``[a-z]``, ``[^...]``,
    grouping ``( )``, alternation ``|``, and the postfix operators ``* + ?``.
"""

from __future__ import annotations

from dataclasses import dataclass

# The lexer's input alphabet: tab, LF, CR and printable ASCII.  Any character
# outside this set can never start a token and is reported as a lexical error.
ALPHABET: frozenset[str] = frozenset(chr(c) for c in [9, 10, 13, *range(32, 127)])

REGEX_METACHARS = set("()[]|*+?.\\")


class RegexSyntaxError(ValueError):
    """Raised when a token pattern is not a valid regular expression."""


# --------------------------------------------------------------------------
# Regex AST
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CharSet:
    chars: frozenset


@dataclass(frozen=True)
class Concat:
    parts: tuple


@dataclass(frozen=True)
class Alt:
    options: tuple


@dataclass(frozen=True)
class Star:
    inner: object


@dataclass(frozen=True)
class Plus:
    inner: object


@dataclass(frozen=True)
class Opt:
    inner: object


@dataclass(frozen=True)
class Epsilon:
    pass


def escape(literal: str) -> str:
    """Escape a literal string so it can be used as a regex pattern."""
    return "".join("\\" + c if c in REGEX_METACHARS else c for c in literal)


class _RegexParser:
    """Recursive-descent parser for the regex grammar:

        alt    = concat { "|" concat }
        concat = { repeat }
        repeat = atom { "*" | "+" | "?" }
        atom   = "(" alt ")" | "[" class "]" | "\\" char | "." | char
    """

    def __init__(self, pattern: str):
        self.p = pattern
        self.i = 0

    def parse(self):
        node = self._alt()
        if self.i != len(self.p):
            raise RegexSyntaxError(
                f"unexpected {self.p[self.i]!r} at offset {self.i} in {self.p!r}")
        return node

    def _peek(self):
        return self.p[self.i] if self.i < len(self.p) else None

    def _next(self) -> str:
        ch = self.p[self.i]
        self.i += 1
        return ch

    def _alt(self):
        options = [self._concat()]
        while self._peek() == "|":
            self._next()
            options.append(self._concat())
        return options[0] if len(options) == 1 else Alt(tuple(options))

    def _concat(self):
        parts = []
        while self._peek() is not None and self._peek() not in "|)":
            parts.append(self._repeat())
        if not parts:
            return Epsilon()
        return parts[0] if len(parts) == 1 else Concat(tuple(parts))

    def _repeat(self):
        node = self._atom()
        while self._peek() is not None and self._peek() in "*+?":
            op = self._next()
            node = Star(node) if op == "*" else Plus(node) if op == "+" else Opt(node)
        return node

    def _atom(self):
        ch = self._next()
        if ch == "(":
            node = self._alt()
            if self._peek() != ")":
                raise RegexSyntaxError(f"missing ')' in {self.p!r}")
            self._next()
            return node
        if ch == "[":
            return self._char_class()
        if ch == ".":
            return CharSet(ALPHABET - {"\n"})
        if ch == "\\":
            return CharSet(frozenset({self._escape()}))
        if ch in "*+?":
            raise RegexSyntaxError(f"nothing to repeat at offset {self.i - 1} in {self.p!r}")
        if ch in ")]":
            raise RegexSyntaxError(f"unbalanced {ch!r} at offset {self.i - 1} in {self.p!r}")
        return CharSet(frozenset({ch}))

    def _escape(self) -> str:
        if self._peek() is None:
            raise RegexSyntaxError(f"dangling backslash in {self.p!r}")
        ch = self._next()
        return {"n": "\n", "t": "\t", "r": "\r"}.get(ch, ch)

    def _class_char(self) -> str:
        ch = self._next()
        return self._escape() if ch == "\\" else ch

    def _char_class(self):
        negate = False
        if self._peek() == "^":
            self._next()
            negate = True
        chars: set[str] = set()
        first = True
        while True:
            ch = self._peek()
            if ch is None:
                raise RegexSyntaxError(f"unterminated '[' in {self.p!r}")
            if ch == "]" and not first:
                self._next()
                break
            first = False
            lo = self._class_char()
            # A range like a-z (a trailing '-' before ']' is a literal '-').
            if self._peek() == "-" and self.i + 1 < len(self.p) and self.p[self.i + 1] != "]":
                self._next()
                hi = self._class_char()
                if ord(hi) < ord(lo):
                    raise RegexSyntaxError(f"bad range {lo}-{hi} in {self.p!r}")
                chars.update(chr(c) for c in range(ord(lo), ord(hi) + 1))
            else:
                chars.add(lo)
        cs = frozenset(chars)
        return CharSet(ALPHABET - cs if negate else cs)


def parse_regex(pattern: str):
    return _RegexParser(pattern).parse()


# --------------------------------------------------------------------------
# Thompson's construction: regex AST -> epsilon-NFA
# --------------------------------------------------------------------------

class NFA:
    def __init__(self):
        # edges[state] = list of (label, target); label None means epsilon,
        # otherwise label is a frozenset of characters.
        self.edges: list[list[tuple[frozenset | None, int]]] = []
        self.accepting: dict[int, tuple[int, str]] = {}  # state -> (priority, tag)
        self.start: int = -1

    def new_state(self) -> int:
        self.edges.append([])
        return len(self.edges) - 1

    def add_edge(self, src: int, label: frozenset | None, dst: int) -> None:
        self.edges[src].append((label, dst))

    @property
    def num_states(self) -> int:
        return len(self.edges)


def _thompson(nfa: NFA, node) -> tuple[int, int]:
    """Return (start, accept) of the NFA fragment for ``node``."""
    if isinstance(node, CharSet):
        s, a = nfa.new_state(), nfa.new_state()
        nfa.add_edge(s, node.chars, a)
        return s, a
    if isinstance(node, Epsilon):
        s, a = nfa.new_state(), nfa.new_state()
        nfa.add_edge(s, None, a)
        return s, a
    if isinstance(node, Concat):
        frags = [_thompson(nfa, part) for part in node.parts]
        for (_, a1), (s2, _) in zip(frags, frags[1:]):
            nfa.add_edge(a1, None, s2)
        return frags[0][0], frags[-1][1]
    if isinstance(node, Alt):
        s, a = nfa.new_state(), nfa.new_state()
        for option in node.options:
            fs, fa = _thompson(nfa, option)
            nfa.add_edge(s, None, fs)
            nfa.add_edge(fa, None, a)
        return s, a
    if isinstance(node, (Star, Plus, Opt)):
        s, a = nfa.new_state(), nfa.new_state()
        fs, fa = _thompson(nfa, node.inner)
        nfa.add_edge(s, None, fs)
        nfa.add_edge(fa, None, a)
        if not isinstance(node, Plus):   # Star / Opt may skip the body
            nfa.add_edge(s, None, a)
        if not isinstance(node, Opt):    # Star / Plus may repeat the body
            nfa.add_edge(fa, None, fs)
        return s, a
    raise TypeError(f"unknown regex node {node!r}")


def build_nfa(specs: list[tuple[str, str]]) -> NFA:
    """Build one NFA recognising every ``(name, pattern)`` in ``specs``.

    Earlier specs get higher priority when several patterns match the same
    lexeme.
    """
    nfa = NFA()
    nfa.start = nfa.new_state()
    for priority, (name, pattern) in enumerate(specs):
        s, a = _thompson(nfa, parse_regex(pattern))
        nfa.add_edge(nfa.start, None, s)
        nfa.accepting[a] = (priority, name)
    return nfa


# --------------------------------------------------------------------------
# Subset construction: NFA -> DFA
# --------------------------------------------------------------------------

@dataclass
class DFA:
    start: int
    transitions: list[dict[str, int]]   # missing entry == dead state
    accepting: dict[int, str]           # state -> token name

    def step(self, state: int, ch: str) -> int | None:
        return self.transitions[state].get(ch)

    @property
    def num_states(self) -> int:
        return len(self.transitions)

    def accepts(self, text: str) -> str | None:
        """Return the token name if the *whole* text is accepted, else None."""
        state: int | None = self.start
        for ch in text:
            state = self.step(state, ch)
            if state is None:
                return None
        return self.accepting.get(state)


def _epsilon_closure(nfa: NFA, states) -> frozenset[int]:
    stack = list(states)
    seen = set(states)
    while stack:
        s = stack.pop()
        for label, dst in nfa.edges[s]:
            if label is None and dst not in seen:
                seen.add(dst)
                stack.append(dst)
    return frozenset(seen)


def nfa_to_dfa(nfa: NFA) -> DFA:
    start_set = _epsilon_closure(nfa, [nfa.start])
    ids: dict[frozenset[int], int] = {start_set: 0}
    transitions: list[dict[str, int]] = [{}]
    worklist = [start_set]

    while worklist:
        current = worklist.pop()
        cid = ids[current]
        moves: dict[str, set[int]] = {}
        for s in current:
            for label, dst in nfa.edges[s]:
                if label is not None:
                    for ch in label:
                        moves.setdefault(ch, set()).add(dst)
        closure_cache: dict[frozenset[int], frozenset[int]] = {}
        for ch, targets in moves.items():
            key = frozenset(targets)
            nxt = closure_cache.get(key)
            if nxt is None:
                nxt = closure_cache[key] = _epsilon_closure(nfa, key)
            if nxt not in ids:
                ids[nxt] = len(transitions)
                transitions.append({})
                worklist.append(nxt)
            transitions[cid][ch] = ids[nxt]

    accepting: dict[int, str] = {}
    for state_set, i in ids.items():
        tags = [nfa.accepting[s] for s in state_set if s in nfa.accepting]
        if tags:
            accepting[i] = min(tags)[1]  # lowest priority number wins
    return DFA(0, transitions, accepting)


# --------------------------------------------------------------------------
# DFA minimisation (Moore's partition refinement)
# --------------------------------------------------------------------------

def minimize(dfa: DFA) -> DFA:
    alphabet = sorted(ALPHABET)
    n = dfa.num_states
    # Initial partition: states grouped by the token they accept (None = non-accepting).
    labels: dict[str | None, int] = {}
    block = [labels.setdefault(dfa.accepting.get(s), len(labels)) for s in range(n)]
    num_blocks = len(labels)

    while True:
        signatures: dict[tuple, int] = {}
        new_block = []
        for s in range(n):
            row = dfa.transitions[s]
            sig = (block[s], *(block[row[c]] if c in row else -1 for c in alphabet))
            new_block.append(signatures.setdefault(sig, len(signatures)))
        block = new_block
        if len(signatures) == num_blocks:
            break
        num_blocks = len(signatures)

    # Renumber blocks so the start state is 0.
    order = {block[dfa.start]: 0}
    for s in range(n):
        order.setdefault(block[s], len(order))
    transitions: list[dict[str, int]] = [{} for _ in range(len(order))]
    accepting: dict[int, str] = {}
    for s in range(n):
        b = order[block[s]]
        for ch, t in dfa.transitions[s].items():
            transitions[b][ch] = order[block[t]]
        if s in dfa.accepting:
            accepting[b] = dfa.accepting[s]
    return DFA(0, transitions, accepting)


def compile_dfa(specs: list[tuple[str, str]], do_minimize: bool = True) -> DFA:
    """Convenience: build the (minimal) DFA for a list of token specs."""
    dfa = nfa_to_dfa(build_nfa(specs))
    return minimize(dfa) if do_minimize else dfa
