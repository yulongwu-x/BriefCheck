# Changelog

All notable changes to BriefCheck will be documented in this file.

## [0.1.0] - 2026-11-22

### Added
- Zero-dependency Python CLI (`briefcheck`) supporting Python 3.10+.
- `briefcheck verify`: deterministic verifier for BriefCheck Markdown review tables, checking table structure, canonical judgment labels (English and Chinese), exact `base`/`new` diff hunk line citations, test-log revision matching, JSON output, and CI exit-code gates (`--fail-on`).
- `briefcheck pack`: review-bundle assembler supporting local files, local `git diff` ranges, and GitHub PRs with automatic linked-issue extraction (`Fixes`/`Closes`/`Resolves #N`), optional issue comments and check-runs summary, explicit `<untrusted_artifact>` prompt-injection boundaries, and optional embedded skill instructions.
- `briefcheck annotate`: unified diff annotator printing exact `base | new` line numbers for every hunk line.
- New example fixtures: `examples/prompt-injection-auth/` (prompt-injection defense and `base`-side deletion citations) and `examples/retry-backoff/` (multi-hunk line tracking, compound requirement splitting, and revision-mismatched test logs).
- Unit test suite (`tests/`) and GitHub Actions CI workflow (`.github/workflows/ci.yml`).
- Bilingual documentation (`README.md` in English and `README.zh-CN.md` in Chinese).
