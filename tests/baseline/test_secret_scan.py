"""Unit tests for the tracked-file secret scanner used by NEWAPP-001.

Every test uses a disposable temporary directory. No test touches the NEWAPP work tree content,
``.env``, a database, OSS or the network. Credential-shaped fixtures are assembled at runtime so
this tracked test file can never trip the scanner it tests.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASELINE_DIR = Path(__file__).resolve().parent
if str(BASELINE_DIR) not in sys.path:
    sys.path.insert(0, str(BASELINE_DIR))

from secret_scan import (  # noqa: E402
    MIN_ASSIGNMENT_LENGTH,
    is_placeholder_value,
    scan_repository,
    text_rule_findings,
    tracked_files,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Synthetic fixtures, split so that no credential-shaped literal appears in this file.
FAKE_ACCESS_KEY_ID = "AK" + "IA" + "IOSFODNN7EXAMPL" + "E"
FAKE_ASSIGNMENT_VALUE = "".join(["Sup3r", "-", "NotAReal", "-", "Credential", "-42"])
FAKE_JWT = ".".join(["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0", "dk" + "XraDMF1QN7"])
PEM_HEADER = "-" * 5 + "BEGIN RSA PRIVATE KEY" + "-" * 5


def write_file(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


class ContentRuleTests(unittest.TestCase):
    def test_private_key_header_is_reported_without_content(self) -> None:
        text = "\n".join([PEM_HEADER, "body", "-" * 5 + "END RSA PRIVATE KEY" + "-" * 5]) + "\n"
        findings = text_rule_findings("config/server.key", text)
        self.assertEqual(["private_key_block"], [item["rule"] for item in findings])
        self.assertEqual(1, findings[0]["line"])
        self.assertNotIn("body", json.dumps(findings))

    def test_known_token_prefix_is_reported(self) -> None:
        findings = text_rule_findings("src/app.py", f'access_key_id = "{FAKE_ACCESS_KEY_ID}"\n')
        self.assertIn("known_token_prefix", [item["rule"] for item in findings])

    def test_jwt_literal_is_reported(self) -> None:
        findings = text_rule_findings("src/client.ts", f"const token = '{FAKE_JWT}';\n")
        self.assertIn("jwt_like_literal", [item["rule"] for item in findings])

    def test_credential_assignment_is_reported_once_per_line(self) -> None:
        text = f'password = "{FAKE_ASSIGNMENT_VALUE}"\n'
        findings = text_rule_findings("src/settings.json", text)
        self.assertEqual(["credential_assignment"], [item["rule"] for item in findings])
        self.assertEqual(1, findings[0]["line"])

    def test_short_assignment_values_are_ignored(self) -> None:
        value = "a" * (MIN_ASSIGNMENT_LENGTH - 1)
        line = "password" + " = " + value + "\n"
        self.assertEqual([], text_rule_findings("src/settings.json", line))

    def test_placeholders_and_schema_types_are_ignored(self) -> None:
        text = "\n".join(
            [
                "password: string",
                "api_key = ${API_KEY}",
                "secret: <placeholder>",
                "token: 'change-me'",
                "api_secret = $OSS_SECRET",
                "authorization: Bearer",
            ]
        )
        self.assertEqual([], text_rule_findings("docs/spec.yaml", text))

    def test_is_placeholder_value_classifies_documents_not_secrets(self) -> None:
        self.assertTrue(is_placeholder_value("${OSS_BUCKET}"))
        self.assertTrue(is_placeholder_value("example-token"))
        self.assertTrue(is_placeholder_value("os.environ['ERP_Jwt__Key']"))
        self.assertFalse(is_placeholder_value(FAKE_ASSIGNMENT_VALUE))


class PathRuleTests(unittest.TestCase):
    def test_credential_named_file_is_reported_by_path_only(self) -> None:
        text = "harmless looking content\n"
        findings = text_rule_findings(".env", text)
        self.assertEqual([], findings)

    def test_repository_scan_flags_named_credential_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_file(root, ".env", "harmless\n")
            write_file(root, "config/secrets/oss.yaml", "bucket: demo\n")
            summary = scan_repository(root, tracked=[".env", "config/secrets/oss.yaml", "src/app.py"])
            flagged = sorted(item["path"] for item in summary["findings"] if item["rule"] == "tracked_credential_file")
            self.assertEqual([".env", "config/secrets/oss.yaml"], flagged)
            self.assertEqual("failed", summary["status"])

    def test_env_example_is_exempt_but_env_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_file(root, ".env.example", "ERP_Jwt__Key=\n")
            write_file(root, ".env", "ERP_Jwt__Key=\n")
            summary = scan_repository(root, tracked=[".env.example", ".env"])
            self.assertEqual([".env"], [item["path"] for item in summary["findings"]])
            self.assertEqual([".env", ".env.example"], summary["scanned_paths"])


class RepositoryScanTests(unittest.TestCase):
    def test_summary_never_contains_the_matched_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_file(root, "src/settings.json", f'{{"password": "{FAKE_ASSIGNMENT_VALUE}"}}\n')
            write_file(root, "src/keys.py", f'KEY = "{FAKE_ACCESS_KEY_ID}"\n')
            summary = scan_repository(root, tracked=["src/settings.json", "src/keys.py"])
            serialized = json.dumps(summary, ensure_ascii=False)
            self.assertEqual(2, summary["findings_count"])
            for fragment in (FAKE_ASSIGNMENT_VALUE, FAKE_ACCESS_KEY_ID, "NotAReal"):
                self.assertNotIn(fragment, serialized)
            self.assertFalse(summary["values_recorded"])

    def test_binary_and_oversized_files_are_skipped_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "assets.bin").write_bytes(b"\x00\x01\x02password=" + FAKE_ASSIGNMENT_VALUE.encode("utf-8"))
            write_file(root, "big.txt", "x" * 512)
            summary = scan_repository(root, tracked=["assets.bin", "big.txt"], max_bytes=64)
            self.assertEqual(["assets.bin"], summary["files_skipped_binary"])
            self.assertEqual(["big.txt"], summary["files_skipped_large"])
            self.assertEqual([], summary["scanned_paths"])
            self.assertEqual("passed", summary["status"])

    def test_missing_tracked_file_is_reported_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = scan_repository(Path(temporary), tracked=["src/absent.py"])
            self.assertEqual(["src/absent.py"], summary["files_missing_on_disk"])
            self.assertEqual(0, summary["findings_count"])


@unittest.skipUnless(shutil.which("git"), "git is required for tracked-file scope tests")
class TrackedFileScopeTests(unittest.TestCase):
    def _init_repository(self, root: Path) -> None:
        run = lambda *args: subprocess.run(  # noqa: E731
            ["git", *args], cwd=str(root), capture_output=True, text=True, shell=False, check=True
        )
        run("init", "-q")
        run("config", "user.email", "baseline@example.invalid")
        run("config", "user.name", "NEWAPP baseline test")
        run("add", "--", "src/app.py")
        run("commit", "-q", "-m", "disposable test commit")

    def test_only_tracked_files_are_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_file(root, ".gitignore", ".env\n")
            write_file(root, "src/app.py", "print('demo')\n")
            write_file(root, ".env", f"DB_PASSWORD={FAKE_ASSIGNMENT_VALUE}\n")
            self._init_repository(root)
            self.assertEqual(["src/app.py"], tracked_files(root))
            summary = scan_repository(root)
            self.assertEqual(["src/app.py"], summary["scanned_paths"])
            self.assertEqual(0, summary["findings_count"])

    def test_tracked_env_is_reported_by_the_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_file(root, "src/app.py", "print('demo')\n")
            write_file(root, ".env", f"DB_PASSWORD={FAKE_ASSIGNMENT_VALUE}\n")
            self._init_repository(root)
            subprocess.run(["git", "add", "-f", "--", ".env"], cwd=str(root), capture_output=True, check=True)
            summary = scan_repository(root)
            self.assertIn(".env", summary["scanned_paths"])
            self.assertEqual("failed", summary["status"])
            self.assertNotIn(FAKE_ASSIGNMENT_VALUE, json.dumps(summary, ensure_ascii=False))

    def test_scanner_is_read_only_for_the_real_repository(self) -> None:
        before = subprocess.run(
            ["git", "status", "--porcelain=v1"], cwd=str(REPOSITORY_ROOT), capture_output=True, text=True, shell=False
        ).stdout
        scan_repository(REPOSITORY_ROOT)
        after = subprocess.run(
            ["git", "status", "--porcelain=v1"], cwd=str(REPOSITORY_ROOT), capture_output=True, text=True, shell=False
        ).stdout
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
