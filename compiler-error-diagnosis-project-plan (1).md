# LLM-Assisted Compiler Error Diagnosis and Repair Tool

**Course:** BCSE307L — Compiler Design
**Student:** Namish (3rd Year CSE)
**Timeline:** 1 month

---

## 1. Problem Description

Traditional compilers report syntax and semantic errors using terse, low-level diagnostic messages (e.g., `unexpected token ';' at line 4`) that are difficult for programmers — especially beginners — to interpret and act on. These messages describe *what* rule was violated but rarely explain *why* in terms a student can reason about, or *how* to fix it. This creates friction in debugging and increases the learning curve for students writing their first compilers' worth of code.

While recent research has explored using large language models (LLMs) to generate plain-English explanations of error messages, most existing approaches treat the compiler as a black box: they take the compiler's already-flattened error *string* as input to the LLM, after structure has been lost. This project instead builds a custom compiler front-end where error objects are structured and typed from the moment they are raised — giving the LLM richer, more precise context than a wrapper around an existing compiler like GCC or Clang can provide.

## 2. Objectives

1. Design and implement a lexer and recursive-descent parser for a C-subset toy language, producing structured syntax-error objects (not just raw error strings).
2. Implement a semantic analyzer (symbol table, type checking, undeclared-variable detection) that raises structured, typed semantic-error objects.
3. Build an error-context extraction pipeline that captures rich internal compiler state (code snippet, token information, symbol table slice) for any error raised.
4. Integrate an LLM to generate plain-English error explanations and concrete suggested fixes from this context.
5. Implement **error-type-specific prompting** — distinct prompt templates per error category (syntax, undeclared variable, type mismatch, etc.) — instead of one generic prompt for all errors.
6. Evaluate the tool against standard compiler output (GCC/Clang) and against a generic-prompt baseline, to measure whether rich structured context and typed prompting meaningfully improve explanation clarity and fix correctness.

## 3. Novelty

- **Custom front-end, not a compiler wrapper:** owning the lexer/parser/semantic analyzer means error objects are structured and typed *before* they reach the LLM, unlike tools (e.g., RustAssistant, CodeHelp-style tools) that work from a compiler's printed error text.
- **Error-type-specific prompting, measured rather than assumed:** prior work on LLM-based compiler error repair explicitly considered per-error-type prompts but opted for one general prompt for simplicity, leaving the question of whether specialization helps unanswered. This project implements it and evaluates the effect directly against a generic-prompt baseline.
- **Verifiable fixes:** because the full compiler pipeline is self-owned, a suggested fix can be re-compiled automatically to check whether it actually resolves the error before being shown to the user — a safety layer most explanation-only tools lack.

## 4. Final Outcome

A working CLI tool that:
- Compiles a program in the custom C-subset language through a custom lexer → parser → semantic analyzer pipeline.
- On any error, outputs a structured diagnostic plus an LLM-generated plain-English explanation and suggested fix, using an error-type-specific prompt.
- Automatically re-checks the suggested fix against the compiler to flag whether it is verified or unverified.
- Includes a documented evaluation: tool output vs. GCC/Clang raw errors, and typed-prompting vs. generic-prompting, on a curated set of buggy test programs.

---

## 5. Phase 1 — 25% Implementation

**Target completion:** End of Week 2 (Assessment 8 — Project Review 1)

### Scope
- Finalize the EBNF grammar for the C-subset toy language (variables, arithmetic/boolean expressions, `if`/`while`, function declarations — kept intentionally small).
- Implement the **lexer**: regex-to-DFA based tokenizer with line/column tracking.
- Implement the **parser skeleton**: recursive-descent parser producing a basic AST for expressions and core statements.
- Structured **syntax-error objects**: line, column, expected vs. found token, failed grammar rule — captured instead of raw crashes.
- Minimal CLI: `./toycompiler run <file>` tokenizes and parses a file, printing success or a structured error object.
- Literature survey, problem statement, and novelty writeup.

### Week-by-Week

| Week | Tasks |
|---|---|
| 1 | Finalize grammar; implement lexer; unit tests on tokenization edge cases |
| 2 | Implement recursive-descent parser for expressions + core statements; structured syntax-error capture; literature survey & problem statement writeup; prepare Review 1 presentation |

### Review 1 Checklist
- [ ] Problem identification & objectives
- [ ] Literature survey (4–5 cited works + gap analysis)
- [ ] Novelty — custom front-end + typed-prompting direction articulated
- [ ] 25% implementation — lexer + parser demonstrably working on sample programs, producing structured error objects
- [ ] Presentation & Q&A — architecture diagram + live demo on 2–3 sample programs, including one with a syntax error

---

## 6. Phase 2 — 75% Implementation

**Target completion:** Week 3 (progress) → Week 4 (full completion, Assessments 9 & 10)

### Scope
- **Semantic analyzer:** symbol table construction, undeclared-variable detection, basic type checking — raising structured, typed semantic-error objects in the same schema as syntax errors.
- **Unified error-context pipeline:** a single schema across syntax/semantic errors — error type, message, line/column, surrounding code snippet, relevant symbol table slice.
- **LLM integration with error-type-specific prompting:** a small library of prompt templates (syntax, undeclared variable, type mismatch, undefined function), dispatched by the error's known type.
- **Fix verification layer:** re-compile the LLM's suggested fix through the same pipeline to confirm it resolves the error before presenting it as verified.
- **Evaluation suite:** ~15–20 curated buggy programs run through:
  - This tool vs. raw GCC/Clang error messages (explanation clarity, fix correctness)
  - Typed prompting vs. a generic single-prompt baseline (ablation study)
- **Final documentation:** README, architecture write-up, evaluation results, individual contribution summary.
- **Demo:** CLI (or lightweight UI) for live demonstration.

### Week-by-Week

| Week | Tasks |
|---|---|
| 3 | Implement semantic analyzer; unify error schema; build error-context extractor; integrate LLM API with error-type-specific prompts; manual prompt iteration on real errors |
| 4 | Implement fix-verification layer; build evaluation set of buggy programs; run GCC/Clang comparison and typed-vs-generic-prompt ablation; write final report/documentation; prepare demo and final presentation |

### Review 2 Checklist
- [ ] 75% implementation — semantic analyzer + unified error pipeline + typed LLM prompting working end-to-end
- [ ] Documentation/progress report
- [ ] Presentation & Q&A — live demo on 3–4 programs covering syntax + semantic errors

### Final Review Checklist
- [ ] 100% project completion & demo — full pipeline with fix verification, polished CLI
- [ ] Individual contribution documented
- [ ] Outcome — evaluation results (GCC/Clang comparison + typed-prompting ablation) written up in a short report/paper format suitable as a manuscript/extended abstract

---

## 7. Risk & Scope Management

- Keep the grammar small — a focused subset is enough to generate varied, interesting errors without ballooning parser complexity.
- Budget real time for prompt iteration in Week 3 — this is usually the difference between mediocre and strong explanations.
- Start collecting buggy test programs as soon as the semantic analyzer is stable (early Week 4), not at the last minute — the evaluation is what makes the novelty claim credible.
- Fix-verification is simple plumbing on top of the existing pipeline — low risk, high payoff for the live demo.

---

## 8. Summary Timeline

| Phase | Weeks | % Implementation | Assessment |
|---|---|---|---|
| Phase 1 | 1–2 | 25% | Assessment 8 — Project Review 1 |
| Phase 2a | 3 | → 75% | Assessment 9 — Project Review 2 |
| Phase 2b | 4 | → 100% | Assessment 10 — Project Demo & Outcome |
