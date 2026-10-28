"""Fix verification layer.

Takes the LLM's suggested code patch or replacement source and re-compiles it
through the exact same front-end pipeline (lex -> parse -> semantic).

Checks:
1. Does the fixed code compile clean (zero errors)?
2. If errors remain, is the original error resolved, or did the fix introduce new errors?
3. Generates a readable unified diff between original source and suggested fix.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from enum import Enum

from .errors import Diagnostic, ErrorCode
from .pipeline import CompileResult, compile_source


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"                      # Recompilation succeeded with 0 errors
    PARTIAL = "PARTIALLY_VERIFIED"            # Original error fixed, but other pre-existing errors remain
    UNVERIFIED_SAME_ERROR = "UNVERIFIED_SAME_ERROR"   # The same error is still present
    UNVERIFIED_NEW_ERROR = "UNVERIFIED_NEW_ERROR"     # Fix broke something else (new errors)
    INVALID_EMPTY = "INVALID_EMPTY"           # LLM returned empty or whitespace-only code


@dataclass
class VerificationResult:
    status: VerificationStatus
    original_error: Diagnostic
    original_source: str
    fixed_source: str
    recompile_result: CompileResult
    diff: str = ""
    explanation: str = ""
    fix_description: str = ""
    remaining_errors: list[Diagnostic] = field(default_factory=list)

    @property
    def is_verified(self) -> bool:
        return self.status in (VerificationStatus.VERIFIED, VerificationStatus.PARTIAL)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "is_verified": self.is_verified,
            "diff": self.diff,
            "explanation": self.explanation,
            "fix_description": self.fix_description,
            "remaining_error_count": len(self.remaining_errors),
            "remaining_errors": [e.to_dict() for e in self.remaining_errors],
            "fixed_source": self.fixed_source,
        }


def compute_unified_diff(original: str, fixed: str, filename: str = "<input>") -> str:
    """Generate a clean unified diff string between original and fixed source."""
    orig_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        fixed_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3,
    )
    return "".join(diff)


def verify_fix(
    original_source: str,
    fixed_source: str,
    target_diagnostic: Diagnostic,
    filename: str = "<input>",
    explanation: str = "",
    fix_description: str = "",
) -> VerificationResult:
    """Recompile fixed_source and determine whether the proposed fix resolved the error."""
    clean_fixed = fixed_source.strip()
    if not clean_fixed:
        dummy_result = CompileResult(filename, [], None, [], [])
        return VerificationResult(
            status=VerificationStatus.INVALID_EMPTY,
            original_error=target_diagnostic,
            original_source=original_source,
            fixed_source=fixed_source,
            recompile_result=dummy_result,
            diff="",
            explanation=explanation,
            fix_description=fix_description,
            remaining_errors=[],
        )

    # Recompile through the complete compiler pipeline
    recompile = compile_source(fixed_source, filename)
    diff = compute_unified_diff(original_source, fixed_source, filename)

    if recompile.ok:
        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            original_error=target_diagnostic,
            original_source=original_source,
            fixed_source=fixed_source,
            recompile_result=recompile,
            diff=diff,
            explanation=explanation,
            fix_description=fix_description,
            remaining_errors=[],
        )

    # Check whether the targeted error code is still present
    target_code = target_diagnostic.code
    target_still_present = any(d.code == target_code for d in recompile.diagnostics)

    if target_still_present:
        status = VerificationStatus.UNVERIFIED_SAME_ERROR
    else:
        # Check if the new errors are strictly a subset of any other errors in the original code
        # Recompile original to see baseline errors
        orig_recompile = compile_source(original_source, filename)
        orig_codes = [d.code for d in orig_recompile.diagnostics if d is not target_diagnostic]
        all_remaining_were_existing = all(d.code in orig_codes for d in recompile.diagnostics)

        if all_remaining_were_existing:
            status = VerificationStatus.PARTIAL
        else:
            status = VerificationStatus.UNVERIFIED_NEW_ERROR

    return VerificationResult(
        status=status,
        original_error=target_diagnostic,
        original_source=original_source,
        fixed_source=fixed_source,
        recompile_result=recompile,
        diff=diff,
        explanation=explanation,
        fix_description=fix_description,
        remaining_errors=list(recompile.diagnostics),
    )
