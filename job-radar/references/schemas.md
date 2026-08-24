# Job Radar schemas

All canonical records use `schemaVersion: 1`. Top-level records, source objects, and history events reject unknown fields. Dates use `YYYY-MM-DD`; timestamps use ISO-8601. URLs must use HTTP or HTTPS. Missing scalars use `null`, and missing collections use `[]`.

## Profile

| Field | Type | Meaning |
| --- | --- | --- |
| `schemaVersion` | integer | Must be `1`. |
| `targetRoles` | string[] | Required target job names; at least one. |
| `roleAliases` | string[] | Chinese/English titles used to improve recall. |
| `recruitmentTypes` | string[] | One or more of `campus`, `internship`, `experienced`. |
| `cities` | string[] | Desired cities or regions. |
| `remotePreference` | string/null | User's remote-work preference; `neutral` is the generic default. |
| `yearsOfExperience` | number/null | Total relevant experience. |
| `graduationDate` | date/null | Expected or actual graduation date. |
| `education` | string/null | Normalized education level. |
| `skills` | string[] | Skills supported by the resume or user. |
| `preferredIndustries` | string[] | Soft industry preferences. |
| `preferredCompanyTypes` | string[] | Soft employer-type preferences. |
| `excludedCompanies` | string[] | Employers rejected by hard filtering. |
| `excludedKeywords` | string[] | Job evidence terms rejected by hard filtering. |
| `excludedCities` | string[] | Locations rejected by hard filtering. |
| `strictCityFilter` | boolean | Whether a desired-city mismatch is a hard rejection. |
| `scoreWeights` | object | Six numeric weights that must contain all score dimensions and sum to 100. |
| `confirmed` | boolean | True only after the user approves the privacy-safe profile. |

Synthetic valid profile:

```json
{
  "schemaVersion": 1,
  "targetRoles": ["Data Platform Engineer"],
  "roleAliases": ["数据平台工程师"],
  "recruitmentTypes": ["campus", "internship"],
  "cities": ["杭州", "上海"],
  "remotePreference": "neutral",
  "yearsOfExperience": 0,
  "graduationDate": "2028-06-30",
  "education": "bachelor",
  "skills": ["Python", "SQL", "Go"],
  "preferredIndustries": ["软件服务"],
  "preferredCompanyTypes": ["民营企业"],
  "excludedCompanies": [],
  "excludedKeywords": ["销售"],
  "excludedCities": [],
  "strictCityFilter": false,
  "scoreWeights": {"role": 30, "skills": 30, "eligibility": 15, "location": 10, "preference": 10, "freshness": 5},
  "confirmed": true
}
```

## Job

| Field | Type | Meaning |
| --- | --- | --- |
| `schemaVersion` | integer | Must be `1`. |
| `id` | string/null | Stable `job_…` hash; assigned during merge. |
| `employerJobId` | string/null | Public identifier supplied by the employer. |
| `company` | string | Required employer name. |
| `title` | string | Required vacancy title. |
| `recruitmentType` | string | `campus`, `internship`, or `experienced`. |
| `cities` | string[] | Explicit work locations. |
| `experienceMin` | number/null | Explicit minimum years of experience. |
| `experienceMax` | number/null | Explicit maximum years of experience. |
| `education` | string/null | Explicit normalized education requirement. |
| `graduationWindow` | [date, date]/null | Inclusive campus graduation eligibility window. |
| `skills` | string[] | Explicit required or preferred skills. |
| `industry` | string/null | Normalized industry when supported by evidence. |
| `companyType` | string/null | Normalized employer type when supported by evidence. |
| `descriptionSummary` | string/null | Short original summary; never raw HTML or a full copied JD. |
| `publishedAt` | timestamp/null | Explicit publication time. |
| `deadlineAt` | timestamp/null | Explicit deadline or closure time. |
| `officialUrl` | URL/null | Employer-controlled vacancy/detail URL. |
| `applyUrl` | URL/null | Direct public application page URL. |
| `linkType` | string/null | Best verified destination: `detail`, `apply`, `listing`, or `homepage`. |
| `linkUrl` | URL/null | URL matching `linkType`; never synthesized. |
| `linkSearchHint` | string/null | Employer job ID or title to search when the destination is a list or homepage. |
| `sources` | source[] | Traceable public source records. |
| `sourceTier` | integer/null | Best available tier, 1 through 4. |
| `sourceConfidence` | string/null | Normally `high`, `medium`, or `low`. |
| `firstDiscoveredAt` | timestamp/null | First time Job Radar saw the vacancy. |
| `lastVerifiedAt` | timestamp/null | Last time a source was actually checked. |
| `verificationState` | string/null | Recommended values are in `source-policy.md`. |
| `poolStatus` | string | `discovered`, `saved`, `preparing`, `applied`, `ignored`, `expired`, or `archived`. |
| `score` | number/null | Final score from 0 through 100. |
| `scoreBreakdown` | object | Points by the six score dimensions. |
| `recommendationReasons` | string[] | Evidence-backed positive explanations. |
| `gaps` | string[] | Missing evidence, partial matches, or user gaps. |
| `riskFlags` | string[] | Machine-readable warnings such as `filtered:deadline_passed`. |

