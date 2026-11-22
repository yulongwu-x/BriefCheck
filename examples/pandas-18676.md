# 公开试跑 · pandas 的 CSV 首行缺失值

Issue 报告了单列 CSV 的输出差异。导出时关闭表头和索引，首个值为空。报告者期望第一行是空行，接下来两行是 `1.0` 和 `2.0`。 [pandas Issue #18676](https://github.com/pandas-dev/pandas/issues/18676)

审查输入为 Issue 正文和 PR #19091 的完整 diff，PR head 为 `c8dd8135805a9a64eb574d443b13730841148866`。输入材料中的测试证据来自 diff。 [PR #19091](https://github.com/pandas-dev/pandas/pull/19091) · [变更文件](https://github.com/pandas-dev/pandas/pull/19091/files)

## 复现

1. 将 Issue 的原始描述复制到 `issue.md`，保留复现代码和期望输出。
2. 将 PR 的统一 diff 保存为 `change.diff`。 [下载 diff](https://github.com/pandas-dev/pandas/pull/19091.diff)
3. 在 Codex 中用 `$briefcheck` 审查这两份文件，得到输出后再对照下表。

## 审查结果

下表转述了独立 Codex 会话根据 Skill、Issue 正文和 diff 给出的判断。文件行号来自 PR 新侧的 diff。

| 验收要求 | 判断 | 证据 | 待补查 |
| --- | --- | --- | --- |
| 从 Issue 推导。关闭表头、索引并使用 UTF-8，单列首值缺失时导出空白首行。 | 证据不足 | `pandas/tests/io/formats/test_to_csv.py:24–32` 新增的测试期望首行含两个双引号，与 Issue 要求不一致。`pandas/tests/io/formats/test_to_csv.py:13–15` 的预期失败条件覆盖报告者使用的 Python 3.6.2。diff 提供的是测试断言，实际输出待核实。 | 在待审提交和报告者的环境中运行原复现，确认首行只有换行符。 |
| 从 Issue 推导。CSV 接下来的两行保持为 `1.0` 和 `2.0`，且没有表头或索引。 | 证据不足 | `pandas/tests/io/formats/test_to_csv.py:24–32` 的用例输入为 `[None, 1]`，期望包含 `1.0`，覆盖范围少了第三行。 | 用同一次运行核对第二行和第三行的值。 |
