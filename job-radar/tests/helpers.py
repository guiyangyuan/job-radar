from copy import deepcopy
from datetime import datetime


NOW = datetime.fromisoformat("2026-08-21T10:00:00+08:00")


def profile(**overrides):
    value = {
        "schemaVersion": 1,
        "targetRoles": ["AI 应用开发工程师"],
        "roleAliases": ["AI Engineer"],
        "recruitmentTypes": ["campus"],
        "cities": ["上海"],
        "remotePreference": "neutral",
        "yearsOfExperience": 0,
        "graduationDate": "2028-06-30",
        "education": "bachelor",
        "skills": ["Python", "Go", "RAG"],
        "preferredIndustries": ["互联网"],
        "preferredCompanyTypes": ["民营企业"],
        "excludedCompanies": [],
        "excludedKeywords": [],
        "excludedCities": [],
        "strictCityFilter": False,
        "scoreWeights": {
            "role": 30,
            "skills": 30,
            "eligibility": 15,
            "location": 10,
            "preference": 10,
            "freshness": 5,
        },
        "confirmed": True,
    }
    value.update(overrides)
    return value


def job(**overrides):
    value = {
        "schemaVersion": 1,
        "id": "job_example",
        "company": "示例科技",
        "title": "AI 应用开发工程师",
        "recruitmentType": "campus",
        "cities": ["上海"],
        "experienceMin": 0,
        "experienceMax": 1,
        "education": "bachelor",
        "graduationWindow": ["2027-09-01", "2028-08-31"],
        "skills": ["Python", "Go", "RAG"],
        "industry": "互联网",
        "companyType": "民营企业",
        "descriptionSummary": "构建 AI 应用",
        "publishedAt": "2026-08-20T09:00:00+08:00",
        "deadlineAt": "2026-09-30T23:59:59+08:00",
        "officialUrl": "https://company.example/jobs/42",
        "applyUrl": "https://company.example/jobs/42/apply",
        "linkType": "detail",
        "linkUrl": "https://company.example/jobs/42",
        "linkSearchHint": None,
        "sources": [],
        "sourceTier": 1,
        "sourceConfidence": "high",
        "firstDiscoveredAt": "2026-08-21T09:00:00+08:00",
        "lastVerifiedAt": "2026-08-21T09:00:00+08:00",
        "verificationState": "verified",
        "poolStatus": "discovered",
        "score": 0,
        "scoreBreakdown": {},
        "recommendationReasons": [],
        "gaps": [],
        "riskFlags": [],
    }
    value.update(overrides)
    return value


def official_job(**overrides):
    value = job(
        sources=[
            {
                "name": "Employer",
                "url": "https://company.example/jobs/42",
                "tier": 1,
            }
        ]
    )
    value.update(overrides)
    return value


def aggregator_job(**overrides):
    value = job(
        officialUrl="https://company.example/jobs/42?utm_source=nowcoder",
        sourceTier=3,
        sourceConfidence="medium",
        sources=[
            {
                "name": "Nowcoder",
                "url": "https://nowcoder.example/jobs/42",
                "tier": 3,
            }
        ],
    )
    value.update(overrides)
    return value


def application(**overrides):
    value = {
        "schemaVersion": 1,
        "id": "app_example",
        "jobId": "job_example",
        "company": "示例科技",
        "title": "AI 应用开发工程师",
        "officialUrl": "https://company.example/jobs/42",
        "applyUrl": "https://company.example/jobs/42/apply",
        "recruitmentType": "campus",
        "cities": ["上海"],
        "appliedAt": "2026-08-21T10:00:00+08:00",
        "status": "applied",
        "interviewStage": None,
        "nextAction": None,
        "nextActionAt": None,
        "notes": "",
        "evidenceLinks": [],
        "updatedAt": "2026-08-21T10:00:00+08:00",
        "history": [],
    }
    value.update(overrides)
    return value


def company_policy(**overrides):
    value = {
        "schemaVersion": 1,
        "company": "大疆创新",
        "recruitmentType": "campus",
        "maxApplications": 1,
        "canChangeSubmittedRole": False,
        "ruleSummary": "每位同学限投递一个职位，且投递后无法更新已投递的职位。",
        "officialUrl": "https://careers.dji.com/zh-CN/campus/recruitment",
        "lastVerifiedAt": "2026-08-21T00:00:00+08:00",
        "verificationState": "verified",
    }
    value.update(overrides)
    return value


def sample_data(**overrides):
    sample_job = job()
    sample_application = application()
    if "title" in overrides:
        sample_job["title"] = overrides["title"]
    if "notes" in overrides:
        sample_application["notes"] = overrides["notes"]
    if "evidenceLinks" in overrides:
        sample_application["evidenceLinks"] = overrides["evidenceLinks"]
    return {
        "profile": deepcopy(profile()),
        "jobs": [sample_job],
        "applications": [sample_application],
        "companyPolicies": [],
        "generatedAt": "2026-08-21T10:00:00+08:00",
    }
