#!/usr/bin/env python3
"""Fail-closed validation for cross-artifact IDs and PPT text mappings."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable


TEXT_ROLES = (
    "teaching-design",
    "student-handout",
    "teacher-answer",
    "teaching-script",
)
PPT_ONLY_TEXT_ROLES = (
    "teaching-design",
    "teaching-script",
)
PPT_ROLE = "ppt-text"
ID_PATTERNS = {
    "objective": re.compile(r"^OBJ-[0-9]{2,}$"),
    "material": re.compile(r"^MAT-[0-9]{2,}$"),
    "task": re.compile(r"^TASK-[0-9]{2,}$"),
    "assessment": re.compile(r"^ASM-[0-9]{2,}$"),
    "answer": re.compile(r"^ANS-[0-9]{2,}$"),
    "script": re.compile(r"^SCRIPT-[0-9]{2,}$"),
    "slide": re.compile(r"^SLIDE-[0-9]{2,}$"),
}
ID_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:OBJ|MAT|TASK|ASM|ANS|SCRIPT|SLIDE)-[0-9]{2,}(?![A-Za-z0-9_-])"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LESSON_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PLACEHOLDER_RE = re.compile(
    r"(?:\bTODO\b|\bTBD\b|\bPLACEHOLDER\b|待填写|待补充|待生成|此处填写|此处讲解|后续补充|replace[-_ ]?me|replace-source-id)",
    re.IGNORECASE,
)
INTERACTION_PLACEHOLDER_RE = PLACEHOLDER_RE
ACTUAL_INTERACTION_TEXT_RE = re.compile(r"[A-Za-z0-9\u3400-\u9fff]")
LABEL_NUMBER = r"(?:[一二三四五六七八九十0-9]+)?"
INTERACTION_LABEL_PATTERNS = {
    "问题": re.compile(
        rf"(?m)^[ \t]*(?:(?:核心|课堂|学习|探究)[ \t]*)?问题{LABEL_NUMBER}[ \t]*[：:]"
    ),
    "活动": re.compile(
        rf"(?m)^[ \t]*(?:(?:课堂|学习|学生|小组)[ \t]*)?活动{LABEL_NUMBER}[ \t]*[：:]"
    ),
    "时间": re.compile(
        rf"(?m)^[ \t]*(?:时间|用时|限时){LABEL_NUMBER}[ \t]*[：:]"
    ),
    "成果": re.compile(
        rf"(?m)^[ \t]*(?:成果|产出){LABEL_NUMBER}[ \t]*[：:]"
    ),
    "交流或提交方式": re.compile(
        rf"(?m)^[ \t]*(?:交流|汇报|展示|分享|提交)(?:方式)?{LABEL_NUMBER}[ \t]*[：:]"
    ),
}
BACKEND_TERMS = (
    "文本合同",
    "技术冻结",
    "哈希绑定",
    "占位语检测",
    "权利状态",
    "系统一致性合同",
    "文件哈希",
    "批准记录",
    "校验值",
)
BACKEND_ARTIFACT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:schema[\s_-]*version|sha\s*[-_－]?\s*256|"
    r"manifest(?:\.json)?|approval[\s_-]*record|python[\s_-]*pptx)"
    r"(?![A-Za-z0-9_])|(?<![A-Za-z0-9])json(?![A-Za-z0-9])"
    r"[ \t]*(?:文件|格式|结构)?[ \t]*(?:校验|验证|检查)(?:报告|结果|记录|结论)?",
    re.IGNORECASE,
)
BACKEND_PROCESS_RE = re.compile(
    r"(?:^|[\r\n。；;])[ \t]*(?:"
    r"(?:后台|系统)(?:说明|备注|提示)|"
    r"(?:当前|本轮|本次)?(?:检查|校验|验证)(?:结论|报告)[ \t]*[：:]|"
    r"(?:课件|PPTX?|文件|文档)(?:的)?(?:制作|生成|导出)(?:过程|说明|记录)"
    r")[ \t]*[：:]?|"
    r"(?:制作|生成|导出)(?:过程|说明|记录)[ \t]*[：:]"
    r"[^\r\n。；;]{0,80}(?:脚本|程序|代码|软件|python|PPTX?|JSON|文件|文档|导出|生成|校验|兼容)",
    re.IGNORECASE,
)
SOFTWARE_COMPATIBILITY_RE = re.compile(
    r"(?:software[\s_-]*compatibility|compatibility[\s_-]*(?:notice|warning|report))|"
    r"(?:软件|课件|文件|文档|PPTX?|PowerPoint|WPS|Office|LibreOffice)"
    r"[^\r\n。；;]{0,24}(?:兼容(?:性)?|适配|打开(?:方式)?|版本(?:要求)?|"
    r"字体(?:替换|缺失)|错位|显示异常|播放异常|换行)|"
    r"(?:兼容(?:性)?|适配|打开方式|版本要求)"
    r"[^\r\n。；;]{0,24}(?:PPTX?|PowerPoint|WPS|Office|LibreOffice)",
    re.IGNORECASE,
)
TEACHER_VISIBLE_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:OBJ|TASK|ASM|ANS|SCRIPT|SLIDE|SRC|CLM|MAT)-[0-9]+"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
BACKEND_STATUS_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:status|verification[_-]status|package[_-]status|"
    r"external[_-]ppt[_-]status|draft|review|approved|invalidated|student-blank|prompt|"
    r"answer|summary|neutral|release-candidate|final-package-ready|not-requested|"
    r"design-handoff-ready|returned|content-checked|pass|failed|lesson-brief|"
    r"research-plan|evidence-dossier|stance-selection|route-freeze|teaching-design|"
    r"student-resources|teaching-script|text-contract|ppt-text|external-ppt-check|"
    r"release)(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
DECORATIVE_EMOJI_RE = re.compile(
    r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u20E3]"
)
STUDENT_LEAK_PATTERNS = (
    re.compile(r"参考答案"),
    re.compile(r"评分标准"),
    re.compile(r"评分点"),
    re.compile(r"教师提示"),
    re.compile(r"答案\s*[:：]"),
    re.compile(r"(?<![A-Za-z0-9_-])ANS-[0-9]{2,}(?![A-Za-z0-9_-])"),
)
STUDENT_SAFETY_ALLOWLIST_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\[\s*[xX]?\s*\]\s*)?"
    r"(?:严禁出现教师答案、评分点或答案提示|"
    r"未泄露答案或评分点|"
    r"未泄露参考答案、评分点或教师提示|"
    r"不包含参考答案、评分点或教师提示)[。.\s]*$"
)
ROLE_REQUIRED_PREFIXES = {
    "teaching-design": ("OBJ-", "TASK-", "ASM-"),
    "student-handout": ("OBJ-", "TASK-", "ASM-"),
    "teacher-answer": ("TASK-", "ASM-", "ANS-"),
    "teaching-script": ("TASK-", "SCRIPT-"),
    "ppt-text": ("SLIDE-", "TASK-", "SCRIPT-"),
}


class ContractInputError(RuntimeError):
    """The validator cannot safely read the requested inputs."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _issue(issues: list[dict[str, str]], code: str, path: str, message: str) -> None:
    issues.append({"code": code, "path": path, "message": message})


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ContractInputError(f"{label} does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractInputError(f"{label} is not valid UTF-8 JSON: {path}: {error}") from error
    if not isinstance(data, dict):
        raise ContractInputError(f"{label} root must be a JSON object: {path}")
    return data


def _parse_artifacts(values: Iterable[str], required_roles: set[str]) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    resolved_paths: set[Path] = set()
    for raw in values:
        role, separator, raw_path = raw.partition("=")
        if not separator or role not in required_roles or not raw_path:
            raise ContractInputError(
                "artifact must use a required ROLE=PATH value; required roles: "
                + ", ".join(sorted(required_roles))
            )
        if role in artifacts:
            raise ContractInputError(f"artifact role is repeated: {role}")
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise ContractInputError(f"artifact does not exist: {role}={path}")
        if path in resolved_paths:
            raise ContractInputError(f"different artifact roles cannot use the same file: {path}")
        artifacts[role] = path
        resolved_paths.add(path)
    missing = sorted(required_roles - artifacts.keys())
    extra = sorted(artifacts.keys() - required_roles)
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise ContractInputError("artifact role set is invalid (" + "; ".join(details) + ")")
    return artifacts


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _check_top_level(
    data: dict[str, Any],
    *,
    record_type: str,
    allowed_keys: set[str],
    required_keys: set[str],
    issues: list[dict[str, str]],
) -> None:
    for key in sorted(required_keys - data.keys()):
        _issue(issues, "missing-field", f"$.{key}", "required field is missing")
    for key in sorted(data.keys() - allowed_keys):
        _issue(issues, "unexpected-field", f"$.{key}", "field is not allowed")
    if data.get("schema_version") != "1.0":
        _issue(issues, "schema-version", "$.schema_version", "must equal '1.0'")
    if data.get("record_type") != record_type:
        _issue(issues, "record-type", "$.record_type", f"must equal {record_type!r}")
    lesson_id = data.get("lesson_id")
    if not isinstance(lesson_id, str) or not LESSON_ID_RE.fullmatch(lesson_id):
        _issue(issues, "lesson-id", "$.lesson_id", "must be a portable lesson identifier")
    if data.get("status") not in {"draft", "review", "approved"}:
        _issue(issues, "status", "$.status", "must be draft, review or approved; invalidated content cannot pass")
    if not _valid_datetime(data.get("generated_at")):
        _issue(issues, "generated-at", "$.generated_at", "must be an ISO-8601 date-time")


def _index_records(
    records: Any,
    *,
    collection: str,
    id_key: str,
    id_kind: str,
    required_keys: set[str],
    allowed_keys: set[str],
    issues: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list) or not records:
        _issue(issues, "collection", f"$.{collection}", "must be a non-empty array")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        path = f"$.{collection}[{index}]"
        if not isinstance(record, dict):
            _issue(issues, "record", path, "must be an object")
            continue
        for key in sorted(required_keys - record.keys()):
            _issue(issues, "missing-field", f"{path}.{key}", "required field is missing")
        for key in sorted(record.keys() - allowed_keys):
            _issue(issues, "unexpected-field", f"{path}.{key}", "field is not allowed")
        record_id = record.get(id_key)
        pattern = ID_PATTERNS[id_kind]
        if not isinstance(record_id, str) or not pattern.fullmatch(record_id):
            _issue(issues, "id-format", f"{path}.{id_key}", f"must match {pattern.pattern}")
            continue
        if record_id in indexed:
            _issue(issues, "duplicate-id", f"{path}.{id_key}", f"duplicate identifier: {record_id}")
            continue
        indexed[record_id] = record
    return indexed


def _id_list(
    record: dict[str, Any],
    key: str,
    kind: str,
    path: str,
    issues: list[dict[str, str]],
    *,
    allow_empty: bool = False,
) -> list[str]:
    value = record.get(key)
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a non-empty array"
        _issue(issues, "id-list", f"{path}.{key}", f"must be {qualifier}")
        return []
    result: list[str] = []
    seen: set[str] = set()
    pattern = ID_PATTERNS[kind]
    for index, item in enumerate(value):
        item_path = f"{path}.{key}[{index}]"
        if not isinstance(item, str) or not pattern.fullmatch(item):
            _issue(issues, "id-format", item_path, f"must match {pattern.pattern}")
            continue
        if item in seen:
            _issue(issues, "duplicate-reference", item_path, f"reference is repeated: {item}")
            continue
        result.append(item)
        seen.add(item)
    return result


def _check_placeholders(value: Any, path: str, issues: list[dict[str, str]]) -> None:
    if isinstance(value, str):
        match = PLACEHOLDER_RE.search(value)
        if match:
            _issue(issues, "placeholder", path, f"contains unresolved placeholder: {match.group(0)!r}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_placeholders(item, f"{path}[{index}]", issues)
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_placeholders(item, f"{path}.{key}", issues)


def _check_teacher_facing_text(
    value: str,
    path: str,
    issues: list[dict[str, str]],
) -> None:
    if (
        any(term in value for term in BACKEND_TERMS)
        or BACKEND_ARTIFACT_RE.search(value)
        or BACKEND_PROCESS_RE.search(value)
        or SOFTWARE_COMPATIBILITY_RE.search(value)
    ):
        _issue(
            issues,
            "teacher-facing-backend-term",
            path,
            "teacher-visible text contains backend language",
        )
    if TEACHER_VISIBLE_ID_RE.search(value):
        _issue(
            issues,
            "teacher-facing-internal-id",
            path,
            "teacher-visible text contains an internal identifier",
        )
    if BACKEND_STATUS_RE.search(value):
        _issue(
            issues,
            "teacher-facing-english-status",
            path,
            "teacher-visible text contains an English backend status",
        )
    if DECORATIVE_EMOJI_RE.search(value):
        _issue(
            issues,
            "teacher-facing-emoji",
            path,
            "teacher-visible text contains a decorative emoji",
        )


def interaction_label_has_actual_content(text: str, pattern: re.Pattern[str]) -> bool:
    """Read same-line or following-line content without crossing into another label."""

    for match in pattern.finditer(text):
        for raw_line in text[match.end():].splitlines():
            candidate = raw_line.strip()
            if not candidate:
                continue
            if any(
                other_pattern.match(raw_line)
                for other_pattern in INTERACTION_LABEL_PATTERNS.values()
            ):
                break
            if INTERACTION_PLACEHOLDER_RE.search(candidate):
                break
            if ACTUAL_INTERACTION_TEXT_RE.search(candidate):
                return True
    return False


def text_roles_for_contract(
    contract: dict[str, Any],
    issues: list[dict[str, str]] | None = None,
) -> tuple[str, ...]:
    """Return the exact text roles for a contract, preserving pre-mode history."""

    mode = contract.get("mode", "handout")
    if mode == "handout":
        return TEXT_ROLES
    if mode == "ppt-only":
        return PPT_ONLY_TEXT_ROLES
    if issues is None:
        raise ContractInputError(
            "text contract mode must be 'handout' or 'ppt-only'"
        )
    _issue(
        issues,
        "contract-mode",
        "$.mode",
        "must be 'handout' or 'ppt-only'; omitted legacy contracts use handout",
    )
    return TEXT_ROLES


def _check_artifacts(
    contract: dict[str, Any],
    artifacts: dict[str, Path],
    text_roles: tuple[str, ...],
    declared_ids: set[str],
    required_ids_by_role: dict[str, set[str]],
    issues: list[dict[str, str]],
) -> dict[str, str]:
    bindings = contract.get("artifacts")
    if not isinstance(bindings, dict):
        _issue(issues, "artifacts", "$.artifacts", "must be an object")
        bindings = {}
    expected_roles = set(text_roles)
    missing_bindings = sorted(expected_roles - bindings.keys())
    extra_bindings = sorted(bindings.keys() - expected_roles)
    for role in missing_bindings:
        _issue(issues, "artifact-binding", f"$.artifacts.{role}", "required binding is missing")
    for role in extra_bindings:
        _issue(issues, "artifact-binding", f"$.artifacts.{role}", "unexpected binding")

    missing_artifacts = sorted(expected_roles - artifacts.keys())
    extra_artifacts = sorted(artifacts.keys() - expected_roles)
    for role in missing_artifacts:
        _issue(issues, "artifact-input", f"artifact:{role}", "required artifact input is missing")
    for role in extra_artifacts:
        _issue(issues, "artifact-input", f"artifact:{role}", "unexpected artifact input")

    hashes: dict[str, str] = {}
    bound_union: set[str] = set()
    for role in text_roles:
        if role not in artifacts:
            continue
        path = artifacts[role]
        text = path.read_text(encoding="utf-8")
        actual_hash = sha256_file(path)
        hashes[role] = actual_hash
        binding = bindings.get(role)
        binding_path = f"$.artifacts.{role}"
        if not isinstance(binding, dict):
            continue
        if set(binding.keys()) != {"sha256", "ids"}:
            _issue(issues, "artifact-binding-shape", binding_path, "must contain only sha256 and ids")
        expected_hash = binding.get("sha256")
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            _issue(issues, "artifact-hash-format", f"{binding_path}.sha256", "must be lowercase SHA-256")
        elif expected_hash != actual_hash:
            _issue(issues, "artifact-hash-mismatch", f"{binding_path}.sha256", f"does not match {role} bytes")

        ids = binding.get("ids")
        if not isinstance(ids, list):
            _issue(issues, "artifact-ids", f"{binding_path}.ids", "must be an array")
            expected_ids: set[str] = set()
        else:
            expected_ids = set()
            for index, item in enumerate(ids):
                item_path = f"{binding_path}.ids[{index}]"
                if not isinstance(item, str) or item not in declared_ids:
                    _issue(issues, "unknown-bound-id", item_path, f"identifier is not declared by the contract: {item!r}")
                    continue
                if item in expected_ids:
                    _issue(issues, "duplicate-reference", item_path, f"identifier is repeated: {item}")
                    continue
                expected_ids.add(item)
            bound_union.update(expected_ids)
            missing_required_ids = sorted(
                required_ids_by_role.get(role, set()) - expected_ids
            )
            if missing_required_ids:
                _issue(
                    issues,
                    "artifact-role-coverage",
                    f"{binding_path}.ids",
                    f"{role} omits required IDs: " + ", ".join(missing_required_ids),
                )

        actual_ids = set(ID_TOKEN_RE.findall(text))
        missing_in_file = sorted(expected_ids - actual_ids)
        unbound_in_file = sorted(actual_ids - expected_ids)
        if missing_in_file:
            _issue(issues, "artifact-id-missing", binding_path, "bound IDs absent from file: " + ", ".join(missing_in_file))
        if unbound_in_file:
            _issue(issues, "artifact-id-unbound", binding_path, "file IDs absent from binding: " + ", ".join(unbound_in_file))
        for prefix in ROLE_REQUIRED_PREFIXES[role]:
            if not any(item.startswith(prefix) for item in actual_ids):
                _issue(issues, "artifact-id-family", binding_path, f"{role} must contain at least one {prefix} identifier")
        _check_placeholders(text, f"artifact:{role}", issues)
        if role == "student-handout":
            leak_found = False
            for line_number, line in enumerate(text.splitlines(), start=1):
                if STUDENT_SAFETY_ALLOWLIST_RE.fullmatch(line):
                    continue
                for pattern in STUDENT_LEAK_PATTERNS:
                    match = pattern.search(line)
                    if match:
                        _issue(
                            issues,
                            "student-answer-leak",
                            f"artifact:student-handout:{line_number}",
                            f"contains teacher-only marker: {match.group(0)!r}",
                        )
                        leak_found = True
                        break
                if leak_found:
                    break

    missing_bindings_for_ids = sorted(declared_ids - bound_union)
    if missing_bindings_for_ids:
        _issue(issues, "unbound-contract-id", "$.artifacts", "declared IDs absent from all artifacts: " + ", ".join(missing_bindings_for_ids))
    return hashes


def validate_text_contract(contract_path: Path, artifacts: dict[str, Path]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    contract = _read_json(contract_path, "text contract")
    issues: list[dict[str, str]] = []
    top_keys = {
        "schema_version", "record_type", "lesson_id", "status", "generated_at", "mode", "artifacts",
        "objectives", "materials", "tasks", "assessments", "answers", "scripts",
    }
    _check_top_level(
        contract,
        record_type="text-contract",
        allowed_keys=top_keys,
        required_keys=top_keys - {"mode"},
        issues=issues,
    )
    text_roles = text_roles_for_contract(contract, issues)
    content_mode = contract.get("mode", "handout")
    _check_placeholders(contract, "$", issues)

    objectives = _index_records(
        contract.get("objectives"), collection="objectives", id_key="objective_id", id_kind="objective",
        required_keys={"objective_id"}, allowed_keys={"objective_id"}, issues=issues,
    )
    materials = _index_records(
        contract.get("materials"), collection="materials", id_key="material_id", id_kind="material",
        required_keys={"material_id", "source_ids", "rights_status"},
        allowed_keys={"material_id", "source_ids", "rights_status"}, issues=issues,
    )
    tasks = _index_records(
        contract.get("tasks"), collection="tasks", id_key="task_id", id_kind="task",
        required_keys={"task_id", "objective_ids", "material_ids", "assessment_ids", "ppt_required"},
        allowed_keys={"task_id", "objective_ids", "material_ids", "assessment_ids", "ppt_required"}, issues=issues,
    )
    assessments = _index_records(
        contract.get("assessments"), collection="assessments", id_key="assessment_id", id_kind="assessment",
        required_keys={"assessment_id", "task_id", "objective_ids", "answer_id"},
        allowed_keys={"assessment_id", "task_id", "objective_ids", "answer_id"}, issues=issues,
    )
    answers = _index_records(
        contract.get("answers"), collection="answers", id_key="answer_id", id_kind="answer",
        required_keys={"answer_id", "assessment_id"}, allowed_keys={"answer_id", "assessment_id"}, issues=issues,
    )
    scripts = _index_records(
        contract.get("scripts"), collection="scripts", id_key="script_id", id_kind="script",
        required_keys={"script_id", "task_id"}, allowed_keys={"script_id", "task_id"}, issues=issues,
    )

    for material_id, material in materials.items():
        source_ids = material.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids or any(not isinstance(item, str) or not item.strip() for item in source_ids):
            _issue(issues, "material-sources", f"$.materials[{material_id}].source_ids", "must contain non-empty source identifiers")
        elif len(source_ids) != len(set(source_ids)):
            _issue(issues, "duplicate-reference", f"$.materials[{material_id}].source_ids", "source identifiers must be unique")
        if material.get("rights_status") not in {"user-provided", "licensed", "public-domain", "link-only", "unknown"}:
            _issue(issues, "rights-status", f"$.materials[{material_id}].rights_status", "unsupported rights status")

    task_refs: dict[str, dict[str, list[str]]] = {}
    for task_id, task in tasks.items():
        base = f"$.tasks[{task_id}]"
        objective_refs = _id_list(task, "objective_ids", "objective", base, issues)
        material_refs = _id_list(task, "material_ids", "material", base, issues, allow_empty=True)
        assessment_refs = _id_list(task, "assessment_ids", "assessment", base, issues)
        if not isinstance(task.get("ppt_required"), bool):
            _issue(issues, "ppt-required", f"{base}.ppt_required", "must be boolean")
        elif content_mode == "ppt-only" and task["ppt_required"] is not True:
            _issue(
                issues,
                "ppt-only-task-not-required",
                f"{base}.ppt_required",
                "every classroom task must be included in the PPT when no handout is used",
            )
        task_refs[task_id] = {"objectives": objective_refs, "materials": material_refs, "assessments": assessment_refs}
        for item in objective_refs:
            if item not in objectives:
                _issue(issues, "broken-reference", f"{base}.objective_ids", f"unknown objective: {item}")
        for item in material_refs:
            if item not in materials:
                _issue(issues, "broken-reference", f"{base}.material_ids", f"unknown material: {item}")
        for item in assessment_refs:
            if item not in assessments:
                _issue(issues, "broken-reference", f"{base}.assessment_ids", f"unknown assessment: {item}")

    assessment_refs_by_objective: dict[str, set[str]] = {item: set() for item in objectives}
    for assessment_id, assessment in assessments.items():
        base = f"$.assessments[{assessment_id}]"
        task_id = assessment.get("task_id")
        objective_refs = _id_list(assessment, "objective_ids", "objective", base, issues)
        answer_id = assessment.get("answer_id")
        if task_id not in tasks:
            _issue(issues, "broken-reference", f"{base}.task_id", f"unknown task: {task_id!r}")
        else:
            if assessment_id not in task_refs[task_id]["assessments"]:
                _issue(issues, "reverse-reference", base, f"task {task_id} does not list {assessment_id}")
            extra_objectives = sorted(set(objective_refs) - set(task_refs[task_id]["objectives"]))
            if extra_objectives:
                _issue(issues, "objective-scope", f"{base}.objective_ids", "assessment exceeds task objectives: " + ", ".join(extra_objectives))
        for item in objective_refs:
            if item not in objectives:
                _issue(issues, "broken-reference", f"{base}.objective_ids", f"unknown objective: {item}")
            else:
                assessment_refs_by_objective[item].add(assessment_id)
        if answer_id not in answers:
            _issue(issues, "broken-reference", f"{base}.answer_id", f"unknown answer: {answer_id!r}")
        elif answers[answer_id].get("assessment_id") != assessment_id:
            _issue(issues, "reverse-reference", f"{base}.answer_id", f"answer {answer_id} points to another assessment")

    for answer_id, answer in answers.items():
        assessment_id = answer.get("assessment_id")
        if assessment_id not in assessments:
            _issue(issues, "broken-reference", f"$.answers[{answer_id}].assessment_id", f"unknown assessment: {assessment_id!r}")
        elif assessments[assessment_id].get("answer_id") != answer_id:
            _issue(issues, "reverse-reference", f"$.answers[{answer_id}]", f"assessment {assessment_id} points to another answer")

    scripts_by_task: dict[str, set[str]] = {item: set() for item in tasks}
    for script_id, script in scripts.items():
        task_id = script.get("task_id")
        if task_id not in tasks:
            _issue(issues, "broken-reference", f"$.scripts[{script_id}].task_id", f"unknown task: {task_id!r}")
        else:
            scripts_by_task[task_id].add(script_id)

    for objective_id in objectives:
        task_coverage = [task_id for task_id, refs in task_refs.items() if objective_id in refs["objectives"]]
        if not task_coverage:
            _issue(issues, "objective-without-task", f"$.objectives[{objective_id}]", "objective has no task")
        if not assessment_refs_by_objective[objective_id]:
            _issue(issues, "objective-without-assessment", f"$.objectives[{objective_id}]", "objective has no assessment evidence")
    for task_id, linked_scripts in scripts_by_task.items():
        if not linked_scripts:
            _issue(issues, "task-without-script", f"$.tasks[{task_id}]", "task has no teaching-script block")

    declared_ids = set(objectives) | set(materials) | set(tasks) | set(assessments) | set(answers) | set(scripts)
    required_ids_by_role = {
        "teaching-design": set(objectives) | set(tasks) | set(assessments),
        "student-handout": set(objectives) | set(materials) | set(tasks) | set(assessments),
        "teacher-answer": set(tasks) | set(assessments) | set(answers),
        "teaching-script": set(objectives) | set(tasks) | set(scripts),
    }
    if content_mode == "ppt-only":
        required_ids_by_role["teaching-design"] |= set(materials)
        required_ids_by_role["teaching-script"] |= set(assessments) | set(answers)
    artifact_hashes = _check_artifacts(
        contract, artifacts, text_roles, declared_ids, required_ids_by_role, issues
    )
    issues.sort(key=lambda item: (item["path"], item["code"], item["message"]))
    context = {
        "contract": contract,
        "content_mode": content_mode,
        "text_roles": text_roles,
        "text_contract_sha256": sha256_file(contract_path),
        "objectives": objectives,
        "materials": materials,
        "tasks": tasks,
        "task_refs": task_refs,
        "assessments": assessments,
        "answers": answers,
        "scripts": scripts,
        "scripts_by_task": scripts_by_task,
        "artifact_hashes": artifact_hashes,
    }
    return issues, context


def render_ppt_markdown(ppt: dict[str, Any]) -> str:
    """Render the human-readable PPT draft from the structured source."""

    slides = ppt.get("slides")
    if not isinstance(slides, list) or not slides or any(not isinstance(item, dict) for item in slides):
        raise ContractInputError("structured PPT slides must be a non-empty array of objects")
    for index, slide in enumerate(slides):
        for key in ("material_direction", "information_hierarchy", "immutable_content"):
            if key in slide and not isinstance(slide[key], str):
                raise ContractInputError(
                    f"structured PPT slides[{index}].{key} must be a string"
                )
    ordered = sorted(slides, key=lambda item: (item.get("page", 0), str(item.get("slide_id", ""))))
    lines = [
        "# PPT 逐页完整文字粗稿",
        "",
        f"> lesson_id：{ppt.get('lesson_id', '')}  ",
        f"> status：{ppt.get('status', '')}  ",
        f"> 文本合同 SHA-256：{ppt.get('text_contract_sha256', '')}  ",
        "> 本文件由结构化 PPT 文字稿确定性投影，不是视觉设计稿。",
        "",
    ]
    for slide in ordered:
        objective_ids = "、".join(slide.get("objective_ids", []))
        script_ids = "、".join(slide.get("script_ids", []))
        answer_ids = "、".join(slide.get("answer_ids", [])) or "无"
        lines.extend(
            [
                "---",
                "",
                f"## {slide.get('slide_id', '')} · {slide.get('title', '')}",
                "",
                f"- 页序：{slide.get('page', '')}",
                f"- reveal_state：{slide.get('reveal_state', '')}",
                f"- objective_id：{objective_ids}",
                f"- task_id：{slide.get('task_id', '')}",
                f"- script_id：{script_ids}",
                f"- answer_id：{answer_ids}",
                "",
                "### 屏显文字（完整）",
                "",
                str(slide.get("screen_text", "")),
                "",
                "### 教师备注",
                "",
                str(slide.get("teacher_notes", "")),
                "",
            ]
        )
        for key, label in (
            ("material_direction", "素材方向建议"),
            ("information_hierarchy", "信息层级建议"),
            ("immutable_content", "不得由设计师改变的内容"),
        ):
            value = slide.get(key)
            if isinstance(value, str) and value.strip():
                lines.extend([f"### {label}", "", value, ""])
    return "\n".join(lines).rstrip() + "\n"


def validate_ppt_text(
    contract_path: Path,
    ppt_json_path: Path,
    artifacts: dict[str, Path],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    text_artifacts = {
        role: path for role, path in artifacts.items() if role in TEXT_ROLES
    }
    issues, context = validate_text_contract(contract_path, text_artifacts)
    ppt = _read_json(ppt_json_path, "structured PPT text")
    ppt_keys = {
        "schema_version", "record_type", "lesson_id", "status", "generated_at",
        "text_contract_sha256", "ppt_text_sha256", "slides",
    }
    _check_top_level(
        ppt,
        record_type="ppt-text",
        allowed_keys=ppt_keys,
        required_keys=ppt_keys,
        issues=issues,
    )
    _check_placeholders(ppt, "$ppt", issues)
    contract_hash = sha256_file(contract_path)
    if ppt.get("text_contract_sha256") != contract_hash:
        _issue(issues, "text-contract-hash-mismatch", "$ppt.text_contract_sha256", "does not match text contract bytes")
    ppt_markdown_hash = sha256_file(artifacts[PPT_ROLE])
    if ppt.get("ppt_text_sha256") != ppt_markdown_hash:
        _issue(issues, "ppt-text-hash-mismatch", "$ppt.ppt_text_sha256", "does not match PPT Markdown bytes")
    if ppt.get("lesson_id") != context["contract"].get("lesson_id"):
        _issue(issues, "lesson-id-mismatch", "$ppt.lesson_id", "must match the text contract lesson_id")

    slides = _index_records(
        ppt.get("slides"), collection="slides", id_key="slide_id", id_kind="slide",
        required_keys={
            "slide_id", "page", "title", "screen_text", "teacher_notes", "task_id",
            "objective_ids", "script_ids", "answer_ids", "reveal_state",
        },
        allowed_keys={
            "slide_id", "page", "title", "screen_text", "teacher_notes", "task_id",
            "objective_ids", "script_ids", "answer_ids", "reveal_state", "material_direction",
            "information_hierarchy", "immutable_content",
        },
        issues=issues,
    )
    pages: dict[int, str] = {}
    slides_by_task: dict[str, set[str]] = {item: set() for item in context["tasks"]}
    screen_text_by_task: dict[str, list[str]] = {
        item: [] for item in context["tasks"]
    }
    for slide_id, slide in slides.items():
        base = f"$ppt.slides[{slide_id}]"
        page = slide.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            _issue(issues, "page", f"{base}.page", "must be a positive integer")
        elif page in pages:
            _issue(issues, "duplicate-page", f"{base}.page", f"page {page} is already used by {pages[page]}")
        else:
            pages[page] = slide_id
        for key in ("title", "screen_text", "teacher_notes"):
            if not isinstance(slide.get(key), str) or not slide[key].strip():
                _issue(issues, "empty-slide-field", f"{base}.{key}", "must contain complete text")
            else:
                _check_teacher_facing_text(slide[key], f"{base}.{key}", issues)
        for key in ("material_direction", "information_hierarchy", "immutable_content"):
            if key in slide and not isinstance(slide[key], str):
                _issue(
                    issues,
                    "invalid-optional-slide-field",
                    f"{base}.{key}",
                    "must be a string when present",
                )
        task_id = slide.get("task_id")
        objective_refs = _id_list(slide, "objective_ids", "objective", base, issues)
        script_refs = _id_list(slide, "script_ids", "script", base, issues)
        answer_refs = _id_list(slide, "answer_ids", "answer", base, issues, allow_empty=True)
        if task_id not in context["tasks"]:
            _issue(issues, "broken-reference", f"{base}.task_id", f"unknown task: {task_id!r}")
        else:
            slides_by_task[task_id].add(slide_id)
            if isinstance(slide.get("screen_text"), str):
                screen_text_by_task[task_id].append(slide["screen_text"])
            allowed_objectives = set(context["task_refs"][task_id]["objectives"])
            extra_objectives = sorted(set(objective_refs) - allowed_objectives)
            if extra_objectives:
                _issue(issues, "objective-scope", f"{base}.objective_ids", "slide exceeds task objectives: " + ", ".join(extra_objectives))
        for objective_id in objective_refs:
            if objective_id not in context["objectives"]:
                _issue(issues, "broken-reference", f"{base}.objective_ids", f"unknown objective: {objective_id}")
        for script_id in script_refs:
            if script_id not in context["scripts"]:
                _issue(issues, "broken-reference", f"{base}.script_ids", f"unknown script: {script_id}")
            elif task_id in context["tasks"] and context["scripts"][script_id].get("task_id") != task_id:
                _issue(issues, "script-task-mismatch", f"{base}.script_ids", f"script {script_id} belongs to another task")
        for answer_id in answer_refs:
            if answer_id not in context["answers"]:
                _issue(issues, "broken-reference", f"{base}.answer_ids", f"unknown answer: {answer_id}")
                continue
            assessment_id = context["answers"][answer_id].get("assessment_id")
            assessment = context["assessments"].get(assessment_id)
            if (
                task_id in context["tasks"]
                and isinstance(assessment, dict)
                and assessment.get("task_id") != task_id
            ):
                _issue(
                    issues,
                    "answer-task-mismatch",
                    f"{base}.answer_ids",
                    f"answer {answer_id} belongs to another task",
                )
        reveal_state = slide.get("reveal_state")
        if reveal_state not in {"student-blank", "prompt", "answer", "summary", "neutral"}:
            _issue(issues, "reveal-state", f"{base}.reveal_state", "unsupported reveal state")
        if answer_refs and reveal_state not in {"answer", "summary"}:
            _issue(issues, "answer-reveal", f"{base}.answer_ids", "answer IDs are allowed only on answer or summary slides")

    if pages and sorted(pages) != list(range(1, len(pages) + 1)):
        _issue(issues, "page-sequence", "$ppt.slides", "pages must be contiguous and start at 1")
    for task_id in context["tasks"]:
        if not slides_by_task[task_id]:
            _issue(
                issues,
                "task-without-slide",
                f"$.tasks[{task_id}]",
                "every classroom task must appear in student-visible PPT pages",
            )
            continue
        visible_text = "\n".join(screen_text_by_task[task_id])
        incomplete_labels = [
            label
            for label, pattern in INTERACTION_LABEL_PATTERNS.items()
            if not interaction_label_has_actual_content(visible_text, pattern)
        ]
        if incomplete_labels:
            _issue(
                issues,
                "task-screen-content",
                f"$ppt.task-groups[{task_id}].screen_text",
                "student-visible pages are missing actual content after labels: "
                + ", ".join(incomplete_labels),
            )

    ppt_text = artifacts[PPT_ROLE].read_text(encoding="utf-8")
    try:
        rendered_ppt_text = render_ppt_markdown(ppt)
    except ContractInputError:
        rendered_ppt_text = None
    if rendered_ppt_text is not None and ppt_text.replace("\r\n", "\n") != rendered_ppt_text:
        _issue(
            issues,
            "ppt-markdown-drift",
            "artifact:ppt-text",
            "Markdown is not the deterministic projection of the structured PPT text",
        )
    ppt_ids = set(ID_TOKEN_RE.findall(ppt_text))
    expected_ppt_ids = set(slides)
    for slide in slides.values():
        expected_ppt_ids.add(slide.get("task_id"))
        expected_ppt_ids.update(item for item in slide.get("objective_ids", []) if isinstance(item, str))
        expected_ppt_ids.update(item for item in slide.get("script_ids", []) if isinstance(item, str))
        expected_ppt_ids.update(item for item in slide.get("answer_ids", []) if isinstance(item, str))
    expected_ppt_ids.discard(None)
    missing_ids = sorted(expected_ppt_ids - ppt_ids)
    extra_ids = sorted(ppt_ids - expected_ppt_ids)
    if missing_ids:
        _issue(issues, "ppt-id-missing", "artifact:ppt-text", "structured IDs absent from Markdown: " + ", ".join(missing_ids))
    if extra_ids:
        _issue(issues, "ppt-id-unbound", "artifact:ppt-text", "Markdown IDs absent from structured PPT: " + ", ".join(extra_ids))
    for prefix in ROLE_REQUIRED_PREFIXES[PPT_ROLE]:
        if not any(item.startswith(prefix) for item in ppt_ids):
            _issue(issues, "artifact-id-family", "artifact:ppt-text", f"PPT Markdown must contain at least one {prefix} identifier")
    _check_placeholders(ppt_text, "artifact:ppt-text", issues)
    issues.sort(key=lambda item: (item["path"], item["code"], item["message"]))
    context["ppt"] = ppt
    context["slides"] = slides
    context["ppt_structured_sha256"] = sha256_file(ppt_json_path)
    context["ppt_text_sha256"] = ppt_markdown_hash
    context["text_contract_sha256"] = contract_hash
    return issues, context


def _report(command: str, issues: list[dict[str, str]], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "record_type": "contract-validation-report",
        "ok": not issues,
        "validator": "yuwen-courseware-text-contract-v1",
        "mode": command,
        "lesson_id": context.get("contract", {}).get("lesson_id"),
        "counts": {
            "objectives": len(context.get("objectives", {})),
            "materials": len(context.get("materials", {})),
            "tasks": len(context.get("tasks", {})),
            "assessments": len(context.get("assessments", {})),
            "answers": len(context.get("answers", {})),
            "scripts": len(context.get("scripts", {})),
            "slides": len(context.get("slides", {})),
        },
        "artifact_hashes": context.get("artifact_hashes", {}),
        "text_contract_sha256": context.get("text_contract_sha256"),
        "ppt_structured_sha256": context.get("ppt_structured_sha256"),
        "ppt_text_sha256": context.get("ppt_text_sha256"),
        "issues": issues,
    }


def _write_new_file(path: Path, content: bytes, label: str) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.chmod(0o644)
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise ContractInputError(
                f"refusing to overwrite existing {label}: {destination}"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _write_report(path: Path, report: dict[str, Any]) -> None:
    content = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_new_file(path, content, "report")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("text", "ppt"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--contract", type=Path, required=True)
        sub.add_argument("--artifact", action="append", required=True, help="ROLE=PATH; repeatable")
        sub.add_argument("--report", type=Path)
        if command == "ppt":
            sub.add_argument("--ppt-json", type=Path, required=True)
    render = subparsers.add_parser(
        "render-ppt", help="create the human-readable Markdown projection from structured PPT JSON"
    )
    render.add_argument("--ppt-json", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "render-ppt":
            ppt = _read_json(args.ppt_json.expanduser().resolve(), "structured PPT text")
            content = render_ppt_markdown(ppt).encode("utf-8")
            output = _write_new_file(args.output, content, "PPT Markdown")
            print(
                json.dumps(
                    {"output": str(output), "sha256": sha256_file(output), "size": len(content)},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        contract = _read_json(args.contract.expanduser().resolve(), "text contract")
        required_roles = set(text_roles_for_contract(contract))
        if args.command == "ppt":
            required_roles.add(PPT_ROLE)
        artifacts = _parse_artifacts(args.artifact, required_roles)
        if args.command == "text":
            issues, context = validate_text_contract(args.contract.expanduser().resolve(), artifacts)
        else:
            issues, context = validate_ppt_text(
                args.contract.expanduser().resolve(),
                args.ppt_json.expanduser().resolve(),
                artifacts,
            )
        report = _report(args.command, issues, context)
        if args.report:
            _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["ok"] else 2
    except (ContractInputError, OSError, UnicodeError) as error:
        print(f"contract validation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
