import unittest

from job_radar_lib.scoring import hard_filter, score_job

from tests.helpers import NOW, job, profile


class HardFilterTests(unittest.TestCase):
    def test_expired_job_is_filtered(self):
        value = job(deadlineAt="2026-08-20T00:00:00+08:00")
        self.assertEqual(hard_filter(profile(), value, NOW), "deadline_passed")

    def test_excluded_company_is_filtered_after_normalization(self):
        value = profile(excludedCompanies=[" 示例科技 "])
        self.assertEqual(
            hard_filter(value, job(company="示例科技有限公司"), NOW),
            "excluded_company",
        )

    def test_excluded_keyword_is_checked_in_job_evidence(self):
        value = profile(excludedKeywords=["销售"])
        self.assertEqual(
            hard_filter(value, job(descriptionSummary="负责售前销售支持"), NOW),
            "excluded_keyword",
        )

    def test_excluded_city_and_recruitment_type_are_filtered(self):
        self.assertEqual(
            hard_filter(profile(excludedCities=["上海"]), job(), NOW),
            "excluded_city",
        )
        self.assertEqual(
            hard_filter(profile(recruitmentTypes=["campus"]), job(recruitmentType="experienced"), NOW),
            "recruitment_type_mismatch",
        )

    def test_strict_city_mismatch_is_filtered(self):
        value = profile(cities=["上海"], strictCityFilter=True)
        self.assertEqual(
            hard_filter(value, job(cities=["北京"]), NOW),
            "city_mismatch",
        )

    def test_experience_and_graduation_mismatch_are_filtered(self):
        self.assertEqual(
            hard_filter(
                profile(recruitmentTypes=["experienced"], yearsOfExperience=1),
                job(recruitmentType="experienced", experienceMin=3),
                NOW,
            ),
            "experience_mismatch",
        )
        self.assertEqual(
            hard_filter(
                profile(graduationDate="2028-06-30"),
                job(graduationWindow=["2026-09-01", "2027-08-31"]),
                NOW,
            ),
            "graduation_window_mismatch",
        )


class ScoringTests(unittest.TestCase):
    def test_perfect_match_uses_all_six_dimensions(self):
        result = score_job(profile(), job(), NOW)
        self.assertEqual(result.score, 100)
        self.assertEqual(
            set(result.breakdown),
            {"role", "skills", "eligibility", "location", "preference", "freshness"},
        )
        self.assertIsNone(result.filtered_reason)

    def test_missing_evidence_does_not_receive_full_credit(self):
        result = score_job(profile(), job(skills=[], publishedAt=None), NOW)
        self.assertLess(result.breakdown["skills"], 30)
        self.assertLess(result.breakdown["freshness"], 5)
        self.assertIn("技能要求缺失", result.gaps)
        self.assertIn("发布时间缺失", result.gaps)

    def test_partial_role_and_skill_matches_are_explainable(self):
        result = score_job(
            profile(skills=["Python", "Go"]),
            job(title="AI 工程师", skills=["Python", "Rust"]),
            NOW,
        )
        self.assertGreater(result.breakdown["role"], 0)
        self.assertLess(result.breakdown["role"], 30)
        self.assertEqual(result.breakdown["skills"], 15)
        self.assertTrue(any("Python" in reason for reason in result.reasons))
        self.assertTrue(any("Rust" in gap for gap in result.gaps))

    def test_missing_eligibility_evidence_gets_half_credit(self):
        result = score_job(
            profile(recruitmentTypes=["experienced"], yearsOfExperience=2),
            job(
                recruitmentType="experienced",
                experienceMin=None,
                experienceMax=None,
            ),
            NOW,
        )
        self.assertEqual(result.breakdown["eligibility"], 8)
        self.assertIn("经验要求缺失", result.gaps)

    def test_non_strict_city_mismatch_scores_zero_but_is_not_filtered(self):
        result = score_job(
            profile(cities=["上海"], strictCityFilter=False),
            job(cities=["北京"]),
            NOW,
        )
        self.assertIsNone(result.filtered_reason)
        self.assertEqual(result.breakdown["location"], 0)

    def test_remote_role_gets_half_location_credit_for_neutral_preference(self):
        result = score_job(
            profile(cities=["上海"], remotePreference="neutral"),
            job(cities=["远程"]),
            NOW,
        )
        self.assertEqual(result.breakdown["location"], 5)

    def test_freshness_declines_and_filtered_job_returns_zero(self):
        recent = score_job(profile(), job(publishedAt="2026-08-14T10:00:00+08:00"), NOW)
        older = score_job(profile(), job(publishedAt="2026-07-22T10:00:00+08:00"), NOW)
        filtered = score_job(
            profile(), job(deadlineAt="2026-08-20T00:00:00+08:00"), NOW
        )
        self.assertEqual(recent.breakdown["freshness"], 5)
        self.assertGreater(older.breakdown["freshness"], 0)
        self.assertLess(older.breakdown["freshness"], 5)
        self.assertEqual(filtered.score, 0)
        self.assertEqual(filtered.filtered_reason, "deadline_passed")


if __name__ == "__main__":
    unittest.main()
