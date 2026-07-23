# yuwen-courseware

高中语文备课 Agent Skill 的公开学习参考版（v0.1.0）。它帮助教师先形成课堂主线与问题链，再把已确认的资料组织成日常教学设计、授课导航稿、可视化板书和白底可编辑 PPTX；完整逐字稿按需展开。

这是技术预览，不是已完成课堂验证的教材产品或商业交付系统。

如需组织真实教师试用，可使用仓库内的[常态课验证空白模板](validation/real-teacher-trials/README.md)。模板不含真实课堂数据，也不能替代实际试用结论。

## 包含与不包含

包含：备课工作流、v2.1 教学设计课程导演规则、九板块教学设计模板、机械成稿检查器、课例状态守卫、文本一致性校验、逐字引文校对、个人课例索引、教师版过滤和白底 PPTX 导出。

不包含：教材、课程标准、教参、教师课例、学生信息、字体、模型、Office/WPS、DOCX/PDF 样式、模式卡与私有评测材料。使用前请提供本课可合法使用、且可核对的原文与资料；未能核对的内容必须标注为待确认，不能把模型记忆当作引文或教材事实。

仓库另附一个仅用于安装学习的自创示例资源，详见 [资源层说明](resources/README.md)。它不替代真实教材或权威资料；新增资源必须具有明确的再分发权利证据。

## 使用

1. 将整个目录安装到支持 `SKILL.md` 的 Agent 宿主。
2. 启动时提供本课教材版本、篇目或原文，以及可用的课标、注释或教参来源。
3. 让宿主按 [资料与个人资产工作流](references/workflows/source-materials-and-history.md) 和 [备课工作流](references/workflows/lesson-preparation.md) 组织课例。
4. 将个人课例资料放到 `YUWEN_DATA_HOME` 指定的私有目录，绝不提交到本仓库。

核心脚本需要 Python 3.10+。白底 PPTX 导出与完整测试需要：

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -q
```

对清洗后的单课时教学设计，可运行：

```bash
python3 scripts/check.py <教学设计.md>
```

该脚本只做板块、时间、预设、格式与篇幅等机械检查，不评价教学质量。

PPTX 导出还需要本机安装 `Source Han Serif SC`；该字体不随本项目提供。学校如需 DOCX/PDF，请将已确认的 Markdown 用本校合规工具转换，并在实际授课设备上检查结果。

## 版权与隐私

请仅使用自己拥有权利、已获授权或可合法公开使用的材料。不要提交教材全文、课程标准全文、课堂录像、学生信息、教师课例、Cookie、密钥、绝对路径或其他个人/受限数据。详见 [资料边界](references/workflows/source-materials-and-history.md) 与 [安全说明](SECURITY.md)。

## 授权、贡献与发布

本仓库仅供个人学习、研究、评估和非商业备课参考，不是 OSI 意义上的开源项目。安装、修改和使用须遵守 [个人学习与参考许可](LICENSE)；不得镜像、再分发、商用或将其用于机构级部署。GitHub 的公开访问与 fork 机制不扩大本许可授予的使用范围。

贡献者请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。公开仓与研发用私有仓保持独立历史，公开更新只能由经过审查的无敏感导出产生，禁止镜像或全 refs 推送；详见 [维护边界](MAINTENANCE.md)。
