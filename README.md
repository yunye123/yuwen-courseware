# yuwen-courseware

[![public verify](https://github.com/yunye123/yuwen-courseware/actions/workflows/verify.yml/badge.svg)](https://github.com/yunye123/yuwen-courseware/actions/workflows/verify.yml)

高中语文备课 Agent Skill 的公开学习参考版。当前目标版本为 **v0.1.0 发布候选**，仍是技术预览：它帮助教师先确认一页《课堂主线与问题链》，再把已确认的资料组织成日常教学设计、授课导航稿、可视化板书和白底可编辑 PPTX；完整逐字稿、学案和教师参考答案按课堂需要生成。

它适合熟悉基本命令行和 Agent Skill 安装方式、愿意核对并修改成品的高中语文教师或教学设计研究者。它不是教材产品、商业交付系统，也不替代教师的专业判断、教材核验、试讲和真实课堂反馈。

## 能做什么，不能证明什么

本候选版包含：

- 常态课流程、首件《课堂主线与问题链》、一次方向确认；
- v2.1 教学设计课程导演规则、九板块教学设计模板和机械成稿检查器；
- 授课导航稿、按需完整逐字稿、白底可编辑 PPTX、引文核对、文本一致性与教师版过滤；
- 空白真实教师验证模板、公开边界和 GitHub Actions `verify` 检查；
- 一篇仅供安装与流程演示的自创材料。

本候选版不包含教材、课程标准、教参、教师课例、学生信息、字体、模型、Office/WPS、DOCX/PDF 样式、模式卡、私有评测材料或真实教师试用数据。它也尚未证明能减少备课时间、适用于所有课型、无需教师修改即可授课，或已产生课堂学习效果。

## 默认流程与成品

1. 使用者提供本课可合法使用、可核对的原文、版本、课时、学情和课堂条件。
2. Skill 先给出一页《课堂主线与问题链》；教师确认推荐方向、切换方向或改写核心问题。
3. 方向确认后，生成日常教学设计、授课导航稿和白底可编辑 PPTX。
4. 完整逐字稿、学案和教师参考答案仅在课堂确有需要且教师同意时增加。

默认文件是《课名》课堂主线与问题链.md、《课名》日常教学设计.md、《课名》授课导航稿.md 和《课名》白底课件.pptx。Markdown 是可编辑源文件；如需 DOCX/PDF，应使用本校合规工具转换，并在实际授课设备中打开、编辑和打印检查。

## 使用前准备

- Python 3.10+；本候选版的测试依赖固定为 `python-pptx==1.0.2`。
- 一个支持 `SKILL.md` 的 Agent 宿主。按该宿主的官方方法使本仓库完整目录可被发现；本项目不提供宿主安装器。
- 真实备课使用者自行合法提供的原文、教材版本与必要资料；个人课例资料保存在 `YUWEN_DATA_HOME` 指向的私有目录，绝不提交到本仓库。
- 如需实际导出 PPTX，目标机器还要安装 `Source Han Serif SC`（思源宋体）；字体不随项目分发。

## 十分钟首次体验

这里的“十分钟”只指理解并启动自创示例流程，不承诺在十分钟内完成真实课例备课。请按 [首次使用与三场景验收](docs/quickstart.md) 操作：它使用 `resources/learning/窗边的纸飞机-安装学习示例.md`，分别说明材料完整、材料缺失与无设备课堂时应出现什么结果。

最小 Python 检查：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -q
python -m compileall -q scripts tests
```

`scripts/check.py` 只检查教学设计的板块、时间、预设、格式和篇幅等机械合同，不评价教学质量。`scripts/verify_install.py` 只适用于另有根目录 `manifest.json` 的封存安装包，**不**适用于本源码检出目录；两种验真不要混为一谈。

## 原文缺失、字体和 Office 限制

没有可靠原文或版本时，Skill 应明确列出已知信息、待补材料和下一步，而不是凭模型记忆补写引文或生成虚假完整成品。PPTX 由 `python-pptx` 导出；字体缺失、PowerPoint/WPS 版本差异、宿主不能附加可点击文件等问题，均需按 [首次使用与三场景验收](docs/quickstart.md#常见问题) 的最小处理方式在目标环境复核。

## 验证状态、版本与反馈

GitHub Actions `verify` 和本地单元测试覆盖公开代码、模板与边界合同；自创示例用于流程演示。真实教师试用框架保留在 [validation/real-teacher-trials](validation/real-teacher-trials/README.md)，其中只有空白模板，尚未产生教师、课堂或学生结论。当前发布候选范围、检查项和待验证边界见 [RC 检查表](docs/release-candidate-checklist.md)。

版本号的唯一来源是 [VERSION](VERSION)；[CHANGELOG](CHANGELOG.md) 记录候选范围但不代表已发布版本。依赖通过 `requirements-dev.txt` 的精确版本固定；CI 使用 Python 3.11，实际宿主、字体与 Office/WPS 组合仍需本地核验。

请在 [Issues](https://github.com/yunye123/yuwen-courseware/issues) 报告可公开的问题；涉及凭据、个人数据或安全敏感路径时，按 [SECURITY.md](SECURITY.md) 的非公开方式联系维护者。贡献前阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；公开仓与私有研发仓保持独立历史，维护边界见 [MAINTENANCE.md](MAINTENANCE.md)。

## 许可

本仓库仅供个人学习、研究、评估和非商业备课参考，不是 OSI 意义上的开源项目。安装、修改和使用须遵守 [个人学习与参考许可](LICENSE)；不得镜像、再分发、商用或将其用于机构级部署。GitHub 的公开访问与 fork 机制不扩大本许可授予的使用范围。
