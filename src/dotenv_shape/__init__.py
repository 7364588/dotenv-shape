"""Read-only dotenv shape checks that never include values in their results."""

from .core import CheckResult, Entry, Finding, ParsedDocument, check_texts, parse_text

__all__ = ["CheckResult", "Entry", "Finding", "ParsedDocument", "check_texts", "parse_text"]
__version__ = "0.1.0"
