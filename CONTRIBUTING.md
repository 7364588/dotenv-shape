# Contributing

Use Python 3.11 or newer. The package has no runtime dependencies, and tests use
the standard library. From the repository root, run:

```sh
python -m unittest discover -s tests -v
```

The test modules load `src/` directly, so installation is optional for tests.
To exercise the installed console script, use a disposable virtual environment
and install the checkout with `python -m pip install .`.

Keep parser changes consistent with the README's dialect and add behavior tests
for ambiguity, quoting, and duplicates. Preserve deterministic diagnostic order
and the documented exit codes. Never include real configurations or credentials
in examples, tests, bug reports, logs, or commits. A minimal synthetic example is
enough to reproduce a parser issue.

Any new diagnostic or exception path needs a regression test checking both
stdout and stderr for a synthetic secret marker. Configuration values, raw
source lines, paths, and exception messages must not appear in CLI output.
Tests should also inspect library return objects when changing their structure.
Do not add value previews, automatic rewriting, environment-variable loading,
or interpolation as convenience behavior.

Before a release, run the tests on the minimum supported Python and the current
stable Python, test the console script from a built wheel in an isolated
environment, and update `CHANGELOG.md` plus both version declarations in
`pyproject.toml` and `src/dotenv_shape/__init__.py`. Packaging checks may use build
tools in that isolated environment; they are not runtime dependencies.
