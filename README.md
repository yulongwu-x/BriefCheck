# BriefCheck

BriefCheck 是一个 Codex Skill，用来逐条核对 GitHub Issue 的验收要求和 PR 改动。输入 Issue 正文、统一 diff 和可选测试日志，输出一张包含判断、证据位置和待补查项的 Markdown 表。

A Codex skill for reviewing a pull request against issue acceptance criteria, with file and line references for each judgment.

## 快速试用

在 Codex 中打开本仓库根目录，通过 `$` 选中 `briefcheck`，发送下面的提示。

~~~text
$briefcheck 请用中文审查 examples/csv-export/issue.md 和 examples/csv-export/change.diff。
~~~

运行后对照 [预期审查](examples/csv-export/expected.md)。也可以将 [Skill 指令](.agents/skills/briefcheck/SKILL.md) 和两个输入文件的正文一起粘贴到新会话中试用。也可以在请求里加上 `examples/csv-export/test-run.log`。这份日志记录了样例提交上中文文件名单测的实际运行，diff 开头的提交号与日志中的提交号一致。

## 审查自己的 PR

1. 将 Issue 正文保存为 Markdown，保留验收条件和复现时的预期行为。
2. 从 PR 的 **Files changed** 取得统一 diff，也可以在待审仓库用下面的命令生成文件。将 `origin/main` 和 `HEAD` 换成 PR 的目标分支与待审提交。

   ~~~sh
   git diff --no-color --no-ext-diff --output=change.diff origin/main...HEAD
   ~~~

3. 用 `$briefcheck` 指明 Issue 和 diff 文件。如有相关测试日志，一并提供，并注明日志对应的提交和测试范围。

| 判断 | 含义 |
| --- | --- |
| 有证据支持 | 可见实现或对应的运行结果支持要求 |
| 明确不符 | 可见代码或对应的运行结果与要求直接冲突 |
| 证据不足 | 当前材料覆盖不全或相互矛盾，需补查 |

证据列会区分代码位置、测试用例和测试运行结果。对于 diff 中未显示的行为，补充待审提交里的相关实现或测试结果即可继续核对。

[查看 pandas 公开案例及复现步骤](examples/pandas-18676.md)。

## 许可证

[MIT](LICENSE)
