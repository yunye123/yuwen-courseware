#!/usr/bin/env python3
"""为独立课例数据目录建立个人课例索引和经验库。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


DATA_HOME_ENV = "YUWEN_DATA_HOME"
LESSON_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
BRIEF_FIELDS = {
    "title": "篇目或主题",
    "textbook": "教材出版社、册次、单元、版次",
    "lesson_type": "课型",
    "duration": "课时数与单课时长度",
    "scenario": "使用场景",
}
PRIVATE_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])/(?:Users|Volumes|home|root|tmp|private/tmp)/[^\s'\"`<>]+"),
    re.compile(
        r"(?:" + "学生" + r"姓名|" + "学生" + r"名字|" + "学员" + r"姓名|姓名)"
        r"\s*[：:]\s*[\u3400-\u9fff·]{2,12}"
    ),
    re.compile(r"(?:电话|手机|联系电话)\s*[：:]\s*(?:\+?86[- ]?)?1[3-9][0-9]{9}\b"),
    re.compile(r"(?:邮箱|电子邮箱|e-?mail)\s*[：:]\s*[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"(?:身份证|身份证号|证件号码)\s*[：:]\s*[0-9]{17}[0-9Xx]\b"),
)


class TeachingLibraryError(Exception):
    """个人教学资料不能安全归档。"""


def emit(value: Any, *, stream: Any | None = None) -> None:
    stream = stream or sys.stdout
    json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write("\n")


def resolve_data_home(raw: str | None) -> Path:
    value = raw or os.environ.get(DATA_HOME_ENV)
    if not value:
        raise TeachingLibraryError(f"请用 --data-home 指定个人教学资料目录，或设置 {DATA_HOME_ENV}")
    path = Path(value).expanduser().resolve(strict=False)
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise TeachingLibraryError("个人教学资料目录不是可用的真实文件夹")
    return path


def validate_lesson_id(value: str) -> str:
    if not LESSON_ID_RE.fullmatch(value):
        raise TeachingLibraryError("课例编号格式不正确")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_inside(base: Path, raw: str) -> tuple[Path, str]:
    candidate = base / raw
    if candidate.is_symlink():
        raise TeachingLibraryError(f"个人教学资料不能通过符号链接读取：{raw}")
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(base.resolve(strict=True)).as_posix()
    except (OSError, ValueError) as error:
        raise TeachingLibraryError(f"文件缺失或越出课例目录：{raw}") from error
    if not resolved.is_file():
        raise TeachingLibraryError(f"不是普通文件：{raw}")
    return resolved, relative


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_brief(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {key: "" for key in BRIEF_FIELDS}
    text = path.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for key, label in BRIEF_FIELDS.items():
        match = re.search(rf"^- {re.escape(label)}[：:]\s*(.*)$", text, re.MULTILINE)
        result[key] = match.group(1).strip() if match else ""
    return result


def load_state(path: Path, expected_id: str) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TeachingLibraryError(f"无法读取课例状态：{expected_id}") from error
    if state.get("lesson_id") != expected_id:
        raise TeachingLibraryError(f"课例状态编号不一致：{expected_id}")
    return state


def experience_records(data_home: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    root = data_home / "library" / "个人经验"
    if not root.is_dir():
        return result
    for path in sorted(root.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        lesson_id = value.get("lesson_id")
        if isinstance(lesson_id, str):
            result.setdefault(lesson_id, []).append(value)
    return result


def build_index(data_home: Path) -> dict[str, Any]:
    lessons_root = data_home / "lessons"
    records = experience_records(data_home)
    entries: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    if lessons_root.is_dir():
        for lesson_dir in sorted(lessons_root.iterdir(), key=lambda item: item.name):
            if not lesson_dir.is_dir() or lesson_dir.is_symlink() or not LESSON_ID_RE.fullmatch(lesson_dir.name):
                continue
            state_path = lesson_dir / "state.json"
            if not state_path.is_file():
                issues.append({"lesson_id": lesson_dir.name, "kind": "missing-state"})
                continue
            try:
                state = load_state(state_path, lesson_dir.name)
                brief = parse_brief(lesson_dir / "00-lesson-brief.md")
            except (TeachingLibraryError, UnicodeDecodeError) as error:
                issues.append({"lesson_id": lesson_dir.name, "kind": "invalid-lesson", "detail": str(error)})
                continue
            reflections = sorted(
                path.relative_to(lesson_dir).as_posix()
                for path in lesson_dir.glob("*课后反思*.md")
                if path.is_file() and not path.is_symlink()
            )
            entries.append(
                {
                    "lesson_id": lesson_dir.name,
                    **brief,
                    "current_stage": state.get("current_stage"),
                    "status": state.get("status"),
                    "revision": state.get("revision"),
                    "created_at": state.get("created_at"),
                    "updated_at": state.get("updated_at"),
                    "reflection_files": reflections,
                    "personal_experience_count": len(records.get(lesson_dir.name, [])),
                }
            )
    return {
        "schema_version": "yuwen-courseware.personal-teaching-index/v1",
        "lesson_count": len(entries),
        "experience_count": sum(len(values) for values in records.values()),
        "lessons": entries,
        "issues": issues,
        "ok": len(issues) == 0,
    }


def command_rebuild_index(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    value = build_index(data_home)
    target = data_home / "library" / "课例索引.json"
    atomic_write_json(target, value)
    emit({**value, "index_file": "library/课例索引.json"})
    return 0 if value["ok"] else 2


def command_status(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    value = build_index(data_home)
    emit(value)
    return 0 if value["ok"] else 2


def validate_confirmation(path: Path, lesson_id: str, user_id: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TeachingLibraryError("无法读取老师的经验库确认记录") from error
    required = {
        "record_type": "user-personal-library-confirmation",
        "lesson_id": lesson_id,
        "user_id": user_id,
        "decision": "promote",
    }
    if any(value.get(key) != expected for key, expected in required.items()):
        raise TeachingLibraryError("经验库确认记录与本次课例、老师或决定不一致")
    if not isinstance(value.get("confirmed_at"), str) or not value["confirmed_at"]:
        raise TeachingLibraryError("经验库确认记录缺少确认时间")
    if not isinstance(value.get("message_excerpt"), str) or not value["message_excerpt"].strip():
        raise TeachingLibraryError("经验库确认记录缺少老师真实决定摘要")
    return value


def scan_private_text(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise TeachingLibraryError(f"个人经验文件必须是 UTF-8 文本：{path.name}") from error
    return [f"privacy-pattern-{index + 1}" for index, pattern in enumerate(PRIVATE_PATTERNS) if pattern.search(text)]


def command_promote(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    lesson_id = validate_lesson_id(args.lesson_id)
    lesson_dir = data_home / "lessons" / lesson_id
    if lesson_dir.is_symlink() or not lesson_dir.is_dir():
        raise TeachingLibraryError("课例目录不存在")
    load_state(lesson_dir / "state.json", lesson_id)
    confirmation_path, confirmation_relative = relative_inside(lesson_dir, args.confirmation)
    reflection_path, reflection_relative = relative_inside(lesson_dir, args.reflection)
    card_path, card_relative = relative_inside(lesson_dir, args.card)
    confirmation = validate_confirmation(confirmation_path, lesson_id, args.user_id)
    privacy_issues = sorted(set(scan_private_text(reflection_path) + scan_private_text(card_path)))
    if privacy_issues:
        raise TeachingLibraryError("课后反思或经验卡含有需要先处理的个人信息或本机路径")
    card_text = card_path.read_text(encoding="utf-8")
    required_checks = (
        "- [x] 不含学生姓名、学号、联系方式或可识别个人的信息",
        "- [x] 仅加入当前老师的个人经验库",
        "- [x] 老师已明确同意加入个人经验库",
    )
    if any(item not in card_text for item in required_checks):
        raise TeachingLibraryError("个人经验卡的隐私与授权三项确认尚未全部勾选")
    payload = {
        "schema_version": "yuwen-courseware.personal-experience/v1",
        "lesson_id": lesson_id,
        "user_id": args.user_id,
        "confirmed_at": confirmation["confirmed_at"],
        "confirmation": {
            "path": f"lessons/{lesson_id}/{confirmation_relative}",
            "sha256": sha256_file(confirmation_path),
        },
        "reflection": {
            "path": f"lessons/{lesson_id}/{reflection_relative}",
            "sha256": sha256_file(reflection_path),
        },
        "card": {
            "path": f"lessons/{lesson_id}/{card_relative}",
            "sha256": sha256_file(card_path),
        },
    }
    record_digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    target = data_home / "library" / "个人经验" / f"{lesson_id}-{record_digest[:12]}.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != payload:
            raise TeachingLibraryError("同名个人经验记录已经存在但内容不同")
    else:
        atomic_write_json(target, payload)
    index = build_index(data_home)
    atomic_write_json(data_home / "library" / "课例索引.json", index)
    emit({"ok": True, "record": target.relative_to(data_home).as_posix(), "index_file": "library/课例索引.json"})
    return 0


def command_search(args: argparse.Namespace) -> int:
    data_home = resolve_data_home(args.data_home)
    query = args.query.strip().casefold()
    if not query:
        raise TeachingLibraryError("检索词不能为空")
    hits: list[dict[str, Any]] = []
    for records in experience_records(data_home).values():
        for record in records:
            raw_path = record.get("card", {}).get("path")
            if not isinstance(raw_path, str):
                continue
            try:
                card_path, relative = relative_inside(data_home, raw_path)
                text = card_path.read_text(encoding="utf-8")
            except (TeachingLibraryError, UnicodeDecodeError):
                continue
            if query in text.casefold():
                hits.append(
                    {
                        "lesson_id": record.get("lesson_id"),
                        "card": relative,
                        "confirmed_at": record.get("confirmed_at"),
                        "preview": " ".join(text.split())[:500],
                    }
                )
    emit({"query": args.query.strip(), "hit_count": len(hits), "hits": hits[: args.limit]})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="建立可迁移的个人课例索引与教学经验库")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler, help_text in (
        ("status", command_status, "只读查看个人课例与经验库状态"),
        ("rebuild-index", command_rebuild_index, "重建中文课例索引"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--data-home")
        command.set_defaults(handler=handler)
    promote = subparsers.add_parser("promote", help="经老师确认后把课后经验加入个人经验库")
    promote.add_argument("--data-home")
    promote.add_argument("--lesson-id", required=True)
    promote.add_argument("--user-id", required=True)
    promote.add_argument("--confirmation", required=True)
    promote.add_argument("--reflection", required=True)
    promote.add_argument("--card", required=True)
    promote.set_defaults(handler=command_promote)
    search = subparsers.add_parser("search", help="检索已经确认的个人教学经验")
    search.add_argument("--data-home")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(handler=command_search)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "limit", 1) < 1 or getattr(args, "limit", 1) > 50:
        parser.error("--limit 必须在 1 到 50 之间")
    try:
        return args.handler(args)
    except TeachingLibraryError as error:
        emit({"ok": False, "error": str(error)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
