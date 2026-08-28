import asyncio
import unittest
from unittest.mock import patch

from resume_gen.mcp_server import INSTRUCTIONS, list_application_candidates, mcp


class McpServerTests(unittest.TestCase):
    def test_exposes_focused_approval_first_tools(self):
        tools = asyncio.run(mcp.list_tools())
        by_name = {tool.name: tool for tool in tools}

        self.assertEqual(
            set(by_name),
            {
                "list_job_opportunities",
                "list_application_candidates",
                "get_job_opportunity",
                "list_application_history",
                "prepare_job_application",
                "get_application_approval",
                "decide_job_application",
                "record_application_result",
                "update_job_tracking",
            },
        )
        self.assertTrue(by_name["list_job_opportunities"].annotations.readOnlyHint)
        self.assertTrue(by_name["list_application_candidates"].annotations.readOnlyHint)
        self.assertTrue(by_name["decide_job_application"].annotations.destructiveHint)
        self.assertFalse(by_name["prepare_job_application"].annotations.openWorldHint)
        self.assertIn("fresh yes/no decision", INSTRUCTIONS)
        self.assertIn("Never click Submit", INSTRUCTIONS)

    def test_application_candidates_are_capped_and_report_restrictions(self):
        rows = [{"key_id": "one", "likely_blocked": False},
                {"key_id": "two", "likely_blocked": True}]
        with patch("resume_gen.mcp_server.autoapply.candidates", return_value=rows) as candidates:
            result = list_application_candidates(days=7, limit=500)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["likely_restricted"], 1)
        self.assertEqual(candidates.call_args.kwargs["limit"], 100)


if __name__ == "__main__":
    unittest.main()