Synthetic valid job:

```json
{
  "schemaVersion": 1,
  "id": "job_7d4a8d705a7b0f12",
  "employerJobId": "DEMO-2027-014",
  "company": "星河数据实验室",
  "title": "数据平台工程师",
  "recruitmentType": "campus",
  "cities": ["杭州"],
  "experienceMin": 0,
  "experienceMax": 1,
  "education": "bachelor",
  "graduationWindow": ["2027-09-01", "2028-08-31"],
  "skills": ["Python", "SQL", "Go"],
  "industry": "软件服务",
  "companyType": "民营企业",
  "descriptionSummary": "建设批处理与实时数据服务，并维护内部开发工具。",
  "publishedAt": "2026-08-20T09:00:00+08:00",
  "deadlineAt": "2026-10-31T23:59:59+08:00",
  "officialUrl": "https://careers.example.org/jobs/DEMO-2027-014",
  "applyUrl": "https://careers.example.org/jobs/DEMO-2027-014/apply",
  "linkType": "detail",
  "linkUrl": "https://careers.example.org/jobs/DEMO-2027-014",
  "linkSearchHint": null,
  "sources": [{"name": "Employer Careers", "url": "https://careers.example.org/jobs/DEMO-2027-014", "tier": 1}],
  "sourceTier": 1,
  "sourceConfidence": "high",
  "firstDiscoveredAt": "2026-08-21T09:00:00+08:00",
  "lastVerifiedAt": "2026-08-21T09:05:00+08:00",
  "verificationState": "verified",
  "poolStatus": "discovered",
  "score": 100,
  "scoreBreakdown": {"role": 30, "skills": 30, "eligibility": 15, "location": 10, "preference": 10, "freshness": 5},
  "recommendationReasons": ["岗位名称匹配目标：数据平台工程师"],
  "gaps": [],
  "riskFlags": []
}
```

Destination priority is `detail`, `apply`, `listing`, then `homepage`. Listing and homepage links require a search hint when one is available and must never be labeled as a vacancy detail page.

## Company policy

| Field | Type | Meaning |
| --- | --- | --- |
| `schemaVersion` | integer | Must be `1`. |
| `company` | string | Required employer name; identity is normalized with recruitment type. |
| `recruitmentType` | string | `campus`, `internship`, or `experienced`. |
| `maxApplications` | positive integer/null | Officially supported application limit, otherwise `null`. |
| `canChangeSubmittedRole` | boolean/null | Whether the employer officially permits changing a submitted role. |
| `ruleSummary` | string/null | Short evidence-backed summary; required when verified. |
| `officialUrl` | URL/null | Official employer evidence; required when verified. |
| `lastVerifiedAt` | timestamp/null | Last time the official rule was checked. |
| `verificationState` | string | `verified`, `unknown`, or `needs_verification`. |

```json
{
  "schemaVersion": 1,
  "company": "示例科技",
  "recruitmentType": "campus",
  "maxApplications": 1,
  "canChangeSubmittedRole": false,
  "ruleSummary": "每位候选人限投一个校招职位。",
  "officialUrl": "https://careers.example.org/campus/faq",
  "lastVerifiedAt": "2026-08-21T10:00:00+08:00",
  "verificationState": "verified"
}
```

## Source

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | Required human-readable public source name. |
| `url` | URL/null | HTTP(S) page used as evidence. |
| `tier` | integer | Required integer from 1 through 4. |

Synthetic valid source:

```json
{"name": "Employer Careers", "url": "https://careers.example.org/jobs/DEMO-2027-014", "tier": 1}
```

## Score breakdown

