import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from job_radar_lib.email_models import (
    DEFAULT_EMAIL_SYNC_STATE,
    validate_email_event,
    validate_email_events,
    validate_email_sync_state,
)
from job_radar_lib.models import ValidationError
from job_radar_lib.storage import (
    initialize_workspace,
    load_workspace,
    read_json,
    write_json_atomic,
    write_json_bundle_atomic,
)
from tests.helpers import email_event, email_sync_state


class EmailModelTests(unittest.TestCase):
    def test_sync_state_rejects_credentials_and_unknown_fields(self):
        value = email_sync_state(appPassword="secret")
        with self.assertRaisesRegex(ValidationError, "unknown email sync fields"):
            validate_email_sync_state(value)

    def test_sync_state_validates_hash_cursor_and_window(self):
        self.assertEqual(validate_email_sync_state(email_sync_state())["lastSeenUid"], 42)
        for invalid in (
            email_sync_state(mailboxHash="candidate@qq.com"),
            email_sync_state(initialWindowDays=0),
            email_sync_state(uidValidity=-1),
            email_sync_state(lastSeenUid="42"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    validate_email_sync_state(invalid)

    def test_event_requires_supported_classification_state_and_confidence(self):
        for invalid in (
            email_event(classification="maybe"),
            email_event(state="maybe"),
            email_event(confidence=1.1),
            email_event(proposedStatus="maybe"),
            email_event(reasons="not-a-list"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    validate_email_event(invalid)

    def test_event_collection_rejects_duplicate_ids_and_message_keys(self):
        first = email_event()
        with self.assertRaisesRegex(ValidationError, "duplicate email event ids"):
            validate_email_events([first, email_event(messageKeyHash="sha256:" + "c" * 64)])
        with self.assertRaisesRegex(ValidationError, "duplicate email message keys"):
            validate_email_events([first, email_event(id="evt_other")])


class EmailWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "workspace"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_initialize_creates_non_sensitive_email_files(self):
        workspace = initialize_workspace(self.root)
        self.assertEqual(read_json(workspace.email_sync), DEFAULT_EMAIL_SYNC_STATE)
        self.assertEqual(read_json(workspace.email_events), [])
        serialized = workspace.email_sync.read_text(encoding="utf-8")
        self.assertNotIn("username", serialized.lower())
        self.assertNotIn("password", serialized.lower())

    def test_load_workspace_upgrades_legacy_workspace(self):
        workspace = initialize_workspace(self.root)
        workspace.email_sync.unlink()
        workspace.email_events.unlink()
        loaded = load_workspace(self.root)
        self.assertEqual(read_json(loaded.email_sync), DEFAULT_EMAIL_SYNC_STATE)
        self.assertEqual(read_json(loaded.email_events), [])

    def test_bundle_write_updates_all_targets(self):
        workspace = initialize_workspace(self.root)
        write_json_bundle_atomic(
            {workspace.jobs: [{"job": 1}], workspace.applications: [{"application": 1}]},
            workspace.backups,
        )
        self.assertEqual(read_json(workspace.jobs), [{"job": 1}])
        self.assertEqual(read_json(workspace.applications), [{"application": 1}])

    def test_bundle_write_restores_all_targets_when_replace_fails(self):
        workspace = initialize_workspace(self.root)
        write_json_atomic(workspace.jobs, [{"old": "job"}], workspace.backups)
        write_json_atomic(
            workspace.applications, [{"old": "application"}], workspace.backups
        )
        real_replace = os.replace
        failed = False

        def fail_second_target(source, target):
            nonlocal failed
            source_path = Path(source)
            target_path = Path(target)
            if (
                not failed
                and target_path == workspace.jobs
                and source_path.name.startswith(".jobs.json.")
            ):
                failed = True
                raise OSError("simulated replace failure")
            return real_replace(source, target)

        with mock.patch("job_radar_lib.storage.os.replace", side_effect=fail_second_target):
            with self.assertRaisesRegex(OSError, "simulated replace failure"):
                write_json_bundle_atomic(
                    {
                        workspace.applications: [{"new": "application"}],
                        workspace.jobs: [{"new": "job"}],
                    },
                    workspace.backups,
                )
        self.assertEqual(read_json(workspace.jobs), [{"old": "job"}])
        self.assertEqual(read_json(workspace.applications), [{"old": "application"}])


if __name__ == "__main__":
    unittest.main()
