#!/usr/bin/env python3
"""检查教师版教学设计的 v2.1 成稿合同。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Iterable


EXPECTED_SECTIONS = (
    "一、基本信息",
    "二、本课只攻一处",
    "三、本课不做",
    "四、教学目标",
    "五、教学重难点",
    "六、教学过程",
    "七、板书设计",
    "八、当堂检测",
    "九、作业",
)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
PROCESS_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
PROCESS_DURATION_RE = re.compile(r"（(\d+)分钟）\s*$")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
FRAME_RE = re.compile(r"[┌┐└┘├┤┬┴┼│─═║╔╗╚╝╠╣╦╩╬]")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF]")
INTERNAL_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FORBIDDEN_HEADINGS = ("备课说明", "教材解读", "学情分析", "设计依据", "评价设计", "备选方案")
FORBIDDEN_WORDS = (
    "作为AI",
    "大模型",
    "增强审美能力",
    "合理异答边界",
    "纠偏支架",
    "教师承接",
    "教学分支",
)
CAUTIONARY_WORDS = ("核心素养", "文化自信")
SINGLE_LESSON_MAX_MINUTES = 60
REQUIRED_PROCESS_LABELS = ("师", "生", "预设", "应对", "板书随写")
PROCESS_LABELS = (*REQUIRED_PROCESS_LABELS, "预设（误）")


def visible_text(value: str) -> str:
    """Count visible content while ignoring Markdown markers and internal comments."""
    value = INTERNAL_COMMENT_RE.sub("", value)
    value = re.sub(r"^#{1,6}\s+", "", value, flags=re.MULTILINE)
    value = value.replace("**", "").replace("`", "")
    return re.sub(r"\s+", "", value)


def normalized_line(value: str) -> str:
    return value.strip().strip("- ").replace("**", "").replace("`", "")


def split_sections(text: str) -> dict[str, str]:
    headings = list(SECTION_RE.finditer(text))
    result: dict[str, str] = {}
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        result[match.group(1)] = text[match.end() : end]
    return result


def process_blocks(process: str) -> list[tuple[str, str]]:
    """Return every process heading and its body, even when its time is malformed."""
    headings = list(PROCESS_HEADING_RE.finditer(process))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(process)
        result.append((match.group(1), process[match.end() : end]))
    return result


def parse_process_label_line(line: str) -> tuple[str, str] | None:
    """Recognize a supported process label and preserve the value after its colon."""
    normalized = normalized_line(line)
    match = re.match(
        r"^(师|生|预设（误）|预设|应对|板书随写)\s*[：:]\s*(.*)$",
        normalized,
    )
    if match is None:
        return None
    return match.group(1), match.group(2)


def has_substantive_content(value: str) -> bool:
    return bool(visible_text(value))


def extract_label_values(block: str) -> dict[str, list[str]]:
    """Collect label values, allowing an empty label to continue on the next prose line.

    A continuation may skip blank lines, but never crosses another supported label or a
    Markdown heading. This accepts ordinary Markdown wrapping without letting a later
    classroom field satisfy an empty earlier field.
    """
    lines = block.splitlines()
    values: dict[str, list[str]] = {}
    for index, line in enumerate(lines):
        parsed = parse_process_label_line(line)
        if parsed is None:
            continue
        label, value = parsed
        if not has_substantive_content(value):
            for continuation in lines[index + 1 :]:
                normalized = normalized_line(continuation)
                if parse_process_label_line(continuation) is not None or normalized.startswith("#"):
                    break
                if has_substantive_content(normalized):
                    value = normalized
                    break
        values.setdefault(label, []).append(value)
    return values


def issues_for_labels(process: str) -> list[str]:
    issues: list[str] = []
    for index, (_, block) in enumerate(process_blocks(process)):
        values = extract_label_values(block)
        missing = [label for label in REQUIRED_PROCESS_LABELS if label not in values]
        if missing:
            issues.append(f"环节 {index + 1} 缺少：{'、'.join(missing)}")
        empty = [
            label
            for label in PROCESS_LABELS
            if any(not has_substantive_content(value) for value in values.get(label, []))
        ]
        if empty:
            issues.append(f"环节 {index + 1} 的标签内容不能为空：{'、'.join(empty)}")
    return issues


def check_document(text: str) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    headings = tuple(match.group(1) for match in SECTION_RE.finditer(text))
    sections = split_sections(text)
    if headings != EXPECTED_SECTIONS:
        errors.append("一级板块必须且只能依次为九个规定板块")

    if INTERNAL_COMMENT_RE.search(text):
        errors.append("教师版不得残留内部注释")

    for heading in FORBIDDEN_HEADINGS:
        if heading in sections:
            errors.append(f"不得设置独立板块：{heading}")
    for word in FORBIDDEN_WORDS:
        if word in text:
            errors.append(f"含禁止语句：{word}")
    for word in CAUTIONARY_WORDS:
        if word in text:
            warnings.append(f"含需核对的泛化表述：{word}")
    if TABLE_RE.search(text):
        errors.append("不得使用 Markdown 表格")
    if FRAME_RE.search(text):
        errors.append("不得使用框线字符")
    if EMOJI_RE.search(text):
        errors.append("不得使用 emoji")

    duration_match = re.search(r"课时[：:].*?（(\d+)分钟）", sections.get("一、基本信息", ""))
    total_minutes = int(duration_match.group(1)) if duration_match else None
    if duration_match is None:
        errors.append("基本信息须写明单课时总分钟数，例如“课时：1课时（45分钟）”")

    total_chars = len(visible_text(text))
    if total_minutes is not None and total_minutes <= SINGLE_LESSON_MAX_MINUTES:
        if total_chars > 3500:
            errors.append(f"全文可见字数为 {total_chars}，不得超过 3500")
        elif total_chars < 2500:
            warnings.append(f"全文可见字数为 {total_chars}，低于建议下限 2500")
    elif total_minutes is not None:
        warnings.append("当前设计超过单课时范围，固定字数合同不适用，请人工检查篇幅")

    process = sections.get("六、教学过程", "")
    process_chars = len(visible_text(process))
    process_ratio = process_chars / total_chars if total_chars else 0
    if process_ratio < 0.70:
        warnings.append(f"教学过程占比为 {process_ratio:.1%}，低于建议值 70%")

    front_chars = sum(len(visible_text(sections.get(name, ""))) for name in EXPECTED_SECTIONS[1:5])
    if front_chars > 300:
        warnings.append(f"本课只攻一处、本课不做、目标和重难点共 {front_chars} 字，超过建议值 300 字")

    basic_lines = [line for line in sections.get("一、基本信息", "").splitlines() if normalized_line(line)]
    if len(basic_lines) > 5:
        warnings.append("基本信息超过建议上限 5 行")
    target_lines = [line for line in sections.get("四、教学目标", "").splitlines() if normalized_line(line)]
    if not 1 <= len(target_lines) <= 3:
        warnings.append("教学目标建议为 1 个核心达成加 0—2 个必要支撑（共 1—3 条）")

    blocks = process_blocks(process)
    durations: list[int] = []
    if not blocks:
        errors.append("教学过程的每个环节均须在标题标注“（X分钟）”")
    else:
        for title, _ in blocks:
            duration = PROCESS_DURATION_RE.search(title)
            if duration is not None:
                durations.append(int(duration.group(1)))
        if len(durations) != len(blocks):
            errors.append("教学过程的每个环节均须在标题标注“（X分钟）”")
    if duration_match and blocks and len(durations) == len(blocks) and sum(durations) != int(duration_match.group(1)):
        errors.append(f"教学过程时间合计 {sum(durations)} 分钟，与课时 {duration_match.group(1)} 分钟不一致")
    errors.extend(issues_for_labels(process))

    process_values = extract_label_values(process)
    preset_count = sum(has_substantive_content(value) for value in process_values.get("预设", []))
    mistaken_count = sum(has_substantive_content(value) for value in process_values.get("预设（误）", []))
    if preset_count < 6:
        errors.append(f"预设仅 {preset_count} 处，至少需要 6 处")
    if mistaken_count < 2:
        errors.append(f"预设（误）仅 {mistaken_count} 处，至少需要 2 处")

    board = sections.get("七、板书设计", "")
    board_lines = [normalized_line(line) for line in board.splitlines() if normalized_line(line)]
    if not board_lines:
        errors.append("板书设计不得为空")
    elif not any("→" in line for line in board_lines):
        warnings.append("板书设计未使用“→”呈现关系；请确认并列或层级表达已足够清楚")
    if any("|" in line for line in board_lines):
        errors.append("板书设计不得使用表格")

    if "联读" in text:
        warnings.append("检测到“联读”；请确认这是老师明确提出的要求")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "total_visible_chars": total_chars,
            "process_visible_chars": process_chars,
            "process_ratio": round(process_ratio, 4),
            "front_visible_chars": front_chars,
            "process_minutes": sum(durations),
            "preset_count": preset_count,
            "mistaken_preset_count": mistaken_count,
        },
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查教学设计 v2.1 成稿合同")
    parser.add_argument("design", type=Path, help="教师版教学设计 Markdown 文件")
    args = parser.parse_args(argv)
    try:
        text = args.design.read_text(encoding="utf-8")
    except OSError as error:
        parser.error(f"无法读取教学设计：{error}")
    report = check_document(text)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
