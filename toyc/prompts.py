"""Error-type-specific prompt templates.

Each diagnostic is dispatched on its ``ErrorCode`` to a template that injects
exactly the compiler facts relevant to that error class:

==============================  ==============================================
Template                        Error codes
==============================  ==============================================
PromptSyntaxMissingDelimiter    SYN_UNBALANCED_DELIMITER, SYN_MISSING_SEMICOLON
PromptSyntaxGeneral             all other SYN_* and LEX_* codes
PromptUndeclaredVariable        SEM_UNDECLARED_VARIABLE, SEM_DUPLICATE_DECLARATION
PromptTypeMismatch              SEM_TYPE_MISMATCH, SEM_RETURN_MISMATCH, SEM_INVALID_VOID
PromptUndefinedFunction         SEM_UNDEFINED_FUNCTION, SEM_ARGUMENT_MISMATCH, SEM_NOT_CALLABLE
PromptGenericBaseline           (ablation control -- used for every code)
==============================  ==============================================

``PromptGenericBaseline`` deliberately sees only what a wrapper around a
conventional compiler would see: the flattened one-line error message and the
source file.  The typed templates see the structured diagnostic.  Comparing
the two is the ablation study in :mod:`toyc.evaluation`.

Every template asks for the same JSON response (see :data:`RESPONSE_SCHEMA`),
so the verifier never depends on which template produced a suggestion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .context import ErrorContext, numbered_source
from .errors import ErrorCode

C = ErrorCode

LANGUAGE_SUMMARY = """\
Toy-C is a small C subset:
- types: int, bool, void (void only as a function return type); no implicit int<->bool conversion
- top level: global variable declarations and function definitions (functions may be called before they are defined)
- statements: variable declaration, if/else, while, return, block { ... }, expression statement
- expressions: = (assignment to a variable only), || && == != < <= > >= + - * / % and unary ! -, calls f(a, b), true/false, integer literals
- no strings, arrays, pointers, for-loops, ++/--, or compound assignment"""

SYSTEM_INSTRUCTION = """\
You are a patient compiler tutor helping a student fix an error reported by the Toy-C compiler.
Explain the problem in plain English a beginner can follow (2-4 sentences, no jargon without explanation),
then give the smallest change that fixes it. Keep the student's intent, names and formatting.
Change only what is needed for THIS error. Respond ONLY with JSON matching the requested schema."""

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string",
                        "description": "Plain-English explanation of what is wrong and why."},
        "fix_description": {"type": "string",
                            "description": "One sentence describing the change to make."},
        "fixed_source": {"type": "string",
                         "description": "The COMPLETE corrected program, without line numbers or markdown fences."},
    },
    "required": ["explanation", "fix_description", "fixed_source"],
}

_RESPONSE_INSTRUCTIONS = """\
Respond with a JSON object with exactly these keys:
  "explanation":     plain-English explanation of the error and its cause
  "fix_description": one sentence describing the change
  "fixed_source":    the COMPLETE corrected program text (no line numbers, no markdown fences)"""


@dataclass
class Prompt:
    template: str
    system: str
    user: str
    error_code: str

    @property
    def text(self) -> str:
        return f"{self.system}\n\n{self.user}"

    def to_dict(self) -> dict:
        return {"template": self.template, "error_code": self.error_code,
                "system": self.system, "user": self.user}


class PromptTemplate:
    name = "PromptTemplate"
    codes: frozenset[ErrorCode] = frozenset()
    focus = ""

    def build(self, ctx: ErrorContext) -> Prompt:
        sections = [
            LANGUAGE_SUMMARY,
            self._diagnostic_section(ctx),
            self.specific(ctx),
            self._source_section(ctx),
            f"Task: {self.focus}\n\n{_RESPONSE_INSTRUCTIONS}",
        ]
        user = "\n\n".join(s for s in sections if s)
        return Prompt(self.name, SYSTEM_INSTRUCTION, user, ctx.diagnostic.code.value)

    # -- shared sections ----------------------------------------------------
    def _diagnostic_section(self, ctx: ErrorContext) -> str:
        d = ctx.diagnostic
        lines = [
            "## Structured compiler diagnostic",
            f"- code: {d.code.value} ({d.category.value} error)",
            f"- message: {d.message}",
            f"- location: line {d.line}, column {d.column}",
            f"- source line: `{d.source_line.strip()}`",
        ]
        if d.rule_stack:
            lines.append(f"- grammar/analysis path: {' > '.join(d.rule_stack)}")
        if d.expected:
            lines.append(f"- expected: {', '.join(d.expected)}")
        if d.found:
            lines.append(f"- found: {d.found['description']} at line {d.found['line']}, "
                         f"column {d.found['column']}")
        for r in d.related:
            lines.append(f"- related: {r.message} (line {r.line}, column {r.column})")
        if d.hint:
            lines.append(f"- compiler hint: {d.hint}")
        if ctx.enclosing_function:
            lines.append(f"- enclosing function: {ctx.enclosing_function}")
        if ctx.other_errors:
            lines.append("- other errors in this file (do not fix them unless required):")
            lines.extend(f"    - {e}" for e in ctx.other_errors)
        return "\n".join(lines)

    def _source_section(self, ctx: ErrorContext) -> str:
        return (f"## Error window (lines {ctx.snippet_start}-{ctx.snippet_end}, '>' marks the error line)\n"
                f"{ctx.snippet}\n\n"
                f"## Full program `{ctx.filename}` (line numbers are NOT part of the code)\n"
                f"{numbered_source(ctx.source)}")

    def _symbols_section(self, ctx: ErrorContext, title: str) -> str:
        if not ctx.symbols:
            return f"## {title}\n(none)"
        exact = "exact, from the semantic analyser" if ctx.symbols_exact else "approximate, recovered from tokens"
        body = "\n".join(f"- {s}" for s in ctx.symbol_lines)
        return f"## {title} ({exact})\n{body}"

    def specific(self, ctx: ErrorContext) -> str:
        return ""


class PromptSyntaxMissingDelimiter(PromptTemplate):
    name = "PromptSyntaxMissingDelimiter"
    codes = frozenset({C.SYN_UNBALANCED_DELIMITER, C.SYN_MISSING_SEMICOLON})
    focus = ("Explain which delimiter is missing and why the compiler noticed it where it did "
             "(often later than where it belongs), then insert it in the right place.")

    def specific(self, ctx: ErrorContext) -> str:
        d = ctx.diagnostic
        delim = d.expected[0] if d.expected else "a delimiter"
        lines = ["## Delimiter facts"]
        if d.code is C.SYN_MISSING_SEMICOLON:
            lines.append(f"- a {delim} is required to end the statement at rule '{d.rule}'")
            lines.append(f"- the compiler places the insertion point at line {d.line}, column {d.column}")
            if d.found and d.found["line"] != d.line:
                lines.append(f"- it only noticed at line {d.found['line']} because the next token "
                             f"({d.found['description']}) cannot continue the statement")
        else:
            lines.append(f"- missing closing delimiter: {delim}")
            for r in d.related:
                lines.append(f"- its opening partner: {r.message} at line {r.line}, column {r.column}")
            if d.found:
                lines.append(f"- the parser reached {d.found['description']} at line {d.found['line']}, "
                             f"column {d.found['column']} while the opener was still unclosed")
            lines.append("- decide whether the closer is missing or the opener is extra; "
                         "prefer the reading that matches the indentation and intent")
        return "\n".join(lines)


class PromptSyntaxGeneral(PromptTemplate):
    name = "PromptSyntaxGeneral"
    codes = frozenset({C.SYN_EXPECTED_EXPRESSION, C.SYN_EXPECTED_IDENTIFIER, C.SYN_EXPECTED_TYPE,
                       C.SYN_INVALID_ASSIGNMENT_TARGET, C.SYN_UNEXPECTED_EOF, C.SYN_UNEXPECTED_TOKEN,
                       C.LEX_UNEXPECTED_CHAR, C.LEX_UNTERMINATED_COMMENT})
    focus = ("Explain which grammar rule was violated, in terms of what the student was trying to "
             "write, and repair the statement with the smallest edit.")

    def specific(self, ctx: ErrorContext) -> str:
        d = ctx.diagnostic
        lines = ["## Grammar facts"]
        if d.rule:
            lines.append(f"- the parser was inside rule '{d.rule}' when it failed")
        if d.code is C.SYN_INVALID_ASSIGNMENT_TARGET:
            lines.append("- only a plain variable name may appear on the left of '='; "
                         "the student may have meant '==' (comparison)")
        if d.code in (C.LEX_UNEXPECTED_CHAR, C.LEX_UNTERMINATED_COMMENT):
            lines.append("- this is a lexical error: the character sequence is not a Toy-C token at all")
        return "\n".join(lines) + "\n\n" + self._symbols_section(ctx, "Declarations seen before the error")


class PromptUndeclaredVariable(PromptTemplate):
    name = "PromptUndeclaredVariable"
    codes = frozenset({C.SEM_UNDECLARED_VARIABLE, C.SEM_DUPLICATE_DECLARATION})
    focus = ("Decide whether this is a typo of a variable that IS in scope, a variable declared in a "
             "different scope, or a genuinely missing declaration, and fix accordingly.")

    def specific(self, ctx: ErrorContext) -> str:
        d = ctx.diagnostic
        name = d.details.get("name", "?")
        lines = ["## Name-resolution facts"]
        if d.code is C.SEM_UNDECLARED_VARIABLE:
            lines.append(f"- '{name}' is not declared in the current scope or any enclosing scope")
            if d.details.get("suggestion"):
                lines.append(f"- closest in-scope name by spelling: '{d.details['suggestion']}'")
            lines.append("- variables must be declared before use; a variable declared inside a "
                         "block { } is not visible after the block ends")
        else:
            lines.append(f"- '{name}' was already declared in the same scope at line "
                         f"{d.details.get('previous_line')} as a {d.details.get('previous_kind')} "
                         f"of type '{d.details.get('previous_type')}'")
            lines.append("- the student probably meant to assign to the existing variable, or to use a new name")
        return "\n".join(lines) + "\n\n" + self._symbols_section(ctx, "Symbols in scope at the error")


class PromptTypeMismatch(PromptTemplate):
    name = "PromptTypeMismatch"
    codes = frozenset({C.SEM_TYPE_MISMATCH, C.SEM_RETURN_MISMATCH, C.SEM_INVALID_VOID})
    focus = ("Explain which value has the wrong type and what type was required there, then fix it "
             "with an explicit comparison, a corrected declaration, or a corrected return.")

    def specific(self, ctx: ErrorContext) -> str:
        d = ctx.diagnostic
        det = d.details
        lines = ["## Type facts"]
        if "expected_type" in det:
            lines.append(f"- required type: {det['expected_type']}")
        if "actual_type" in det:
            lines.append(f"- inferred type of the offending expression: {det['actual_type']}")
        if "context" in det:
            lines.append(f"- where: {det['context']}")
        if "operator" in det:
            lines.append(f"- operator: '{det['operator']}' (left operand: {det.get('left_type', '?')}, "
                         f"right operand: {det.get('right_type', '?')})")
        if "function" in det:
            lines.append(f"- enclosing/target function: {det['function']}")
        lines.append("- typing rules: + - * / % and unary - need int; < <= > >= need int and give bool; "
                     "== != need equal types; && || ! need bool; if/while conditions must be bool")
        return "\n".join(lines) + "\n\n" + self._symbols_section(ctx, "Symbols in scope at the error")


class PromptUndefinedFunction(PromptTemplate):
    name = "PromptUndefinedFunction"
    codes = frozenset({C.SEM_UNDEFINED_FUNCTION, C.SEM_ARGUMENT_MISMATCH, C.SEM_NOT_CALLABLE})
    focus = ("Explain the mismatch between the call and the available function definitions, then fix "
             "the call (name, argument count or argument types) rather than rewriting the function.")

    def specific(self, ctx: ErrorContext) -> str:
        d = ctx.diagnostic
        det = d.details
        lines = ["## Call facts"]
        if d.code is C.SEM_UNDEFINED_FUNCTION:
            lines.append(f"- no function named '{det.get('name')}' exists")
            if det.get("suggestion"):
                lines.append(f"- closest defined function by spelling: '{det['suggestion']}'")
            lines.append(f"- argument types at the call: {det.get('arg_types')}")
        elif d.code is C.SEM_ARGUMENT_MISMATCH:
            lines.append(f"- callee signature: {det.get('signature')}")
            if "expected_count" in det:
                lines.append(f"- expected {det['expected_count']} argument(s) of types "
                             f"{det.get('expected_types')}, got {det['actual_count']} of types {det.get('arg_types')}")
            else:
                lines.append(f"- argument {det.get('position')} ('{det.get('parameter')}') must be "
                             f"{det.get('expected_type')} but is {det.get('actual_type')}")
        else:
            lines.append(f"- '{det.get('name')}' is a variable of type {det.get('actual_type')}, not a function")
        functions = [s for s in ctx.symbols if s.get("kind") == "function"]
        if functions:
            lines.append("- defined functions: " + "; ".join(s["signature"] for s in functions))
        return "\n".join(lines) + "\n\n" + self._symbols_section(ctx, "Symbols in scope at the error")


class PromptGenericBaseline(PromptTemplate):
    """Control condition: a single prompt for every error, given only flattened text."""
    name = "PromptGenericBaseline"
    focus = "Explain the error and fix it."

    def build(self, ctx: ErrorContext) -> Prompt:
        d = ctx.diagnostic
        flat = f"{d.filename}:{d.line}:{d.column}: error: {d.message}"
        user = (f"The following program fails to compile.\n\n"
                f"Compiler output:\n{flat}\n\n"
                f"Program:\n{ctx.source}\n\n"
                f"Task: {self.focus}\n\n{_RESPONSE_INSTRUCTIONS}")
        return Prompt(self.name, SYSTEM_INSTRUCTION, user, d.code.value)


TYPED_TEMPLATES: tuple[PromptTemplate, ...] = (
    PromptSyntaxMissingDelimiter(), PromptSyntaxGeneral(), PromptUndeclaredVariable(),
    PromptTypeMismatch(), PromptUndefinedFunction(),
)
GENERIC_TEMPLATE = PromptGenericBaseline()

_DISPATCH: dict[ErrorCode, PromptTemplate] = {
    code: tpl for tpl in TYPED_TEMPLATES for code in tpl.codes
}


def select_template(code: ErrorCode, mode: str = "typed") -> PromptTemplate:
    """Return the template for ``code``; ``mode='generic'`` forces the baseline."""
    if mode == "generic":
        return GENERIC_TEMPLATE
    if mode != "typed":
        raise ValueError("mode must be 'typed' or 'generic'")
    return _DISPATCH.get(code, PromptSyntaxGeneral())


def build_prompt(ctx: ErrorContext, mode: str = "typed") -> Prompt:
    return select_template(ctx.diagnostic.code, mode).build(ctx)


def schema_json() -> str:
    return json.dumps(RESPONSE_SCHEMA, indent=2)
