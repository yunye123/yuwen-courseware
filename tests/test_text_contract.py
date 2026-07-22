from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_text_contract.py"
SPEC = importlib.util.spec_from_file_location("validate_text_contract", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TextContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.artifacts = {
            "teaching-design": self.root / "teaching-design.md",
            "student-handout": self.root / "student-handout.md",
            "teacher-answer": self.root / "teacher-answer.md",
            "teaching-script": self.root / "teaching-script.md",
            "ppt-text": self.root / "ppt-text.md",
        }
        self.artifacts["teaching-design"].write_text(
            "# 教学设计\n目标 OBJ-01\n核心任务 TASK-01\n评价 ASM-01\n",
            encoding="utf-8",
        )
        self.artifacts["student-handout"].write_text(
            "# 学生学案\n目标 OBJ-01\n材料 MAT-01\n任务 TASK-01\n作答 ASM-01\n",
            encoding="utf-8",
        )
        self.artifacts["teacher-answer"].write_text(
            "# 教师答案与评分参考\n任务 TASK-01\n题目 ASM-01\n解析 ANS-01\n",
            encoding="utf-8",
        )
        self.artifacts["teaching-script"].write_text(
            "# 授课逐字稿\n目标 OBJ-01\n任务 TASK-01\n话语块 SCRIPT-01\n",
            encoding="utf-8",
        )
        self.artifacts["ppt-text"].write_text(
            "# PPT逐页文字粗稿\nSLIDE-01\nTASK-01\nOBJ-01\nSCRIPT-01\n",
            encoding="utf-8",
        )
        self.contract_path = self.root / "text-contract.json"
        self.ppt_path = self.root / "ppt-text.json"
        self.write_contract(self.valid_contract())
        self.write_ppt_bundle(self.valid_ppt())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def valid_contract(self) -> dict:
        bindings = {}
        ids_by_role = {
            "teaching-design": ["OBJ-01", "TASK-01", "ASM-01"],
            "student-handout": ["OBJ-01", "MAT-01", "TASK-01", "ASM-01"],
            "teacher-answer": ["TASK-01", "ASM-01", "ANS-01"],
            "teaching-script": ["OBJ-01", "TASK-01", "SCRIPT-01"],
        }
        for role in MODULE.TEXT_ROLES:
            bindings[role] = {
                "sha256": MODULE.sha256_file(self.artifacts[role]),
                "ids": ids_by_role[role],
            }
        return {
            "schema_version": "1.0",
            "record_type": "text-contract",
            "lesson_id": "synthetic-lesson",
            "status": "review",
            "generated_at": "2026-07-18T18:30:00+08:00",
            "artifacts": bindings,
            "objectives": [{"objective_id": "OBJ-01"}],
            "materials": [{"material_id": "MAT-01", "source_ids": ["SRC-01"], "rights_status": "user-provided"}],
            "tasks": [{
                "task_id": "TASK-01",
                "objective_ids": ["OBJ-01"],
                "material_ids": ["MAT-01"],
                "assessment_ids": ["ASM-01"],
                "ppt_required": True,
            }],
            "assessments": [{
                "assessment_id": "ASM-01",
                "task_id": "TASK-01",
                "objective_ids": ["OBJ-01"],
                "answer_id": "ANS-01",
            }],
            "answers": [{"answer_id": "ANS-01", "assessment_id": "ASM-01"}],
            "scripts": [{"script_id": "SCRIPT-01", "task_id": "TASK-01"}],
        }

    def valid_ppt_only_contract(self) -> dict:
        self.artifacts["teaching-design"].write_text(
            "# 教学设计\n目标 OBJ-01\n材料 MAT-01\n核心任务 TASK-01\n评价 ASM-01\n",
            encoding="utf-8",
        )
        self.artifacts["teaching-script"].write_text(
            "# 授课逐字稿\n目标 OBJ-01\n任务 TASK-01\n评价 ASM-01\n"
            "参考与反馈 ANS-01\n话语块 SCRIPT-01\n",
            encoding="utf-8",
        )
        contract = self.valid_contract()
        contract["mode"] = "ppt-only"
        contract["artifacts"] = {
            "teaching-design": {
                "sha256": MODULE.sha256_file(self.artifacts["teaching-design"]),
                "ids": ["OBJ-01", "MAT-01", "TASK-01", "ASM-01"],
            },
            "teaching-script": {
                "sha256": MODULE.sha256_file(self.artifacts["teaching-script"]),
                "ids": ["OBJ-01", "TASK-01", "ASM-01", "ANS-01", "SCRIPT-01"],
            },
        }
        return contract

    def valid_ppt(self) -> dict:
        return {
            "schema_version": "1.0",
            "record_type": "ppt-text",
            "lesson_id": "synthetic-lesson",
            "status": "review",
            "generated_at": "2026-07-18T18:31:00+08:00",
            "text_contract_sha256": MODULE.sha256_file(self.contract_path),
            "ppt_text_sha256": MODULE.sha256_file(self.artifacts["ppt-text"]),
            "slides": [{
                "slide_id": "SLIDE-01",
                "page": 1,
                "title": "核心任务",
                "screen_text": (
                    "问题：材料中的判断是否成立？\n"
                    "活动：独立圈画依据，再与同桌比较。\n"
                    "时间：5 分钟\n"
                    "成果：一句判断和两处依据\n"
                    "交流：同桌互证后全班汇报。"
                ),
                "teacher_notes": "先给学生独立思考时间，再组织交流。",
                "task_id": "TASK-01",
                "objective_ids": ["OBJ-01"],
                "script_ids": ["SCRIPT-01"],
                "answer_ids": [],
                "reveal_state": "prompt",
            }],
        }

    def write_contract(self, value: dict) -> None:
        self.contract_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_ppt(self, value: dict) -> None:
        self.ppt_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_ppt_bundle(self, value: dict) -> None:
        value["text_contract_sha256"] = MODULE.sha256_file(self.contract_path)
        self.artifacts["ppt-text"].write_text(MODULE.render_ppt_markdown(value), encoding="utf-8")
        value["ppt_text_sha256"] = MODULE.sha256_file(self.artifacts["ppt-text"])
        self.write_ppt(value)

    def text_artifacts(self) -> dict[str, Path]:
        return {role: self.artifacts[role] for role in MODULE.TEXT_ROLES}

    def ppt_only_text_artifacts(self) -> dict[str, Path]:
        return {role: self.artifacts[role] for role in MODULE.PPT_ONLY_TEXT_ROLES}

    def add_second_task(self, contract: dict, *, ppt_required: bool = False) -> None:
        contract["tasks"].append({
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "material_ids": [],
            "assessment_ids": ["ASM-02"],
            "ppt_required": ppt_required,
        })
        contract["assessments"].append({
            "assessment_id": "ASM-02",
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "answer_id": "ANS-02",
        })
        contract["answers"].append({"answer_id": "ANS-02", "assessment_id": "ASM-02"})
        contract["scripts"].append({"script_id": "SCRIPT-02", "task_id": "TASK-02"})
        additions = {
            "teaching-design": "TASK-02 ASM-02\n",
            "student-handout": "TASK-02 ASM-02\n",
            "teacher-answer": "TASK-02 ASM-02 ANS-02\n",
            "teaching-script": "TASK-02 SCRIPT-02\n",
        }
        ids = {
            "teaching-design": ["OBJ-01", "TASK-01", "ASM-01", "TASK-02", "ASM-02"],
            "student-handout": [
                "OBJ-01", "MAT-01", "TASK-01", "ASM-01", "TASK-02", "ASM-02",
            ],
            "teacher-answer": [
                "TASK-01", "ASM-01", "ANS-01", "TASK-02", "ASM-02", "ANS-02",
            ],
            "teaching-script": [
                "OBJ-01", "TASK-01", "SCRIPT-01", "TASK-02", "SCRIPT-02",
            ],
        }
        for role, addition in additions.items():
            self.artifacts[role].write_text(
                self.artifacts[role].read_text(encoding="utf-8") + addition,
                encoding="utf-8",
            )
            contract["artifacts"][role] = {
                "sha256": MODULE.sha256_file(self.artifacts[role]),
                "ids": ids[role],
            }

    def test_valid_text_contract_passes(self) -> None:
        issues, context = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        self.assertEqual(issues, [])
        self.assertEqual(set(context["tasks"]), {"TASK-01"})

    def test_valid_ppt_contract_passes(self) -> None:
        issues, context = MODULE.validate_ppt_text(self.contract_path, self.ppt_path, self.artifacts)
        self.assertEqual(issues, [])
        self.assertEqual(set(context["slides"]), {"SLIDE-01"})

    def test_second_of_two_tasks_must_have_complete_student_visible_content(self) -> None:
        contract = self.valid_contract()
        self.add_second_task(contract, ppt_required=False)
        self.write_contract(contract)
        ppt = self.valid_ppt()
        ppt["slides"].append({
            "slide_id": "SLIDE-02",
            "page": 2,
            "title": "比较表达效果",
            "screen_text": (
                "问题：删去详写部分会怎样？\n"
                "活动：小组改写并比较表达效果。\n"
                "时间：4 分钟\n"
                "成果：一份改写稿和比较结论"
            ),
            "teacher_notes": "第二个任务结束后回扣传记写法。",
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "script_ids": ["SCRIPT-02"],
            "answer_ids": [],
            "reveal_state": "neutral",
        })
        self.write_ppt_bundle(ppt)

        issues, _ = MODULE.validate_ppt_text(
            self.contract_path, self.ppt_path, self.artifacts
        )

        task_issues = [item for item in issues if item["code"] == "task-screen-content"]
        self.assertTrue(any("TASK-02" in item["path"] for item in task_issues))
        self.assertTrue(any("交流或提交方式" in item["message"] for item in task_issues))

    def test_each_required_interaction_label_is_checked_by_the_contract_validator(self) -> None:
        components = {
            "问题": "问题：材料中的判断是否成立？",
            "活动": "活动：独立圈画依据，再与同桌比较。",
            "时间": "时间：5 分钟",
            "成果": "成果：一句判断和两处依据",
            "交流或提交方式": "提交：把结论写在课堂便笺上。",
        }
        for missing_label, missing_line in components.items():
            with self.subTest(missing_label=missing_label):
                ppt = self.valid_ppt()
                ppt["slides"][0]["screen_text"] = "\n".join(
                    line for label, line in components.items() if label != missing_label
                )
                ppt["slides"][0]["teacher_notes"] = missing_line
                self.write_ppt_bundle(ppt)
                issues, _ = MODULE.validate_ppt_text(
                    self.contract_path, self.ppt_path, self.artifacts
                )
                coverage = [
                    item for item in issues if item["code"] == "task-screen-content"
                ]
                self.assertTrue(
                    any(missing_label in item["message"] for item in coverage)
                )

    def test_interaction_values_require_actual_content_after_each_label(self) -> None:
        cases = {
            "五项都为空": "问题：\n活动：\n时间：\n成果：\n交流：",
            "成果仍是占位语": (
                "问题：材料中的判断是否成立？\n"
                "活动：独立圈画依据，再与同桌比较。\n"
                "时间：5 分钟\n"
                "成果：待补充\n"
                "交流：同桌互证后全班汇报。"
            ),
        }
        for name, screen_text in cases.items():
            with self.subTest(name=name):
                ppt = self.valid_ppt()
                ppt["slides"][0]["screen_text"] = screen_text
                self.write_ppt_bundle(ppt)

                issues, _ = MODULE.validate_ppt_text(
                    self.contract_path, self.ppt_path, self.artifacts
                )

                coverage = [
                    item for item in issues if item["code"] == "task-screen-content"
                ]
                self.assertTrue(coverage)

    def test_interaction_values_may_continue_on_the_next_line(self) -> None:
        ppt = self.valid_ppt()
        ppt["slides"][0]["screen_text"] = (
            "问题：\n材料中的判断是否成立？\n"
            "活动：独立圈画依据，再与同桌比较。\n"
            "时间：\n5 分钟\n"
            "成果：一句判断和两处依据\n"
            "提交方式：\n把结论写在课堂便笺上。"
        )
        self.write_ppt_bundle(ppt)

        issues, _ = MODULE.validate_ppt_text(
            self.contract_path, self.ppt_path, self.artifacts
        )

        self.assertEqual(issues, [])

    def test_every_contract_task_requires_student_visible_ppt_pages(self) -> None:
        contract = self.valid_contract()
        self.add_second_task(contract, ppt_required=False)
        self.write_contract(contract)
        self.write_ppt_bundle(self.valid_ppt())

        issues, _ = MODULE.validate_ppt_text(
            self.contract_path, self.ppt_path, self.artifacts
        )

        missing = [item for item in issues if item["code"] == "task-without-slide"]
        self.assertTrue(any("TASK-02" in item["path"] for item in missing))

    def test_ppt_teacher_visible_fields_reject_backend_content(self) -> None:
        cases = [
            *[("title", term, "teacher-facing-backend-term") for term in MODULE.BACKEND_TERMS],
            *[
                ("screen_text", f"课堂说明 {prefix}-01", "teacher-facing-internal-id")
                for prefix in ("OBJ", "TASK", "ASM", "ANS", "SCRIPT", "SLIDE", "SRC", "CLM", "MAT")
            ],
            ("teacher_notes", "当前状态 approved", "teacher-facing-english-status"),
            ("teacher_notes", "当前状态 student-blank", "teacher-facing-english-status"),
            ("teacher_notes", "status: review", "teacher-facing-english-status"),
            ("teacher_notes", "当前阶段 text-contract", "teacher-facing-english-status"),
            ("title", "课堂任务 ✨", "teacher-facing-emoji"),
        ]
        for field, value, expected_code in cases:
            with self.subTest(field=field, value=value):
                ppt = self.valid_ppt()
                ppt["slides"][0][field] = value
                self.write_ppt_bundle(ppt)
                issues, _ = MODULE.validate_ppt_text(
                    self.contract_path, self.ppt_path, self.artifacts
                )
                self.assertIn(expected_code, {item["code"] for item in issues})

    def test_ppt_teacher_visible_fields_reject_black_box_production_metadata(self) -> None:
        cases = [
            ("title", "Schema Version = 1.0"),
            ("screen_text", "JSON结构验证报告：通过"),
            ("teacher_notes", "SHA256 = 0123456789abcdef"),
            ("title", "manifest.json"),
            ("screen_text", "approval_record 已写入"),
            ("teacher_notes", "检查结论：页面没有异常"),
            ("teacher_notes", "当前检查结论：页面没有异常"),
            ("teacher_notes", "制作过程：由脚本生成后导出文档"),
            ("teacher_notes", "本页由 PythonPptx 生成"),
            ("teacher_notes", "PowerPoint 兼容提醒：WPS 可能出现字体替换"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                ppt = self.valid_ppt()
                ppt["slides"][0][field] = value
                self.write_ppt_bundle(ppt)
                issues, _ = MODULE.validate_ppt_text(
                    self.contract_path, self.ppt_path, self.artifacts
                )
                self.assertIn(
                    "teacher-facing-backend-term",
                    {item["code"] for item in issues},
                )

    def test_ppt_teacher_visible_filter_keeps_normal_chinese_teaching_language(self) -> None:
        ppt = self.valid_ppt()
        ppt["slides"][0]["title"] = "梳理木版年画的制作过程"
        ppt["slides"][0]["teacher_notes"] = (
            "检查结论是否有原文依据，再用自己的话修订。"
        )
        self.write_ppt_bundle(ppt)

        issues, _ = MODULE.validate_ppt_text(
            self.contract_path, self.ppt_path, self.artifacts
        )

        self.assertEqual(issues, [])

    def test_explicit_handout_mode_text_and_ppt_chain_passes(self) -> None:
        contract = self.valid_contract()
        contract["mode"] = "handout"
        self.write_contract(contract)
        self.write_ppt_bundle(self.valid_ppt())

        text_issues, text_context = MODULE.validate_text_contract(
            self.contract_path, self.text_artifacts()
        )
        ppt_issues, _ = MODULE.validate_ppt_text(
            self.contract_path, self.ppt_path, self.artifacts
        )
        self.assertEqual(text_issues, [])
        self.assertEqual(ppt_issues, [])
        self.assertEqual(text_context["content_mode"], "handout")

    def test_ppt_only_text_and_ppt_chain_passes(self) -> None:
        self.write_contract(self.valid_ppt_only_contract())
        self.write_ppt_bundle(self.valid_ppt())
        artifacts = {
            **self.ppt_only_text_artifacts(),
            "ppt-text": self.artifacts["ppt-text"],
        }

        text_issues, text_context = MODULE.validate_text_contract(
            self.contract_path, self.ppt_only_text_artifacts()
        )
        ppt_issues, _ = MODULE.validate_ppt_text(
            self.contract_path, self.ppt_path, artifacts
        )
        self.assertEqual(text_issues, [])
        self.assertEqual(ppt_issues, [])
        self.assertEqual(text_context["content_mode"], "ppt-only")
        self.assertEqual(
            set(text_context["artifact_hashes"]),
            {"teaching-design", "teaching-script"},
        )

    def test_handout_mode_rejects_half_of_the_student_resource_pair(self) -> None:
        contract = self.valid_contract()
        contract["mode"] = "handout"
        contract["artifacts"].pop("teacher-answer")
        self.write_contract(contract)
        artifacts = self.text_artifacts()
        artifacts.pop("teacher-answer")

        issues, _ = MODULE.validate_text_contract(self.contract_path, artifacts)
        codes = {item["code"] for item in issues}
        self.assertIn("artifact-binding", codes)
        self.assertIn("artifact-input", codes)

    def test_ppt_only_rejects_any_task_not_required_in_ppt(self) -> None:
        contract = self.valid_ppt_only_contract()
        contract["tasks"][0]["ppt_required"] = False
        self.write_contract(contract)

        issues, _ = MODULE.validate_text_contract(
            self.contract_path, self.ppt_only_text_artifacts()
        )
        self.assertIn(
            "ppt-only-task-not-required", {item["code"] for item in issues}
        )

    def test_ppt_only_script_binds_assessments_answers_and_script_blocks(self) -> None:
        contract = self.valid_ppt_only_contract()
        contract["artifacts"]["teaching-script"]["ids"] = [
            "OBJ-01",
            "TASK-01",
            "SCRIPT-01",
        ]
        self.write_contract(contract)

        issues, _ = MODULE.validate_text_contract(
            self.contract_path, self.ppt_only_text_artifacts()
        )
        coverage = [
            item for item in issues if item["code"] == "artifact-role-coverage"
        ]
        self.assertTrue(any("ASM-01" in item["message"] for item in coverage))
        self.assertTrue(any("ANS-01" in item["message"] for item in coverage))

    def test_teacher_answer_template_groups_one_answer_set_per_assessment(self) -> None:
        template = (
            ROOT / "assets" / "templates" / "04-teacher-answer.md"
        ).read_text(encoding="utf-8")
        self.assertIn("一个评价编号只对应一个答案集编号", template)
        self.assertIn("对应任务或活动", template)
        self.assertNotIn("## 一、逐题答案", template)

    def test_three_assessments_with_fifteen_answer_items_use_three_answer_sets(self) -> None:
        contract = self.valid_contract()
        assessment_ids = ["ASM-01", "ASM-02", "ASM-03"]
        answer_ids = ["ANS-01", "ANS-02", "ANS-03"]
        contract["tasks"][0]["assessment_ids"] = assessment_ids
        contract["assessments"] = [
            {
                "assessment_id": assessment_id,
                "task_id": "TASK-01",
                "objective_ids": ["OBJ-01"],
                "answer_id": answer_id,
            }
            for assessment_id, answer_id in zip(assessment_ids, answer_ids)
        ]
        contract["answers"] = [
            {"answer_id": answer_id, "assessment_id": assessment_id}
            for assessment_id, answer_id in zip(assessment_ids, answer_ids)
        ]
        self.artifacts["teaching-design"].write_text(
            "# 教学设计\nOBJ-01 TASK-01 ASM-01 ASM-02 ASM-03\n",
            encoding="utf-8",
        )
        self.artifacts["student-handout"].write_text(
            "# 学生学案\nOBJ-01 MAT-01 TASK-01 ASM-01 ASM-02 ASM-03\n",
            encoding="utf-8",
        )
        answer_lines = []
        for group, (assessment_id, answer_id) in enumerate(
            zip(assessment_ids, answer_ids), start=1
        ):
            details = "；".join(
                f"活动 {group}.{item} 要点" for item in range(1, 6)
            )
            answer_lines.append(
                f"TASK-01 {assessment_id} {answer_id}：{details}"
            )
        self.artifacts["teacher-answer"].write_text(
            "# 教师答案与评分参考\n" + "\n".join(answer_lines) + "\n",
            encoding="utf-8",
        )
        ids_by_role = {
            "teaching-design": ["OBJ-01", "TASK-01", *assessment_ids],
            "student-handout": ["OBJ-01", "MAT-01", "TASK-01", *assessment_ids],
            "teacher-answer": ["TASK-01", *assessment_ids, *answer_ids],
            "teaching-script": ["OBJ-01", "TASK-01", "SCRIPT-01"],
        }
        for role, ids in ids_by_role.items():
            contract["artifacts"][role] = {
                "sha256": MODULE.sha256_file(self.artifacts[role]),
                "ids": ids,
            }
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(
            self.contract_path, self.text_artifacts()
        )
        self.assertEqual(issues, [])

    def test_broken_cross_reference_fails_closed(self) -> None:
        contract = self.valid_contract()
        contract["assessments"][0]["task_id"] = "TASK-99"
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        codes = {item["code"] for item in issues}
        self.assertIn("broken-reference", codes)

    def test_student_answer_leak_is_rejected(self) -> None:
        self.artifacts["student-handout"].write_text(
            self.artifacts["student-handout"].read_text(encoding="utf-8") + "参考答案：略\n",
            encoding="utf-8",
        )
        contract = self.valid_contract()
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        self.assertIn("student-answer-leak", {item["code"] for item in issues})

    def test_student_safety_checklist_is_not_mistaken_for_a_leak(self) -> None:
        self.artifacts["student-handout"].write_text(
            self.artifacts["student-handout"].read_text(encoding="utf-8")
            + "- [ ] 未泄露参考答案、评分点或教师提示\n",
            encoding="utf-8",
        )
        contract = self.valid_contract()
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        self.assertNotIn("student-answer-leak", {item["code"] for item in issues})

    def test_checked_student_safety_checklist_is_not_mistaken_for_a_leak(self) -> None:
        for marker in ("x", "X"):
            with self.subTest(marker=marker):
                self.artifacts["student-handout"].write_text(
                    "# 学生学案\n目标 OBJ-01\n材料 MAT-01\n任务 TASK-01\n"
                    f"作答 ASM-01\n- [{marker}] 未泄露答案或评分点\n",
                    encoding="utf-8",
                )
                contract = self.valid_contract()
                self.write_contract(contract)
                issues, _ = MODULE.validate_text_contract(
                    self.contract_path, self.text_artifacts()
                )
                self.assertNotIn(
                    "student-answer-leak", {item["code"] for item in issues}
                )

    def test_safety_negation_cannot_mask_answer_leak_in_a_later_clause(self) -> None:
        self.artifacts["student-handout"].write_text(
            self.artifacts["student-handout"].read_text(encoding="utf-8")
            + "说明：不包含占位语。参考答案：B\n",
            encoding="utf-8",
        )
        contract = self.valid_contract()
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        self.assertIn("student-answer-leak", {item["code"] for item in issues})

    def test_unrelated_negation_cannot_mask_answer_leak_in_same_clause(self) -> None:
        self.artifacts["student-handout"].write_text(
            self.artifacts["student-handout"].read_text(encoding="utf-8")
            + "不包含占位内容但参考答案：B\n",
            encoding="utf-8",
        )
        contract = self.valid_contract()
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        self.assertIn("student-answer-leak", {item["code"] for item in issues})

    def test_artifact_hash_and_id_binding_are_enforced(self) -> None:
        contract = self.valid_contract()
        contract["artifacts"]["teaching-design"]["sha256"] = "0" * 64
        contract["artifacts"]["teaching-design"]["ids"].remove("ASM-01")
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        codes = {item["code"] for item in issues}
        self.assertIn("artifact-hash-mismatch", codes)
        self.assertIn("artifact-id-unbound", codes)

    def test_teacher_answer_must_cover_every_declared_task_assessment_and_answer(self) -> None:
        contract = self.valid_contract()
        contract["tasks"].append({
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "material_ids": [],
            "assessment_ids": ["ASM-02"],
            "ppt_required": False,
        })
        contract["assessments"].append({
            "assessment_id": "ASM-02",
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "answer_id": "ANS-02",
        })
        contract["answers"].append({"answer_id": "ANS-02", "assessment_id": "ASM-02"})
        contract["scripts"].append({"script_id": "SCRIPT-02", "task_id": "TASK-02"})
        additions = {
            "teaching-design": "TASK-02 ASM-02\n",
            "student-handout": "TASK-02 ASM-02\n",
            "teacher-answer": "TASK-02 ASM-02\n",
            "teaching-script": "TASK-02 SCRIPT-02 ANS-02\n",
        }
        ids = {
            "teaching-design": ["OBJ-01", "TASK-01", "ASM-01", "TASK-02", "ASM-02"],
            "student-handout": ["OBJ-01", "MAT-01", "TASK-01", "ASM-01", "TASK-02", "ASM-02"],
            "teacher-answer": ["TASK-01", "ASM-01", "ANS-01", "TASK-02", "ASM-02"],
            "teaching-script": [
                "OBJ-01",
                "TASK-01",
                "SCRIPT-01",
                "TASK-02",
                "SCRIPT-02",
                "ANS-02",
            ],
        }
        for role, addition in additions.items():
            self.artifacts[role].write_text(
                self.artifacts[role].read_text(encoding="utf-8") + addition,
                encoding="utf-8",
            )
            contract["artifacts"][role] = {
                "sha256": MODULE.sha256_file(self.artifacts[role]),
                "ids": ids[role],
            }
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        coverage = [item for item in issues if item["code"] == "artifact-role-coverage"]
        self.assertTrue(any(item["path"].endswith("teacher-answer.ids") for item in coverage))
        self.assertTrue(any("ANS-02" in item["message"] for item in coverage))

    def test_unresolved_placeholder_is_rejected(self) -> None:
        self.artifacts["teaching-script"].write_text(
            self.artifacts["teaching-script"].read_text(encoding="utf-8") + "TODO\n",
            encoding="utf-8",
        )
        contract = self.valid_contract()
        self.write_contract(contract)
        issues, _ = MODULE.validate_text_contract(self.contract_path, self.text_artifacts())
        self.assertIn("placeholder", {item["code"] for item in issues})

    def test_ppt_report_rejects_answer_before_reveal(self) -> None:
        ppt = self.valid_ppt()
        ppt["slides"][0]["answer_ids"] = ["ANS-01"]
        self.write_ppt_bundle(ppt)
        issues, _ = MODULE.validate_ppt_text(self.contract_path, self.ppt_path, self.artifacts)
        self.assertIn("answer-reveal", {item["code"] for item in issues})

    def test_ppt_markdown_must_be_exact_structured_projection(self) -> None:
        self.artifacts["ppt-text"].write_text(
            self.artifacts["ppt-text"].read_text(encoding="utf-8") + "\n额外但未登记的屏显文字。\n",
            encoding="utf-8",
        )
        ppt = json.loads(self.ppt_path.read_text(encoding="utf-8"))
        ppt["ppt_text_sha256"] = MODULE.sha256_file(self.artifacts["ppt-text"])
        self.write_ppt(ppt)
        issues, _ = MODULE.validate_ppt_text(self.contract_path, self.ppt_path, self.artifacts)
        self.assertIn("ppt-markdown-drift", {item["code"] for item in issues})

    def test_ppt_optional_direction_fields_reject_non_strings(self) -> None:
        ppt = self.valid_ppt()
        ppt["slides"][0]["material_direction"] = ["must not be silently dropped"]
        with self.assertRaisesRegex(MODULE.ContractInputError, "material_direction must be a string"):
            MODULE.render_ppt_markdown(ppt)

    def test_ppt_script_must_belong_to_the_same_task(self) -> None:
        contract = self.valid_contract()
        contract["tasks"].append({
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "material_ids": [],
            "assessment_ids": ["ASM-02"],
            "ppt_required": False,
        })
        contract["assessments"].append({
            "assessment_id": "ASM-02",
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "answer_id": "ANS-02",
        })
        contract["answers"].append({"answer_id": "ANS-02", "assessment_id": "ASM-02"})
        contract["scripts"].append({"script_id": "SCRIPT-02", "task_id": "TASK-02"})
        self.artifacts["teaching-design"].write_text(
            self.artifacts["teaching-design"].read_text(encoding="utf-8") + "TASK-02 ASM-02\n",
            encoding="utf-8",
        )
        self.artifacts["student-handout"].write_text(
            self.artifacts["student-handout"].read_text(encoding="utf-8") + "TASK-02 ASM-02\n",
            encoding="utf-8",
        )
        self.artifacts["teacher-answer"].write_text(
            self.artifacts["teacher-answer"].read_text(encoding="utf-8") + "TASK-02 ASM-02 ANS-02\n",
            encoding="utf-8",
        )
        self.artifacts["teaching-script"].write_text(
            self.artifacts["teaching-script"].read_text(encoding="utf-8") + "TASK-02 SCRIPT-02\n",
            encoding="utf-8",
        )
        contract["artifacts"] = self.valid_contract()["artifacts"]
        contract["artifacts"]["teaching-design"] = {
            "sha256": MODULE.sha256_file(self.artifacts["teaching-design"]),
            "ids": ["OBJ-01", "TASK-01", "ASM-01", "TASK-02", "ASM-02"],
        }
        contract["artifacts"]["student-handout"] = {
            "sha256": MODULE.sha256_file(self.artifacts["student-handout"]),
            "ids": ["OBJ-01", "MAT-01", "TASK-01", "ASM-01", "TASK-02", "ASM-02"],
        }
        contract["artifacts"]["teacher-answer"] = {
            "sha256": MODULE.sha256_file(self.artifacts["teacher-answer"]),
            "ids": ["TASK-01", "ASM-01", "ANS-01", "TASK-02", "ASM-02", "ANS-02"],
        }
        contract["artifacts"]["teaching-script"] = {
            "sha256": MODULE.sha256_file(self.artifacts["teaching-script"]),
            "ids": ["OBJ-01", "TASK-01", "SCRIPT-01", "TASK-02", "SCRIPT-02"],
        }
        self.write_contract(contract)
        ppt = self.valid_ppt()
        ppt["slides"][0]["script_ids"] = ["SCRIPT-02"]
        self.write_ppt_bundle(ppt)
        issues, _ = MODULE.validate_ppt_text(self.contract_path, self.ppt_path, self.artifacts)
        self.assertIn("script-task-mismatch", {item["code"] for item in issues})

    def test_ppt_answer_must_belong_to_the_same_task(self) -> None:
        contract = self.valid_contract()
        contract["tasks"].append({
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "material_ids": [],
            "assessment_ids": ["ASM-02"],
            "ppt_required": False,
        })
        contract["assessments"].append({
            "assessment_id": "ASM-02",
            "task_id": "TASK-02",
            "objective_ids": ["OBJ-01"],
            "answer_id": "ANS-02",
        })
        contract["answers"].append({"answer_id": "ANS-02", "assessment_id": "ASM-02"})
        contract["scripts"].append({"script_id": "SCRIPT-02", "task_id": "TASK-02"})
        self.artifacts["teaching-design"].write_text(
            self.artifacts["teaching-design"].read_text(encoding="utf-8") + "TASK-02 ASM-02\n",
            encoding="utf-8",
        )
        self.artifacts["student-handout"].write_text(
            self.artifacts["student-handout"].read_text(encoding="utf-8") + "TASK-02 ASM-02\n",
            encoding="utf-8",
        )
        self.artifacts["teacher-answer"].write_text(
            self.artifacts["teacher-answer"].read_text(encoding="utf-8") + "TASK-02 ASM-02 ANS-02\n",
            encoding="utf-8",
        )
        self.artifacts["teaching-script"].write_text(
            self.artifacts["teaching-script"].read_text(encoding="utf-8") + "TASK-02 SCRIPT-02\n",
            encoding="utf-8",
        )
        contract["artifacts"]["teaching-design"] = {
            "sha256": MODULE.sha256_file(self.artifacts["teaching-design"]),
            "ids": ["OBJ-01", "TASK-01", "ASM-01", "TASK-02", "ASM-02"],
        }
        contract["artifacts"]["student-handout"] = {
            "sha256": MODULE.sha256_file(self.artifacts["student-handout"]),
            "ids": ["OBJ-01", "MAT-01", "TASK-01", "ASM-01", "TASK-02", "ASM-02"],
        }
        contract["artifacts"]["teacher-answer"] = {
            "sha256": MODULE.sha256_file(self.artifacts["teacher-answer"]),
            "ids": ["TASK-01", "ASM-01", "ANS-01", "TASK-02", "ASM-02", "ANS-02"],
        }
        contract["artifacts"]["teaching-script"] = {
            "sha256": MODULE.sha256_file(self.artifacts["teaching-script"]),
            "ids": ["OBJ-01", "TASK-01", "SCRIPT-01", "TASK-02", "SCRIPT-02"],
        }
        self.write_contract(contract)
        ppt = self.valid_ppt()
        ppt["slides"][0]["answer_ids"] = ["ANS-02"]
        ppt["slides"][0]["reveal_state"] = "answer"
        self.write_ppt_bundle(ppt)
        issues, _ = MODULE.validate_ppt_text(self.contract_path, self.ppt_path, self.artifacts)
        self.assertIn("answer-task-mismatch", {item["code"] for item in issues})

    def test_cli_renders_ppt_markdown_without_overwrite(self) -> None:
        output = self.root / "rendered" / "ppt.md"
        command = [
            sys.executable,
            str(SCRIPT),
            "render-ppt",
            "--ppt-json",
            str(self.ppt_path),
            "--output",
            str(output),
        ]
        first = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertEqual(output.read_text(encoding="utf-8"), MODULE.render_ppt_markdown(self.valid_ppt()))
        second = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(second.returncode, 2)
        self.assertIn("refusing to overwrite", second.stderr)

    def test_cli_writes_immutable_report_and_refuses_overwrite(self) -> None:
        report = self.root / "reports" / "text-report.json"
        command = [
            sys.executable,
            str(SCRIPT),
            "text",
            "--contract",
            str(self.contract_path),
            "--report",
            str(report),
        ]
        for role in MODULE.TEXT_ROLES:
            command.extend(["--artifact", f"{role}={self.artifacts[role]}"])
        first = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["text_contract_sha256"], MODULE.sha256_file(self.contract_path))
        self.assertIsNone(payload["ppt_structured_sha256"])
        second = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(second.returncode, 2)
        self.assertIn("refusing to overwrite", second.stderr)

    def test_concurrent_immutable_writes_have_exactly_one_winner(self) -> None:
        output = self.root / "race" / "report.json"
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(MODULE._write_new_file, output, content, "report")
                for content in (b"first\n", b"second\n")
            ]
        successes = 0
        failures = 0
        for future in futures:
            try:
                future.result()
                successes += 1
            except MODULE.ContractInputError:
                failures += 1
        self.assertEqual((successes, failures), (1, 1))
        self.assertIn(output.read_bytes(), {b"first\n", b"second\n"})

    def test_ppt_report_binds_contract_structured_source_and_projection(self) -> None:
        report = self.root / "reports" / "ppt-report.json"
        command = [
            sys.executable,
            str(SCRIPT),
            "ppt",
            "--contract",
            str(self.contract_path),
            "--ppt-json",
            str(self.ppt_path),
            "--report",
            str(report),
        ]
        for role in (*MODULE.TEXT_ROLES, MODULE.PPT_ROLE):
            command.extend(["--artifact", f"{role}={self.artifacts[role]}"])
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["text_contract_sha256"], MODULE.sha256_file(self.contract_path))
        self.assertEqual(payload["ppt_structured_sha256"], MODULE.sha256_file(self.ppt_path))
        self.assertEqual(payload["ppt_text_sha256"], MODULE.sha256_file(self.artifacts["ppt-text"]))

    def test_json_schemas_and_templates_are_parseable(self) -> None:
        for path in (
            ROOT / "references" / "schemas" / "text-contract.schema.json",
            ROOT / "references" / "schemas" / "ppt-text.schema.json",
            ROOT / "references" / "schemas" / "contract-validation-report.schema.json",
            ROOT / "assets" / "templates" / "text-contract.json",
            ROOT / "assets" / "templates" / "ppt-text-structured.json",
        ):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()
