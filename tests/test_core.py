"""Behavior and non-disclosure tests using synthetic values only."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv_shape import check_texts, parse_text

SECRET = "synthetic-secret-9a7d2!"


class ParserTests(unittest.TestCase):
    def test_comments_export_whitespace_and_crlf(self):
        parsed = parse_text("\ufeff# header\r\n\r\n export\tKEY = value \r\n")
        self.assertEqual([(e.key, e.line, e.empty) for e in parsed.entries], [("KEY", 3, False)])
        self.assertFalse(parsed.findings)

    def test_only_one_leading_bom_is_removed(self):
        parsed = parse_text("\ufeff\ufeffKEY=value\n")
        self.assertFalse(parsed.entries)
        self.assertEqual([finding.kind for finding in parsed.findings], ["malformed_entry"])

    def test_key_grammar(self):
        parsed = parse_text("_A9=ok\nA.B=x\n9A=x\nÄ=x\nA B=x\n")
        self.assertEqual([e.key for e in parsed.entries], ["_A9"])
        self.assertEqual([f.line for f in parsed.findings], [2, 3, 4, 5])
        self.assertTrue(all(f.key is None for f in parsed.findings))

    def test_empty_forms(self):
        for value in ("", "  ", "# comment", " # comment", "''", '""', '"" # comment'):
            with self.subTest(value=value):
                parsed = parse_text("KEY=" + value)
                self.assertFalse(parsed.findings)
                self.assertTrue(parsed.entries[0].empty)

    def test_nonempty_forms(self):
        for value in ("value", "x#y", "x # comment", "' '", '" "', '"\\n"', "${OTHER}", "$(command)", "`command`", "folder\\item"):
            with self.subTest(value=value):
                parsed = parse_text("KEY=" + value)
                self.assertFalse(parsed.findings)
                self.assertFalse(parsed.entries[0].empty)

    def test_quoted_hash_equals_and_escapes(self):
        for value in ("'a#b=c'", '"a#b=c"', '"a\\"b"', '"a\\\\b"', '"\\n\\r\\t\\$"', "'a\\b'"):
            with self.subTest(value=value):
                self.assertFalse(parse_text("KEY=" + value).findings)

    def test_malformed_quoting(self):
        for value in ("'unfinished", '"unfinished', '"x"tail', '"x"#comment', "'x'#comment", 'a"b', "a'b", '"\\q"', '"x\\', "'can\\'t'"):
            with self.subTest(value=value):
                parsed = parse_text("KEY=" + value)
                self.assertFalse(parsed.entries)
                self.assertEqual(parsed.findings[0].kind, "malformed_entry")
                self.assertEqual(parsed.findings[0].key, "KEY")

    def test_comment_text_is_not_value_syntax(self):
        self.assertFalse(parse_text("KEY=value # 'unclosed \" quote").findings)

    def test_multiline_quotes_are_not_accepted(self):
        parsed = parse_text('KEY="first\nsecond"\n')
        self.assertEqual([f.line for f in parsed.findings], [1, 2])

    def test_nul_and_bare_carriage_return(self):
        for text in ("KEY=a\x00b", "KEY=a\rb", "KEY=value\r"):
            with self.subTest(text=text):
                self.assertEqual(parse_text(text).findings[0].kind, "malformed_entry")

    def test_duplicate_retains_first_valid_assignment(self):
        parsed = parse_text("KEY=\nKEY=other\nKEY=third\n")
        self.assertEqual(len(parsed.entries), 1)
        self.assertTrue(parsed.entries[0].empty)
        self.assertEqual([(f.line, f.first_line) for f in parsed.findings], [(2, 1), (3, 1)])

    def test_invalid_assignment_does_not_reserve_key(self):
        parsed = parse_text('KEY="unfinished\nKEY=valid\n')
        self.assertEqual(parsed.entries[0].line, 2)
        self.assertEqual([f.kind for f in parsed.findings], ["malformed_entry"])

    def test_export_is_a_key_without_separating_whitespace(self):
        self.assertEqual(parse_text("export=value").entries[0].key, "export")

    def test_unterminated_statement_does_not_become_a_key(self):
        parsed = parse_text(SECRET)
        self.assertEqual(parsed.findings[0].key, None)
        self.assertNotIn(SECRET, repr(parsed))

    def test_values_absent_from_result_and_serialized_findings(self):
        text = f"KEY={SECRET}\nKEY={SECRET}\nBAD='{SECRET}\n{SECRET}=x\n{SECRET}\n"
        parsed = parse_text(text)
        self.assertNotIn(SECRET, repr(parsed))
        self.assertNotIn(SECRET, json.dumps([f.to_dict() for f in parsed.findings]))

    def test_invalid_input_type_is_generic(self):
        with self.assertRaisesRegex(TypeError, "dotenv input must be text"):
            parse_text(123)


class ComparisonTests(unittest.TestCase):
    def test_matching_ignores_values(self):
        self.assertTrue(check_texts("A=example", ["A=target"]).ok)

    def test_missing_sorted_and_target_identifiers(self):
        result = check_texts("Z=\nA=", ["", "A=present"])
        self.assertEqual([(f.file, f.key, f.line) for f in result.findings], [("target:1", "A", None), ("target:1", "Z", None), ("target:2", "Z", None)])

    def test_extra_and_empty_allowed_by_default(self):
        self.assertTrue(check_texts("A=", ["A=\nEXTRA="]).ok)

    def test_strict_extra(self):
        result = check_texts("A=", ["Z=\nA=\nB="], strict_extra=True)
        self.assertEqual([(f.kind, f.key, f.line) for f in result.findings], [("extra_key", "B", 3), ("extra_key", "Z", 1)])

    def test_nonempty_only_applies_to_expected_keys(self):
        result = check_texts("A=", ["A=\nEXTRA="], require_nonempty=True)
        self.assertEqual([(f.kind, f.key) for f in result.findings], [("empty_required_value", "A")])

    def test_empty_example_is_valid(self):
        self.assertTrue(check_texts("# no required keys", [""]).ok)

    def test_broken_example_is_finding(self):
        result = check_texts("A=\nA=duplicate\nbroken", ["A=valid"])
        self.assertEqual([f.file for f in result.findings], ["example", "example"])
        self.assertEqual([f.kind for f in result.findings], ["duplicate_key", "malformed_entry"])

    def test_invalid_target_can_also_be_missing(self):
        result = check_texts("A=", ['A="unfinished'])
        self.assertEqual([f.kind for f in result.findings], ["malformed_entry", "missing_key"])

    def test_first_duplicate_controls_nonempty(self):
        result = check_texts("A=", ["A=\nA=nonempty"], require_nonempty=True)
        self.assertEqual([f.kind for f in result.findings], ["duplicate_key", "empty_required_value"])

    def test_values_absent_from_public_check_result(self):
        result = check_texts("KEY=", [f"KEY={SECRET}\nKEY={SECRET}\nBAD='{SECRET}"])
        self.assertNotIn(SECRET, repr(result))
        self.assertNotIn(SECRET, json.dumps(result.to_dict()))

    def test_wrong_target_container(self):
        for targets in ("A=value", b"A=value", None, 123):
            with self.subTest(targets=targets), self.assertRaises(TypeError):
                check_texts("A=", targets)

    def test_no_targets(self):
        with self.assertRaisesRegex(ValueError, "at least one target"):
            check_texts("", [])

    def test_comparison_options_require_boolean_types(self):
        for name in ("strict_extra", "require_nonempty"):
            for value in ("false", SECRET, 0, 1, None, [], {}):
                with self.subTest(option=name, value=value):
                    with self.assertRaisesRegex(TypeError, "comparison options must be booleans") as caught:
                        check_texts("KEY=", ["KEY="], **{name: value})
                    self.assertNotIn(SECRET, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
