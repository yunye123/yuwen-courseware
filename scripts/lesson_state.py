#!/usr/bin/env python3
"""Minimal, portable lesson-state and approval ledger.

This module intentionally uses only the Python standard library.  It stores all
lesson data below an explicitly configured data home and treats every approval
record as an immutable, content-addressed snapshot.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import wraps
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import uuid4


SCHEMA_VERSION = "1.0"
DATA_HOME_ENV = "YUWEN_DATA_HOME"
INIT_SUBDIRECTORIES = ("approvals", "reviews", "adoptions", "invalidations")
STAGES = (
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
)
STAGE_INDEX = {stage: index for index, stage in enumerate(STAGES)}
STATUSES = ("draft", "review", "approved", "invalidated")
ADOPTABLE_STAGES = STAGES[:4]
LESSON_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REVIEW_ID_RE = re.compile(r"^review-[a-f0-9]{32}$")
STAGE_REQUIRED_ROLES = {
    "lesson-brief": {"lesson-brief"},
    "research-plan": {"research-plan"},
    "evidence-dossier": {"evidence-dossier"},
    "stance-selection": {"stance-selection"},
    "route-freeze": {"route-freeze"},
    "teaching-design": {"teaching-design"},
    "student-resources": {"student-handout", "teacher-answer"},
    "teaching-script": {"teaching-script"},
    "text-contract": {"text-contract", "text-contract-report"},
    "ppt-text": {"ppt-text", "ppt-structured", "ppt-contract-report"},
    "external-ppt-check": {"external-ppt-check"},
    "release": {"manifest", "package-checklist"},
}
LEGACY_STAGE_REQUIRED_ROLES = {
    **STAGE_REQUIRED_ROLES,
    "text-contract": {"text-contract"},
    "ppt-text": {"ppt-text"},
}
CANONICAL_ROLE_STAGE = {
    role: stage for stage, roles in STAGE_REQUIRED_ROLES.items() for role in roles
}
DUAL_REVIEW_STAGES = {"teaching-design", "text-contract", "release"}
INDEPENDENT_CONFIRMATION_STAGES = DUAL_REVIEW_STAGES
QUOTE_GATE_POLICY_CUTOFF = "2026-07-19T05:49:57Z"
HISTORICAL_COMPATIBILITY_STATUS = "historical-compatible-retrospective-evidence"
HISTORICAL_COMPATIBILITY_STATEMENT = (
    "追溯核对，生成于 alpha.10 逐字校对门之后，不冒充审批当时存在"
)
QUALITY_REVIEW_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "review_id",
        "lesson_id",
        "stage",
        "reviewer_type",
        "reviewer_id",
        "route_id",
        "provider",
        "model",
        "runtime_mode",
        "run_id",
        "persona_version",
        "prompt_version",
        "verdict",
        "comment",
        "reviewed_at",
        "inputs",
        "report",
        "quote_check_report",
    }
)
TEXT_CONTRACT_ARTIFACT_ROLES = (
    "teaching-design",
    "student-handout",
    "teacher-answer",
    "teaching-script",
)
PPT_ONLY_TEXT_CONTRACT_ARTIFACT_ROLES = (
    "teaching-design",
    "teaching-script",
)
CONTRACT_VALIDATOR_ID = "yuwen-courseware-text-contract-v1"
CONTRACT_SCHEMA_FILES = {
    "text-contract": "text-contract.schema.json",
    "contract-report": "contract-validation-report.schema.json",
    "ppt-structured": "ppt-text.schema.json",
}
SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "$id",
    "$ref",
    "$defs",
    "title",
    "description",
    "type",
    "const",
    "enum",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "oneOf",
    "allOf",
    "if",
    "then",
    "else",
}
_CONTRACT_VALIDATOR_MODULE: Any | None = None


class UserError(Exception):
    """An actionable command-line or state error."""


@contextmanager
def lesson_mutation_lock(lesson_dir: Path):
    """Hold a crash-releasing, cross-process lock for one lesson state mutation."""

    lock_path = lesson_dir / ".mutation.lock"
    try:
        handle = lock_path.open("a+b")
    except OSError as error:
        raise UserError(f"cannot open lesson mutation lock: {error}") from error
    try:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as error:
            raise UserError(
                "another lesson state mutation is in progress; reload status and retry"
            ) from error
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def mutation_locked(handler):
    """Serialize commands that may append a ledger event and replace state.json."""

    @wraps(handler)
    def wrapped(args: argparse.Namespace) -> int:
        data_home = resolve_data_home(args.data_home)
        lesson_id = validate_lesson_id(args.lesson_id)
        lesson_dir = lesson_directory(data_home, lesson_id)
        with lesson_mutation_lock(lesson_dir):
            return handler(args)

    return wrapped


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_directory(path: Path) -> None:
    """Best-effort directory fsync after a rename or exclusive create."""

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write_json(path: Path, value: Any) -> None:
    """Replace a JSON file atomically using a temporary file beside it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        sync_directory(path.parent)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def exclusive_write_json(path: Path, value: Any, *, read_only: bool = False) -> bytes:
    """Create a JSON file exactly once; an existing path is never overwritten."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json_bytes(value)
    mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError as error:
        raise UserError(f"immutable file already exists: {path}") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if read_only:
            path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        sync_directory(path.parent)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return payload


def emit_json(value: Any, *, stream: Any = sys.stdout) -> None:
    json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write("\n")


def resolve_data_home(raw_value: str | None) -> Path:
    value = raw_value or os.environ.get(DATA_HOME_ENV)
    if not value:
        raise UserError(
            f"data home is required; pass --data-home PATH or set {DATA_HOME_ENV}"
        )
    return Path(value).expanduser().resolve(strict=False)


def validate_lesson_id(lesson_id: str) -> str:
    if not LESSON_ID_RE.fullmatch(lesson_id):
        raise UserError(
            "lesson id must start with an ASCII letter or digit and contain only "
            "letters, digits, '.', '_' or '-' (maximum 128 characters)"
        )
    return lesson_id


def lesson_directory(data_home: Path, lesson_id: str) -> Path:
    return data_home / "lessons" / validate_lesson_id(lesson_id)


def state_path(data_home: Path, lesson_id: str) -> Path:
    return lesson_directory(data_home, lesson_id) / "state.json"


def load_state(data_home: Path, lesson_id: str) -> dict[str, Any]:
    path = state_path(data_home, lesson_id)
    if not path.is_file():
        raise UserError(f"lesson state does not exist: {path}; run init first")
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise UserError(f"cannot read lesson state {path}: {error}") from error
    if not isinstance(value, dict):
        raise UserError(f"lesson state is not a JSON object: {path}")
    if value.get("lesson_id") != lesson_id:
        raise UserError(f"lesson id mismatch in state: expected {lesson_id!r}")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise UserError(
            f"unsupported lesson-state schema: {value.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION!r}"
        )
    current_stage = value.get("current_stage")
    if current_stage not in STAGE_INDEX:
        raise UserError(f"unknown current stage in state: {current_stage!r}")
    initial_stage = value.get("initial_stage")
    if initial_stage not in STAGE_INDEX:
        raise UserError(f"unknown initial stage in state: {initial_stage!r}")
    revision = value.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise UserError(f"invalid revision in state: {revision!r}")
    if not isinstance(value.get("approvals"), list):
        raise UserError("invalid approvals list in lesson state")
    if "invalidations" in value and not isinstance(value.get("invalidations"), list):
        raise UserError("invalid invalidations list in lesson state")
    if "active_approval_ids" in value and not isinstance(
        value.get("active_approval_ids"), list
    ):
        raise UserError("invalid active approval id list in lesson state")
    if not isinstance(value.get("artifacts"), list):
        raise UserError("invalid artifact registry in lesson state")
    if value.get("status") not in STATUSES:
        raise UserError(
            f"invalid lesson status: {value.get('status')!r}; allowed: {', '.join(STATUSES)}"
        )
    return value


def find_writable_ancestor(path: Path) -> tuple[Path, bool]:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    usable = candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)
    return candidate, usable


def command_doctor(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    if data_home.exists():
        usable = data_home.is_dir() and os.access(data_home, os.W_OK | os.X_OK)
        checked_path = data_home
        reason = "existing data home is writable" if usable else "existing path is not a writable directory"
    else:
        checked_path, usable = find_writable_ancestor(data_home)
        reason = (
            "data home can be created below a writable ancestor"
            if usable
            else "no writable ancestor is available"
        )
    emit_json(
        {
            "data_home": str(data_home),
            "checked_path": str(checked_path),
            "ok": usable,
            "reason": reason,
            "schema_version": SCHEMA_VERSION,
            "stages": [{"id": stage, "index": index} for index, stage in enumerate(STAGES)],
        }
    )
    return 0 if usable else 1


def is_empty_legacy_init_residue(directory: Path) -> bool:
    """Recognize only the exact empty directory shape left by alpha.9 init."""

    if directory.is_symlink() or not directory.is_dir():
        return False
    allowed = set(INIT_SUBDIRECTORIES)
    try:
        entries = list(directory.iterdir())
    except OSError:
        return False
    for entry in entries:
        if entry.name not in allowed or entry.is_symlink() or not entry.is_dir():
            return False
        try:
            next(entry.iterdir())
        except StopIteration:
            continue
        except OSError:
            return False
        return False
    return True


def command_init(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    lessons_root = data_home / "lessons"
    lessons_root.mkdir(parents=True, exist_ok=True)
    directory = lesson_directory(data_home, lesson_id)
    directory_exists = directory.exists() or directory.is_symlink()
    if directory_exists and not is_empty_legacy_init_residue(directory):
        raise UserError(
            f"new lesson directory already exists: {directory}; use adopt or repair-adoption"
        )
    now = utc_now()
    state = {
        "schema_version": SCHEMA_VERSION,
        "lesson_id": lesson_id,
        "revision": 0,
        "initial_stage": "lesson-brief",
        "current_stage": "lesson-brief",
        "current_stage_index": 0,
        "status": "draft",
        "origin": "new",
        "adoption": None,
        "artifacts": [],
        "approvals": [],
        "invalidations": [],
        "active_approval_ids": [],
        "contract_gate_enforced_after_revision": 0,
        "created_at": now,
        "updated_at": now,
    }
    if directory_exists:
        for child in INIT_SUBDIRECTORIES:
            (directory / child).mkdir(exist_ok=True)
        if not is_empty_legacy_init_residue(directory):
            raise UserError(
                f"legacy init residue changed while recovering: {directory}; "
                "preserve it and inspect the unexpected content"
            )
        exclusive_write_json(directory / "state.json", state)
        sync_directory(directory)
    else:
        staging = Path(
            tempfile.mkdtemp(prefix=f".{lesson_id}.init-", dir=lessons_root)
        )
        try:
            for child in INIT_SUBDIRECTORIES:
                (staging / child).mkdir()
            exclusive_write_json(staging / "state.json", state)
            sync_directory(staging)
            try:
                os.replace(staging, directory)
            except OSError as error:
                if directory.exists() or directory.is_symlink():
                    raise UserError(
                        f"new lesson directory already exists: {directory}; "
                        "reload status and retry"
                    ) from error
                raise UserError(f"cannot publish initialized lesson directory: {error}") from error
            sync_directory(lessons_root)
        finally:
            if staging.exists() or staging.is_symlink():
                shutil.rmtree(staging, ignore_errors=True)
    emit_json(state)
    return 0


def adoption_record_payload(
    *,
    lesson_id: str,
    initial_stage: str,
    status: str,
    user_id: str,
    reason: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "legacy-adoption",
        "lesson_id": lesson_id,
        "initial_stage": initial_stage,
        "status": status,
        "user_id": user_id,
        "reason": reason,
        "adopted_at": utc_now(),
        "artifacts": [
            {key: item[key] for key in ("role", "path", "sha256", "size")}
            for item in artifacts
        ],
    }


def write_or_reuse_adoption_snapshot(
    lesson_dir: Path, record: dict[str, Any]
) -> dict[str, Any]:
    path = lesson_dir / "adoptions" / "adoption-v1.json"
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        payload = path.read_bytes()
        try:
            existing = json.loads(payload)
        except json.JSONDecodeError as error:
            raise UserError(f"existing adoption snapshot is invalid: {error}") from error
        comparable_keys = (
            "schema_version",
            "record_type",
            "lesson_id",
            "initial_stage",
            "status",
            "user_id",
            "reason",
            "artifacts",
        )
        if any(existing.get(key) != record.get(key) for key in comparable_keys):
            raise UserError("existing adoption snapshot does not match the explicit repair request")
    else:
        payload = exclusive_write_json(path, record, read_only=True)
    return {
        "file": "adoptions/adoption-v1.json",
        "snapshot_sha256": sha256_bytes(payload),
    }


def command_adopt(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    lesson_dir = lesson_directory(data_home, lesson_id)
    if not lesson_dir.is_dir():
        raise UserError(f"adopt requires an existing lesson directory: {lesson_dir}")
    if (lesson_dir / "state.json").exists():
        raise UserError("lesson state already exists; use repair-adoption for a legacy state")
    if args.current_stage not in ADOPTABLE_STAGES:
        raise UserError(
            "adoption is limited to pre-freeze stages: " + ", ".join(ADOPTABLE_STAGES)
        )
    user_id = args.user_id.strip()
    reason = args.reason.strip()
    if not user_id or not reason:
        raise UserError("adoption requires non-empty --user-id and --reason")
    artifacts = parse_role_inputs(lesson_dir, args.artifact)
    if not artifacts:
        raise UserError("adoption requires at least one role-bound artifact")
    now = utc_now()
    registered = [{**item, "registered_at": now} for item in artifacts]
    record = adoption_record_payload(
        lesson_id=lesson_id,
        initial_stage=args.current_stage,
        status=args.status,
        user_id=user_id,
        reason=reason,
        artifacts=registered,
    )
    adoption = write_or_reuse_adoption_snapshot(lesson_dir, record)
    (lesson_dir / "approvals").mkdir(exist_ok=True)
    (lesson_dir / "reviews").mkdir(exist_ok=True)
    (lesson_dir / "invalidations").mkdir(exist_ok=True)
    state = {
        "schema_version": SCHEMA_VERSION,
        "lesson_id": lesson_id,
        "revision": 0,
        "initial_stage": args.current_stage,
        "current_stage": args.current_stage,
        "current_stage_index": STAGE_INDEX[args.current_stage],
        "status": args.status,
        "origin": "adopted",
        "adoption": adoption,
        "artifacts": registered,
        "approvals": [],
        "invalidations": [],
        "active_approval_ids": [],
        "contract_gate_enforced_after_revision": 0,
        "created_at": now,
        "updated_at": now,
    }
    exclusive_write_json(lesson_dir / "state.json", state)
    emit_json(state)
    return 0


@mutation_locked
def command_repair_adoption(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    state = load_state(data_home, lesson_id)
    lesson_dir = lesson_directory(data_home, lesson_id)
    if state.get("origin") != "adopted" or state["revision"] != 0 or state["approvals"]:
        raise UserError("repair-adoption only accepts an unapproved revision-0 adopted state")
    if args.expected_stage not in ADOPTABLE_STAGES:
        raise UserError(
            "repair-adoption is limited to pre-freeze stages: "
            + ", ".join(ADOPTABLE_STAGES)
        )
    if state.get("adoption"):
        raise UserError("adoption snapshot is already attached; run verify instead")
    if state["current_stage"] != args.expected_stage or state["initial_stage"] != args.expected_stage:
        raise UserError("--expected-stage does not match the legacy state")
    if state["status"] != args.expected_status or args.expected_status == "approved":
        raise UserError("--expected-status must match and cannot be approved")
    user_id = args.user_id.strip()
    reason = args.reason.strip()
    if not user_id or not reason:
        raise UserError("repair-adoption requires non-empty --user-id and --reason")
    artifacts = parse_role_inputs(lesson_dir, args.artifact)
    if not artifacts:
        raise UserError("repair-adoption requires explicit role-bound artifacts")
    existing_paths = {
        item.get("path") for item in state.get("artifacts", []) if isinstance(item, dict)
    }
    new_paths = {item["path"] for item in artifacts}
    if existing_paths - new_paths:
        raise UserError("repair request omitted artifacts already registered by the legacy state")
    now = utc_now()
    registered = [{**item, "registered_at": now} for item in artifacts]
    record = adoption_record_payload(
        lesson_id=lesson_id,
        initial_stage=args.expected_stage,
        status=args.expected_status,
        user_id=user_id,
        reason=reason,
        artifacts=registered,
    )
    adoption = write_or_reuse_adoption_snapshot(lesson_dir, record)
    new_state = dict(state)
    new_state["adoption"] = adoption
    new_state["artifacts"] = registered
    new_state.setdefault("invalidations", [])
    new_state.setdefault("active_approval_ids", [])
    new_state.setdefault("contract_gate_enforced_after_revision", state["revision"])
    new_state["updated_at"] = now
    atomic_write_json(lesson_dir / "state.json", new_state)
    emit_json(new_state)
    return 0


def command_status(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    state = load_state(data_home, validate_lesson_id(args.lesson_id))
    emit_json(state)
    return 0


def resolve_input(lesson_dir: Path, raw_path: str) -> tuple[Path, str]:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = lesson_dir / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise UserError(f"approval input does not exist: {candidate}") from error
    if not resolved.is_file():
        raise UserError(f"approval input is not a regular file: {resolved}")
    try:
        relative = resolved.relative_to(lesson_dir.resolve(strict=True))
    except ValueError as error:
        raise UserError(
            f"approval input must be stored inside the lesson directory: {resolved}"
        ) from error
    return resolved, relative.as_posix()


def parse_role_inputs(lesson_dir: Path, raw_values: Sequence[str]) -> list[dict[str, Any]]:
    """Resolve ROLE=PATH inputs and bind each role to a unique path and digest."""

    inputs: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    seen_paths: set[str] = set()
    seen_hashes: set[str] = set()
    for raw_value in raw_values:
        role, separator, raw_path = raw_value.partition("=")
        if not separator or not ROLE_RE.fullmatch(role):
            raise UserError(
                f"role input must use ROLE=PATH with a lowercase role identifier: {raw_value!r}"
            )
        if role in seen_roles:
            raise UserError(f"duplicate input role: {role}")
        resolved, relative = resolve_input(lesson_dir, raw_path)
        digest = sha256_file(resolved)
        if relative in seen_paths:
            raise UserError(f"one file cannot satisfy multiple roles: {relative}")
        if digest in seen_hashes:
            raise UserError("identical file content cannot satisfy multiple roles in one stage")
        seen_roles.add(role)
        seen_paths.add(relative)
        seen_hashes.add(digest)
        inputs.append(
            {
                "role": role,
                "path": relative,
                "sha256": digest,
                "size": resolved.stat().st_size,
            }
        )
    inputs.sort(key=lambda item: item["role"])
    return inputs


def require_stage_roles(stage: str, inputs: Sequence[dict[str, Any]]) -> None:
    roles = {item.get("role") for item in inputs}
    missing = sorted(STAGE_REQUIRED_ROLES[stage] - roles)
    if missing:
        raise UserError(f"stage {stage!r} is missing required input roles: {', '.join(missing)}")
    misplaced = sorted(
        role
        for role in roles
        if role in CANONICAL_ROLE_STAGE and CANONICAL_ROLE_STAGE[role] != stage
    )
    if misplaced:
        raise UserError(
            f"stage {stage!r} cannot reuse canonical roles owned by another stage: "
            + ", ".join(misplaced)
        )


def history_required_roles(stage: str, revision: int, gate_baseline: int) -> set[str]:
    if revision <= gate_baseline:
        return LEGACY_STAGE_REQUIRED_ROLES[stage]
    return STAGE_REQUIRED_ROLES[stage]


def text_contract_artifact_roles(contract: dict[str, Any]) -> tuple[str, ...]:
    """Resolve current roles while treating pre-mode contracts as handout history."""

    if contract.get("mode", "handout") == "ppt-only":
        return PPT_ONLY_TEXT_CONTRACT_ARTIFACT_ROLES
    return TEXT_CONTRACT_ARTIFACT_ROLES


def text_contract_sha256_from_approvals(
    approvals: Sequence[dict[str, Any]],
) -> str | None:
    for approval in reversed(approvals):
        if approval.get("stage") != "text-contract":
            continue
        for item in approval.get("inputs", []):
            if isinstance(item, dict) and item.get("role") == "text-contract":
                digest = item.get("sha256")
                return digest if isinstance(digest, str) else None
    return None


def source_artifact_hashes_from_approvals(
    approvals: Sequence[dict[str, Any]],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for approval in approvals:
        approval_stage = approval.get("stage")
        for item in approval.get("inputs", []):
            if not isinstance(item, dict) or item.get("role") not in TEXT_CONTRACT_ARTIFACT_ROLES:
                continue
            if CANONICAL_ROLE_STAGE[item["role"]] != approval_stage:
                continue
            digest = item.get("sha256")
            if isinstance(digest, str):
                hashes[item["role"]] = digest
    return hashes


def canonical_inputs_from_approvals(
    approvals: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    inputs: dict[str, dict[str, Any]] = {}
    for approval in approvals:
        approval_stage = approval.get("stage")
        for item in approval.get("inputs", []):
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if not isinstance(role, str) or CANONICAL_ROLE_STAGE.get(role) != approval_stage:
                continue
            inputs[role] = item
    return inputs


def _load_contract_validator() -> Any:
    global _CONTRACT_VALIDATOR_MODULE
    if _CONTRACT_VALIDATOR_MODULE is not None:
        return _CONTRACT_VALIDATOR_MODULE
    script = Path(__file__).resolve().with_name("validate_text_contract.py")
    try:
        spec = importlib.util.spec_from_file_location(
            "_yuwen_courseware_validate_text_contract", script
        )
        if spec is None or spec.loader is None:
            raise ImportError("cannot create module spec")
        module = importlib.util.module_from_spec(spec)
        previous_dont_write_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous_dont_write_bytecode
    except (OSError, ImportError, UnicodeError, SyntaxError) as error:
        raise RuntimeError(f"cannot load bundled contract validator: {error}") from error
    for name in (
        "validate_text_contract",
        "validate_ppt_text",
        "text_roles_for_contract",
        "_report",
    ):
        if not callable(getattr(module, name, None)):
            raise RuntimeError(f"bundled contract validator is missing callable {name}")
    _CONTRACT_VALIDATOR_MODULE = module
    return module


def _input_path(lesson_dir: Path, item: dict[str, Any]) -> Path:
    raw_path = item.get("path")
    if not isinstance(raw_path, str):
        raise UserError("contract input is missing a lesson-relative path")
    return safe_lesson_relative_path(lesson_dir, raw_path)


def rerun_contract_validation(
    lesson_dir: Path,
    *,
    stage: str,
    by_role: dict[str, dict[str, Any]],
    upstream_inputs: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the bundled semantic validator against the actual bound lesson files."""

    try:
        validator = _load_contract_validator()
        if stage == "text-contract":
            contract_item = by_role.get("text-contract")
        else:
            contract_item = upstream_inputs.get("text-contract")
        if not isinstance(contract_item, dict):
            return None, "contract-validator-missing-text-contract"
        contract, contract_error = _read_stage_input_json(
            lesson_dir, contract_item, "text-contract"
        )
        if contract_error or contract is None:
            return None, contract_error or "contract-validator-invalid-text-contract"
        artifact_roles = tuple(validator.text_roles_for_contract(contract))
        missing_sources = sorted(set(artifact_roles) - set(upstream_inputs))
        if missing_sources:
            return None, "contract-validator-missing-upstream-artifacts"
        artifacts = {
            role: _input_path(lesson_dir, upstream_inputs[role])
            for role in artifact_roles
        }
        if stage == "text-contract":
            semantic_issues, context = validator.validate_text_contract(
                _input_path(lesson_dir, contract_item), artifacts
            )
            mode = "text"
        else:
            structured_item = by_role.get("ppt-structured")
            ppt_text_item = by_role.get("ppt-text")
            if not all(
                isinstance(item, dict)
                for item in (contract_item, structured_item, ppt_text_item)
            ):
                return None, "contract-validator-missing-ppt-inputs"
            artifacts["ppt-text"] = _input_path(lesson_dir, ppt_text_item)
            semantic_issues, context = validator.validate_ppt_text(
                _input_path(lesson_dir, contract_item),
                _input_path(lesson_dir, structured_item),
                artifacts,
            )
            mode = "ppt"
        return validator._report(mode, semantic_issues, context), None
    except (UserError, OSError, UnicodeError, RuntimeError, ValueError, TypeError) as error:
        return None, f"contract-validator-execution-failed:{type(error).__name__}"


