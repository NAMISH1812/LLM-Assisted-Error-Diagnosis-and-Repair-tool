"""Unit tests for error-context extraction and error-type-specific prompt generation."""

import unittest

from toyc.context import extract_context
from toyc.errors import ErrorCode
from toyc.pipeline import compile_source
from toyc.prompts import (
    PromptGenericBaseline,
    PromptSyntaxMissingDelimiter,
    PromptTypeMismatch,
    PromptUndeclaredVariable,
    PromptUndefinedFunction,
    build_prompt,
    select_template,
)


class PromptAndContextTests(unittest.TestCase):
    def test_context_extraction_window(self):
        src = "int f() {\n    int a = 1;\n    int b = 2\n    return a + b;\n}\n"
        res = compile_source(src)
        self.assertFalse(res.ok)
        diag = res.diagnostics[0]
        ctx = extract_context(diag, src, res.tokens, res.diagnostics, radius=2)

        self.assertIn("> 3 |", ctx.snippet)
        self.assertIn("int b = 2", ctx.snippet)
        self.assertEqual(ctx.snippet_start, 1)

    def test_typed_prompt_dispatch(self):
        t1 = select_template(ErrorCode.SYN_MISSING_SEMICOLON)
        self.assertIsInstance(t1, PromptSyntaxMissingDelimiter)

        t2 = select_template(ErrorCode.SEM_UNDECLARED_VARIABLE)
        self.assertIsInstance(t2, PromptUndeclaredVariable)

        t3 = select_template(ErrorCode.SEM_TYPE_MISMATCH)
        self.assertIsInstance(t3, PromptTypeMismatch)

        t4 = select_template(ErrorCode.SEM_UNDEFINED_FUNCTION)
        self.assertIsInstance(t4, PromptUndefinedFunction)

        t_base = select_template(ErrorCode.SEM_TYPE_MISMATCH, mode="generic")
        self.assertIsInstance(t_base, PromptGenericBaseline)

    def test_prompt_build_contains_diagnostic_facts(self):
        src = "int main() { int counter = 10; return conter + 1; }"
        res = compile_source(src)
        diag = res.diagnostics[0]
        ctx = extract_context(diag, src, res.tokens, res.diagnostics)

        prompt = build_prompt(ctx, mode="typed")
        self.assertEqual(prompt.template, "PromptUndeclaredVariable")
        self.assertIn("SEM_UNDECLARED_VARIABLE", prompt.user)
        self.assertIn("counter", prompt.user)
        self.assertIn("closest in-scope name", prompt.user)
        self.assertIn("Symbols in scope", prompt.user)

    def test_generic_baseline_prompt_is_minimal(self):
        src = "int main() { int x = 10; return y; }"
        res = compile_source(src)
        diag = res.diagnostics[0]
        ctx = extract_context(diag, src, res.tokens, res.diagnostics)

        prompt = build_prompt(ctx, mode="generic")
        self.assertEqual(prompt.template, "PromptGenericBaseline")
        self.assertNotIn("## Structured compiler diagnostic", prompt.user)
        self.assertIn("Compiler output:\n", prompt.user)


    def test_provider_selection_and_groq_client(self):
        from toyc.llm import GroqClient, MockLLMClient, get_llm_client, parse_llm_json

        # Offline or mock
        client = get_llm_client(offline=True)
        self.assertIsInstance(client, MockLLMClient)

        client_mock = get_llm_client(provider="mock")
        self.assertIsInstance(client_mock, MockLLMClient)

        # Groq client with explicit key
        groq_client = get_llm_client(provider="groq", api_key="gsk_dummy_key_12345")
        self.assertIsInstance(groq_client, GroqClient)
        self.assertEqual(groq_client.api_key, "gsk_dummy_key_12345")
        self.assertEqual(groq_client.model, "openai/gpt-oss-120b")

        # JSON extraction parser
        sample_json = '{"explanation": "Missing semicolon", "fix_description": "Add ;", "fixed_source": "int x = 1;"}'
        parsed = parse_llm_json(sample_json)
        self.assertEqual(parsed["explanation"], "Missing semicolon")
        self.assertEqual(parsed["fixed_source"], "int x = 1;")

        # Strips markdown fences
        fence_json = '```json\n{"explanation": "A", "fix_description": "B", "fixed_source": "C"}\n```'
        parsed_fenced = parse_llm_json(fence_json)
        self.assertEqual(parsed_fenced["explanation"], "A")


if __name__ == "__main__":
    unittest.main()
