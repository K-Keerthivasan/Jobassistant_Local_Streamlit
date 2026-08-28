import unittest
from unittest.mock import patch

from resume_gen.automation import autoapply
from resume_gen.intake import apply_sessions


class ApprovalGateTests(unittest.TestCase):
    def test_approved_session_retry_is_idempotent(self):
        existing = {
            "session_id": "session-1",
            "status": apply_sessions.APPROVED,
            "submit_by": "agent",
            "banked_answers": [{"id": "answer-1"}],
        }
        with (
            patch.object(apply_sessions, "get_session", return_value=existing),
            patch.object(autoapply.answers_bank, "save_answer") as save_answer,
            patch.object(apply_sessions, "set_status") as set_status,
        ):
            result = autoapply.confirm("session-1", approved=True)

        self.assertTrue(result["approved"])
        self.assertTrue(result["already_decided"])
        self.assertTrue(result["may_submit"])
        save_answer.assert_not_called()
        set_status.assert_not_called()

    def test_profile_answer_is_not_duplicated_in_bank(self):
        existing = {
            "session_id": "session-2",
            "status": apply_sessions.PREPARED,
            "company": "Example Co",
            "screening_answers": [{
                "question": "Are you authorized to work?",
                "answer": "Yes",
                "source": "profile",
                "verified": True,
            }],
            "standard_fields": [],
        }
        with (
            patch.object(apply_sessions, "get_session", return_value=existing),
            patch.object(autoapply.answers_bank, "save_answer") as save_answer,
            patch.object(apply_sessions, "set_status"),
        ):
            result = autoapply.confirm("session-2", approved=True)

        self.assertTrue(result["approved"])
        self.assertEqual(result["banked"], [])
        save_answer.assert_not_called()

    def test_submitted_result_requires_verified_success(self):
        existing = {
            "session_id": "session-3",
            "status": apply_sessions.APPROVED,
            "job_key": "job-1",
        }
        with patch.object(apply_sessions, "get_session", return_value=existing):
            with self.assertRaisesRegex(ValueError, "verified_success=true"):
                autoapply.log_outcome(
                    "session-3", status="submitted", verified_success=False
                )

if __name__ == "__main__":
    unittest.main()
