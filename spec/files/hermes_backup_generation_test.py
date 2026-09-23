from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
from typing import cast
import unittest
import zipfile


sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "files" / "hermes-backup-generation"
PROFILES = ("talon", "star", "beryl", "quill")


class HermesBackupGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backup_dir = self.root / "backups"
        self.call_log = self.root / "calls"
        self.fake_hermes = self.root / "hermes"
        self.fake_hermes.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import os
                from pathlib import Path
                import sys
                import zipfile

                args = sys.argv[1:]
                if args[0] != "backup" or args[1] != "--output":
                    raise SystemExit(2)
                output = Path(args[2])
                with Path(os.environ["HERMES_TEST_CALL_LOG"]).open("a") as log:
                    log.write("backup\\n")
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("config.yaml", "model: test\\n")
                    archive.writestr("auth.json", '{{"providers": {{}}}}\\n')
                    archive.writestr("kanban.db", "shared-kanban")
                    for profile in {PROFILES!r}:
                        archive.writestr(f"profiles/{{profile}}/config.yaml", f"profile: {{profile}}\\n")
                """
            ),
            encoding="utf-8",
        )
        self.fake_hermes.chmod(0o700)
        self.environment = os.environ.copy()
        self.environment["HERMES_TEST_CALL_LOG"] = str(self.call_log)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_helper(self, *args: str) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(HELPER), *args],
            check=True,
            capture_output=True,
            env=self.environment,
            text=True,
        )
        return json.loads(result.stdout)

    def backup(self, checkpoint: str, retain: int = 24) -> dict[str, object]:
        return self.run_helper(
            "backup",
            "--backup-dir",
            str(self.backup_dir),
            "--hermes-bin",
            str(self.fake_hermes),
            "--checkpoint",
            checkpoint,
            "--retain",
            str(retain),
        )

    def test_four_profile_callers_create_one_restorable_full_home_generation(self) -> None:
        with ThreadPoolExecutor(max_workers=len(PROFILES)) as executor:
            results = list(executor.map(lambda _profile: self.backup("rollout-326eb96b"), PROFILES))

        self.assertEqual([result["action"] for result in results].count("created"), 1)
        self.assertEqual([result["action"] for result in results].count("reused"), 3)
        self.assertEqual(self.call_log.read_text(encoding="utf-8"), "backup\n")
        archives = list(self.backup_dir.glob("*.zip"))
        self.assertEqual([archive.name for archive in archives], ["hermes-home-rollout-326eb96b.zip"])
        self.assertFalse(any(profile in archives[0].name for profile in PROFILES))
        self.assertEqual(stat.S_IMODE(archives[0].stat().st_mode), 0o600)

        restore_root = self.root / "restored"
        with zipfile.ZipFile(archives[0]) as archive:
            self.assertIsNone(archive.testzip())
            archive.extractall(restore_root)
        self.assertEqual((restore_root / "kanban.db").read_text(), "shared-kanban")
        for profile in PROFILES:
            self.assertEqual(
                (restore_root / "profiles" / profile / "config.yaml").read_text(),
                f"profile: {profile}\n",
            )

    def test_retention_is_global_generation_count(self) -> None:
        self.backup("checkpoint-1", retain=2)
        self.backup("checkpoint-2", retain=2)
        self.backup("checkpoint-3", retain=2)

        self.assertEqual(
            sorted(path.name for path in self.backup_dir.glob("*.zip")),
            ["hermes-home-checkpoint-2.zip", "hermes-home-checkpoint-3.zip"],
        )

    def test_legacy_cleanup_dry_run_is_exact_and_apply_preserves_newest(self) -> None:
        self.backup("known-good")
        legacy = []
        for index, profile in enumerate(PROFILES):
            path = self.backup_dir / f"{profile}-hermes-2026092{index}-010203.zip"
            path.write_bytes(bytes([index]))
            os.utime(path, (index + 1, index + 1))
            legacy.append(path)

        dry_run = self.run_helper("legacy-cleanup", "--backup-dir", str(self.backup_dir))
        self.assertEqual(dry_run["action"], "legacy-cleanup-dry-run")
        self.assertEqual(dry_run["protected_newest_legacy"], [str(legacy[-1])])
        candidates = cast(list[str], dry_run["candidates"])
        self.assertIsInstance(candidates, list)
        self.assertEqual(set(candidates), {str(path) for path in legacy[:-1]})
        self.assertTrue(all(path.exists() for path in legacy))

        applied = self.run_helper(
            "legacy-cleanup",
            "--backup-dir",
            str(self.backup_dir),
            "--apply",
        )
        self.assertEqual(applied["readback_survivors"], [str(legacy[-1])])
        self.assertTrue(legacy[-1].exists())
        self.assertTrue(all(not path.exists() for path in legacy[:-1]))


if __name__ == "__main__":
    unittest.main()
