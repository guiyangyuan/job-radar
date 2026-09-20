import concurrent.futures
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from job_radar_lib.server import create_server
from job_radar_lib.storage import initialize_workspace, read_json, write_json_atomic

from tests.helpers import application, company_policy, email_event, job


EVENT_TIME = "2026-08-21T10:00:00+08:00"


class BlockingRunner:
    def __init__(self):
        self.started = threading.Event()
        self.release_event = threading.Event()

    def __call__(self, workspace, days):
        self.started.set()
        self.release_event.wait(timeout=2)
        return {"fetched": 0, "added": 0, "days": days}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = initialize_workspace(Path(self.tempdir.name) / "data")
        write_json_atomic(
            self.workspace.applications, [application()], self.workspace.backups
        )
        write_json_atomic(self.workspace.jobs, [job()], self.workspace.backups)
        write_json_atomic(
            self.workspace.email_events,
            [email_event(id="evt_1", createdAt=EVENT_TIME, updatedAt=EVENT_TIME)],
            self.workspace.backups,
        )
        self.token = "test-token"
        self.server = create_server(self.workspace, "127.0.0.1", 0, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def restart_server(self, email_sync_runner):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server = create_server(
            self.workspace,
            "127.0.0.1",
            0,
            self.token,
            email_sync_runner=email_sync_runner,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tempdir.cleanup()

    def request(
        self,
        method,
        path,
        *,
        token=None,
        origin=None,
        body=None,
        headers=None,
    ):
        request_headers = dict(headers or {})
        if token:
            request_headers["X-Job-Radar-Token"] = token
        if origin:
            request_headers["Origin"] = origin
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection(self.host, self.port, timeout=3)
        connection.request(method, path, body=encoded, headers=request_headers)
        response = connection.getresponse()
        result = SimpleNamespace(
            status=response.status,
            body=response.read(),
            headers=dict(response.getheaders()),
        )
        connection.close()
        return result

    def test_summary_is_available_with_token_and_security_headers(self):
        response = self.request("GET", "/api/summary", token=self.token)
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload["jobs"], 1)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_query_token_establishes_strict_http_only_cookie(self):
        response = self.request("GET", "/?token=" + self.token)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/")
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        dashboard = self.request("GET", "/", headers={"Cookie": cookie.split(";", 1)[0]})
        self.assertEqual(dashboard.status, 200)
        self.assertIn("求职工作台".encode(), dashboard.body)

    def test_missing_or_wrong_token_is_rejected(self):
        self.assertEqual(self.request("GET", "/api/jobs").status, 403)
        self.assertEqual(
            self.request("GET", "/api/jobs", token="wrong-token").status,
            403,
        )

    def test_unexpected_host_and_cross_origin_write_are_rejected(self):
        bad_host = self.request(
            "GET", "/api/jobs", token=self.token, headers={"Host": "evil.example"}
        )
        self.assertEqual(bad_host.status, 403)
        response = self.request(
            "PATCH",
            "/api/applications/app_example",
            token=self.token,
            origin="https://evil.example",
            body={"status": "interview", "updatedAt": application()["updatedAt"]},
        )
        self.assertEqual(response.status, 403)

    def test_patch_updates_canonical_json(self):
        current = application()
        response = self.request(
            "PATCH",
            f"/api/applications/{current['id']}",
            token=self.token,
            body={"status": "screening", "updatedAt": current["updatedAt"]},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            read_json(self.workspace.applications)[0]["status"], "screening"
        )

    def test_stale_patch_returns_conflict_without_writing(self):
        response = self.request(
            "PATCH",
            "/api/applications/app_example",
            token=self.token,
            body={"status": "screening", "updatedAt": "stale"},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(read_json(self.workspace.applications)[0]["status"], "applied")

    def test_application_creation_requires_confirmation_and_updates_job(self):
        denied = self.request(
            "POST",
            "/api/applications",
            token=self.token,
            body={"jobId": "job_example", "confirmed": False},
        )
        self.assertEqual(denied.status, 400)
        write_json_atomic(self.workspace.applications, [], self.workspace.backups)
        created = self.request(
            "POST",
            "/api/applications",
            token=self.token,
            body={"jobId": "job_example", "confirmed": True},
        )
        self.assertEqual(created.status, 201)
        self.assertEqual(read_json(self.workspace.jobs)[0]["poolStatus"], "applied")
        self.assertEqual(read_json(self.workspace.applications)[0]["status"], "applied")

    def test_job_patch_and_private_export_use_canonical_storage(self):
        patched = self.request(
            "PATCH",
            "/api/jobs/job_example",
            token=self.token,
            body={"updates": {"poolStatus": "saved"}},
        )
        self.assertEqual(patched.status, 200)
        self.assertEqual(read_json(self.workspace.jobs)[0]["poolStatus"], "saved")
        exported = self.request(
            "POST", "/api/export", token=self.token, body={"privacy": True}
        )
        self.assertEqual(exported.status, 200)
        self.assertTrue((self.workspace.exports / "dashboard.html").is_file())

    def test_oversized_body_is_rejected(self):
        response = self.request(
            "POST",
            "/api/export",
            token=self.token,
            headers={"Content-Length": str(1024 * 1024 + 1)},
        )
        self.assertEqual(response.status, 413)

    def test_non_loopback_binding_is_refused(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_server(self.workspace, "0.0.0.0", 0, self.token)

    def test_company_policies_are_available_with_token(self):
        write_json_atomic(
            self.workspace.company_policies,
            [company_policy()],
            self.workspace.backups,
        )

        response = self.request("GET", "/api/company-policies", token=self.token)

        self.assertEqual(response.status, 200)
        self.assertEqual(
            json.loads(response.body)["companyPolicies"][0]["maxApplications"],
            1,
        )

    def test_dashboard_loads_policy_file_without_enabling_policy_writes(self):
        response = self.request("GET", "/", token=self.token)

        self.assertEqual(response.status, 200)
        denied = self.request(
            "PATCH",
            "/api/company-policies/example",
            token=self.token,
            body={"maxApplications": 99},
        )
        self.assertEqual(denied.status, 404)

    def test_email_routes_require_session_token(self):
        self.assertEqual(self.request("GET", "/api/email-events").status, 403)
        self.assertEqual(
            self.request("POST", "/api/email-sync/run", body={"days": 60}).status,
            403,
        )

    def test_email_status_and_summary_redact_mailbox_identity(self):
        response = self.request("GET", "/api/email-sync/status", token=self.token)
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body)
        self.assertNotIn("mailboxHash", payload)
        self.assertNotIn("username", payload)
        summary = json.loads(
            self.request("GET", "/api/summary", token=self.token).body
        )
        self.assertEqual(summary["pendingEmailEvents"], 1)

    def test_sync_is_single_flight(self):
        runner = BlockingRunner()
        self.restart_server(runner)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(
                self.request,
                "POST",
                "/api/email-sync/run",
                token=self.token,
                body={"days": 60},
            )
            self.assertTrue(runner.started.wait(timeout=1))
            second = self.request(
                "POST",
                "/api/email-sync/run",
                token=self.token,
                body={"days": 60},
            )
            self.assertEqual(second.status, 409)
            runner.release_event.set()
            self.assertEqual(first.result(timeout=2).status, 200)

    def test_email_event_list_patch_ignore_and_restore(self):
        listed = self.request("GET", "/api/email-events", token=self.token)
        self.assertEqual(listed.status, 200)
        self.assertEqual(len(json.loads(listed.body)["events"]), 1)
        patched = self.request(
            "PATCH",
            "/api/email-events/evt_1",
            token=self.token,
            body={"updates": {"title": "Agent 开发"}, "updatedAt": EVENT_TIME},
        )
        self.assertEqual(patched.status, 200)
        patched_event = json.loads(patched.body)["event"]
        self.assertEqual(patched_event["title"], "Agent 开发")
        ignored = self.request(
            "POST",
            "/api/email-events/evt_1/ignore",
            token=self.token,
            body={"ignored": True, "updatedAt": patched_event["updatedAt"]},
        )
        self.assertEqual(ignored.status, 200)
        ignored_event = json.loads(ignored.body)["event"]
        self.assertEqual(ignored_event["state"], "ignored")
        restored = self.request(
            "POST",
            "/api/email-events/evt_1/ignore",
            token=self.token,
            body={"ignored": False, "updatedAt": ignored_event["updatedAt"]},
        )
        self.assertEqual(restored.status, 200)
        self.assertEqual(json.loads(restored.body)["event"]["state"], "pending")

    def test_confirm_rejects_stale_application_version(self):
        response = self.request(
            "POST",
            "/api/email-events/evt_1/confirm",
            token=self.token,
            body={
                "confirmed": True,
                "applicationId": "app_example",
                "status": "interview",
                "updatedAt": EVENT_TIME,
                "applicationUpdatedAt": "stale",
            },
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(read_json(self.workspace.applications)[0]["status"], "applied")

    def test_confirm_updates_application_with_email_audit_history(self):
        response = self.request(
            "POST",
            "/api/email-events/evt_1/confirm",
            token=self.token,
            body={
                "confirmed": True,
                "applicationId": "app_example",
                "status": "assessment",
                "updatedAt": EVENT_TIME,
                "applicationUpdatedAt": application()["updatedAt"],
            },
        )
        self.assertEqual(response.status, 200)
        updated = read_json(self.workspace.applications)[0]
        self.assertEqual(updated["status"], "assessment")
        self.assertEqual(updated["history"][-1]["channel"], "email")

    def test_email_routes_reject_unknown_payload_fields(self):
        response = self.request(
            "POST",
            "/api/email-events/evt_1/ignore",
            token=self.token,
            body={"ignored": True, "updatedAt": EVENT_TIME, "secret": "no"},
        )
        self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main()
