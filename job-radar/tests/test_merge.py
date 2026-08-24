import unittest

from job_radar_lib.merge import canonical_url, merge_jobs, stable_job_id

from tests.helpers import aggregator_job, job, official_job


class CanonicalUrlTests(unittest.TestCase):
    def test_tracking_parameters_and_fragment_do_not_change_identity(self):
        self.assertEqual(
            canonical_url(
                "HTTPS://COMPANY.EXAMPLE/jobs/42/?utm_source=feed&ref=home#details"
            ),
            "https://company.example/jobs/42",
        )

    def test_non_tracking_query_parameters_are_preserved_deterministically(self):
        self.assertEqual(
            canonical_url("https://company.example/jobs?a=2&b=1&utm_medium=email"),
            "https://company.example/jobs?a=2&b=1",
        )


class StableIdTests(unittest.TestCase):
    def test_stable_id_is_deterministic_and_ignores_city_order(self):
        first = official_job(id=None, cities=["上海", "北京"])
        second = official_job(
            id=None,
            cities=["北京", "上海"],
            officialUrl="https://mirror.example/another-url",
        )
        self.assertEqual(stable_job_id(first), stable_job_id(second))
        self.assertTrue(stable_job_id(first).startswith("job_"))

    def test_recruitment_type_changes_stable_id(self):
        self.assertNotEqual(
            stable_job_id(official_job(id=None, recruitmentType="campus")),
            stable_job_id(official_job(id=None, recruitmentType="experienced")),
        )


class MergeJobsTests(unittest.TestCase):
    def test_shared_listing_url_does_not_merge_different_job_titles(self):
        listing = "https://careers.example/campus/hot-jobs"
        first = job(
            id=None,
            employerJobId=None,
            title="AI 全栈开发工程师",
            linkType="listing",
            linkUrl=listing,
            officialUrl=listing,
        )
        second = job(
            id=None,
            employerJobId=None,
            title="大前端开发工程师",
            linkType="listing",
            linkUrl=listing,
            officialUrl=listing,
        )

        result = merge_jobs([], [first, second])

        self.assertEqual(result.added, 2)
        self.assertEqual(len(result.jobs), 2)

    def test_same_canonical_official_url_merges_and_official_source_wins(self):
        existing = aggregator_job(
            id="job_saved",
            title="AI工程师",
            poolStatus="saved",
            firstDiscoveredAt="2026-08-20T08:00:00+08:00",
            score=88,
            scoreBreakdown={"role": 30},
            recommendationReasons=["岗位匹配"],
        )
        incoming = official_job(
            id="temporary",
            title="AI 应用开发工程师",
            descriptionSummary="官网完整描述",
            lastVerifiedAt="2026-08-21T10:00:00+08:00",
        )

        result = merge_jobs([existing], [incoming])

        self.assertEqual((result.added, result.updated, result.unchanged), (0, 1, 0))
        self.assertEqual(len(result.jobs), 1)
        merged = result.jobs[0]
        self.assertEqual(merged["id"], "job_saved")
        self.assertEqual(merged["poolStatus"], "saved")
        self.assertEqual(merged["firstDiscoveredAt"], "2026-08-20T08:00:00+08:00")
        self.assertEqual(merged["score"], 88)
        self.assertEqual(merged["title"], "AI 应用开发工程师")
        self.assertEqual(merged["descriptionSummary"], "官网完整描述")
        self.assertEqual(merged["sourceTier"], 1)
        self.assertEqual(
            {source["name"] for source in merged["sources"]},
            {"Employer", "Nowcoder"},
        )

    def test_same_composite_identity_merges_when_urls_differ(self):
        existing = aggregator_job(
            id="job_existing",
            officialUrl=None,
            applyUrl="https://nowcoder.example/apply/42",
        )
        incoming = official_job(
            id="incoming",
            officialUrl="https://careers.example/positions/9001",
            applyUrl="https://careers.example/positions/9001/apply",
        )

        result = merge_jobs([existing], [incoming])

        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["id"], "job_existing")
        self.assertEqual(
            result.jobs[0]["officialUrl"],
            "https://careers.example/positions/9001",
        )

    def test_different_city_or_recruitment_type_does_not_merge(self):
        existing = official_job(id="shanghai-campus")
        different_city = official_job(
            id=None,
            officialUrl="https://company.example/jobs/43",
            applyUrl="https://company.example/jobs/43/apply",
            cities=["北京"],
        )
        different_type = official_job(
            id=None,
            officialUrl="https://company.example/jobs/44",
            applyUrl="https://company.example/jobs/44/apply",
            recruitmentType="experienced",
        )

        result = merge_jobs([existing], [different_city, different_type])

        self.assertEqual(result.added, 2)
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(len({item["id"] for item in result.jobs}), 3)

    def test_identical_refresh_is_unchanged(self):
        existing = official_job(id="job_existing")
        incoming = official_job(id="ignored")

        result = merge_jobs([existing], [incoming])

        self.assertEqual((result.added, result.updated, result.unchanged), (0, 0, 1))
        self.assertEqual(result.jobs[0]["id"], "job_existing")


if __name__ == "__main__":
    unittest.main()
