import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import BaseModel
from resume_gen import llm
from resume_gen.llm import hermes_client, ollama_client


class Answer(BaseModel):
    answer: str


class HermesRateLimitTests(unittest.TestCase):
    def test_quota_never_switches_to_ollama(self):
        with patch.object(hermes_client, 'chat_structured', side_effect=hermes_client.HermesRateLimitError('retry_after=600')), \
             patch.object(ollama_client, 'chat_structured') as fallback:
            with self.assertRaises(hermes_client.HermesRateLimitError):
                llm.chat_structured('system', 'user', Answer, model='hermes-agent')
            fallback.assert_not_called()

    def test_retry_after_survives_http_response(self):
        response = SimpleNamespace(status_code=429, headers={'Retry-After': '1234'})
        with patch.object(hermes_client.httpx, 'post', return_value=response):
            with self.assertRaisesRegex(hermes_client.HermesRateLimitError, 'retry_after=1234'):
                hermes_client._chat([], model='hermes-agent', timeout=1)
