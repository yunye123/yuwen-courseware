# v0.1.0 发布候选检查表

> 本文是发布前复核清单，不是正式 Release，也不把任一勾选项解释为真实课堂效果或教师试用结论。

## 版本与范围

- 版本号唯一来源：仓库根目录 `VERSION`；本候选目标为 `0.1.0`，尚未创建 tag 或 GitHub Release。
- 发布说明：见 `CHANGELOG.md`；公开仓只包含经审查的学习参考内容。
- 默认链路：课堂主线与问题链 → 日常教学设计 → 授课导航稿 → 白底可编辑 PPTX；完整逐字稿、学案和答案按需增加。
- 不包含：教材、课标全文、教参、教师课例、学生信息、真实试用记录、私有路径、字体、Office/WPS 与生成课例成品。

## 发布前必须复核

- [ ] `python3 -m unittest discover -s tests -q` 通过。
- [ ] `python3 -m compileall -q scripts tests` 通过。
- [ ] `git diff --check` 通过。
- [ ] 公开边界扫描未发现私有路径、私有知识库、模式卡、生产案例或受限材料。
- [ ] README、首次使用说明、资源清单和相对链接可打开。
- [ ] 自创资源的权利人、来源类别、许可证和允许用途已在 `resources/manifest.json` 登记。
- [ ] 场景 A、B、C 分别按 `docs/quickstart.md` 完成：完整材料、缺材料、无设备。
- [ ] 目标机器已按需要试开、编辑和放映白底 PPTX；未覆盖的字体、Office/WPS 或宿主组合明确列为待验证。
- [ ] 候选 PR 的 GitHub Actions `verify` 通过；没有绕过 CI、合并、tag 或正式 Release。

## 依赖与安装边界

- `requirements-dev.txt` 固定公开源码测试与 PPTX 导出依赖；CI 使用 Python 3.11，Skill 运行要求 Python 3.10+。
- 源码检出验证不等于封存安装包验证：只有另带根目录 `manifest.json` 的发布包才可运行 `scripts/verify_install.py`。
- Agent 宿主安装、PPTX 试放和 Office/WPS 兼容性必须在实际目标环境确认，不从本机单测推断。

## 证据边界

- 自动化测试和自创示例只能支持安装、启动、结构、导出和公开边界的技术验证。
- `validation/real-teacher-trials/` 只有空白模板；真实教师修改耗时、课堂实施、学生作答和课堂效果尚未收集。
- 首批真实用户如明确授权，其匿名反馈才可进入私有验证流程；本公开仓不收集、模拟或提交这些数据。

## 回滚

本候选尚未合并 `main`、未打 tag、未发布 Release。若发现公开边界、版权、安装或 CI 问题，关闭候选 PR 或以新提交修复即可；不要从私有仓镜像、强推或移动公开 tag。私有生产流程与本公开候选保持独立，不因关闭公开 PR 而回滚。
