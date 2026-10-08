# Project Implementation Guide & Architecture Documentation

**Course:** BCSE307L — Compiler Design  
**Project:** LLM-Assisted Compiler Error Diagnosis and Repair Tool  
**Student:** Namish (3rd Year CSE)

---

## 1. Executive Summary & Architecture

The objective of this project is to bridge compiler front-end internals with Large Language Models (LLMs) to provide clear, actionable explanations and verified fixes for compilation errors.

Unlike conventional tools that scrape compiler error text from `stderr` as a black box, this project implements a custom compiler front-end where every error is modeled as an enriched, typed `Diagnostic` object directly at the moment it is raised.

### System Architecture Pipeline

```
                                  +-----------------------------------------------+
                                  |                 Source Code                   |
                                  +-----------------------------------------------+
                                                          |
                                                          v
                                  +-----------------------------------------------+
                                  |         Stage 1: DFA-Driven Lexer             |
                                  |  - Regex -> NFA -> DFA -> Minimal DFA         |
                                  |  - Line/Col/Span tracking                     |
                                  |  - Early Lexical Diagnostic emission          |
                                  +-----------------------------------------------+
                                                          |
                                           [Token Stream with Spans]
                                                          |
                                                          v
                                  +-----------------------------------------------+
                                  |    Stage 2: Recursive-Descent Parser          |
                                  |  - EBNF grammar implementation                |
                                  |  - Live rule-stack tracker                    |
                                  |  - Panic-mode boundary synchronization        |
                                  +-----------------------------------------------+
                                           /                             \
                                          /                               \
                                         v                                 v
                +---------------------------------+      +---------------------------------+
                |      Abstract Syntax Tree       |      |   Structured Syntax Diagnostic  |
                |  (Program, Function, Stmt, Expr)|      |  - Error code & category        |
                +---------------------------------+      |  - Expected / Found tokens      |
                                                         |  - Grammar rule stack trace     |
                                                         |  - Related opener locations     |
                                                         +---------------------------------+
                                                                          |
                                                                          v
[Phase 2 Ready]                                          +---------------------------------+
                                                         |  Stage 3: Semantic Analysis     |
                                                         |  - Symbol table & Scope tree    |
                                                         |  - Type checking & resolution   |
                                                         +---------------------------------+
                                                                          |
                                                                          v
[Phase 2 Ready]                                          +---------------------------------+
                                                         | Stage 4: Typed LLM Prompting    |
                                                         |  - Error-type prompt dispatch   |
                                                         |  - Automated fix verification   |
                                                         +---------------------------------+
```

---

## 2. Phase 1 Implementation Walkthrough

Phase 1 provides the foundational 25% implementation: the lexical analyzer, recursive-descent parser, and structured error reporting engine.

### 2.1 Lexical Analysis (`toyc/regex_dfa.py` & `toyc/lexer.py`)

Rather than relying on high-level Python libraries, the tokenizer is implemented using foundational automata theory from the ground up:

1. **Regular Expression Parsing:**  
   `_RegexParser` converts regex strings into an explicit AST (`CharSet`, `Concat`, `Alt`, `Star`, `Plus`, `Opt`, `Epsilon`).
2. **Thompson's Construction:**  
   `_thompson()` builds an $\epsilon$-NFA graph. Each token rule's accept state is labeled with a priority rank `(priority, token_name)`.
3. **Subset Construction:**  
   `nfa_to_dfa()` calculates the $\epsilon$-closure to convert the non-deterministic automaton to deterministic states. When multiple tokens could match, the lowest priority index (order in specification) breaks ties—allowing keywords (e.g. `if`, `while`) to take precedence over identifiers.
4. **Moore's Partition Refinement:**  
   `minimize()` partitions states based on output signatures, generating the minimal DFA (reducing our token matcher to an optimal 67 states).
5. **Maximal-Munch Tokenizer:**  
   `Lexer.tokenize()` greedily consumes input using the DFA until no transition is possible, recording the furthest accepting position.
6. **Span & Source Tracking:**  
   Calculates 1-based `line`, `column`, `end_line`, and `end_column` using newline index bisecting (`bisect_right`).

### 2.2 Grammar & Parsing (`toyc/ast_nodes.py` & `toyc/parser.py`)

The recursive-descent parser directly mirrors the formal EBNF grammar defined in `docs/grammar.ebnf`:

