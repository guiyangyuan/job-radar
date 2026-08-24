import unittest

from job_radar_lib.recommendations import build_company_groups
from tests.helpers import application, company_policy, job


class RecommendationTests(unittest.TestCase):
    def test_company_group_exposes_one_primary_and_two_alternatives(self):
        jobs = [
            job(id=f"job_{index}", title=f"岗位 {index}", score=score)
            for index, score in enumerate((91, 84, 76, 60))
        ]

        group = build_company_groups(jobs, [], [])[0]

        self.assertEqual(group["primary"]["score"], 91)
        self.assertEqual(
            [item["score"] for item in group["alternatives"]], [84, 76]
        )
        self.assertEqual(len(group["remaining"]), 1)

    def test_direct_link_wins_equal_score_tie(self):
        listing = job(
            id="listing",
            score=80,
            linkType="listing",
            linkUrl="https://company.example/jobs",
        )
        detail = job(
            id="detail",
            score=80,
            linkType="detail",
            linkUrl="https://company.example/jobs/42",
        )

        group = build_company_groups([listing, detail], [], [])[0]

        self.assertEqual(group["primary"]["id"], "detail")
        self.assertEqual(group["primary"]["resolvedLink"]["label"], "查看职位详情")

    def test_applied_job_does_not_displace_actionable_primary(self):
        applied_job = job(id="applied", score=95, poolStatus="applied")
        actionable = job(id="actionable", score=80, poolStatus="discovered")

        group = build_company_groups([applied_job, actionable], [], [])[0]

        self.assertEqual(group["primary"]["id"], "actionable")
        self.assertEqual(group["remaining"][0]["id"], "applied")

    def test_verified_limit_marks_conflict_without_removing_jobs(self):
        jobs = [job(id="job_a"), job(id="job_b", title="备选岗位")]
        applications = [application(jobId="job_a", status="screening")]

        group = build_company_groups(
            jobs,
            applications,
            [company_policy(company="示例科技", maxApplications=1)],
        )[0]

        self.assertTrue(group["quotaConflict"])
        self.assertEqual(group["policyLabel"], "限投 1 个")
        self.assertEqual(group["activeApplicationCount"], 1)
        self.assertEqual(group["totalJobs"], 2)

    def test_missing_policy_is_explicitly_unknown(self):
        group = build_company_groups([job()], [], [])[0]

        self.assertIsNone(group["policy"])
        self.assertEqual(group["policyLabel"], "规则未核实")
        self.assertFalse(group["quotaConflict"])

    def test_group_without_actionable_job_has_no_primary(self):
        group = build_company_groups(
            [job(id="applied", poolStatus="applied")], [], []
        )[0]

        self.assertIsNone(group["primary"])
        self.assertEqual(group["alternatives"], [])
        self.assertEqual(group["remaining"][0]["id"], "applied")

    def test_company_sort_accepts_primary_job_without_published_date(self):
        undated = job(
            id="undated",
            company="未标注日期公司",
            title="AI 应用工程师",
            score=80,
            publishedAt=None,
        )
        dated = job(
            id="dated",
            company="有日期公司",
            title="前端开发工程师",
            score=80,
            publishedAt="2026-08-20T09:00:00+08:00",
        )

        groups = build_company_groups([dated, undated], [], [])

        self.assertEqual(
            [group["company"] for group in groups],
            ["有日期公司", "未标注日期公司"],
        )


if __name__ == "__main__":
    unittest.main()
