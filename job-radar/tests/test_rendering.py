import tempfile
import unittest
from pathlib import Path

from job_radar_lib.rendering import render_dashboard, write_export
from job_radar_lib.storage import initialize_workspace, write_json_atomic

from tests.helpers import company_policy, sample_data, sample_data_with_email


class RenderingTests(unittest.TestCase):
    def test_dashboard_keeps_company_workbench_and_email_tabs(self):
        html = render_dashboard(sample_data(), editable=True, privacy=False)
        self.assertIn('data-tab="recommendations"', html)
        self.assertIn('data-tab="applications"', html)
        self.assertIn('data-tab="email"', html)
        self.assertIn('data-tab="overview"', html)
        self.assertIn('data-action="application-status"', html)
        self.assertIn("岗位推荐", html)
        self.assertIn("投递进度", html)
        self.assertIn("待选择公司", html)
        self.assertIn("面试中", html)

    def test_recommendation_ui_is_link_first_and_hides_explanations(self):
        html = render_dashboard(sample_data(), editable=True, privacy=False)

        self.assertIn("job-title-link", html)
        self.assertIn("company-mark", html)
        self.assertIn("高级筛选", html)
        self.assertIn("查看其他岗位（", html)
        self.assertNotIn("展开详情", html)
        self.assertNotIn("推荐理由", html)
        self.assertNotIn("待确认 / 缺口", html)
        self.assertNotIn("评分明细", html)

    def test_application_editor_only_exposes_status(self):
        html = render_dashboard(sample_data(), editable=True, privacy=False)
        application_renderer = html.split("function renderApplications()", 1)[1].split(
            "function showEmailConflict()", 1
        )[0]

        self.assertIn('data-action="application-status"', html)
        self.assertIn("被拒绝", html)
        self.assertNotIn("面试阶段", application_renderer)
        self.assertNotIn("下一步行动", application_renderer)
        self.assertNotIn("截止时间", application_renderer)
        self.assertNotIn("备注", application_renderer)
        self.assertNotIn("证据链接", application_renderer)
        self.assertNotIn("归档记录", application_renderer)
        self.assertNotIn("查看修改历史", application_renderer)

    def test_link_labels_are_specific(self):
        data = sample_data()
        data["jobs"][0].update(
            linkType="listing",
            linkUrl="https://company.example/jobs",
            linkSearchHint="J103964",
        )

        html = render_dashboard(data, editable=True, privacy=False)

        self.assertIn("前往岗位列表", html)
        self.assertIn("需搜索：", html)
        self.assertIn("J103964", html)
        self.assertNotIn("查看岗位官网", html)

    def test_untrusted_text_cannot_close_script(self):
        html = render_dashboard(
            sample_data(title="</script><script>alert(1)</script>"),
            editable=False,
            privacy=False,
        )
        self.assertNotIn("</script><script>alert(1)</script>", html)
        self.assertIn("\\u003c/script", html)

    def test_privacy_export_omits_notes_evidence_and_history_copies(self):
        data = sample_data(notes="private-note", evidenceLinks=["https://private.example"])
        data["applications"][0]["history"] = [
            {
                "timestamp": "2026-08-21T10:00:00+08:00",
                "channel": "dashboard",
                "changes": {
                    "notes": {"old": "", "new": "private-note"},
                    "evidenceLinks": {"old": [], "new": ["https://private.example"]},
                },
            }
        ]
        html = render_dashboard(data, editable=False, privacy=True)
        self.assertNotIn("private-note", html)
        self.assertNotIn("private.example", html)

    def test_static_export_is_read_only(self):
        html = render_dashboard(sample_data(), editable=False, privacy=False)
        self.assertNotIn('data-action="application-status"', html)
        self.assertIn("只读快照", html)

    def test_dashboard_is_self_contained_and_uses_safe_dom_rendering(self):
        html = render_dashboard(sample_data(), editable=True, privacy=False)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("<link rel=", html)
        self.assertNotIn("innerHTML", html)
        self.assertIn("textContent", html)
        self.assertIn("async function api", html)

    def test_mobile_layout_keeps_primary_action_above_expanded_details(self):
        html = render_dashboard(sample_data(), editable=True, privacy=False)

        self.assertIn("@media (max-width: 680px)", html)
        self.assertIn(
            ".compact-metrics { grid-template-columns: repeat(5, 1fr)", html
        )
        self.assertIn(
            ".filter-main { grid-template-columns: repeat(2, minmax(0, 1fr))",
            html,
        )
        self.assertIn(".filter-main input { grid-column: span 2; }", html)

    def test_write_export_reads_canonical_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = initialize_workspace(Path(tempdir) / "data")
            data = sample_data(notes="private-note")
            write_json_atomic(workspace.profile, data["profile"], workspace.backups)
            write_json_atomic(workspace.jobs, data["jobs"], workspace.backups)
            write_json_atomic(
                workspace.applications, data["applications"], workspace.backups
            )
            output = write_export(workspace, privacy=True)
            self.assertEqual(output, workspace.exports / "dashboard.html")
            self.assertTrue(output.is_file())
            self.assertNotIn("private-note", output.read_text(encoding="utf-8"))

    def test_dashboard_embeds_company_groups_and_policies(self):
        data = sample_data()
        data["companyPolicies"] = [
            company_policy(company=data["jobs"][0]["company"])
        ]

        html = render_dashboard(data, editable=True, privacy=False)

        self.assertIn('"companyGroups"', html)
        self.assertIn('"companyPolicies"', html)
        self.assertIn("限投 1 个", html)

    def test_static_export_keeps_policy_evidence_but_removes_private_data(self):
        data = sample_data(notes="private-note")
        data["companyPolicies"] = [company_policy()]

        html = render_dashboard(data, editable=False, privacy=True)

        self.assertIn("careers.dji.com", html)
        self.assertNotIn("private-note", html)

    def test_editable_dashboard_has_email_sync_controls(self):
        html = render_dashboard(
            sample_data_with_email(), editable=True, privacy=False
        )
        self.assertIn('data-tab="email"', html)
        self.assertIn('data-action="email-sync"', html)
        self.assertIn('data-action="email-confirm"', html)
        self.assertIn("状态冲突", html)
        self.assertIn("邮件进度", html)

    def test_privacy_export_omits_all_email_metadata(self):
        html = render_dashboard(
            sample_data_with_email(), editable=False, privacy=True
        )
        for secretish in (
            "技术面试邀请",
            "jobs.example.com",
            "sha256:" + "a" * 64,
            "lastSeenUid",
            "messageKeyHash",
        ):
            self.assertNotIn(secretish, html)

    def test_readonly_export_has_no_email_mutation_controls(self):
        html = render_dashboard(
            sample_data_with_email(), editable=False, privacy=False
        )
        self.assertIn('data-tab="email"', html)
        self.assertNotIn('data-action="email-confirm"', html)
        self.assertNotIn('data-action="email-sync"', html)

    def test_email_event_values_use_safe_dom_rendering(self):
        data = sample_data_with_email()
        data["emailEvents"][0]["company"] = "</script><script>alert(1)</script>"
        html = render_dashboard(data, editable=True, privacy=False)
        self.assertNotIn("</script><script>alert(1)</script>", html)
        self.assertIn("\\u003c/script", html)
        self.assertNotIn("innerHTML", html)


if __name__ == "__main__":
    unittest.main()
