import unittest

from job_radar_lib.email_classification import classify_message
from job_radar_lib.imap_sync import FetchedMessage
from tests.helpers import NOW


def message(subject="", text="", sender_domain="jobs.example.com"):
    return FetchedMessage(
        uid_validity=7,
        uid=42,
        message_id="<synthetic@example.com>",
        received_at="2026-08-21T09:30:00+08:00",
        sender_domain=sender_domain,
        subject=subject,
        text=text,
        has_attachments=False,
    )


class EmailClassificationTests(unittest.TestCase):
    def test_explicit_stage_evidence(self):
        cases = [
            ("投递成功", "您的字节跳动申请已收到", "applied"),
            ("简历进度", "您的简历已进入筛选", "screening"),
            ("在线测评", "请于2026年8月30日23:59前完成测评", "assessment"),
            ("技术一面", "邀请参加后端开发技术一面", "interview"),
            ("录用通知", "正式录用通知书", "offer"),
            ("未通过", "很遗憾本次流程未能继续", "rejected"),
            ("岗位关闭", "该岗位招聘流程已关闭", "closed"),
        ]
        for subject, text, expected in cases:
            with self.subTest(expected=expected):
                result = classify_message(message(subject, text), NOW)
                self.assertEqual(result.proposed_status, expected)
                self.assertEqual(result.classification, "actionable")
                self.assertGreaterEqual(result.confidence, 0.45)

    def test_talent_pool_and_marketing_are_not_stage_updates(self):
        result = classify_message(
            message("加入人才库", "订阅校招资讯与宣讲会"), NOW
        )
        self.assertIsNone(result.proposed_status)
        self.assertEqual(result.classification, "irrelevant")

    def test_ambiguous_thanks_is_incomplete(self):
        result = classify_message(
            message("感谢关注", "期待未来保持联系"), NOW
        )
        self.assertIsNone(result.proposed_status)
        self.assertEqual(result.classification, "incomplete")

    def test_sender_domain_alone_never_proves_a_stage(self):
        result = classify_message(
            message("您好", "请查看最新消息", "recruit.bytedance.com"), NOW
        )
        self.assertIsNone(result.proposed_status)
        self.assertEqual(result.classification, "incomplete")

    def test_contradictory_stage_evidence_is_a_conflict(self):
        result = classify_message(
            message("录用结果", "正式录用通知；很遗憾本次流程未能继续"), NOW
        )
        self.assertIsNone(result.proposed_status)
        self.assertEqual(result.classification, "conflict")
        self.assertTrue(any("矛盾" in reason for reason in result.reasons))

    def test_extracts_labeled_fields_stage_and_chinese_deadline(self):
        result = classify_message(
            message(
                "技术一面邀请",
                "公司：示例科技\n应聘岗位：AI 应用开发工程师\n职位编号：JR-42\n"
                "请于2026年8月30日 14:30前参加技术一面",
            ),
            NOW,
        )
        self.assertEqual(result.company, "示例科技")
        self.assertEqual(result.title, "AI 应用开发工程师")
        self.assertEqual(result.employer_job_id, "JR-42")
        self.assertEqual(result.interview_stage, "技术一面")
        self.assertEqual(result.next_action_at, "2026-08-30T14:30:00+08:00")
        self.assertEqual(result.confidence, 1.0)

    def test_extracts_company_from_received_application_phrase(self):
        result = classify_message(
            message("申请已收到", "您的字节跳动申请已收到"), NOW
        )
        self.assertEqual(result.company, "字节跳动")

    def test_malformed_deadline_is_not_invented(self):
        result = classify_message(
            message("在线测评", "请于2026年13月40日前完成在线测评"), NOW
        )
        self.assertEqual(result.proposed_status, "assessment")
        self.assertIsNone(result.next_action_at)
        self.assertTrue(any("日期" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
