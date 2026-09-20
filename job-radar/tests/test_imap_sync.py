import email.policy
import unittest
from datetime import datetime
from email.message import EmailMessage

from job_radar_lib.imap_sync import (
    EmailSyncError,
    ImapConfig,
    parse_message,
    sync_messages,
    test_connection as check_connection,
)
from tests.helpers import NOW, email_sync_state


def raw_message(
    *,
    subject="在线测评邀请",
    body="请于 8 月 30 日完成在线测评",
    html=None,
    attachment=False,
):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "Recruiting Team <jobs@jobs.example.com>"
    message["Date"] = "Fri, 21 Aug 2026 09:30:00 +0800"
    message["Message-ID"] = "<synthetic-42@example.com>"
    message.set_content(body)
    if html is not None:
        message.add_alternative(html, subtype="html")
    if attachment:
        message.add_attachment(
            b"attachment payload",
            maintype="application",
            subtype="octet-stream",
            filename="resume.pdf",
        )
    return message.as_bytes(policy=email.policy.default)


class FakeImap:
    def __init__(self, host, port, ssl_context=None, *, uid_validity=7, uids=(41, 42)):
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.uid_validity = uid_validity
        self.uids = tuple(uids)
        self.select_calls = []
        self.search_criteria = []
        self.fetch_calls = []
        self.login_calls = []

    def login(self, username, password):
        self.login_calls.append((username, password))
        return "OK", [b"logged in"]

    def select(self, folder, readonly=False):
        self.select_calls.append((folder, readonly))
        return "OK", [str(len(self.uids)).encode()]

    def response(self, name):
        if name == "UIDVALIDITY":
            return "UIDVALIDITY", [str(self.uid_validity).encode()]
        return None, []

    def uid(self, command, *args):
        if command.lower() == "search":
            criterion = str(args[-1])
            self.search_criteria.append(criterion)
            return "OK", [b" ".join(str(uid).encode() for uid in self.uids)]
        if command.lower() == "fetch":
            uid = int(args[0])
            query = str(args[1])
            self.fetch_calls.append((uid, query))
            raw = raw_message(subject=f"在线测评邀请 {uid}")
            metadata = f'{uid} (UID {uid} INTERNALDATE "21-Aug-2026 09:30:00 +0800" BODY[] {{{len(raw)}}}'.encode()
            return "OK", [(metadata, raw), b")"]
        raise AssertionError(command)

    def logout(self):
        return "BYE", [b"logout"]


class FakeFactory:
    def __init__(self, **client_options):
        self.instances = []
        self.client_options = client_options

    def __call__(self, host, port, ssl_context=None):
        instance = FakeImap(host, port, ssl_context, **self.client_options)
        self.instances.append(instance)
        return instance


def qq_config():
    return ImapConfig.from_env(
        {
            "JOB_RADAR_IMAP_USERNAME": "candidate@qq.com",
            "JOB_RADAR_IMAP_APP_PASSWORD": "app-secret",
            "JOB_RADAR_IMAP_PROVIDER": "qq",
        }
    )


class ImapConfigTests(unittest.TestCase):
    def test_default_auto_detects_common_personal_mailboxes(self):
        cases = {
            "candidate@qq.com": ("qq", "imap.qq.com", 993),
            "candidate@163.com": ("netease-163", "imap.163.com", 993),
            "candidate@126.com": ("netease-126", "imap.126.com", 993),
            "candidate@yeah.net": ("netease-yeah", "imap.yeah.net", 993),
            "candidate@gmail.com": ("gmail", "imap.gmail.com", 993),
            "candidate@googlemail.com": ("gmail", "imap.gmail.com", 993),
        }

        for username, expected in cases.items():
            with self.subTest(username=username):
                config = ImapConfig.from_env(
                    {
                        "JOB_RADAR_IMAP_USERNAME": username,
                        "JOB_RADAR_IMAP_APP_PASSWORD": "app-secret",
                    }
                )
                self.assertEqual(
                    (config.provider, config.host, config.port), expected
                )

    def test_enterprise_provider_presets_use_tls_imap(self):
        cases = {
            "tencent-enterprise": "imap.exmail.qq.com",
            "netease-enterprise": "imap.qiye.163.com",
            "aliyun-enterprise": "imap.qiye.aliyun.com",
        }

        for provider, expected_host in cases.items():
            with self.subTest(provider=provider):
                config = ImapConfig.from_env(
                    {
                        "JOB_RADAR_IMAP_USERNAME": "candidate@company.example",
                        "JOB_RADAR_IMAP_APP_PASSWORD": "app-secret",
                        "JOB_RADAR_IMAP_PROVIDER": provider,
                    }
                )
                self.assertEqual(
                    (config.provider, config.host, config.port),
                    (provider, expected_host, 993),
                )

    def test_auto_unknown_domain_requires_custom_configuration(self):
        with self.assertRaisesRegex(
            EmailSyncError,
            "cannot auto-detect the IMAP provider; set "
            "JOB_RADAR_IMAP_PROVIDER=custom",
        ):
            ImapConfig.from_env(
                {
                    "JOB_RADAR_IMAP_USERNAME": "candidate@example.com",
                    "JOB_RADAR_IMAP_APP_PASSWORD": "app-secret",
                }
            )

    def test_qq_preset_is_secret_safe(self):
        config = qq_config()
        self.assertEqual((config.host, config.port), ("imap.qq.com", 993))
        self.assertNotIn("candidate@qq.com", repr(config))
        self.assertNotIn("app-secret", repr(config))

    def test_custom_provider_requires_host_and_valid_port(self):
        common = {
            "JOB_RADAR_IMAP_USERNAME": "candidate@example.com",
            "JOB_RADAR_IMAP_APP_PASSWORD": "secret",
            "JOB_RADAR_IMAP_PROVIDER": "custom",
        }
        with self.assertRaisesRegex(EmailSyncError, "JOB_RADAR_IMAP_HOST is not set"):
            ImapConfig.from_env(common)
        with self.assertRaisesRegex(EmailSyncError, "JOB_RADAR_IMAP_PORT must be an integer"):
            ImapConfig.from_env({**common, "JOB_RADAR_IMAP_HOST": "mail.example.com", "JOB_RADAR_IMAP_PORT": "oops"})


