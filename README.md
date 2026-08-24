# Job Radar

[![Tests](https://github.com/guiyangyuan/job-radar/actions/workflows/test.yml/badge.svg)](https://github.com/guiyangyuan/job-radar/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local-first Codex skill for discovering Mainland China job openings and tracking applications in a private, editable dashboard.

Job Radar turns a resume or a short onboarding interview into a privacy-safe job-search profile, searches current public recruitment sources, ranks matching roles with visible evidence, and keeps application status in local JSON files. It never submits applications on the user's behalf.

## What it does

- Builds a reusable profile from a resume or guided questions
- Prioritizes employer career sites and other public Mainland China recruitment sources
- Keeps direct job-detail, application, listing, or careers-page links without pretending they are equivalent
- Groups recommendations by company and records official application limits when available
- Scores roles with explainable role, skill, eligibility, location, preference, and freshness signals
- Runs a token-protected dashboard on `127.0.0.1` for local application-status updates
- Exports a privacy-filtered, read-only HTML snapshot when sharing is necessary
- Preserves an auditable history for screening, assessment, interview, offer, rejection, and withdrawal states

## Install

```bash
git clone https://github.com/guiyangyuan/job-radar.git
mkdir -p ~/.codex/skills
cp -R job-radar/job-radar ~/.codex/skills/job-radar
```

Restart Codex after installation, then invoke the skill with a prompt such as:

```text
Use $job-radar to build my job-search profile from my resume.
```

Job Radar requires Python 3.11 or newer and uses only the Python standard library.

## Local workflow

```bash
python3 ~/.codex/skills/job-radar/scripts/job_radar.py init --workspace ./job-radar-data
python3 ~/.codex/skills/job-radar/scripts/job_radar.py validate --workspace ./job-radar-data
python3 ~/.codex/skills/job-radar/scripts/job_radar.py serve --workspace ./job-radar-data
```

The workspace contains the user's profile, normalized job pool, application records, company policies, bounded backups, and exports. It is intentionally separate from the installed skill and ignored by Git.

## Privacy and safety

- No credentials, session cookies, MFA codes, identity numbers, personal contact details, or full resume text are stored.
- Application stages change only after explicit user confirmation or user-provided evidence.
- The editable dashboard binds only to localhost and uses a per-session token.
- Public exports remove notes, evidence links, and their history copies.
- Login, CAPTCHA, rate limits, robots rules, and anti-automation controls are never bypassed.

See [`job-radar/SKILL.md`](job-radar/SKILL.md) for the complete agent workflow and boundaries.

## Test

```bash
PYTHONPATH=job-radar/scripts python3 -m unittest discover -s job-radar/tests -t job-radar -v
```

## License

[MIT](LICENSE) © 2026 Guiyang Yuan
