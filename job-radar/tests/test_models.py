import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from job_radar_lib.models import (  # noqa: E402
    ValidationError,
    normalize_text,
    validate_application,
    validate_company_policy,
    validate_job,
    validate_profile,
)
from tests.helpers import application, company_policy, job, profile  # noqa: E402


class ModelValidationTests(unittest.TestCase):
    def test_profile_rejects_weights_that_do_not_sum_to_100(self):
        value = profile(
            scoreWeights={
                "role": 30,
                "skills": 30,
                "eligibility": 15,
                "location": 10,
                "preference": 10,
                "freshness": 4,
            }
        )

        with self.assertRaisesRegex(ValidationError, "sum to 100"):
            validate_profile(value)

    def test_job_requires_company(self):
        value = job(company="")

        with self.assertRaisesRegex(ValidationError, "company"):
            validate_job(value)

    def test_application_rejects_unknown_status(self):
        value = application(status="maybe")

        with self.assertRaisesRegex(ValidationError, "status"):
            validate_application(value)

    def test_normalize_text_collapses_width_case_and_space(self):
        self.assertEqual(normalize_text("  ＡＩ  Engineer\n"), "ai engineer")

    def test_profile_rejects_unknown_fields(self):
        value = profile(secretPhone="redacted")

        with self.assertRaisesRegex(ValidationError, "unknown profile fields"):
            validate_profile(value)

    def test_job_rejects_non_http_application_url(self):
        value = job(applyUrl="javascript:alert(1)")

        with self.assertRaisesRegex(ValidationError, "applyUrl"):
            validate_job(value)

    def test_job_accepts_explicit_detail_link(self):
        validated = validate_job(
            job(linkType="detail", linkUrl="https://company.example/jobs/42")
        )

        self.assertEqual(validated["linkType"], "detail")

    def test_job_rejects_unsupported_link_type(self):
        with self.assertRaisesRegex(ValidationError, "linkType is unsupported"):
            validate_job(job(linkType="search-result"))

    def test_job_rejects_non_http_link_url(self):
        with self.assertRaisesRegex(ValidationError, "linkUrl must be an HTTP"):
            validate_job(job(linkUrl="javascript:alert(1)"))

    def test_application_requires_list_history(self):
        value = application(history={})

        with self.assertRaisesRegex(ValidationError, "history"):
            validate_application(value)

    def test_job_rejects_unknown_nested_source_fields(self):
        value = job(
            sources=[
                {
                    "name": "Employer",
                    "url": "https://company.example/jobs/42",
                    "tier": 1,
                    "invented": True,
                }
            ]
        )

        with self.assertRaisesRegex(ValidationError, "unknown source fields"):
            validate_job(value)

    def test_application_rejects_unknown_history_event_fields(self):
        value = application(
            history=[
                {
                    "timestamp": "2026-08-21T10:00:00+08:00",
                    "channel": "dashboard",
                    "changes": {
                        "status": {"old": "applied", "new": "screening"}
                    },
                    "invented": True,
                }
            ]
        )

        with self.assertRaisesRegex(ValidationError, "unknown history event fields"):
            validate_application(value)

    def test_company_policy_rejects_negative_limit(self):
        with self.assertRaisesRegex(ValidationError, "maxApplications"):
            validate_company_policy(company_policy(maxApplications=-1))

    def test_company_policy_rejects_boolean_limit(self):
        with self.assertRaisesRegex(ValidationError, "maxApplications"):
            validate_company_policy(company_policy(maxApplications=True))

    def test_company_policy_requires_official_evidence_for_verified_rule(self):
        with self.assertRaisesRegex(ValidationError, "officialUrl"):
            validate_company_policy(company_policy(officialUrl=None))

    def test_unknown_company_policy_keeps_nullable_rule_fields(self):
        value = validate_company_policy(
            company_policy(
                maxApplications=None,
                canChangeSubmittedRole=None,
                ruleSummary=None,
                officialUrl=None,
                verificationState="unknown",
            )
        )

        self.assertIsNone(value["maxApplications"])


if __name__ == "__main__":
    unittest.main()
