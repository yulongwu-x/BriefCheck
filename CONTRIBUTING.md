# Contributing to BriefCheck

Contributions are welcome — especially new real-world review fixtures, diff-parser edge cases, and verification rules that keep PR reviews grounded in verifiable evidence.

## Development setup

BriefCheck has zero runtime dependencies and uses Python's standard library (`>= 3.10`).

```sh
python -m pip install --no-deps -e .
python -m unittest discover -s tests -v
```

You can also run the CLI directly without installing:

```sh
PYTHONPATH=src python -m briefcheck --help
```

## Adding a review fixture

Good fixtures under `examples/<name>/` should stay small, self-contained, and isolate one or two concrete failure modes (for example: base-side deletions, multi-hunk offsets, prompt-injection payloads, or revision-mismatched logs).

Each fixture typically includes:
- `issue.md` — acceptance criteria or bug description
- `change.diff` — unified diff (optionally with a `From <sha>` commit header)
- `expected.md` — reference BriefCheck Markdown table
- `test-run.log` (optional) — test output tied to a commit SHA

Before opening a pull request, confirm your fixture passes both the test suite and the verifier:

```sh
briefcheck verify --report examples/<name>/expected.md --diff examples/<name>/change.diff
```

## Pull request guidelines

- Link the target issue (`Fixes #...`) and keep acceptance criteria clear and testable.
- Include unit tests for any parser, verifier, packer, or CLI change.
- Keep `briefcheck` free of unnecessary runtime dependencies.
