#!/usr/bin/env python3
"""Verify a copied yuwen-courseware Skill against its bundled manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any


SCHEMA_VERSION = "yuwen-courseware.install-verification/v1"
PACKAGE_NAME = "yuwen-courseware"
MANIFEST_NAME = "manifest.json"
WORKBUDDY_METADATA_NAME = "_user_meta.json"
MAX_HOST_METADATA_BYTES = 4096
MAX_SAFE_JSON_INTEGER = (1 << 53) - 1
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*\Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_manifest_path(raw: Any) -> PurePosixPath | None:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        return None
    if raw.startswith("/") or any(part in {"", ".", ".."} for part in raw.split("/")):
        return None
    relative = PurePosixPath(raw)
    if relative.is_absolute() or relative.as_posix() != raw or ":" in relative.parts[0]:
        return None
    return relative


def issue(kind: str, **details: Any) -> dict[str, Any]:
    return {"kind": kind, **details}


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate-key")
        payload[key] = value
    return payload


def validate_workbuddy_metadata(path: Path) -> str | None:
    try:
        file_stat = path.lstat()
        if not stat.S_ISREG(file_stat.st_mode):
            return "not-regular-file"
        if file_stat.st_mode & 0o111:
            return "executable-mode"
        if file_stat.st_size < 1:
            return "empty"
        if file_stat.st_size > MAX_HOST_METADATA_BYTES:
            return "too-large"
        with path.open("rb") as handle:
            raw_payload = handle.read(MAX_HOST_METADATA_BYTES + 1)
        if len(raw_payload) < 1:
            return "empty"
        if len(raw_payload) > MAX_HOST_METADATA_BYTES:
            return "too-large"
        payload = json.loads(
            raw_payload.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    except OSError:
        return "unreadable"
    except (UnicodeError, json.JSONDecodeError):
        return "json-invalid"
    except ValueError as error:
        return str(error)
    if not isinstance(payload, dict):
        return "root-invalid"
    if set(payload) != {"name", "installedAt", "source"}:
        return "field-set-mismatch"
    if payload.get("name") != PACKAGE_NAME:
        return "name-mismatch"
    installed_at = payload.get("installedAt")
    if (
        not isinstance(installed_at, int)
        or isinstance(installed_at, bool)
        or installed_at < 0
        or installed_at > MAX_SAFE_JSON_INTEGER
    ):
        return "installed-at-invalid"
    if payload.get("source") != "userImport":
        return "source-invalid"
    return None


def verify_install(skill_root: Path) -> dict[str, Any]:
    root = skill_root.absolute()
    issues: list[dict[str, Any]] = []
    manifest_path = root / MANIFEST_NAME

    if manifest_path.is_symlink():
        issues.append(issue("manifest-symlink"))
        manifest: Any = None
    elif not manifest_path.is_file():
        issues.append(issue("manifest-missing"))
        manifest = None
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            issues.append(issue("manifest-invalid", detail=str(error)))
            manifest = None

    expected_paths: dict[str, dict[str, Any]] = {}
    version: str | None = None
    if isinstance(manifest, dict):
        expected_fields = {
            "manifest_version",
            "package",
            "release_directory",
            "version",
            "files",
        }
        if set(manifest) != expected_fields:
            issues.append(issue("manifest-field-set-mismatch"))
        if manifest.get("manifest_version") != 1:
            issues.append(issue("manifest-version-unsupported"))
        if manifest.get("package") != PACKAGE_NAME:
            issues.append(issue("manifest-package-mismatch"))
        if manifest.get("release_directory") != PACKAGE_NAME:
            issues.append(issue("manifest-release-directory-mismatch"))

        raw_version = manifest.get("version")
        if isinstance(raw_version, str) and VERSION_PATTERN.fullmatch(raw_version):
            version = raw_version
        else:
            issues.append(issue("manifest-release-version-invalid"))

        records = manifest.get("files")
        if not isinstance(records, list):
            issues.append(issue("manifest-files-invalid"))
        else:
            listed_paths: list[str] = []
            for index, record in enumerate(records):
                if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
                    issues.append(issue("manifest-file-record-invalid", index=index))
                    continue
                relative = safe_manifest_path(record.get("path"))
                digest = record.get("sha256")
                size = record.get("size")
                if relative is None:
                    issues.append(issue("manifest-file-path-invalid", index=index))
                    continue
                path_text = relative.as_posix()
                if (
                    path_text in {MANIFEST_NAME, WORKBUDDY_METADATA_NAME}
                    or path_text in expected_paths
                ):
                    issues.append(issue("manifest-file-path-duplicate-or-reserved", path=path_text))
                    continue
                if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
                    issues.append(issue("manifest-file-sha256-invalid", path=path_text))
                    continue
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    issues.append(issue("manifest-file-size-invalid", path=path_text))
                    continue
                expected_paths[path_text] = record
                listed_paths.append(path_text)
            if listed_paths != sorted(listed_paths):
                issues.append(issue("manifest-files-not-sorted"))
    elif manifest is not None:
        issues.append(issue("manifest-root-invalid"))

    actual_paths: set[str] = set()
    host_metadata_files: list[str] = []
    if root.is_symlink():
        issues.append(issue("skill-root-symlink"))
    if not root.is_dir():
        issues.append(issue("skill-root-missing"))
    else:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            relative_text = path.relative_to(root).as_posix()
            if path.is_symlink():
                issues.append(issue("symlink-not-allowed", path=relative_text))
                continue
            if relative_text == WORKBUDDY_METADATA_NAME:
                if path.is_file():
                    reason = validate_workbuddy_metadata(path)
                    if reason is None:
                        host_metadata_files.append(relative_text)
                    else:
                        issues.append(
                            issue(
                                "host-metadata-invalid",
                                path=relative_text,
                                reason=reason,
                            )
                        )
                else:
                    issues.append(
                        issue(
                            "host-metadata-invalid",
                            path=relative_text,
                            reason="not-regular-file",
                        )
                    )
                continue
            if path.is_file() and relative_text != MANIFEST_NAME:
                actual_paths.add(relative_text)

    for missing in sorted(set(expected_paths) - actual_paths):
        issues.append(issue("declared-file-missing", path=missing))
    for extra in sorted(actual_paths - set(expected_paths)):
        issues.append(issue("undeclared-file", path=extra))

    for path_text in sorted(set(expected_paths) & actual_paths):
        record = expected_paths[path_text]
        relative = PurePosixPath(path_text)
        path = root.joinpath(*relative.parts)
        try:
            size = path.stat().st_size
            digest = sha256_file(path)
        except OSError as error:
            issues.append(issue("declared-file-unreadable", path=path_text, detail=str(error)))
            continue
        if size != record["size"]:
            issues.append(
                issue(
                    "declared-file-size-mismatch",
                    path=path_text,
                    expected=record["size"],
                    actual=size,
                )
            )
        if digest != record["sha256"]:
            issues.append(
                issue(
                    "declared-file-sha256-mismatch",
                    path=path_text,
                    expected=record["sha256"],
                    actual=digest,
                )
            )

    version_path = root / "VERSION"
    if version_path.is_symlink():
        issues.append(issue("version-symlink"))
    elif not version_path.is_file():
        issues.append(issue("version-file-missing"))
    else:
        try:
            version_file = version_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            issues.append(issue("version-file-invalid", detail=str(error)))
        else:
            if version is not None and version_file != version:
                issues.append(
                    issue("version-file-mismatch", expected=version, actual=version_file)
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not issues,
        "package": PACKAGE_NAME,
        "version": version,
        "checked_files": len(set(expected_paths) & actual_paths),
        "host_metadata_files": sorted(host_metadata_files),
        "issues": issues,
    }


def main() -> int:
    skill_root = Path(__file__).absolute().parents[1]
    payload = verify_install(skill_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
