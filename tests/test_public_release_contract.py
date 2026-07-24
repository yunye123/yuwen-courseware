from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicReleaseContractTest(unittest.TestCase):
    def test_version_changelog_and_rc_documents_are_aligned(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "0.1.0")

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "release-candidate-checklist.md").read_text(
            encoding="utf-8"
        )

        for text in (changelog, readme, checklist):
            self.assertIn("0.1.0", text)
        self.assertIn("发布候选", changelog)
        self.assertIn("技术预览", readme)
        self.assertIn("尚未证明", readme)
        self.assertIn("不把任一勾选项解释为真实课堂效果", checklist)

    def test_readme_and_quickstart_explain_the_public_workflow_boundary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")

        for phrase in (
            "课堂主线与问题链",
            "日常教学设计",
            "授课导航稿",
            "白底可编辑 PPTX",
            "完整逐字稿、学案和教师参考答案按课堂需要生成",
            "而不是凭模型记忆补写引文或生成虚假完整成品",
            "`scripts/verify_install.py`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)

        for phrase in (
            "场景 A：材料完整的常态课",
            "场景 B：材料不完整",
            "场景 C：无设备课堂",
            "不生成看似完整的教学设计、导航稿或课件",
            "PPTX 是辅助材料，不是课堂继续进行的唯一载体",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, quickstart)

    def test_relative_markdown_links_from_public_entry_documents_resolve(self) -> None:
        documents = (
            ROOT / "README.md",
            ROOT / "docs" / "quickstart.md",
            ROOT / "docs" / "release-candidate-checklist.md",
        )
        pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")

        for document in documents:
            for target in pattern.findall(document.read_text(encoding="utf-8")):
                target = target.strip()
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                local_target = target.split("#", 1)[0]
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / local_target).exists())

    def test_original_resource_has_manifest_rights_and_minimal_lesson_input(self) -> None:
        manifest = json.loads((ROOT / "resources" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["distribution_license"], "PLRL-1.0")
        resource = manifest["resources"][0]
        self.assertEqual(resource["source_kind"], "original")
        self.assertEqual(resource["license"], "PLRL-1.0")

        sample = ROOT / "resources" / resource["path"]
        self.assertTrue(sample.is_file())
        sample_text = sample.read_text(encoding="utf-8")
        for phrase in ("自创安装学习示例 v1", "45 分钟", "高一普通班", "场景 C 变体"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, sample_text)

    def test_public_ci_and_pinned_dependency_cover_the_release_contract(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(
            encoding="utf-8"
        )
        requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

        self.assertIn("pull_request:", workflow)
        self.assertIn("python -B -m compileall -q scripts tests", workflow)
        self.assertIn("git diff --check", workflow)
        self.assertIn("python-pptx==1.0.2", requirements)


if __name__ == "__main__":
    unittest.main()
