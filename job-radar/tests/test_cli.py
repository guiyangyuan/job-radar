import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import job_radar
from job_radar_lib.imap_sync import FetchedMessage, SyncBatch
from tests.helpers import (
    application,
    company_policy,
    email_event,
    email_sync_state,
    job,
    official_job,
    profile,
)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "job_radar.py"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = self.root / "job-radar-data"
        self.incoming = self.root / "incoming.json"
        self.export = self.root / "dashboard.html"

    def tearDown(self):
        self.tempdir.cleanup()

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(CLI), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def run_ok(self, *arguments):
        result = self.run_cli(*arguments)
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def write_confirmed_profile(self):
        (self.workspace / "profile.json").write_text(
            json.dumps(profile(), ensure_ascii=False), encoding="utf-8"
        )

    def test_full_offline_workflow(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        self.write_confirmed_profile()
        self.run_ok("validate", "--workspace", str(self.workspace))
        self.incoming.write_text(
            json.dumps([official_job(id=None)], ensure_ascii=False), encoding="utf-8"
        )
        self.run_ok(
            "merge-jobs",
            "--workspace",
            str(self.workspace),
            "--input",
            str(self.incoming),
        )
        self.run_ok(
            "score",
            "--workspace",
            str(self.workspace),
            "--now",
            "2026-08-21T10:00:00+08:00",
        )
        jobs = json.loads((self.workspace / "jobs.json").read_text(encoding="utf-8"))
        self.assertEqual(jobs[0]["score"], 100)
        job_id = jobs[0]["id"]
        self.run_ok(
            "apply",
            "--workspace",
            str(self.workspace),
            "--job-id",
            job_id,
            "--confirmed",
        )
        applications = json.loads(
            (self.workspace / "applications.json").read_text(encoding="utf-8")
        )
        app_id = applications[0]["id"]
        self.run_ok(
            "update",
            "--workspace",
            str(self.workspace),
            "--application-id",
            app_id,
            "--status",
            "screening",
            "--next-action",
            "准备技术面试",
        )
        self.run_ok(
            "export",
            "--workspace",
            str(self.workspace),
            "--output",
            str(self.export),
            "--privacy",
        )
        summary = self.run_ok(
            "summary", "--workspace", str(self.workspace), "--json"
        )
        self.assertEqual(json.loads(summary.stdout)["applications"]["screening"], 1)
        self.assertTrue(self.export.exists())
        self.assertIn("只读快照", self.export.read_text(encoding="utf-8"))

    def test_apply_without_confirmation_writes_nothing(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        (self.workspace / "jobs.json").write_text(
            json.dumps([official_job(id="j1")], ensure_ascii=False), encoding="utf-8"
        )
        result = self.run_cli(
            "apply", "--workspace", str(self.workspace), "--job-id", "j1"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit confirmation", result.stderr)
        self.assertEqual(
            json.loads(
                (self.workspace / "applications.json").read_text(encoding="utf-8")
            ),
            [],
        )
        self.assertEqual(
            json.loads((self.workspace / "jobs.json").read_text(encoding="utf-8"))[0][
                "poolStatus"
            ],
            "discovered",
        )

    def test_score_requires_confirmed_profile(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        result = self.run_cli(
            "score",
            "--workspace",
            str(self.workspace),
            "--now",
            "2026-08-21T10:00:00+08:00",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("profile must be confirmed", result.stderr)

    def test_migrate_links_preserves_status_and_adds_link_metadata(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        value = job(
            poolStatus="preparing",
            linkType=None,
            linkUrl=None,
            officialUrl="https://talent.baidu.com/jobs/detail/GRADUATE/abc",
        )
        (self.workspace / "jobs.json").write_text(
            json.dumps([value], ensure_ascii=False), encoding="utf-8"
        )

        result = self.run_cli(
            "migrate-links", "--workspace", str(self.workspace)
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(json.loads(result.stdout)["migrated"], 1)
        migrated = json.loads(
            (self.workspace / "jobs.json").read_text(encoding="utf-8")
        )[0]
        self.assertEqual(migrated["poolStatus"], "preparing")
        self.assertEqual(migrated["linkType"], "detail")

    def test_merge_policies_validates_and_writes_canonical_file(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        self.incoming.write_text(
            json.dumps([company_policy()], ensure_ascii=False), encoding="utf-8"
        )

        result = self.run_cli(
            "merge-policies",
            "--workspace",
            str(self.workspace),
            "--input",
            str(self.incoming),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        policies = json.loads(
            (self.workspace / "company-policies.json").read_text(encoding="utf-8")
        )
        self.assertEqual(policies[0]["maxApplications"], 1)
        validation = self.run_ok("validate", "--workspace", str(self.workspace))
        self.assertEqual(json.loads(validation.stdout)["companyPolicies"], 1)

    def test_email_test_has_no_password_argument(self):
        result = self.run_cli("email-test", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("--password", result.stdout)
        self.assertNotIn("--app-password", result.stdout)

    def test_email_test_missing_config_has_safe_error(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        with mock.patch.dict(os.environ, {}, clear=True):
            stderr = io.StringIO()
            with mock.patch("sys.stderr", stderr):
                code = job_radar.main(
                    ["email-test", "--workspace", str(self.workspace)]
                )
        self.assertEqual(code, 2)
        self.assertIn("JOB_RADAR_IMAP_USERNAME is not set", stderr.getvalue())

    def test_email_sync_persists_events_but_not_applications(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        before = (self.workspace / "applications.json").read_text(encoding="utf-8")
        fetched = FetchedMessage(
            uid_validity=7,
            uid=42,
            message_id="<synthetic@example.com>",
            received_at="2026-08-21T09:30:00+08:00",
            sender_domain="jobs.example.com",
            subject="在线测评邀请",
            text="公司：示例科技\n应聘岗位：AI 应用开发工程师\n请完成在线测评",
            has_attachments=False,
        )
        batch = SyncBatch(
            messages=[fetched],
            issues=[],
            state=email_sync_state(lastSeenUid=42),
        )
        safe_env = {
            "JOB_RADAR_IMAP_USERNAME": "candidate@qq.com",
            "JOB_RADAR_IMAP_APP_PASSWORD": "synthetic-secret",
            "JOB_RADAR_IMAP_PROVIDER": "qq",
        }
        output = io.StringIO()
        with mock.patch.dict(os.environ, safe_env, clear=True), mock.patch(
            "job_radar.sync_messages", return_value=batch
        ), redirect_stdout(output):
            code = job_radar.main(
                [
                    "email-sync",
                    "--workspace",
                    str(self.workspace),
                    "--days",
                    "60",
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(
            (self.workspace / "applications.json").read_text(encoding="utf-8"),
            before,
        )
        events = json.loads(
            (self.workspace / "email-events.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["state"], "pending")
        self.assertNotIn("请完成在线测评", repr(events))

    def test_email_summary_separates_pending_from_canonical_statuses(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        (self.workspace / "applications.json").write_text(
            json.dumps([application()], ensure_ascii=False), encoding="utf-8"
        )
        (self.workspace / "email-events.json").write_text(
            json.dumps([email_event()], ensure_ascii=False), encoding="utf-8"
        )
        result = self.run_ok(
            "email-summary", "--workspace", str(self.workspace), "--json"
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["emailEvents"]["pending"], 1)
        self.assertEqual(payload["emailEvents"]["classifications"]["actionable"], 1)
        self.assertEqual(payload["applications"]["applied"], 1)

    def test_email_sync_rejects_invalid_window(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        result = self.run_cli(
            "email-sync",
            "--workspace",
            str(self.workspace),
            "--days",
            "0",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("1 to 3650", result.stderr)

    def test_validate_checks_email_files_and_rejects_secret_fields(self):
        self.run_ok("init", "--workspace", str(self.workspace))
        invalid = email_sync_state(appPassword="must-not-be-stored")
        (self.workspace / "email-sync.json").write_text(
            json.dumps(invalid), encoding="utf-8"
        )
        result = self.run_cli("validate", "--workspace", str(self.workspace))
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown email sync fields", result.stderr)


if __name__ == "__main__":
    unittest.main()
