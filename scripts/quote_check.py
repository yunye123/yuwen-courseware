#!/usr/bin/env python3
"""对课例的逐字引文清单做确定性原文比对。"""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence


class UserError(Exception):
    """可操作的输入错误。"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_text(value: str) -> str:
    """只忽略排版空白，不改写异体字、标点或其他字符。"""

    return "".join(character for character in value if not character.isspace())


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UserError(f"逐字校对清单必须是 UTF-8 JSON：{error}") from error
    if not isinstance(value, dict):
        raise UserError("逐字校对清单必须是 JSON 对象")
    return value


def resolve_source(checklist_dir: Path, raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise UserError("原文 path 必须是非空相对路径")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise UserError("原文必须位于逐字校对清单目录内（inside the checklist directory）")
    root = checklist_dir.resolve(strict=True)
    try:
        resolved = (root / candidate).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise UserError(
            "原文必须位于逐字校对清单目录内（inside the checklist directory）"
        ) from error
    if not resolved.is_file():
        raise UserError(f"原文不是可读文本文件：{raw_path}")
    return resolved


def closest_excerpt(source: str, quote: str) -> str:
    """从原文中找到与引文最可能对应的定长片段。"""

    if not source:
        return ""
    if len(quote) >= len(source):
        return source
    matcher = SequenceMatcher(None, source, quote, autojunk=False)
    candidates: set[int] = {0, len(source) - len(quote)}
    for block in matcher.get_matching_blocks():
        start = max(0, min(len(source) - len(quote), block.a - block.b))
        candidates.update(
            max(0, min(len(source) - len(quote), start + offset))
            for offset in (-2, -1, 0, 1, 2)
        )

    for anchor_length in range(min(12, len(quote)), 1, -1):
        prefix = quote[:anchor_length]
        found = source.find(prefix)
        if found >= 0:
            while found >= 0:
                candidates.add(min(found, len(source) - len(quote)))
                found = source.find(prefix, found + 1)
            break
    for anchor_length in range(min(12, len(quote)), 1, -1):
        suffix = quote[-anchor_length:]
        found = source.find(suffix)
        if found >= 0:
            while found >= 0:
                start = found + anchor_length - len(quote)
                candidates.add(max(0, min(len(source) - len(quote), start)))
                found = source.find(suffix, found + 1)
            break

    def score(start: int) -> tuple[int, float, int]:
        excerpt = source[start : start + len(quote)]
        mismatches = sum(actual != expected for actual, expected in zip(quote, excerpt))
        ratio = SequenceMatcher(None, quote, excerpt, autojunk=False).ratio()
        return -mismatches, ratio, -start

    best_start = max(candidates, key=score)
    return source[best_start : best_start + len(quote)]


def character_differences(actual: str, expected: str) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    matcher = SequenceMatcher(None, actual, expected, autojunk=False)
    for operation, actual_start, actual_end, expected_start, expected_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        actual_text = actual[actual_start:actual_end]
        expected_text = expected[expected_start:expected_end]
        width = max(len(actual_text), len(expected_text))
        for offset in range(width):
            differences.append(
                {
                    "position": actual_start + offset + 1,
                    "actual": actual_text[offset] if offset < len(actual_text) else "",
                    "expected": expected_text[offset] if offset < len(expected_text) else "",
                }
            )
    return differences


def validate_checklist(value: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if value.get("schema_version") != "1.0" or value.get("record_type") != "verbatim-quote-checklist":
        raise UserError(
            "清单必须声明 schema_version=1.0 且 record_type=verbatim-quote-checklist"
        )
    lesson_id = value.get("lesson_id")
    sources = value.get("sources")
    quotes = value.get("quotes")
    if not isinstance(lesson_id, str) or not lesson_id.strip():
        raise UserError("清单 lesson_id 不得为空")
    if not isinstance(sources, list) or not sources:
        raise UserError("清单 sources 必须是非空数组")
    if not isinstance(quotes, list) or not quotes:
        raise UserError("清单 quotes 必须是非空数组")
    if any(not isinstance(item, dict) for item in sources + quotes):
        raise UserError("sources 和 quotes 的每一项必须是 JSON 对象")
    source_ids = [item.get("source_id") for item in sources]
    quote_ids = [item.get("quote_id") for item in quotes]
    if any(not isinstance(item, str) or not item.strip() for item in source_ids):
        raise UserError("每个 source_id 必须是非空字符串")
    if len(source_ids) != len(set(source_ids)):
        raise UserError("source_id 不得重复")
    if any(not isinstance(item, str) or not item.strip() for item in quote_ids):
        raise UserError("每个 quote_id 必须是非空字符串")
    if len(quote_ids) != len(set(quote_ids)):
        raise UserError("quote_id 不得重复")
    return lesson_id, sources, quotes


def build_report(checklist: Path) -> dict[str, Any]:
    value = load_json_object(checklist)
    lesson_id, source_items, quote_items = validate_checklist(value)
    verification_context = value.get("verification_context")
    if verification_context is not None:
        if (
            not isinstance(verification_context, dict)
            or set(verification_context) != {"kind", "generated_at", "note"}
            or verification_context.get("kind") != "retrospective"
            or not isinstance(verification_context.get("generated_at"), str)
            or not verification_context["generated_at"].strip()
            or not isinstance(verification_context.get("note"), str)
            or "不冒充审批当时存在" not in verification_context["note"]
        ):
            raise UserError(
                "追溯核对上下文必须声明 kind=retrospective、生成时间和不冒充原审批的说明"
            )
    source_texts: dict[str, str] = {}
    source_records: list[dict[str, Any]] = []
    for item in source_items:
        source_id = item["source_id"]
        source_path = resolve_source(checklist.parent, item.get("path"))
        try:
            raw_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise UserError(f"原文必须是 UTF-8 文本：{item.get('path')}：{error}") from error
        source_texts[source_id] = compact_text(raw_text)
        source_records.append(
            {
                "source_id": source_id,
                "label": item.get("label") if isinstance(item.get("label"), str) else source_id,
                "path": Path(item["path"]).as_posix(),
                "sha256": sha256_file(source_path),
            }
        )

    results: list[dict[str, Any]] = []
    differences: list[dict[str, Any]] = []
    for item in quote_items:
        source_id = item.get("source_id")
        raw_quote = item.get("text")
        if source_id not in source_texts:
            raise UserError(f"引文 {item['quote_id']} 引用了未登记的 source_id：{source_id}")
        if not isinstance(raw_quote, str) or not compact_text(raw_quote):
            raise UserError(f"引文 {item['quote_id']} 的 text 不得为空")
        quote = compact_text(raw_quote)
        source = source_texts[source_id]
        passed = quote in source
        result: dict[str, Any] = {
            "quote_id": item["quote_id"],
            "source_id": source_id,
            "status": "passed" if passed else "different",
            "text": quote,
        }
        if not passed:
            expected = closest_excerpt(source, quote)
            result["expected_excerpt"] = expected
            result["character_differences"] = character_differences(quote, expected)
            differences.append(result)
        results.append(result)

    passed_count = sum(item["status"] == "passed" for item in results)
    report = {
        "schema_version": "1.0",
        "record_type": "verbatim-quote-check-report",
        "lesson_id": lesson_id,
        "checklist": {
            "path": checklist.name,
            "sha256": sha256_file(checklist),
        },
        "sources": source_records,
        "ok": not differences,
        "summary": {
            "passed": passed_count,
            "different": len(differences),
            "total": len(results),
        },
        "results": results,
        "differences": differences,
    }
    if verification_context is not None:
        report["verification_context"] = verification_context
    return report


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="逐字引文与使用者提供原文的确定性比对")
    parser.add_argument("--checklist", required=True, help="逐字校对清单 JSON")
    parser.add_argument("--output", help="可选：将报告写入指定 JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checklist = Path(args.checklist).expanduser().resolve(strict=False)
    try:
        if not checklist.is_file():
            raise UserError(f"逐字校对清单不存在：{checklist}")
        report = build_report(checklist)
        payload = json_text(report)
        if args.output:
            output = Path(args.output).expanduser().resolve(strict=False)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
        sys.stdout.write(payload)
        return 0 if report["ok"] else 1
    except UserError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
