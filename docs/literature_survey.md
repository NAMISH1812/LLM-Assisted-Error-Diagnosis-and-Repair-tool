# Literature Survey & Problem Statement

**Course:** BCSE307L — Compiler Design  
**Project:** LLM-Assisted Compiler Error Diagnosis and Repair Tool  
**Phase:** 1 (Review 1 Deliverable)

---

## 1. Problem Identification

Modern production compilers (such as GCC, Clang, or rustc) are engineered primarily for code generation efficiency, strict conformance, and optimization rather than pedagogical guidance. Consequently, their diagnostics report terse, rule-level syntactic violations (e.g., `error: expected ';' before '}' token` or `error: incompatible types in assignment`).

While these messages identify the token location where a formal grammatical rule was violated:
1. **Misleading Locations:** Syntax violations frequently misreport the point of failure (e.g., cascading errors caused by missing braces or missing semicolons attributed to the subsequent line).
2. **Cognitive Burden on Novices:** Beginners struggle to mental-model *why* the compiler failed and *how* their mental intention diverged from the language syntax.
3. **Loss of Semantic State:** Once an error string is emitted by standard CLI compilers, the internal grammatical rule stack, token lookahead state, and symbol table slices are discarded.

---

## 2. Literature Survey

Recent research has explored Large Language Models (LLMs) to demystify compilation errors and provide automated program repair (APR). However, existing works exhibit fundamental architectural gaps:

### 2.1 CodeHelp: Using Large Language Models with Guardrails for Novice Programming (Lau et al., 2023)
- **Summary:** CodeHelp introduces an in-IDE assistant providing explanations and hints for novice programmers, relying on general-purpose prompts and teacher guardrails to prevent direct code generation.
- **Limitation & Gap:** CodeHelp operates at the user/IDE level. It relies exclusively on the raw error text copied or intercepted from standard compilers, missing compiler-internal state and failing to automate verification of suggested fixes.

### 2.2 LLM-Based Automated Program Repair for Compiler Errors (Ahmed et al., 2023 / Joshi et al., 2023)
- **Summary:** Explores GPT-3.5/4 and specialized models to repair syntax and type errors in introductory C and Python benchmarks (e.g., DeepFix, TRACER benchmarks).
- **Limitation & Gap:** Most APR benchmarks treat the compiler as a monolithic "black box". They feed the source code and the compiler's textual stderr output into the LLM. In doing so, grammatical rule paths, expected token sets, and typed taxonomy are lost before prompting. Furthermore, most systems use a single uniform prompt across all error types.

### 2.3 RustAssistant & Rust Compiler Diagnostics Enhancements (2022–2024)
- **Summary:** The Rust compiler (`rustc`) is known for the most human-friendly diagnostics in the industry, utilizing sub-diagnostics, help/note spans, and compiler-generated suggestions. Recent tools pair rustc output with LLMs.
- **Limitation & Gap:** Even with rich diagnostics, tools still scrape the rendered JSON/stderr stream. When applying LLMs to repairs, they do not dynamically tailor prompt schemas based on whether the issue is a token mismatch, delimiter imbalance, or scope visibility issue.

### 2.4 Prompt Engineering in APR: Generic vs. Typed Prompting
- **Summary:** Studies in prompt engineering demonstrate that few-shot examples and task-specific contextual framing significantly boost generation fidelity. However, in compiler repair pipelines, prior works defaulted to one generic system prompt ("You are a debugging assistant; fix this code") to minimize system complexity.
- **Limitation & Gap:** The empirical difference between generic prompt baselines and structured, error-type-specific prompt templates remains largely unmeasured and under-explored in custom compiler front-ends.

---

## 3. Gap Analysis & Proposed Novelty

| Dimension | Existing Approaches (e.g., Black-Box Wrappers) | This Project (LLM-Assisted Diagnosis & Repair) |
|---|---|---|
| **Compiler Architecture** | Wrapper around external compiler (GCC/Clang) | **Custom Front-End:** Full control over lexer, parser, AST, and symbol table. |
| **Diagnostic Representation** | Plain unstructured text strings from stderr | **First-Class Diagnostic Objects:** Typed enum codes, rule stacks, expected token sets, span ranges, and related opener locations. |
| **Prompt Engineering** | Uniform, generic prompt for all error categories | **Error-Type-Specific Prompting:** Dedicated prompt templates dispatched by structured error type (`SYN_MISSING_SEMICOLON`, `SYN_UNBALANCED_DELIMITER`, etc.). |
| **Fix Verification** | Manual compilation or none | **Automated In-Pipeline Verification:** Re-compiles suggested fixes through the internal compiler to verify error resolution before user presentation. |

---

## 4. Phase 1 Architecture Overview

```
Source Code (.toy)
       │
       ▼
┌──────────────┐
│  Regex -> DFA│  Token patterns: keywords, identifiers, literals, operators
│    Lexer     │  Tracks (line, col, end_col), emits Token stream
└──────┬───────┘
       │ [LexResult]
       ├── (If Lexical Error) ──► Structured Lexical Diagnostic (halts early)
       ▼
┌──────────────┐
│  Recursive-  │  EBNF recursive-descent parser with live rule-stack context
│   Descent    │  Panic-mode synchronization at statement/declaration boundaries
│    Parser    │
└──────┬───────┘
       │
       ├──► AST Tree (Program, FunctionDecl, VarDecl, Block, Expr)
       └──► Structured Syntax Diagnostics (ErrorCode, expected, found, rule_stack, related)
```