| Field | Default maximum | Calculation |
| --- | ---: | --- |
| `role` | 30 | Exact normalized phrase match or title-token overlap. |
| `skills` | 30 | Profile skills matched against evidenced job skills; no evidence gets zero. |
| `eligibility` | 15 | Full for a supported match, half for missing constraints, zero for conflict. |
| `location` | 10 | Full for desired city, half for neutral remote, otherwise zero if non-strict. |
| `preference` | 10 | Average industry and employer-type preference match. |
| `freshness` | 5 | Full through 7 days, declining to zero at 60 days; unpublished gets zero. |

Synthetic valid score breakdown:

```json
{"role": 30, "skills": 20, "eligibility": 15, "location": 10, "preference": 5, "freshness": 5}
```

Each component is rounded once. The final sum is clamped to 0 through 100. A hard-filtered record receives zero and a `filtered:<reason>` risk flag.

## Application

| Field | Type | Meaning |
| --- | --- | --- |
| `schemaVersion` | integer | Must be `1`. |
| `id` | string | Required UUID4 generated on confirmed creation. |
| `jobId` | string | Stable job ID. |
| `company` | string | Copied employer name. |
| `title` | string | Copied vacancy title. |
| `officialUrl` | URL/null | Copied employer detail URL. |
| `applyUrl` | URL/null | Copied application URL. |
| `recruitmentType` | string | Copied recruitment type. |
| `cities` | string[] | Copied work locations. |
| `appliedAt` | timestamp | User-confirmed submission time. |
| `status` | string | `applied`, `screening`, `assessment`, `interview`, `offer`, `rejected`, `withdrawn`, `closed`, or `archived`. |
| `interviewStage` | string/null | Optional first/second/technical/HR stage label. |
| `nextAction` | string/null | Concrete follow-up action. |
| `nextActionAt` | timestamp/null | Due time for the next action. |
| `notes` | string | Private user notes. |
| `evidenceLinks` | URL[] | Private HTTP(S) evidence links. |
| `updatedAt` | timestamp | Optimistic concurrency version. |
| `history` | history-event[] | Append-only field-change events. |

Synthetic valid application:

```json
{
  "schemaVersion": 1,
  "id": "17947c46-5ac6-46f8-a461-4fce99be18cd",
  "jobId": "job_7d4a8d705a7b0f12",
  "company": "星河数据实验室",
  "title": "数据平台工程师",
  "officialUrl": "https://careers.example.org/jobs/DEMO-2027-014",
  "applyUrl": "https://careers.example.org/jobs/DEMO-2027-014/apply",
  "recruitmentType": "campus",
  "cities": ["杭州"],
  "appliedAt": "2026-08-22T10:00:00+08:00",
  "status": "screening",
  "interviewStage": null,
  "nextAction": "准备在线测评",
  "nextActionAt": "2026-08-25T19:00:00+08:00",
  "notes": "仅保存在本地的沟通记录。",
  "evidenceLinks": ["https://candidate.example.org/evidence/123"],
  "updatedAt": "2026-08-22T11:00:00+08:00",
  "history": [{"timestamp": "2026-08-22T11:00:00+08:00", "channel": "email", "changes": {"status": {"old": "applied", "new": "screening"}}}]
}
```

## History event

| Field | Type | Meaning |
| --- | --- | --- |
| `timestamp` | timestamp | When the change was recorded. |
| `channel` | string | `conversation`, `dashboard`, `email`, `screenshot`, or `portal`. |
| `changes` | object | One or more mutable application fields, each containing exactly `old` and `new`. |

Mutable history keys are `status`, `interviewStage`, `nextAction`, `nextActionAt`, `notes`, and `evidenceLinks`.

Synthetic valid history event:

```json
{
  "timestamp": "2026-08-22T11:00:00+08:00",
  "channel": "email",
  "changes": {
    "status": {"old": "applied", "new": "screening"},
    "nextAction": {"old": null, "new": "准备在线测评"}
  }
}
```

## Settings and workspace files

`settings.json` contains exactly:

```json
{"schemaVersion": 1, "sourceTiersEnabled": [1, 2, 3, 4], "backupRetention": 20}
```

`jobs.json`, `applications.json`, and `company-policies.json` are JSON arrays. `profile.json` is one profile object. Unknown fields, invalid versions, invalid HTTP(S) URLs, invalid dates/timestamps, unsupported statuses, malformed sources/history, and score weights that do not sum to 100 fail validation before canonical writes.
