import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import company_policy, job, official_job, profile


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


if __name__ == "__main__":
    unittest.main()
