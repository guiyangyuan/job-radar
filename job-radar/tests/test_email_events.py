import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from job_radar_lib.applications import ApplicationConflict
from job_radar_lib.email_classification import EmailCandidate
from job_radar_lib.email_events import (
    EventConflict,
    build_error_event,
    build_event,
    confirm_event,
    merge_events,
    patch_event,
    set_event_ignored,
)
from job_radar_lib.imap_sync import FetchIssue, FetchedMessage
from job_radar_lib.storage import (
    initialize_workspace,
    read_json,
    write_json_atomic,
)
from tests.helpers import NOW, application, email_event, job


MAILBOX_HASH = "sha256:" + "d" * 64
EVENT_TIME = "2026-08-21T10:00:00+08:00"


def fetched(**overrides):
    value = {
        "uid_validity": 7,
        "uid": 42,
        "message_id": "<synthetic-42@example.com>",
        "received_at": "2026-08-21T10:30:00+08:00",
        "sender_domain": "jobs.example.com",
        "subject": "在线测评邀请",
        "text": "不应写入事件存储的正文",
        "has_attachments": False,
    }
    value.update(overrides)
    return FetchedMessage(**value)


def candidate(**overrides):
    value = {
        "company": "示例科技",
        "title": "AI 应用开发工程师",
        "employer_job_id": None,
        "proposed_status": "assessment",
        "interview_stage": None,
        "next_action": "完成在线测评",
        "next_action_at": "2026-08-25T23:59:00+08:00",
        "classification": "actionable",
        "confidence": 0.85,
        "reasons": ("检测到明确的 assessment 阶段证据",),
    }
    value.update(overrides)
    return EmailCandidate(**value)


class EmailEventBuildTests(unittest.TestCase):
    def test_exact_job_identifier_wins_over_title_similarity(self):
        jobs = [job(id="job_jr42", employerJobId="JR-42", title="后端开发")]
        applications = [
            application(id="app_for_jr42", jobId="job_jr42", title="后端开发")
        ]
        event = build_event(
            fetched(),
            candidate(title="前端开发", employer_job_id="JR-42"),
            MAILBOX_HASH,
            jobs,
            applications,
            NOW,
        )
        self.assertEqual(event["matchedApplicationId"], "app_for_jr42")
        self.assertTrue(any("职位编号" in reason for reason in event["reasons"]))

    def test_pending_event_never_mutates_application(self):
        original = application()
        event = build_event(
            fetched(), candidate(), MAILBOX_HASH, [job()], [original], NOW
        )
        self.assertEqual(event["state"], "pending")
        self.assertEqual(original["status"], "applied")
        self.assertNotIn("不应写入事件存储的正文", repr(event))

    def test_regression_and_terminal_targets_become_conflicts(self):
        for status, proposed in (("interview", "assessment"), ("rejected", "offer")):
            with self.subTest(status=status):
                current = application(status=status)
                event = build_event(
                    fetched(),
                    candidate(proposed_status=proposed),
                    MAILBOX_HASH,
                    [job()],
                    [current],
                    NOW,
                )
                self.assertEqual(event["classification"], "conflict")

    def test_older_email_than_application_version_is_conflict(self):
        current = application(updatedAt="2026-08-22T10:00:00+08:00")
        event = build_event(
            fetched(received_at="2026-08-21T09:00:00+08:00"),
            candidate(),
            MAILBOX_HASH,
            [job()],
            [current],
            NOW,
        )
        self.assertEqual(event["classification"], "conflict")

    def test_error_event_contains_only_minimized_fields(self):
        issue = FetchIssue(7, 42, None, None, "jobs.example.com", "坏邮件", "mime_parse_error")
        event = build_error_event(issue, MAILBOX_HASH, NOW)
        self.assertEqual(event["state"], "error")
        self.assertEqual(event["classification"], "incomplete")
        self.assertNotIn("body", event)

    def test_same_message_key_is_idempotent(self):
        first = email_event()
        merged, stats = merge_events([], [first])
        again, second_stats = merge_events(merged, [email_event(createdAt="2026-08-22T10:00:00+08:00")])
        self.assertEqual(len(again), 1)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(second_stats["unchanged"], 1)


class EmailEventLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = initialize_workspace(Path(self.tempdir.name) / "workspace")
        self.job = job()
        self.application = application()
        self.event = email_event(id="evt_1", updatedAt=EVENT_TIME, createdAt=EVENT_TIME)
        write_json_atomic(self.workspace.jobs, [self.job], self.workspace.backups)
        write_json_atomic(
            self.workspace.applications, [self.application], self.workspace.backups
        )
        write_json_atomic(
            self.workspace.email_events, [self.event], self.workspace.backups
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_patch_requires_exact_version_and_only_pending_fields(self):
        with self.assertRaises(EventConflict):
            patch_event(self.event, {"title": "新岗位"}, NOW, "stale")
        patched = patch_event(
            self.event, {"title": "新岗位"}, NOW, EVENT_TIME
        )
        self.assertEqual(patched["title"], "新岗位")
        self.assertEqual(patched["updatedAt"], NOW.isoformat())
        with self.assertRaisesRegex(ValueError, "unsupported email event fields"):
            patch_event(self.event, {"senderDomain": "evil.example"}, NOW, EVENT_TIME)

    def test_ignore_and_restore_are_optimistic(self):
        ignored = set_event_ignored(
            "evt_1", True, self.workspace, NOW, expected_updated_at=EVENT_TIME
        )
        self.assertEqual(ignored["state"], "ignored")
        restored = set_event_ignored(
            "evt_1",
            False,
            self.workspace,
            NOW + timedelta(minutes=1),
            expected_updated_at=ignored["updatedAt"],
        )
        self.assertEqual(restored["state"], "pending")

    def test_confirm_updates_application_and_email_history(self):
        result = confirm_event(
            "evt_1",
            {
                "confirmed": True,
                "status": "assessment",
                "applicationId": "app_example",
                "updatedAt": EVENT_TIME,
                "applicationUpdatedAt": self.application["updatedAt"],
            },
            self.workspace,
            NOW,
        )
        updated = read_json(self.workspace.applications)[0]
        self.assertEqual(updated["status"], "assessment")
        self.assertEqual(updated["history"][-1]["channel"], "email")
        self.assertEqual(result["event"]["state"], "confirmed")

    def test_confirmation_requires_explicit_consent_and_versions(self):
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            confirm_event(
                "evt_1",
                {"confirmed": False},
                self.workspace,
                NOW,
            )
        with self.assertRaises(ApplicationConflict):
            confirm_event(
                "evt_1",
                {
                    "confirmed": True,
                    "status": "assessment",
                    "applicationId": "app_example",
                    "updatedAt": EVENT_TIME,
                    "applicationUpdatedAt": "stale",
                },
                self.workspace,
                NOW,
            )

    def test_confirmation_rolls_back_when_bundle_write_fails(self):
        payload = {
            "confirmed": True,
            "status": "assessment",
            "applicationId": "app_example",
            "updatedAt": EVENT_TIME,
            "applicationUpdatedAt": self.application["updatedAt"],
        }
        with mock.patch(
            "job_radar_lib.email_events.write_json_bundle_atomic",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                confirm_event("evt_1", payload, self.workspace, NOW)
        self.assertEqual(read_json(self.workspace.email_events)[0]["state"], "pending")
        self.assertEqual(read_json(self.workspace.applications)[0]["status"], "applied")

    def test_confirm_can_create_a_new_email_confirmed_application(self):
        unmatched = email_event(
            id="evt_new",
            matchedApplicationId=None,
            company="新公司",
            title="Agent 开发工程师",
            proposedStatus="interview",
        )
        write_json_atomic(
            self.workspace.email_events, [unmatched], self.workspace.backups
        )
        result = confirm_event(
            "evt_new",
            {
                "confirmed": True,
                "status": "interview",
                "applicationId": None,
                "updatedAt": unmatched["updatedAt"],
                "applicationUpdatedAt": None,
                "company": "新公司",
                "title": "Agent 开发工程师",
                "recruitmentType": "campus",
            },
            self.workspace,
            NOW,
        )
        created = next(
            item
            for item in read_json(self.workspace.applications)
            if item["id"] == result["application"]["id"]
        )
        self.assertEqual(created["status"], "interview")
        self.assertEqual(created["history"][-1]["channel"], "email")
        created_job = next(
            item for item in read_json(self.workspace.jobs) if item["id"] == created["jobId"]
        )
        self.assertEqual(created_job["verificationState"], "email_confirmed")


if __name__ == "__main__":
    unittest.main()
