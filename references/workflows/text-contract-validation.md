# 跨产物文本合同与 PPT 文字稿校验

> 适用阶段：`text-contract`、`ppt-text`
> 性质：确定性结构门；不能代替事实核查、语文教学判断、在线双路审查或使用者批准。

`<PYTHON>` 由宿主先解析为已验证的 Python 3.10+ 执行器：macOS/Linux 通常为 `python3`，Windows 通常为 `py -3`。

## 文本合同门

教学设计与逐字稿完成后进入本门。课堂选择学案时，学生学案与教师参考答案也必须已成对完成。

`text-contract.json` 是跨文件内容哈希的唯一绑定点。学生学案、教师答案和逐字稿正文只记录上游批准记录，不互抄彼此文件哈希；因此单个文件的机械修订不会仅为更新头部哈希而级联改写其他正文。

1. 复制 `assets/templates/text-contract.json` 到课例目录，替换示例值。
2. 根据老师在教学设计阶段的决定选模式：无学案使用 `mode: "ppt-only"`，有学案使用 `mode: "handout"`。旧课例没有 `mode` 时只按历史 `handout` 口径兼容。
3. `ppt-only` 的 `artifacts` 只绑定教学设计和逐字稿；`handout` 另加学生学案和教师参考答案，两者不得缺一。每个角色记录冻结文件的 SHA-256 和实际出现的稳定 ID。
4. 建立目标、材料、任务、评价、答案和讲稿块的显式关系；材料必须记录来源 ID 与权利状态。`ppt-only` 中每个课堂任务都必须 `ppt_required=true`，逐字稿必须覆盖任务、评价、答案与讲稿块。
5. 按模式运行。无学案路线：

```text
<PYTHON> scripts/validate_text_contract.py text \
  --contract <text-contract.json> \
  --artifact teaching-design=<教学设计.md> \
  --artifact teaching-script=<逐字稿.md> \
  --report <新的不可变校验报告.json>
```

有学案路线再在同一命令中增加 `student-handout=<学生学案.md>` 与 `teacher-answer=<教师参考答案.md>`。

只有 `ok=true` 才能进入在线双路审查和教学内容核对。报告结构见 `references/schemas/contract-validation-report.schema.json`。批准 `text-contract` 阶段时，必须同时登记 `text-contract=<合同JSON>` 与 `text-contract-report=<ok=true 的不可变报告JSON>`；状态守卫会按当前模式读取两份或四份教学文本，并与当前有效记录一一核对。面向老师只提供完整教师版文件，并询问“有没有漏项，或前后说法不一致”，不提供合同 JSON 或检查报告。缺一、报告未通过或报告拿错版本均不得放行。校验器会拒绝：

- 未声明、重复或断链的 `OBJ/MAT/TASK/ASM/ANS/SCRIPT` ID；
- 目标没有任务或评价、任务没有评价或讲稿块；
- 题目与答案不能双向对应；
- 学生版出现答案、评分点、教师提示或 `ANS-*`；
- 合同哈希与文件字节不一致；
- 合同绑定的 ID 与文件实际 ID 不一致；
- `TODO/TBD/PLACEHOLDER/待填写/此处讲解` 等未解决占位语。

合同模板中的零哈希和占位值故意不能通过生产校验，不得把模板本身冒充完成记录。

## PPT 文字稿门

文本合同批准后：

1. 复制 `assets/templates/ppt-text-structured.json`，在结构化文件中完整记录每页页码、标题、屏显、教师备注、任务、目标、讲稿块、答案 ID 和揭示状态。
2. `text_contract_sha256` 先绑定已批准文本合同；然后运行 `render-ppt` 生成唯一的人类可读 Markdown 投影：

```text
<PYTHON> scripts/validate_text_contract.py render-ppt \
  --ppt-json <ppt-text-structured.json> \
  --output <新的 PPT逐页文字粗稿.md>
```

3. 把命令返回的 SHA-256 写入结构化文件的 `ppt_text_sha256`。不得手工改写已投影的 Markdown；需要修改时先改 JSON，再生成新的 Markdown 路径。
4. 使用同一模式下的冻结文本再次验真并运行。无学案路线：

```text
<PYTHON> scripts/validate_text_contract.py ppt \
  --contract <已批准 text-contract.json> \
  --ppt-json <ppt-text-structured.json> \
  --artifact teaching-design=<教学设计.md> \
  --artifact teaching-script=<逐字稿.md> \
  --artifact ppt-text=<PPT逐页文字粗稿.md> \
  --report <新的不可变校验报告.json>
```

有学案路线再增加学生学案与教师参考答案两个 `--artifact`。

PPT 校验还会拒绝页码断档、空标题/屏显/备注、讲稿或答案与任务错配、结构化 JSON 与 Markdown 的任何文字漂移，以及在 `student-blank`、`prompt` 或 `neutral` 页面提前绑定答案。每个课堂任务都必须在学生可见页完整写出问题、活动、时间、成果与交流或提交方式。只有 `answer` 或 `summary` 页面可以绑定 `ANS-*`。批准 `ppt-text` 阶段时，必须同时登记 `ppt-text=<确定性投影Markdown>`、`ppt-structured=<结构化JSON>` 和 `ppt-contract-report=<ok=true 的不可变报告JSON>`；报告必须同时绑定当前有效文本合同、结构化源和 Markdown 投影的哈希。

## 失败处理

- 校验失败时保持当前阶段为 `draft/review`，修正文档或合同后生成新的报告路径。
- 报告文件不可覆盖；不要删除失败报告来伪装首次通过。
- 上游内容实质变化时，重新计算哈希并按状态守卫的受控修订流程失效下游；不得只改合同数字。
