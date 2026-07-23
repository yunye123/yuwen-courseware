from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]


class TeacherExperienceContractTest(unittest.TestCase):
    def test_skill_requires_a_subject_teacher_voice_and_hides_backend_language(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        interaction = (
            SKILL_ROOT / "references" / "workflows" / "teacher-interaction.md"
        ).read_text(encoding="utf-8")

        self.assertIn("专业高中语文教师的学科语言", skill)
        self.assertIn("不以“作为 AI/大模型”开场", skill)
        for term in ("文本合同", "技术冻结", "哈希绑定", "占位语检测", "权利状态"):
            self.assertIn(term, interaction)
        self.assertIn("严禁在老师可见界面出现", skill)

    def test_interaction_uses_host_choices_with_a_short_numbered_fallback(self) -> None:
        interaction = (
            SKILL_ROOT / "references" / "workflows" / "teacher-interaction.md"
        ).read_text(encoding="utf-8")

        self.assertIn("按钮、选项卡、表单或对话框", interaction)
        self.assertIn("回复序号即可", interaction)
        self.assertIn("不根据平台名称猜测能力", interaction)
        self.assertIn("每次只请老师决定一件事", interaction)

    def test_content_consistency_confirmation_is_short_and_teacher_facing(self) -> None:
        interaction = (
            SKILL_ROOT / "references" / "workflows" / "teacher-interaction.md"
        ).read_text(encoding="utf-8")
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")

        self.assertIn("一次简短的“内容核对”", interaction)
        self.assertIn("有没有漏项，或前后说法不一致", interaction)
        self.assertIn("不得把这次确认藏起来", interaction)
        self.assertIn("不能让老师审核后台合同或报告", workflow)

    def test_every_confirmation_must_expose_the_complete_teacher_artifact(self) -> None:
        interaction = (
            SKILL_ROOT / "references" / "workflows" / "teacher-interaction.md"
        ).read_text(encoding="utf-8")

        self.assertIn("打开完整文件", interaction)
        self.assertIn("文件链接、文档卡片或附件", interaction)
        self.assertIn("链接只能打开教师版文件", interaction)
        self.assertIn("不得只说“已完成”或只给压缩摘要", interaction)

    def test_default_delivery_and_optional_handout_are_explicit(self) -> None:
        interaction = (
            SKILL_ROOT / "references" / "workflows" / "teacher-interaction.md"
        ).read_text(encoding="utf-8")
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")

        for filename in (
            "《课名》教学设计.md",
            "《课名》授课逐字稿.md",
            "《课名》白底课件.pptx",
        ):
            self.assertIn(filename, interaction)
        self.assertIn("学案不是默认必做", interaction)
        self.assertIn("阶段 6 和阶段 10 可选", workflow)
        self.assertIn("直接进入逐字稿", workflow)

    def test_no_handout_route_keeps_questions_and_activities_on_slides(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")

        self.assertIn("无学案时不得省略", skill)
        self.assertIn("只写在教师备注里不算", workflow)
        self.assertIn("核心问题和课堂活动", workflow)

    def test_teacher_delivery_folder_excludes_internal_artifacts(self) -> None:
        interaction = (
            SKILL_ROOT / "references" / "workflows" / "teacher-interaction.md"
        ).read_text(encoding="utf-8")

        self.assertIn("研究记录、检查报告、来源台账、结构数据、中间稿和版本记录", interaction)
        self.assertIn("不进入教师交付文件夹", interaction)
        self.assertIn("文件名全部使用中文", interaction)

    def test_openai_interface_uses_teacher_facing_product_language(self) -> None:
        interface = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

        self.assertIn("共备详实教学设计", interface)
        self.assertIn("教学设计、可打印逐字稿、可视化板书和白底课件", interface)
        self.assertIn("学案根据课堂需要再决定", interface)
        self.assertNotIn("当前批准阶段", interface)
        self.assertNotIn("PPT逐页文字稿", interface)

    def test_teacher_facing_templates_avoid_marketing_and_engineering_language(self) -> None:
        templates = SKILL_ROOT / "assets" / "templates"
        teacher_body = "\n".join(
            (templates / name).read_text(encoding="utf-8")
            for name in (
                "00-lesson-brief.md",
                "01-research-dossier.md",
                "02-teaching-design.md",
                "05-teaching-script.md",
                "06-ppt-text-draft.md",
            )
        )

        for phrase in (
            "人工智能赋能",
            "路线冻结与逐字校对登记",
            "无人工智能时的替代方案",
            "未知项与显式假设",
        ):
            self.assertNotIn(phrase, teacher_body)

    def test_teacher_outputs_hide_governance_and_are_print_ready(self) -> None:
        design = (SKILL_ROOT / "assets" / "templates" / "02-teaching-design.md").read_text(
            encoding="utf-8"
        )
        script = (SKILL_ROOT / "assets" / "templates" / "05-teaching-script.md").read_text(
            encoding="utf-8"
        )
        interaction = (
            SKILL_ROOT / "references" / "workflows" / "teacher-interaction.md"
        ).read_text(encoding="utf-8")

        self.assertNotIn("质量审查摘要", design)
        self.assertNotIn("下游稳定编号分配表", design)
        self.assertIn("空间预览", design)
        self.assertIn("教师说", script)
        self.assertIn("停：", script)
        self.assertIn("超时处理", script)
        self.assertIn("不得附“质量审查摘要”", interaction)


if __name__ == "__main__":
    unittest.main()
