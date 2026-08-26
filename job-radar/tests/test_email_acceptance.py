import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import job_radar
from job_radar_lib.email_events import confirm_event
from job_radar_lib.imap_sync import FetchedMessage, SyncBatch
from job_radar_lib.rendering import write_export
from job_radar_lib.storage import initialize_workspace, read_json, write_json_atomic
from tests.helpers import NOW, application, email_sync_state, job


def recruitment_message(uid, subject, text):
    return FetchedMessage(
        uid_validity=7,
        uid=uid,
        message_id=f"<synthetic-{uid}@example.com>",
        received_at="2026-08-21T10:30:00+08:00",
        sender_domain="jobs.example.com",
        subject=subject,
        text=(
            "公司：示例科技\n应聘岗位：AI 应用开发工程师\n" + text
        ),
        has_attachments=False,
    )


class EmailAcceptanceTests(unittest.TestCase):
    def test_five_message_sync_review_confirm_and_privacy_export(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = initialize_workspace(Path(tempdir) / "job-radar-data")
            current_application = application()
            write_json_atomic(workspace.jobs, [job()], workspace.backups)
            write_json_atomic(
                workspace.applications, [current_application], workspace.backups
            )
            before = read_json(workspace.applications)
            messages = [
                recruitment_message(41, "投递成功", "您的申请已收到"),
                recruitment_message(42, "在线测评", "请完成在线测评"),
                recruitment_message(43, "技术一面", "邀请参加技术一面"),
                recruitment_message(44, "未通过", "很遗憾本次流程未能继续"),
                recruitment_message(45, "加入人才库", "订阅校招资讯与宣讲会"),
            ]
            batch = SyncBatch(messages, [], email_sync_state(lastSeenUid=45))
            safe_env = {
                "JOB_RADAR_IMAP_USERNAME": "candidate@qq.com",
                "JOB_RADAR_IMAP_APP_PASSWORD": "synthetic-app-secret",
                "JOB_RADAR_IMAP_PROVIDER": "qq",
            }
            with mock.patch.dict(os.environ, safe_env, clear=True), mock.patch(
                "job_radar.sync_messages", return_value=batch
            ):
                result = job_radar.run_email_sync(
                    workspace, 60, NOW, env=safe_env
                )
            self.assertEqual(result["fetched"], 5)
            self.assertEqual(result["added"], 5)
            self.assertEqual(result["actionable"], 4)
            self.assertEqual(result["irrelevant"], 1)
            self.assertEqual(read_json(workspace.applications), before)

            events = read_json(workspace.email_events)
            assessment = next(
                event for event in events if event["proposedStatus"] == "assessment"
            )
            confirm_event(
                assessment["id"],
                {
                    "confirmed": True,
                    "status": "assessment",
                    "applicationId": "app_example",
                    "updatedAt": assessment["updatedAt"],
                    "applicationUpdatedAt": current_application["updatedAt"],
                },
                workspace,
                NOW,
            )
            confirmed = read_json(workspace.applications)[0]
            self.assertEqual(confirmed["status"], "assessment")
            self.assertEqual(confirmed["history"][-1]["channel"], "email")

            output = write_export(workspace, privacy=True)
            html = output.read_text(encoding="utf-8")
            for private_value in (
                "在线测评邀请",
                "加入人才库",
                "jobs.example.com",
                "lastSeenUid",
                "messageKeyHash",
                "synthetic-app-secret",
                "candidate@qq.com",
            ):
                self.assertNotIn(private_value, html)


if __name__ == "__main__":
    unittest.main()
