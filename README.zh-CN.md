# BriefCheck

[![CI](https://github.com/yulongwu-x/BriefCheck/actions/workflows/ci.yml/badge.svg)](https://github.com/yulongwu-x/BriefCheck/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) | 简体中文

**基于证据的 PR 验收审查工具**：将可移植的 **Agent Skill** 与零依赖的 **Python CLI** 结合起来，用来逐条核对 GitHub Issue 的验收要求和 PR 改动，并对审查结果中的文件行号、表格格式与测试日志提交号做确定性校验。

## 包含内容

1. **Agent Skill（[`.agents/skills/briefcheck/SKILL.md`](.agents/skills/briefcheck/SKILL.md)）**：输入 Issue 正文、统一 diff 和可选测试日志，输出包含判断、证据位置和待补查项的 Markdown 表，严格区分「代码实现 / 测试定义 / 提交号匹配的测试执行结果」，并将输入材料中的指令视为纯数据。兼容 **Codex**、**Antigravity**、**Claude Code** 等支持 Agent Skills 规范的工具。
2. **`briefcheck pack`**：从本地文件、本地 `git diff` 范围或直接从 GitHub PR 链接（自动解析 `Fixes #N` / `Closes #N` 关联 Issue）拉取并组装审查材料，附带防 Prompt Injection 边界隔离标记。
3. **`briefcheck annotate`**：为任意统一 diff 标出每一行的精确 `base | new` 行号，避免审查时手算行号出错。
4. **`briefcheck verify`**：对生成的 BriefCheck Markdown 表格执行确定性核查：
   * 校验表格列数、转义 `|` 与标准判断枚举值（中英文均支持）；
   * 逐条校验 `path:line`、`path:start–end` 及 `base`（旧侧）引用是否真实落在 diff 可见 hunk 范围内；
   * 捕获把已删除行误标成新侧行号、越界行号、虚构文件名，以及测试日志与待审 diff 提交号不一致的问题；
   * 支持 `--format json` 输出和 CI 退出码门禁（`--fail-on contradicted|insufficient|unresolved`）。

## 安装

需要 Python 3.10+，**无任何第三方运行时依赖**：

```sh
pip install -e .
```

也可以不安装直接运行：

```sh
PYTHONPATH=src python -m briefcheck --help
```

## 快速试用

### 1. 用 Agent Skill 审查样例

在 Codex（或其他支持 `.agents/skills/` 的工具）中打开本仓库根目录，通过 `$` 选中 `briefcheck`，发送：

```text
$briefcheck 请用中文审查 examples/csv-export/issue.md 和 examples/csv-export/change.diff。
```

运行后对照 [预期审查](examples/csv-export/expected.md)，也可以一并提供 [`examples/csv-export/test-run.log`](examples/csv-export/test-run.log) 核对与提交号匹配的测试运行记录。

### 2. 用 CLI 对审查表做确定性校验

```sh
briefcheck verify \
  --report examples/csv-export/expected.md \
  --diff examples/csv-export/change.diff \
  --test-log examples/csv-export/test-run.log
```

输出示例：

```text
BriefCheck Verify: PASS
Rows: 3 (supported=1, contradicted=1, insufficient=1, invalid=0)
Citations checked: 3
Revisions: diff=dcd899c57675, test_log=dcd899c57675, match=yes
```

在 CI 中可配合 `--fail-on contradicted`（存在明确不符项时返回退出码 `2`）或 `--format json` 使用。

### 3. 一键打包自己的 PR 或本地分支

直接从 GitHub PR 打包（自动解析 `Fixes #N` 关联 Issue；私有仓库或高频调用可设置 `GITHUB_TOKEN`）：

```sh
briefcheck pack \
  --pr https://github.com/owner/repo/pull/123 \
  --include-comments \
  --include-checks \
  --annotate \
  --out-dir ./review-pr-123
```

或从本地 Issue 与 git 分支打包（加上 `--include-skill` 可直接整份粘贴到任意对话模型中使用）：

```sh
briefcheck pack \
  --issue issue.md \
  --git-base origin/main \
  --git-head HEAD \
  --test-log test-run.log \
  --annotate \
  --include-skill \
  -o review-bundle.md
```

### 4. 查看精确的 diff 行号映射

```sh
briefcheck annotate examples/csv-export/change.diff
```

## 判断含义

| 判断 | 英文对应 | 含义 |
| --- | --- | --- |
| 有证据支持 | Supported | 可见实现或提交号匹配的运行结果完整支持要求 |
| 明确不符 | Contradicted | 可见代码或提交号匹配的运行结果与要求直接冲突 |
| 证据不足 | Insufficient evidence | 当前材料覆盖不全或相互矛盾，需按待补查项进一步核实 |

## 内置样例与公开案例

| 案例 | 覆盖重点 |
| --- | --- |
| [`examples/csv-export/`](examples/csv-export) | 一次性覆盖全部三种判断以及提交号匹配的 `test-run.log`。 |
| [`examples/prompt-injection-auth/`](examples/prompt-injection-auth) | 防御 diff 内嵌的 Prompt Injection 指令，并使用 `base` 旧侧行号引用被删除的权限检查代码。 |
| [`examples/retry-backoff/`](examples/retry-backoff) | 同文件多 hunk 行号追踪、复合验收条件拆分，以及识别提交号不匹配的旧测试日志。 |
| [`examples/pandas-18676.md`](examples/pandas-18676.md) | pandas Issue #18676 / PR #19091 公开案例及复现步骤。 |

## 运行测试

```sh
python -m unittest discover -s tests -v
```

## 许可证

[MIT](LICENSE)
