import unittest

from job_radar_lib.links import migrate_legacy_link, resolve_job_link
from tests.helpers import job


class LinkTests(unittest.TestCase):
    def test_explicit_detail_link_wins_over_apply_link(self):
        value = job(
            linkType="detail",
            linkUrl="https://company.example/jobs/42",
            applyUrl="https://company.example/jobs/42/apply",
        )

        resolved = resolve_job_link(value)

        self.assertEqual((resolved.kind, resolved.label), ("detail", "查看职位详情"))

    def test_apply_link_is_used_when_detail_is_absent(self):
        value = job(linkType="apply", linkUrl="https://company.example/apply/42")

        resolved = resolve_job_link(value)

        self.assertEqual((resolved.kind, resolved.label), ("apply", "立即投递"))

    def test_unclassified_legacy_url_is_not_assumed_to_be_detail(self):
        value = job(
            linkType=None,
            linkUrl=None,
            officialUrl="https://company.example/jobs",
        )

        self.assertIsNone(resolve_job_link(value))

    def test_listing_link_exposes_search_hint(self):
        value = job(
            linkType="listing",
            linkUrl="https://company.example/jobs",
            linkSearchHint="J103964",
        )

        resolved = resolve_job_link(value)

        self.assertEqual(resolved.label, "前往岗位列表")
        self.assertEqual(resolved.search_hint, "J103964")

    def test_legacy_detail_path_is_migrated_conservatively(self):
        value = job(
            linkType=None,
            linkUrl=None,
            officialUrl="https://talent.baidu.com/jobs/detail/GRADUATE/abc",
            employerJobId="J99974",
        )

        migrated = migrate_legacy_link(value)

        self.assertEqual(migrated["linkType"], "detail")
        self.assertEqual(migrated["linkUrl"], value["officialUrl"])

    def test_legacy_list_path_is_not_mislabeled_as_detail(self):
        value = job(
            linkType=None,
            linkUrl=None,
            officialUrl="https://talent.baidu.com/jobs/list?recruitType=GRADUATE",
            employerJobId="J103964",
        )

        migrated = migrate_legacy_link(value)

        self.assertEqual(migrated["linkType"], "listing")
        self.assertEqual(migrated["linkSearchHint"], "J103964")

    def test_legacy_apply_url_is_used_when_official_path_is_ambiguous(self):
        value = job(
            linkType=None,
            linkUrl=None,
            officialUrl="https://company.example/recruitment/unknown",
            applyUrl="https://company.example/apply/42",
        )

        migrated = migrate_legacy_link(value)

        self.assertEqual(migrated["linkType"], "apply")
        self.assertEqual(migrated["linkUrl"], value["applyUrl"])

    def test_verified_tier_one_hot_jobs_source_becomes_listing_fallback(self):
        source_url = "https://careers.dji.com/zh-CN/campus/hot-jobs"
        value = job(
            linkType=None,
            linkUrl=None,
            officialUrl=None,
            applyUrl=None,
            employerJobId=None,
            sources=[{"name": "Employer Careers", "url": source_url, "tier": 1}],
            sourceTier=1,
            verificationState="verified",
        )

        migrated = migrate_legacy_link(value)

        self.assertEqual(migrated["linkType"], "listing")
        self.assertEqual(migrated["linkUrl"], source_url)
        self.assertEqual(migrated["linkSearchHint"], value["title"])


if __name__ == "__main__":
    unittest.main()