1. **Explicit Operator Precedence:**  
   Expressions are broken into distinct grammar layers to enforce precedence without ambiguity:
   $$\text{assignment} \to \text{logic\_or} \to \text{logic\_and} \to \text{equality} \to \text{comparison} \to \text{term} \to \text{factor} \to \text{unary} \to \text{call} \to \text{primary}$$
2. **Grammar Rule Stack Tracking:**  
   Using a Python context manager (`with self.rule("function_decl"):`), the parser maintains an active `rule_stack`. If an error occurs, the exact nested grammatical path is preserved (e.g., `program > declaration > function_decl > block > statement > var_decl`).
3. **Delimiter Opener Tracking:**  
   When matching delimiters (`( ... )`, `{ ... }`), the opening token is tracked. If the closing delimiter is missing, the diagnostic references both the missing token and the line/column where the delimiter was opened.
4. **Panic-Mode Error Recovery:**  
   When a syntax error occurs, a `_ParseAbort` exception unwinds parsing to either `_synchronize_statement()` or `_synchronize_declaration()`. The parser skips corrupt tokens until reaching a boundary token (`;`, `}`, or a keyword), allowing multiple independent errors to be diagnosed in a single pass.

### 2.3 Structured Diagnostics (`toyc/errors.py`)

Instead of raising uncaught exceptions or printing bare strings, diagnostics are modeled as structured objects:

```json
{
  "category": "syntax",
  "code": "SYN_MISSING_SEMICOLON",
  "message": "expected ';' after variable declaration, found keyword 'int'",
  "location": {
    "file": "examples/err_missing_semicolon.toy",
    "line": 3,
    "column": 18,
    "end_column": null
  },
  "expected": [ "';'" ],
  "found": {
    "type": "INT",
    "lexeme": "int",
    "line": 4,
    "column": 5,
    "description": "keyword 'int'"
  },
  "rule": "var_decl",
  "rule_stack": [
    "program",
    "declaration",
    "function_decl",
    "block",
    "statement",
    "var_decl"
  ],
  "source_line": "    int count = 5",
  "hint": "insert ';' after variable declaration",
  "related": []
}
```

---

## 3. Step-by-Step Guide to Implement the Project

This section details how to develop the complete system from scratch across both phases.

### Step 1: Lexical Specification & Automata Engine
- [x] **Define Token Types:** Enumerate keywords, identifiers, numeric literals, multi-char operators (`==`, `!=`, `<=`, `>=`, `&&`, `||`), single-char symbols, and `EOF`.
- [x] **Implement Automata Builders:**
  - Build a regex AST parser.
  - Implement Thompson's NFA construction.
  - Implement subset construction for DFA conversion.
  - Implement Moore's partition refinement for state minimization.
- [x] **Build Tokenizer:** Implement maximal-munch matching, skip whitespace/comments, and track line/column offsets.

### Step 2: AST Nodes and EBNF Grammar
- [x] **Formalize EBNF:** Specify program structure, statements (`var_decl`, `if`, `while`, `return`, `expr_stmt`), and expression precedence hierarchy.
- [x] **Define AST Data Classes:** Create structured dataclasses for nodes (`Program`, `FunctionDecl`, `VarDecl`, `Block`, `If`, `While`, `Return`, `Assign`, `Binary`, `Unary`, `Call`, `IntLiteral`, `BoolLiteral`, `Identifier`).
- [x] **Build AST Visualizer:** Implement ASCII tree indentation and JSON export.

### Step 3: Recursive-Descent Parser & Error Recovery
- [x] **Implement Grammar Rules:** Write a parsing function corresponding to each non-terminal in the EBNF grammar.
- [x] **Implement Contextual Stack:** Track the current active rule hierarchy during descent.
- [x] **Implement Intelligent Error Detection:**
  - Delimiter matching with opener reference.
  - Semicolon detection with lookahead to place the caret after the prior token.
  - Invalid assignment target detection (e.g., `5 = x` vs `5 == x`).
  - Reserved keyword and malformed identifier detection.
- [x] **Implement Panic-Mode Synchronization:** Recover at statement boundaries (`;`, `}`) and declaration boundaries.

### Step 4: CLI and Phase 1 Validation
- [x] **Build CLI:** Support commands:
  - `run <file>`: Standard compilation with colorized diagnostics.
  - `run <file> --tokens`: Inspect token sequence.
  - `run <file> --ast`: Inspect abstract syntax tree.
  - `run <file> --json`: Output full structured JSON diagnostics.
  - `dfa-stats`: Display automaton metrics.
