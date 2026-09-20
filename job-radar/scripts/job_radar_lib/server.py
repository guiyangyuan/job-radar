"""Token-protected loopback HTTP service for the editable dashboard."""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .applications import (
    ApplicationConflict,
    ApplicationNotFound,
    create_application,
    update_application,
)
from .email_events import (
    EventConflict,
    EventNotFound,
    confirm_event,
    patch_event,
    set_event_ignored,
)
from .email_models import validate_email_events, validate_email_sync_state
from .imap_sync import EmailSyncError
from .models import ValidationError, validate_job
from .rendering import render_dashboard, write_export
from .storage import Workspace, WorkspaceConflict, read_json, write_json_atomic


MAX_BODY_BYTES = 1024 * 1024
COOKIE_NAME = "job_radar_token"
CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
)


class PayloadTooLarge(ValueError):
    pass


@dataclass
class ServerConfig:
    workspace: Workspace
    host: str
    port: int
    token: str
    lock: threading.RLock = field(default_factory=threading.RLock)
    email_sync_lock: threading.Lock = field(default_factory=threading.Lock)
    email_sync_runner: Callable[[Workspace, int], dict] | None = None


def _default_email_sync_runner(workspace: Workspace, days: int) -> dict:
    # Imported lazily to avoid a module cycle: the CLI imports this server module.
    import job_radar

    return job_radar.run_email_sync(
        workspace, days, datetime.now(timezone.utc)
    )


def _find_index(records: list[dict], record_id: str) -> int:
    for index, record in enumerate(records):
        if record.get("id") == record_id:
            return index
    raise ApplicationNotFound(f"record not found: {record_id}")


