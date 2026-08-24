import unittest

from job_radar_lib.policies import find_policy, merge_policies
from tests.helpers import company_policy


class PolicyTests(unittest.TestCase):
    def test_newer_verified_policy_replaces_same_company_and_type(self):
        old = company_policy(lastVerifiedAt="2026-08-01T00:00:00+08:00")
        new = company_policy(
            lastVerifiedAt="2026-08-21T00:00:00+08:00",
            maxApplications=1,
        )

        result = merge_policies([old], [new])

        self.assertEqual(result.updated, 1)
        self.assertEqual(result.policies[0]["lastVerifiedAt"], new["lastVerifiedAt"])

    def test_policy_lookup_normalizes_company_width_case_and_space(self):
        match = find_policy(
            [company_policy(company="DJI 大疆创新")],
            "  dji  大疆创新 ",
            "campus",
        )

        self.assertIsNotNone(match)

    def test_unknown_refresh_does_not_erase_newer_verified_rule(self):
        verified = company_policy()
        unknown = company_policy(
            maxApplications=None,
            canChangeSubmittedRole=None,
            ruleSummary=None,
            officialUrl=None,
            lastVerifiedAt="2026-08-20T00:00:00+08:00",
            verificationState="unknown",
        )

        result = merge_policies([verified], [unknown])

        self.assertEqual(result.policies[0]["verificationState"], "verified")
        self.assertEqual((result.added, result.updated, result.unchanged), (0, 0, 1))

    def test_new_company_policy_is_added(self):
        result = merge_policies([], [company_policy()])

        self.assertEqual((result.added, result.updated, result.unchanged), (1, 0, 0))
        self.assertEqual(len(result.policies), 1)


if __name__ == "__main__":
    unittest.main()
