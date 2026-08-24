import unittest

from job_radar_lib.applications import (
    ApplicationConflict,
    ApplicationNotFound,
    archive_application,
    create_application,
    find_application,
    update_application,
)
from job_radar_lib.models import ValidationError

from tests.helpers import NOW, application, job


class ApplicationTests(unittest.TestCase):
    def test_creation_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            create_application(job(), NOW, confirmed=False)

    def test_creation_marks_job_applied_and_records_history(self):
        created, updated_job = create_application(job(), NOW, confirmed=True)
        self.assertEqual(created["status"], "applied")
        self.assertEqual(updated_job["poolStatus"], "applied")
        self.assertEqual(created["history"][0]["channel"], "conversation")
        self.assertEqual(
            created["history"][0]["changes"]["status"],
            {"old": None, "new": "applied"},
        )
        self.assertNotEqual(created["id"], "app_example")
        self.assertNotIn("descriptionSummary", created)

    def test_update_records_old_and_new_values(self):
        updated = update_application(
            application(),
            {"status": "interview", "interviewStage": "一面"},
            NOW,
            "dashboard",
        )
        event = updated["history"][-1]
        self.assertEqual(
            event["changes"]["status"],
            {"old": "applied", "new": "interview"},
        )
        self.assertEqual(
            event["changes"]["interviewStage"],
            {"old": None, "new": "一面"},
        )
        self.assertEqual(event["channel"], "dashboard")

    def test_stale_version_is_rejected(self):
        with self.assertRaises(ApplicationConflict):
            update_application(
                application(),
                {"status": "screening"},
                NOW,
                "dashboard",
                expected_updated_at="stale",
            )

    def test_unknown_update_field_and_channel_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported update fields"):
            update_application(application(), {"company": "篡改"}, NOW, "dashboard")
        with self.assertRaisesRegex(ValueError, "unsupported update channel"):
            update_application(application(), {"status": "screening"}, NOW, "unknown")

    def test_invalid_evidence_link_is_rejected(self):
        with self.assertRaises(ValidationError):
            update_application(
                application(),
                {"evidenceLinks": ["javascript:alert(1)"]},
                NOW,
                "dashboard",
            )

    def test_no_change_does_not_create_history_noise(self):
        original = application()
        updated = update_application(
            original,
            {"status": "applied"},
            NOW,
            "dashboard",
            expected_updated_at=original["updatedAt"],
        )
        self.assertEqual(updated, original)

    def test_archive_preserves_the_record(self):
        updated = archive_application(application(), NOW, "dashboard")
        self.assertEqual(updated["status"], "archived")
        self.assertTrue(updated["history"])

    def test_find_application_has_typed_not_found_error(self):
        self.assertEqual(
            find_application([application()], "app_example")["company"],
            "示例科技",
        )
        with self.assertRaises(ApplicationNotFound):
            find_application([application()], "missing")


if __name__ == "__main__":
    unittest.main()
