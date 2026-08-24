import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from job_radar_lib.storage import (  # noqa: E402
    initialize_workspace,
    load_workspace,
    read_json,
    write_json_atomic,
)


class StorageTests(unittest.TestCase):
    def test_initialize_creates_canonical_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = initialize_workspace(Path(tmp) / "data")

            self.assertTrue(workspace.profile.exists())
            self.assertEqual(read_json(workspace.jobs), [])
            self.assertEqual(read_json(workspace.applications), [])
            self.assertFalse(read_json(workspace.profile)["confirmed"])

    def test_initialize_creates_company_policy_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = initialize_workspace(Path(tempdir) / "data")

            self.assertEqual(read_json(workspace.company_policies), [])

    def test_load_upgrades_legacy_workspace_with_empty_policy_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "data"
            workspace = initialize_workspace(root)
            workspace.company_policies.unlink()

            upgraded = load_workspace(root)

            self.assertEqual(read_json(upgraded.company_policies), [])

    def test_load_still_rejects_a_missing_v1_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "data"
            workspace = initialize_workspace(root)
            workspace.jobs.unlink()
            workspace.company_policies.unlink()

            with self.assertRaisesRegex(FileNotFoundError, "jobs.json"):
                load_workspace(root)

    def test_load_workspace_rejects_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"

            with self.assertRaises(FileNotFoundError):
                load_workspace(missing)

    def test_atomic_write_backs_up_previous_valid_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = initialize_workspace(Path(tmp) / "data")
            write_json_atomic(workspace.jobs, [{"id": "first"}], workspace.backups)
            write_json_atomic(workspace.jobs, [{"id": "second"}], workspace.backups)

            backups = list(workspace.backups.glob("jobs-*.json"))
            values = [json.loads(path.read_text(encoding="utf-8")) for path in backups]
            self.assertIn([{"id": "first"}], values)
            self.assertEqual(read_json(workspace.jobs), [{"id": "second"}])

    def test_broken_existing_json_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = initialize_workspace(Path(tmp) / "data")
            workspace.jobs.write_text("{broken", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                write_json_atomic(workspace.jobs, [], workspace.backups)

            self.assertEqual(workspace.jobs.read_text(encoding="utf-8"), "{broken")

    def test_backup_retention_is_bounded_to_twenty(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = initialize_workspace(Path(tmp) / "data")
            for index in range(25):
                write_json_atomic(workspace.jobs, [{"id": str(index)}], workspace.backups)

            self.assertLessEqual(len(list(workspace.backups.glob("jobs-*.json"))), 20)


if __name__ == "__main__":
    unittest.main()
