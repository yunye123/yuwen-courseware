from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "teacher_view_filter.py"


def load_filter_module():
    spec = importlib.util.spec_from_file_location("teacher_view_filter", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TeacherViewFilterTest(unittest.TestCase):
    def test_whitelist_filter_removes_only_metadata_and_governance(self) -> None:
        module = load_filter_module()
        source = """# 《示例课文》教学设计

> lesson_id：suwu-02
> status：approved
> 上游：route-freeze-v2.md
> 修订版本：v3
> 教学设计批准哈希：0123456789abcdef
> **【模拟测试声明】本文档不冒充真实教师。**
> 本文档是教师可删改的课堂支持稿。

## 教学目标

OBJ-01 对应 TASK-01/02/03 与 ASM-01，教师查看 ANS-01。

> 课堂引文：“晨光照进教室”。

## 质量审查摘要

- 在线评审 A 路：通过。

### 审查细节

- 内部哈希：deadbeef。

## 教学过程

SCRIPT-01 使用 SLIDE-001，再完成 TASK-12。
"""

        filtered, report = module.filter_markdown_text(source)

        self.assertEqual(
            filtered,
            """# 《示例课文》教学设计

> 本文档是教师可删改的课堂支持稿。

## 教学目标

目标一 对应 任务一/任务二/任务三 与 评价一，教师查看 参考答案一。

> 课堂引文：“晨光照进教室”。

## 教学过程

讲稿一 使用 第一页，再完成 任务十二。
""",
        )
        self.assertEqual(report["schema_version"], "yuwen-courseware.teacher-view-filter/v2")
        self.assertTrue(report["ok"])
        self.assertEqual(report["removed_blocks"][0]["kind"], "header-metadata")
        self.assertEqual(report["removed_blocks"][1]["title"], "质量审查摘要")
        self.assertEqual(
            report["identifier_replacements"],
            {"ANS": 1, "ASM": 1, "OBJ": 1, "SCRIPT": 1, "SLIDE": 1, "TASK": 4},
        )
        self.assertEqual(report["total_replacements"], 9)
        self.assertEqual(report["forbidden_terms"], [])
        self.assertEqual(report["source_sha256"], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(
            report["teacher_view_sha256"], hashlib.sha256(filtered.encode()).hexdigest()
        )

    def test_unrecognised_header_quote_and_similar_heading_are_preserved(self) -> None:
        module = load_filter_module()
        source = """# 课例

> 课堂导语：请回到原文。

## 质量审查能力训练

学生审核两种解释的证据。
"""
        filtered, report = module.filter_markdown_text(source)
        self.assertEqual(filtered, source)
        self.assertEqual(report["removed_blocks"], [])
        self.assertEqual(report["total_replacements"], 0)

    def test_filter_is_idempotent(self) -> None:
        module = load_filter_module()
        source = "# 课例\n\n> status：approved\n\n## 任务\n\nTASK-01\n"
        once, _ = module.filter_markdown_text(source)
        twice, second_report = module.filter_markdown_text(once)
        self.assertEqual(twice, once)
        self.assertEqual(second_report["removed_blocks"], [])
        self.assertEqual(second_report["total_replacements"], 0)

    def test_removes_marked_internal_comments_and_identifier_columns(self) -> None:
        module = load_filter_module()
        source = """# 教学设计

<!-- YUWEN_INTERNAL_MAPPING
OBJ-01 -> TASK-01 -> ASM-01
-->

| objective_id | 教学目标 | 核心任务 | 来源/任务 ID |
|---|---|---|---|
| OBJ-01 | 结合原文解释人物选择 | 比较两处细节 | SRC-01 / TASK-01 |
"""

        filtered, report = module.filter_markdown_text(source)

        self.assertTrue(report["ok"], report["forbidden_terms"])
        self.assertNotIn("YUWEN_INTERNAL_MAPPING", filtered)
        self.assertNotIn("objective_id", filtered)
        self.assertNotIn("来源/任务", filtered)
        self.assertIn("结合原文解释人物选择", filtered)
        self.assertIn("比较两处细节", filtered)
        self.assertNotIn("dropped_table_columns", report)

    def test_translates_teacher_visible_field_labels_and_evidence_identifiers(self) -> None:
        module = load_filter_module()
        source = """# 教学设计

| objective_id | task_id | source_id / claim_id | material_id | 来源/任务 ID |
|---|---|---|---|
| OBJ-01 | TASK-02 | SRC-003 / CLM-004 | MAT-05 |
"""

        filtered, _ = module.filter_markdown_text(source)

        self.assertNotRegex(
            filtered,
            r"objective_id|task_id|source_id|claim_id|material_id|OBJ-|TASK-|SRC-|CLM-|MAT-",
        )
        self.assertIn("教学目标", filtered)
        self.assertIn("课堂任务", filtered)
        self.assertIn("资料出处 / 研究结论", filtered)
        self.assertIn("学习材料", filtered)
        self.assertIn("资料出处/课堂任务", filtered)
        self.assertIn("目标一", filtered)
        self.assertIn("任务二", filtered)
        self.assertIn("资料三 / 结论四", filtered)
        self.assertIn("材料五", filtered)

    def test_removes_localized_internal_header_metadata(self) -> None:
        module = load_filter_module()
        source = """# 教学设计

> 课例编号：sample-lesson
> 当前状态：已批准
> 输入版本与校验值：0123456789abcdef
> 教师可删改本文稿。

## 教学目标

理解文本。
"""

        filtered, report = module.filter_markdown_text(source)

        self.assertNotIn("课例编号", filtered)
        self.assertNotIn("当前状态", filtered)
        self.assertNotIn("输入版本与校验值", filtered)
        self.assertIn("教师可删改本文稿", filtered)
        self.assertEqual(report["removed_line_count"], 3)

    def test_filter_file_writes_markdown_and_machine_report_without_overwrite(self) -> None:
        module = load_filter_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "内部稿.md"
            output = root / "教师版.md"
            report_path = root / "转换报告.json"
            source.write_text("# 课例\n\nTASK-01\n", encoding="utf-8")

            report = module.filter_file(source, output, report_path)

            self.assertEqual(output.read_text(encoding="utf-8"), "# 课例\n\n任务一\n")
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), report)
            self.assertEqual(report["source"]["path"], "内部稿.md")
            self.assertEqual(report["output"]["path"], "教师版.md")
            with self.assertRaises(module.FilterError):
                module.filter_file(source, output, root / "另一报告.json")

    def test_numbered_governance_sections_and_internal_header_notes_are_removed(self) -> None:
        module = load_filter_module()
        source = """# 教学设计

> 跨文件绑定由系统一致性合同统一记录，不在正文头部互抄文件哈希。
> 编号警示：SLIDE 编号只供后台使用。

## 一、教学目标

OBJ-01 引导学生概括诗歌的情感层次。

## 四、下游稳定编号分配表

| OBJ | TASK | ASM |
|---|---|---|

## 十一、质量审查摘要

技术校验通过。

## 十二、教学过程

请学生朗读并圈画关键词。
"""

        filtered, report = module.filter_markdown_text(source)

        self.assertTrue(report["ok"])
        self.assertNotIn("系统一致性合同", filtered)
        self.assertNotIn("编号警示", filtered)
        self.assertNotIn("下游稳定编号分配表", filtered)
        self.assertNotIn("质量审查摘要", filtered)
        self.assertIn("目标一 引导学生概括诗歌的情感层次", filtered)
        self.assertIn("请学生朗读并圈画关键词", filtered)

    def test_filter_file_rejects_remaining_teacher_facing_backend_jargon(self) -> None:
        module = load_filter_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "内部稿.md"
            output = root / "教师版.md"
            report_path = root / "转换报告.json"
            source.write_text(
                "# 教学设计\n\n正文误写了文本合同，请核对。\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(module.FilterError, "教师版仍含后台用语"):
                module.filter_file(source, output, report_path)
            self.assertFalse(output.exists())
            self.assertFalse(report_path.exists())

    def test_filter_rejects_backend_reports_and_software_notices_in_document_body(self) -> None:
        module = load_filter_module()
        variants = (
            "schema_version：1.0；manifest 已生成。",
            "JSON 校验报告：全部通过。",
            "SHA-256：" + "a" * 64,
            "approval_record 已绑定。",
            "当前检查结论：全部通过。",
            "软件兼容提醒：请安装 python-pptx。",
        )

        for body in variants:
            with self.subTest(body=body):
                _, report = module.filter_markdown_text(
                    "# 教学设计\n\n" + body + "\n"
                )
                self.assertFalse(report["ok"])
                self.assertTrue(report["forbidden_terms"])

    def test_filter_keeps_normal_subject_uses_of_process_and_conclusion(self) -> None:
        module = load_filter_module()
        source = (
            "# 教学设计\n\n"
            "梳理木版年画的制作过程。\n\n"
            "检查结论是否有诗句依据，再用自己的话修订。\n"
        )

        filtered, report = module.filter_markdown_text(source)

        self.assertTrue(report["ok"], report["forbidden_terms"])
        self.assertIn("木版年画的制作过程", filtered)
        self.assertIn("检查结论是否有诗句依据", filtered)

    def test_filter_keeps_status_progress_and_ai_when_they_are_lesson_content(self) -> None:
        module = load_filter_module()
        source = (
            "# 教学设计\n\n"
            "分析人物当前状态及变化。\n\n"
            "说明情节当前进度与叙事节奏的关系。\n\n"
            "比较人工智能辅助写作与独立写作的差异。\n"
        )

        filtered, report = module.filter_markdown_text(source)

        self.assertTrue(report["ok"], report["forbidden_terms"])
        self.assertEqual(filtered, source)

    def test_real_teacher_document_templates_filter_to_subject_language(self) -> None:
        module = load_filter_module()
        templates = SKILL_ROOT / "assets" / "templates"
        forbidden_phrases = (
            "人工智能辅助",
            "当前状态",
            "当前进度",
            "启动确认",
            "批准人",
            "批准时间",
            "检索通道日志",
            "研究充分性裁决",
            "来源编号",
            "论断编号",
            "目标编号",
            "任务编号",
            "素材编号",
            "评价编号",
            "答案集编号",
            "已批准教学设计",
            "猜页码",
            "复制以上页面块",
            "严禁出现教师答案",
            "制作要求",
        )
        for name in (
            "00-lesson-brief.md",
            "01-research-dossier.md",
            "02-teaching-design.md",
            "03-student-handout.md",
            "04-teacher-answer.md",
            "05-teaching-script.md",
            "06-ppt-text-draft.md",
        ):
            with self.subTest(template=name):
                source = (templates / name).read_text(encoding="utf-8")
                filtered, report = module.filter_markdown_text(source)
                self.assertTrue(report["ok"], report["forbidden_terms"])
                self.assertEqual(report["forbidden_terms"], [])
                self.assertNotRegex(
                    filtered,
                    r"(?:OBJ|TASK|ASM|ANS|SCRIPT|SLIDE|SRC|CLM|MAT)-[0-9]",
                )
                self.assertNotIn("质量审查摘要", filtered)
                self.assertNotIn("下游稳定编号分配表", filtered)
                self.assertNotIn("学生版检查", filtered)
                self.assertNotIn("答案核查", filtered)
                self.assertNotIn("讲稿检查", filtered)
                for phrase in forbidden_phrases:
                    self.assertNotIn(phrase, filtered)
                self.assertNotRegex(
                    filtered,
                    r"(?<![A-Za-z0-9_])(?:OBJ|TASK|ASM|ANS|SCRIPT|SLIDE|SRC|CLM|MAT)(?![A-Za-z0-9_-])",
                )
                chapter_numbers = re.findall(
                    r"(?m)^## ([一二三四五六七八九十百]+)、",
                    filtered,
                )
                self.assertEqual(
                    chapter_numbers,
                    [module.chinese_number(index) for index in range(1, len(chapter_numbers) + 1)],
                )

    def test_real_filtered_templates_keep_useful_teaching_content(self) -> None:
        module = load_filter_module()
        templates = SKILL_ROOT / "assets" / "templates"
        expected_content = {
            "00-lesson-brief.md": ("学生学习诊断", "常见误解", "学生表现"),
            "01-research-dossier.md": ("资料出处与课堂用途", "文本解读与教学结论", "不同解释"),
            "02-teaching-design.md": ("本课只攻一处", "核心达成", "文字空间预览"),
            "03-student-handout.md": ("学习目标", "课堂任务", "证据要求"),
            "04-teacher-answer.md": ("参考答案与评价依据", "评分点", "可接受的不同答案"),
            "05-teaching-script.md": ("一页课堂导航", "学生可能说", "课堂机动速查"),
            "06-ppt-text-draft.md": ("问题：", "活动：", "交流："),
        }

        for name, phrases in expected_content.items():
            with self.subTest(template=name):
                source = (templates / name).read_text(encoding="utf-8")
                filtered, report = module.filter_markdown_text(source)
                self.assertTrue(report["ok"], report["forbidden_terms"])
                for phrase in phrases:
                    self.assertIn(phrase, filtered)

    def test_internal_instructions_are_removed_without_touching_lesson_content(self) -> None:
        module = load_filter_module()
        source = """# 课例

## 一、研究结论

诗歌的情感与叙事视角有关。

## 二、检索通道日志

后台记录。

## 三、教学目标

OBJ-01：学生能结合诗句说明判断。

> 严禁出现教师答案、评分点或答案提示。

- 评价编号：ASM-01

## 四、课堂任务

学生圈画诗句，交流两种不同理解。

## 五、学习评价

评价时保留有文本依据、可接受的不同答案。
"""

        filtered, report = module.filter_markdown_text(source)

        self.assertTrue(report["ok"], report["forbidden_terms"])
        self.assertNotIn("检索通道日志", filtered)
        self.assertNotIn("严禁出现教师答案", filtered)
        self.assertNotIn("评价编号", filtered)
        self.assertEqual(
            re.findall(r"(?m)^## ([一二三四]+)、", filtered),
            ["一", "二", "三", "四"],
        )
        for phrase in (
            "诗歌的情感与叙事视角有关",
            "学生能结合诗句说明判断",
            "学生圈画诗句",
            "可接受的不同答案",
        ):
            self.assertIn(phrase, filtered)


if __name__ == "__main__":
    unittest.main()
