"""CLI end-to-end coverage plus sanitized exception-path regression tests."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv_shape.cli import main

SECRET = "synthetic-secret-9a7d2!"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.example = Path(self.directory.name) / ".env.example"
        self.target = Path(self.directory.name) / ".env"
        self.example.write_text("KEY=\n", encoding="utf-8")
        self.target.write_text(f"KEY={SECRET}\n", encoding="utf-8")

    def invoke(self, *arguments):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "dotenv_shape", *map(str, arguments)],
            text=True, capture_output=True, env=environment, timeout=10,
        )
        self.assertNotIn(SECRET, result.stdout)
        self.assertNotIn(SECRET, result.stderr)
        self.assertNotIn(str(self.directory.name), result.stdout)
        self.assertNotIn(str(self.directory.name), result.stderr)
        return result

    def captured_main(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        self.assertNotIn(SECRET, stdout.getvalue())
        self.assertNotIn(SECRET, stderr.getvalue())
        return code, stdout.getvalue(), stderr.getvalue()

    def test_clean_run_is_read_only(self):
        before = (self.example.read_bytes(), self.target.read_bytes())
        result = self.invoke(self.example, self.target)
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK:", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(before, (self.example.read_bytes(), self.target.read_bytes()))

    def test_clean_json(self):
        result = self.invoke("--json", self.example, self.target)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {"ok": True, "findings": []})
        self.assertEqual(result.stderr, "")

    def test_malformed_and_duplicate_values_redacted_in_both_formats(self):
        self.target.write_text(f"KEY={SECRET}\nKEY={SECRET}\nBAD='{SECRET}\n{SECRET}\n", encoding="utf-8")
        for flags in ([], ["--json"]):
            with self.subTest(flags=flags):
                result = self.invoke(*flags, self.example, self.target)
                self.assertEqual(result.returncode, 1)
                self.assertIn("duplicate_key", result.stdout)
                self.assertIn("malformed_entry", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_strict_extra_and_require_nonempty(self):
        self.target.write_text("KEY=\nEXTRA=\n", encoding="utf-8")
        result = self.invoke("--json", "--strict-extra", "--require-nonempty", self.example, self.target)
        self.assertEqual(result.returncode, 1)
        self.assertEqual([f["kind"] for f in json.loads(result.stdout)["findings"]], ["extra_key", "empty_required_value"])

    def test_multiple_targets(self):
        other = self.target.with_name("other.env")
        other.write_text("", encoding="utf-8")
        result = self.invoke("--json", self.example, self.target, other)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["findings"][0]["file"], "target:2")

    def test_missing_path_is_sanitized(self):
        missing = self.target.with_name(SECRET)
        result = self.invoke(self.example, missing)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "target:1: io_error\n")

    def test_missing_example_and_target_report_both(self):
        result = self.invoke("--json", self.target.with_name("missing-example"), self.target.with_name(SECRET))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["errors"], [{"file": "example", "kind": "io_error"}, {"file": "target:1", "kind": "io_error"}])
        self.assertEqual(result.stderr, "")

    def test_invalid_utf8(self):
        self.target.write_bytes(SECRET.encode() + b"\xff")
        result = self.invoke("--json", self.example, self.target)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["errors"][0]["kind"], "encoding_error")
        self.assertEqual(result.stderr, "")

    def test_crlf_bom_files(self):
        self.target.write_bytes(b"\xef\xbb\xbfKEY=value\r\n")
        self.assertEqual(self.invoke(self.example, self.target).returncode, 0)

    def test_double_bom_is_rejected_consistently_with_library(self):
        from dotenv_shape import check_texts

        self.target.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbfKEY=value\n")
        result = self.invoke("--json", self.example, self.target)
        expected = check_texts(
            self.example.read_text(encoding="utf-8"),
            [self.target.read_text(encoding="utf-8")],
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), expected.to_dict())

    def test_closed_stdout_is_silent_exit_two(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for unbuffered in (False, True):
            environment.pop("PYTHONUNBUFFERED", None)
            if unbuffered:
                environment["PYTHONUNBUFFERED"] = "1"
            for arguments in (
                [str(self.example), str(self.target)],
                ["--json", str(self.example), str(self.target)],
                ["--help"],
                ["--version"],
            ):
                with self.subTest(arguments=arguments, unbuffered=unbuffered):
                    child = subprocess.Popen(
                        [sys.executable, "-m", "dotenv_shape", *arguments],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                    )
                    try:
                        child.stdout.close()
                        child.stdout = None
                        _, errors = child.communicate(timeout=10)
                    finally:
                        if child.poll() is None:
                            child.kill()
                            child.communicate()
                    self.assertEqual(child.returncode, 2)
                    self.assertEqual(errors, b"")

    def test_closed_stderr_is_silent_exit_two(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for unbuffered in (False, True):
            environment.pop("PYTHONUNBUFFERED", None)
            if unbuffered:
                environment["PYTHONUNBUFFERED"] = "1"
            with self.subTest(unbuffered=unbuffered):
                child = subprocess.Popen(
                    [sys.executable, "-m", "dotenv_shape", "--unknown"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                )
                try:
                    child.stderr.close()
                    child.stderr = None
                    output, _ = child.communicate(timeout=10)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.communicate()
                self.assertEqual(child.returncode, 2)
                self.assertEqual(output, b"")

    def test_bare_cr_not_normalized_by_file_reader(self):
        self.target.write_bytes(b"KEY=value\rOTHER=value\r")
        result = self.invoke(self.example, self.target)
        self.assertEqual(result.returncode, 1)
        self.assertIn("malformed_entry", result.stdout)

    def test_usage_errors_do_not_echo_arguments(self):
        for args in (("--unknown=" + SECRET,), ("--json", "--unknown=" + SECRET), (SECRET,)):
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid_arguments", result.stdout + result.stderr)

    def test_help_and_version(self):
        self.assertIn("--strict-extra", self.invoke("--help").stdout)
        result = self.invoke("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "dotenv-shape 0.1.0")

    def test_synthetic_fixture_pair(self):
        fixtures = ROOT / "tests" / "fixtures"
        result = self.invoke(fixtures / ".env.example", fixtures / "complete.env")
        self.assertEqual(result.returncode, 0)

    def test_os_error_message_never_rendered(self):
        with patch("dotenv_shape.cli.Path.open", side_effect=OSError(SECRET)):
            code, stdout, stderr = self.captured_main([str(self.example), str(self.target)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("io_error", stderr)

    def test_decode_error_payload_never_rendered(self):
        error = UnicodeDecodeError("utf-8", SECRET.encode(), 0, 1, SECRET)
        with patch("dotenv_shape.cli.Path.open", side_effect=error):
            code, stdout, stderr = self.captured_main(["--json", str(self.example), str(self.target)])
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["errors"][0]["kind"], "encoding_error")

    def test_unexpected_exception_never_rendered(self):
        for flags in ([], ["--json"]):
            with self.subTest(flags=flags), patch("dotenv_shape.cli.check_texts", side_effect=RuntimeError(SECRET)):
                code, stdout, stderr = self.captured_main([*flags, str(self.example), str(self.target)])
                self.assertEqual(code, 2)
                self.assertIn("internal_error", stdout + stderr)
                self.assertNotIn("Traceback", stdout + stderr)

    def test_unexpected_read_exception_never_rendered(self):
        with patch("dotenv_shape.cli.Path.open", side_effect=RuntimeError(SECRET)):
            code, stdout, stderr = self.captured_main([str(self.example), str(self.target)])
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "command: internal_error\n")


if __name__ == "__main__":
    unittest.main()
