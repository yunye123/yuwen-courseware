# 每课备课生产工作流 v2

> 状态：active
> 适用范围：真实课例生产主线
> 核心原则：老师负责目标、取舍与批准；常态课先确认一页课堂主线与问题链，再完成日常教学设计、授课导航稿与白底课件。完整逐字稿和学案只在课堂需要时增加。

老师可见的对话、选择、文件预览与交付方式一律按 `teacher-interaction.md` 执行；教师成品的内容质量一律按 `teacher-ready-content.md` 执行。本文件中的英文阶段名、内部记录和检查办法只供宿主在后台使用，不得原样转述给老师。

## 目录

- [三条线不得混淆](#1-三条线不得混淆)
- [规范阶段与批准](#2-规范阶段与批准)
- [教学设计闭环](#3-第一段教学设计闭环最高优先级)
- [派生文本资源](#4-第二段派生文本资源)
- [PPT 文字粗稿与外部交接](#5-第三段ppt-文字粗稿与外部设计交接)
- [教师成品整理](#6-教师成品整理)
- [包状态](#7-包状态)

## 1. 三条线不得混淆

1. **真实备课生产线**：本文件规定的必走主线。任何课例均可立即开工，不等待八课型基准全部完成。
2. **使用反馈线**：只有老师明确同意提供真实修改或课堂反馈时，才用于其个人经验改进；不是每次备课的启动门槛，也不进入公开仓。
3. **公开发布线**：公开核心版不随包发布内部研究、验证或个人资料；这些资料不能成为教师成品或备课前置条件。

## 2. 规范阶段与批准

所有宿主和课例状态文件必须使用同一组阶段 ID；中文名称可以展示，ID 不得自行改写或合并：

| 阶段 | 稳定 ID | 阶段门 |
|---|---|---|
| 0 | `lesson-brief` | 教师需求、课型用途、课时、教材与课标版本、学情和学生学习困难已确认 |
| 1 | `research-plan` | 检索问题、来源组合、检索词、风险和研究充分条件已确认 |
| 2 | `evidence-dossier` | 证据分级、关键事实、教师经验线索、冲突和缺口已确认 |
| 3 | `stance-selection` | 2—3 个实质不同的教学立意已比较，并由使用者选择或组合 |
| 4 | `route-freeze` | 关键主张完成核验，争议边界与选定路线冻结 |
| 5 | `teaching-design` | 教学设计通过确定性检查、在线双路审查和使用者确认 |
| 6 | `student-resources` | 可选：课堂需要学案且老师同意时，学案/练习与教师参考答案已成对确认 |
| 7 | `teaching-script` | 授课导航稿已确认，课时、追问、纠偏和删减方案可执行 |
| 8 | `text-contract` | 教学设计、授课导航稿、可选学案与课件所用问题、答案口径已核对一致 |
| 9 | `ppt-text` | 白底课件的逐页内容已确认并可导出；可按需形成外部设计交接单 |
| 10 | `external-ppt-check` | 可选：外部返稿完成内容一致性核对 |
| 11 | `release` | 中文教师成品文件夹与私有课例归档分别完成检查 |

阶段 6 和阶段 10 可选。教学设计确认后，若课堂不需要纸质学案或老师明确不要，直接进入授课导航稿；需要时才进入阶段 6。阶段 9 批准后，未请求外部设计时直接进入阶段 11；请求外部设计并把返稿纳入商业交付时才进入阶段 10。

与老师沟通时默认收敛为三个真正需要做教学取舍的决策点：课堂主线与问题链方向、教学设计确认、成品验收。教学设计确认时同时判断是否需要学案。授课导航稿完成后另有一次独立但极短的“教学内容核对”：宿主必须先给出教学设计、授课导航稿与可选学案的完整教师版文件，只请老师确认有没有漏项或前后说法不一致，不展示后台文件，不再要求选路线。其余中间阶段由宿主用中文汇报完整文件、具体内容例子、检查结论和下一步。状态守卫仍在后台逐阶段留存记录。

需要老师选择时，先检查宿主真实可用的交互能力：有按钮、选项卡、表单或对话框就直接调用；没有时只给 2—3 个短选项并让老师回复序号。一个确认点只承载一个决定。任何批准请求之前，都必须先提供可打开的完整教师版文件，不能只给摘要。

`teaching-design`、`text-contract`、`release` 是三条独立确认红线，任何批量确认都不得包含它们。面向老师时分别称为“教学设计确认”“教学内容核对”“成品验收”。“教学内容核对”必须让老师看完整教师版文件，不能让老师审核后台合同或报告。

### 2.1 状态守卫由宿主调用

状态守卫使用当前 Skill 目录中的 `scripts/lesson_state.py`，需要 Python 3.10+，只使用标准库。宿主先把下文 `<PYTHON>` 解析为实际可执行的 Python 3：macOS/Linux 通常为 `python3`，Windows 通常为 `py -3`；必须先验证版本不低于 3.10，不能假定 Windows 存在 `python3`。使用者只需要在对话中审阅和确认，以下命令由当前宿主智能体在解析 Skill 目录后执行：

```text
<PYTHON> scripts/lesson_state.py doctor --data-home <data-home>
<PYTHON> scripts/lesson_state.py init --data-home <data-home> --lesson-id <lesson-id>
<PYTHON> scripts/lesson_state.py status --data-home <data-home> --lesson-id <lesson-id>
<PYTHON> scripts/lesson_state.py verify --data-home <data-home> --lesson-id <lesson-id>
<PYTHON> scripts/lesson_state.py approve --data-home <data-home> --lesson-id <lesson-id> --expected-revision <revision> --user-id <实际确认者> --confirmation <课例内确认JSON> --input <ROLE=PATH>
<PYTHON> scripts/lesson_state.py revise --data-home <data-home> --lesson-id <lesson-id> --expected-revision <revision> --stage <已走过阶段> --user-id <修订发起者> --reason <原因> --confirmation <课例内用户修订确认JSON> --input <新ROLE=PATH>
```

`verify` 的机器状态必须按下列口径解释，不能只看“没有普通问题”就口头宣称通过：

- 正常验真通过：`verification_status=pass`、`ok=true`、退出码 `0`。
- 历史审批产生于逐字校对字段引入之前，且已附符合当前红线的追溯核对和版本边界记录：`verification_status=historical-compatible-retrospective-evidence`、`ok=false`、退出码 `3`。该状态允许审批链继续，但必须原样披露，不能改写成 `pass`；追溯记录不得冒充审批当时已经存在。
- 其他验真问题：`verification_status=failed`、`ok=false`、退出码 `1`，必须停止推进。

历史兼容只允许新增追溯证据，不得伪造旧报告、回写冻结审批快照或放松事实与引文红线。

- 数据根目录只能由 `--data-home` 或 `YUWEN_DATA_HOME` 明示，永不默认为当前目录。
- `init` 只创建全新课例，且强制从 `lesson-brief/draft` 开始。无 `state.json` 的旧课例使用 `adopt --current-stage ... --status draft|review|invalidated --user-id ... --reason ... --artifact ROLE=PATH`；已有旧版 revision-0 接管状态但缺快照时，才使用 `repair-adoption`。接管记录只证明旧课例的当前起点，不等于补造历史审批，也不允许 `status=approved`。
- `approve` 前必须重新读取状态与验真，并把当前阶段全部获批产物按 `ROLE=PATH` 逐项传入；意见或限制分别写入 `--comment` 与可重复的 `--limit`。相同路径或相同内容不能冒充不同阶段产物。上游返工使下游审批失效后，若某下游产物的角色、路径和 SHA-256 与原失效审批完全相同，可在 `approve` 增加 `--rebuild-from <原审批号>` 做同内容重建；新审批会标注 `rebuild` 和继承审批号，不要为了过门制造新字节。
- 已批准上游需要实质修改时，不得覆盖旧文件或手改 `state.json`。只有使用者在宿主会话中真实作出修订决定后，宿主才能据该条消息创建 `user-revision-confirmation`，把新版本另存为课例目录内的新文件并运行 `revise`；AI 不得根据评审意见自行补造修订确认。工具以 `--expected-revision` 做并发保护，只允许回到当前链已经到达且不晚于当前阶段的节点，要求新 `ROLE=PATH` 内容哈希确有变化，并把确认文件的路径、哈希和大小绑定进只读 `invalidations/*.json`。该阶段及其下游的当前有效审批全部失效，但旧审批、旧输入和哈希历史继续保留；状态回到目标阶段 `draft`。
- 修订后的阶段必须以 `revise` 登记的同一组角色、路径与哈希重新审查和批准，随后逐阶段重建下游。`state.json` 中 `approvals` 是不可变历史，`active_approval_ids` 才表示当前有效审批；任何宿主不得把已经列入失效记录的旧审批当作当前放行依据。
- PPT 文字粗稿批准后默认跳过可选阶段 10，直接进入阶段 11；只有使用者明确要求把外部返稿纳入本包时才传 `--next-stage external-ppt-check`。
- `state.json`、`approvals/*.json`、`invalidations/*.json`、`reviews/*.json`、`adoptions/*.json` 和 `conflicts/*.json` 不得手改；历史输入、快照、登记文件或阶段链发生漂移时，`verify` 与下一次 `approve`、`revise` 都必须失败。同一课例的审批、返工、接管修复和中断恢复由跨进程互斥锁串行化，竞争请求必须重读状态再重试，不得各自写回。若一份完整审批或失效快照因进程中断没有写回状态，使用 `recover --expected-revision <revision>` 做全量验真接回；不能手工删除它。
- Python、脚本或 Schema 缺失时报告“自动阶段守卫不可用”，不得把手工状态或聊天上下文冒充自动验证通过。

当前阶段至少要提供下列角色化产物；可以增加辅助输入，不能缺少必需角色：

| 阶段 ID | 必需 `ROLE` |
|---|---|
| `lesson-brief` | `lesson-brief` |
| `research-plan` | `research-plan` |
| `evidence-dossier` | `evidence-dossier` |
| `stance-selection` | `stance-selection` |
| `route-freeze` | `route-freeze` |
| `teaching-design` | `teaching-design` |
| `student-resources` | 仅在选择学案路线时使用：`student-handout`、`teacher-answer` |
| `teaching-script` | `teaching-script` |
| `text-contract` | `text-contract`、`text-contract-report` |
| `ppt-text` | `ppt-text`、`ppt-structured`、`ppt-contract-report` |
| `external-ppt-check` | `external-ppt-check` |
| `release` | `package-checklist`、`manifest` |

使用者同意当前阶段后，宿主把该次真实决定留存在课例内部记录中；不得根据审查结果自动代写“使用者同意”。以下结构只供后台使用，不得显示给老师：

```json
{
  "record_type": "user-confirmation",
  "lesson_id": "<lesson-id>",
  "stage": "<current-stage>",
  "user_id": "<actual-user-id>",
  "decision": "approve",
  "source": "host-conversation",
  "host": "<codex-or-claude-code-or-other-host>",
  "conversation_id": "<host-conversation-id>",
  "message_id": "<actual-user-message-id>",
  "confirmed_at": "<ISO-8601-time>",
  "decision_text": "<the-user's-actual-decision>"
}
```

教学设计阶段的单次确认还必须加入 `"resource_choice": "ppt-only"` 或 `"resource_choice": "handout"`，分别表示“本课不设学案”与“本课需要学案和教师参考答案”。它必须来自老师在当前对话中的明确决定，并与实际下一步一致；宿主不得自行猜测。

批量确认使用同样的真实会话来源，但把 `record_type` 改为 `user-batch-confirmation`，并用按工作流顺序排列的 `stages` 代替单一 `stage`：

```json
{
  "record_type": "user-batch-confirmation",
  "lesson_id": "<lesson-id>",
  "stages": ["lesson-brief", "research-plan", "evidence-dossier"],
  "user_id": "<actual-user-id>",
  "decision": "approve",
  "source": "host-conversation",
  "host": "<host>",
  "conversation_id": "<host-conversation-id>",
  "message_id": "<actual-user-message-id>",
  "confirmed_at": "<ISO-8601-time>",
  "decision_text": "<the-user's-actual-decision>"
}
```

使用者明确要求回改已批准阶段时，宿主另存一份同样可追溯的修订确认；`reason` 必须与 `revise --reason` 完全一致：

```json
{
  "record_type": "user-revision-confirmation",
  "lesson_id": "<lesson-id>",
  "stage": "<target-stage>",
  "user_id": "<actual-user-id>",
  "decision": "revise",
  "source": "host-conversation",
  "host": "<codex-or-claude-code-or-other-host>",
  "conversation_id": "<host-conversation-id>",
  "message_id": "<actual-user-message-id>",
  "confirmed_at": "<ISO-8601-time>",
  "decision_text": "<the-user's-actual-revision-decision>",
  "reason": "<same-value-as-revise---reason>"
}
```

`teaching-design`、`text-contract` 和 `release` 在 `approve` 前必须先对 route-freeze 登记的“逐字校对清单”运行确定性原文比对，再对同一组 `ROLE=PATH` 输入各运行一次 A/B 路在线审查：

```text
<PYTHON> scripts/quote_check.py --checklist <逐字校对清单.json> --output <逐字校对报告.json>
```

只有报告 `ok=true`、`different=0` 才允许进入双路评审。校对器只忽略换行、空格等排版空白，不会把异体字或近义字自动当成相同。评审守卫将校对报告的路径、哈希和大小绑定到评审记录：

```text
<PYTHON> scripts/lesson_state.py record-review --data-home <data-home> --lesson-id <lesson-id> --stage <stage> --reviewer-id <persona-id> --persona-version <persona-version> --route-id <route-a-or-b> --provider <provider> --model <model> --runtime-mode online --run-id <provider-run-id> --prompt-version <prompt-version> --quote-check-report <逐字校对报告.json> --report <review-report-path> --verdict pass|fail --input <ROLE=PATH>
```

只有两路均为 `pass`、`reviewer-id`、`route-id`、`run-id` 和报告文件分别不同、输入哈希与待批准产物完全一致时，工具才允许使用者审批。审查失败只留下证据并返回修订，不会自动推进阶段。使用者退回或尚未表态时，不创建 user-confirmation，不运行 `approve`。

工具验证的是“可审计声明 + 不可变哈希链”，不是安全级身份认证：它无法在一个恶意或不遵守 Skill 的宿主上，独立证明 user-confirmation 一定由真人输入，或 `runtime-mode=online` 一定获得了供应商回执。宿主必须保留实际会话消息 ID、运行 ID 和评审报告，且不得自行伪造。若业务需要对不可信宿主做强认证，必须另接外部签名/供应商验证服务，当前 alpha 未实现。

每个阶段产物必须写明：`lesson_id`、输入版本或哈希、`status`、生成时间、已知缺口和批准记录。

- `draft`：可修改，不得驱动下游正式产物。
- `review`：正在核对，不得越级。
- `approved`：使用者确认，可以驱动下一阶段。
- `invalidated`：上游发生实质变化，依赖产物失效待重审。

使用者批准负责目标、取舍和发布决定；在线 AI 双路审查负责发现事实、教学、答案、课堂执行和跨产物风险。两者不能互相替代。

## 3. 第一段：教学设计闭环（最高优先级）

### 0. 备课开课单

使用 `assets/templates/00-lesson-brief.md`，先确认：

- 教材版本、篇目、单元、课时和使用场景；
- 具体教师的教学风格、现实限制和希望解决的问题；
- 学生已有基础、真实困难、常见误解、班级差异与可见学习结果；
- 是否需要 AI 赋能，以及 AI 不应替代学生思考的边界；
- 用户已有材料和不可改变的要求。

未知信息必须标为“待确认”或显式假设，不能由模型补写成事实。开课单批准后才进入研究。

### 1. 研究计划与证据包

使用 `assets/templates/01-research-dossier.md`。每课至少执行以下检索层：

1. 当前老师的个人历史课例与已确认经验，以及可用的共享知识源、项目/用户案例库或用户上传材料；
2. 老师提供、已获授权或可公开核验的课程标准、教材、课文、教师教学用书等一手材料；材料不完整时先列出缺口，不得用模型记忆补写；
3. 权威学术资料、辞书、出版社和专业机构资料；
4. 一线教师文章、公开课与教研分享；
5. 小红书、微信公众号、B站等平台中的课堂问题、情境创意与经验线索。

社交平台内容主要提供需求、经验和创意线索；事实、引文、教材版本和课标依据必须回到更高等级来源核验。平台无法访问、视频无字幕或证据不足时，输出缺口报告、检索词和人工补料清单，不得想象补齐。

用户私有资料库不是安装前提，但“本课资料核对 + 联网检索”仍是每课必走的证据动作：先确认老师提供材料的版本、出处和可用范围，再检索当前用户可用的历史资产。没有个人历史时如实记录“首次备课或未命中”；联网检索必须在能联网的宿主中单独留下查询、时间、命中或失败记录。两者都未尝试前，不得作出“研究充分”裁决。

可公开核验的课标、教材或官方材料须直接记录其发布者、版本、链接和查阅时间；老师提供的非公开材料只限本课使用，必须记录来源、可用范围和非公开状态。每课开工时锁定实际使用版本。

研究充分的判断不是“链接够多”，而是同时满足：

- 教材、课标和核心文本版本可追溯；
- 关键事实和高风险主张已有可靠证据；
- 教师需求与关键学习障碍及其证据强弱得到回应；
- 至少形成可比较的教学立意、情境或任务候选；
- 争议解释、权利风险和仍缺材料均已显式列出。

主问题或核心任务属于每课研究的重点，不是写教案时临时补一个开场。研究计划必须显式提出：关键学习障碍是什么、其证据强弱如何；哪些文本反常处、知识缺口、策略缺口或表达任务可以启动核心问题；是否需要专门导入或整课情境，直接从文本疑点或核心任务进入是否更有效。若使用情境，再核对其是否通过“去皮、入文、统摄、成果”四项检验。联网结果只作为创意与实践线索，关键事实和引文仍回到可靠来源核对。

### 2. 教学立意候选与选择（阶段 3）

基于同一证据包给出 2—3 个真正不同的候选，不以换标题冒充不同方案。每个候选说明：

- 核心问题或核心任务及文本依据；
- 对应的教师需求、关键学习障碍及其证据强弱；
- 预期学生产出与评价证据；
- 若使用情境或创意，它为什么能改善学习；
- AI 赋能的真实价值、风险和不用 AI 的替代；
- 课时可行性和主要取舍。

使用者选择或组合后形成冻结的设计合同；未经重新批准不得在下游偷偷更换主线。

随后进入阶段 4 `route-freeze`：核对关键事实、引文和解释边界，把选定路线、证据版本与已知限制写入冻结记录。同时登记一份 `verbatim-quote-checklist` JSON：`sources` 指向课例目录内的教材/教参 UTF-8 全文，`quotes` 逐条登记 `quote_id`、`source_id` 和实际使用引文 `text`。原文不得使用课例目录外路径。阶段 4 未获批准，不得生成完整教学设计。

### 3. 教学设计（阶段 5）

使用 `assets/templates/02-teaching-design.md`，并完整执行 `teacher-ready-content.md` 与 `teaching-design-decision-review.md`。先完成内部课程导演推演：标注学情证据，识别关键学习障碍及其类型，确定一个核心达成、最多两个必要支撑、唯一突破口、明确舍弃和课堂路径；这些内容不逐项打印。教学过程必须成为正文主体；每个核心活动写清任务与材料、教师组织与关键话语、学生行动、评价与时间。导入和整课情境先判断必要性；备选立意的比较属研究记录，不写入成稿正文。板书必须给出文字空间预览和随课堂生成的落笔顺序。

教学设计严格只含九个板块。总时长不超过 60 分钟时，建议成稿 2500 至 3500 字、教学过程建议不少于七成；超过 3500 字时优先删说明和重复交代，不删课堂成品话语、检测题与作业。总时长超过 60 分钟时，固定字数合同不适用，由教师人工判断篇幅。前置说明、目标与重难点建议合计控制在 300 字以内。每个教学过程环节均标注分钟，并有“师：”“生：”“预设：”“应对：”“板书随写：”；承担核心问题推进的环节再写“预设（误）：”。全课至少六处“预设”、两处“预设（误）”，时间合计等于课时。不得为了满足格式虚构错答。板书只用文字节点；需要表达关系时可用 `→`，不使用表格、框线或特殊图形。

生成教师版、清除 HTML 内部注释后，运行 <PYTHON> scripts/check.py <教学设计.md>。检查器只执行机械可判定的教学设计成稿合同检查，不评价教学立意、文本解读深度、问题质量或课堂创新；检查结果只用于内部修改，不进入教师成稿。教学设计是下游设计源：不得为了减字删去核心问题、关键预设或课堂推进逻辑。教学设计完成后默认进入“教学设计确认”；未经老师确认，不得自动生成逐字稿或 PPT。

教学目标、任务、学生产出、评价、教师支架、时间和删减方案必须一一对应。内部映射只能写入模板顶部明确标记的 `YUWEN_INTERNAL_MAPPING` 注释或使用者私有结构文件，不得把内部编号列放进教师正文。情境、创意与 AI 只有在直接改善理解、表达、反馈或评价时才保留。

### 4. 教学设计质量门（阶段 5 批准条件）

教学设计先做确定性事实核查，再做两路相互隔离的在线 AI 审查：

- A 路：课标、教材、事实、文本解释、目标—任务—评价和答案风险；
- B 路：真实课堂执行、学生认知负荷、学情适配、情境有效性和课时可行性。

使用者看到完整、已清洗的教师版教学设计文件，以及用教研语言写的设计摘要、主要取舍和未决问题后批准。质量审查摘要、来源代码和编号映射留在内部。教学设计未批准，不得生成学案、授课导航稿或白底 PPT。

## 4. 第二段：授课导航稿与可选学生资源

教学设计批准后，先根据课堂设计作出学案判断：

- 学生需要纸面记录、当堂提交、较长材料或大面积书写空间，且老师同意：生成学案与教师参考答案；
- 课堂可以由课件、口头交流、板书或学生自备纸完成，或老师明确不要学案：跳过学案，直接生成授课导航稿。

学案路线从同一目标—任务—评价映射派生：

1. `assets/templates/03-student-handout.md`：学生学案或同步练习，不得泄露答案；
2. `assets/templates/04-teacher-answer.md`：答案、解析、评分点、可接受的不同答案、常见错误与反馈；
随后无论是否有学案，都使用 `assets/templates/05-teaching-script.md` 生成授课导航稿。导航稿第一页给整课路线与时间锚点；正文只在开场、关键任务指令、学生卡住、重要转场和课堂收束写完整话语，并紧邻安排等待时间、学生反应分支、追问纠偏、翻页与板书动作、转场和超时删减。生成后模拟“低头一眼能否接着上、沉默时能否接住、超时五分钟能否立刻删减”。没有独立教师答案时，必要的参考答案、可接受的不同答案、反馈语和评分依据必须进入导航稿旁注或课件备注，不能消失。完整逐字稿只在新教师、实习、面试、公开课或老师明确需要时，沿用同一结构补足普通讲解话语。

产物完成后执行跨成品审查：编号、事实、任务顺序、时间、题目与答案必须一致。有学案时核对教学设计、学案、参考答案和授课导航稿；无学案时核对教学设计与授课导航稿，并要求所有学生任务进入 PPT。确认后才进入课件制作。

三份正文不互抄彼此文件哈希；跨文件内容哈希只在 `text-contract.json` 中绑定。受控修订同一阶段的多角色产物时，未改动角色必须显式沿用原路径和原哈希，守卫只要求改动角色使用新的不可变文件路径。

## 5. 第三段：白底课堂课件与外部设计交接

使用 `assets/templates/06-ppt-text-draft.md` 生成逐页完整内容并导出白底课堂课件。每页至少包含：

- 页面 ID 与页面类型；
- 页标题和全部屏显文字；
- 学生可见的核心问题、活动步骤、作答时间、成果形式与汇报方式；
- 教师备注与授课导航稿映射；
- 对应目标、任务、材料和来源 ID；
- 可选的素材方向、信息层级或版式建议。

教学设计中的每个核心问题和课堂活动都必须至少映射到一张学生可见页面。没有学案时，题目正文、所需材料、操作步骤与提交要求必须完整显示在 PPT 中；只写在教师备注里不算。

本 Skill 默认导出 16:9、白底黑字、文字可编辑、带教师备注的课堂 PPTX，不生成图片、动画或精装视觉设计：

```bash
<PYTHON> scripts/export_text_pptx.py <已批准的结构化PPT.json> <导出目录> --approval-record <ppt-text批准记录.json> --expect-source-sha256 <冻结JSON的SHA-256> --name <白底课件文件名>
```

机器必须已安装 python-pptx 和思源宋体 `Source Han Serif SC`；缺失时由宿主在后台处理并用自然中文说明。溢出页必须回到内容阶段减字。若使用者需要外部美化，再用 `assets/templates/07-ppt-design-handoff.md` 固定内容与交接边界，交给其他工具或真人设计师；不需要外部美化时可直接进入教师成品发布检查。

外部精装 PPT 返回后，可使用 `assets/templates/08-returned-ppt-content-check.md` 核对是否漏页、漏字、错字、改写事实、泄露答案或破坏任务顺序。本 Skill 只对内容一致性负责，不替代视觉设计师的审美和版式验收。

## 6. 教师成品整理

阶段 9 的课件内容获批后，才整理教师可编辑文件。公开核心版默认交付课堂主线与问题链 Markdown、日常教学设计 Markdown、授课导航稿 Markdown 与白底课件 PPTX；选择学案路线时再增加学生学案 Markdown 与教师参考答案 Markdown。完整逐字稿只按需增加。老师如需 DOCX/PDF，应使用学校认可的转换工具自行生成，并在目标设备中实际核验。

教师交付文件夹只放最终成品，全部使用中文名称；研究记录、来源台账、检查报告、批准记录、结构数据和中间稿保留在老师的私有课例归档中，不进入交付压缩包。交付前用 `assets/templates/09-package-checklist.md` 做人工检查；这不是自动发布或商业合规保证。

白底 PPTX 必须在目标授课设备中打开、编辑与放映检查；当前设备未实测的组合要明确写成待验证，不能用本机导出成功代替。外部精装 PPT 不属于此门禁。

## 7. 包状态

`package_status` 只追踪本 Skill 的教师成品：

- `teaching-design-approved`：教学设计已批准，可生成下游文本。
- `content-pack-approved`：教学设计和授课导航稿已批准；若选择学案，学案与参考答案也已批准。
- `ppt-text-approved`：白底课件逐页内容已批准，可进入发布检查；也可按需交外部设计。
- `final-package-ready`：课堂主线与问题链、教学设计、授课导航稿、白底 PPT，以及所选的学案与参考答案齐全；教师交付文件夹与私有课例归档均已分别完成检查。

`external_ppt_status` 单独追踪可选外部设计：

- `not-requested`：本包不需要外部精装 PPT。
- `design-handoff-ready`：文字冻结、交接单和素材权利说明齐全，可交外部设计。
- `returned`：外部 PPT 已返回，尚未完成内容核对。
- `content-checked`：外部 PPT 已按确认文字稿完成内容一致性核对。

使用 `assets/templates/09-package-checklist.md` 做最终清单。外部精装 PPT 未返回不阻断 `final-package-ready`；若外部 PPT 被纳入商业交付，再单独完成内容核对，其审美与办公软件技术验收仍由外部设计方和老师负责。
