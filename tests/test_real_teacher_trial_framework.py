import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT / "validation" / "real-teacher-trials"


class RealTeacherTrialFrameworkTest(unittest.TestCase):
    def test_blank_template_chain_is_complete(self) -> None:
        expected = [
            "real-teacher-trial-guide.md",
            "templates/01-teacher-profile.md",
            "templates/02-preparation-log.md",
            "templates/03-editing-record.md",
            "templates/04-classroom-observation.md",
            "templates/05-interview.md",
            "templates/06-trial-summary.md",
            "templates/07-validation-report.md",
        ]
        for relative in expected:
            with self.subTest(relative=relative):
                self.assertTrue((FRAMEWORK / relative).is_file())

    def test_public_framework_keeps_thresholds_and_data_boundary(self) -> None:
        readme = (FRAMEWORK / "README.md").read_text(encoding="utf-8")
        self.assertIn("至少完成 6 位真实教师", readme)
        self.assertIn("误差不超过 3 分钟", readme)
        self.assertIn("没有任何真实教师、课堂或学生数据", readme)
        self.assertIn("不得提交教师姓名、学校、班级、学生信息", readme)

    def test_readme_links_resolve(self) -> None:
        readme = (FRAMEWORK / "README.md").read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", readme):
            with self.subTest(target=target):
                self.assertTrue((FRAMEWORK / target).is_file())


if __name__ == "__main__":
    unittest.main()