class ImapSyncTests(unittest.TestCase):
    def test_qq_preset_uses_tls_readonly_and_body_peek(self):
        factory = FakeFactory()
        batch = sync_messages(
            qq_config(), email_sync_state(), NOW, client_factory=factory
        )
        client = factory.instances[0]
        self.assertIsNotNone(client.ssl_context)
        self.assertIn(("INBOX", True), client.select_calls)
        self.assertTrue(
            all("BODY.PEEK[]" in query for _, query in client.fetch_calls)
        )
        self.assertEqual(batch.state["lastSeenUid"], 42)
        self.assertEqual(len(batch.messages), 2)

    def test_incremental_sync_searches_only_uids_after_cursor(self):
        factory = FakeFactory(uids=(41, 42))
        sync_messages(
            qq_config(),
            email_sync_state(lastSeenUid=40, uidValidity=7),
            NOW,
            client_factory=factory,
        )
        self.assertIn("UID 41:*", factory.instances[0].search_criteria)

    def test_changed_uidvalidity_restarts_with_sixty_day_window(self):
        factory = FakeFactory(uid_validity=8, uids=())
        batch = sync_messages(
            qq_config(), email_sync_state(uidValidity=7), NOW, client_factory=factory
        )
        self.assertIn("SINCE 22-Jun-2026", factory.instances[0].search_criteria)
        self.assertEqual(batch.state["uidValidity"], 8)

    def test_connection_summary_contains_no_mailbox_identity(self):
        factory = FakeFactory(uids=())
        result = check_connection(qq_config(), client_factory=factory)
        self.assertEqual(result["provider"], "qq")
        self.assertTrue(result["readonly"])
        self.assertNotIn("username", result)

    def test_mime_parser_skips_attachment_and_remote_resources(self):
        raw = raw_message(
            body="请于 8 月 30 日完成在线测评",
            html='<p>测评邀请</p><img src="https://tracker.example/pixel"><script>secret()</script>',
            attachment=True,
        )
        message = parse_message(7, 42, raw)
        self.assertEqual(message.text, "请于 8 月 30 日完成在线测评")
        self.assertTrue(message.has_attachments)
        self.assertNotIn("attachment payload", message.text)
        self.assertNotIn("tracker.example", message.text)
        self.assertNotIn("secret()", message.text)

    def test_html_only_message_is_reduced_to_visible_text(self):
        message = EmailMessage()
        message["Subject"] = "技术面试"
        message["From"] = "jobs@example.com"
        message["Date"] = "Fri, 21 Aug 2026 09:30:00 +0800"
        message.set_content('<p>请参加<b>技术一面</b></p><style>.x{}</style>', subtype="html")
        parsed = parse_message(7, 3, message.as_bytes())
        self.assertIn("请参加 技术一面", parsed.text)
        self.assertNotIn(".x{}", parsed.text)

    def test_oversized_message_becomes_safe_issue_and_later_uid_continues(self):
        class OversizedFirst(FakeImap):
            def uid(self, command, *args):
                if command.lower() == "fetch" and int(args[0]) == 41:
                    raw = b"x" * (2 * 1024 * 1024 + 1)
                    self.fetch_calls.append((41, str(args[1])))
                    return "OK", [(b"41 (UID 41 BODY[]", raw), b")"]
                return super().uid(command, *args)

        class Factory(FakeFactory):
            def __call__(self, host, port, ssl_context=None):
                instance = OversizedFirst(host, port, ssl_context)
                self.instances.append(instance)
                return instance

        batch = sync_messages(
            qq_config(),
            email_sync_state(lastSeenUid=40),
            NOW,
            client_factory=Factory(),
        )
        self.assertEqual([issue.error_category for issue in batch.issues], ["message_too_large"])
        self.assertEqual([message.uid for message in batch.messages], [42])
        self.assertEqual(batch.state["lastSeenUid"], 42)


if __name__ == "__main__":
    unittest.main()
