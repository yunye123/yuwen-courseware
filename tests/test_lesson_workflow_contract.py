import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


class LessonWorkflowContractTest(unittest.TestCase):
    def test_all_real_lesson_templates_are_packaged_with_the_skill(self) -> None:
        required = [
            "00-lesson-brief.md",
            "01-research-dossier.md",
            "02-teaching-design.md",
            "03-student-handout.md",
            "04-teacher-answer.md",
            "05-teaching-script.md",
            "06-ppt-text-draft.md",
            "07-ppt-design-handoff.md",
            "08-returned-ppt-content-check.md",
            "09-package-checklist.md",
            "《使用说明》.md",
            "text-contract.json",
            "ppt-text-structured.json",
        ]

        for filename in required:
            with self.subTest(filename=filename):
                self.assertTrue((SKILL_ROOT / "assets" / "templates" / filename).is_file())

    def test_skill_routes_real_lessons_to_the_staged_workflow(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")

        self.assertIn("references/workflows/teacher-interaction.md", skill)
        self.assertIn("references/workflows/teacher-ready-content.md", skill)
        self.assertIn("references/workflows/lesson-preparation.md", skill)
        self.assertIn("references/workflows/text-contract-validation.md", skill)
        for operation in ("status", "verify", "approve"):
            self.assertIn(f"scripts/lesson_state.py {operation}", workflow)
        self.assertIn("教学设计完成后默认进入确认状态", skill)
        self.assertIn("未经老师确认，不自动生成逐字稿或 PPT", skill)
        self.assertIn("白底 PPT 逐页内容与导出", skill)

    def test_skill_has_a_chinese_teacher_communication_contract(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        interaction = (
            SKILL_ROOT / "references" / "workflows" / "teacher-interaction.md"
        ).read_text(encoding="utf-8")

        self.assertIn("## 教师沟通规范", skill)
        self.assertIn("全程使用专业高中语文教师的学科语言", skill)
        self.assertIn("严禁在老师可见界面出现", skill)
        self.assertIn("有按钮、选项卡、表单或对话框能力时直接调用", skill)
        self.assertIn("每次请老师确认前都先给完整教师版文件", skill)
        self.assertIn("问题与活动已经一一对应", interaction)

    def test_all_human_facing_templates_use_chinese_labels_and_numbering(self) -> None:
        forbidden_labels = (
            "lesson_id",
            "status",
            "objective_id",
            "task_id",
            "assessment_id",
            "answer_id",
            "script_id",
            "slide_id",
            "source_id",
            "claim_id",
            "material_id",
            "package_status",
            "external_ppt_status",
            "reveal_state",
        )
        for path in sorted((SKILL_ROOT / "assets" / "templates").glob("0[0-9]-*.md")):
            with self.subTest(template=path.name):
                text = path.read_text(encoding="utf-8")
                for label in forbidden_labels:
                    self.assertNotIn(label, text)
                self.assertNotRegex(text, r"(?m)^#{1,6}\s+[0-9]+(?:[.、·)]|\s)")

        instructions = SKILL_ROOT / "assets" / "templates" / "《使用说明》.md"
        self.assertTrue(instructions.is_file())
        self.assertNotRegex(instructions.read_text(encoding="utf-8"), r"[A-Za-z]{3,}")

    def test_teaching_design_gate_blocks_downstream_generation(self) -> None:
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")

        self.assertIn("教学设计未批准，不得生成学案、授课导航稿或白底 PPT", workflow)
        self.assertLess(
            workflow.index("第一段：教学设计闭环"),
            workflow.index("第二段：授课导航稿与可选学生资源"),
        )
        self.assertLess(
            workflow.index("第二段：授课导航稿与可选学生资源"),
            workflow.index("第三段：白底课堂课件"),
        )

    def test_every_lesson_records_user_materials_and_online_research_attempts(self) -> None:
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")
        dossier = (
            SKILL_ROOT / "assets" / "templates" / "01-research-dossier.md"
        ).read_text(encoding="utf-8")

        self.assertIn("本课资料核对 + 联网检索", workflow)
        self.assertIn("两者都未尝试前", workflow)
        self.assertIn("检索通道日志", dossier)
        self.assertIn("本课资料与历史资产", dossier)
        self.assertIn("联网·官方与权威来源", dossier)
        self.assertIn("联网·一线教研", dossier)
        self.assertIn("联网·社交平台线索", dossier)

    def test_default_ppt_is_a_teachable_editable_white_deck(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")
        template = (
            SKILL_ROOT / "assets" / "templates" / "06-ppt-text-draft.md"
        ).read_text(encoding="utf-8")

        self.assertIn("常态课默认交付课堂主线与问题链、日常教学设计、授课导航稿与白底可编辑 PPT", skill)
        self.assertIn("白底黑字、文字可编辑、带教师备注的课堂 PPTX", workflow)
        self.assertIn("scripts/export_text_pptx.py", workflow)
        self.assertNotIn("提供确定性纯文字 PPTX 导出，不做视觉设计、图片、动画与美化模板", skill)
        self.assertIn("屏显文字（完整）", template)
        self.assertIn("课件为白底简洁版，所有文字均可编辑", template)
        for interference in ("哈希", "SLIDE", "结构化副本", "课件文字合同"):
            with self.subTest(interference=interference):
                self.assertNotIn(interference, template)

    def test_handout_is_optional_but_ppt_interactions_are_complete(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")
        template = (
            SKILL_ROOT / "assets" / "templates" / "06-ppt-text-draft.md"
        ).read_text(encoding="utf-8")

        self.assertIn("学案和教师参考答案只在课堂确有需要且老师同意时增加", skill)
        self.assertIn("阶段 6 和阶段 10 可选", workflow)
        self.assertIn("没有学案时", workflow)
        self.assertIn("只写在教师备注里不算", workflow)
        self.assertIn("每个课堂任务都在学生可见页面写明“问题：”和“活动：”", template)
        self.assertIn("没有学案时，学生只看课件也能参与课堂", template)

    def test_text_and_ppt_contracts_are_fail_closed_and_staged(self) -> None:
        contract_workflow = (
            SKILL_ROOT / "references" / "workflows" / "text-contract-validation.md"
        ).read_text(encoding="utf-8")

        self.assertIn("text-contract.json", contract_workflow)
        self.assertIn("ppt-text-structured.json", contract_workflow)
        self.assertIn("validate_text_contract.py text", contract_workflow)
        self.assertIn("validate_text_contract.py render-ppt", contract_workflow)
        self.assertIn("validate_text_contract.py ppt", contract_workflow)
        self.assertIn("不得手工改写已投影的 Markdown", contract_workflow)
        self.assertIn("只有 `answer` 或 `summary` 页面可以绑定 `ANS-*`", contract_workflow)
        self.assertIn("text-contract-report=<ok=true 的不可变报告JSON>", contract_workflow)
        self.assertIn("ppt-contract-report=<ok=true 的不可变报告JSON>", contract_workflow)

    def test_downstream_templates_use_single_point_lineage_and_frozen_id_plan(self) -> None:
        templates = SKILL_ROOT / "assets" / "templates"
        for name in ("03-student-handout.md", "04-teacher-answer.md"):
            with self.subTest(template=name):
                text = (templates / name).read_text(encoding="utf-8")
                self.assertIn("跨文件绑定由系统一致性合同统一记录", text)
                self.assertNotIn("批准哈希", text)
                self.assertNotIn("学生学案哈希", text)
                self.assertNotIn("学案/答案哈希", text)

        script = (templates / "05-teaching-script.md").read_text(encoding="utf-8")
        self.assertIn("YUWEN_INTERNAL_MAPPING", script)
        self.assertNotIn("跨文件绑定由系统一致性合同统一记录", script)

        design = (templates / "02-teaching-design.md").read_text(encoding="utf-8")
        self.assertNotIn("下游稳定编号分配表", design)
        self.assertIn("YUWEN_INTERNAL_MAPPING", design)
        for prefix in ("OBJ", "TASK", "ASM", "ANS", "MAT", "SCRIPT"):
            self.assertIn(prefix, design)

        workflow = (
            SKILL_ROOT / "references" / "workflows" / "text-contract-validation.md"
        ).read_text(encoding="utf-8")
        self.assertIn("跨文件内容哈希的唯一绑定点", workflow)

    def test_teacher_ready_standard_focuses_on_real_classroom_use(self) -> None:
        standard = (
            SKILL_ROOT / "references" / "workflows" / "teacher-ready-content.md"
        ).read_text(encoding="utf-8")
        design = (SKILL_ROOT / "assets" / "templates" / "02-teaching-design.md").read_text(
            encoding="utf-8"
        )
        script = (SKILL_ROOT / "assets" / "templates" / "05-teaching-script.md").read_text(
            encoding="utf-8"
        )

        for phrase in ("去皮检验", "入文检验", "统摄检验", "成果检验"):
            self.assertIn(phrase, standard)
        self.assertIn("空间预览", design)
        self.assertIn("随课堂生成的落笔顺序", design)
        self.assertIn("一页课堂导航", script)
        self.assertIn("学生可能说", script)
        self.assertIn("超时处理", script)
        for phrase in ("半成品回答或典型误答", "抽样方式", "何时停止", "无设备或无额外准备"):
            self.assertIn(phrase, design)

    def test_external_ppt_does_not_block_skill_package_completion(self) -> None:
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")
        checklist = (
            SKILL_ROOT / "assets" / "templates" / "09-package-checklist.md"
        ).read_text(encoding="utf-8")

        self.assertIn("`package_status` 只追踪本 Skill 的教师成品", workflow)
        self.assertIn("`external_ppt_status` 单独追踪可选外部设计", workflow)
        self.assertIn("外部精装 PPT 未返回不阻断 `final-package-ready`", workflow)
        self.assertIn("外部课件状态：未请求", checklist)
        self.assertIn("外部设计未返回不影响白底课件交付", checklist)

    def test_review_budget_and_single_point_verification_match_owner_decision(self) -> None:
        review_rules = (
            SKILL_ROOT
            / "references"
            / "quality"
            / "dual-adversarial-stage-review-v1.md"
        ).read_text(encoding="utf-8")

        self.assertIn("每个质量门最多 2 轮", review_rules)
        self.assertNotIn("每包总计最多 2 轮", review_rules)
        self.assertIn("事实、引文、答案类", review_rules)
        self.assertIn("对应槽位做全深度复核", review_rules)
        self.assertIn("隐私与版权类缺陷一律不适用", review_rules)
        self.assertIn("每个质量门至多使用一次", review_rules)
        self.assertIn("修改前后哈希", review_rules)
        self.assertIn("差异证明", review_rules)

    def test_skill_discloses_historical_compatibility_without_calling_it_pass(self) -> None:
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")

        self.assertIn("historical-compatible-retrospective-evidence", workflow)
        self.assertIn("不能改写成 `pass`", workflow)
        self.assertIn("允许审批链继续", workflow)

    def test_teacher_workflows_use_a_cross_platform_python_placeholder(self) -> None:
        workflow_names = (
            "lesson-preparation.md",
            "text-contract-validation.md",
            "source-materials-and-history.md",
        )
        for name in workflow_names:
            with self.subTest(name=name):
                workflow = (
                    SKILL_ROOT / "references" / "workflows" / name
                ).read_text(encoding="utf-8")
                self.assertIn("<PYTHON>", workflow)
                self.assertNotIn("\npython3 scripts/", workflow)
                self.assertIn("Windows", workflow)

    def test_canonical_stage_ids_are_complete_and_optional_stages_are_explicit(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")
        stage_ids = [
            "lesson-brief",
            "research-plan",
            "evidence-dossier",
            "stance-selection",
            "route-freeze",
            "teaching-design",
            "student-resources",
            "teaching-script",
            "text-contract",
            "ppt-text",
            "external-ppt-check",
            "release",
        ]

        for stage_id in stage_ids:
            with self.subTest(stage_id=stage_id):
                self.assertIn(f"`{stage_id}`", workflow)
        self.assertIn("构建纯净中文教师文件夹", skill)
        self.assertIn("阶段 6 和阶段 10 可选", workflow)


if __name__ == "__main__":
    unittest.main()
