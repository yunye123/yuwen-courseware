#!/usr/bin/env python3
"""将冻结的内部 Markdown 确定性转换为教师可见版。

转换只允许四类白名单操作：删除文件头内部元数据、删除明确标记的内部注释、
删除指定治理章节、将稳定内部编号投影为中文表述。其余教学文字逐字保留。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Sequence


SCHEMA_VERSION = "yuwen-courseware.teacher-view-filter/v2"
IDENTIFIER_LABELS = {
    "OBJ": "目标",
    "TASK": "任务",
    "ASM": "评价",
    "ANS": "参考答案",
    "SCRIPT": "讲稿",
    "SLIDE": "页面",
    "SRC": "资料",
    "CLM": "结论",
    "MAT": "材料",
}
IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(OBJ|TASK|ASM|ANS|SCRIPT|SLIDE|SRC|CLM|MAT)-0*([1-9][0-9]*)"
    r"((?:[/／]0*[1-9][0-9]*)*)(?![A-Za-z0-9_-])"
)
FIELD_LABELS = {
    "objective_id": "教学目标",
    "task_id": "课堂任务",
    "assessment_id": "评价依据",
    "answer_id": "参考答案",
    "script_id": "讲稿位置",
    "slide_id": "课件页面",
    "source_id": "资料出处",
    "claim_id": "研究结论",
    "material_id": "学习材料",
    "id": "序号",
}
FIELD_LABEL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(sorted(FIELD_LABELS, key=len, reverse=True)) + r")(s)?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
LOCALIZED_FIELD_LABELS = {
    "来源/任务 序号": "资料出处/课堂任务",
    "来源/任务编号": "资料出处/课堂任务",
    "答案集编号": "参考答案",
    "答案编号": "参考答案",
    "来源编号": "资料出处",
    "论断编号": "研究结论",
    "目标编号": "教学目标",
    "任务编号": "课堂任务",
    "素材编号": "学习材料",
    "评价编号": "评价依据",
}
LOCALIZED_FIELD_LABEL_PATTERN = re.compile(
    "|".join(re.escape(label) for label in sorted(LOCALIZED_FIELD_LABELS, key=len, reverse=True))
)
HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*(?:\r?\n)?$")
FENCE_PATTERN = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
GOVERNANCE_SECTION_TITLES = frozenset(
    {
        "下游稳定编号分配表",
        "启动确认",
        "检索通道日志",
        "研究充分性裁决",
        "质量审查摘要",
        "质量审查记录",
        "双路评审摘要",
        "审批记录",
        "治理记录",
        "技术校验摘要",
        "学生版检查",
        "答案核查",
        "讲稿检查",
        "文字稿检查",
        "内部检查（不进入教师交付文件夹）",
    }
)
SYSTEM_METADATA_LABELS = frozenset(
    {
        "lesson_id",
        "status",
        "package_status",
        "external_ppt_status",
        "使用者批准",
        "设计合同版本",
        "修订版本",
        "重批版本",
        "版本",
        "课例编号",
        "当前状态",
        "当前进度",
        "课件包状态",
        "外部课件状态",
        "输入版本与校验值",
        "跨文件绑定",
        "编号警示",
        "制作要求",
    }
)
TEACHER_FORBIDDEN_TERMS = (
    "文本合同",
    "技术冻结",
    "哈希绑定",
    "占位语检测",
    "权利状态",
    "系统一致性合同",
    "文件哈希",
    "批准记录",
    "校验值",
    "SLIDE-",
    "启动确认",
    "批准人",
    "批准时间",
    "检索通道日志",
    "研究充分性裁决",
    "已批准教学设计",
    "猜页码",
    "复制以上页面块",
    "严禁出现教师答案",
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
    r"(?:软件|课件|PPTX?|PowerPoint|WPS|Office|LibreOffice)"
    r"[^\r\n。；;]{0,24}(?:兼容(?:性)?|适配|打开(?:方式)?|版本(?:要求)?|"
    r"字体(?:替换|缺失)|错位|显示异常|播放异常|换行)|"
    r"(?:兼容(?:性)?|适配|打开方式|版本要求)"
    r"[^\r\n。；;]{0,24}(?:PPTX?|PowerPoint|WPS|Office|LibreOffice)",
    re.IGNORECASE,
)
BARE_INTERNAL_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:OBJ|TASK|ASM|ANS|SCRIPT|SLIDE|SRC|CLM|MAT)(?![A-Za-z0-9_-])"
)
NUMBERED_FIELD_RE = re.compile(
    r"(?:来源|论断|目标|任务|素材|评价|答案集)[ \t]*编号"
)
INTERNAL_TABLE_HEADER_TOKENS = frozenset(
    {
        "objective_id",
        "task_id",
        "assessment_id",
        "answer_id",
        "script_id",
        "slide_id",
        "source_id",
        "claim_id",
        "material_id",
        "id",
    }
)
INTERNAL_TABLE_HEADER_LABELS = frozenset(
    {
        "来源/任务id",
        "来源/任务编号",
        "来源编号/论断编号",
        "来源编号",
        "论断编号",
        "目标编号",
        "任务编号",
        "素材编号",
        "评价编号",
        "答案编号",
        "答案集编号",
        "讲稿编号",
        "页面编号",
    }
)
TEACHER_VISIBLE_PATTERN_LABELS = (
    (BACKEND_ARTIFACT_RE, "后台文件或检查说明"),
    (BACKEND_PROCESS_RE, "后台制作或检查记录"),
    (SOFTWARE_COMPATIBILITY_RE, "软件兼容提醒"),
    (BARE_INTERNAL_ID_RE, "内部编号缩写"),
    (NUMBERED_FIELD_RE, "内部编号标签"),
)
HEADING_NUMBER_PREFIX_PATTERN = re.compile(
    r"^(?:(?:[一二三四五六七八九十百]+|[0-9]+)[、.．]\s*|（(?:[一二三四五六七八九十百]+|[0-9]+)）\s*)"
)
CHINESE_H2_PATTERN = re.compile(
    r"^(##[ \t]+)([一二三四五六七八九十百]+)([、.．])([^\r\n]*)(\r?\n)?$"
)
INTERNAL_INSTRUCTION_PATTERNS = (
    re.compile(r"^[ \t]*>[ \t]*严禁出现教师答案、评分点或答案提示。?[ \t]*$"),
    re.compile(r"^[ \t]*>[ \t]*一个评价编号只对应一个答案集编号。.*$"),
    re.compile(r"^[ \t]*>[ \t]*页码提醒：.*猜页码。?[ \t]*$"),
    re.compile(r"^[ \t]*复制以上页面块直至全课结束。?[ \t]*$"),
    re.compile(r"^[ \t]*-[ \t]*评价编号：ASM-[0-9]+[ \t]*$"),
)
INTERNAL_COMMENT_STARTS = (
    "<!-- YUWEN_INTERNAL_MAPPING",
    "<!-- YUWEN_AUTHORING_NOTE",
)


class FilterError(RuntimeError):
    """教师版转换无法安全完成。"""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def chinese_number(value: int) -> str:
    if value <= 0 or value > 9999:
        raise FilterError("内部编号数字必须在 1—9999 之间")
    digits = "零一二三四五六七八九"
    units = ((1000, "千"), (100, "百"), (10, "十"), (1, ""))
    result: list[str] = []
    pending_zero = False
    remainder = value
    for unit_value, unit_label in units:
        digit, remainder = divmod(remainder, unit_value)
        if digit:
            if pending_zero and result:
                result.append("零")
            if not (unit_value == 10 and digit == 1 and not result):
                result.append(digits[digit])
            result.append(unit_label)
            pending_zero = False
        elif result and remainder:
            pending_zero = True
    return "".join(result)


def metadata_quote(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped.startswith(">"):
        return False
    content = stripped[1:].strip().strip("*_`").strip()
    if content.startswith(("【模拟测试声明】", "模拟测试声明", "模拟声明")):
        return True
    label = re.split(r"[：:]", content, maxsplit=1)[0].strip()
    if label in SYSTEM_METADATA_LABELS or label.startswith(("上游", "跨文件绑定", "编号警示")):
        return True
    return ("哈希" in label or "校验值" in label) and label.startswith(
        ("输入", "开课单", "证据包", "教学设计", "学案/答案", "文本包", "PPT", "批准文字稿", "返回 PPT")
    )


def header_metadata_indexes(lines: list[str]) -> list[int]:
    first_content = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_content is None or not re.match(r"^#(?:\s|$)", lines[first_content]):
        return []
    indexes: list[int] = []
    index = first_content + 1
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.lstrip().startswith(">"):
            if metadata_quote(line):
                indexes.append(index)
            index += 1
            continue
        break
    return indexes


def normalized_heading_title(title: str) -> str:
    return HEADING_NUMBER_PREFIX_PATTERN.sub("", title.strip()).strip()


def governance_ranges(lines: list[str]) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    index = 0
    active_fence: str | None = None
    while index < len(lines):
        fence = FENCE_PATTERN.match(lines[index])
        if fence:
            marker = fence.group(1)[0]
            if active_fence is None:
                active_fence = marker
            elif active_fence == marker:
                active_fence = None
            index += 1
            continue
        heading = None if active_fence else HEADING_PATTERN.match(lines[index])
        normalized_title = (
            "" if heading is None else normalized_heading_title(heading.group(2))
        )
        if heading is None or normalized_title not in GOVERNANCE_SECTION_TITLES:
            index += 1
            continue
        level = len(heading.group(1))
        title = normalized_title
        end = index + 1
        nested_fence: str | None = None
        while end < len(lines):
            nested = FENCE_PATTERN.match(lines[end])
            if nested:
                marker = nested.group(1)[0]
                if nested_fence is None:
                    nested_fence = marker
                elif nested_fence == marker:
                    nested_fence = None
                end += 1
                continue
            candidate = None if nested_fence else HEADING_PATTERN.match(lines[end])
            if candidate is not None and len(candidate.group(1)) <= level:
                break
            end += 1
        ranges.append((index, end, title))
        index = end
    return ranges


def internal_comment_ranges(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return explicitly marked internal HTML comment blocks.

    Ordinary lesson-content comments are preserved. Only project-owned markers are
    removable so the filter cannot silently erase teacher-authored material.
    """

    ranges: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].lstrip()
        marker = next(
            (value for value in INTERNAL_COMMENT_STARTS if stripped.startswith(value)),
            None,
        )
        if marker is None:
            index += 1
            continue
        end = index
        while end < len(lines) and "-->" not in lines[end]:
            end += 1
        if end >= len(lines):
            raise FilterError(f"内部注释没有闭合：第 {index + 1} 行")
        ranges.append((index, end + 1, marker.removeprefix("<!-- ")))
        index = end + 1
    return ranges


