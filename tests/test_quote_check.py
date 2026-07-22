from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "quote_check.py"


class QuoteCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "示例原文.txt"
        self.source.write_text(
            "晨光落在书页上，教室安静下来。\n"
            "学生圈画关键词，再说明理由。\n"
            "讨论结束后，写下一句结论。\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_check(self, quotes: list[dict[str, str]]) -> subprocess.CompletedProcess[str]:
        checklist = self.root / "逐字校对清单.json"
        checklist.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "record_type": "verbatim-quote-checklist",
                    "lesson_id": "synthetic-quote-check",
                    "sources": [
                        {
                            "source_id": "user-material",
                            "path": self.source.name,
                            "label": "使用者提供的示例原文",
                        }
                    ],
                    "quotes": quotes,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--checklist", str(checklist)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_detects_three_character_errors_in_synthetic_source(self) -> None:
        result = self.run_check(
            [
                {"quote_id": "Q-01", "source_id": "user-material", "text": "暮光落在书页上，教室安静下来"},
                {"quote_id": "Q-02", "source_id": "user-material", "text": "学生标画关键词，再说明理由"},
                {"quote_id": "Q-03", "source_id": "user-material", "text": "讨论结束后，写下一段结论"},
            ]
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        self.assertEqual(report["summary"], {"passed": 0, "different": 3, "total": 3})
        self.assertEqual(
            [item["quote_id"] for item in report["differences"]],
            ["Q-01", "Q-02", "Q-03"],
        )
        replacements = {
            (difference["actual"], difference["expected"])
            for item in report["differences"]
            for difference in item["character_differences"]
        }
        self.assertTrue({("暮", "晨"), ("标", "圈"), ("段", "句")}.issubset(replacements))

    def test_correct_quotes_pass_with_line_breaks_and_zero_false_positives(self) -> None:
        result = self.run_check(
            [
                {
                    "quote_id": "Q-OK-01",
                    "source_id": "user-material",
                    "text": "晨光落在书页上，\n教室安静下来",
                },
                {
                    "quote_id": "Q-OK-02",
                    "source_id": "user-material",
                    "text": "学生圈画关键词，再说明理由",
                },
                {
                    "quote_id": "Q-OK-03",
                    "source_id": "user-material",
                    "text": "讨论结束后，写下一句结论",
                },
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"], {"passed": 3, "different": 0, "total": 3})
        self.assertEqual(report["differences"], [])

    def test_rejects_source_path_outside_checklist_directory(self) -> None:
        outside = self.root.parent / "outside-source.txt"
        outside.write_text("不应读取", encoding="utf-8")
        try:
            result = self.run_check(
                [{"quote_id": "Q-01", "source_id": "user-material", "text": "不应读取"}]
            )
            checklist = self.root / "逐字校对清单.json"
            value = json.loads(checklist.read_text(encoding="utf-8"))
            value["sources"][0]["path"] = "../outside-source.txt"
            checklist.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--checklist", str(checklist)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("inside the checklist directory", result.stderr)
        finally:
            outside.unlink(missing_ok=True)

    def test_retrospective_context_is_preserved_in_report(self) -> None:
        checklist = self.root / "逐字校对清单.json"
        context = {
            "kind": "retrospective",
            "generated_at": "2026-07-19T08:00:00Z",
            "note": "追溯核对，生成于 alpha.10 之后，不冒充审批当时存在",
        }
        checklist.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "record_type": "verbatim-quote-checklist",
                    "lesson_id": "synthetic-quote-check",
                    "verification_context": context,
                    "sources": [
                        {
                            "source_id": "user-material",
                            "path": self.source.name,
                            "label": "使用者提供的示例原文",
                        }
                    ],
                    "quotes": [
                        {
                            "quote_id": "Q-01",
                            "source_id": "user-material",
                            "text": "讨论结束后，写下一句结论",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--checklist", str(checklist)],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verification_context"], context)

    def test_workflow_and_templates_expose_quote_gate_and_page_number_boundary(self) -> None:
        workflow = (
            SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md"
        ).read_text(encoding="utf-8")
        review_rules = (
            SKILL_ROOT
            / "references"
            / "quality"
            / "dual-adversarial-stage-review-v1.md"
        ).read_text(encoding="utf-8")
        teaching_script = (SKILL_ROOT / "assets" / "templates" / "05-teaching-script.md").read_text(
            encoding="utf-8"
        )
        ppt_draft = (SKILL_ROOT / "assets" / "templates" / "06-ppt-text-draft.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/quote_check.py", workflow)
        self.assertLess(workflow.index("scripts/quote_check.py"), workflow.index("record-review"))
        self.assertIn("单点核验", review_rules)
        self.assertIn("全新轻量评审", review_rules)
        for template in (teaching_script, ppt_draft):
            self.assertIn("第 X 页", template)
            self.assertNotIn("SLIDE 编号", template)


if __name__ == "__main__":
    unittest.main()
