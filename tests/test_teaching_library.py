from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "teaching_library.py"
SPEC = importlib.util.spec_from_file_location("teaching_library", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TeachingLibraryTests(unittest.TestCase):
    def make_lesson(self, data_home: Path, lesson_id: str = "yan-ge-xing") -> Path:
        lesson = data_home / "lessons" / lesson_id
        lesson.mkdir(parents=True)
        (lesson / "state.json").write_text(
            json.dumps(
                {
                    "lesson_id": lesson_id,
                    "current_stage": "release",
                    "status": "review",
                    "revision": 3,
                    "created_at": "2026-07-20T00:00:00Z",
                    "updated_at": "2026-07-20T01:00:00Z",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (lesson / "00-lesson-brief.md").write_text(
            "# 备课开课单\n\n"
            "- 篇目或主题：《示例古诗》\n"
            "- 教材出版社、册次、单元、版次：公开示例版·第一册·阅读单元\n"
            "- 课型：古诗词阅读\n"
            "- 课时数与单课时长度：1课时·45分钟\n"
            "- 使用场景：日常同步课\n",
            encoding="utf-8",
        )
        return lesson

    def write_promotion_files(self, lesson: Path, *, private_name: bool = False) -> None:
        reflection = "# 课后反思\n活动有效，第三环节超时。\n"
        if private_name:
            reflection += "学生姓名：张三\n"
        (lesson / "10-课后反思.md").write_text(reflection, encoding="utf-8")
        (lesson / "11-个人经验卡.md").write_text(
            "# 个人教学经验卡\n\n"
            "核心问题：征人和思妇的两重悲歌如何彼此映照？\n\n"
            "- [x] 不含学生姓名、学号、联系方式或可识别个人的信息\n"
            "- [x] 仅加入当前老师的个人经验库\n"
            "- [x] 老师已明确同意加入个人经验库\n",
            encoding="utf-8",
        )
        (lesson / "确认加入经验库.json").write_text(
            json.dumps(
                {
                    "record_type": "user-personal-library-confirmation",
                    "lesson_id": lesson.name,
                    "user_id": "teacher-1",
                    "decision": "promote",
                    "confirmed_at": "2026-07-20T02:00:00Z",
                    "message_excerpt": "加入我的教学经验库",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def promote_args(self, data_home: Path, lesson_id: str = "yan-ge-xing"):
        return type(
            "Args",
            (),
            {
                "data_home": str(data_home),
                "lesson_id": lesson_id,
                "user_id": "teacher-1",
                "confirmation": "确认加入经验库.json",
                "reflection": "10-课后反思.md",
                "card": "11-个人经验卡.md",
            },
        )()

    def test_rebuild_index_parses_teacher_facing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_home = Path(temporary)
            self.make_lesson(data_home)
            value = MODULE.build_index(data_home)
            self.assertTrue(value["ok"])
            self.assertEqual(value["lesson_count"], 1)
            self.assertEqual(value["lessons"][0]["title"], "《示例古诗》")
            self.assertEqual(value["lessons"][0]["personal_experience_count"], 0)

    def test_promote_requires_real_confirmation_and_writes_outside_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_home = Path(temporary)
            lesson = self.make_lesson(data_home)
            self.write_promotion_files(lesson)
            with redirect_stdout(io.StringIO()):
                code = MODULE.command_promote(self.promote_args(data_home))
            self.assertEqual(code, 0)
            records = list((data_home / "library" / "个人经验").glob("*.json"))
            self.assertEqual(len(records), 1)
            index = json.loads((data_home / "library" / "课例索引.json").read_text(encoding="utf-8"))
            self.assertEqual(index["experience_count"], 1)
            self.assertEqual(index["lessons"][0]["personal_experience_count"], 1)

    def test_promote_blocks_student_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_home = Path(temporary)
            lesson = self.make_lesson(data_home)
            self.write_promotion_files(lesson, private_name=True)
            with self.assertRaises(MODULE.TeachingLibraryError):
                MODULE.command_promote(self.promote_args(data_home))
            self.assertFalse((data_home / "library" / "个人经验").exists())

    def test_search_only_reads_promoted_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_home = Path(temporary)
            lesson = self.make_lesson(data_home)
            self.write_promotion_files(lesson)
            with redirect_stdout(io.StringIO()):
                MODULE.command_promote(self.promote_args(data_home))
            records = MODULE.experience_records(data_home)
            self.assertIn("yan-ge-xing", records)
            card_path = records["yan-ge-xing"][0]["card"]["path"]
            self.assertTrue((data_home / card_path).is_file())


if __name__ == "__main__":
    unittest.main()