def internal_instruction_indexes(lines: list[str]) -> list[int]:
    indexes: list[int] = []
    active_fence: str | None = None
    for index, line in enumerate(lines):
        fence = FENCE_PATTERN.match(line)
        if fence:
            marker = fence.group(1)[0]
            if active_fence is None:
                active_fence = marker
            elif active_fence == marker:
                active_fence = None
            continue
        if active_fence is not None:
            continue
        value = line.rstrip("\r\n")
        if any(pattern.fullmatch(value) for pattern in INTERNAL_INSTRUCTION_PATTERNS):
            indexes.append(index)
    return indexes


def collapse_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        if not line.strip() and result and not result[-1].strip():
            continue
        result.append(line)
    while result and not result[0].strip():
        result.pop(0)
    return result


def split_markdown_table_row(line: str) -> tuple[list[str], str] | None:
    value = line.rstrip("\r\n")
    newline = line[len(value) :]
    if not value.lstrip().startswith("|") or not value.rstrip().endswith("|"):
        return None
    cells = re.split(r"(?<!\\)\|", value.strip()[1:-1])
    return cells, newline


def is_markdown_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r"[ \t]*:?-{3,}:?[ \t]*", cell) is not None for cell in cells
    )


def is_internal_table_header(value: str) -> bool:
    normalized = value.strip().strip("*_`").lower()
    compact = re.sub(r"[ \t]", "", normalized)
    if compact in INTERNAL_TABLE_HEADER_LABELS:
        return True
    tokens = [token for token in re.split(r"[ /／,+＋，]+", normalized) if token]
    return bool(tokens) and all(token in INTERNAL_TABLE_HEADER_TOKENS for token in tokens)


