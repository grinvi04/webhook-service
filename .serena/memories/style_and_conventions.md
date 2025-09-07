# Style and Conventions

This project uses `ruff` for both linting and formatting to ensure consistent code style.

## Configuration (`pyproject.toml`)

- **Line Length**: 88 characters
- **Quote Style**: Double quotes (`"`)
- **Selected Lint Rules**: `E`, `F`, `W`, `I`, `UP`

## Pre-commit Hooks

The project uses `pre-commit` to automatically enforce style and quality checks before each commit. The configured hooks are:

- `trailing-whitespace`: Removes trailing whitespace.
- `end-of-file-fixer`: Ensures files end with a single newline.
- `check-yaml`: Checks YAML files for syntax errors.
- `check-added-large-files`: Prevents large files from being committed.
- `ruff`: Runs the linter with auto-fix enabled.
- `ruff-format`: Formats code according to the defined style.

To enable these hooks, run `pre-commit install` after setting up your environment.
