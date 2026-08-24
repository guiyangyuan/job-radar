---
name: job-radar
description: Local-first job discovery and application tracking for Mainland China campus, internship, and experienced-hire searches. Use when Codex needs to build a job-search profile from a resume or onboarding answers, find and rank matching roles from official and public recruitment sources, record user-confirmed applications, update recruitment stages, serve an editable local HTML dashboard, or summarize job-search progress.
---

# Job Radar

Build a privacy-safe job-search profile, discover current Mainland China openings, score them transparently, and maintain a local application dashboard. Keep all personal search and application data outside the installed skill.

## Non-negotiable boundaries

- Never submit an application form or claim that an application was submitted.
- Never store credentials, session cookies, MFA codes, identity numbers, phone numbers, personal email addresses, exact street addresses, or full resume text in the workspace.
- Never bypass login, CAPTCHA, MFA, access controls, robots rules, rate limits, or a site's anti-automation measures.
- Never invent a deadline, graduation window, experience requirement, salary, location, job identifier, status, or application URL.
- Never advance an application stage without explicit user confirmation or user-provided evidence.
- Never publish notes or evidence links. Use `export --privacy` for anything the user may share.
- Treat visiting an application link as navigation only, not evidence of submission.

## Resolve the skill and workspace

Use Python 3.11 or newer with no third-party packages. Resolve `SKILL_DIR` to the directory containing this file, then call:

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" --help
```

Locate an existing workspace from conversation context before creating one. If none exists, use `./job-radar-data`, initialize it, and report its absolute path:

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" init --workspace ./job-radar-data
```

The workspace contains `profile.json`, `jobs.json`, `applications.json`, `company-policies.json`, `settings.json`, bounded backups, and HTML exports. Read the canonical JSON at the beginning of every invocation; dashboard edits become visible to Codex on the next invocation, not continuously.

## Choose the workflow

- **First use or changed target:** build and confirm the profile, then discover jobs.
- **Find more jobs:** refresh public sources, normalize candidates, merge, score, and report changes.
- **User says they applied:** ask for explicit confirmation if it is not already clear, then create the application record.
- **User reports screening, assessment, interview, offer, rejection, or withdrawal:** update only the supported fields and retain evidence/history.
- **User wants the tracker:** start the editable dashboard or create a read-only privacy export.
- **User asks for progress:** read current JSON and return a concise funnel/status summary.

## 1. Build and confirm a privacy-safe profile

Accept either a PDF, DOCX, Markdown, or plain-text resume, or run a guided interview. Use the host's document-reading capability; if the file cannot be read locally, ask for exported or pasted text rather than uploading it to an unknown service.

Collect or infer a draft containing:

- target roles and role aliases;
- campus, internship, and/or experienced-hire preference;
- cities and remote preference;
- years of experience and graduation date when relevant;
- education and skills;
- preferred industries and company types;
- excluded companies, keywords, and cities;
- whether city matching is strict.

Do not persist contact details, account identifiers, exact addresses, employer-confidential material, or full resume passages. Use the profile schema in [references/schemas.md](references/schemas.md). Present the structured draft to the user and require confirmation before searching. Set `confirmed` to `true` only after that confirmation, then validate:

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" validate --workspace "$WORKSPACE"
```

Do not score or recommend jobs while the profile is unconfirmed.

## 2. Discover and normalize current jobs

Read [references/source-policy.md](references/source-policy.md) before each discovery run. Job availability is time-sensitive, so browse current public pages rather than relying on memory.

Search in this order:

1. employer careers pages;
2. NCSS and Guopin;
3. Nowcoder, Shixiseng, and public university career centers;
4. public link-level discovery sources, followed to an employer page when possible.

Build queries from role names/aliases, recruitment type, cities, graduation or experience constraints, and selected employers. Open accessible candidate pages before classifying a destination. Record `detail` only for an exact vacancy page and `apply` only for that vacancy's application flow. Use `listing` for a searchable employer job list and `homepage` for a general careers site, with `linkSearchHint` set to the title or employer job ID. A search-result title or snippet never establishes `detail` or `apply`. Record only evidence visible on the page. Use `null` or an empty list for missing evidence, preserve every source link, and summarize rather than store raw page HTML or long copied descriptions.

Record an application limit in `company-policies.json` only when an official employer page states the rule. Keep `maxApplications`, role-change behavior, and summary nullable when the rule is unknown; never infer a quota from discussion posts or search snippets.

Write normalized candidates as a JSON array using the job schema. Use synthetic, non-personal temporary filenames inside the workspace, for example `incoming-jobs.json`. Then run:

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" merge-jobs --workspace "$WORKSPACE" --input "$WORKSPACE/incoming-jobs.json"
python3 "$SKILL_DIR/scripts/job_radar.py" merge-policies --workspace "$WORKSPACE" --input "$WORKSPACE/incoming-policies.json"
python3 "$SKILL_DIR/scripts/job_radar.py" score --workspace "$WORKSPACE"
```

