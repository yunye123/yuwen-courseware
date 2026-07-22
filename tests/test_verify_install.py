from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_install.py"
SPEC = importlib.util.spec_from_file_location("verify_install", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verify_install = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_install
SPEC.loader.exec_module(verify_install)


class VerifyInstallTests(unittest.TestCase):
    def make_skill(self, root: Path) -> Path:
        skill = root / "yuwen-courseware"
        files = {
            "SKILL.md": b"---\nname: yuwen-courseware\n---\n",
            "VERSION": b"1.2.3\n",
            "scripts/verify_install.py": b"# bundled verifier\n",
        }
        records = []
        for relative, content in sorted(files.items()):
            path = skill / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            records.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                }
            )
        manifest = {
            "manifest_version": 1,
            "package": "yuwen-courseware",
            "release_directory": "yuwen-courseware",
            "version": "1.2.3",
            "files": records,
        }
        (skill / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return skill

    def add_workbuddy_metadata(self, skill: Path, **overrides: object) -> None:
        payload: dict[str, object] = {
            "name": "yuwen-courseware",
            "installedAt": 1784385442575,
            "source": "userImport",
        }
        payload.update(overrides)
        (skill / "_user_meta.json").write_text(
            json.dumps(payload, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def test_accepts_exact_manifest_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            result = verify_install.verify_install(skill)
            self.assertTrue(result["ok"], result["issues"])
            self.assertEqual(result["checked_files"], 3)
            self.assertEqual(result["version"], "1.2.3")
            self.assertEqual(result["host_metadata_files"], [])

    def test_accepts_strict_workbuddy_user_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            self.add_workbuddy_metadata(skill)
            result = verify_install.verify_install(skill)
            self.assertTrue(result["ok"], result["issues"])
            self.assertEqual(result["checked_files"], 3)
            self.assertEqual(result["host_metadata_files"], ["_user_meta.json"])

    def test_rejects_malformed_workbuddy_user_metadata(self) -> None:
        invalid_overrides = (
            {"name": "other-skill"},
            {"installedAt": True},
            {"installedAt": -1},
            {"installedAt": "1784385442575"},
            {"installedAt": 1.5},
            {"installedAt": (1 << 53)},
            {"source": "unknown"},
            {"extra": "unexpected"},
        )
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides):
                with tempfile.TemporaryDirectory() as temporary:
                    skill = self.make_skill(Path(temporary))
                    self.add_workbuddy_metadata(skill, **overrides)
                    result = verify_install.verify_install(skill)
                    kinds = {item["kind"] for item in result["issues"]}
                    self.assertFalse(result["ok"])
                    self.assertIn("host-metadata-invalid", kinds)

    def test_rejects_oversized_workbuddy_user_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            (skill / "_user_meta.json").write_text(" " * 4097, encoding="utf-8")
            result = verify_install.verify_install(skill)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertFalse(result["ok"])
            self.assertIn("host-metadata-invalid", kinds)

    def test_rejects_duplicate_keys_and_invalid_utf8_in_workbuddy_metadata(self) -> None:
        invalid_contents = (
            b'{"name":"yuwen-courseware","name":"other","installedAt":1,"source":"userImport"}',
            b"\xff\xfe",
        )
        for content in invalid_contents:
            with self.subTest(content=content):
                with tempfile.TemporaryDirectory() as temporary:
                    skill = self.make_skill(Path(temporary))
                    (skill / "_user_meta.json").write_bytes(content)
                    result = verify_install.verify_install(skill)
                    kinds = {item["kind"] for item in result["issues"]}
                    self.assertFalse(result["ok"])
                    self.assertIn("host-metadata-invalid", kinds)

    @unittest.skipIf(os.name == "nt", "POSIX executable mode required")
    def test_rejects_executable_workbuddy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            self.add_workbuddy_metadata(skill)
            (skill / "_user_meta.json").chmod(0o755)
            result = verify_install.verify_install(skill)
            reasons = {
                item.get("reason")
                for item in result["issues"]
                if item["kind"] == "host-metadata-invalid"
            }
            self.assertFalse(result["ok"])
            self.assertIn("executable-mode", reasons)

    def test_rejects_directory_at_workbuddy_metadata_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            (skill / "_user_meta.json").mkdir()
            result = verify_install.verify_install(skill)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertFalse(result["ok"])
            self.assertIn("host-metadata-invalid", kinds)

    def test_manifest_cannot_declare_workbuddy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            manifest_path = skill / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["path"] = "_user_meta.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = verify_install.verify_install(skill)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertFalse(result["ok"])
            self.assertIn("manifest-file-path-duplicate-or-reserved", kinds)

    def test_valid_workbuddy_metadata_does_not_hide_other_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            self.add_workbuddy_metadata(skill)
            (skill / "SKILL.md").write_text("tampered\n", encoding="utf-8")
            (skill / "payload.sh").write_text("echo unsafe\n", encoding="utf-8")
            result = verify_install.verify_install(skill)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertFalse(result["ok"])
            self.assertIn("declared-file-sha256-mismatch", kinds)
            self.assertIn("undeclared-file", kinds)
            self.assertEqual(result["host_metadata_files"], ["_user_meta.json"])

    def test_nested_or_case_variant_workbuddy_metadata_is_undeclared(self) -> None:
        for relative in ("nested/_user_meta.json", "_USER_META.json"):
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as temporary:
                    skill = self.make_skill(Path(temporary))
                    path = skill / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("{}\n", encoding="utf-8")
                    result = verify_install.verify_install(skill)
                    kinds = {item["kind"] for item in result["issues"]}
                    self.assertFalse(result["ok"])
                    self.assertIn("undeclared-file", kinds)

    def test_rejects_tampered_and_undeclared_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            (skill / "SKILL.md").write_text("tampered\n", encoding="utf-8")
            (skill / "extra.txt").write_text("extra\n", encoding="utf-8")
            result = verify_install.verify_install(skill)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertFalse(result["ok"])
            self.assertIn("declared-file-sha256-mismatch", kinds)
            self.assertIn("undeclared-file", kinds)

    def test_rejects_unsafe_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            manifest_path = skill / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["path"] = "../outside.txt"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = verify_install.verify_install(skill)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertFalse(result["ok"])
            self.assertIn("manifest-file-path-invalid", kinds)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support required")
    def test_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill = self.make_skill(Path(temporary))
            target = skill / "target.txt"
            target.write_text("target\n", encoding="utf-8")
            link = skill / "link.txt"
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            result = verify_install.verify_install(skill)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertFalse(result["ok"])
            self.assertIn("symlink-not-allowed", kinds)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support required")
    def test_rejects_symlinked_skill_root_for_copy_only_beta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = self.make_skill(root / "real")
            linked = root / "linked-skill"
            try:
                linked.symlink_to(skill, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlink unavailable: {error}")
            result = verify_install.verify_install(linked)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertFalse(result["ok"])
            self.assertIn("skill-root-symlink", kinds)


if __name__ == "__main__":
    unittest.main()
