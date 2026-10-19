import unittest
from types import SimpleNamespace
from unittest.mock import patch

from resume_gen.llm import hermes_client


class HermesHealthTests(unittest.TestCase):
    def test_only_authenticated_success_is_ready(self):
        for status in (200, 401, 403, 500):
            with self.subTest(status=status), patch.object(
                hermes_client.httpx, 'get', return_value=SimpleNamespace(status_code=status)
            ):
                self.assertEqual(hermes_client.health(), status == 200)

