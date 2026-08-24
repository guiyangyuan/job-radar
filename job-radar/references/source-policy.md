# Job Radar source policy

Use this policy for Mainland China campus, internship, and experienced-hire discovery. Availability and recruitment rules change frequently; verify current pages on every run.

## Source tiers

### Tier 1 — employer careers pages

Employer-controlled career sites, campus portals, and official recruitment subdomains are the preferred source of truth. Use them for the vacancy title, employer job ID, locations, recruitment type, eligibility, deadline, job detail, and application URL when those facts are explicitly present.

Examples are employer career portals discovered for the current search. Do not hard-code a closed company list.

Set:

- `sourceTier: 1`;
- `sourceConfidence: high` when the detail page is accessible and internally consistent;
- `verificationState: verified` when checked during this run.

Classify the best outbound destination only after opening it: `detail` for the exact vacancy, `apply` for that vacancy's application flow, `listing` for an employer job list, and `homepage` for a general careers site. Prefer them in that order.

### Tier 2 — national public employment platforms

Use the National College Student Employment Service Platform (NCSS/国家大学生就业服务平台) and Guopin (国聘) for public-sector, state-owned-enterprise, graduate, and broad recruitment discovery.

Set `sourceTier: 2`. Treat the page as authoritative for what it publishes, but prefer a linked employer careers page when the employer maintains one.

### Tier 3 — technical, internship, and university sources

Use public pages from Nowcoder (牛客), Shixiseng (实习僧), and university career centers for campus events, internships, technical positions, and employer announcements.

Set `sourceTier: 3`. Keep the announcement URL in `sources`. Follow official links and verify material fields where possible.

### Tier 4 — link-level discovery

Publicly visible links or search results from BOSS Zhipin, Zhaopin, 51job, Liepin, Lagou, and other aggregators may identify a candidate vacancy. Do not promise structured extraction from pages that require login, block automated access, or restrict reuse.

Set `sourceTier: 4`, normally use `sourceConfidence: low`, and use `verificationState: link-only` unless the employer page is opened and checked. A search-result snippet alone does not prove that a job is still active.

## Precedence and deduplication

Merge evidence in this order:

1. canonical official URL for an explicitly classified `detail` or `apply` destination;
2. employer name plus employer job ID;
3. normalized employer, title, city set, and recruitment type.

Remove URL fragments and tracking parameters such as `utm_*`, `spread`, `ref`, and `source` before comparison. Materially different city sets, recruitment types, or titles remain separate vacancies.

When sources conflict:

- the lower numeric tier wins material fields;
- a supported non-null value wins an unsupported null value;
- for equal tiers, the newer verification wins;
- preserve all distinct source links for traceability;
- never overwrite the user's pool status, first discovery time, score, or decisions during refresh.

## Missing fields and verification

- Use `null` for an unknown scalar and `[]` for an unknown list.
- Do not infer a deadline from campaign timing.
- Do not infer a city from company headquarters.
- Do not turn a role family or recruitment landing page into a specific vacancy.
- Do not treat a search-result title or snippet as proof of a `detail` or `apply` destination.
- Do not synthesize an application URL. Keep a public detail URL if no direct apply URL is visible.
- Do not infer years of experience from title seniority alone.
- Summarize the job in original words; do not store raw HTML or long copied descriptions.
- Keep `firstDiscoveredAt` unchanged and refresh `lastVerifiedAt` only when a page was actually checked.

Recommended verification states:

| State | Meaning |
| --- | --- |
| `verified` | Current employer or authoritative detail page was opened during this run. |
| `cross-checked` | Material fields agree across at least two public sources. |
| `link-only` | Only a public link or search result was available. |
| `needs_verification` | A previously known record could not be rechecked. |
| `unavailable` | The prior public page is unavailable or explicitly closed. |

Do not delete an inaccessible existing record. Mark it for verification or expiry as supported by evidence.

## Company application limits

Store company limits separately in `company-policies.json`, keyed by normalized company and recruitment type. A verified rule requires an official employer HTTP(S) page, a concise summary, and a verification timestamp. Community posts, aggregator text, and search snippets may help discovery but never establish a quota.

Use `null` for unknown `maxApplications` and `canChangeSubmittedRole`, and display the rule as unverified. Refresh policy evidence independently from job evidence. A verified quota may produce a warning when the active application count reaches the limit, but it must never block navigation or change the user's application state.

## Query construction

Combine only the dimensions relevant to the confirmed profile. Use Chinese and English aliases where they improve recall.

### Recruitment-type templates

```text
"<role>" 校招 <year> <city>
"<role>" 应届生 <graduation-year> <city>
"<role>" 实习 <city> <skill>
"<role>" 社招 <city> <experience>年
```

### Role-alias templates

```text
("<target-role>" OR "<alias-1>" OR "<alias-2>") 招聘 <city>
"<target-role>" <skill-1> <skill-2> 招聘
```

When the search interface does not support `OR`, issue separate focused queries rather than an oversized query.

### Employer-first templates

```text
site:<employer-careers-domain> "<role>" <city>
site:<employer-careers-domain> (校招 OR 实习 OR 社招) "<role>"
<employer-name> 招聘官网 "<role>" <city>
```

### Public-source templates

```text
site:ncss.cn "<role>" <city>
site:iguopin.com "<role>" <city>
site:nowcoder.com "<role>" 校招 <city>
site:shixiseng.com "<role>" <city>
site:edu.cn 就业 "<employer-name>" "<role>"
```

Domains can change. Confirm the result is the intended organization before assigning a tier.

## Anti-automation boundaries

- Browse only public pages that the current environment is authorized to access.
- Respect site terms, robots guidance, request limits, and visible access restrictions.
- Use normal on-demand queries; do not fan out high-volume crawling.
- Stop when challenged by login, CAPTCHA, MFA, slider verification, blocked requests, or a rate-limit response.
- Do not import browser credentials, persist cookies, rotate identities, spoof users, or evade blocking.
- Do not submit forms, upload resumes, send messages, or trigger applications.
- Link to restricted platforms for the user to open manually.
- Store source facts and links, not page archives or personal session data.

## Run reporting

Separate results into new, updated, unchanged, filtered, stale, and unverifiable records. For each recommendation, provide the official link when available, score, reasons, gaps, deadline, source tier/confidence, and last verification time. Clearly label link-only or inferred normalization; never label unsupported facts as verified.