def _read_stage_input_json(
    lesson_dir: Path, item: dict[str, Any], label: str
) -> tuple[dict[str, Any] | None, str | None]:
    raw_path = item.get("path")
    if not isinstance(raw_path, str):
        return None, f"invalid-{label}-path"
    try:
        path = safe_lesson_relative_path(lesson_dir, raw_path)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UserError, OSError, UnicodeError, json.JSONDecodeError):
        return None, f"invalid-{label}-json"
    if not isinstance(value, dict):
        return None, f"invalid-{label}-record"
    return value, None


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _resolve_local_schema_ref(root_schema: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported non-local schema reference: {reference!r}")
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unresolvable schema reference: {reference!r}")
        current = current[part]
    return current


def _valid_schema_datetime(value: str) -> bool:
    if "T" not in value and "t" not in value:
        return False
    if not (value.endswith(("Z", "z")) or re.search(r"[+-][0-9]{2}:[0-9]{2}$", value)):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return False
    return True


def _json_schema_issues(
    value: Any,
    schema: Any,
    root_schema: dict[str, Any],
    path: str = "$",
) -> list[str]:
    """Evaluate the fail-closed JSON Schema subset used by bundled contracts."""

    if schema is True:
        return []
    if schema is False:
        return [f"{path}: rejected by false schema"]
    if not isinstance(schema, dict):
        return [f"{path}: schema node is not an object or boolean"]

    unknown = sorted(set(schema) - SUPPORTED_SCHEMA_KEYWORDS)
    if unknown:
        return [f"{path}: unsupported schema keyword(s): {', '.join(unknown)}"]

    issues: list[str] = []
    reference = schema.get("$ref")
    if reference is not None:
        if not isinstance(reference, str):
            return [f"{path}: schema $ref must be a string"]
        try:
            target = _resolve_local_schema_ref(root_schema, reference)
        except ValueError as error:
            return [f"{path}: {error}"]
        issues.extend(_json_schema_issues(value, target, root_schema, path))

    branches = schema.get("oneOf")
    if branches is not None:
        if not isinstance(branches, list) or not branches:
            issues.append(f"{path}: schema oneOf must be a non-empty array")
        else:
            matches = sum(
                not _json_schema_issues(value, branch, root_schema, path)
                for branch in branches
            )
            if matches != 1:
                issues.append(f"{path}: must match exactly one oneOf branch")

    all_branches = schema.get("allOf")
    if all_branches is not None:
        if not isinstance(all_branches, list):
            issues.append(f"{path}: schema allOf must be an array")
        else:
            for branch in all_branches:
                issues.extend(_json_schema_issues(value, branch, root_schema, path))

    conditional = schema.get("if")
    if conditional is not None:
        branch_name = "then" if not _json_schema_issues(
            value, conditional, root_schema, path
        ) else "else"
        if branch_name in schema:
            issues.extend(
                _json_schema_issues(value, schema[branch_name], root_schema, path)
            )

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = [expected_type] if isinstance(expected_type, str) else expected_type
        if (
            not isinstance(expected_types, list)
            or not expected_types
            or any(not isinstance(item, str) for item in expected_types)
        ):
            issues.append(f"{path}: schema type must be a string or non-empty string array")
            return issues
        if not any(_schema_type_matches(value, item) for item in expected_types):
            issues.append(f"{path}: value has the wrong JSON type")
            return issues

    if "const" in schema and value != schema["const"]:
        issues.append(f"{path}: value does not equal schema const")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or value not in enum:
            issues.append(f"{path}: value is not in schema enum")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            issues.append(f"{path}: schema required must be a string array")
            required = []
        for key in required:
            if key not in value:
                issues.append(f"{path}.{key}: required property is missing")

        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            issues.append(f"{path}: schema properties must be an object")
            properties = {}
        for key, child_schema in properties.items():
            if key in value:
                issues.extend(
                    _json_schema_issues(value[key], child_schema, root_schema, f"{path}.{key}")
                )
        additional = schema.get("additionalProperties", True)
        extras = sorted(set(value) - set(properties))
        if additional is False:
            issues.extend(f"{path}.{key}: additional property is not allowed" for key in extras)
        elif isinstance(additional, dict) or isinstance(additional, bool):
            if additional is not True:
                for key in extras:
                    issues.extend(
                        _json_schema_issues(value[key], additional, root_schema, f"{path}.{key}")
                    )
        else:
            issues.append(f"{path}: schema additionalProperties is invalid")

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            issues.append(f"{path}: array has fewer than {minimum_items} items")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            issues.append(f"{path}: array has more than {maximum_items} items")
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(item == previous for previous in value[:index]):
                    issues.append(f"{path}[{index}]: array item is not unique")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                issues.extend(
                    _json_schema_issues(item, item_schema, root_schema, f"{path}[{index}]")
                )

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            issues.append(f"{path}: string is shorter than {minimum_length} characters")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            issues.append(f"{path}: string is longer than {maximum_length} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matches = re.search(pattern, value) is not None
            except re.error as error:
                issues.append(f"{path}: invalid schema pattern: {error}")
            else:
                if not matches:
                    issues.append(f"{path}: string does not match schema pattern")
        if schema.get("format") == "date-time" and not _valid_schema_datetime(value):
            issues.append(f"{path}: string is not an RFC 3339 date-time")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            issues.append(f"{path}: number is below schema minimum")
        if isinstance(maximum, (int, float)) and value > maximum:
            issues.append(f"{path}: number is above schema maximum")
    return issues


def bundled_schema_issues(value: dict[str, Any], label: str) -> list[str]:
    schema_name = CONTRACT_SCHEMA_FILES[label]
    schema_path = (
        Path(__file__).resolve().parents[1] / "references" / "schemas" / schema_name
    )
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [f"bundled schema unavailable or invalid: {schema_name}: {error}"]
    if not isinstance(schema, dict):
        return [f"bundled schema root is not an object: {schema_name}"]
    return _json_schema_issues(value, schema, schema)


def contract_gate_issues(
    lesson_dir: Path,
    *,
    lesson_id: str,
    stage: str,
    inputs: Sequence[dict[str, Any]],
    upstream_text_contract_sha256: str | None,
    upstream_artifact_hashes: dict[str, str],
    upstream_inputs: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate that deterministic contract reports are positive and hash-bound."""

    if stage not in {"text-contract", "ppt-text"}:
        return []
    by_role = {
        item.get("role"): item
        for item in inputs
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    report_role = "text-contract-report" if stage == "text-contract" else "ppt-contract-report"
    report_item = by_role.get(report_role)
    if not isinstance(report_item, dict):
        return ["missing-contract-validation-report"]
    report, error = _read_stage_input_json(lesson_dir, report_item, "contract-report")
    if error or report is None:
        return [error or "invalid-contract-report"]

    issues: list[str] = []
    if bundled_schema_issues(report, "contract-report"):
        issues.append("contract-report-schema-invalid")
    expected_report, validator_error = rerun_contract_validation(
        lesson_dir,
        stage=stage,
        by_role=by_role,
        upstream_inputs=upstream_inputs,
    )
    if validator_error:
        issues.append(validator_error)
    elif expected_report is not None:
        if expected_report.get("ok") is not True:
            issues.append(f"{stage}-semantic-validation-failed")
        if report != expected_report:
            issues.append("contract-report-validator-output-mismatch")
    expected_mode = "text" if stage == "text-contract" else "ppt"
    if report.get("schema_version") != "1.0":
        issues.append("contract-report-schema-mismatch")
    if report.get("record_type") != "contract-validation-report":
        issues.append("contract-report-record-type-mismatch")
    if report.get("validator") != CONTRACT_VALIDATOR_ID:
        issues.append("contract-report-validator-mismatch")
    if report.get("mode") != expected_mode:
        issues.append("contract-report-mode-mismatch")
    if report.get("lesson_id") != lesson_id:
        issues.append("contract-report-lesson-mismatch")
    if report.get("ok") is not True:
        issues.append("contract-report-not-passing")
    if report.get("issues") != []:
        issues.append("contract-report-has-issues")

    if stage == "text-contract":
        contract_item = by_role.get("text-contract")
        if not isinstance(contract_item, dict):
            issues.append("missing-text-contract")
            return list(dict.fromkeys(issues))
        if report.get("text_contract_sha256") != contract_item.get("sha256"):
            issues.append("contract-report-text-contract-hash-mismatch")
        contract, contract_error = _read_stage_input_json(
            lesson_dir, contract_item, "text-contract"
        )
        if contract_error or contract is None:
            issues.append(contract_error or "invalid-text-contract")
        else:
            if bundled_schema_issues(contract, "text-contract"):
                issues.append("text-contract-schema-invalid")
            if contract.get("record_type") != "text-contract":
                issues.append("text-contract-record-type-mismatch")
            if contract.get("lesson_id") != lesson_id:
                issues.append("text-contract-lesson-mismatch")
            bindings = contract.get("artifacts")
            expected_hashes: dict[str, str] = {}
            if not isinstance(bindings, dict):
                issues.append("text-contract-artifact-bindings-invalid")
            else:
                artifact_roles = text_contract_artifact_roles(contract)
                for role in artifact_roles:
                    binding = bindings.get(role)
                    digest = binding.get("sha256") if isinstance(binding, dict) else None
                    if not isinstance(digest, str):
                        issues.append("text-contract-artifact-bindings-invalid")
                    else:
                        expected_hashes[role] = digest
                if report.get("artifact_hashes") != expected_hashes:
                    issues.append("contract-report-artifact-hashes-mismatch")
                if expected_hashes != upstream_artifact_hashes:
                    issues.append("text-contract-upstream-artifact-hashes-mismatch")
    else:
        ppt_text_item = by_role.get("ppt-text")
        structured_item = by_role.get("ppt-structured")
        if not isinstance(ppt_text_item, dict) or not isinstance(structured_item, dict):
            issues.append("missing-ppt-contract-input")
            return list(dict.fromkeys(issues))
        if report.get("ppt_text_sha256") != ppt_text_item.get("sha256"):
            issues.append("contract-report-ppt-text-hash-mismatch")
        if report.get("ppt_structured_sha256") != structured_item.get("sha256"):
            issues.append("contract-report-ppt-structured-hash-mismatch")
        structured, structured_error = _read_stage_input_json(
            lesson_dir, structured_item, "ppt-structured"
        )
        if structured_error or structured is None:
            issues.append(structured_error or "invalid-ppt-structured")
        else:
            if bundled_schema_issues(structured, "ppt-structured"):
                issues.append("ppt-structured-schema-invalid")
            if structured.get("record_type") != "ppt-text":
                issues.append("ppt-structured-record-type-mismatch")
            if structured.get("lesson_id") != lesson_id:
                issues.append("ppt-structured-lesson-mismatch")
            if structured.get("ppt_text_sha256") != ppt_text_item.get("sha256"):
                issues.append("ppt-structured-text-hash-mismatch")
            structured_contract_hash = structured.get("text_contract_sha256")
            if report.get("text_contract_sha256") != structured_contract_hash:
                issues.append("contract-report-upstream-hash-mismatch")
            if (
                upstream_text_contract_sha256 is None
                or structured_contract_hash != upstream_text_contract_sha256
            ):
                issues.append("ppt-upstream-text-contract-not-active")
    return list(dict.fromkeys(issues))


def require_contract_gate(
    state: dict[str, Any],
    lesson_dir: Path,
    *,
    lesson_id: str,
    stage: str,
    inputs: Sequence[dict[str, Any]],
) -> None:
    replayed = replay_history(state, lesson_dir)
    active_approvals = replayed["active_approvals"]
    issues = contract_gate_issues(
        lesson_dir,
        lesson_id=lesson_id,
        stage=stage,
        inputs=inputs,
        upstream_text_contract_sha256=text_contract_sha256_from_approvals(active_approvals),
        upstream_artifact_hashes=source_artifact_hashes_from_approvals(active_approvals),
        upstream_inputs=canonical_inputs_from_approvals(active_approvals),
    )
    if issues:
        raise UserError(
            "deterministic contract gate failed: " + ", ".join(sorted(issues))
        )


def input_fingerprint(inputs: Sequence[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return sorted((item["role"], item["path"], item["sha256"]) for item in inputs)


def validate_confirmation_evidence(
    lesson_dir: Path,
    raw_path: str,
    *,
    lesson_id: str,
    stage: str,
    user_id: str,
    expected_resource_choice: str | None = None,
    require_resource_choice: bool = False,
) -> tuple[dict[str, Any], str, list[str]]:
    resolved, relative = resolve_input(lesson_dir, raw_path)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as error:
        raise UserError(f"user confirmation must be a valid UTF-8 JSON file: {error}") from error
    common_expected = {
        "lesson_id": lesson_id,
        "user_id": user_id,
        "decision": "approve",
        "source": "host-conversation",
    }
    provenance_fields = (
        "host",
        "conversation_id",
        "message_id",
        "confirmed_at",
        "decision_text",
    )
    if not isinstance(value, dict) or any(
        value.get(key) != wanted for key, wanted in common_expected.items()
    ) or any(
        not isinstance(value.get(key), str) or not value[key].strip()
        for key in provenance_fields
    ):
        raise UserError(
            "user confirmation JSON must contain matching lesson_id/user_id, "
            "decision=approve, source=host-conversation, and non-empty "
            "host/conversation_id/message_id/confirmed_at/decision_text provenance"
        )

    record_type = value.get("record_type")
    if record_type == "user-confirmation":
        if value.get("stage") != stage:
            raise UserError(
                "user confirmation JSON must contain record_type=user-confirmation and "
                "a stage matching the current stage"
            )
        mode = "single"
        stages = [stage]
    elif record_type == "user-batch-confirmation":
        stages = value.get("stages")
        if (
            not isinstance(stages, list)
            or len(stages) < 2
            or any(item not in STAGE_INDEX for item in stages)
            or len(set(stages)) != len(stages)
        ):
            raise UserError(
                "batch confirmation stages must contain at least two unique known stages"
            )
        indexes = [STAGE_INDEX[item] for item in stages]
        if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            raise UserError("batch confirmation must bind continuous stages in workflow order")
        redlines = sorted(set(stages) & INDEPENDENT_CONFIRMATION_STAGES)
        if redlines:
            raise UserError(
                "teaching-design, text-contract, and release require independent confirmation; "
                "batch confirmation cannot include: " + ", ".join(redlines)
            )
        if stage not in stages:
            raise UserError("current stage is not covered by the batch confirmation")
        mode = "batch"
    else:
        raise UserError(
            "user confirmation record_type must be user-confirmation or "
            "user-batch-confirmation"
        )

    if expected_resource_choice is not None:
        if "resource_choice" not in value:
            if require_resource_choice:
                raise UserError(
                    "teaching-design confirmation must explicitly set "
                    "resource_choice to 'ppt-only' or 'handout'"
                )
        else:
            resource_choice = value.get("resource_choice")
            if resource_choice not in {"ppt-only", "handout"}:
                raise UserError(
                    "teaching-design confirmation resource_choice must be "
                    "'ppt-only' or 'handout'"
                )
            if resource_choice != expected_resource_choice:
                raise UserError(
                    "teaching-design confirmation resource_choice does not match "
                    "the selected next stage"
                )

    reference = {
        "path": relative,
        "sha256": sha256_file(resolved),
        "size": resolved.stat().st_size,
    }
    return reference, mode, stages


def validate_confirmation_file(
    lesson_dir: Path,
    raw_path: str,
    *,
    lesson_id: str,
    stage: str,
    user_id: str,
) -> dict[str, Any]:
    reference, _, _ = validate_confirmation_evidence(
        lesson_dir,
        raw_path,
        lesson_id=lesson_id,
        stage=stage,
        user_id=user_id,
    )
    return reference


def validate_revision_confirmation_file(
    lesson_dir: Path,
    raw_path: str,
    *,
    lesson_id: str,
    stage: str,
    user_id: str,
    reason: str,
) -> dict[str, Any]:
    resolved, relative = resolve_input(lesson_dir, raw_path)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as error:
        raise UserError(
            f"user revision confirmation must be a valid UTF-8 JSON file: {error}"
        ) from error
    expected = {
        "record_type": "user-revision-confirmation",
        "lesson_id": lesson_id,
        "stage": stage,
        "user_id": user_id,
        "decision": "revise",
        "source": "host-conversation",
        "reason": reason,
    }
    provenance_fields = (
        "host",
        "conversation_id",
        "message_id",
        "confirmed_at",
        "decision_text",
    )
    if (
        not isinstance(value, dict)
        or any(value.get(key) != wanted for key, wanted in expected.items())
        or any(
            not isinstance(value.get(key), str) or not value[key].strip()
            for key in provenance_fields
        )
    ):
        raise UserError(
            "user revision confirmation JSON must contain record_type=user-revision-confirmation, "
            "matching lesson_id/stage/user_id/reason, decision=revise, "
            "source=host-conversation, and non-empty "
            "host/conversation_id/message_id/confirmed_at/decision_text provenance"
        )
    return {
        "path": relative,
        "sha256": sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def non_blank_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def review_report_reference(
    lesson_dir: Path,
    raw_report: Any,
    *,
    input_paths: set[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate one immutable review report and return its current file reference."""

    if not isinstance(raw_report, dict) or set(raw_report) != {"path", "sha256", "size"}:
        return None, ["invalid-quality-review-report-reference"]
    report_path = raw_report.get("path")
    if not non_blank_string(report_path):
        return None, ["invalid-quality-review-report-reference"]
    if report_path in input_paths:
        return None, ["quality-review-report-reuses-stage-output"]
    try:
        resolved = safe_lesson_relative_path(lesson_dir, report_path)
    except UserError:
        return None, ["unsafe-quality-review-report"]
    if not resolved.is_file():
        return None, ["missing-quality-review-report"]
    current = {
        "path": report_path,
        "sha256": sha256_file(resolved),
        "size": resolved.stat().st_size,
    }
    issues: list[str] = []
    if current["sha256"] != raw_report.get("sha256"):
        issues.append("quality-review-report-hash-mismatch")
    if current["size"] != raw_report.get("size"):
        issues.append("quality-review-report-size-mismatch")
    return current, issues


def validate_quote_check_report_file(
    lesson_dir: Path,
    raw_path: str,
    *,
    lesson_id: str,
    input_paths: set[str],
) -> dict[str, Any]:
    resolved, relative = resolve_input(lesson_dir, raw_path)
    if relative in input_paths:
        raise UserError("quote-check report must be separate from every stage input")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as error:
        raise UserError(f"quote-check report must be valid UTF-8 JSON: {error}") from error
    summary = value.get("summary") if isinstance(value, dict) else None
    checklist = value.get("checklist") if isinstance(value, dict) else None
    sources = value.get("sources") if isinstance(value, dict) else None
    results = value.get("results") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("record_type") != "verbatim-quote-check-report"
        or value.get("lesson_id") != lesson_id
        or value.get("ok") is not True
        or not isinstance(summary, dict)
        or summary.get("different") != 0
        or not isinstance(summary.get("total"), int)
        or summary["total"] < 1
        or not isinstance(checklist, dict)
        or set(checklist) != {"path", "sha256"}
        or not isinstance(checklist.get("path"), str)
        or not isinstance(checklist.get("sha256"), str)
        or not isinstance(sources, list)
        or not sources
        or not isinstance(results, list)
        or len(results) != summary["total"]
        or any(not isinstance(item, dict) or item.get("status") != "passed" for item in results)
        or value.get("differences") != []
    ):
        raise UserError(
            "verbatim quote check failed or report scope is invalid; dual review is blocked"
        )
    try:
        checklist_relative = (
            Path(relative).parent / Path(checklist["path"])
        ).as_posix()
        checklist_path = safe_lesson_relative_path(lesson_dir, checklist_relative)
    except UserError as error:
        raise UserError("quote-check checklist reference is unsafe") from error
    if not checklist_path.is_file() or sha256_file(checklist_path) != checklist["sha256"]:
        raise UserError("quote-check checklist is missing or its SHA-256 has changed")
    return {
        "path": relative,
        "sha256": sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def quality_review_contract_issues(
    record: Any,
    lesson_dir: Path,
    *,
    lesson_id: str,
    stage: str,
    expected_inputs: Sequence[dict[str, Any]],
    require_pass: bool,
) -> list[str]:
    """Return schema-like and file-integrity failures for one AI review record."""

    if not isinstance(record, dict):
        return ["invalid-quality-review-record"]
    issues: list[str] = []
    if set(record) != QUALITY_REVIEW_REQUIRED_KEYS:
        issues.append("quality-review-fields-mismatch")
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append("quality-review-schema-mismatch")
    if record.get("record_type") != "online-quality-review":
        issues.append("quality-review-record-type-mismatch")
    if record.get("lesson_id") != lesson_id or record.get("stage") != stage:
        issues.append("quality-review-scope-mismatch")
    if record.get("reviewer_type") != "ai" or record.get("runtime_mode") != "online":
        issues.append("quality-review-runtime-mismatch")
    if not isinstance(record.get("review_id"), str) or not REVIEW_ID_RE.fullmatch(
        record["review_id"]
    ):
        issues.append("invalid-quality-review-id")
    for field in (
        "reviewer_id",
        "route_id",
        "provider",
        "model",
        "run_id",
        "persona_version",
        "prompt_version",
        "reviewed_at",
    ):
        if not non_blank_string(record.get(field)):
            issues.append(f"missing-quality-review-{field.replace('_', '-')}")
    verdict = record.get("verdict")
    if verdict not in {"pass", "fail"} or (require_pass and verdict != "pass"):
        issues.append("quality-review-verdict-mismatch")
    comment = record.get("comment")
    if comment is not None and not non_blank_string(comment):
        issues.append("invalid-quality-review-comment")
    record_inputs = record.get("inputs")
    if not isinstance(record_inputs, list):
        issues.append("quality-review-input-invalid")
        record_inputs = []
    try:
        if input_fingerprint(record_inputs) != input_fingerprint(expected_inputs):
            issues.append("quality-review-input-mismatch")
    except (KeyError, TypeError):
        issues.append("quality-review-input-invalid")
    input_paths = {
        item.get("path") for item in record_inputs if isinstance(item, dict)
    }
    _, report_issues = review_report_reference(
        lesson_dir, record.get("report"), input_paths=input_paths
    )
    issues.extend(report_issues)
    quote_check_reference = record.get("quote_check_report")
    if stage in DUAL_REVIEW_STAGES:
        if not isinstance(quote_check_reference, dict):
            issues.append("missing-quote-check-report")
        else:
            quote_check_path = quote_check_reference.get("path")
            if not isinstance(quote_check_path, str):
                issues.append("invalid-quote-check-report-reference")
            else:
                try:
                    current_quote_check = validate_quote_check_report_file(
                        lesson_dir,
                        quote_check_path,
                        lesson_id=lesson_id,
                        input_paths=input_paths,
                    )
                except UserError:
                    issues.append("failed-quote-check-report")
                else:
                    if current_quote_check != quote_check_reference:
                        issues.append("quote-check-report-hash-mismatch")
    elif quote_check_reference is not None:
        issues.append("unexpected-quote-check-report")
    return list(dict.fromkeys(issues))


def default_next_stage(current_stage: str) -> str | None:
    index = STAGE_INDEX[current_stage]
    if current_stage == "teaching-design":
        return "teaching-script"
    if current_stage == "ppt-text":
        return "release"
    if current_stage == "release":
        return None
    return STAGES[index + 1]


def allowed_next_stages(current_stage: str) -> set[str | None]:
    if current_stage == "teaching-design":
        return {"student-resources", "teaching-script"}
    if current_stage == "ppt-text":
        return {"external-ppt-check", "release"}
    if current_stage == "release":
        return {None}
    return {default_next_stage(current_stage)}


def determine_next_stage(current_stage: str, requested: str | None) -> str | None:
    default = default_next_stage(current_stage)
    if requested is None:
        return default
    allowed = allowed_next_stages(current_stage) - {None}
    if requested not in allowed:
        allowed_text = ", ".join(sorted(allowed)) if allowed else "none"
        raise UserError(
            f"illegal next stage {requested!r} after {current_stage!r}; allowed: {allowed_text}"
        )
    return requested


def write_conflict_diagnostic(
    lesson_dir: Path,
    *,
    lesson_id: str,
    expected_revision: int,
    actual_revision: int,
) -> Path | None:
    path = lesson_dir / "conflicts" / (
        f"revision-{expected_revision}-actual-{actual_revision}-{uuid4().hex}.json"
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": "revision-conflict",
        "lesson_id": lesson_id,
        "expected_revision": expected_revision,
        "actual_revision": actual_revision,
        "detected_at": utc_now(),
    }
    try:
        exclusive_write_json(path, record, read_only=True)
    except (OSError, UserError):
        return None
    return path


def historical_approved_inputs(
    state: dict[str, Any], lesson_dir: Path
) -> tuple[set[str], set[str]]:
    paths: set[str] = set()
    hashes: set[str] = set()
    for reference in state["approvals"]:
        record_path = safe_lesson_relative_path(lesson_dir, reference["file"])
        record = json.loads(record_path.read_text(encoding="utf-8"))
        for item in record.get("inputs", []):
            if isinstance(item, dict):
                if isinstance(item.get("path"), str):
                    paths.add(item["path"])
                if isinstance(item.get("sha256"), str):
                    hashes.add(item["sha256"])
    return paths, hashes


def history_events(
    state: dict[str, Any], lesson_dir: Path
) -> list[tuple[int, str, dict[str, Any]]]:
    """Load the immutable approval/invalidation ledger in global revision order.

    Callers must run ``collect_integrity_issues`` first.  This helper deliberately
    stays small and assumes every referenced snapshot has already been verified.
    """

    events: list[tuple[int, str, dict[str, Any]]] = []
    for kind, references in (
        ("approval", state.get("approvals", [])),
        ("invalidation", state.get("invalidations", [])),
    ):
        for reference in references:
            record_path = safe_lesson_relative_path(lesson_dir, reference["file"])
            record = json.loads(record_path.read_text(encoding="utf-8"))
            events.append((int(reference["revision"]), kind, record))
    events.sort(key=lambda item: item[0])
    return events


def replay_history(state: dict[str, Any], lesson_dir: Path) -> dict[str, Any]:
    """Derive the active workflow view without discarding immutable history."""

    current_stage = state["initial_stage"]
    status = "draft" if state.get("origin") == "new" else state.get("status", "draft")
    visited_stages = {current_stage}
    active_approvals: list[dict[str, Any]] = []
    latest_stage_inputs: dict[str, list[dict[str, Any]]] = {}
    pending_stage: str | None = None
    pending_inputs: list[dict[str, Any]] | None = None

    initial_roles = STAGE_REQUIRED_ROLES[current_stage]
    initial_inputs = [
        {key: item[key] for key in ("role", "path", "sha256", "size")}
        for item in state.get("artifacts", [])
        if isinstance(item, dict) and item.get("role") in initial_roles
    ]
    if initial_roles.issubset({item["role"] for item in initial_inputs}):
        latest_stage_inputs[current_stage] = sorted(
            initial_inputs, key=lambda item: item["role"]
        )

    for _, kind, record in history_events(state, lesson_dir):
        if kind == "approval":
            stage = record["stage"]
            active_approvals.append(record)
            latest_stage_inputs[stage] = record["inputs"]
            next_stage = record["next_stage"]
            if next_stage is None:
                current_stage = stage
                status = "approved"
            else:
                current_stage = next_stage
                status = "draft"
                visited_stages.add(next_stage)
            visited_stages.add(stage)
            if pending_stage == stage:
                pending_stage = None
                pending_inputs = None
        else:
            target_stage = record["target_stage"]
            target_index = STAGE_INDEX[target_stage]
            active_approvals = [
                approval
                for approval in active_approvals
                if STAGE_INDEX[approval["stage"]] < target_index
            ]
            latest_stage_inputs[target_stage] = record["inputs"]
            current_stage = target_stage
            status = "draft"
            visited_stages.add(target_stage)
            pending_stage = target_stage
            pending_inputs = record["inputs"]

    return {
        "current_stage": current_stage,
        "status": status,
        "visited_stages": visited_stages,
        "active_approvals": active_approvals,
        "latest_stage_inputs": latest_stage_inputs,
        "pending_stage": pending_stage,
        "pending_inputs": pending_inputs,
    }


def role_content_fingerprint(inputs: Sequence[dict[str, Any]]) -> list[tuple[str, str]]:
    """Compare stage content by role and digest while allowing a new immutable path."""

    return sorted((item["role"], item["sha256"]) for item in inputs)


def require_pending_revision_inputs(
    state: dict[str, Any], lesson_dir: Path, inputs: Sequence[dict[str, Any]]
) -> None:
    replayed = replay_history(state, lesson_dir)
    if replayed["pending_stage"] != state["current_stage"]:
        return
    pending = replayed["pending_inputs"]
    if pending is None or input_fingerprint(pending) != input_fingerprint(inputs):
        raise UserError(
            "stage inputs must exactly match the ROLE=PATH hashes registered by the latest revision"
        )


def reject_reused_stage_outputs(
    state: dict[str, Any],
    lesson_dir: Path,
    inputs: Sequence[dict[str, Any]],
    *,
    allow_exact: Sequence[dict[str, Any]] = (),
) -> None:
    used_paths, used_hashes = historical_approved_inputs(state, lesson_dir)
    allowed = set(input_fingerprint(allow_exact))
    for item in inputs:
        if (item["role"], item["path"], item["sha256"]) in allowed:
            continue
        if item["path"] in used_paths:
            raise UserError(f"stage output path was already approved earlier: {item['path']}")
        if item["sha256"] in used_hashes:
            raise UserError(
                f"stage output duplicates previously approved content for role {item['role']!r}"
            )


def historical_approval_record(
    state: dict[str, Any], lesson_dir: Path, approval_id: str
) -> dict[str, Any]:
    for reference in state["approvals"]:
        if reference.get("approval_id") != approval_id:
            continue
        path = safe_lesson_relative_path(lesson_dir, reference["file"])
        return json.loads(path.read_text(encoding="utf-8"))
    raise UserError(f"rebuild source approval does not exist: {approval_id}")


def validate_rebuild_source(
    state: dict[str, Any],
    lesson_dir: Path,
    *,
    approval_id: str,
    stage: str,
    inputs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if approval_id in set(state.get("active_approval_ids", [])):
        raise UserError("rebuild must inherit an invalidated approval, not an active approval")
    inherited = historical_approval_record(state, lesson_dir, approval_id)
    if inherited.get("stage") != stage:
        raise UserError(
            f"rebuild source stage {inherited.get('stage')!r} does not match current stage {stage!r}"
        )
    if input_fingerprint(inherited.get("inputs", [])) != input_fingerprint(inputs):
        raise UserError(
            "rebuild inputs must use the exact ROLE=PATH hashes from the inherited approval"
        )
    return inherited


def command_record_review(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    state = load_state(data_home, lesson_id)
    lesson_dir = lesson_directory(data_home, lesson_id)
    if state["status"] == "invalidated":
        raise UserError("cannot review an invalidated lesson state")
    if args.stage != state["current_stage"]:
        raise UserError("review stage must equal the lesson's current stage")
    integrity_issues, _ = effective_integrity_issues(state, lesson_dir, lesson_id)
    if integrity_issues:
        kinds = ", ".join(sorted({issue["kind"] for issue in integrity_issues}))
        raise UserError(f"lesson integrity check failed before review ({kinds})")
    inputs = parse_role_inputs(lesson_dir, args.input)
    require_stage_roles(args.stage, inputs)
    replayed = replay_history(state, lesson_dir)
    pending_inputs = (
        replayed["pending_inputs"]
        if replayed["pending_stage"] == args.stage
        else ()
    )
    reject_reused_stage_outputs(
        state, lesson_dir, inputs, allow_exact=pending_inputs or ()
    )
    require_pending_revision_inputs(state, lesson_dir, inputs)
    require_contract_gate(
        state,
        lesson_dir,
        lesson_id=lesson_id,
        stage=args.stage,
        inputs=inputs,
    )
    reviewer_id = args.reviewer_id.strip()
    route_id = args.route_id.strip()
    provider = args.provider.strip()
    model = args.model.strip()
    run_id = args.run_id.strip()
    persona_version = args.persona_version.strip()
    prompt_version = args.prompt_version.strip()
    if not all(
        (reviewer_id, route_id, provider, model, run_id, persona_version, prompt_version)
    ):
        raise UserError(
            "reviewer-id, route-id, provider, model, run-id, persona-version, and "
            "prompt-version must not be empty"
        )
    report_path, report_relative = resolve_input(lesson_dir, args.report)
    input_paths = {item["path"] for item in inputs}
    if report_relative in input_paths:
        raise UserError("quality review report must be separate from every stage input")
    report = {
        "path": report_relative,
        "sha256": sha256_file(report_path),
        "size": report_path.stat().st_size,
    }
    quote_check_report: dict[str, Any] | None = None
    if args.stage in DUAL_REVIEW_STAGES:
        if not args.quote_check_report:
            raise UserError(
                "dual review requires --quote-check-report from a passing deterministic check"
            )
        quote_check_report = validate_quote_check_report_file(
            lesson_dir,
            args.quote_check_report,
            lesson_id=lesson_id,
            input_paths=input_paths | {report_relative},
        )
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "online-quality-review",
        "review_id": f"review-{uuid4().hex}",
        "lesson_id": lesson_id,
        "stage": args.stage,
        "reviewer_type": "ai",
        "reviewer_id": reviewer_id,
        "route_id": route_id,
        "provider": provider,
        "model": model,
        "runtime_mode": args.runtime_mode,
        "run_id": run_id,
        "persona_version": persona_version,
        "prompt_version": prompt_version,
        "verdict": args.verdict,
        "comment": args.comment.strip() if args.comment and args.comment.strip() else None,
        "reviewed_at": utc_now(),
        "inputs": inputs,
        "report": report,
        "quote_check_report": quote_check_report,
    }
    path = lesson_dir / "reviews" / f"{record['review_id']}.json"
    exclusive_write_json(path, record, read_only=True)
    emit_json(record)
    return 0


def matching_quality_reviews(
    lesson_dir: Path,
    lesson_id: str,
    stage: str,
    inputs: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    review_dir = lesson_dir / "reviews"
    if not review_dir.is_dir():
        return []
    for path in sorted(review_dir.glob("*.json")):
        payload = path.read_bytes()
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if quality_review_contract_issues(
            record,
            lesson_dir,
            lesson_id=lesson_id,
            stage=stage,
            expected_inputs=inputs,
            require_pass=True,
        ):
            continue
        eligible.append(
            {
                "file": path.relative_to(lesson_dir).as_posix(),
                "snapshot_sha256": sha256_bytes(payload),
                "review_id": record["review_id"],
                "reviewer_id": record["reviewer_id"],
                "route_id": record["route_id"],
                "run_id": record["run_id"],
                "report_path": record["report"]["path"],
            }
        )
    return eligible


def select_independent_reviews(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    independent_fields = ("reviewer_id", "route_id", "run_id", "report_path")
    for first_index, first in enumerate(candidates):
        for second in candidates[first_index + 1 :]:
            if all(
                first.get(field) and first.get(field) != second.get(field)
                for field in independent_fields
            ):
                return [first, second]
    return []


def state_after_approval(
    state: dict[str, Any], record: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    next_stage = record["next_stage"]
    new_state = dict(state)
    new_state["revision"] = record["resulting_revision"]
    new_state["approvals"] = [*state["approvals"], reference]
    previous_active = state.get("active_approval_ids")
    if previous_active is None:
        previous_active = [item["approval_id"] for item in state["approvals"]]
    new_state["active_approval_ids"] = [*previous_active, record["approval_id"]]
    new_state.setdefault("invalidations", [])
    new_state.setdefault("contract_gate_enforced_after_revision", state["revision"])
    new_state["updated_at"] = record["approved_at"]
    if next_stage is None:
        new_state["status"] = "approved"
    else:
        new_state["current_stage"] = next_stage
        new_state["current_stage_index"] = STAGE_INDEX[next_stage]
        new_state["status"] = "draft"
    return new_state


@mutation_locked
def command_approve(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    state = load_state(data_home, lesson_id)
    lesson_dir = lesson_directory(data_home, lesson_id)
    actual_revision = state["revision"]
    if actual_revision != args.expected_revision:
        diagnostic = write_conflict_diagnostic(
            lesson_dir,
            lesson_id=lesson_id,
            expected_revision=args.expected_revision,
            actual_revision=actual_revision,
        )
        suffix = f"; diagnostic: {diagnostic}" if diagnostic else ""
        raise UserError(
            f"revision conflict: expected {args.expected_revision}, actual {actual_revision}{suffix}"
        )

    if state["status"] == "invalidated":
        raise UserError("lesson state is invalidated; resolve and re-establish the stage before approval")
    if state["current_stage"] == "release" and state["status"] == "approved":
        raise UserError("release is already approved; a duplicate approval is not allowed")
    integrity_issues, _ = effective_integrity_issues(state, lesson_dir, lesson_id)
    if integrity_issues:
        kinds = ", ".join(sorted({issue["kind"] for issue in integrity_issues}))
        raise UserError(
            "existing lesson integrity check failed; run verify and resolve all integrity "
            f"issues before approval ({kinds})"
        )

    current_stage = state["current_stage"]
    next_stage = determine_next_stage(current_stage, args.next_stage)
    user_id = args.user_id.strip()
    if not user_id:
        raise UserError("user-id must not be empty")
    comment = args.comment.strip() if args.comment else None
    if not comment:
        comment = None
    limits = []
    for value in args.limit:
        normalized = value.strip()
        if not normalized:
            raise UserError("approval limit must not be empty")
        limits.append(normalized)
    inputs = parse_role_inputs(lesson_dir, args.input)
    require_stage_roles(current_stage, inputs)
    inherited_approval: dict[str, Any] | None = None
    rebuild: dict[str, Any] | None = None
    if args.rebuild_from:
        inherited_id = args.rebuild_from.strip()
        if not inherited_id:
            raise UserError("rebuild-from approval id must not be empty")
        inherited_approval = validate_rebuild_source(
            state,
            lesson_dir,
            approval_id=inherited_id,
            stage=current_stage,
            inputs=inputs,
        )
        rebuild = {
            "content_unchanged": True,
            "inherited_approval_id": inherited_id,
        }
    else:
        replayed = replay_history(state, lesson_dir)
        pending_inputs = (
            replayed["pending_inputs"]
            if replayed["pending_stage"] == current_stage
            else ()
        )
        reject_reused_stage_outputs(
            state, lesson_dir, inputs, allow_exact=pending_inputs or ()
        )
    require_pending_revision_inputs(state, lesson_dir, inputs)
    require_contract_gate(
        state,
        lesson_dir,
        lesson_id=lesson_id,
        stage=current_stage,
        inputs=inputs,
    )
    confirmation, confirmation_mode, confirmation_stages = validate_confirmation_evidence(
        lesson_dir,
        args.confirmation,
        lesson_id=lesson_id,
        stage=current_stage,
        user_id=user_id,
        expected_resource_choice=(
            "handout"
            if current_stage == "teaching-design" and next_stage == "student-resources"
            else "ppt-only" if current_stage == "teaching-design" else None
        ),
        require_resource_choice=current_stage == "teaching-design",
    )
    if confirmation["path"] in {item["path"] for item in inputs}:
        raise UserError("user confirmation must be a separate file from all stage outputs")
    quality_reviews: list[dict[str, Any]] = []
    if current_stage in DUAL_REVIEW_STAGES:
        if inherited_approval is not None:
            quality_reviews = inherited_approval.get("quality_reviews", [])
        else:
            quality_reviews = select_independent_reviews(
                matching_quality_reviews(lesson_dir, lesson_id, current_stage, inputs)
            )
        if len(quality_reviews) != 2:
            raise UserError(
                f"stage {current_stage!r} requires two passing independent online quality reviews"
            )

    resulting_revision = actual_revision + 1
    approval_id = f"r{resulting_revision:04d}-{current_stage}"
    approved_at = utc_now()
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "user-stage-approval",
        "approval_id": approval_id,
        "lesson_id": lesson_id,
        "stage": current_stage,
        "stage_index": STAGE_INDEX[current_stage],
        "expected_revision": actual_revision,
        "resulting_revision": resulting_revision,
        "approved_at": approved_at,
        "user_id": user_id,
        "comment": comment,
        "limits": limits,
        "next_stage": next_stage,
        "inputs": inputs,
        "confirmation": confirmation,
        "confirmation_mode": confirmation_mode,
        "confirmation_stages": confirmation_stages,
        "quality_reviews": quality_reviews,
        "rebuild": rebuild,
    }
    record_name = f"{approval_id}.json"
    record_path = lesson_dir / "approvals" / record_name
    payload = exclusive_write_json(record_path, record, read_only=True)
    record_reference = {
        "approval_id": approval_id,
        "stage": current_stage,
        "revision": resulting_revision,
        "approved_at": approved_at,
        "file": f"approvals/{record_name}",
        "snapshot_sha256": sha256_bytes(payload),
    }

    new_state = state_after_approval(state, record, record_reference)
    atomic_write_json(lesson_dir / "state.json", new_state)
    emit_json(new_state)
    return 0


def state_after_invalidation(
    state: dict[str, Any], record: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    invalidated = set(record["invalidated_approval_ids"])
    previous_active = state.get("active_approval_ids")
    if previous_active is None:
        previous_active = [item["approval_id"] for item in state["approvals"]]
    new_state = dict(state)
    new_state["revision"] = record["resulting_revision"]
    new_state["invalidations"] = [*state.get("invalidations", []), reference]
    new_state["active_approval_ids"] = [
        approval_id for approval_id in previous_active if approval_id not in invalidated
    ]
    new_state.setdefault("contract_gate_enforced_after_revision", state["revision"])
    new_state["current_stage"] = record["target_stage"]
    new_state["current_stage_index"] = STAGE_INDEX[record["target_stage"]]
    new_state["status"] = "draft"
    new_state["updated_at"] = record["invalidated_at"]
    return new_state


@mutation_locked
def command_revise(args: argparse.Namespace) -> int:
    """Register replacement stage output and invalidate active downstream approvals."""

    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    state = load_state(data_home, lesson_id)
    lesson_dir = lesson_directory(data_home, lesson_id)
    actual_revision = state["revision"]
    if actual_revision != args.expected_revision:
        diagnostic = write_conflict_diagnostic(
            lesson_dir,
            lesson_id=lesson_id,
            expected_revision=args.expected_revision,
            actual_revision=actual_revision,
        )
        suffix = f"; diagnostic: {diagnostic}" if diagnostic else ""
        raise UserError(
            f"revision conflict: expected {args.expected_revision}, actual {actual_revision}{suffix}"
        )
    if state["status"] == "invalidated":
        raise UserError("cannot revise a legacy invalidated state; re-establish it first")
    integrity_issues, _ = effective_integrity_issues(state, lesson_dir, lesson_id)
    if integrity_issues:
        kinds = ", ".join(sorted({issue["kind"] for issue in integrity_issues}))
        raise UserError(
            "existing lesson integrity check failed; run verify and resolve all integrity "
            f"issues before revision ({kinds})"
        )

    target_stage = args.stage
    replayed = replay_history(state, lesson_dir)
    if target_stage not in replayed["visited_stages"]:
        raise UserError(f"cannot revise stage {target_stage!r}: the lesson has never reached it")
    if STAGE_INDEX[target_stage] > STAGE_INDEX[state["current_stage"]]:
        raise UserError(
            f"cannot revise downstream stage {target_stage!r} while current stage is "
            f"{state['current_stage']!r}"
        )
    previous_inputs = replayed["latest_stage_inputs"].get(target_stage)
    if not previous_inputs:
        raise UserError(
            f"cannot revise stage {target_stage!r}: it has no registered prior output"
        )

    user_id = args.user_id.strip()
    reason = args.reason.strip()
    if not user_id or not reason:
        raise UserError("revision requires non-empty --user-id and --reason")
    inputs = parse_role_inputs(lesson_dir, args.input)
    require_stage_roles(target_stage, inputs)
    if role_content_fingerprint(inputs) == role_content_fingerprint(previous_inputs):
        raise UserError("revision does not change stage content; no invalidation was recorded")
    previous_by_role = {item["role"]: item for item in previous_inputs}
    retained_inputs = [
        item
        for item in inputs
        if item["role"] in previous_by_role
        and (item["role"], item["path"], item["sha256"])
        == (
            previous_by_role[item["role"]]["role"],
            previous_by_role[item["role"]]["path"],
            previous_by_role[item["role"]]["sha256"],
        )
    ]
    reject_reused_stage_outputs(
        state, lesson_dir, inputs, allow_exact=retained_inputs
    )
    require_contract_gate(
        state,
        lesson_dir,
        lesson_id=lesson_id,
        stage=target_stage,
        inputs=inputs,
    )
    confirmation = validate_revision_confirmation_file(
        lesson_dir,
        args.confirmation,
        lesson_id=lesson_id,
        stage=target_stage,
        user_id=user_id,
        reason=reason,
    )
    if confirmation["path"] in {item["path"] for item in inputs}:
        raise UserError("user revision confirmation must be separate from all stage outputs")

    invalidated_ids = [
        record["approval_id"]
        for record in replayed["active_approvals"]
        if STAGE_INDEX[record["stage"]] >= STAGE_INDEX[target_stage]
    ]
    resulting_revision = actual_revision + 1
    invalidation_id = f"r{resulting_revision:04d}-invalidate-{target_stage}"
    invalidated_at = utc_now()
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "stage-invalidation",
        "invalidation_id": invalidation_id,
        "lesson_id": lesson_id,
        "target_stage": target_stage,
        "target_stage_index": STAGE_INDEX[target_stage],
        "expected_revision": actual_revision,
        "resulting_revision": resulting_revision,
        "invalidated_at": invalidated_at,
        "user_id": user_id,
        "reason": reason,
        "inputs": inputs,
        "confirmation": confirmation,
        "invalidated_approval_ids": invalidated_ids,
    }
    record_name = f"{invalidation_id}.json"
    record_path = lesson_dir / "invalidations" / record_name
    payload = exclusive_write_json(record_path, record, read_only=True)
    reference = {
        "invalidation_id": invalidation_id,
        "target_stage": target_stage,
        "revision": resulting_revision,
        "invalidated_at": invalidated_at,
        "file": f"invalidations/{record_name}",
        "snapshot_sha256": sha256_bytes(payload),
    }
    new_state = state_after_invalidation(state, record, reference)
    atomic_write_json(lesson_dir / "state.json", new_state)
    emit_json(new_state)
    return 0


@mutation_locked
def command_recover(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    lesson_dir = lesson_directory(data_home, lesson_id)
    state = load_state(data_home, lesson_id)
    if state["revision"] != args.expected_revision:
        raise UserError(
            f"revision conflict: expected {args.expected_revision}, actual {state['revision']}"
        )
    if state["status"] == "invalidated":
        raise UserError("cannot recover into an invalidated state")
    next_revision = args.expected_revision + 1
    stage = state["current_stage"]
    approval_relative = f"approvals/r{next_revision:04d}-{stage}.json"
    candidates: list[tuple[str, str, Path]] = []
    approval_path = lesson_dir / approval_relative
    if approval_path.is_file():
        candidates.append(("approval", approval_relative, approval_path))
    invalidation_dir = lesson_dir / "invalidations"
    if invalidation_dir.is_dir():
        for path in sorted(invalidation_dir.glob(f"r{next_revision:04d}-invalidate-*.json")):
            candidates.append(
                ("invalidation", path.relative_to(lesson_dir).as_posix(), path)
            )
    if not candidates:
        raise UserError(
            f"no recoverable orphan event snapshot for revision {next_revision}"
        )
    if len(candidates) != 1:
        files = ", ".join(item[1] for item in candidates)
        raise UserError(f"multiple orphan events compete for one revision: {files}")
    kind, relative_file, record_path = candidates[0]
    preexisting_issues, _ = effective_integrity_issues(
        state,
        lesson_dir,
        lesson_id,
        allowed_orphan_snapshots={relative_file},
    )
    if preexisting_issues:
        kinds = ", ".join(sorted({issue["kind"] for issue in preexisting_issues}))
        raise UserError(f"existing state is not safe to recover ({kinds})")
    payload = record_path.read_bytes()
    try:
        record = json.loads(payload)
    except json.JSONDecodeError as error:
        raise UserError(f"orphan event snapshot is invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise UserError("orphan event snapshot is not an object")
    if kind == "approval":
        reference = {
            "approval_id": record.get("approval_id"),
            "stage": record.get("stage"),
            "revision": record.get("resulting_revision"),
            "approved_at": record.get("approved_at"),
            "file": relative_file,
            "snapshot_sha256": sha256_bytes(payload),
        }
        try:
            tentative = state_after_approval(state, record, reference)
        except (KeyError, TypeError) as error:
            raise UserError(f"orphan approval snapshot is incomplete: {error}") from error
    else:
        reference = {
            "invalidation_id": record.get("invalidation_id"),
            "target_stage": record.get("target_stage"),
            "revision": record.get("resulting_revision"),
            "invalidated_at": record.get("invalidated_at"),
            "file": relative_file,
            "snapshot_sha256": sha256_bytes(payload),
        }
        try:
            tentative = state_after_invalidation(state, record, reference)
        except (KeyError, TypeError) as error:
            raise UserError(f"orphan invalidation snapshot is incomplete: {error}") from error
    recovery_issues, _ = effective_integrity_issues(
        tentative, lesson_dir, lesson_id
    )
    if recovery_issues:
        kinds = ", ".join(sorted({issue["kind"] for issue in recovery_issues}))
        raise UserError(f"orphan {kind} failed full recovery validation ({kinds})")
    atomic_write_json(lesson_dir / "state.json", tentative)
    emit_json(tentative)
    return 0


def safe_lesson_relative_path(lesson_dir: Path, raw_path: str) -> Path:
    candidate = lesson_dir / raw_path
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(lesson_dir.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise UserError(f"unsafe lesson-relative path in state: {raw_path!r}") from error
    return resolved


def collect_integrity_issues(
    state: dict[str, Any],
    lesson_dir: Path,
    lesson_id: str,
    *,
    allowed_orphan_snapshots: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return every integrity problem without mutating lesson state."""

    issues: list[dict[str, Any]] = []

    allowed_orphan_snapshots = allowed_orphan_snapshots or set()
    approvals = state["approvals"]
    invalidations = state.get("invalidations", [])
    if not isinstance(invalidations, list):
        issues.append({"kind": "invalid-invalidation-reference-list"})
        invalidations = []
    active_approval_ids = state.get("active_approval_ids")
    if active_approval_ids is not None and (
        not isinstance(active_approval_ids, list)
        or any(not isinstance(item, str) for item in active_approval_ids)
        or len(set(active_approval_ids)) != len(active_approval_ids)
    ):
        issues.append({"kind": "invalid-active-approval-id-list"})
    contract_gate_baseline = state.get(
        "contract_gate_enforced_after_revision", state["revision"]
    )
    if (
        not isinstance(contract_gate_baseline, int)
        or isinstance(contract_gate_baseline, bool)
        or contract_gate_baseline < 0
        or contract_gate_baseline > state["revision"]
    ):
        issues.append({"kind": "invalid-contract-gate-revision-baseline"})
        contract_gate_baseline = state["revision"]
    origin = state.get("origin")
    adoption = state.get("adoption")
    if "adoption" not in state:
        issues.append({"kind": "missing-adoption-field"})
    if origin == "new":
        if state.get("initial_stage") != "lesson-brief":
            issues.append({"kind": "new-lesson-initial-stage-mismatch"})
        if adoption is not None:
            issues.append({"kind": "unexpected-adoption-snapshot"})
    elif origin == "adopted":
        if state.get("initial_stage") not in ADOPTABLE_STAGES:
            issues.append({"kind": "adoption-stage-not-allowed"})
        if not isinstance(adoption, dict):
            issues.append({"kind": "missing-adoption-snapshot"})
        else:
            raw_file = adoption.get("file")
            if not isinstance(raw_file, str):
                issues.append({"kind": "invalid-adoption-reference"})
            else:
                try:
                    adoption_path = safe_lesson_relative_path(lesson_dir, raw_file)
                except UserError as error:
                    issues.append({"kind": "unsafe-adoption-snapshot", "detail": str(error)})
                else:
                    if not adoption_path.is_file():
                        issues.append({"kind": "missing-adoption-snapshot", "file": raw_file})
                    else:
                        payload = adoption_path.read_bytes()
                        if sha256_bytes(payload) != adoption.get("snapshot_sha256"):
                            issues.append({"kind": "adoption-snapshot-hash-mismatch", "file": raw_file})
                        else:
                            try:
                                record = json.loads(payload)
                            except json.JSONDecodeError:
                                record = None
                            if not isinstance(record, dict):
                                issues.append({"kind": "invalid-adoption-record", "file": raw_file})
                            else:
                                if record.get("record_type") != "legacy-adoption":
                                    issues.append({"kind": "adoption-record-type-mismatch"})
                                if record.get("lesson_id") != lesson_id:
                                    issues.append({"kind": "adoption-lesson-mismatch"})
                                if record.get("initial_stage") != state.get("initial_stage"):
                                    issues.append({"kind": "adoption-stage-mismatch"})
                                if state["revision"] == 0 and record.get("status") != state["status"]:
                                    issues.append(
                                        {
                                            "kind": "adoption-initial-status-mismatch",
                                            "expected": record.get("status"),
                                            "actual": state["status"],
                                        }
                                    )
                                state_artifacts = [
                                    {
                                        key: item.get(key)
                                        for key in ("role", "path", "sha256", "size")
                                    }
                                    for item in state.get("artifacts", [])
                                    if isinstance(item, dict)
                                ]
                                if record.get("artifacts") != state_artifacts:
                                    issues.append({"kind": "adoption-artifact-ledger-mismatch"})
    else:
        issues.append({"kind": "invalid-lesson-origin", "actual": origin})
    if state.get("current_stage_index") != STAGE_INDEX[state["current_stage"]]:
        issues.append(
            {
                "kind": "stage-index-mismatch",
                "stage": state["current_stage"],
                "expected": STAGE_INDEX[state["current_stage"]],
                "actual": state.get("current_stage_index"),
            }
        )
    artifact_roles: set[str] = set()
    artifact_paths: set[str] = set()
    for item in state["artifacts"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("role"), str)
            or not ROLE_RE.fullmatch(item["role"])
        ):
            issues.append({"kind": "invalid-registered-artifact"})
            continue
        if item["role"] in artifact_roles or item["path"] in artifact_paths:
            issues.append({"kind": "duplicate-registered-artifact-role-or-path"})
        artifact_roles.add(item["role"])
        artifact_paths.add(item["path"])
        try:
            artifact_path = safe_lesson_relative_path(lesson_dir, item["path"])
        except UserError as error:
            issues.append({"kind": "unsafe-registered-artifact", "detail": str(error)})
            continue
        if not artifact_path.is_file():
            issues.append({"kind": "missing-registered-artifact", "path": item["path"]})
            continue
        actual_hash = sha256_file(artifact_path)
        if actual_hash != item.get("sha256"):
            issues.append(
                {
                    "kind": "registered-artifact-hash-mismatch",
                    "path": item["path"],
                    "expected": item.get("sha256"),
                    "actual": actual_hash,
                }
            )
    if state["revision"] != len(approvals) + len(invalidations):
        issues.append(
            {
                "kind": "revision-ledger-mismatch",
                "revision": state["revision"],
                "approval_count": len(approvals),
                "invalidation_count": len(invalidations),
            }
        )
    if not approvals and not invalidations:
        if state["current_stage"] != state["initial_stage"]:
            issues.append(
                {
                    "kind": "unapproved-state-stage-mismatch",
                    "expected": state["initial_stage"],
                    "actual": state["current_stage"],
                }
            )
        if state["status"] == "approved":
            issues.append({"kind": "unapproved-state-approved-status"})

    referenced_snapshots: set[str] = set()
    event_records: dict[int, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    approved_paths: set[str] = set()
    approved_hashes: set[str] = set()
    prior_approval_records: dict[str, dict[str, Any]] = {}
    revision_reuse_allowances: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for invalidation_reference in invalidations:
        if not isinstance(invalidation_reference, dict):
            continue
        invalidation_revision = invalidation_reference.get("revision")
        invalidation_file = invalidation_reference.get("file")
        target_stage = invalidation_reference.get("target_stage")
        if (
            not isinstance(invalidation_revision, int)
            or isinstance(invalidation_revision, bool)
            or not isinstance(invalidation_file, str)
            or target_stage not in STAGE_INDEX
        ):
            continue
        try:
            invalidation_path = safe_lesson_relative_path(
                lesson_dir, invalidation_file
            )
        except UserError:
            continue
        if not invalidation_path.is_file():
            continue
        invalidation_payload = invalidation_path.read_bytes()
        if sha256_bytes(invalidation_payload) != invalidation_reference.get(
            "snapshot_sha256"
        ):
            continue
        try:
            invalidation_record = json.loads(invalidation_payload)
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(invalidation_record, dict)
            or invalidation_record.get("record_type") != "stage-invalidation"
            or invalidation_record.get("resulting_revision") != invalidation_revision
            or invalidation_record.get("target_stage") != target_stage
            or not isinstance(invalidation_record.get("inputs"), list)
        ):
            continue
        revision_reuse_allowances[(invalidation_revision + 1, target_stage)] = [
            item
            for item in invalidation_record["inputs"]
            if isinstance(item, dict)
        ]
    previous_approval_revision = 0
    for list_position, reference in enumerate(approvals, start=1):
        if not isinstance(reference, dict):
            issues.append({"kind": "invalid-approval-reference", "position": list_position})
            continue
        reference_revision = reference.get("revision")
        if (
            not isinstance(reference_revision, int)
            or isinstance(reference_revision, bool)
            or reference_revision < 1
        ):
            issues.append({"kind": "invalid-approval-reference-revision", "position": list_position})
            continue
        if reference_revision <= previous_approval_revision:
            issues.append({"kind": "approval-reference-order-mismatch", "position": list_position})
        previous_approval_revision = reference_revision
        raw_file = reference.get("file")
        if not isinstance(raw_file, str):
            issues.append({"kind": "missing-approval-file", "position": list_position})
            continue
        referenced_snapshots.add(raw_file)
        try:
            approval_path = safe_lesson_relative_path(lesson_dir, raw_file)
        except UserError as error:
            issues.append({"kind": "unsafe-approval-file", "detail": str(error)})
            continue
        if not approval_path.is_file():
            issues.append({"kind": "missing-approval-snapshot", "file": raw_file})
            continue
        payload = approval_path.read_bytes()
        actual_snapshot_hash = sha256_bytes(payload)
        if actual_snapshot_hash != reference.get("snapshot_sha256"):
            issues.append(
                {
                    "kind": "approval-snapshot-hash-mismatch",
                    "file": raw_file,
                    "expected": reference.get("snapshot_sha256"),
                    "actual": actual_snapshot_hash,
                }
            )
            continue
        try:
            record = json.loads(payload)
        except json.JSONDecodeError as error:
            issues.append(
                {"kind": "invalid-approval-json", "file": raw_file, "detail": str(error)}
            )
            continue
        if not isinstance(record, dict):
            issues.append({"kind": "invalid-approval-record", "file": raw_file})
            continue
        if record.get("record_type") != "user-stage-approval":
            issues.append({"kind": "approval-record-type-mismatch", "file": raw_file})
        record_stage = record.get("stage")
        if record_stage != reference.get("stage"):
            issues.append({"kind": "approval-stage-reference-mismatch", "file": raw_file})
        if record.get("approval_id") != reference.get("approval_id"):
            issues.append({"kind": "approval-id-mismatch", "file": raw_file})
        expected_approval_id = f"r{reference_revision:04d}-{record_stage}"
        if record.get("approval_id") != expected_approval_id:
            issues.append(
                {
                    "kind": "approval-id-chain-mismatch",
                    "file": raw_file,
                    "expected": expected_approval_id,
                    "actual": record.get("approval_id"),
                }
            )
        if record.get("lesson_id") != lesson_id:
            issues.append({"kind": "approval-lesson-mismatch", "file": raw_file})
        if record.get("expected_revision") != reference_revision - 1:
            issues.append(
                {
                    "kind": "approval-expected-revision-mismatch",
                    "file": raw_file,
                    "expected": reference_revision - 1,
                    "actual": record.get("expected_revision"),
                }
            )
        if record.get("resulting_revision") != reference_revision:
            issues.append(
                {
                    "kind": "approval-revision-mismatch",
                    "file": raw_file,
                    "expected": reference_revision,
                    "actual": record.get("resulting_revision"),
                }
            )
        record_next_stage = record.get("next_stage")
        if record_stage not in STAGE_INDEX:
            issues.append(
                {"kind": "unknown-approval-stage", "file": raw_file, "actual": record_stage}
            )
        elif record_next_stage not in allowed_next_stages(record_stage):
            issues.append(
                {
                    "kind": "approval-next-stage-mismatch",
                    "file": raw_file,
                    "stage": record_stage,
                    "actual": record_next_stage,
                }
            )
        record_inputs = record.get("inputs")
        if not isinstance(record_inputs, list):
            issues.append({"kind": "invalid-input-record-list", "file": raw_file})
            record_inputs = []
        if record_stage in STAGE_INDEX:
            roles = {
                item.get("role") for item in record_inputs if isinstance(item, dict)
            }
            missing_roles = sorted(
                history_required_roles(
                    record_stage, reference_revision, contract_gate_baseline
                )
                - roles
            )
            if missing_roles:
                issues.append(
                    {
                        "kind": "missing-required-input-role",
                        "file": raw_file,
                        "roles": missing_roles,
                    }
                )
            grandfathered_gate_roles = sorted(
                (
                    STAGE_REQUIRED_ROLES[record_stage]
                    - LEGACY_STAGE_REQUIRED_ROLES[record_stage]
                )
                & roles
            )
            if reference_revision <= contract_gate_baseline and grandfathered_gate_roles:
                issues.append(
                    {
                        "kind": "contract-gate-baseline-covers-enforced-approval",
                        "file": raw_file,
                        "revision": reference_revision,
                        "baseline": contract_gate_baseline,
                        "roles": grandfathered_gate_roles,
                    }
                )
        stage_roles: set[str] = set()
        stage_paths: set[str] = set()
        stage_hashes: set[str] = set()
        rebuild = record.get("rebuild")
        inherited_record: dict[str, Any] | None = None
        if rebuild is not None:
            if (
                not isinstance(rebuild, dict)
                or set(rebuild) != {"content_unchanged", "inherited_approval_id"}
                or rebuild.get("content_unchanged") is not True
                or not isinstance(rebuild.get("inherited_approval_id"), str)
            ):
                issues.append({"kind": "invalid-rebuild-reference", "file": raw_file})
            else:
                inherited_id = rebuild["inherited_approval_id"]
                inherited_record = prior_approval_records.get(inherited_id)
                if inherited_record is None:
                    issues.append({"kind": "missing-prior-rebuild-approval", "file": raw_file})
                elif inherited_id in set(state.get("active_approval_ids", [])):
                    issues.append({"kind": "rebuild-inherits-active-approval", "file": raw_file})
                elif inherited_record.get("stage") != record_stage:
                    issues.append({"kind": "rebuild-stage-mismatch", "file": raw_file})
                elif input_fingerprint(inherited_record.get("inputs", [])) != input_fingerprint(
                    record_inputs
                ):
                    issues.append({"kind": "rebuild-content-mismatch", "file": raw_file})
        for item in record_inputs:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not isinstance(item.get("role"), str)
                or not isinstance(item.get("sha256"), str)
            ):
                issues.append({"kind": "invalid-input-record", "file": raw_file})
                continue
            if (
                item["role"] in stage_roles
                or item["path"] in stage_paths
                or item["sha256"] in stage_hashes
            ):
                issues.append({"kind": "duplicate-stage-input-role-path-or-hash", "file": raw_file})
            inherited_input = (
                inherited_record is not None
                and any(
                    candidate.get("role") == item["role"]
                    and candidate.get("path") == item["path"]
                    and candidate.get("sha256") == item["sha256"]
                    for candidate in inherited_record.get("inputs", [])
                    if isinstance(candidate, dict)
                )
            )
            retained_revision_input = any(
                candidate.get("role") == item["role"]
                and candidate.get("path") == item["path"]
                and candidate.get("sha256") == item["sha256"]
                for candidate in revision_reuse_allowances.get(
                    (reference_revision, record_stage), []
                )
            )
            if (
                item["path"] in approved_paths or item["sha256"] in approved_hashes
            ) and not inherited_input and not retained_revision_input:
                issues.append({"kind": "reused-prior-stage-output", "file": raw_file})
            stage_roles.add(item["role"])
            stage_paths.add(item["path"])
            stage_hashes.add(item["sha256"])
            try:
                input_path = safe_lesson_relative_path(lesson_dir, item["path"])
            except UserError as error:
                issues.append(
                    {
                        "kind": "unsafe-approved-input",
                        "approval": reference.get("approval_id"),
                        "detail": str(error),
                    }
                )
                continue
            if not input_path.is_file():
                issues.append(
                    {
                        "kind": "missing-approved-input",
                        "approval": reference.get("approval_id"),
                        "path": item["path"],
                    }
                )
                continue
            actual_hash = sha256_file(input_path)
            if actual_hash != item.get("sha256"):
                issues.append(
                    {
                        "kind": "approved-input-hash-mismatch",
                        "approval": reference.get("approval_id"),
                        "path": item["path"],
                        "expected": item.get("sha256"),
                        "actual": actual_hash,
                    }
                )
        approved_paths.update(stage_paths)
        approved_hashes.update(stage_hashes)

        user_id = record.get("user_id")
        confirmation = record.get("confirmation")
        if not isinstance(user_id, str) or not user_id or not isinstance(confirmation, dict):
            issues.append({"kind": "missing-user-confirmation", "file": raw_file})
        else:
            confirmation_path = confirmation.get("path")
            if not isinstance(confirmation_path, str):
                issues.append({"kind": "invalid-user-confirmation-reference", "file": raw_file})
            else:
                try:
                    current_confirmation, confirmation_mode, confirmation_stages = (
                        validate_confirmation_evidence(
                        lesson_dir,
                        confirmation_path,
                        lesson_id=lesson_id,
                        stage=record_stage,
                        user_id=user_id,
                        expected_resource_choice=(
                            "handout"
                            if record_stage == "teaching-design"
                            and record_next_stage == "student-resources"
                            else (
                                "ppt-only"
                                if record_stage == "teaching-design"
                                and record_next_stage == "teaching-script"
                                else None
                            )
                        ),
                        )
                    )
                except UserError as error:
                    issues.append(
                        {"kind": "invalid-user-confirmation", "file": raw_file, "detail": str(error)}
                    )
                else:
                    if current_confirmation != confirmation:
                        issues.append({"kind": "user-confirmation-hash-mismatch", "file": raw_file})
                    if record.get("confirmation_mode", "single") != confirmation_mode:
                        issues.append({"kind": "confirmation-mode-mismatch", "file": raw_file})
                    if record.get("confirmation_stages", [record_stage]) != confirmation_stages:
                        issues.append({"kind": "confirmation-stage-scope-mismatch", "file": raw_file})
                    if confirmation_path in stage_paths:
                        issues.append({"kind": "confirmation-reuses-stage-output", "file": raw_file})

        quality_reviews = record.get("quality_reviews")
        if not isinstance(quality_reviews, list):
            issues.append({"kind": "invalid-quality-review-list", "file": raw_file})
            quality_reviews = []
        validated_reviews: list[dict[str, Any]] = []
        for review_reference in quality_reviews:
            if not isinstance(review_reference, dict) or not isinstance(
                review_reference.get("file"), str
            ):
                issues.append({"kind": "invalid-quality-review-reference", "file": raw_file})
                continue
            try:
                review_path = safe_lesson_relative_path(lesson_dir, review_reference["file"])
            except UserError as error:
                issues.append({"kind": "unsafe-quality-review", "detail": str(error)})
                continue
            if not review_path.is_file():
                issues.append({"kind": "missing-quality-review", "file": review_reference["file"]})
                continue
            review_payload = review_path.read_bytes()
            if sha256_bytes(review_payload) != review_reference.get("snapshot_sha256"):
                issues.append({"kind": "quality-review-hash-mismatch", "file": review_reference["file"]})
                continue
            try:
                review_record = json.loads(review_payload)
            except json.JSONDecodeError:
                review_record = None
            review_issues = quality_review_contract_issues(
                review_record,
                lesson_dir,
                lesson_id=lesson_id,
                stage=record_stage,
                expected_inputs=record_inputs,
                require_pass=True,
            )
            if review_issues:
                for kind in review_issues:
                    issues.append(
                        {
                            "kind": kind,
                            "file": review_reference["file"],
                        }
                    )
                continue
            reference_fields = {
                "review_id": review_record["review_id"],
                "reviewer_id": review_record["reviewer_id"],
                "route_id": review_record["route_id"],
                "run_id": review_record["run_id"],
                "report_path": review_record["report"]["path"],
            }
            if any(
                review_reference.get(key) != value
                for key, value in reference_fields.items()
            ):
                issues.append({"kind": "quality-review-reference-mismatch", "file": raw_file})
                continue
            validated_reviews.append(review_reference)
        if record_stage in DUAL_REVIEW_STAGES:
            if len(validated_reviews) != 2 or not select_independent_reviews(validated_reviews):
                issues.append({"kind": "missing-independent-online-quality-reviews", "file": raw_file})
        elif quality_reviews:
            issues.append({"kind": "unexpected-quality-review-binding", "file": raw_file})
        if reference_revision in event_records:
            issues.append({"kind": "duplicate-history-revision", "revision": reference_revision})
        elif record_stage in STAGE_INDEX and isinstance(record_inputs, list):
            event_records[reference_revision] = ("approval", reference, record)
        if isinstance(record.get("approval_id"), str):
            prior_approval_records[record["approval_id"]] = record

    approval_directory = lesson_dir / "approvals"
    if approval_directory.is_dir():
        for snapshot_path in approval_directory.glob("*.json"):
            relative = snapshot_path.relative_to(lesson_dir).as_posix()
            if relative not in referenced_snapshots and relative not in allowed_orphan_snapshots:
                issues.append({"kind": "unreferenced-approval-snapshot", "file": relative})

    referenced_invalidations: set[str] = set()
    previous_invalidation_revision = 0
    for list_position, reference in enumerate(invalidations, start=1):
        if not isinstance(reference, dict):
            issues.append({"kind": "invalid-invalidation-reference", "position": list_position})
            continue
        reference_revision = reference.get("revision")
        if (
            not isinstance(reference_revision, int)
            or isinstance(reference_revision, bool)
            or reference_revision < 1
        ):
            issues.append(
                {"kind": "invalid-invalidation-reference-revision", "position": list_position}
            )
            continue
        if reference_revision <= previous_invalidation_revision:
            issues.append(
                {"kind": "invalidation-reference-order-mismatch", "position": list_position}
            )
        previous_invalidation_revision = reference_revision
        if reference_revision <= contract_gate_baseline:
            issues.append(
                {
                    "kind": "contract-gate-baseline-covers-enforced-invalidation",
                    "position": list_position,
                    "revision": reference_revision,
                    "baseline": contract_gate_baseline,
                }
            )
        raw_file = reference.get("file")
        if not isinstance(raw_file, str):
            issues.append({"kind": "missing-invalidation-file", "position": list_position})
            continue
        referenced_invalidations.add(raw_file)
        try:
            invalidation_path = safe_lesson_relative_path(lesson_dir, raw_file)
        except UserError as error:
            issues.append({"kind": "unsafe-invalidation-file", "detail": str(error)})
            continue
        if not invalidation_path.is_file():
            issues.append({"kind": "missing-invalidation-snapshot", "file": raw_file})
            continue
        payload = invalidation_path.read_bytes()
        actual_snapshot_hash = sha256_bytes(payload)
        if actual_snapshot_hash != reference.get("snapshot_sha256"):
            issues.append(
                {
                    "kind": "invalidation-snapshot-hash-mismatch",
                    "file": raw_file,
                    "expected": reference.get("snapshot_sha256"),
                    "actual": actual_snapshot_hash,
                }
            )
            continue
        try:
            record = json.loads(payload)
        except json.JSONDecodeError as error:
            issues.append(
                {"kind": "invalid-invalidation-json", "file": raw_file, "detail": str(error)}
            )
            continue
        required_fields = {
            "schema_version",
            "record_type",
            "invalidation_id",
            "lesson_id",
            "target_stage",
            "target_stage_index",
            "expected_revision",
            "resulting_revision",
            "invalidated_at",
            "user_id",
            "reason",
            "inputs",
            "confirmation",
            "invalidated_approval_ids",
        }
        if not isinstance(record, dict) or set(record) != required_fields:
            issues.append({"kind": "invalid-invalidation-record", "file": raw_file})
            continue
        target_stage = record.get("target_stage")
        invalidation_id = record.get("invalidation_id")
        if record.get("record_type") != "stage-invalidation":
            issues.append({"kind": "invalidation-record-type-mismatch", "file": raw_file})
        if record.get("schema_version") != SCHEMA_VERSION:
            issues.append({"kind": "invalidation-schema-mismatch", "file": raw_file})
        if record.get("lesson_id") != lesson_id:
            issues.append({"kind": "invalidation-lesson-mismatch", "file": raw_file})
        if target_stage != reference.get("target_stage"):
            issues.append({"kind": "invalidation-stage-reference-mismatch", "file": raw_file})
        expected_id = f"r{reference_revision:04d}-invalidate-{target_stage}"
        if invalidation_id != reference.get("invalidation_id") or invalidation_id != expected_id:
            issues.append({"kind": "invalidation-id-mismatch", "file": raw_file})
        if record.get("expected_revision") != reference_revision - 1:
            issues.append(
                {
                    "kind": "invalidation-expected-revision-mismatch",
                    "file": raw_file,
                    "expected": reference_revision - 1,
                    "actual": record.get("expected_revision"),
                }
            )
        if record.get("resulting_revision") != reference_revision:
            issues.append({"kind": "invalidation-revision-mismatch", "file": raw_file})
        if record.get("invalidated_at") != reference.get("invalidated_at"):
            issues.append({"kind": "invalidation-time-reference-mismatch", "file": raw_file})
        if not non_blank_string(record.get("user_id")) or not non_blank_string(
            record.get("reason")
        ):
            issues.append({"kind": "missing-invalidation-author-or-reason", "file": raw_file})
        if target_stage not in STAGE_INDEX:
            issues.append({"kind": "unknown-invalidation-stage", "file": raw_file})
        elif record.get("target_stage_index") != STAGE_INDEX[target_stage]:
            issues.append({"kind": "invalidation-stage-index-mismatch", "file": raw_file})

        record_inputs = record.get("inputs")
        if not isinstance(record_inputs, list):
            issues.append({"kind": "invalid-invalidation-input-list", "file": raw_file})
            record_inputs = []
        if target_stage in STAGE_INDEX:
            roles = {
                item.get("role") for item in record_inputs if isinstance(item, dict)
            }
            missing_roles = sorted(
                history_required_roles(
                    target_stage, reference_revision, contract_gate_baseline
                )
                - roles
            )
            if missing_roles:
                issues.append(
                    {
                        "kind": "missing-invalidation-input-role",
                        "file": raw_file,
                        "roles": missing_roles,
                    }
                )
        input_roles: set[str] = set()
        input_paths: set[str] = set()
        input_hashes: set[str] = set()
        for item in record_inputs:
            if (
                not isinstance(item, dict)
                or set(item) != {"role", "path", "sha256", "size"}
                or not isinstance(item.get("role"), str)
                or not ROLE_RE.fullmatch(item["role"])
                or not isinstance(item.get("path"), str)
                or not isinstance(item.get("sha256"), str)
                or not isinstance(item.get("size"), int)
            ):
                issues.append({"kind": "invalid-invalidation-input", "file": raw_file})
                continue
            if (
                item["role"] in input_roles
                or item["path"] in input_paths
                or item["sha256"] in input_hashes
            ):
                issues.append({"kind": "duplicate-invalidation-input", "file": raw_file})
            input_roles.add(item["role"])
            input_paths.add(item["path"])
            input_hashes.add(item["sha256"])
            try:
                input_path = safe_lesson_relative_path(lesson_dir, item["path"])
            except UserError as error:
                issues.append(
                    {"kind": "unsafe-invalidation-input", "file": raw_file, "detail": str(error)}
                )
                continue
            if not input_path.is_file():
                issues.append(
                    {"kind": "missing-invalidation-input", "file": raw_file, "path": item["path"]}
                )
                continue
            if sha256_file(input_path) != item["sha256"]:
                issues.append(
                    {"kind": "invalidation-input-hash-mismatch", "file": raw_file, "path": item["path"]}
                )
            if input_path.stat().st_size != item["size"]:
                issues.append(
                    {"kind": "invalidation-input-size-mismatch", "file": raw_file, "path": item["path"]}
                )
        confirmation = record.get("confirmation")
        if not isinstance(confirmation, dict) or target_stage not in STAGE_INDEX:
            issues.append({"kind": "missing-revision-confirmation", "file": raw_file})
        else:
            confirmation_path = confirmation.get("path")
            if not isinstance(confirmation_path, str):
                issues.append(
                    {"kind": "invalid-revision-confirmation-reference", "file": raw_file}
                )
            else:
                try:
                    current_confirmation = validate_revision_confirmation_file(
                        lesson_dir,
                        confirmation_path,
                        lesson_id=lesson_id,
                        stage=target_stage,
                        user_id=record.get("user_id"),
                        reason=record.get("reason"),
                    )
                except UserError as error:
                    issues.append(
                        {
                            "kind": "invalid-revision-confirmation",
                            "file": raw_file,
                            "detail": str(error),
                        }
                    )
                else:
                    if current_confirmation != confirmation:
                        issues.append(
                            {"kind": "revision-confirmation-hash-mismatch", "file": raw_file}
                        )
                    if confirmation_path in input_paths:
                        issues.append(
                            {"kind": "revision-confirmation-reuses-stage-output", "file": raw_file}
                        )
        invalidated_ids = record.get("invalidated_approval_ids")
        if (
            not isinstance(invalidated_ids, list)
            or any(not isinstance(item, str) for item in invalidated_ids)
            or len(set(invalidated_ids)) != len(invalidated_ids)
        ):
            issues.append({"kind": "invalid-invalidated-approval-id-list", "file": raw_file})
        if reference_revision in event_records:
            issues.append({"kind": "duplicate-history-revision", "revision": reference_revision})
        elif target_stage in STAGE_INDEX:
            event_records[reference_revision] = ("invalidation", reference, record)

    invalidation_directory = lesson_dir / "invalidations"
    if invalidation_directory.is_dir():
        for snapshot_path in invalidation_directory.glob("*.json"):
            relative = snapshot_path.relative_to(lesson_dir).as_posix()
            if (
                relative not in referenced_invalidations
                and relative not in allowed_orphan_snapshots
            ):
                issues.append({"kind": "unreferenced-invalidation-snapshot", "file": relative})

    expected_revisions = set(range(1, state["revision"] + 1))
    actual_revisions = set(event_records)
    for revision in sorted(expected_revisions - actual_revisions):
        issues.append({"kind": "missing-history-revision", "revision": revision})
    for revision in sorted(actual_revisions - expected_revisions):
        issues.append({"kind": "out-of-range-history-revision", "revision": revision})

    expected_stage = state["initial_stage"]
    expected_status = "draft"
    visited_stages = {expected_stage}
    active_records: list[dict[str, Any]] = []
    latest_inputs: dict[str, list[dict[str, Any]]] = {}
    initial_roles = STAGE_REQUIRED_ROLES[expected_stage]
    initial_inputs = [
        {key: item.get(key) for key in ("role", "path", "sha256", "size")}
        for item in state.get("artifacts", [])
        if isinstance(item, dict) and item.get("role") in initial_roles
    ]
    if initial_roles.issubset({item["role"] for item in initial_inputs}):
        latest_inputs[expected_stage] = initial_inputs
    pending_stage: str | None = None
    pending_inputs: list[dict[str, Any]] | None = None

    for revision in range(1, state["revision"] + 1):
        event = event_records.get(revision)
        if event is None:
            continue
        kind, reference, record = event
        if kind == "approval":
            record_stage = record["stage"]
            if record_stage != expected_stage:
                issues.append(
                    {
                        "kind": "approval-stage-chain-mismatch",
                        "file": reference.get("file"),
                        "expected": expected_stage,
                        "actual": record_stage,
                    }
                )
            if pending_stage == record_stage and pending_inputs is not None:
                if input_fingerprint(pending_inputs) != input_fingerprint(record["inputs"]):
                    issues.append(
                        {"kind": "approval-does-not-match-revision-inputs", "file": reference.get("file")}
                    )
            if revision > contract_gate_baseline:
                for gate_issue in contract_gate_issues(
                    lesson_dir,
                    lesson_id=lesson_id,
                    stage=record_stage,
                    inputs=record["inputs"],
                    upstream_text_contract_sha256=text_contract_sha256_from_approvals(
                        active_records
                    ),
                    upstream_artifact_hashes=source_artifact_hashes_from_approvals(
                        active_records
                    ),
                    upstream_inputs=canonical_inputs_from_approvals(active_records),
                ):
                    issues.append(
                        {
                            "kind": gate_issue,
                            "file": reference.get("file"),
                        }
                    )
            active_records.append(record)
            latest_inputs[record_stage] = record["inputs"]
            next_stage = record.get("next_stage")
            if next_stage is None:
                expected_stage = record_stage
                expected_status = "approved"
            elif next_stage in STAGE_INDEX:
                expected_stage = next_stage
                expected_status = "draft"
                visited_stages.add(next_stage)
            visited_stages.add(record_stage)
            if pending_stage == record_stage:
                pending_stage = None
                pending_inputs = None
        else:
            target_stage = record["target_stage"]
            target_index = STAGE_INDEX[target_stage]
            if revision > contract_gate_baseline:
                for gate_issue in contract_gate_issues(
                    lesson_dir,
                    lesson_id=lesson_id,
                    stage=target_stage,
                    inputs=record["inputs"],
                    upstream_text_contract_sha256=text_contract_sha256_from_approvals(
                        active_records
                    ),
                    upstream_artifact_hashes=source_artifact_hashes_from_approvals(
                        active_records
                    ),
                    upstream_inputs=canonical_inputs_from_approvals(active_records),
                ):
                    issues.append(
                        {
                            "kind": gate_issue,
                            "file": reference.get("file"),
                        }
                    )
            if target_stage not in visited_stages or target_index > STAGE_INDEX[expected_stage]:
                issues.append(
                    {
                        "kind": "invalidation-target-not-reached",
                        "file": reference.get("file"),
                        "stage": target_stage,
                    }
                )
            previous_inputs = latest_inputs.get(target_stage)
            if previous_inputs is None:
                issues.append(
                    {"kind": "invalidation-target-has-no-prior-output", "file": reference.get("file")}
                )
            elif role_content_fingerprint(previous_inputs) == role_content_fingerprint(
                record["inputs"]
            ):
                issues.append(
                    {"kind": "invalidation-does-not-change-content", "file": reference.get("file")}
                )
            expected_invalidated_ids = [
                approval["approval_id"]
                for approval in active_records
                if STAGE_INDEX[approval["stage"]] >= target_index
            ]
            if record.get("invalidated_approval_ids") != expected_invalidated_ids:
                issues.append(
                    {
                        "kind": "invalidated-approval-set-mismatch",
                        "file": reference.get("file"),
                        "expected": expected_invalidated_ids,
                        "actual": record.get("invalidated_approval_ids"),
                    }
                )
            active_records = [
                approval
                for approval in active_records
                if STAGE_INDEX[approval["stage"]] < target_index
            ]
            latest_inputs[target_stage] = record["inputs"]
            expected_stage = target_stage
            expected_status = "draft"
            visited_stages.add(target_stage)
            pending_stage = target_stage
            pending_inputs = record["inputs"]

    if (approvals or invalidations) and state["current_stage"] != expected_stage:
        issues.append(
            {
                "kind": "state-stage-chain-mismatch",
                "expected": expected_stage,
                "actual": state["current_stage"],
            }
        )
    if (approvals or invalidations) and state["status"] != expected_status:
        issues.append(
            {
                "kind": "state-status-chain-mismatch",
                "expected": expected_status,
                "actual": state["status"],
            }
        )
    expected_active_ids = [record["approval_id"] for record in active_records]
    if invalidations and active_approval_ids is None:
        issues.append({"kind": "missing-active-approval-id-list"})
    elif active_approval_ids is not None and active_approval_ids != expected_active_ids:
        issues.append(
            {
                "kind": "active-approval-id-list-mismatch",
                "expected": expected_active_ids,
                "actual": active_approval_ids,
            }
        )

    return issues


def parse_utc_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def historical_review_compatibility(
    state: dict[str, Any],
    lesson_dir: Path,
    lesson_id: str,
    raw_issues: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply explicit legacy quote-gate evidence without rewriting old snapshots."""

    compatibility_dir = lesson_dir / "compatibility"
    if not compatibility_dir.is_dir():
        return list(raw_issues), []
    cutoff = parse_utc_timestamp(QUOTE_GATE_POLICY_CUTOFF)
    assert cutoff is not None
    covered: set[tuple[str, str]] = set()
    notices: list[dict[str, Any]] = []
    compatibility_issues: list[dict[str, Any]] = []
    required_keys = {
        "schema_version",
        "record_type",
        "lesson_id",
        "stage",
        "generated_at",
        "policy_cutoff",
        "compatibility_status",
        "statement",
        "approval",
        "affected_reviews",
        "retrospective_quote_check",
    }
    approval_references = {
        reference.get("file"): reference
        for reference in state.get("approvals", [])
        if isinstance(reference, dict) and isinstance(reference.get("file"), str)
    }

    for record_path in sorted(
        compatibility_dir.glob("historical-review-compatibility-*.json")
    ):
        relative_record = record_path.relative_to(lesson_dir).as_posix()
        error_detail: str | None = None
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            record = None
            error_detail = f"invalid JSON: {error}"
        generated_at = (
            parse_utc_timestamp(record.get("generated_at"))
            if isinstance(record, dict)
            else None
        )
        if error_detail is None and (
            not isinstance(record, dict)
            or set(record) != required_keys
            or record.get("schema_version") != SCHEMA_VERSION
            or record.get("record_type") != "historical-review-compatibility"
            or record.get("lesson_id") != lesson_id
            or record.get("stage") not in DUAL_REVIEW_STAGES
            or record.get("policy_cutoff") != QUOTE_GATE_POLICY_CUTOFF
            or record.get("compatibility_status") != HISTORICAL_COMPATIBILITY_STATUS
            or record.get("statement") != HISTORICAL_COMPATIBILITY_STATEMENT
            or generated_at is None
            or generated_at <= cutoff
        ):
            error_detail = "record fields or policy boundary are invalid"

        approval = record.get("approval") if isinstance(record, dict) else None
        approval_reference = None
        approval_record = None
        if error_detail is None:
            if (
                not isinstance(approval, dict)
                or set(approval) != {"path", "sha256"}
                or not non_blank_string(approval.get("path"))
                or not non_blank_string(approval.get("sha256"))
            ):
                error_detail = "approval reference is invalid"
            else:
                approval_reference = approval_references.get(approval["path"])
                try:
                    approval_path = safe_lesson_relative_path(
                        lesson_dir, approval["path"]
                    )
                    approval_payload = approval_path.read_bytes()
                    approval_record = json.loads(approval_payload)
                except (OSError, UserError, json.JSONDecodeError) as error:
                    error_detail = f"approval snapshot is unreadable: {error}"
                else:
                    digest = sha256_bytes(approval_payload)
                    approved_at = (
                        parse_utc_timestamp(approval_record.get("approved_at"))
                        if isinstance(approval_record, dict)
                        else None
                    )
                    if (
                        approval_reference is None
                        or digest != approval["sha256"]
                        or digest != approval_reference.get("snapshot_sha256")
                        or not isinstance(approval_record, dict)
                        or approval_record.get("lesson_id") != lesson_id
                        or approval_record.get("stage") != record.get("stage")
                        or approved_at is None
                        or approved_at >= cutoff
                    ):
                        error_detail = "approval snapshot does not match active history"

        quote_reference = (
            record.get("retrospective_quote_check")
            if isinstance(record, dict)
            else None
        )
        if error_detail is None:
            if not isinstance(quote_reference, dict):
                error_detail = "retrospective quote-check reference is invalid"
            else:
                try:
                    current_quote_reference = validate_quote_check_report_file(
                        lesson_dir,
                        quote_reference.get("path"),
                        lesson_id=lesson_id,
                        input_paths={
                            item.get("path")
                            for item in approval_record.get("inputs", [])
                            if isinstance(item, dict)
                        },
                    )
                    quote_path = safe_lesson_relative_path(
                        lesson_dir, quote_reference["path"]
                    )
                    quote_report = json.loads(quote_path.read_text(encoding="utf-8"))
                except (OSError, UserError, json.JSONDecodeError, TypeError) as error:
                    error_detail = f"retrospective quote-check is invalid: {error}"
                else:
                    context = quote_report.get("verification_context")
                    if (
                        current_quote_reference != quote_reference
                        or not isinstance(context, dict)
                        or context.get("kind") != "retrospective"
                        or context.get("generated_at") != record.get("generated_at")
                        or context.get("note") != HISTORICAL_COMPATIBILITY_STATEMENT
                    ):
                        error_detail = "retrospective quote-check lacks matching disclosure"

        affected_reviews = (
            record.get("affected_reviews") if isinstance(record, dict) else None
        )
        if error_detail is None:
            approval_reviews = approval_record.get("quality_reviews")
            if (
                not isinstance(affected_reviews, list)
                or len(affected_reviews) != 2
                or not isinstance(approval_reviews, list)
                or len(approval_reviews) != 2
            ):
                error_detail = "exactly two historical review references are required"
            else:
                expected_reviews = {
                    item.get("file"): item.get("snapshot_sha256")
                    for item in approval_reviews
                    if isinstance(item, dict)
                }
                declared_reviews = {
                    item.get("path"): item.get("sha256")
                    for item in affected_reviews
                    if isinstance(item, dict)
                    and set(item) == {"path", "sha256"}
                }
                if declared_reviews != expected_reviews:
                    error_detail = "historical reviews do not match the approval snapshot"

        validated_review_paths: list[str] = []
        if error_detail is None:
            routes: set[str] = set()
            for review_path_raw, expected_hash in declared_reviews.items():
                try:
                    review_path = safe_lesson_relative_path(lesson_dir, review_path_raw)
                    review_payload = review_path.read_bytes()
                    legacy_review = json.loads(review_payload)
                except (OSError, UserError, json.JSONDecodeError) as error:
                    error_detail = f"historical review is unreadable: {error}"
                    break
                reviewed_at = (
                    parse_utc_timestamp(legacy_review.get("reviewed_at"))
                    if isinstance(legacy_review, dict)
                    else None
                )
                if (
                    sha256_bytes(review_payload) != expected_hash
                    or not isinstance(legacy_review, dict)
                    or set(legacy_review)
                    != QUALITY_REVIEW_REQUIRED_KEYS - {"quote_check_report"}
                    or reviewed_at is None
                    or reviewed_at >= cutoff
                ):
                    error_detail = "historical review is not an eligible pre-gate snapshot"
                    break
                upgraded_review = dict(legacy_review)
                upgraded_review["quote_check_report"] = quote_reference
                review_issues = quality_review_contract_issues(
                    upgraded_review,
                    lesson_dir,
                    lesson_id=lesson_id,
                    stage=record["stage"],
                    expected_inputs=approval_record["inputs"],
                    require_pass=True,
                )
                route_id = legacy_review.get("route_id")
                if review_issues or not non_blank_string(route_id) or route_id in routes:
                    error_detail = "historical review fails current non-legacy checks"
                    break
                routes.add(route_id)
                validated_review_paths.append(review_path_raw)

        if error_detail is not None:
            compatibility_issues.append(
                {
                    "kind": "invalid-historical-review-compatibility",
                    "file": relative_record,
                    "detail": error_detail,
                }
            )
            continue

        for review_path_raw in validated_review_paths:
            covered.add(("quality-review-fields-mismatch", review_path_raw))
            covered.add(("missing-quote-check-report", review_path_raw))
        covered.add(
            ("missing-independent-online-quality-reviews", approval["path"])
        )
        notices.append(
            {
                "status": HISTORICAL_COMPATIBILITY_STATUS,
                "stage": record["stage"],
                "record": relative_record,
                "approval": approval["path"],
                "reviews": sorted(validated_review_paths),
                "retrospective_quote_check": quote_reference["path"],
            }
        )

    remaining = [
        issue
        for issue in raw_issues
        if (issue.get("kind"), issue.get("file")) not in covered
    ]
    remaining.extend(compatibility_issues)
    return remaining, notices


def effective_integrity_issues(
    state: dict[str, Any],
    lesson_dir: Path,
    lesson_id: str,
    *,
    allowed_orphan_snapshots: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_issues = collect_integrity_issues(
        state,
        lesson_dir,
        lesson_id,
        allowed_orphan_snapshots=allowed_orphan_snapshots,
    )
    return historical_review_compatibility(
        state, lesson_dir, lesson_id, raw_issues
    )


def command_verify(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    state = load_state(data_home, lesson_id)
    lesson_dir = lesson_directory(data_home, lesson_id)
    issues, compatibility = effective_integrity_issues(
        state, lesson_dir, lesson_id
    )
    verification_status = (
        "failed"
        if issues
        else HISTORICAL_COMPATIBILITY_STATUS
        if compatibility
        else "pass"
    )
    result = {
        "lesson_id": lesson_id,
        "revision": state["revision"],
        "ok": verification_status == "pass",
        "verification_status": verification_status,
        "issues": issues,
        "compatibility": compatibility,
    }
    emit_json(result)
    if issues:
        return 1
    return 3 if compatibility else 0


def add_data_home_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-home",
        help=f"lesson data root (or set {DATA_HOME_ENV}); never defaults to cwd",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Portable lesson-state, approval, and SHA-256 verification ledger"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check whether the configured data home is usable")
    add_data_home_argument(doctor)
    doctor.set_defaults(handler=command_doctor)

    init = subparsers.add_parser("init", help="create one lesson state")
    add_data_home_argument(init)
    init.add_argument("--lesson-id", required=True)
    init.set_defaults(handler=command_init)

    adopt = subparsers.add_parser("adopt", help="attach state to an existing legacy lesson directory")
    add_data_home_argument(adopt)
    adopt.add_argument("--lesson-id", required=True)
    adopt.add_argument("--current-stage", choices=ADOPTABLE_STAGES, required=True)
    adopt.add_argument("--status", choices=("draft", "review", "invalidated"), required=True)
    adopt.add_argument("--user-id", required=True)
    adopt.add_argument("--reason", required=True)
    adopt.add_argument("--artifact", action="append", required=True, help="ROLE=PATH; repeatable")
    adopt.set_defaults(handler=command_adopt)

    repair = subparsers.add_parser(
        "repair-adoption", help="migrate a revision-0 adopted state to a verified adoption snapshot"
    )
    add_data_home_argument(repair)
    repair.add_argument("--lesson-id", required=True)
    repair.add_argument("--expected-stage", choices=ADOPTABLE_STAGES, required=True)
    repair.add_argument(
        "--expected-status", choices=("draft", "review", "invalidated"), required=True
    )
    repair.add_argument("--user-id", required=True)
    repair.add_argument("--reason", required=True)
    repair.add_argument("--artifact", action="append", required=True, help="ROLE=PATH; repeatable")
    repair.set_defaults(handler=command_repair_adoption)

    status = subparsers.add_parser("status", help="print one lesson state")
    add_data_home_argument(status)
    status.add_argument("--lesson-id", required=True)
    status.set_defaults(handler=command_status)

    review = subparsers.add_parser("record-review", help="record immutable online quality evidence")
    add_data_home_argument(review)
    review.add_argument("--lesson-id", required=True)
    review.add_argument("--stage", choices=STAGES, required=True)
    review.add_argument("--reviewer-id", required=True)
    review.add_argument("--route-id", required=True)
    review.add_argument("--provider", required=True)
    review.add_argument("--model", required=True)
    review.add_argument("--runtime-mode", choices=("online",), required=True)
    review.add_argument("--run-id", required=True)
    review.add_argument("--persona-version", required=True)
    review.add_argument("--prompt-version", required=True)
    review.add_argument("--report", required=True, help="AI review report inside the lesson directory")
    review.add_argument(
        "--quote-check-report",
        help="passing verbatim-quote-check-report JSON; required for dual-review stages",
    )
    review.add_argument("--verdict", choices=("pass", "fail"), required=True)
    review.add_argument("--comment")
    review.add_argument("--input", action="append", required=True, help="ROLE=PATH; repeatable")
    review.set_defaults(handler=command_record_review)

    approve = subparsers.add_parser("approve", help="approve the current stage and advance")
    add_data_home_argument(approve)
    approve.add_argument("--lesson-id", required=True)
    approve.add_argument("--expected-revision", required=True, type=int)
    approve.add_argument("--user-id", required=True, help="identity from the user confirmation")
    approve.add_argument("--confirmation", required=True, help="structured user-confirmation JSON")
    approve.add_argument(
        "--rebuild-from",
        help="invalidated approval id whose unchanged ROLE=PATH hashes are reused",
    )
    approve.add_argument("--comment", help="optional approval rationale or note")
    approve.add_argument(
        "--limit",
        action="append",
        default=[],
        help="approval boundary or constraint; repeat for multiple limits",
    )
    approve.add_argument(
        "--input",
        action="append",
        required=True,
        help="approved ROLE=PATH inside the lesson directory; repeat for multiple roles",
    )
    approve.add_argument("--next-stage", choices=STAGES)
    approve.set_defaults(handler=command_approve)

    revise = subparsers.add_parser(
        "revise", help="register changed stage output and invalidate active downstream approvals"
    )
    add_data_home_argument(revise)
    revise.add_argument("--lesson-id", required=True)
    revise.add_argument("--expected-revision", required=True, type=int)
    revise.add_argument("--stage", choices=STAGES, required=True)
    revise.add_argument("--user-id", required=True)
    revise.add_argument("--reason", required=True)
    revise.add_argument("--confirmation", required=True, help="structured user revision JSON")
    revise.add_argument(
        "--input",
        action="append",
        required=True,
        help="replacement ROLE=PATH inside the lesson directory; repeat for multiple roles",
    )
    revise.set_defaults(handler=command_revise)

    recover = subparsers.add_parser("recover", help="safely attach a fully valid orphan approval")
    add_data_home_argument(recover)
    recover.add_argument("--lesson-id", required=True)
    recover.add_argument("--expected-revision", required=True, type=int)
    recover.set_defaults(handler=command_recover)

    verify = subparsers.add_parser("verify", help="verify approval snapshots and approved inputs")
    add_data_home_argument(verify)
    verify.add_argument("--lesson-id", required=True)
    verify.set_defaults(handler=command_verify)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except UserError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
