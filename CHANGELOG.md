# Changelog

All notable changes to BriefCheck will be documented in this file.

## [0.4.0] - 2026-11-22

### Added
- `briefcheck check` (`verify_citations`): verify all `path:line` and `(base)` diff citations inside **any** free-form Markdown PR review (stdin by default) from Claude Code, Codex, Cursor, Copilot, or custom review scripts.
- Support for `--diff`, `--git-base`, `--staged` (`git diff --cached`), and `--pr owner/repo#123` diff sources in `briefcheck check`, plus `--require-citations` and `--format json`.

## [0.3.1] - 2026-11-22

### Added
- GitHub Actions Marketplace branding (`check-square` / `blue`) in `action.yml`.
- Visual citation verification demo card (`docs/briefcheck-demo.png`) embedded in both READMEs.
- GitHub Issue templates for bug reports and review fixtures, plus one-line Codex and Claude Code skill install snippets.

## [0.3.0] - 2026-11-22

### Added

- `briefcheck demo` runs the verifier offline on a small diff and review. It shows a deleted-line citation on the wrong side, an out-of-hunk citation, and the result after fixing both.
- A ready-to-install Python wheel on the GitHub release, with trial commands in both READMEs.

### Changed

- The pandas case study includes commands to fetch the review bundle and verify the report.
- GitHub API requests identify the installed BriefCheck version in the user agent.

## [0.2.0] - 2026-11-22

### Added
- `briefcheck run` for OpenAI-compatible Chat Completions and Responses. It assembles annotated review material, verifies the generated table, and retries repairable report errors.
- Markdown and JSON review output with distinct verification and judgment-gate exit codes.
- A Composite GitHub Action that publishes a verified report in the job summary and creates or updates a single comment on the reviewed PR.
- Mocked coverage for model requests, retries, gate outcomes, stale PR revisions, skipped reviews, and comment updates.

## [0.1.0] - 2026-11-22

### Added
- Zero-dependency Python CLI (`briefcheck`) supporting Python 3.10+.
- `briefcheck verify`: deterministic verifier for BriefCheck Markdown review tables, checking table structure, canonical judgment labels (English and Chinese), exact `base`/`new` diff hunk line citations, test-log revision matching, JSON output, and CI exit-code gates (`--fail-on`).
- `briefcheck pack`: review-bundle assembler supporting local files, local `git diff` ranges, and GitHub PRs with automatic linked-issue extraction (`Fixes`/`Closes`/`Resolves #N`), optional issue comments and check-runs summary, explicit `<untrusted_artifact>` prompt-injection boundaries, and optional embedded skill instructions.
- `briefcheck annotate`: unified diff annotator printing exact `base | new` line numbers for every hunk line.
- New example fixtures: `examples/prompt-injection-auth/` (prompt-injection defense and `base`-side deletion citations) and `examples/retry-backoff/` (multi-hunk line tracking, compound requirement splitting, and revision-mismatched test logs).
- Unit test suite (`tests/`) and GitHub Actions CI workflow (`.github/workflows/ci.yml`).
- Bilingual documentation (`README.md` in English and `README.zh-CN.md` in Chinese).
