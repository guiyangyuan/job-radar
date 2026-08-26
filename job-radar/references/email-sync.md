# Recruitment email synchronization

Use this reference only when the user explicitly asks Job Radar to inspect a mailbox. Ordinary job discovery and application tracking do not read email.

## Privacy and authority boundary

- Connect with verified TLS and select `INBOX` read-only.
- Fetch with `BODY.PEEK[]`; never mark, move, delete, label, or send messages.
- Parse locally with deterministic rules. Do not send email content to an external model API.
- Keep credentials only in process environment variables. Never put an app password in chat, a shell argument, JSON, logs, HTML, Git, or a screenshot.
- Persist only a hashed mailbox identity, UID cursor, sender domain, received time, short subject summary, extracted fields, classification, confidence, and reasons.
- Never persist the full sender address, body, raw MIME, attachment bytes, Message-ID, username, or app password.
- Treat every parsed event as a proposal. Only an explicit confirmation of the event and final status may update a canonical application.

## Environment configuration

Required for every provider:

```text
JOB_RADAR_IMAP_USERNAME
JOB_RADAR_IMAP_APP_PASSWORD
```

`JOB_RADAR_IMAP_PROVIDER` defaults to `auto`. Auto mode recognizes common personal mailbox domains:

| Address domain | Resolved provider | TLS IMAP endpoint |
| --- | --- | --- |
| `qq.com` | `qq` | `imap.qq.com:993` |
| `163.com` | `netease-163` | `imap.163.com:993` |
| `126.com` | `netease-126` | `imap.126.com:993` |
| `yeah.net` | `netease-yeah` | `imap.yeah.net:993` |
| `gmail.com`, `googlemail.com` | `gmail` | `imap.gmail.com:993` |

Custom-domain enterprise mailboxes cannot be inferred from the address. Select a preset explicitly:

| Provider value | TLS IMAP endpoint |
| --- | --- |
| `tencent-enterprise` | `imap.exmail.qq.com:993` |
| `netease-enterprise` | `imap.qiye.163.com:993` |
| `aliyun-enterprise` | `imap.qiye.aliyun.com:993` |

Obtain an IMAP authorization code or app password from the mailbox provider and set it outside the conversation. Do not use the normal account password when the provider requires a separate credential. Gmail app passwords require eligible two-step-verification settings.

For any other TLS IMAP service, use:

```text
JOB_RADAR_IMAP_PROVIDER=custom
JOB_RADAR_IMAP_HOST=mail.example.com
JOB_RADAR_IMAP_PORT=993
JOB_RADAR_IMAP_FOLDER=INBOX
```

The folder defaults to `INBOX`. The port must be from 1 through 65535.

Microsoft 365 and Outlook.com require OAuth for supported IMAP access. This version only implements app-password/authorization-code login, so do not select an Outlook preset or imply that Microsoft mailboxes are directly supported. A future OAuth flow should use a separate credential type rather than overloading `JOB_RADAR_IMAP_APP_PASSWORD`.

## Safe workflow

1. Tell the user that Job Radar will read `INBOX` only and state the requested lookback window.
2. Confirm that the environment variables are set without asking to see their values.
3. Test the read-only connection:

   ```bash
   python3 "$SKILL_DIR/scripts/job_radar.py" email-test --workspace "$WORKSPACE"
   ```

4. Run the bounded sync (default 60 days, allowed 1–3650):

   ```bash
   python3 "$SKILL_DIR/scripts/job_radar.py" email-sync --workspace "$WORKSPACE" --days 60
   ```

5. Open the local dashboard and review `邮件进度`, or inspect safe counts:

   ```bash
   python3 "$SKILL_DIR/scripts/job_radar.py" email-summary --workspace "$WORKSPACE" --json
   ```

6. Let the user edit the company, role, proposed status, stage, next action, deadline, and application match. Confirming is a separate visible action.

The first sync uses `SINCE` for the requested window. Later runs use UID-incremental search when UIDVALIDITY is unchanged. A UIDVALIDITY change safely restarts the bounded window. A malformed or oversized individual message becomes a minimized error event and does not stop later messages.

## Classification rules

Supported proposals are `applied`, `screening`, `assessment`, `interview`, `offer`, `rejected`, and `closed`. Explicit phrases are required. Talent-pool invitations, job marketing, newsletters, generic thanks, and sender domains alone never prove a stage. Contradictory, regressive, stale, terminal-target, or multiply matched evidence enters the conflict queue.

## Sharing and export

Nonprivacy local snapshots may contain minimized event metadata in their embedded data. For any shareable artifact, always use:

```bash
python3 "$SKILL_DIR/scripts/job_radar.py" export --workspace "$WORKSPACE" --privacy
```

Privacy mode removes all email sync state and events, in addition to private notes and evidence links.
