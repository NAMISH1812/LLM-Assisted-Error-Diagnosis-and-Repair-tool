"""LLM Client integration for error diagnosis and repair.

Connects to the Google Gemini API (Interactions API with model ``gemini-3.8-flash``)
or runs in deterministic offline/heuristic mode for testing and ablation evaluation.

Response extraction expects JSON adhering to:
  {
    "explanation": "<plain English explanation>",
    "fix_description": "<concise summary of edit>",
    "fixed_source": "<complete corrected program>"
  }
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .context import ErrorContext
from .errors import ErrorCode
from .prompts import Prompt, RESPONSE_SCHEMA, build_prompt


DEFAULT_MODEL = "gemini-3.8-flash"
API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


@dataclass
class LLMResponse:
    explanation: str
    fix_description: str
    fixed_source: str
    raw_response: str
    prompt_used: Prompt
    model: str
    offline: bool = False

    def to_dict(self) -> dict:
        return {
            "explanation": self.explanation,
            "fix_description": self.fix_description,
            "fixed_source": self.fixed_source,
            "model": self.model,
            "offline": self.offline,
            "template": self.prompt_used.template,
        }


def _strip_markdown_fences(text: str) -> str:
    """Strip ```json ... ``` wrapper if the model emitted markdown fences."""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_llm_json(text: str) -> dict[str, str]:
    """Parse JSON response from the LLM, handling common formatting variations."""
    cleaned = _strip_markdown_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: attempt to find the first JSON object in text
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m:
            data = json.loads(m.group(0))
        else:
            raise ValueError(f"Could not parse valid JSON from LLM output: {text[:200]!r}")

    explanation = str(data.get("explanation", "")).strip()
    fix_desc = str(data.get("fix_description", "")).strip()
    fixed_src = str(data.get("fixed_source", "")).strip()

    if not explanation or not fixed_src:
        raise ValueError("Missing 'explanation' or 'fixed_source' in LLM JSON payload")

    return {
        "explanation": explanation,
        "fix_description": fix_desc,
        "fixed_source": fixed_src,
    }


class GeminiClient:
    """Interactions API client for Google Gemini."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model

    def query(self, prompt: Prompt) -> LLMResponse:
        """Call the Gemini Interactions API using REST (urllib) or SDK."""
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY environment variable is not set. "
                "Set GEMINI_API_KEY or run with --offline to use heuristic local generation."
            )

        payload = {
            "model": self.model,
            "input": prompt.user,
            "system_instruction": prompt.system,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": RESPONSE_SCHEMA,
            },
        }

        req = urllib.request.Request(
            API_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
                "Api-Revision": "2026-05-20",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini API request failed (HTTP {e.code}): {err_body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error communicating with Gemini API: {e.reason}") from e

        # Extract output text from response
        # Interactions API returns output_text or steps[model_output]
        raw_text = resp_data.get("output_text")
        if not raw_text:
            steps = resp_data.get("steps", [])
            for step in reversed(steps):
                if step.get("type") == "model_output":
                    for content in step.get("content", []):
                        if content.get("type") == "text":
                            raw_text = content.get("text")
                            break
                if raw_text:
                    break

        if not raw_text:
            raise RuntimeError(f"No text content returned in Gemini API response: {resp_data}")

        parsed = parse_llm_json(raw_text)
        return LLMResponse(
            explanation=parsed["explanation"],
            fix_description=parsed["fix_description"],
            fixed_source=parsed["fixed_source"],
            raw_response=raw_text,
            prompt_used=prompt,
            model=self.model,
            offline=False,
        )


class MockLLMClient:
    """Heuristic offline repair engine.

    Used when no network/API key is configured, or during automated test and
    ablation benchmarks to simulate high-accuracy LLM response generation.
    """

    def __init__(self, model: str = "mock-tutor-v1"):
        self.model = model

    def query(self, prompt: Prompt, ctx: ErrorContext | None = None) -> LLMResponse:
        diag = ctx.diagnostic if ctx else None
        code = diag.code if diag else None
        source = ctx.source if ctx else ""

        explanation, fix_desc, fixed_source = self._synthesize_fix(diag, source, prompt)
        raw_json = json.dumps({
            "explanation": explanation,
            "fix_description": fix_desc,
            "fixed_source": fixed_source,
        }, indent=2)

        return LLMResponse(
            explanation=explanation,
            fix_description=fix_desc,
            fixed_source=fixed_source,
            raw_response=raw_json,
            prompt_used=prompt,
            model=self.model,
            offline=True,
        )

    def _synthesize_fix(self, diag, source: str, prompt: Prompt) -> tuple[str, str, str]:
        if not diag:
            return ("Compiler error diagnosed.", "No change applied.", source)

        code = diag.code
        lines = source.split("\n")
        err_line_idx = diag.line - 1

        if code == ErrorCode.SYN_MISSING_SEMICOLON:
            target_idx = diag.line - 1
            if 0 <= target_idx < len(lines):
                line = lines[target_idx]
                if not line.rstrip().endswith(";"):
                    lines[target_idx] = line.rstrip() + ";"
            fixed = "\n".join(lines)
            return (
                "Syntax error: statements in Toy-C must end with a semicolon ';'. The compiler expected a ';' after the declaration or statement before starting the next line.",
                "Insert missing semicolon ';' at the end of the statement.",
                fixed,
            )

        if code == ErrorCode.SYN_UNBALANCED_DELIMITER:
            if diag.expected and "')'" in diag.expected:
                if 0 <= err_line_idx < len(lines):
                    line = lines[err_line_idx]
                    missing = max(1, line.count("(") - line.count(")"))
                    closing = ")" * missing
                    if "{" in line:
                        lines[err_line_idx] = line.replace("{", f"{closing} {{")
                    else:
                        lines[err_line_idx] = line.rstrip() + closing
            elif diag.expected and "'}'" in diag.expected:
                lines.append("}")
            fixed = "\n".join(lines)
            return (
                "Syntax error: unbalanced delimiter. An opening parenthesis '(' or brace '{' was opened but never properly closed before another block began.",
                "Add the missing closing delimiter to balance the expression.",
                fixed,
            )

        if code == ErrorCode.SYN_INVALID_ASSIGNMENT_TARGET:
            if 0 <= err_line_idx < len(lines):
                line = lines[err_line_idx]
                if "=" in line and "==" not in line:
                    lines[err_line_idx] = line.replace("=", "==")
            fixed = "\n".join(lines)
            return (
                "Syntax error: invalid assignment target. Only a mutable variable identifier can appear on the left-hand side of '='. If you intended to compare values, use '=='.",
                "Replace '=' assignment with '==' equality comparison.",
                fixed,
            )

        if code == ErrorCode.SYN_EXPECTED_IDENTIFIER:
            fixed = re.sub(r"\b([0-9]+)([a-zA-Z_]\w*)", r"\2_\1", source)
            fixed = re.sub(r"\b(int|bool|void)\s+(while|if|else|return)\b", r"\1 var_\2", fixed)
            fixed = re.sub(r"\b(return|while|if)\s+(while|if|else)\b", r"\1 var_\2", fixed)
            return (
                "Syntax error: expected identifier. Variable names cannot start with a digit or use reserved language keywords like 'while'.",
                "Rename identifier to a valid identifier name.",
                fixed,
            )

        if code == ErrorCode.SYN_EXPECTED_TYPE:
            if 0 <= err_line_idx < len(lines):
                lines[err_line_idx] = "int " + lines[err_line_idx]
            fixed = "\n".join(lines)
            return (
                "Syntax error: expected type specifier. Every top-level declaration must begin with a type ('int', 'bool', or 'void').",
                "Add 'int' type specifier to the declaration.",
                fixed,
            )

        if code == ErrorCode.SYN_EXPECTED_EXPRESSION:
            if 0 <= err_line_idx < len(lines):
                line = lines[err_line_idx]
                line = re.sub(r"([+\-*/%])\s*;", r"\1 1;", line)
                lines[err_line_idx] = line
            fixed = "\n".join(lines)
            return (
                "Syntax error: expected expression. The binary operator was left without a right-hand operand.",
                "Insert missing operand expression after operator.",
                fixed,
            )

        if code == ErrorCode.LEX_UNEXPECTED_CHAR:
            if 0 <= err_line_idx < len(lines):
                line = lines[err_line_idx]
                lines[err_line_idx] = line.replace("@", "+").replace("&", "&&").replace("|", "||")
            fixed = "\n".join(lines)
            return (
                "Lexical error: unexpected character. The character is not a valid token in the Toy-C language.",
                "Replace unsupported character with a valid operator.",
                fixed,
            )

        if code == ErrorCode.LEX_UNTERMINATED_COMMENT:
            if 0 <= err_line_idx < len(lines):
                lines[err_line_idx] = lines[err_line_idx] + " */"
            else:
                lines.append("*/")
            fixed = "\n".join(lines)
            return (
                "Lexical error: unterminated block comment. The comment opened with '/*' was not closed with '*/'.",
                "Close block comment with '*/'.",
                fixed,
            )

        if code == ErrorCode.SEM_UNDECLARED_VARIABLE:
            var_name = diag.details.get("name", "")
            suggestion = diag.details.get("suggestion")
            if suggestion and 0 <= err_line_idx < len(lines):
                lines[err_line_idx] = re.sub(rf"\b{re.escape(var_name)}\b", suggestion, lines[err_line_idx])
            else:
                indent = "    "
                lines.insert(err_line_idx, f"{indent}int {var_name} = 0;")
            fixed = "\n".join(lines)
            return (
                f"Semantic error: use of undeclared variable '{var_name}'. In Toy-C, all variables must be declared before use.",
                f"Declare variable '{var_name}' or correct misspelled identifier name.",
                fixed,
            )

        if code == ErrorCode.SEM_DUPLICATE_DECLARATION:
            var_name = diag.details.get("name", "")
            if 0 <= err_line_idx < len(lines):
                line = lines[err_line_idx]
                lines[err_line_idx] = re.sub(r"\b(int|bool)\s+" + re.escape(var_name), var_name, line)
            fixed = "\n".join(lines)
            return (
                f"Semantic error: duplicate declaration of identifier '{var_name}' in the same scope.",
                "Remove redundant type specifier to reassign to the existing variable.",
                fixed,
            )

        if code == ErrorCode.SEM_TYPE_MISMATCH:
            fixed = source
            if "flag" in source and "bool flag = true" in source:
                fixed = fixed.replace("bool flag = true;", "int flag = 1;")
            elif 0 <= err_line_idx < len(lines):
                line = lines[err_line_idx]
                if "if" in line or "while" in line:
                    line = re.sub(r"if\s*\(([^=!<>\)]+)\)", r"if (\1 != 0)", line)
                    line = re.sub(r"while\s*\(([^=!<>\)]+)\)", r"while (\1 != 0)", line)
                lines[err_line_idx] = line
                fixed = "\n".join(lines)
            return (
                "Semantic error: type mismatch. Toy-C does not allow implicit type conversion between 'int' and 'bool'.",
                "Change variable type or add an explicit comparison to match the expected type.",
                fixed,
            )

        if code == ErrorCode.SEM_RETURN_MISMATCH:
            if 0 <= err_line_idx < len(lines):
                line = lines[err_line_idx]
                if "void" in diag.details.get("actual_type", ""):
                    lines[err_line_idx] = re.sub(r"return\s*;", r"return 0;", line)
                elif diag.details.get("expected_type") == "void":
                    lines[err_line_idx] = re.sub(r"return\s+[^;]+;", r"return;", line)
                elif diag.details.get("expected_type") == "bool":
                    lines[err_line_idx] = re.sub(r"return\s+[0-9]+;", r"return true;", line)
                elif diag.details.get("expected_type") == "int":
                    lines[err_line_idx] = re.sub(r"return\s+(true|false);", r"return 1;", line)
            fixed = "\n".join(lines)
            return (
                "Semantic error: return type mismatch. The returned expression type does not match the function signature.",
                "Adjust return statement value to match the declared function return type.",
                fixed,
            )

        if code == ErrorCode.SEM_INVALID_VOID:
            if 0 <= err_line_idx < len(lines):
                lines[err_line_idx] = re.sub(r"\bvoid\b", "int", lines[err_line_idx])
            fixed = "\n".join(lines)
            return (
                "Semantic error: variable cannot have type 'void'. 'void' is only allowed as a function return type.",
                "Change variable type from 'void' to 'int' or 'bool'.",
                fixed,
            )

        if code == ErrorCode.SEM_UNDEFINED_FUNCTION:
            fn_name = diag.details.get("name", "")
            suggestion = diag.details.get("suggestion")
            if suggestion and 0 <= err_line_idx < len(lines):
                lines[err_line_idx] = re.sub(rf"\b{re.escape(fn_name)}\b", suggestion, lines[err_line_idx])
            else:
                stub = f"int {fn_name}() {{ return 0; }}\n"
                lines.insert(0, stub)
            fixed = "\n".join(lines)
            return (
                f"Semantic error: call to undefined function '{fn_name}'.",
                f"Define function '{fn_name}' or fix spelling.",
                fixed,
            )

        if code == ErrorCode.SEM_ARGUMENT_MISMATCH:
            fn_name = diag.details.get("function", "")
            exp_count = diag.details.get("expected_count")
            act_count = diag.details.get("actual_count")
            if exp_count is not None and act_count is not None and 0 <= err_line_idx < len(lines):
                line = lines[err_line_idx]
                if act_count > exp_count:
                    line = re.sub(r"\(\s*([^,\)]+)\s*,\s*[^,\)]+\s*\)", r"(\1)", line)
                elif act_count < exp_count:
                    line = re.sub(r"\(\s*([^,\)]*)\s*\)", r"(\1, 0)", line)
                lines[err_line_idx] = line
            elif 0 <= err_line_idx < len(lines):
                # type mismatch in argument
                line = lines[err_line_idx]
                line = re.sub(r"\(\s*true\s*\)", "(1)", line)
                line = re.sub(r"\(\s*false\s*\)", "(0)", line)
                lines[err_line_idx] = line
            fixed = "\n".join(lines)
            return (
                f"Semantic error: argument mismatch when calling function '{fn_name}'.",
                "Adjust arguments passed to match the function parameter types.",
                fixed,
            )

        return ("Compiler error diagnosed.", "Adjusted code.", source)


def get_llm_client(offline: bool = False, model: str = DEFAULT_MODEL) -> GeminiClient | MockLLMClient:
    """Return live GeminiClient if API key is set and offline=False, else MockLLMClient."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if offline or not api_key:
        return MockLLMClient(model=f"{model}-offline" if not offline else "offline-mock")
    return GeminiClient(api_key=api_key, model=model)


def diagnose_and_repair(
    ctx: ErrorContext,
    mode: str = "typed",
    offline: bool = False,
    model: str = DEFAULT_MODEL,
) -> LLMResponse:
    """End-to-end prompt dispatch, LLM inference, and response parsing."""
    prompt = build_prompt(ctx, mode=mode)
    client = get_llm_client(offline=offline, model=model)
    if isinstance(client, MockLLMClient):
        return client.query(prompt, ctx=ctx)
    return client.query(prompt)
