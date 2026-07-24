import importlib.util
from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "check.py"


def load_module():
    spec = importlib.util.spec_from_file_location("teaching_design_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_design() -> str:
    detail = "学生回到文本中的关键词，说明自己的判断，并根据同伴意见修正表达。"
    process = "\n\n".join(
        [
            f"### （一）初读辨误（10分钟）\n\n师：出示问题，要求圈画依据。\n\n生：默读、圈画并交流。\n\n预设：{detail}\n\n预设（误）：学生只凭印象下结论。\n\n应对：追问依据在哪里。\n\n板书随写：误读→证据",
            f"### （二）细读求证（15分钟）\n\n师：引导学生比较两处表达。\n\n生：比较、讨论并陈述理由。\n\n预设：{detail}\n\n预设：{detail}\n\n预设（误）：学生只罗列手法名称。\n\n应对：请学生说清表达效果。\n\n板书随写：证据→推理",
            f"### （三）交流修正（10分钟）\n\n师：组织汇报并追问。\n\n生：修改原有判断。\n\n预设：{detail}\n\n预设：{detail}\n\n预设（误）：学生只重复同伴结论。\n\n应对：回到原句核对。\n\n板书随写：推理→结论",
            f"### （四）检测收束（10分钟）\n\n师：布置当堂表达任务。\n\n生：独立完成并互评。\n\n预设：{detail}\n\n预设（误）：学生没有写出文本依据。\n\n应对：展示一份答案共同修订。\n\n板书随写：结论→表达",
        ]
    )
    process += "\n\n" + ("围绕文本证据完成表达并修订判断。" * 115)
    return f"""# 《示例》教学设计

## 一、基本信息

教材与单元：必修上册第一单元
年级：高一
课时：1课时（45分钟）
课型：古诗词

## 二、本课只攻一处

本课集中解决：学生把抒情句只看作豪放表态的误读。

最终希望学生形成：能用词句说明诗人的复杂心境。

## 三、本课不做

本课不展开：作者生平与全部典故。

原因：把时间留给关键词句的细读。

## 四、教学目标

1. 理解关键句的语境。
2. 分析词句之间的关系。
3. 表达有依据的鉴赏判断。

## 五、教学重难点

重点：用词句证据修正初读判断。

难点：从字面情绪读出复杂心境。

## 六、教学过程

{process}

## 七、板书设计

初读印象→文本证据→修正判断

## 八、当堂检测

1. 用两句文字说明你的判断与依据。

## 九、作业

基础：整理课堂中的两处证据。

提升：写一段鉴赏文字。
"""


class TeachingDesignCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_valid_design_passes(self) -> None:
        report = self.module.check_document(valid_design())
        self.assertTrue(report["ok"], report)

    def test_rejects_wrong_duration_and_missing_mistaken_presets(self) -> None:
        text = valid_design().replace("（45分钟）", "（50分钟）").replace("预设（误）：", "预设：")
        report = self.module.check_document(text)
        self.assertFalse(report["ok"])
        self.assertTrue(any("时间合计" in issue for issue in report["errors"]))
        self.assertTrue(any("预设（误）" in issue for issue in report["errors"]))

    def test_rejects_missing_total_duration(self) -> None:
        text = valid_design().replace("课时：1课时（45分钟）", "课时：1课时")
        report = self.module.check_document(text)
        self.assertFalse(report["ok"])
        self.assertTrue(any("总分钟数" in issue for issue in report["errors"]))

    def test_rejects_extra_section_and_tables(self) -> None:
        text = valid_design() + "\n## 十、备课说明\n\n| 项目 | 内容 |\n|---|---|\n"
        report = self.module.check_document(text)
        self.assertFalse(report["ok"])
        self.assertTrue(any("九个规定板块" in issue for issue in report["errors"]))
        self.assertTrue(any("Markdown 表格" in issue for issue in report["errors"]))

    def test_rejects_duplicate_primary_heading(self) -> None:
        text = valid_design() + "\n## 一、基本信息\n\n重复标题。\n"
        report = self.module.check_document(text)
        self.assertFalse(report["ok"])
        self.assertTrue(any("九个规定板块" in issue for issue in report["errors"]))

    def test_rejects_empty_required_process_label(self) -> None:
        text = valid_design().replace("师：出示问题，要求圈画依据。", "师：", 1)
        report = self.module.check_document(text)
        self.assertFalse(report["ok"])
        self.assertTrue(any("标签内容不能为空：师" in issue for issue in report["errors"]))

    def test_allows_adjacent_prose_to_continue_a_process_label(self) -> None:
        text = valid_design().replace(
            "师：出示问题，要求圈画依据。",
            "师：\n\n教师出示问题，要求圈画依据。",
            1,
        )
        report = self.module.check_document(text)
        self.assertTrue(report["ok"], report)

    def test_rejects_only_one_nonempty_mistaken_preset(self) -> None:
        text = valid_design()
        for preset in (
            "预设（误）：学生只凭印象下结论。\n\n",
            "预设（误）：学生只重复同伴结论。\n\n",
        ):
            text = text.replace(preset, "")
        text = text.replace("预设（误）：学生没有写出文本依据。", "预设（误）：")
        report = self.module.check_document(text)
        self.assertFalse(report["ok"])
        self.assertEqual(report["metrics"]["mistaken_preset_count"], 1)
        self.assertTrue(any("预设（误）仅 1 处" in issue for issue in report["errors"]))

    def test_allows_only_two_core_process_sections_with_mistaken_presets(self) -> None:
        text = valid_design()
        for preset in (
            "预设（误）：学生只凭印象下结论。\n\n",
            "预设（误）：学生没有写出文本依据。\n\n",
        ):
            text = text.replace(preset, "")
        report = self.module.check_document(text)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["metrics"]["mistaken_preset_count"], 2)

    def test_reports_low_length_and_process_ratio_as_warnings(self) -> None:
        padding = "围绕文本证据完成表达并修订判断。" * 115
        text = valid_design().replace(padding, "")
        report = self.module.check_document(text)
        self.assertTrue(report["ok"], report)
        self.assertTrue(any("低于建议下限" in issue for issue in report["warnings"]))
        self.assertTrue(any("教学过程占比" in issue for issue in report["warnings"]))

    def test_rejects_length_above_hard_upper_limit(self) -> None:
        text = valid_design() + ("补充文本。" * 200)
        report = self.module.check_document(text)
        self.assertFalse(report["ok"])
        self.assertTrue(any("不得超过 3500" in issue for issue in report["errors"]))

    def test_waives_fixed_length_contract_for_designs_over_one_lesson(self) -> None:
        text = valid_design()
        text = text.replace("课时：1课时（45分钟）", "课时：2课时（90分钟）")
        text = text.replace("### （四）检测收束（10分钟）", "### （四）检测收束（55分钟）")
        text += "补充文本。" * 300
        report = self.module.check_document(text)
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["metrics"]["total_visible_chars"], 3500)
        self.assertFalse(any("不得超过 3500" in issue for issue in report["errors"]))
        self.assertTrue(
            any("固定字数合同不适用" in issue for issue in report["warnings"]),
            report,
        )

    def test_rejects_internal_comments_in_teacher_design(self) -> None:
        text = valid_design().replace(
            "# 《示例》教学设计",
            "# 《示例》教学设计\n\n<!-- YUWEN_AUTHORING_NOTE\n内部推演\n-->",
        )
        report = self.module.check_document(text)
        self.assertFalse(report["ok"])
        self.assertTrue(any("不得残留内部注释" in issue for issue in report["errors"]))

    def test_rejects_ai_teaching_jargon_but_only_warns_for_curriculum_terms(self) -> None:
        for term in ("合理异答边界", "纠偏支架", "教师承接", "教学分支"):
            with self.subTest(term=term):
                report = self.module.check_document(valid_design() + f"\n{term}\n")
                self.assertFalse(report["ok"])
                self.assertTrue(any(term in issue for issue in report["errors"]))

        report = self.module.check_document(valid_design() + "\n核心素养与文化自信。\n")
        self.assertTrue(report["ok"], report)
        self.assertTrue(any("核心素养" in issue for issue in report["warnings"]))
        self.assertTrue(any("文化自信" in issue for issue in report["warnings"]))

    def test_accepts_one_core_target_and_warns_about_four_targets(self) -> None:
        original_targets = """1. 理解关键句的语境。
2. 分析词句之间的关系。
3. 表达有依据的鉴赏判断。"""
        one_target = "1. 表达有文本依据的鉴赏判断。"
        single_target_report = self.module.check_document(valid_design().replace(original_targets, one_target))
        self.assertTrue(single_target_report["ok"], single_target_report)
        self.assertFalse(any("教学目标建议" in issue for issue in single_target_report["warnings"]))

        four_targets = original_targets + "\n4. 迁移到同类文本的阅读。"
        four_target_report = self.module.check_document(valid_design().replace(original_targets, four_targets))
        self.assertTrue(four_target_report["ok"], four_target_report)
        self.assertTrue(any("教学目标建议" in issue for issue in four_target_report["warnings"]))

    def test_reports_board_without_connector_as_warning(self) -> None:
        text = valid_design().replace("初读印象→文本证据→修正判断", "初读印象、文本证据、修正判断")
        report = self.module.check_document(text)
        self.assertTrue(report["ok"], report)
        self.assertTrue(any("板书设计未使用“→”" in issue for issue in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
