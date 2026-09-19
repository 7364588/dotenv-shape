# dotenv-shape

Check whether dotenv files contain the keys required by an example file, without
printing configuration values. The CLI reads files and emits diagnostics; it
does not modify files, set environment variables, interpolate values, execute
commands, or contact a network service.

Requires Python 3.11 or newer. There are no runtime dependencies.

## Install and run

From a checkout:

```sh
python -m pip install .
dotenv-shape .env.example .env
python -m dotenv_shape --strict-extra --require-nonempty .env.example .env.local .env.production
```

Use `--` before positional arguments when a filename starts with a hyphen.
Relative paths are resolved against the current working directory. Symlinks
are followed by normal operating-system file handling.

Given this `.env.example`:

```dotenv
SERVICE_URL=
ACCESS_TOKEN=
```

And this target:

```dotenv
SERVICE_URL=https://example.invalid
OLD_SETTING=placeholder
```

`dotenv-shape --strict-extra .env.example .env` prints:

```text
target:1: missing_key key=ACCESS_TOKEN
target:1:2: extra_key key=OLD_SETTING
```

The example is identified as `example`; targets are `target:1`, `target:2`, etc.,
in argument order. Paths are deliberately omitted from all diagnostics. A line
number is 1-based and follows the file identifier; missing keys have no target
line number. `first_line` identifies the first valid assignment of a duplicate.
Keep the original invocation if you need to map these identifiers to files.

Extra keys and empty values are allowed by default. `--strict-extra` reports
extra keys. `--require-nonempty` reports empty values for required keys only.
The example's values do not specify defaults or desired values.

## Exit status and JSON

| Exit code | Meaning |
| --- | --- |
| `0` | No findings; also used by `--help` and `--version`. |
| `1` | Validation findings, including malformed or duplicate entries in the example. |
| `2` | Invalid arguments, read/encoding/output failure, or an unexpected internal error. |

Human validation output goes to stdout; input failures go to stderr. `--json`
writes one JSON object to stdout for either result, with stderr empty. Help and
version are plain text even when `--json` is present.
If an output pipe is closed or cannot be written, the tool exits `2`; a report
cannot be guaranteed in that case.

```sh
dotenv-shape --json --strict-extra .env.example .env
```

```json
{"findings": [{"file": "target:1", "key": "ACCESS_TOKEN", "kind": "missing_key"}, {"file": "target:1", "key": "OLD_SETTING", "kind": "extra_key", "line": 2}], "ok": false}
```

A read failure returns, for example:

```json
{"errors": [{"file": "target:1", "kind": "io_error"}], "findings": [], "ok": false}
```

Finding kinds are `malformed_entry`, `duplicate_key`, `missing_key`, `extra_key`,
and `empty_required_value`. Error kinds are `invalid_arguments`, `io_error`,
`encoding_error`, and `internal_error`. Diagnostic fields are omitted when they
do not apply. Results are deterministic: example parse findings first, then
each target's parse findings in source order, missing keys sorted by name,
extra keys sorted by name, and empty required keys sorted by name. On read
failure, all inputs are attempted and no partial validation result is emitted.

## Supported dotenv dialect

Dotenv has multiple dialects. This tool intentionally accepts a small, explicit
one and is not a drop-in parser for every shell or dotenv library.

- Files must be UTF-8, optionally with one leading BOM. LF and CRLF line endings
  are accepted. Bare carriage returns in assignments are malformed.
- Each assignment occupies one physical line. Blank lines and lines beginning
  with `#` after optional spaces/tabs are ignored.
- Keys match ASCII `[A-Za-z_][A-Za-z0-9_]*`. Assignment is `KEY=VALUE`, with
  optional spaces/tabs around `=`. A leading `export` followed by one or more
  spaces/tabs is accepted, but has no effect.
- Bare values are literal. Leading/trailing spaces and tabs are ignored.
  A `#` starts a comment only at the beginning of the value or after a space/tab.
  Thus `x#y` is a value, while `x # comment` has value `x`. Quotes inside a bare
  value are malformed; backslashes, dollar signs, and backticks are literal.
- A value beginning with a single or double quote must close on the same line.
  After its closing quote, only spaces/tabs and an optional comment are allowed.
  A comment following a quoted value must be separated by a space/tab.
- Single-quoted content is literal; a backslash cannot escape a single quote.
  Double quotes recognize only `\\`, `\"`, `\n`, `\r`, `\t`, and `\$` as valid
  escape sequences. Escapes are checked for syntax, not decoded or executed.
  `#` inside quotes is literal. Variable expansion never occurs.
- An empty bare value, a comment-only bare value, `''`, and `""` count as empty.
  Quoted whitespace, `"\n"`, and literal `${NAME}` are nonempty. This is a
  syntactic presence check, not a check of eventual runtime values.
- NUL and bare carriage returns in value text are malformed. Multiline values,
  continuation lines, shell statements, and assignments without `=` are not
  supported.

Only valid assignments contribute keys. A malformed target assignment may
therefore also produce a missing-key finding. Duplicate detection considers
valid assignments only and preserves the first one's emptiness and line number;
duplicates always remain findings. Malformed and duplicate example entries are
also findings, so a broken example cannot produce a successful result.
An empty example is allowed and requires no keys.

## Python API

```python
from dotenv_shape import check_texts, parse_text

result = check_texts(
    "SERVICE_URL=\nACCESS_TOKEN=\n",
    ["SERVICE_URL=https://example.invalid\nACCESS_TOKEN=\n"],
    require_nonempty=True,
)
assert not result.ok
assert result.findings[0].kind == "empty_required_value"
print(result.to_dict())

shape = parse_text("export SERVICE_URL='https://example.invalid'\n")
assert shape.entries[0].key == "SERVICE_URL"
```

`parse_text()` returns immutable tuples of `Entry(key, line, empty)` and
`Finding` objects. Its fixed file identifier is `document`. `check_texts()`
accepts a nonempty sequence of text documents, returns a `CheckResult`, and uses
the same identifiers as the CLI. Neither API reads a file or changes the
environment. Invalid API argument types raise a generic `TypeError`; no targets
raises a generic `ValueError`. Input text is never attached to result objects.
The `strict_extra` and `require_nonempty` options require actual `bool` values;
strings and integers are rejected rather than interpreted by truthiness.

## Security boundary and limitations

Tool-generated diagnostics include only fixed messages, key names, generated
file identifiers, and line numbers. They omit values, raw malformed lines, input
paths, and operating-system or unexpected exception messages. Arguments are not
echoed on usage errors. **Key names are public output: never put secrets in key
names.** The empty/nonempty state of a value is intentionally observable.

The tool reads complete files into process memory. It does not erase memory,
scrub terminal history or operating-system process arguments, prevent a debugger
from observing inputs, or control logging performed by a caller. It does not
validate credential strength, URLs, value types, interpolation results, access
permissions, or compatibility with your application's dotenv loader. Avoid
passing unbounded files or devices; there is no input-size or read-time limit.
There is no file locking, so another process can change an input during a run.

## Development

Tests use `unittest` and synthetic data only; no network access or package install
is needed to run them from the repository root:

```sh
python -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for changes and release checks. The project
uses the [MIT license](LICENSE).