def _handler_factory(config: ServerConfig):
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "JobRadar/0.1"
        sys_version = ""

        def log_message(self, _format, *_args):
            # Query-string tokens must never reach default request logs.
            return

        def _common_headers(self):
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")

        def _send_json(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str):
            body = html.encode("utf-8")
            self.send_response(200)
            self._common_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect_with_cookie(self):
            self.send_response(302)
            self._common_headers()
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={config.token}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _error(self, status: int, message: str):
            self._send_json(status, {"error": message})

        def _host_is_allowed(self) -> bool:
            value = self.headers.get("Host", "")
            try:
                parsed = urlsplit("//" + value)
                if parsed.hostname not in {"127.0.0.1", "localhost"}:
                    return False
                return parsed.port in {None, self.server.server_port}
            except ValueError:
                return False

        def _origin_is_allowed(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            return origin == "http://" + self.headers.get("Host", "")

        def _authenticated(self) -> bool:
            header_token = self.headers.get("X-Job-Radar-Token", "")
            if header_token and secrets.compare_digest(header_token, config.token):
                return True
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:
                return False
            morsel = cookie.get(COOKIE_NAME)
            return bool(morsel and secrets.compare_digest(morsel.value, config.token))

        def _read_json(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length > MAX_BODY_BYTES:
                raise PayloadTooLarge("request body exceeds 1 MiB")
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("request body must be valid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def _dashboard_data(self) -> dict:
            email_sync = validate_email_sync_state(
                read_json(config.workspace.email_sync)
            )
            email_events = validate_email_events(
                read_json(config.workspace.email_events)
            )
            return {
                "profile": read_json(config.workspace.profile),
                "jobs": read_json(config.workspace.jobs),
                "applications": read_json(config.workspace.applications),
                "companyPolicies": read_json(config.workspace.company_policies),
                "emailSync": email_sync,
                "emailEvents": email_events,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }

        def _summary(self) -> dict:
            jobs = read_json(config.workspace.jobs)
            applications = read_json(config.workspace.applications)
            email_events = validate_email_events(
                read_json(config.workspace.email_events)
            )
            active = {"screening", "assessment", "interview"}
            return {
                "jobs": len(jobs),
                "applications": len(applications),
                "newJobs": sum(job.get("poolStatus") == "discovered" for job in jobs),
                "preparing": sum(job.get("poolStatus") == "preparing" for job in jobs),
                "active": sum(item.get("status") in active for item in applications),
                "interviews": sum(item.get("status") == "interview" for item in applications),
                "offers": sum(item.get("status") == "offer" for item in applications),
                "pendingEmailEvents": sum(
                    item.get("state") == "pending" for item in email_events
                ),
            }

        def _email_status(self):
            state = validate_email_sync_state(read_json(config.workspace.email_sync))
            self._send_json(
                200,
                {
                    "provider": state.get("provider"),
                    "folder": state["folder"],
                    "initialWindowDays": state["initialWindowDays"],
                    "lastSyncedAt": state.get("lastSyncedAt"),
                    "readonly": True,
                },
            )

        def _email_events(self):
            events = validate_email_events(read_json(config.workspace.email_events))
            self._send_json(200, {"events": events})

        def _run_email_sync(self, payload: dict):
            if set(payload) - {"days"}:
                raise ValueError("email sync accepts only a days field")
            days = payload.get("days", 60)
            if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
                raise ValueError("days must be an integer from 1 to 3650")
            if not config.email_sync_lock.acquire(blocking=False):
                raise EventConflict("email sync is already running")
            try:
                runner = config.email_sync_runner or _default_email_sync_runner
                with config.lock:
                    result = runner(config.workspace, days)
                if not isinstance(result, dict):
                    raise ValueError("email sync runner returned an invalid result")
                self._send_json(200, result)
            finally:
                config.email_sync_lock.release()

        def _patch_email_event(self, event_id: str, payload: dict):
            if "updates" in payload:
                if set(payload) - {"updates", "updatedAt"}:
                    raise ValueError("unknown email event patch fields")
                updates = payload.get("updates")
            else:
                updates = {
                    key: value for key, value in payload.items() if key != "updatedAt"
                }
            if not isinstance(updates, dict):
                raise ValueError("email event updates must be an object")
            expected = payload.get("updatedAt")
            if not isinstance(expected, str) or not expected:
                raise ValueError("updatedAt is required")
            with config.lock:
                events = validate_email_events(
                    read_json(config.workspace.email_events)
                )
                index = _find_index(events, event_id)
                updated = patch_event(
                    events[index],
                    updates,
                    datetime.now(timezone.utc),
                    expected,
                )
                events[index] = updated
                write_json_atomic(
                    config.workspace.email_events,
                    events,
                    config.workspace.backups,
                )
            self._send_json(200, {"event": updated})

        def _confirm_email_event(self, event_id: str, payload: dict):
            with config.lock:
                result = confirm_event(
                    event_id,
                    payload,
                    config.workspace,
                    datetime.now(timezone.utc),
                )
            self._send_json(200, result)

        def _ignore_email_event(self, event_id: str, payload: dict):
            if set(payload) != {"ignored", "updatedAt"}:
                raise ValueError(
                    "ignore accepts exactly ignored and updatedAt fields"
                )
            if not isinstance(payload["ignored"], bool):
                raise ValueError("ignored must be boolean")
            if not isinstance(payload["updatedAt"], str) or not payload["updatedAt"]:
                raise ValueError("updatedAt is required")
            with config.lock:
                updated = set_event_ignored(
                    event_id,
                    payload["ignored"],
                    config.workspace,
                    datetime.now(timezone.utc),
                    expected_updated_at=payload["updatedAt"],
                )
            self._send_json(200, {"event": updated})

        def _patch_application(self, application_id: str, payload: dict):
            if "updates" in payload:
                unknown = set(payload) - {"updates", "updatedAt"}
                if unknown:
                    raise ValueError("unknown application patch fields")
                updates = payload.get("updates")
            else:
                updates = {key: value for key, value in payload.items() if key != "updatedAt"}
            expected = payload.get("updatedAt")
            with config.lock:
                applications = read_json(config.workspace.applications)
                index = _find_index(applications, application_id)
                updated = update_application(
                    applications[index],
                    updates,
                    datetime.now(timezone.utc),
                    "dashboard",
                    expected_updated_at=expected,
                )
                applications[index] = updated
                write_json_atomic(
                    config.workspace.applications,
                    applications,
                    config.workspace.backups,
                )
            self._send_json(200, {"application": updated})

        def _patch_job(self, job_id: str, payload: dict):
            if "updates" in payload:
                unknown = set(payload) - {"updates", "lastVerifiedAt"}
                if unknown:
                    raise ValueError("unknown job patch fields")
                updates = payload.get("updates")
            else:
                updates = {
                    key: value for key, value in payload.items() if key != "lastVerifiedAt"
                }
            if not isinstance(updates, dict) or set(updates) - {"poolStatus"}:
                raise ValueError("only poolStatus can be changed from the dashboard")
            with config.lock:
                jobs = read_json(config.workspace.jobs)
                index = _find_index(jobs, job_id)
                expected = payload.get("lastVerifiedAt")
                if expected is not None and expected != jobs[index].get("lastVerifiedAt"):
                    raise WorkspaceConflict("job changed after the dashboard loaded")
                updated = dict(jobs[index])
                updated.update(updates)
                updated = validate_job(updated)
                jobs[index] = updated
                write_json_atomic(config.workspace.jobs, jobs, config.workspace.backups)
            self._send_json(200, {"job": updated})

        def _create_application(self, payload: dict):
            if set(payload) - {"jobId", "confirmed"}:
                raise ValueError("unknown application creation fields")
            if payload.get("confirmed") is not True:
                raise ValueError(
                    "explicit confirmation is required before recording an application"
                )
            job_id = str(payload.get("jobId", ""))
            with config.lock:
                jobs = read_json(config.workspace.jobs)
                job_index = _find_index(jobs, job_id)
                applications = read_json(config.workspace.applications)
                if any(
                    item.get("jobId") == job_id and item.get("status") != "archived"
                    for item in applications
                ):
                    raise ApplicationConflict("an active application already exists")
                created, updated_job = create_application(
                    jobs[job_index],
                    datetime.now(timezone.utc),
                    confirmed=True,
                    channel="dashboard",
                )
                applications.append(created)
                jobs[job_index] = updated_job
                write_json_atomic(config.workspace.jobs, jobs, config.workspace.backups)
                write_json_atomic(
                    config.workspace.applications,
                    applications,
                    config.workspace.backups,
                )
            self._send_json(201, {"application": created, "job": updated_job})

        def _dispatch(self, method: str):
            parsed = urlsplit(self.path)
            path = parsed.path
            if not self._host_is_allowed():
                self._error(403, "unexpected Host header")
                return
            if method == "GET" and path == "/":
                supplied = parse_qs(parsed.query).get("token", [""])[0]
                if supplied and secrets.compare_digest(supplied, config.token):
                    self._redirect_with_cookie()
                    return
            if not self._authenticated():
                self._error(403, "invalid or missing session token")
                return
            if method in {"POST", "PATCH", "PUT", "DELETE"} and not self._origin_is_allowed():
                self._error(403, "cross-origin write rejected")
                return

            if method == "GET" and path == "/":
                self._send_html(
                    render_dashboard(self._dashboard_data(), editable=True, privacy=False)
                )
            elif method == "GET" and path == "/api/summary":
                self._send_json(200, self._summary())
            elif method == "GET" and path == "/api/jobs":
                self._send_json(200, {"jobs": read_json(config.workspace.jobs)})
            elif method == "GET" and path == "/api/applications":
                self._send_json(
                    200,
                    {"applications": read_json(config.workspace.applications)},
                )
            elif method == "GET" and path == "/api/company-policies":
                self._send_json(
                    200,
                    {
                        "companyPolicies": read_json(
                            config.workspace.company_policies
                        )
                    },
                )
            elif method == "GET" and path == "/api/email-sync/status":
                self._email_status()
            elif method == "GET" and path == "/api/email-events":
                self._email_events()
            elif method == "POST" and path == "/api/email-sync/run":
                self._run_email_sync(self._read_json())
            elif method == "PATCH" and path.startswith("/api/email-events/"):
                event_id = unquote(path.removeprefix("/api/email-events/"))
                if not event_id or "/" in event_id:
                    self._error(404, "route not found")
                else:
                    self._patch_email_event(event_id, self._read_json())
            elif (
                method == "POST"
                and path.startswith("/api/email-events/")
                and path.endswith("/confirm")
            ):
                encoded_id = path.removeprefix("/api/email-events/").removesuffix(
                    "/confirm"
                )
                event_id = unquote(encoded_id)
                if not event_id or "/" in event_id:
                    self._error(404, "route not found")
                else:
                    self._confirm_email_event(event_id, self._read_json())
            elif (
                method == "POST"
                and path.startswith("/api/email-events/")
                and path.endswith("/ignore")
            ):
                encoded_id = path.removeprefix("/api/email-events/").removesuffix(
                    "/ignore"
                )
                event_id = unquote(encoded_id)
                if not event_id or "/" in event_id:
                    self._error(404, "route not found")
                else:
                    self._ignore_email_event(event_id, self._read_json())
            elif method == "PATCH" and path.startswith("/api/jobs/"):
                self._patch_job(unquote(path.removeprefix("/api/jobs/")), self._read_json())
            elif method == "PATCH" and path.startswith("/api/applications/"):
                self._patch_application(
                    unquote(path.removeprefix("/api/applications/")), self._read_json()
                )
            elif method == "POST" and path == "/api/applications":
                self._create_application(self._read_json())
            elif method == "POST" and path == "/api/export":
                payload = self._read_json()
                if set(payload) - {"privacy"} or not isinstance(
                    payload.get("privacy", False), bool
                ):
                    raise ValueError("export accepts only a boolean privacy field")
                output = write_export(
                    config.workspace, privacy=payload.get("privacy", False)
                )
                self._send_json(200, {"file": output.name})
            else:
                self._error(404, "route not found")

        def _handle(self, method: str):
            try:
                self._dispatch(method)
            except PayloadTooLarge as exc:
                self._error(413, str(exc))
            except (ApplicationConflict, EventConflict, WorkspaceConflict) as exc:
                self._error(409, str(exc))
            except (ApplicationNotFound, EventNotFound) as exc:
                self._error(404, str(exc))
            except (
                EmailSyncError,
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
            ) as exc:
                self._error(400, str(exc))
            except Exception:
                self._error(500, "internal server error")

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PATCH(self):
            self._handle("PATCH")

        def do_OPTIONS(self):
            self._error(403, "cross-origin access is disabled")

    return DashboardHandler


def create_server(
    workspace: Workspace,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str | None = None,
    *,
    email_sync_runner: Callable[[Workspace, int], dict] | None = None,
) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Job Radar only permits a loopback host")
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    session_token = token or secrets.token_urlsafe(32)
    if not session_token:
        raise ValueError("session token cannot be empty")
    config = ServerConfig(
        workspace=workspace,
        host=host,
        port=port,
        token=session_token,
        email_sync_runner=email_sync_runner,
    )
    server = ThreadingHTTPServer((host, port), _handler_factory(config))
    server.daemon_threads = True
    config.port = server.server_port
    server.job_radar_config = config
    return server


def serve(
    workspace: Workspace,
    *,
    port: int = 0,
    open_browser: bool = True,
) -> str:
    token = secrets.token_urlsafe(32)
    server = create_server(workspace, "127.0.0.1", port, token)
    url = f"http://127.0.0.1:{server.server_port}/?token={quote(token)}"
    print(f"Job Radar dashboard: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return url