- [x] **Write Unit Test Suite:** Verify DFA minimization, lexer edge cases, operator precedence, and diagnostic reporting.

---

### Step 5: Semantic Analysis (Phase 2 — Next Step)
*To be implemented in Week 3:*

1. **Symbol Table & Scopes:**
   - Create a `SymbolTable` class supporting nested lexical scopes (`Scope` stack).
   - Record variable names, types (`int`, `bool`, `void`), declaration locations, and function signatures (parameters + return types).
2. **Semantic Checks:**
   - **Undeclared Variables:** Flag variable usage without prior declaration in current or enclosing scopes (`SEM_UNDECLARED_VARIABLE`).
   - **Duplicate Declarations:** Flag redeclaring an identifier in the same scope (`SEM_DUPLICATE_DECLARATION`).
   - **Type Checking:** Ensure operands to `+`, `-`, `*`, `/`, `%` are integer; condition in `if`/`while` is boolean; assignment types match (`SEM_TYPE_MISMATCH`).
   - **Function Signature Validation:** Verify argument count and parameter types on calls (`SEM_ARGUMENT_MISMATCH`, `SEM_UNDEFINED_FUNCTION`).
3. **Emit Semantic Diagnostics:**
   - Integrate semantic errors into the identical `Diagnostic` schema used by syntax errors.

### Step 6: Error-Context Extraction & LLM Integration
*To be implemented in Week 3 & 4:*

1. **Context Extraction Engine:**
   - On error, slice surrounding source code lines (e.g., 3 lines before and after).
   - Extract the local symbol table snapshot (declared variables and their types in scope).
2. **Error-Type-Specific Prompt Templates:**
   - Implement distinct prompt templates rather than a generic prompt:
     - `PromptSyntaxMissingDelimiter`: Injects opener line/col and expected delimiter.
     - `PromptUndeclaredVariable`: Injects active symbols in scope to suggest typos or missing declarations.
     - `PromptTypeMismatch`: Injects expected operand types and inferred sub-expression types.
     - `PromptGenericBaseline`: Generic prompt used as the control for ablation study.
3. **LLM Client Integration:**
   - Connect to LLM API (e.g., Gemini API via `google-genai`).
   - Send formatted structured diagnostic + extracted context.
   - Parse response for plain-English explanation and concrete patch/fix code.

### Step 7: Automated Fix Verification Layer
*To be implemented in Week 4:*

1. **In-Memory Recompilation:**
   - Take the LLM's suggested code patch and substitute it into the source buffer.
   - Pass the patched source back into `compile_source()`.
2. **Verification Status Tagging:**
   - If the patched code compiles without errors $\implies$ mark diagnostic as `[VERIFIED FIX]`.
   - If new errors are generated $\implies$ mark as `[UNVERIFIED - FIX FAILED]`.

### Step 8: Evaluation Suite & Comparative Study
*To be implemented in Week 4:*

1. **Curate Benchmark Dataset:**
   - Assemble 15–20 benchmark buggy programs covering syntax errors, undeclared variables, type mismatches, and operator precedence confusion.
2. **Run Comparative Evaluations:**
   - **Evaluation 1:** Toy-C Structured Output vs. Raw GCC/Clang `stderr` diagnostics.
   - **Evaluation 2 (Ablation Study):** Error-type-specific prompting vs. Generic single-prompt baseline.
3. **Evaluation Metrics:**
   - Explanation clarity & novice readability (rubric-scored).
   - Fix verification success rate (% of code suggestions that compile clean).

---

## 4. Verification and Quick Commands

Run these commands in the terminal to verify the current Phase 1 implementation:

```bash
# 1. View DFA generation statistics (67 states, 62 accepting, 2730 transitions)
.\toycompiler.bat dfa-stats

# 2. Run valid program and inspect AST
.\toycompiler.bat run examples\valid_factorial.toy --ast

# 3. Test syntax error diagnostics with human-readable visual carets
.\toycompiler.bat run examples\err_missing_semicolon.toy

# 4. Test machine-readable JSON diagnostic output
.\toycompiler.bat run examples\err_unbalanced_paren.toy --json

# 5. Run full test suite (43 tests passing)
python -m unittest discover -s tests -v
```
