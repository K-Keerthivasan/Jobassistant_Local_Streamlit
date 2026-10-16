"""A run fails fast with a clear message when no engine can be reached, instead
of silently switching to an Ollama that is not installed and returning a 500."""

import unittest
from unittest import mock

from resume_gen import pipeline
from resume_gen.llm import hermes_client, ollama_client


class EngineCheckTests(unittest.TestCase):
    def _check(self, model, hermes_up, ollama_up, engine="hermes"):
        with mock.patch.object(hermes_client, "health", return_value=hermes_up), \
             mock.patch.object(ollama_client, "health", return_value=ollama_up), \
             mock.patch.object(pipeline.settings, "default_engine", engine):
            pipeline.check_engines(model)

    def test_both_down_raises_a_message_naming_the_bridge(self):
        with self.assertRaises(pipeline.EngineUnavailable) as ctx:
            self._check(None, hermes_up=False, ollama_up=False)
        self.assertIn("start_hermes_bridge.ps1", str(ctx.exception))

    def test_hermes_up_passes(self):
        self._check(None, hermes_up=True, ollama_up=False)
        self._check("hermes-agent", hermes_up=True, ollama_up=False)

    def test_ollama_fallback_still_allowed_when_installed(self):
        self._check(None, hermes_up=False, ollama_up=True)

    def test_explicit_ollama_model_is_not_checked_against_hermes(self):
        self._check("qwen3:8b", hermes_up=False, ollama_up=False)


if __name__ == "__main__":
    unittest.main()
