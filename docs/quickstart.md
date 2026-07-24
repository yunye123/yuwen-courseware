# 首次使用与三场景验收

本说明用于 `v0.1.0` 发布候选的源码检出体验。它把“可由 Python 自动核验的工具链”与“必须在真实 Agent 宿主中完成的课堂流程”分开：前者可以在干净环境运行，后者没有命令行替身，不能据此宣称已经完成课堂验证。

## 准备源码与 Python 环境

```bash
git clone https://github.com/yunye123/yuwen-courseware.git
cd yuwen-courseware
git switch codex/public-v0.1.0
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -q
python -m compileall -q scripts tests
```

Windows 可将前两条 Python 环境命令换为 `py -3 -m venv .venv` 和 `.\.venv\Scripts\Activate.ps1`。Python 必须为 3.10+。`requirements-dev.txt` 固定当前测试使用的 `python-pptx` 版本；其他核心脚本只用标准库。

将仓库完整目录按 Agent 宿主的官方方法安装或配置为可发现的 `SKILL.md` 目录，然后在一个新会话中调用 `yuwen-courseware`。本仓库不包含某一宿主的安装器；宿主是否发现 Skill 要由该宿主实际确认。

## 场景 A：材料完整的常态课

使用 [《窗边的纸飞机》自创安装学习示例](../resources/learning/窗边的纸飞机-安装学习示例.md)，并提供其中列出的版本、课时、班情和设备条件。可向宿主发出：

> 请使用本自创材料，先只生成一页《课堂主线与问题链》；不要代替我确认方向，也不要先生成教学设计、导航稿或课件。

第一份教师可见文件应包含：最值得教的一处、学生可能停留的理解、核心问题、两到三个核心活动及成果、时间路线、风险和待核内容。选择“按推荐方向继续”“切换到另一方向”或“改写核心问题”之一后，再请求：

> 请按已确认方向生成日常教学设计、授课导航稿和白底可编辑 PPTX；完整逐字稿、学案和答案暂不需要。

人工验收：问题、活动、时间、成果和答案展示时机在教学设计、导航稿和学生可见 PPT 页面中一致；PPTX 能在目标软件中打开、编辑和放映。此步骤是宿主工作流验收，不是由仓库内 Python 脚本自动生成的“标准答案”。

## 场景 B：材料不完整

只提供篇目名称，故意不提供可靠原文或版本。预期结果是：宿主说明已知信息和缺口，要求补充合法可核对的原文或权威来源；不把模型记忆当作引文，不生成看似完整的教学设计、导航稿或课件。收到补充材料后才回到场景 A。

## 场景 C：无设备课堂

仍使用场景 A 的自创材料，但明确“投影不可用、无网络、不打印学案”。方向确认后，验收下列结果：

- 核心活动可改用课本、黑板或口头指令；
- 学生任务可在无打印学案时完成；
- 授课导航稿写出无设备处理与超时删减；
- PPTX 是辅助材料，不是课堂继续进行的唯一载体；
- 不出现依赖实时互动技术的环节。

## 可自动运行的辅助检查

对教师版教学设计可运行：

```bash
python scripts/check.py <教学设计.md>
```

该检查器只守结构、时间、预设数量、格式与篇幅等机械合同。对使用者已经合法提供的 UTF-8 原文，可按 [资料工作流](../references/workflows/source-materials-and-history.md) 准备逐字校对清单，再运行 `scripts/quote_check.py`。PPTX 导出和测试需要 `Source Han Serif SC`；单元测试会用 `python-pptx` 程序化打开生成的 PPTX，但这不等于已经在你的 PowerPoint/WPS 版本中试放。

`scripts/verify_install.py` 只接受带根目录 `manifest.json` 的封存安装包。源码检出目录没有该发布清单，因此不要把它作为本页克隆步骤的验收命令。

## 常见问题

- **Python 版本过低或缺依赖**：确认 `python --version` 不低于 3.10，再重新激活虚拟环境并执行 `python -m pip install -r requirements-dev.txt`。
- **宿主找不到 Skill**：确认整个仓库目录而非单个 `SKILL.md` 已按宿主官方方式安装；开启新会话后再检查。不同宿主的安装位置不同。
- **没有可靠原文**：停止生成引用性成品，补充版本明确、可合法使用的原文或权威来源。
- **PPTX 字体或显示异常**：安装 `Source Han Serif SC`，在实际授课电脑的 PowerPoint/WPS 中打开、编辑和试放；不要以本机测试替代。
- **没有可点击附件**：由宿主提供可复制的文件路径或直接附文件；仍要先给教师版成品，不显示内部报告。
- **需要 DOCX/PDF**：用学校认可的工具从已确认 Markdown 转换，并单独核验分页、打印和字体。
- **个人资料目录未配置**：显式设置 `YUWEN_DATA_HOME` 到私有目录；不得使用仓库目录保存真实教材、学生信息或生成课例。
