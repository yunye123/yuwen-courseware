from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "lesson_state.py"
VALIDATOR_SCRIPT = SKILL_ROOT / "scripts" / "validate_text_contract.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "lesson_state_test_contract_validator", VALIDATOR_SCRIPT
)
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC.loader is not None
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)
STAGES = [
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
REQUIRED_ROLES = {
    "lesson-brief": ("lesson-brief",),
    "research-plan": ("research-plan",),
    "evidence-dossier": ("evidence-dossier",),
    "stance-selection": ("stance-selection",),
    "route-freeze": ("route-freeze",),
    "teaching-design": ("teaching-design",),
    "student-resources": ("student-handout", "teacher-answer"),
    "teaching-script": ("teaching-script",),
    "text-contract": ("text-contract", "text-contract-report"),
    "ppt-text": ("ppt-text", "ppt-structured", "ppt-contract-report"),
    "external-ppt-check": ("external-ppt-check",),
    "release": ("package-checklist", "manifest"),
}
REVIEW_STAGES = {"teaching-design", "text-contract", "release"}


class LessonStateCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_home = self.root / "data"
        self.lesson_id = "sample-lesson"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str, use_data_home: bool = True) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(SCRIPT), *arguments]
        if use_data_home:
            command.extend(["--data-home", str(self.data_home)])
        environment = os.environ.copy()
        environment.pop("YUWEN_DATA_HOME", None)
        return subprocess.run(command, text=True, capture_output=True, env=environment, check=False)

    def lesson_dir(self, lesson_id: str | None = None) -> Path:
        return self.data_home / "lessons" / (lesson_id or self.lesson_id)

    def state(self, lesson_id: str | None = None) -> dict[str, object]:
        return json.loads((self.lesson_dir(lesson_id) / "state.json").read_text(encoding="utf-8"))

    def active_text_contract_hash(self, lesson_id: str | None = None) -> str:
        lesson_id = lesson_id or self.lesson_id
        for reference in reversed(self.state(lesson_id)["approvals"]):
            record = json.loads(
                (self.lesson_dir(lesson_id) / reference["file"]).read_text(encoding="utf-8")
            )
            if record["stage"] != "text-contract":
                continue
            for item in record["inputs"]:
                if item["role"] == "text-contract":
                    return item["sha256"]
        self.fail("an active text-contract approval is required for the PPT fixture")

    def active_text_contract_path(self, lesson_id: str | None = None) -> Path:
        lesson_id = lesson_id or self.lesson_id
        state = self.state(lesson_id)
        active_ids = set(state["active_approval_ids"])
        for reference in reversed(state["approvals"]):
            if reference["approval_id"] not in active_ids:
                continue
            record = json.loads(
                (self.lesson_dir(lesson_id) / reference["file"]).read_text(
                    encoding="utf-8"
                )
            )
            if record["stage"] != "text-contract":
                continue
            for item in record["inputs"]:
                if item["role"] == "text-contract":
                    return self.lesson_dir(lesson_id) / item["path"]
        self.fail("an active text-contract path is required for the PPT fixture")

    def active_source_artifact_hashes(self, lesson_id: str | None = None) -> dict[str, str]:
        lesson_id = lesson_id or self.lesson_id
        state = self.state(lesson_id)
        active_ids = set(
            state.get("active_approval_ids")
            or [reference["approval_id"] for reference in state["approvals"]]
        )
        hashes: dict[str, str] = {}
        wanted = {
            "teaching-design",
            "student-handout",
            "teacher-answer",
            "teaching-script",
        }
        for reference in state["approvals"]:
            if reference["approval_id"] not in active_ids:
                continue
            record = json.loads(
                (self.lesson_dir(lesson_id) / reference["file"]).read_text(encoding="utf-8")
            )
            for item in record["inputs"]:
                if item["role"] in wanted:
                    hashes[item["role"]] = item["sha256"]
        return hashes

    def active_source_artifact_paths(self, lesson_id: str | None = None) -> dict[str, Path]:
        lesson_id = lesson_id or self.lesson_id
        state = self.state(lesson_id)
        active_ids = set(state["active_approval_ids"])
        paths: dict[str, Path] = {}
        wanted = {
            "teaching-design",
            "student-handout",
            "teacher-answer",
            "teaching-script",
        }
        for reference in state["approvals"]:
            if reference["approval_id"] not in active_ids:
                continue
            record = json.loads(
                (self.lesson_dir(lesson_id) / reference["file"]).read_text(
                    encoding="utf-8"
                )
            )
            for item in record["inputs"]:
                if item["role"] in wanted:
                    paths[item["role"]] = self.lesson_dir(lesson_id) / item["path"]
        return paths

    def write_contract_gate_fixture(
        self,
        stage: str,
        role_paths: dict[str, Path],
        label: str,
        *,
        lesson_id: str | None = None,
    ) -> None:
        lesson_id = lesson_id or self.lesson_id
        if stage == "text-contract":
            artifact_hashes = self.active_source_artifact_hashes(lesson_id)
            content_mode = (
                "handout"
                if {"student-handout", "teacher-answer"}.issubset(artifact_hashes)
                else "ppt-only"
            )
            ids_by_role = {
                "teaching-design": ["OBJ-01", "MAT-01", "TASK-01", "ASM-01"],
                "student-handout": ["OBJ-01", "MAT-01", "TASK-01", "ASM-01"],
                "teacher-answer": ["TASK-01", "ASM-01", "ANS-01"],
                "teaching-script": (
                    ["OBJ-01", "TASK-01", "SCRIPT-01"]
                    if content_mode == "handout"
                    else ["OBJ-01", "TASK-01", "ASM-01", "ANS-01", "SCRIPT-01"]
                ),
            }
            contract = {
                "schema_version": "1.0",
                "record_type": "text-contract",
                "lesson_id": lesson_id,
                "status": "review",
                "generated_at": "2026-07-18T00:00:00Z",
                "artifacts": {
                    role: {"sha256": digest, "ids": ids_by_role[role]}
                    for role, digest in artifact_hashes.items()
                },
                "objectives": [{"objective_id": "OBJ-01"}],
                "materials": [
                    {
                        "material_id": "MAT-01",
                        "source_ids": [f"SRC-{label}"],
                        "rights_status": "user-provided",
                    }
                ],
                "tasks": [
                    {
                        "task_id": "TASK-01",
                        "objective_ids": ["OBJ-01"],
                        "material_ids": ["MAT-01"],
                        "assessment_ids": ["ASM-01"],
                        "ppt_required": True,
                    }
                ],
                "assessments": [
                    {
                        "assessment_id": "ASM-01",
                        "task_id": "TASK-01",
                        "objective_ids": ["OBJ-01"],
                        "answer_id": "ANS-01",
                    }
                ],
                "answers": [{"answer_id": "ANS-01", "assessment_id": "ASM-01"}],
                "scripts": [{"script_id": "SCRIPT-01", "task_id": "TASK-01"}],
            }
            if content_mode == "ppt-only":
                contract["mode"] = "ppt-only"
            role_paths["text-contract"].write_text(
                json.dumps(contract, sort_keys=True), encoding="utf-8"
            )
            semantic_issues, context = VALIDATOR.validate_text_contract(
                role_paths["text-contract"],
                self.active_source_artifact_paths(lesson_id),
            )
            self.assertEqual(semantic_issues, [])
            report = VALIDATOR._report("text", semantic_issues, context)
            role_paths["text-contract-report"].write_text(
                json.dumps(report, sort_keys=True), encoding="utf-8"
            )
        elif stage == "ppt-text":
            contract_path = self.active_text_contract_path(lesson_id)
            contract_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
            structured = {
                "schema_version": "1.0",
                "record_type": "ppt-text",
                "lesson_id": lesson_id,
                "status": "review",
                "generated_at": "2026-07-18T00:00:00Z",
                "text_contract_sha256": contract_hash,
                "ppt_text_sha256": "0" * 64,
                "slides": [
                    {
                        "slide_id": "SLIDE-01",
                        "page": 1,
                        "title": f"fixture {label}",
                        "screen_text": (
                            "问题：如何依据材料作出判断？\n"
                            "活动：独立圈画证据后与同桌比较。\n"
                            "时间：3分钟。\n"
                            "成果：形成一条有依据的判断。\n"
                            "交流方式：口头交流并提交关键词。"
                        ),
                        "teacher_notes": "schema-valid fixture teacher notes",
                        "task_id": "TASK-01",
                        "objective_ids": ["OBJ-01"],
                        "script_ids": ["SCRIPT-01"],
                        "answer_ids": [],
                        "reveal_state": "prompt",
                    }
                ],
            }
            role_paths["ppt-text"].write_text(
                VALIDATOR.render_ppt_markdown(structured), encoding="utf-8"
            )
            structured["ppt_text_sha256"] = hashlib.sha256(
                role_paths["ppt-text"].read_bytes()
            ).hexdigest()
            role_paths["ppt-structured"].write_text(
                json.dumps(structured, sort_keys=True), encoding="utf-8"
            )
            artifacts = self.active_source_artifact_paths(lesson_id)
            artifacts["ppt-text"] = role_paths["ppt-text"]
            semantic_issues, context = VALIDATOR.validate_ppt_text(
                contract_path,
                role_paths["ppt-structured"],
                artifacts,
            )
            self.assertEqual(semantic_issues, [])
            report = VALIDATOR._report("ppt", semantic_issues, context)
            role_paths["ppt-contract-report"].write_text(
                json.dumps(report, sort_keys=True), encoding="utf-8"
            )

    def init_lesson(self, lesson_id: str | None = None) -> dict[str, object]:
        result = self.run_cli("init", "--lesson-id", lesson_id or self.lesson_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def make_stage_inputs(
        self, revision: int, *, lesson_id: str | None = None
    ) -> tuple[str, list[str], list[Path]]:
        lesson_id = lesson_id or self.lesson_id
        state = self.state(lesson_id)
        stage = str(state["current_stage"])
        arguments: list[str] = []
        paths: list[Path] = []
        role_paths: dict[str, Path] = {}
        contract_markers = {
            "teaching-design": "OBJ-01 MAT-01 TASK-01 ASM-01",
            "student-handout": "OBJ-01 MAT-01 TASK-01 ASM-01",
            "teacher-answer": "TASK-01 ASM-01 ANS-01",
            "teaching-script": (
                "OBJ-01 TASK-01 SCRIPT-01"
                if {"student-handout", "teacher-answer"}.issubset(
                    self.active_source_artifact_hashes(lesson_id)
                )
                else "OBJ-01 TASK-01 ASM-01 ANS-01 SCRIPT-01"
            ),
        }
        for number, role in enumerate(REQUIRED_ROLES[stage]):
            suffix = ".json" if role in {
                "text-contract",
                "text-contract-report",
                "ppt-structured",
                "ppt-contract-report",
            } else ".md"
            path = self.lesson_dir(lesson_id) / f"r{revision:02d}-{role}{suffix}"
            path.write_text(
                f"# {lesson_id}:{revision}:{role}:{number}\n"
                f"{contract_markers.get(role, 'stage fixture')}\n",
                encoding="utf-8",
            )
            arguments.extend(["--input", f"{role}={path}"])
            paths.append(path)
            role_paths[role] = path
        self.write_contract_gate_fixture(
            stage, role_paths, f"revision-{revision}", lesson_id=lesson_id
        )
        return stage, arguments, paths

    def confirmation(
        self,
        revision: int,
        stage: str,
        *,
        lesson_id: str | None = None,
        resource_choice: str | None = None,
    ) -> Path:
        lesson_id = lesson_id or self.lesson_id
        path = self.lesson_dir(lesson_id) / f"confirm-r{revision:02d}-{stage}.json"
        path.write_text(
            json.dumps(
                {
                    "record_type": "user-confirmation",
                    "lesson_id": lesson_id,
                    "stage": stage,
                    "user_id": "teacher-user",
                    "decision": "approve",
                    "source": "host-conversation",
                    "host": "codex",
                    "conversation_id": f"conversation-{lesson_id}",
                    "message_id": f"message-{revision}",
                    "confirmed_at": "2026-07-18T00:00:00Z",
                    "decision_text": f"approve {stage}",
                    **(
                        {"resource_choice": resource_choice}
                        if resource_choice is not None
                        else {}
                    ),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def batch_confirmation(
        self, revision: int, stages: list[str], *, lesson_id: str | None = None
    ) -> Path:
        lesson_id = lesson_id or self.lesson_id
        path = self.lesson_dir(lesson_id) / f"batch-confirm-r{revision:02d}.json"
        path.write_text(
            json.dumps(
                {
                    "record_type": "user-batch-confirmation",
                    "lesson_id": lesson_id,
                    "stages": stages,
                    "user_id": "teacher-user",
                    "decision": "approve",
                    "source": "host-conversation",
                    "host": "codex",
                    "conversation_id": f"conversation-{lesson_id}",
                    "message_id": f"batch-message-{revision}",
                    "confirmed_at": "2026-07-19T00:00:00Z",
                    "decision_text": "批量确认连续中间阶段",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def revision_confirmation(self, stage: str, label: str, reason: str) -> Path:
        path = self.lesson_dir() / f"revise-confirm-{label}-{stage}.json"
        path.write_text(
            json.dumps(
                {
                    "record_type": "user-revision-confirmation",
                    "lesson_id": self.lesson_id,
                    "stage": stage,
                    "user_id": "teacher-user",
                    "decision": "revise",
                    "source": "host-conversation",
                    "host": "codex",
                    "conversation_id": f"conversation-{self.lesson_id}",
                    "message_id": f"revision-message-{label}",
                    "confirmed_at": "2026-07-18T00:00:00Z",
                    "decision_text": f"revise {stage} for {label}",
                    "reason": reason,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def record_review(
        self,
        stage: str,
        input_arguments: list[str],
        *,
        reviewer: str,
        route: str,
        verdict: str = "pass",
        run_id: str | None = None,
        report: Path | None = None,
        quote_check_report: Path | None = None,
        persona_version: str = "persona-v1",
        prompt_version: str = "prompt-v1",
    ) -> subprocess.CompletedProcess[str]:
        run_id = run_id or f"run-{reviewer}-{route}"
        if report is None:
            report = self.lesson_dir() / f"review-report-{reviewer}-{route}-{run_id}.md"
            report.write_text(f"review by {reviewer} via {route} in {run_id}\n", encoding="utf-8")
        if stage in REVIEW_STAGES and quote_check_report is None:
            quote_check_report = self.lesson_dir() / f"quote-check-{stage}.json"
            if not quote_check_report.exists():
                checklist = self.lesson_dir() / f"quote-checklist-{stage}.json"
                checklist.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "record_type": "verbatim-quote-checklist",
                            "lesson_id": self.lesson_id,
                            "sources": [],
                            "quotes": [],
                        }
                    ),
                    encoding="utf-8",
                )
                quote_check_report.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "record_type": "verbatim-quote-check-report",
                            "lesson_id": self.lesson_id,
                            "checklist": {
                                "path": checklist.name,
                                "sha256": hashlib.sha256(checklist.read_bytes()).hexdigest(),
                            },
                            "sources": [{"source_id": "fixture"}],
                            "ok": True,
                            "summary": {"passed": 1, "different": 0, "total": 1},
                            "results": [{"quote_id": "Q-01", "status": "passed"}],
                            "differences": [],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
        quote_check_arguments = (
            ["--quote-check-report", str(quote_check_report)]
            if quote_check_report is not None
            else []
        )
        return self.run_cli(
            "record-review",
            "--lesson-id",
            self.lesson_id,
            "--stage",
            stage,
            "--reviewer-id",
            reviewer,
            "--route-id",
            route,
            "--provider",
            f"provider-{route}",
            "--model",
            f"model-{route}",
            "--runtime-mode",
            "online",
            "--run-id",
            run_id,
            "--persona-version",
            persona_version,
            "--prompt-version",
            prompt_version,
            "--report",
            str(report),
            "--verdict",
            verdict,
            *quote_check_arguments,
            *input_arguments,
        )

    def approve_current(
        self,
        revision: int,
        *,
        next_stage: str | None = None,
        prepare_reviews: bool = True,
        prepared: tuple[str, list[str], list[Path]] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], tuple[str, list[str], list[Path]], Path]:
        stage, input_arguments, paths = prepared or self.make_stage_inputs(revision)
        if prepare_reviews and stage in REVIEW_STAGES:
            for reviewer, route in (("reviewer-a", "route-a"), ("reviewer-b", "route-b")):
                result = self.record_review(
                    stage, input_arguments, reviewer=f"{reviewer}-{revision}", route=f"{route}-{revision}"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
        confirmation = self.confirmation(
            revision,
            stage,
            resource_choice=(
                "handout"
                if stage == "teaching-design" and next_stage == "student-resources"
                else "ppt-only" if stage == "teaching-design" else None
            ),
        )
        arguments = [
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            str(revision),
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(confirmation),
            *input_arguments,
        ]
        if next_stage:
            arguments.extend(["--next-stage", next_stage])
        return self.run_cli(*arguments), (stage, input_arguments, paths), confirmation

    def make_revision_inputs(
        self, stage: str, label: str
    ) -> tuple[list[str], list[Path]]:
        arguments: list[str] = []
        paths: list[Path] = []
        role_paths: dict[str, Path] = {}
        contract_markers = {
            "teaching-design": "OBJ-01 MAT-01 TASK-01 ASM-01",
            "student-handout": "OBJ-01 MAT-01 TASK-01 ASM-01",
            "teacher-answer": "TASK-01 ASM-01 ANS-01",
            "teaching-script": (
                "OBJ-01 TASK-01 SCRIPT-01"
                if {"student-handout", "teacher-answer"}.issubset(
                    self.active_source_artifact_hashes()
                )
                else "OBJ-01 TASK-01 ASM-01 ANS-01 SCRIPT-01"
            ),
        }
        for number, role in enumerate(REQUIRED_ROLES[stage]):
            suffix = ".json" if role in {
                "text-contract",
                "text-contract-report",
                "ppt-structured",
                "ppt-contract-report",
            } else ".md"
            path = self.lesson_dir() / f"revision-{label}-{role}{suffix}"
            path.write_text(
                f"# revised:{self.lesson_id}:{stage}:{label}:{role}:{number}\n"
                f"{contract_markers.get(role, 'stage fixture')}\n",
                encoding="utf-8",
            )
            arguments.extend(["--input", f"{role}={path}"])
            paths.append(path)
            role_paths[role] = path
        self.write_contract_gate_fixture(stage, role_paths, f"revision-{label}")
        return arguments, paths

    def revise_stage(
        self,
        stage: str,
        label: str,
        *,
        expected_revision: int | None = None,
        prepared: tuple[list[str], list[Path]] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[str], list[Path]]:
        input_arguments, paths = prepared or self.make_revision_inputs(stage, label)
        revision = int(self.state()["revision"]) if expected_revision is None else expected_revision
        reason = f"revise {stage} for {label}"
        confirmation = self.revision_confirmation(stage, label, reason)
        result = self.run_cli(
            "revise",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            str(revision),
            "--stage",
            stage,
            "--user-id",
            "teacher-user",
            "--reason",
            reason,
            "--confirmation",
            str(confirmation),
            *input_arguments,
        )
        return result, input_arguments, paths

    def advance_to(self, target: str) -> None:
        if not (self.lesson_dir() / "state.json").exists():
            self.init_lesson()
        while self.state()["current_stage"] != target:
            revision = int(self.state()["revision"])
            result, _, _ = self.approve_current(
                revision,
                next_stage=(
                    "student-resources"
                    if self.state()["current_stage"] == "teaching-design"
                    else None
                ),
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_data_home_is_explicit(self) -> None:
        result = self.run_cli("doctor", use_data_home=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--data-home", result.stderr)

    def test_schemas_require_adoption_roles_and_all_typed_record_variants(self) -> None:
        schema_root = SKILL_ROOT / "references" / "schemas"
        lesson_schema = json.loads(
            (schema_root / "lesson-state.schema.json").read_text(encoding="utf-8")
        )
        record_schema = json.loads(
            (schema_root / "approval-record.schema.json").read_text(encoding="utf-8")
        )

        self.assertIn("adoption", lesson_schema["required"])
        self.assertIn("invalidations", lesson_schema["properties"])
        self.assertIn("active_approval_ids", lesson_schema["properties"])
        self.assertIn("contract_gate_enforced_after_revision", lesson_schema["properties"])
        artifact = lesson_schema["properties"]["artifacts"]["items"]
        self.assertIn("role", artifact["required"])
        self.assertEqual(artifact["properties"]["role"]["$ref"], "#/$defs/role")

        variants = {}
        for branch in record_schema["oneOf"]:
            definition = record_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
            record_type = definition["properties"]["record_type"]["const"]
            variants[record_type] = definition
            self.assertIn("record_type", definition["required"])
        self.assertEqual(
            set(variants),
            {
                "legacy-adoption",
                "online-quality-review",
                "user-stage-approval",
                "user-confirmation",
                "user-batch-confirmation",
                "user-revision-confirmation",
                "stage-invalidation",
            },
        )
        self.assertEqual(
            variants["legacy-adoption"]["properties"]["artifacts"]["items"]["$ref"],
            "#/$defs/roleBoundFile",
        )
        approval = variants["user-stage-approval"]
        self.assertNotIn("approver", approval["properties"])
        self.assertTrue(
            {"user_id", "confirmation", "quality_reviews"}.issubset(approval["required"])
        )
        role_bound_file = record_schema["$defs"]["roleBoundFile"]
        self.assertIn("role", role_bound_file["required"])
        review = variants["online-quality-review"]
        self.assertTrue(
            {
                "reviewer_type",
                "runtime_mode",
                "run_id",
                "persona_version",
                "prompt_version",
                "report",
                "quote_check_report",
            }.issubset(review["required"])
        )
        confirmation = variants["user-confirmation"]
        self.assertTrue(
            {
                "source",
                "host",
                "conversation_id",
                "message_id",
                "confirmed_at",
                "decision_text",
            }.issubset(confirmation["required"])
        )
        self.assertNotIn("resource_choice", confirmation["required"])
        self.assertEqual(
            confirmation["properties"]["resource_choice"]["enum"],
            ["ppt-only", "handout"],
        )
        batch_confirmation = variants["user-batch-confirmation"]
        self.assertIn("stages", batch_confirmation["required"])
        invalidation = variants["stage-invalidation"]
        self.assertTrue(
            {
                "invalidation_id",
                "target_stage",
                "expected_revision",
                "resulting_revision",
                "inputs",
                "confirmation",
                "invalidated_approval_ids",
            }.issubset(invalidation["required"])
        )
        revision_confirmation = variants["user-revision-confirmation"]
        self.assertTrue(
            {
                "reason",
                "source",
                "host",
                "conversation_id",
                "message_id",
                "confirmed_at",
                "decision_text",
            }.issubset(revision_confirmation["required"])
        )

    def test_new_init_is_fixed_to_lesson_brief_draft_and_rejects_stage_override(self) -> None:
        state = self.init_lesson()
        self.assertEqual((state["origin"], state["current_stage"], state["status"]), ("new", "lesson-brief", "draft"))
        self.assertIsNone(state["adoption"])
        blocked = self.run_cli(
            "init", "--lesson-id", "skip", "--current-stage", "teaching-design"
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertFalse((self.lesson_dir("skip") / "state.json").exists())

    def test_adopt_creates_typed_read_only_snapshot_without_advancing(self) -> None:
        directory = self.lesson_dir()
        directory.mkdir(parents=True)
        brief = directory / "brief.md"
        dossier = directory / "dossier.md"
        brief.write_text("brief\n", encoding="utf-8")
        dossier.write_text("dossier\n", encoding="utf-8")
        result = self.run_cli(
            "adopt",
            "--lesson-id",
            self.lesson_id,
            "--current-stage",
            "stance-selection",
            "--status",
            "review",
            "--user-id",
            "teacher-user",
            "--reason",
            "migrate legacy lesson",
            "--artifact",
            f"lesson-brief={brief}",
            "--artifact",
            f"evidence-dossier={dossier}",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual((state["current_stage"], state["status"], state["revision"]), ("stance-selection", "review", 0))
        snapshot = directory / state["adoption"]["file"]
        record = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertEqual(record["record_type"], "legacy-adoption")
        self.assertFalse(snapshot.stat().st_mode & stat.S_IWUSR)
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_adopt_rejects_route_freeze_and_later_stages(self) -> None:
        directory = self.lesson_dir()
        directory.mkdir(parents=True)
        package = directory / "package.md"
        package.write_text("legacy package\n", encoding="utf-8")
        blocked = self.run_cli(
            "adopt",
            "--lesson-id",
            self.lesson_id,
            "--current-stage",
            "release",
            "--status",
            "review",
            "--user-id",
            "teacher-user",
            "--reason",
            "unsafe direct release adoption",
            "--artifact",
            f"manifest={package}",
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("invalid choice", blocked.stderr)
        self.assertFalse((directory / "state.json").exists())

    def test_adopted_revision_zero_status_must_match_immutable_snapshot(self) -> None:
        directory = self.lesson_dir()
        directory.mkdir(parents=True)
        brief = directory / "brief.md"
        brief.write_text("brief\n", encoding="utf-8")
        adopted = self.run_cli(
            "adopt",
            "--lesson-id",
            self.lesson_id,
            "--current-stage",
            "lesson-brief",
            "--status",
            "review",
            "--user-id",
            "teacher-user",
            "--reason",
            "migrate legacy lesson",
            "--artifact",
            f"lesson-brief={brief}",
        )
        self.assertEqual(adopted.returncode, 0, adopted.stderr)
        state = self.state()
        state["status"] = "draft"
        (directory / "state.json").write_text(json.dumps(state), encoding="utf-8")

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 1)
        kinds = {issue["kind"] for issue in json.loads(verified.stdout)["issues"]}
        self.assertIn("adoption-initial-status-mismatch", kinds)

    def test_repair_adoption_migrates_legacy_revision_zero_state_without_stage_change(self) -> None:
        directory = self.lesson_dir()
        directory.mkdir(parents=True)
        brief = directory / "brief.md"
        dossier = directory / "dossier.md"
        brief.write_text("brief\n", encoding="utf-8")
        dossier.write_text("dossier\n", encoding="utf-8")
        now = "2026-07-18T00:00:00Z"
        legacy = {
            "schema_version": "1.0",
            "lesson_id": self.lesson_id,
            "revision": 0,
            "initial_stage": "stance-selection",
            "current_stage": "stance-selection",
            "current_stage_index": 3,
            "status": "review",
            "origin": "adopted",
            "artifacts": [
                {"path": "brief.md", "sha256": hashlib.sha256(brief.read_bytes()).hexdigest(), "size": brief.stat().st_size, "registered_at": now},
                {"path": "dossier.md", "sha256": hashlib.sha256(dossier.read_bytes()).hexdigest(), "size": dossier.stat().st_size, "registered_at": now},
            ],
            "approvals": [],
            "created_at": now,
            "updated_at": now,
        }
        (directory / "state.json").write_text(json.dumps(legacy), encoding="utf-8")
        result = self.run_cli(
            "repair-adoption",
            "--lesson-id",
            self.lesson_id,
            "--expected-stage",
            "stance-selection",
            "--expected-status",
            "review",
            "--user-id",
            "teacher-user",
            "--reason",
            "attach verifiable migration evidence",
            "--artifact",
            f"lesson-brief={brief}",
            "--artifact",
            f"evidence-dossier={dossier}",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        repaired = json.loads(result.stdout)
        self.assertEqual((repaired["current_stage"], repaired["revision"]), ("stance-selection", 0))
        self.assertIsNotNone(repaired["adoption"])
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_approval_is_typed_user_evidence_with_role_and_confirmation(self) -> None:
        self.init_lesson()
        result, _, confirmation = self.approve_current(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        snapshot = self.lesson_dir() / state["approvals"][0]["file"]
        record = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertEqual(record["record_type"], "user-stage-approval")
        self.assertEqual(record["user_id"], "teacher-user")
        self.assertEqual(record["inputs"][0]["role"], "lesson-brief")
        self.assertEqual(record["confirmation"]["path"], confirmation.name)

    def test_confirmation_without_host_message_provenance_is_rejected(self) -> None:
        self.init_lesson()
        stage, input_arguments, _ = self.make_stage_inputs(0)
        confirmation = self.lesson_dir() / "legacy-confirmation.json"
        confirmation.write_text(
            json.dumps(
                {
                    "record_type": "user-confirmation",
                    "lesson_id": self.lesson_id,
                    "stage": stage,
                    "user_id": "teacher-user",
                    "decision": "approve",
                }
            ),
            encoding="utf-8",
        )
        blocked = self.run_cli(
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            "0",
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(confirmation),
            *input_arguments,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("host/conversation_id/message_id", blocked.stderr)
        self.assertEqual(self.state()["revision"], 0)

    def test_one_batch_confirmation_can_bind_consecutive_non_redline_stages(self) -> None:
        self.init_lesson()
        stages = ["lesson-brief", "research-plan", "evidence-dossier"]
        confirmation = self.batch_confirmation(0, stages)
        approval_records = []
        for expected_stage in stages:
            revision = int(self.state()["revision"])
            stage, input_arguments, _ = self.make_stage_inputs(revision)
            self.assertEqual(stage, expected_stage)
            approved = self.run_cli(
                "approve",
                "--lesson-id",
                self.lesson_id,
                "--expected-revision",
                str(revision),
                "--user-id",
                "teacher-user",
                "--confirmation",
                str(confirmation),
                *input_arguments,
            )
            self.assertEqual(approved.returncode, 0, approved.stderr)
            reference = self.state()["approvals"][-1]
            approval_records.append(
                json.loads(
                    (self.lesson_dir() / reference["file"]).read_text(encoding="utf-8")
                )
            )

        self.assertEqual(
            {record["confirmation"]["sha256"] for record in approval_records},
            {hashlib.sha256(confirmation.read_bytes()).hexdigest()},
        )
        self.assertTrue(
            all(record["confirmation_mode"] == "batch" for record in approval_records)
        )
        self.assertTrue(
            all(record["confirmation_stages"] == stages for record in approval_records)
        )
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_batch_confirmation_rejects_nonconsecutive_and_redline_stages(self) -> None:
        for suffix, stages, expected_error in (
            (
                "gap",
                ["lesson-brief", "evidence-dossier"],
                "continuous stages",
            ),
            (
                "redline",
                [
                    "lesson-brief",
                    "research-plan",
                    "evidence-dossier",
                    "stance-selection",
                    "route-freeze",
                    "teaching-design",
                ],
                "independent confirmation",
            ),
        ):
            lesson_id = f"batch-{suffix}"
            self.init_lesson(lesson_id)
            stage, input_arguments, _ = self.make_stage_inputs(0, lesson_id=lesson_id)
            confirmation = self.batch_confirmation(0, stages, lesson_id=lesson_id)
            blocked = self.run_cli(
                "approve",
                "--lesson-id",
                lesson_id,
                "--expected-revision",
                "0",
                "--user-id",
                "teacher-user",
                "--confirmation",
                str(confirmation),
                *input_arguments,
            )
            self.assertEqual(stage, "lesson-brief")
            self.assertEqual(blocked.returncode, 2)
            self.assertIn(expected_error, blocked.stderr)
            self.assertEqual(self.state(lesson_id)["revision"], 0)

    def test_ai_review_cannot_replace_user_confirmation_and_role_gate_blocks_placeholder(self) -> None:
        self.init_lesson()
        stage, input_arguments, paths = self.make_stage_inputs(0)
        fake = self.record_review(stage, input_arguments, reviewer="ai", route="route-ai")
        self.assertEqual(fake.returncode, 0, fake.stderr)
        blocked = self.run_cli(
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            "0",
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(next((self.lesson_dir() / "reviews").glob("*.json"))),
            "--input",
            f"wrong-role={paths[0]}",
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(self.state()["revision"], 0)

    def test_record_review_requires_provenance_and_separate_report(self) -> None:
        self.init_lesson()
        stage, input_arguments, paths = self.make_stage_inputs(0)
        missing = self.run_cli(
            "record-review",
            "--lesson-id",
            self.lesson_id,
            "--stage",
            stage,
            "--reviewer-id",
            "reviewer-a",
            "--route-id",
            "route-a",
            "--provider",
            "provider-a",
            "--model",
            "model-a",
            "--runtime-mode",
            "online",
            "--verdict",
            "pass",
            *input_arguments,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--run-id", missing.stderr)

        reused = self.record_review(
            stage,
            input_arguments,
            reviewer="reviewer-a",
            route="route-a",
            report=paths[0],
        )
        self.assertEqual(reused.returncode, 2)
        self.assertIn("separate from every stage input", reused.stderr)

    def test_legacy_free_form_review_records_do_not_qualify(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-design")
        prepared = self.make_stage_inputs(5)
        stage_input = prepared[2][0]
        inputs = [
            {
                "role": "teaching-design",
                "path": stage_input.name,
                "sha256": hashlib.sha256(stage_input.read_bytes()).hexdigest(),
                "size": stage_input.stat().st_size,
            }
        ]
        review_dir = self.lesson_dir() / "reviews"
        for number in (1, 2):
            legacy = {
                "schema_version": "1.0",
                "record_type": "online-quality-review",
                "review_id": f"review-{'a' * 31}{number}",
                "lesson_id": self.lesson_id,
                "stage": "teaching-design",
                "reviewer_id": f"legacy-reviewer-{number}",
                "route_id": f"legacy-route-{number}",
                "provider": "legacy-provider",
                "model": "legacy-model",
                "runtime": "online",
                "verdict": "pass",
                "comment": None,
                "reviewed_at": "2026-07-18T00:00:00Z",
                "inputs": inputs,
            }
            (review_dir / f"legacy-{number}.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )
        blocked, _, _ = self.approve_current(5, prepare_reviews=False, prepared=prepared)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("two passing independent", blocked.stderr)

    def test_teaching_design_requires_two_independent_online_reviews(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-design")
        prepared = self.make_stage_inputs(5)
        blocked, _, _ = self.approve_current(5, prepare_reviews=False, prepared=prepared)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("two passing independent online quality reviews", blocked.stderr)
        one = self.record_review(prepared[0], prepared[1], reviewer="reviewer-a", route="same")
        two_same = self.record_review(prepared[0], prepared[1], reviewer="reviewer-b", route="same")
        self.assertEqual((one.returncode, two_same.returncode), (0, 0))
        still_blocked, _, _ = self.approve_current(5, prepare_reviews=False, prepared=prepared)
        self.assertEqual(still_blocked.returncode, 2)
        independent = self.record_review(prepared[0], prepared[1], reviewer="reviewer-c", route="other")
        self.assertEqual(independent.returncode, 0, independent.stderr)
        approved, _, _ = self.approve_current(5, prepare_reviews=False, prepared=prepared)
        self.assertEqual(approved.returncode, 0, approved.stderr)

    def test_two_review_routes_require_distinct_run_ids_and_report_paths(self) -> None:
        for suffix, shared_field in (("shared-run", "run"), ("shared-report", "report")):
            with self.subTest(shared_field=shared_field):
                self.lesson_id = suffix
                self.init_lesson()
                self.advance_to("teaching-design")
                prepared = self.make_stage_inputs(5)
                common_report = self.lesson_dir() / "shared-review-report.md"
                common_report.write_text("shared review body\n", encoding="utf-8")
                first = self.record_review(
                    prepared[0],
                    prepared[1],
                    reviewer="reviewer-a",
                    route="route-a",
                    run_id="same-run" if shared_field == "run" else "run-a",
                    report=common_report if shared_field == "report" else None,
                )
                second = self.record_review(
                    prepared[0],
                    prepared[1],
                    reviewer="reviewer-b",
                    route="route-b",
                    run_id="same-run" if shared_field == "run" else "run-b",
                    report=common_report if shared_field == "report" else None,
                )
                self.assertEqual((first.returncode, second.returncode), (0, 0))
                blocked, _, _ = self.approve_current(
                    5, prepare_reviews=False, prepared=prepared
                )
                self.assertEqual(blocked.returncode, 2)
                self.assertIn("two passing independent", blocked.stderr)

    def test_failed_or_missing_quote_check_blocks_dual_review(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-design")
        stage, input_arguments, _ = self.make_stage_inputs(5)
        missing_review_report = self.lesson_dir() / "missing-review-report.md"
        missing_review_report.write_text("review\n", encoding="utf-8")
        missing = self.run_cli(
            "record-review",
            "--lesson-id",
            self.lesson_id,
            "--stage",
            stage,
            "--reviewer-id",
            "reviewer-a",
            "--route-id",
            "route-a",
            "--provider",
            "provider-a",
            "--model",
            "model-a",
            "--runtime-mode",
            "online",
            "--run-id",
            "run-a",
            "--persona-version",
            "persona-v1",
            "--prompt-version",
            "prompt-v1",
            "--report",
            str(missing_review_report),
            "--verdict",
            "pass",
            *input_arguments,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("quote-check-report", missing.stderr)

        failed_report = self.lesson_dir() / "failed-quote-check.json"
        failed_report.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "record_type": "verbatim-quote-check-report",
                    "lesson_id": self.lesson_id,
                    "ok": False,
                    "summary": {"passed": 0, "different": 1, "total": 1},
                    "differences": [{"quote_id": "Q-01"}],
                }
            ),
            encoding="utf-8",
        )
        blocked = self.record_review(
            stage,
            input_arguments,
            reviewer="reviewer-a",
            route="route-a",
            quote_check_report=failed_report,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("verbatim quote check failed", blocked.stderr)

    def test_review_report_tampering_blocks_verify(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-design")
        prepared = self.make_stage_inputs(5)
        for reviewer, route in (("reviewer-a", "route-a"), ("reviewer-b", "route-b")):
            result = self.record_review(
                prepared[0], prepared[1], reviewer=reviewer, route=route
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        approved, _, _ = self.approve_current(5, prepare_reviews=False, prepared=prepared)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        approval = json.loads(
            (self.lesson_dir() / self.state()["approvals"][-1]["file"]).read_text(
                encoding="utf-8"
            )
        )
        review_snapshot = self.lesson_dir() / approval["quality_reviews"][0]["file"]
        review = json.loads(review_snapshot.read_text(encoding="utf-8"))
        report = self.lesson_dir() / review["report"]["path"]
        report.write_text("tampered review body\n", encoding="utf-8")

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 1)
        kinds = {issue["kind"] for issue in json.loads(verified.stdout)["issues"]}
        self.assertIn("quality-review-report-hash-mismatch", kinds)

    def test_legacy_reviews_with_retrospective_evidence_get_distinct_status(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-design")
        prepared = self.make_stage_inputs(5)
        for reviewer, route in (("reviewer-a", "route-a"), ("reviewer-b", "route-b")):
            result = self.record_review(
                prepared[0], prepared[1], reviewer=reviewer, route=route
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        approved, _, _ = self.approve_current(5, prepare_reviews=False, prepared=prepared)
        self.assertEqual(approved.returncode, 0, approved.stderr)

        state_path = self.lesson_dir() / "state.json"
        state = self.state()
        approval_reference = state["approvals"][-1]
        approval_path = self.lesson_dir() / approval_reference["file"]
        approval_path.chmod(0o644)
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        approval["approved_at"] = "2026-07-19T04:22:26Z"
        retrospective_report = None
        affected_reviews = []
        for review_reference in approval["quality_reviews"]:
            review_path = self.lesson_dir() / review_reference["file"]
            review_path.chmod(0o644)
            review = json.loads(review_path.read_text(encoding="utf-8"))
            retrospective_report = retrospective_report or review["quote_check_report"]
            review.pop("quote_check_report")
            review["reviewed_at"] = "2026-07-19T04:19:28Z"
            review_path.write_text(
                json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(review_path.read_bytes()).hexdigest()
            review_reference["snapshot_sha256"] = digest
            affected_reviews.append({"path": review_reference["file"], "sha256": digest})
        self.assertIsNotNone(retrospective_report)
        report_path = self.lesson_dir() / retrospective_report["path"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["verification_context"] = {
            "kind": "retrospective",
            "generated_at": "2026-07-19T08:00:00Z",
            "note": "追溯核对，生成于 alpha.10 逐字校对门之后，不冒充审批当时存在",
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        retrospective_report = {
            "path": retrospective_report["path"],
            "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "size": report_path.stat().st_size,
        }
        approval_path.write_text(
            json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        approval_digest = hashlib.sha256(approval_path.read_bytes()).hexdigest()
        approval_reference["snapshot_sha256"] = approval_digest
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        before = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(before.returncode, 1)
        self.assertEqual(len(json.loads(before.stdout)["issues"]), 5)

        compatibility_dir = self.lesson_dir() / "compatibility"
        compatibility_dir.mkdir()
        record = {
            "schema_version": "1.0",
            "record_type": "historical-review-compatibility",
            "lesson_id": self.lesson_id,
            "stage": "teaching-design",
            "generated_at": "2026-07-19T08:00:00Z",
            "policy_cutoff": "2026-07-19T05:49:57Z",
            "compatibility_status": "historical-compatible-retrospective-evidence",
            "statement": "追溯核对，生成于 alpha.10 逐字校对门之后，不冒充审批当时存在",
            "approval": {"path": approval_reference["file"], "sha256": approval_digest},
            "affected_reviews": affected_reviews,
            "retrospective_quote_check": retrospective_report,
        }
        compatibility_path = (
            compatibility_dir / "historical-review-compatibility-teaching-design.json"
        )
        compatibility_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        compatible = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(compatible.returncode, 3, compatible.stdout + compatible.stderr)
        result = json.loads(compatible.stdout)
        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(
            result["verification_status"],
            "historical-compatible-retrospective-evidence",
        )
        self.assertEqual(len(result["compatibility"]), 1)

        approval["approved_at"] = "2026-07-19T06:00:00Z"
        approval_path.write_text(
            json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        late_approval_digest = hashlib.sha256(approval_path.read_bytes()).hexdigest()
        approval_reference["snapshot_sha256"] = late_approval_digest
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record["approval"]["sha256"] = late_approval_digest
        compatibility_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        late_approval = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(late_approval.returncode, 1)
        late_kinds = {
            item["kind"] for item in json.loads(late_approval.stdout)["issues"]
        }
        self.assertIn("invalid-historical-review-compatibility", late_kinds)

        approval["approved_at"] = "2026-07-19T04:22:26Z"
        approval_path.write_text(
            json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        approval_digest = hashlib.sha256(approval_path.read_bytes()).hexdigest()
        approval_reference["snapshot_sha256"] = approval_digest
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record["approval"]["sha256"] = approval_digest
        compatibility_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        continued, _, _ = self.approve_current(6)
        self.assertEqual(continued.returncode, 0, continued.stderr)

        report_path.write_text("{}\n", encoding="utf-8")
        tampered = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(tampered.returncode, 1)
        kinds = {item["kind"] for item in json.loads(tampered.stdout)["issues"]}
        self.assertIn("invalid-historical-review-compatibility", kinds)

    def test_ppt_text_default_and_explicit_external_route(self) -> None:
        self.init_lesson()
        self.advance_to("ppt-text")
        revision = int(self.state()["revision"])
        result, _, _ = self.approve_current(revision)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["current_stage"], "release")

        other = "external-route"
        self.run_cli("init", "--lesson-id", other)
        original = self.lesson_id
        self.lesson_id = other
        try:
            self.advance_to("ppt-text")
            revision = int(self.state()["revision"])
            result, _, _ = self.approve_current(revision, next_stage="external-ppt-check")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.state()["current_stage"], "external-ppt-check")
        finally:
            self.lesson_id = original

    def test_teaching_design_resource_choice_controls_default_and_handout_route(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-design")
        revision = int(self.state()["revision"])
        defaulted, _, default_confirmation = self.approve_current(revision)
        self.assertEqual(defaulted.returncode, 0, defaulted.stderr)
        self.assertEqual(self.state()["current_stage"], "teaching-script")
        default_value = json.loads(
            default_confirmation.read_text(encoding="utf-8")
        )
        self.assertEqual(default_value["resource_choice"], "ppt-only")

        original = self.lesson_id
        self.lesson_id = "explicit-handout-route"
        try:
            self.init_lesson()
            self.advance_to("teaching-design")
            revision = int(self.state()["revision"])
            selected, _, handout_confirmation = self.approve_current(
                revision, next_stage="student-resources"
            )
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertEqual(self.state()["current_stage"], "student-resources")
            handout_value = json.loads(
                handout_confirmation.read_text(encoding="utf-8")
            )
            self.assertEqual(handout_value["resource_choice"], "handout")
        finally:
            self.lesson_id = original

    def test_teaching_design_resource_choice_is_required_and_must_match_route(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-design")
        revision = int(self.state()["revision"])
        stage, input_arguments, _ = self.make_stage_inputs(revision)
        for reviewer, route in (("resource-a", "route-a"), ("resource-b", "route-b")):
            reviewed = self.record_review(
                stage,
                input_arguments,
                reviewer=reviewer,
                route=route,
            )
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)

        missing = self.confirmation(revision, stage)
        missing_result = self.run_cli(
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            str(revision),
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(missing),
            *input_arguments,
        )
        self.assertEqual(missing_result.returncode, 2)
        self.assertIn("must explicitly set resource_choice", missing_result.stderr)

        for requested_stage, resource_choice in (
            (None, "handout"),
            ("student-resources", "ppt-only"),
        ):
            with self.subTest(
                requested_stage=requested_stage, resource_choice=resource_choice
            ):
                mismatch = self.confirmation(
                    revision,
                    stage,
                    resource_choice=resource_choice,
                )
                arguments = [
                    "approve",
                    "--lesson-id",
                    self.lesson_id,
                    "--expected-revision",
                    str(revision),
                    "--user-id",
                    "teacher-user",
                    "--confirmation",
                    str(mismatch),
                    *input_arguments,
                ]
                if requested_stage is not None:
                    arguments.extend(["--next-stage", requested_stage])
                mismatch_result = self.run_cli(*arguments)
                self.assertEqual(mismatch_result.returncode, 2)
                self.assertIn(
                    "resource_choice does not match", mismatch_result.stderr
                )
        self.assertEqual(self.state()["revision"], revision)

    def test_legacy_teaching_design_confirmation_without_resource_choice_verifies(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-design")
        revision = int(self.state()["revision"])
        approved, _, confirmation_path = self.approve_current(
            revision, next_stage="student-resources"
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)

        confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
        confirmation.pop("resource_choice")
        confirmation_path.write_text(
            json.dumps(confirmation, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        state = self.state()
        reference = state["approvals"][-1]
        approval_path = self.lesson_dir() / reference["file"]
        approval_path.chmod(0o644)
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        approval["confirmation"]["sha256"] = hashlib.sha256(
            confirmation_path.read_bytes()
        ).hexdigest()
        approval["confirmation"]["size"] = confirmation_path.stat().st_size
        approval_path.write_text(
            json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        reference["snapshot_sha256"] = hashlib.sha256(
            approval_path.read_bytes()
        ).hexdigest()
        (self.lesson_dir() / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_historical_resource_choice_must_match_the_recorded_route(self) -> None:
        original = self.lesson_id
        try:
            for lesson_id, next_stage, wrong_choice in (
                ("history-handout-mismatch", "student-resources", "ppt-only"),
                ("history-ppt-only-mismatch", "teaching-script", "handout"),
            ):
                with self.subTest(
                    next_stage=next_stage, wrong_choice=wrong_choice
                ):
                    self.lesson_id = lesson_id
                    self.init_lesson()
                    self.advance_to("teaching-design")
                    revision = int(self.state()["revision"])
                    approved, _, confirmation_path = self.approve_current(
                        revision, next_stage=next_stage
                    )
                    self.assertEqual(approved.returncode, 0, approved.stderr)

                    confirmation = json.loads(
                        confirmation_path.read_text(encoding="utf-8")
                    )
                    confirmation["resource_choice"] = wrong_choice
                    confirmation_path.write_text(
                        json.dumps(
                            confirmation,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    state = self.state()
                    reference = state["approvals"][-1]
                    approval_path = self.lesson_dir() / reference["file"]
                    approval_path.chmod(0o644)
                    approval = json.loads(
                        approval_path.read_text(encoding="utf-8")
                    )
                    approval["confirmation"]["sha256"] = hashlib.sha256(
                        confirmation_path.read_bytes()
                    ).hexdigest()
                    approval["confirmation"][
                        "size"
                    ] = confirmation_path.stat().st_size
                    approval_path.write_text(
                        json.dumps(
                            approval,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    reference["snapshot_sha256"] = hashlib.sha256(
                        approval_path.read_bytes()
                    ).hexdigest()
                    (self.lesson_dir() / "state.json").write_text(
                        json.dumps(
                            state,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )

                    verified = self.run_cli(
                        "verify", "--lesson-id", self.lesson_id
                    )
                    self.assertEqual(verified.returncode, 1, verified.stdout)
                    invalid = [
                        issue
                        for issue in json.loads(verified.stdout)["issues"]
                        if issue["kind"] == "invalid-user-confirmation"
                    ]
                    self.assertTrue(invalid)
                    self.assertIn(
                        "resource_choice does not match", invalid[0]["detail"]
                    )
        finally:
            self.lesson_id = original

    def test_handout_and_ppt_only_chains_verify_with_explicit_resource_skip(self) -> None:
        self.init_lesson()
        self.advance_to("release")
        handout_verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(
            handout_verified.returncode,
            0,
            handout_verified.stdout + handout_verified.stderr,
        )

        original = self.lesson_id
        self.lesson_id = "ppt-only-chain"
        try:
            self.init_lesson()
            self.advance_to("teaching-design")
            revision = int(self.state()["revision"])
            skipped, _, _ = self.approve_current(
                revision, next_stage="teaching-script"
            )
            self.assertEqual(skipped.returncode, 0, skipped.stderr)
            self.assertEqual(self.state()["current_stage"], "teaching-script")
            approval_reference = self.state()["approvals"][-1]
            approval_record = json.loads(
                (self.lesson_dir() / approval_reference["file"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(approval_record["next_stage"], "teaching-script")
            skip_verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
            self.assertEqual(
                skip_verified.returncode,
                0,
                skip_verified.stdout + skip_verified.stderr,
            )

            self.advance_to("release")
            ppt_only_verified = self.run_cli(
                "verify", "--lesson-id", self.lesson_id
            )
            self.assertEqual(
                ppt_only_verified.returncode,
                0,
                ppt_only_verified.stdout + ppt_only_verified.stderr,
            )
            contract_path = self.active_text_contract_path()
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual(contract["mode"], "ppt-only")
            self.assertEqual(
                set(contract["artifacts"]),
                {"teaching-design", "teaching-script"},
            )
        finally:
            self.lesson_id = original

    def test_text_contract_stage_rejects_nonpassing_or_unbound_report(self) -> None:
        self.init_lesson()
        self.advance_to("text-contract")
        revision = int(self.state()["revision"])
        prepared = self.make_stage_inputs(revision)
        role_paths = {
            role: path
            for role, path in zip(REQUIRED_ROLES["text-contract"], prepared[2])
        }
        report_path = role_paths["text-contract-report"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["ok"] = False
        report["issues"] = [
            {
                "code": "fixture-failure",
                "path": "$.fixture",
                "message": "intentional non-passing report",
            }
        ]
        report_path.write_text(json.dumps(report), encoding="utf-8")

        blocked_review = self.record_review(
            "text-contract",
            prepared[1],
            reviewer="reviewer-a",
            route="route-a",
        )
        self.assertEqual(blocked_review.returncode, 2)
        self.assertIn("contract-report-not-passing", blocked_review.stderr)

        report["ok"] = True
        report["issues"] = []
        report["text_contract_sha256"] = "0" * 64
        report_path.write_text(json.dumps(report), encoding="utf-8")
        blocked_review = self.record_review(
            "text-contract",
            prepared[1],
            reviewer="reviewer-a2",
            route="route-a2",
        )
        self.assertEqual(blocked_review.returncode, 2)
        self.assertIn("contract-report-text-contract-hash-mismatch", blocked_review.stderr)

    def test_text_contract_stage_rejects_schema_invalid_contract(self) -> None:
        self.init_lesson()
        self.advance_to("text-contract")
        prepared = self.make_stage_inputs(int(self.state()["revision"]))
        role_paths = {
            role: path
            for role, path in zip(REQUIRED_ROLES["text-contract"], prepared[2])
        }
        contract_path = role_paths["text-contract"]
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["unexpected"] = "not allowed by bundled schema"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        blocked = self.record_review(
            "text-contract",
            prepared[1],
            reviewer="schema-contract",
            route="schema-contract-route",
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("text-contract-schema-invalid", blocked.stderr)

    def test_text_contract_stage_rejects_schema_invalid_report(self) -> None:
        self.init_lesson()
        self.advance_to("text-contract")
        prepared = self.make_stage_inputs(int(self.state()["revision"]))
        role_paths = {
            role: path
            for role, path in zip(REQUIRED_ROLES["text-contract"], prepared[2])
        }
        report_path = role_paths["text-contract-report"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report.pop("counts")
        report_path.write_text(json.dumps(report), encoding="utf-8")

        blocked = self.record_review(
            "text-contract",
            prepared[1],
            reviewer="schema-report",
            route="schema-report-route",
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("contract-report-schema-invalid", blocked.stderr)

    def test_text_contract_stage_reruns_semantics_instead_of_trusting_ok_report(self) -> None:
        self.init_lesson()
        self.advance_to("text-contract")
        prepared = self.make_stage_inputs(int(self.state()["revision"]))
        role_paths = {
            role: path
            for role, path in zip(REQUIRED_ROLES["text-contract"], prepared[2])
        }
        contract_path = role_paths["text-contract"]
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["tasks"][0]["assessment_ids"] = ["ASM-99"]
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        report_path = role_paths["text-contract-report"]
        forged_report = json.loads(report_path.read_text(encoding="utf-8"))
        forged_report["text_contract_sha256"] = hashlib.sha256(
            contract_path.read_bytes()
        ).hexdigest()
        report_path.write_text(json.dumps(forged_report), encoding="utf-8")

        blocked = self.record_review(
            "text-contract",
            prepared[1],
            reviewer="semantic-contract",
            route="semantic-contract-route",
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("text-contract-semantic-validation-failed", blocked.stderr)
        self.assertIn("contract-report-validator-output-mismatch", blocked.stderr)

    def test_ppt_stage_rejects_report_not_bound_to_structured_source(self) -> None:
        self.init_lesson()
        self.advance_to("ppt-text")
        revision = int(self.state()["revision"])
        prepared = self.make_stage_inputs(revision)
        role_paths = {
            role: path for role, path in zip(REQUIRED_ROLES["ppt-text"], prepared[2])
        }
        report_path = role_paths["ppt-contract-report"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["ppt_structured_sha256"] = "0" * 64
        report_path.write_text(json.dumps(report), encoding="utf-8")
        confirmation = self.confirmation(revision, "ppt-text")
        blocked = self.run_cli(
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            str(revision),
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(confirmation),
            *prepared[1],
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("contract-report-ppt-structured-hash-mismatch", blocked.stderr)

    def test_ppt_stage_rejects_schema_invalid_structured_source(self) -> None:
        self.init_lesson()
        self.advance_to("ppt-text")
        revision = int(self.state()["revision"])
        prepared = self.make_stage_inputs(revision)
        role_paths = {
            role: path for role, path in zip(REQUIRED_ROLES["ppt-text"], prepared[2])
        }
        structured_path = role_paths["ppt-structured"]
        structured = json.loads(structured_path.read_text(encoding="utf-8"))
        structured["slides"][0]["page"] = 0
        structured_path.write_text(json.dumps(structured), encoding="utf-8")
        confirmation = self.confirmation(revision, "ppt-text")

        blocked = self.run_cli(
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            str(revision),
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(confirmation),
            *prepared[1],
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("ppt-structured-schema-invalid", blocked.stderr)

    def test_ppt_stage_reruns_semantics_instead_of_trusting_ok_report(self) -> None:
        self.init_lesson()
        self.advance_to("ppt-text")
        revision = int(self.state()["revision"])
        prepared = self.make_stage_inputs(revision)
        role_paths = {
            role: path for role, path in zip(REQUIRED_ROLES["ppt-text"], prepared[2])
        }
        structured_path = role_paths["ppt-structured"]
        structured = json.loads(structured_path.read_text(encoding="utf-8"))
        structured["slides"][0]["script_ids"] = ["SCRIPT-99"]
        structured_path.write_text(json.dumps(structured), encoding="utf-8")
        report_path = role_paths["ppt-contract-report"]
        forged_report = json.loads(report_path.read_text(encoding="utf-8"))
        forged_report["ppt_structured_sha256"] = hashlib.sha256(
            structured_path.read_bytes()
        ).hexdigest()
        report_path.write_text(json.dumps(forged_report), encoding="utf-8")
        confirmation = self.confirmation(revision, "ppt-text")

        blocked = self.run_cli(
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            str(revision),
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(confirmation),
            *prepared[1],
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("ppt-text-semantic-validation-failed", blocked.stderr)
        self.assertIn("contract-report-validator-output-mismatch", blocked.stderr)

    def test_alpha3_history_without_new_contract_report_roles_is_grandfathered(self) -> None:
        self.init_lesson()
        self.advance_to("release")
        state = self.state()
        for stage, retained_role in (
            ("text-contract", "text-contract"),
            ("ppt-text", "ppt-text"),
        ):
            reference = next(item for item in state["approvals"] if item["stage"] == stage)
            approval_path = self.lesson_dir() / reference["file"]
            approval_path.chmod(0o644)
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["inputs"] = [
                item for item in approval["inputs"] if item["role"] == retained_role
            ]
            for review_reference in approval["quality_reviews"]:
                review_path = self.lesson_dir() / review_reference["file"]
                review_path.chmod(0o644)
                review = json.loads(review_path.read_text(encoding="utf-8"))
                review["inputs"] = approval["inputs"]
                review_path.write_text(
                    json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                review_reference["snapshot_sha256"] = hashlib.sha256(
                    review_path.read_bytes()
                ).hexdigest()
            approval_path.write_text(
                json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            reference["snapshot_sha256"] = hashlib.sha256(
                approval_path.read_bytes()
            ).hexdigest()
        state.pop("contract_gate_enforced_after_revision")
        (self.lesson_dir() / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        release_revision = int(self.state()["revision"])
        approved, _, _ = self.approve_current(release_revision)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual(
            self.state()["contract_gate_enforced_after_revision"], release_revision
        )

        revised, _, _ = self.revise_stage("teaching-design", "alpha3-migrated")
        self.assertEqual(revised.returncode, 0, revised.stderr)
        migrated_state = self.state()
        self.assertEqual(
            migrated_state["contract_gate_enforced_after_revision"], release_revision
        )
        migrated_state["contract_gate_enforced_after_revision"] = migrated_state["revision"]
        (self.lesson_dir() / "state.json").write_text(
            json.dumps(migrated_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 1, verified.stdout + verified.stderr)
        kinds = {issue["kind"] for issue in json.loads(verified.stdout)["issues"]}
        self.assertIn(
            "contract-gate-baseline-covers-enforced-invalidation", kinds
        )

    def test_alpha4_contract_gate_baseline_tamper_is_detected(self) -> None:
        self.init_lesson()
        self.advance_to("release")
        state_path = self.lesson_dir() / "state.json"
        original = self.state()

        for mutation in ("raise", "delete"):
            with self.subTest(mutation=mutation):
                tampered = dict(original)
                if mutation == "raise":
                    tampered["contract_gate_enforced_after_revision"] = tampered["revision"]
                else:
                    tampered.pop("contract_gate_enforced_after_revision")
                state_path.write_text(
                    json.dumps(tampered, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
                self.assertEqual(verified.returncode, 1, verified.stdout + verified.stderr)
                kinds = {issue["kind"] for issue in json.loads(verified.stdout)["issues"]}
                self.assertIn(
                    "contract-gate-baseline-covers-enforced-approval", kinds
                )

        state_path.write_text(
            json.dumps(original, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_release_requires_package_checklist_and_manifest(self) -> None:
        self.init_lesson()
        self.advance_to("release")
        revision = int(self.state()["revision"])
        package_checklist = self.lesson_dir() / "package-checklist.md"
        package_checklist.write_text("checked\n", encoding="utf-8")
        confirmation = self.confirmation(revision, "release")
        blocked = self.run_cli(
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            str(revision),
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(confirmation),
            "--input",
            f"package-checklist={package_checklist}",
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("manifest", blocked.stderr)

        approved, _, _ = self.approve_current(revision)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual((self.state()["current_stage"], self.state()["status"]), ("release", "approved"))

    def test_unapproved_state_cannot_be_hand_edited_to_release_approved(self) -> None:
        self.init_lesson()
        state = self.state()
        state["current_stage"] = "release"
        state["current_stage_index"] = STAGES.index("release")
        state["status"] = "approved"
        (self.lesson_dir() / "state.json").write_text(json.dumps(state), encoding="utf-8")

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 1)
        kinds = {issue["kind"] for issue in json.loads(verified.stdout)["issues"]}
        self.assertIn("unapproved-state-stage-mismatch", kinds)
        self.assertIn("unapproved-state-approved-status", kinds)

    def test_tamper_blocks_verify_and_next_approval(self) -> None:
        self.init_lesson()
        approved, prepared, _ = self.approve_current(0)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        prepared[2][0].write_text("tampered\n", encoding="utf-8")
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 1)
        blocked, _, _ = self.approve_current(1)
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(self.state()["revision"], 1)

    def test_revision_invalidates_target_and_all_active_downstream_approvals(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-script")
        before = self.state()
        self.assertEqual(before["revision"], 7)

        revised, _, revised_paths = self.revise_stage("teaching-design", "legal")
        self.assertEqual(revised.returncode, 0, revised.stderr)
        state = json.loads(revised.stdout)
        self.assertEqual(
            (state["revision"], state["current_stage"], state["status"]),
            (8, "teaching-design", "draft"),
        )
        self.assertEqual(len(state["approvals"]), 7)
        self.assertEqual(len(state["invalidations"]), 1)
        self.assertEqual(
            state["active_approval_ids"],
            [f"r{revision:04d}-{STAGES[revision - 1]}" for revision in range(1, 6)],
        )

        reference = state["invalidations"][0]
        snapshot = self.lesson_dir() / reference["file"]
        record = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertEqual(record["record_type"], "stage-invalidation")
        self.assertEqual(
            record["invalidated_approval_ids"],
            ["r0006-teaching-design", "r0007-student-resources"],
        )
        self.assertEqual(record["inputs"][0]["path"], revised_paths[0].name)
        self.assertEqual(
            record["inputs"][0]["sha256"],
            hashlib.sha256(revised_paths[0].read_bytes()).hexdigest(),
        )
        self.assertFalse(snapshot.stat().st_mode & stat.S_IWUSR)
        self.assertTrue(all((self.lesson_dir() / item["file"]).is_file() for item in state["approvals"]))

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_revision_requires_typed_host_conversation_confirmation(self) -> None:
        self.init_lesson()
        self.advance_to("research-plan")
        before = self.state()
        input_arguments, _ = self.make_revision_inputs("lesson-brief", "missing-provenance")
        reason = "revise lesson-brief for missing-provenance"
        confirmation = self.lesson_dir() / "revision-confirmation-without-provenance.json"
        confirmation.write_text(
            json.dumps(
                {
                    "record_type": "user-revision-confirmation",
                    "lesson_id": self.lesson_id,
                    "stage": "lesson-brief",
                    "user_id": "teacher-user",
                    "decision": "revise",
                    "source": "host-conversation",
                    "confirmed_at": "2026-07-18T00:00:00Z",
                    "decision_text": reason,
                    "reason": reason,
                }
            ),
            encoding="utf-8",
        )

        blocked = self.run_cli(
            "revise",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            str(before["revision"]),
            "--stage",
            "lesson-brief",
            "--user-id",
            "teacher-user",
            "--reason",
            reason,
            "--confirmation",
            str(confirmation),
            *input_arguments,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("host/conversation_id/message_id", blocked.stderr)
        after = self.state()
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["invalidations"], [])

    def test_revision_confirmation_tamper_blocks_verify_and_progress(self) -> None:
        self.init_lesson()
        self.advance_to("research-plan")
        revised, input_arguments, paths = self.revise_stage(
            "lesson-brief", "confirmation-tamper"
        )
        self.assertEqual(revised.returncode, 0, revised.stderr)
        confirmation = self.lesson_dir() / "revise-confirm-confirmation-tamper-lesson-brief.json"
        value = json.loads(confirmation.read_text(encoding="utf-8"))
        value["decision_text"] = "tampered but still structurally valid"
        confirmation.write_text(json.dumps(value), encoding="utf-8")

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 1)
        kinds = {issue["kind"] for issue in json.loads(verified.stdout)["issues"]}
        self.assertIn("revision-confirmation-hash-mismatch", kinds)
        blocked, _, _ = self.approve_current(
            int(self.state()["revision"]),
            prepared=("lesson-brief", input_arguments, paths),
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("integrity check failed", blocked.stderr)

    def test_concurrent_revision_with_same_expected_revision_has_one_winner(self) -> None:
        self.init_lesson()
        self.advance_to("research-plan")
        expected_revision = int(self.state()["revision"])
        commands: list[list[str]] = []
        for label in ("concurrent-a", "concurrent-b"):
            reason = f"revise lesson-brief for {label}"
            input_arguments, _ = self.make_revision_inputs("lesson-brief", label)
            confirmation = self.revision_confirmation("lesson-brief", label, reason)
            commands.append(
                [
                    sys.executable,
                    str(SCRIPT),
                    "revise",
                    "--lesson-id",
                    self.lesson_id,
                    "--expected-revision",
                    str(expected_revision),
                    "--stage",
                    "lesson-brief",
                    "--user-id",
                    "teacher-user",
                    "--reason",
                    reason,
                    "--confirmation",
                    str(confirmation),
                    *input_arguments,
                    "--data-home",
                    str(self.data_home),
                ]
            )
        environment = os.environ.copy()
        environment.pop("YUWEN_DATA_HOME", None)
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
            for command in commands
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]

        self.assertEqual(sorted(result[2] for result in results), [0, 2], results)
        state = self.state()
        self.assertEqual(state["revision"], expected_revision + 1)
        self.assertEqual(len(state["invalidations"]), 1)
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_concurrent_approval_and_revision_have_one_winner_without_orphan(self) -> None:
        self.init_lesson()
        self.advance_to("research-plan")
        expected_revision = int(self.state()["revision"])
        stage, approval_arguments, _ = self.make_stage_inputs(expected_revision)
        approval_confirmation = self.confirmation(expected_revision, stage)
        reason = "revise lesson-brief during competing approval"
        revision_arguments, _ = self.make_revision_inputs("lesson-brief", "cross-action")
        revision_confirmation = self.revision_confirmation(
            "lesson-brief", "cross-action", reason
        )
        commands = [
            [
                sys.executable,
                str(SCRIPT),
                "approve",
                "--lesson-id",
                self.lesson_id,
                "--expected-revision",
                str(expected_revision),
                "--user-id",
                "teacher-user",
                "--confirmation",
                str(approval_confirmation),
                *approval_arguments,
                "--data-home",
                str(self.data_home),
            ],
            [
                sys.executable,
                str(SCRIPT),
                "revise",
                "--lesson-id",
                self.lesson_id,
                "--expected-revision",
                str(expected_revision),
                "--stage",
                "lesson-brief",
                "--user-id",
                "teacher-user",
                "--reason",
                reason,
                "--confirmation",
                str(revision_confirmation),
                *revision_arguments,
                "--data-home",
                str(self.data_home),
            ],
        ]
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for command in commands
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual(sorted(result[2] for result in results), [0, 2], results)
        self.assertEqual(self.state()["revision"], expected_revision + 1)
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_revision_rejects_no_change_unreached_stage_and_stale_revision(self) -> None:
        self.init_lesson()
        self.advance_to("student-resources")
        state = self.state()
        teaching_reference = next(
            item for item in state["approvals"] if item["stage"] == "teaching-design"
        )
        teaching_record = json.loads(
            (self.lesson_dir() / teaching_reference["file"]).read_text(encoding="utf-8")
        )
        original = self.lesson_dir() / teaching_record["inputs"][0]["path"]
        unchanged = self.lesson_dir() / "unchanged-teaching-design.md"
        unchanged.write_bytes(original.read_bytes())
        unchanged_args = ["--input", f"teaching-design={unchanged}"]
        blocked, _, _ = self.revise_stage(
            "teaching-design",
            "unchanged",
            expected_revision=int(state["revision"]),
            prepared=(unchanged_args, [unchanged]),
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("does not change stage content", blocked.stderr)
        self.assertEqual(self.state()["revision"], state["revision"])

        unreached, _, _ = self.revise_stage("teaching-script", "unreached")
        self.assertEqual(unreached.returncode, 2)
        self.assertIn("has never reached", unreached.stderr)

        stale, _, _ = self.revise_stage(
            "teaching-design", "stale", expected_revision=int(state["revision"]) - 1
        )
        self.assertEqual(stale.returncode, 2)
        self.assertIn("revision conflict", stale.stderr)
        self.assertEqual(self.state()["revision"], state["revision"])

    def test_revision_can_retain_unchanged_role_at_original_path(self) -> None:
        self.init_lesson()
        self.advance_to("teaching-script")
        state = self.state()
        active_ids = set(state["active_approval_ids"])
        student_approval = None
        for reference in reversed(state["approvals"]):
            if (
                reference["approval_id"] in active_ids
                and reference["stage"] == "student-resources"
            ):
                student_approval = json.loads(
                    (self.lesson_dir() / reference["file"]).read_text(encoding="utf-8")
                )
                break
        self.assertIsNotNone(student_approval)
        previous = {item["role"]: item for item in student_approval["inputs"]}
        unchanged_handout = self.lesson_dir() / previous["student-handout"]["path"]
        revised_answer = self.lesson_dir() / "revision-single-teacher-answer.md"
        revised_answer.write_text(
            "# revised answer\nTASK-01 ASM-01 ANS-01\n",
            encoding="utf-8",
        )
        arguments = [
            "--input",
            f"student-handout={unchanged_handout}",
            "--input",
            f"teacher-answer={revised_answer}",
        ]
        revised, _, _ = self.revise_stage(
            "student-resources",
            "single-role-change",
            prepared=(arguments, [unchanged_handout, revised_answer]),
        )
        self.assertEqual(revised.returncode, 0, revised.stderr)

        invalidation = json.loads(
            (
                self.lesson_dir()
                / self.state()["invalidations"][-1]["file"]
            ).read_text(encoding="utf-8")
        )
        registered = {item["role"]: item for item in invalidation["inputs"]}
        self.assertEqual(
            registered["student-handout"], previous["student-handout"]
        )
        self.assertNotEqual(
            registered["teacher-answer"]["sha256"],
            previous["teacher-answer"]["sha256"],
        )

        revision = int(self.state()["revision"])
        approved, _, _ = self.approve_current(
            revision,
            prepared=("student-resources", arguments, [unchanged_handout, revised_answer]),
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_tampered_invalidation_snapshot_blocks_verify_and_progress(self) -> None:
        self.init_lesson()
        self.advance_to("student-resources")
        revised, _, _ = self.revise_stage("teaching-design", "tamper")
        self.assertEqual(revised.returncode, 0, revised.stderr)
        reference = self.state()["invalidations"][0]
        snapshot = self.lesson_dir() / reference["file"]
        snapshot.chmod(0o644)
        record = json.loads(snapshot.read_text(encoding="utf-8"))
        record["reason"] = "tampered reason"
        snapshot.write_text(json.dumps(record), encoding="utf-8")

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 1)
        kinds = {issue["kind"] for issue in json.loads(verified.stdout)["issues"]}
        self.assertIn("invalidation-snapshot-hash-mismatch", kinds)
        blocked, _, _ = self.approve_current(
            int(self.state()["revision"]), prepare_reviews=False
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("integrity check failed", blocked.stderr)

    def test_revised_stage_can_be_reapproved_and_downstream_rebuilt(self) -> None:
        self.init_lesson()
        self.advance_to("student-resources")
        revised, input_arguments, paths = self.revise_stage("teaching-design", "reapprove")
        self.assertEqual(revised.returncode, 0, revised.stderr)
        revision = int(self.state()["revision"])

        approved, _, _ = self.approve_current(
            revision,
            next_stage="student-resources",
            prepared=("teaching-design", input_arguments, paths),
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual(self.state()["current_stage"], "student-resources")
        self.assertNotIn("r0006-teaching-design", self.state()["active_approval_ids"])
        self.assertIn("r0008-teaching-design", self.state()["active_approval_ids"])

        downstream_revision = int(self.state()["revision"])
        downstream, _, _ = self.approve_current(downstream_revision)
        self.assertEqual(downstream.returncode, 0, downstream.stderr)
        state = self.state()
        self.assertEqual((state["revision"], state["current_stage"]), (9, "teaching-script"))
        self.assertNotIn("r0006-teaching-design", state["active_approval_ids"])
        self.assertIn("r0009-student-resources", state["active_approval_ids"])
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_unchanged_downstream_can_rebuild_from_invalidated_approval(self) -> None:
        self.init_lesson()
        self.advance_to("text-contract")
        before = self.state()
        originals: dict[str, tuple[str, list[str], list[Path]]] = {}
        for stage in ("student-resources", "teaching-script"):
            reference = next(item for item in before["approvals"] if item["stage"] == stage)
            record = json.loads(
                (self.lesson_dir() / reference["file"]).read_text(encoding="utf-8")
            )
            arguments: list[str] = []
            paths: list[Path] = []
            for item in record["inputs"]:
                path = self.lesson_dir() / item["path"]
                arguments.extend(["--input", f"{item['role']}={path}"])
                paths.append(path)
            originals[stage] = (reference["approval_id"], arguments, paths)

        teaching_reference = next(
            item for item in before["approvals"] if item["stage"] == "teaching-design"
        )
        teaching_record = json.loads(
            (self.lesson_dir() / teaching_reference["file"]).read_text(encoding="utf-8")
        )
        original_teaching = self.lesson_dir() / teaching_record["inputs"][0]["path"]
        changed_teaching = self.lesson_dir() / "one-character-upstream-teaching-design.md"
        original_text = original_teaching.read_text(encoding="utf-8")
        changed_teaching.write_text(original_text.replace("#", "##", 1), encoding="utf-8")
        changed_arguments = ["--input", f"teaching-design={changed_teaching}"]
        revised, input_arguments, paths = self.revise_stage(
            "teaching-design",
            "one-character-upstream",
            prepared=(changed_arguments, [changed_teaching]),
        )
        self.assertEqual(revised.returncode, 0, revised.stderr)
        approved, _, _ = self.approve_current(
            int(self.state()["revision"]),
            next_stage="student-resources",
            prepared=("teaching-design", input_arguments, paths),
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)

        for stage in ("student-resources", "teaching-script"):
            inherited_id, original_arguments, _ = originals[stage]
            revision = int(self.state()["revision"])
            confirmation = self.confirmation(revision, stage)
            rebuilt = self.run_cli(
                "approve",
                "--lesson-id",
                self.lesson_id,
                "--expected-revision",
                str(revision),
                "--user-id",
                "teacher-user",
                "--confirmation",
                str(confirmation),
                "--rebuild-from",
                inherited_id,
                *original_arguments,
            )
            self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
            reference = self.state()["approvals"][-1]
            record = json.loads(
                (self.lesson_dir() / reference["file"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                record["rebuild"],
                {"content_unchanged": True, "inherited_approval_id": inherited_id},
            )

        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_rebuild_rejects_changed_content_or_active_source_approval(self) -> None:
        self.init_lesson()
        first, _, _ = self.approve_current(0)
        self.assertEqual(first.returncode, 0, first.stderr)
        active_id = self.state()["approvals"][0]["approval_id"]
        stage, input_arguments, _ = self.make_stage_inputs(1)
        confirmation = self.confirmation(1, stage)
        blocked = self.run_cli(
            "approve",
            "--lesson-id",
            self.lesson_id,
            "--expected-revision",
            "1",
            "--user-id",
            "teacher-user",
            "--confirmation",
            str(confirmation),
            "--rebuild-from",
            active_id,
            *input_arguments,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("invalidated approval", blocked.stderr)

    def test_orphan_recover_commits_only_a_fully_valid_snapshot(self) -> None:
        self.init_lesson()
        before = (self.lesson_dir() / "state.json").read_bytes()
        approved, _, _ = self.approve_current(0)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        (self.lesson_dir() / "state.json").write_bytes(before)
        verify_orphan = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verify_orphan.returncode, 1)
        recovered = self.run_cli(
            "recover", "--lesson-id", self.lesson_id, "--expected-revision", "0"
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(self.state()["revision"], 1)

    def test_orphan_recover_rejects_tampered_confirmation(self) -> None:
        self.init_lesson()
        before = (self.lesson_dir() / "state.json").read_bytes()
        approved, _, confirmation = self.approve_current(0)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        (self.lesson_dir() / "state.json").write_bytes(before)
        confirmation.write_text("{}\n", encoding="utf-8")
        recovered = self.run_cli(
            "recover", "--lesson-id", self.lesson_id, "--expected-revision", "0"
        )
        self.assertEqual(recovered.returncode, 2)
        self.assertIn("failed full recovery validation", recovered.stderr)
        self.assertEqual(self.state()["revision"], 0)

    def test_orphan_invalidation_can_be_recovered_after_state_write_interruption(self) -> None:
        self.init_lesson()
        self.advance_to("research-plan")
        before = (self.lesson_dir() / "state.json").read_bytes()
        revised, _, _ = self.revise_stage("lesson-brief", "orphan-invalidation")
        self.assertEqual(revised.returncode, 0, revised.stderr)
        (self.lesson_dir() / "state.json").write_bytes(before)
        verify_orphan = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verify_orphan.returncode, 1)
        self.assertIn(
            "unreferenced-invalidation-snapshot",
            {issue["kind"] for issue in json.loads(verify_orphan.stdout)["issues"]},
        )
        recovered = self.run_cli(
            "recover", "--lesson-id", self.lesson_id, "--expected-revision", "1"
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(self.state()["revision"], 2)
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_concurrent_init_has_one_winner(self) -> None:
        lesson_id = "concurrent-init"
        command = [
            sys.executable,
            str(SCRIPT),
            "init",
            "--lesson-id",
            lesson_id,
            "--data-home",
            str(self.data_home),
        ]
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(6)
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual(sum(code == 0 for _, _, code in results), 1, results)
        state = self.state(lesson_id)
        self.assertEqual((state["current_stage"], state["status"]), ("lesson-brief", "draft"))
        staging = list((self.data_home / "lessons").glob(f".{lesson_id}.init-*"))
        self.assertEqual(staging, [])

    def test_init_recovers_only_exact_empty_legacy_residue(self) -> None:
        directory = self.lesson_dir()
        directory.mkdir(parents=True)
        (directory / "approvals").mkdir()
        (directory / "reviews").mkdir()

        initialized = self.run_cli("init", "--lesson-id", self.lesson_id)

        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(
            (self.state()["current_stage"], self.state()["status"]),
            ("lesson-brief", "draft"),
        )
        self.assertEqual(
            {path.name for path in directory.iterdir()},
            {"state.json", "approvals", "reviews", "adoptions", "invalidations"},
        )
        verified = self.run_cli("verify", "--lesson-id", self.lesson_id)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_init_preserves_unexpected_existing_content(self) -> None:
        cases = ("file", "nested", "symlink")
        for case in cases:
            lesson_id = f"blocked-init-{case}"
            directory = self.lesson_dir(lesson_id)
            directory.mkdir(parents=True)
            if case == "file":
                unexpected = directory / "keep.txt"
                unexpected.write_text("keep\n", encoding="utf-8")
            elif case == "nested":
                unexpected = directory / "approvals" / "nested"
                unexpected.mkdir(parents=True)
            else:
                target = self.root / "outside-target.txt"
                target.write_text("outside\n", encoding="utf-8")
                unexpected = directory / "approvals"
                try:
                    unexpected.symlink_to(target)
                except (NotImplementedError, OSError):
                    continue

            initialized = self.run_cli("init", "--lesson-id", lesson_id)

            self.assertEqual(initialized.returncode, 2, initialized.stderr)
            self.assertIn("already exists", initialized.stderr)
            self.assertTrue(unexpected.exists() or unexpected.is_symlink())
            self.assertFalse((directory / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