def drop_internal_table_columns(
    lines: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Remove Markdown columns used only for backend lineage."""

    result = list(lines)
    dropped: list[dict[str, Any]] = []
    index = 0
    active_fence: str | None = None
    while index + 1 < len(result):
        fence = FENCE_PATTERN.match(result[index])
        if fence:
            marker = fence.group(1)[0]
            if active_fence is None:
                active_fence = marker
            elif active_fence == marker:
                active_fence = None
            index += 1
            continue
        if active_fence is not None:
            index += 1
            continue
        header = split_markdown_table_row(result[index])
        separator = split_markdown_table_row(result[index + 1])
        if (
            header is None
            or separator is None
            or len(header[0]) != len(separator[0])
            or not is_markdown_separator_row(separator[0])
        ):
            index += 1
            continue
        drop_indexes = [
            cell_index
            for cell_index, cell in enumerate(header[0])
            if is_internal_table_header(cell)
        ]
        if not drop_indexes:
            index += 2
            continue
        keep_indexes = [
            cell_index for cell_index in range(len(header[0])) if cell_index not in drop_indexes
        ]
        if not keep_indexes:
            raise FilterError(f"第 {index + 1} 行表格只包含内部编号列")
        end = index
        while end < len(result):
            parsed = split_markdown_table_row(result[end])
            if parsed is None or len(parsed[0]) != len(header[0]):
                break
            cells, newline = parsed
            result[end] = (
                "| "
                + " | ".join(cells[cell].strip() for cell in keep_indexes)
                + " |"
                + newline
            )
            end += 1
        dropped.append(
            {
                "start_line": index + 1,
                "end_line": end,
                "headers": [header[0][cell].strip() for cell in drop_indexes],
            }
        )
        index = end
    return result, dropped


def renumber_chinese_h2_sections(lines: list[str]) -> list[str]:
    result: list[str] = []
    active_fence: str | None = None
    section_number = 0
    for line in lines:
        fence = FENCE_PATTERN.match(line)
        if fence:
            marker = fence.group(1)[0]
            if active_fence is None:
                active_fence = marker
            elif active_fence == marker:
                active_fence = None
            result.append(line)
            continue
        heading = None if active_fence is not None else CHINESE_H2_PATTERN.match(line)
        if heading is None:
            result.append(line)
            continue
        section_number += 1
        newline = heading.group(5) or ""
        result.append(
            f"{heading.group(1)}{chinese_number(section_number)}{heading.group(3)}"
            f"{heading.group(4)}{newline}"
        )
    return result


def replace_identifier(match: re.Match[str], counts: dict[str, int]) -> str:
    kind = match.group(1)
    numbers = [int(match.group(2))]
    numbers.extend(int(value) for value in re.findall(r"[1-9][0-9]*", match.group(3)))
    counts[kind] = counts.get(kind, 0) + len(numbers)
    if kind == "SLIDE":
        return "/".join(f"第{chinese_number(number)}页" for number in numbers)
    return "/".join(
        f"{IDENTIFIER_LABELS[kind]}{chinese_number(number)}" for number in numbers
    )


def replace_field_label(match: re.Match[str], counts: dict[str, int]) -> str:
    label = match.group(1).lower()
    counts[label] = counts.get(label, 0) + 1
    return FIELD_LABELS[label]


def replace_localized_field_label(match: re.Match[str], counts: dict[str, int]) -> str:
    label = match.group(0)
    counts[label] = counts.get(label, 0) + 1
    return LOCALIZED_FIELD_LABELS[label]


def filter_markdown_text(source_text: str) -> tuple[str, dict[str, Any]]:
    lines = source_text.splitlines(keepends=True)
    removed: set[int] = set()
    removed_blocks: list[dict[str, Any]] = []

    metadata_indexes = header_metadata_indexes(lines)
    if metadata_indexes:
        removed.update(metadata_indexes)
        removed_blocks.append(
            {
                "kind": "header-metadata",
                "start_line": metadata_indexes[0] + 1,
                "end_line": metadata_indexes[-1] + 1,
                "removed_line_count": len(metadata_indexes),
            }
        )

    for start, end, marker in internal_comment_ranges(lines):
        removed.update(range(start, end))
        removed_blocks.append(
            {
                "kind": "internal-comment",
                "title": marker,
                "start_line": start + 1,
                "end_line": end,
                "removed_line_count": end - start,
            }
        )

    for start, end, title in governance_ranges(lines):
        removed.update(range(start, end))
        removed_blocks.append(
            {
                "kind": "governance-section",
                "title": title,
                "start_line": start + 1,
                "end_line": end,
                "removed_line_count": end - start,
            }
        )

    for index in internal_instruction_indexes(lines):
        if index in removed:
            continue
        removed.add(index)
        removed_blocks.append(
            {
                "kind": "internal-instruction",
                "start_line": index + 1,
                "end_line": index + 1,
                "removed_line_count": 1,
            }
        )

    retained = collapse_blank_lines([line for index, line in enumerate(lines) if index not in removed])
    retained, _dropped_table_columns = drop_internal_table_columns(retained)
    retained = renumber_chinese_h2_sections(retained)
    retained_text = "".join(retained)
    field_counts: dict[str, int] = {}
    localized_text = FIELD_LABEL_PATTERN.sub(
        lambda match: replace_field_label(match, field_counts), retained_text
    )
    localized_text = LOCALIZED_FIELD_LABEL_PATTERN.sub(
        lambda match: replace_localized_field_label(match, field_counts), localized_text
    )
    counts: dict[str, int] = {}
    filtered = IDENTIFIER_PATTERN.sub(lambda match: replace_identifier(match, counts), localized_text)
    forbidden_terms = [term for term in TEACHER_FORBIDDEN_TERMS if term in filtered]
    forbidden_terms.extend(
        label
        for pattern, label in TEACHER_VISIBLE_PATTERN_LABELS
        if pattern.search(filtered)
    )
    forbidden_terms = list(dict.fromkeys(forbidden_terms))
    ordered_counts = {kind: counts[kind] for kind in sorted(counts)}
    ordered_field_counts = {label: field_counts[label] for label in sorted(field_counts)}
    source_bytes = source_text.encode("utf-8")
    filtered_bytes = filtered.encode("utf-8")
    report = {
        "schema_version": SCHEMA_VERSION,
        "ok": not forbidden_terms,
        "source_sha256": sha256_bytes(source_bytes),
        "teacher_view_sha256": sha256_bytes(filtered_bytes),
        "removed_blocks": removed_blocks,
        "removed_line_count": len(removed),
        "identifier_replacements": ordered_counts,
        "total_replacements": sum(ordered_counts.values()),
        "field_label_replacements": ordered_field_counts,
        "total_field_label_replacements": sum(ordered_field_counts.values()),
        "forbidden_terms": forbidden_terms,
    }
    return filtered, report


def filter_file(source: Path, output: Path, report_path: Path) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    report_path = report_path.resolve()
    if not source.is_file():
        raise FilterError(f"内部稿不存在：{source.name}")
    if output == report_path:
        raise FilterError("教师版与转换报告不能使用同一路径")
    if output.exists() or output.is_symlink() or report_path.exists() or report_path.is_symlink():
        raise FilterError("拒绝覆盖已有教师版或转换报告")
    try:
        source_text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise FilterError("内部稿必须是可读的 UTF-8 Markdown") from error
    filtered, report = filter_markdown_text(source_text)
    if not report["ok"]:
        raise FilterError(
            "教师版仍含后台用语：" + "、".join(report["forbidden_terms"])
        )
    report = {
        **report,
        "source": {"path": source.name, "size": len(source_text.encode("utf-8"))},
        "output": {"path": output.name, "size": len(filtered.encode("utf-8"))},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if output.parent != report_path.parent:
        raise FilterError("教师版与转换报告必须写入同一目录")
    with tempfile.TemporaryDirectory(prefix=".teacher-view-", dir=output.parent) as temporary:
        staging = Path(temporary)
        staged_output = staging / output.name
        staged_report = staging / report_path.name
        staged_output.write_text(filtered, encoding="utf-8")
        staged_report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if output.exists() or output.is_symlink() or report_path.exists() or report_path.is_symlink():
            raise FilterError("输出目标在转换期间已被创建，未覆盖")
        os.rename(staged_output, output)
        try:
            os.rename(staged_report, report_path)
        except OSError:
            output.unlink(missing_ok=True)
            raise
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将冻结内部稿转换为教师可见 Markdown")
    parser.add_argument("--source", type=Path, required=True, help="冻结内部稿")
    parser.add_argument("--output", type=Path, required=True, help="教师版 Markdown")
    parser.add_argument("--report", type=Path, required=True, help="转换报告 JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = filter_file(args.source, args.output, args.report)
    except FilterError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=os.sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
