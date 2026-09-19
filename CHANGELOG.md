# Changelog

## 0.1.0

- Add a standard-library CLI and Python API for comparing dotenv key names.
- Detect malformed assignments, duplicate keys, and missing required keys.
- Add optional checks for extra keys and empty required values.
- Keep values, raw source lines, filenames, and exception messages out of CLI diagnostics.
- Apply the same single-BOM policy in file and text APIs, and require boolean
  comparison options in the library.
- Handle failed output pipes with exit code 2 without shutdown tracebacks.
