from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]


class PublicTeachingDesignContractTest(unittest.TestCase):
    def test_public_v21_director_contract_is_self_contained(self) -> None:
        files = {
            "skill": SKILL_ROOT / "SKILL.md",
            "workflow": SKILL_ROOT / "references" / "workflows" / "lesson-preparation.md",
            "teacher_ready": (
                SKILL_ROOT / "references" / "workflows" / "teacher-ready-content.md"
            ),
            "template": SKILL_ROOT / "assets" / "templates" / "02-teaching-design.md",
            "review": (
                SKILL_ROOT
                / "references"
                / "workflows"
                / "teaching-design-decision-review.md"
            ),
        }
        content = {name: path.read_text(encoding="utf-8") for name, path in files.items()}

        for phrase in (
            "关键学习障碍",
            "理解误读、知识缺口、阅读或写作策略缺口，或表达与迁移缺口",
            "零至两个必要支撑",
            "0—2 个必要支撑",
            "直接从文本疑点或核心任务进入更有效时，不另加包装",
            "教学设计未获老师确认，不生成下游授课导航稿或课件",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, content["skill"])

        for phrase in (
            "若使用情境，再核对",
            "固定字数合同不适用",
            "教学设计确认",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, content["workflow"])

        self.assertIn("九个板块", content["teacher_ready"])
        self.assertIn("总时长不超过 60 分钟", content["template"])
        self.assertIn("不得把问题、回答或结论打印进教师成稿", content["review"])

        public_contract = "\n".join(content.values())
        for forbidden in (
            "references/knowledge",
            "teaching-patterns",
            "production-case-reuse",
            "knowledge_library.py",
            "built-in-knowledge-and-history",
            "holdout",
            "/Users/",
            "/Volumes/",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, public_contract)


if __name__ == "__main__":
    unittest.main()