The merge keeps stable IDs and user decisions, combines source evidence, and lets a lower source tier win conflicting material fields. The score is a configurable 100-point sum of role, skills, eligibility, location, preference, and freshness. Missing evidence never receives full credit.

Report:

- new, updated, unchanged, filtered, stale, and unverifiable counts;
- the strongest matches with company, title, city, score, reasons, gaps, deadline, verification time, and direct official/apply links;
- which facts are missing or need manual verification.

Do not describe a link-only record as verified or active.

## 3. Record a real application

Only record an application after the user explicitly says the form was submitted or supplies equivalent evidence. If the statement is ambiguous, ask for confirmation. Then call:

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" apply --workspace "$WORKSPACE" --job-id JOB_ID --confirmed
```

This copies only stable job metadata, marks the job `applied`, assigns a UUID application ID, and appends a conversation history event. It does not copy the full job description.

## 4. Update stages and next actions

Supported application states are `applied`, `screening`, `assessment`, `interview`, `offer`, `rejected`, `withdrawn`, `closed`, and `archived`. Corrections are allowed; every actual change records old value, new value, timestamp, and channel.

Bind claims to the user's words or evidence. For example, an interview invitation may justify `status=interview`, an interview stage, next action, due date, and evidence link. A generic recruiter message does not automatically prove screening success.

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" update \
  --workspace "$WORKSPACE" \
  --application-id APPLICATION_ID \
  --status interview \
  --interview-stage "技术一面" \
  --next-action "准备项目复盘" \
  --channel email
```

Use `archived` instead of deleting mistaken or abandoned records. Never silently overwrite a version conflict; reload the canonical record and reconcile with the user.

## 5. Use the dashboard

Start the token-protected editable dashboard:

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" serve --workspace "$WORKSPACE"
```

The service binds only to `127.0.0.1`, prints a tokenized local URL, and normally opens it in the browser. Use `--no-open` in a headless environment. The dashboard provides `岗位推荐` and `投递进度` tabs. Recommendations are grouped by company with one primary role, at most two alternatives, and an explicit verified quota or unknown-rule badge. Edits save immediately to canonical JSON with backups and conflict checks.

Create a self-contained shareable snapshot only in privacy mode:

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" export --workspace "$WORKSPACE" --privacy
```

The static export is read-only. Privacy mode removes notes, evidence links, and their copies in history events.

## 6. Summarize and hand off

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" summary --workspace "$WORKSPACE" --json
```

Lead with outcomes: strongest new opportunities, applications needing action, upcoming or overdue dates, and current funnel counts. Include direct public links where useful. State the absolute workspace and export paths, but do not expose the dashboard session token in a reusable document or public message.

## Command reference

```text
init        Create canonical local files and bounded backup/export folders
validate    Reject invalid versions, fields, URLs, dates, statuses, or weights
merge-jobs  Deduplicate normalized job JSON and apply source precedence
migrate-links Conservatively classify legacy job destinations
merge-policies Merge validated official company application rules
score       Apply hard filters and the explainable six-part score
apply       Create a user-confirmed application and mark its job applied
update      Change an application and append an auditable history event
serve       Run the editable token-protected loopback dashboard
export      Write a self-contained read-only HTML snapshot
summary     Count job-pool and application states
```

If a public page is inaccessible, record `needs_verification` when updating an existing record, preserve its last known public link, and tell the user what could not be verified. Do not weaken the boundaries to obtain more data.
