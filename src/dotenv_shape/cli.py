"""Command line interface with sanitized diagnostics at every error boundary."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence, TextIO

from . import __version__
from .core import CheckResult, check_texts


class _UsageError(Exception):
    pass


class _OutputError(Exception):
    pass


def _discard_failed_output(stream: TextIO) -> None:
    # A failed flush leaves buffered output behind. Redirect its descriptor so
    # interpreter shutdown cannot retry the failed pipe and replace exit 2 with
    # exit 120 or print an unsanitized unraisable-exception diagnostic.
    try:
        with open(os.devnull, "wb") as sink:
            os.dup2(sink.fileno(), stream.fileno())
    except (AttributeError, OSError, ValueError):
        # Embedded callers may provide a stream with no operating-system fd.
        pass


def _write(text: str, stream: TextIO) -> None:
    try:
        stream.write(text)
        stream.flush()
    except (OSError, ValueError):
        _discard_failed_output(stream)
        raise _OutputError from None


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse messages can contain arbitrary command-line input.
        raise _UsageError

    def _print_message(self, message: str, file: TextIO | None = None) -> None:
        # argparse's default implementation can swallow immediate OSError
        # failures on unbuffered help/version output. Preserve our exit policy.
        if message:
            _write(message, file if file is not None else sys.stderr)


def _parser() -> argparse.ArgumentParser:
    parser = _SafeParser(
        prog="dotenv-shape",
        description="Check dotenv key names without printing values or file paths.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"dotenv-shape {__version__}")
    parser.add_argument("--json", action="store_true", help="write machine-readable diagnostics")
    parser.add_argument("--strict-extra", action="store_true", help="report keys absent from the example")
    parser.add_argument("--require-nonempty", action="store_true", help="report empty required values")
    parser.add_argument("example", help="UTF-8 example file defining required keys")
    parser.add_argument("targets", nargs="+", help="one or more UTF-8 dotenv files to check")
    return parser


def _write_errors(errors: list[dict[str, str]], as_json: bool) -> int:
    if as_json:
        _write(json.dumps({"ok": False, "findings": [], "errors": errors}, sort_keys=True) + "\n", sys.stdout)
    else:
        for error in errors:
            prefix = error.get("file", "command")
            _write(f"{prefix}: {error['kind']}\n", sys.stderr)
    return 2


def _write_result(result: CheckResult, as_json: bool) -> int:
    if as_json:
        _write(json.dumps(result.to_dict(), sort_keys=True) + "\n", sys.stdout)
    elif result.ok:
        _write("OK: configuration key shapes match.\n", sys.stdout)
    else:
        for finding in result.findings:
            location = finding.file
            if finding.line is not None:
                location += f":{finding.line}"
            details = f" key={finding.key}" if finding.key is not None else ""
            if finding.first_line is not None:
                details += f" first_line={finding.first_line}"
            _write(f"{location}: {finding.kind}{details}\n", sys.stdout)
    return 0 if result.ok else 1


def _run(argv: list[str], as_json: bool) -> int:
    try:
        args = _parser().parse_args(argv)
    except _UsageError:
        return _write_errors([{"kind": "invalid_arguments"}], as_json)
    texts: list[str] = []
    errors: list[dict[str, str]] = []
    paths = [args.example, *args.targets]
    for index, path in enumerate(paths):
        file_id = "example" if index == 0 else f"target:{index}"
        try:
            # Preserve physical newlines so a bare CR is not silently accepted.
            # The parser removes one leading BOM for both CLI and library use.
            with Path(path).open("r", encoding="utf-8", newline="") as stream:
                texts.append(stream.read())
        except UnicodeError:
            errors.append({"kind": "encoding_error", "file": file_id})
        except (OSError, ValueError):
            errors.append({"kind": "io_error", "file": file_id})
    if errors:
        return _write_errors(errors, args.json)
    result = check_texts(
        texts[0], texts[1:],
        strict_extra=args.strict_extra,
        require_nonempty=args.require_nonempty,
    )
    return _write_result(result, args.json)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; suppress arbitrary exception text and traceback contents."""
    as_json = False
    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        as_json = "--json" in arguments
        return _run(arguments, as_json)
    except _OutputError:
        return 2
    except Exception:
        # Third-party wrappers, file-like objects, and unexpected exceptions can
        # include secrets in their messages. Never render the exception object.
        try:
            return _write_errors([{"kind": "internal_error"}], as_json)
        except Exception:
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
