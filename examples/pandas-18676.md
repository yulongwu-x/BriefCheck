# 公开试跑 · pandas 的 CSV 首行缺失值

Issue 报告了单列 CSV 的输出差异。导出时关闭表头和索引，首个值为空。报告者期望第一行是空行，接下来两行是 `1.0` 和 `2.0`。 [pandas Issue #18676](https://github.com/pandas-dev/pandas/issues/18676)

审查输入为 Issue 正文和 PR #19091 的完整 diff，PR head 为 `c8dd8135805a9a64eb574d443b13730841148866`。输入材料中的测试证据来自 diff。 [PR #19091](https://github.com/pandas-dev/pandas/pull/19091) · [变更文件](https://github.com/pandas-dev/pandas/pull/19091/files)

## 复现

在 BriefCheck 仓库根目录运行下面两条命令。第一条拉取 Issue、PR diff 和行号映射，第二条校验下表的引用。

```sh
briefcheck pack --pr "pandas-dev/pandas#19091" --issue-number 18676 --annotate --include-skill --out-dir ./review-pandas-19091
briefcheck verify --report examples/pandas-18676.md --diff ./review-pandas-19091/change.diff --strict-warnings
```

实跑结果为 `BriefCheck Verify: PASS`，核对了 3 处引用，待审提交为 `c8dd8135805a`。如遇 GitHub API 限流，可设置 `GITHUB_TOKEN` 后重试。需要独立审查时，在 Codex 中用 `$briefcheck` 读取输出目录的 `issue.md` 和 `change.diff`，完成后再对照下表。

## 审查结果

下表转述了独立 Codex 会话根据 Skill、Issue 正文和 diff 给出的判断。文件行号来自 PR 新侧的 diff。

| 验收要求 | 判断 | 证据 | 待补查 |
| --- | --- | --- | --- |
| 从 Issue 推导。关闭表头、索引并使用 UTF-8，单列首值缺失时导出空白首行。 | 证据不足 | `pandas/tests/io/formats/test_to_csv.py:24–32` 新增的测试期望首行含两个双引号，与 Issue 要求不一致。`pandas/tests/io/formats/test_to_csv.py:13–15` 的预期失败条件覆盖报告者使用的 Python 3.6.2。diff 提供的是测试断言，实际输出待核实。 | 在待审提交和报告者的环境中运行原复现，确认首行只有换行符。 |
| 从 Issue 推导。CSV 接下来的两行保持为 `1.0` 和 `2.0`，且没有表头或索引。 | 证据不足 | `pandas/tests/io/formats/test_to_csv.py:24–32` 的用例输入为 `[None, 1]`，期望包含 `1.0`，覆盖范围少了第三行。 | 用同一次运行核对第二行和第三行的值。 |
