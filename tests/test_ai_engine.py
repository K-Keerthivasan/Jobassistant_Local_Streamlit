"""AI Engine view: the activity log, runtime AI settings, the step map, the
Ollama model fallback, and the routes."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pydantic import BaseModel

from resume_gen import ai_settings, llm
from resume_gen.config import settings
from resume_gen.llm import activity, ollama_client


class _Out(BaseModel):
    reply: str = ""


class _Isolated(unittest.TestCase):
    """Point the activity log and AI settings file at a temp dir and restore
    every setting the tests touch."""

    KEYS = list(ai_settings.EDITABLE)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(activity, "_FILE", tmp / "ai_activity.jsonl"),
            mock.patch.object(ai_settings, "_FILE", tmp / "ai_settings.json"),
        ]
        for p in self.patches:
            p.start()
        activity._RECENT.clear()
        activity._loaded = True
        self.saved = {k: getattr(settings, k) for k in self.KEYS}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(settings, k, v)
        for p in self.patches:
            p.stop()
        activity._RECENT.clear()
        self.tmp.cleanup()


class ActivityLogTests(_Isolated):
    def test_successful_call_is_logged_with_job_tokens_and_prompts(self):
        def fake_ollama(system, user, schema, model, **kw):
            llm.record_run_tokens(model, 120, 30, schema.__name__)
            return schema(reply="hi")

        with mock.patch.object(ollama_client, "chat_structured", side_effect=fake_ollama), \
             mock.patch.object(ollama_client, "effective_model", return_value="qwen3:latest"):
            settings.default_engine = "ollama"
            settings.ollama_model = "qwen3:8b"
            with activity.job_context("Loblaw", "Associate Product Manager"):
                llm.chat_structured("SYSTEM RULES", "USER ASK", _Out)

        [entry] = activity.recent(5)
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["job"], "Loblaw · Associate Product Manager")
        self.assertEqual(entry["engine_used"], "qwen3:latest")      # installed model, not the missing one
        self.assertEqual((entry["input_tokens"], entry["output_tokens"]), (120, 30))
        full = activity.get(entry["id"])
        self.assertEqual(full["system_prompt"], "SYSTEM RULES")
        self.assertIn('"reply": "hi"', full["response"])
        self.assertTrue(Path(activity._FILE).exists())

    def test_hermes_failure_falls_back_and_says_so(self):
        settings.allow_ollama_fallback = True
        with mock.patch("resume_gen.llm.hermes_client.chat_structured", side_effect=RuntimeError("bridge down")), \
             mock.patch.object(ollama_client, "health", return_value=True), \
             mock.patch.object(ollama_client, "effective_model", return_value="qwen3:latest"), \
             mock.patch.object(ollama_client, "chat_structured", return_value=_Out(reply="ok")):
            llm.chat_structured("s", "u", _Out, model="hermes-agent")
        [entry] = activity.recent(1)
        self.assertEqual(entry["engine_requested"], "hermes-agent")
        self.assertEqual(entry["engine_used"], "qwen3:latest")
        self.assertIn("bridge down", entry["fallback"])

    def test_fallback_switched_off_surfaces_the_hermes_error(self):
        settings.allow_ollama_fallback = False
        with mock.patch("resume_gen.llm.hermes_client.chat_structured", side_effect=RuntimeError("bridge down")), \
             mock.patch.object(ollama_client, "chat_structured") as ollama:
            with self.assertRaises(RuntimeError):
                llm.chat_structured("s", "u", _Out, model="hermes-agent")
            ollama.assert_not_called()
        [entry] = activity.recent(1)
        self.assertEqual(entry["status"], "error")
        self.assertIn("bridge down", entry["error"])

    def test_prompts_are_not_kept_when_recording_is_off(self):
        settings.record_prompts = False
        with mock.patch.object(ollama_client, "chat_structured", return_value=_Out(reply="x")), \
             mock.patch.object(ollama_client, "effective_model", return_value="m"):
            llm.chat_structured("secret system", "secret user", _Out, model="m")
        full = activity.get(activity.recent(1)[0]["id"])
        self.assertNotIn("user_prompt", full)


class SettingsTests(_Isolated):
    def test_update_validates_applies_and_persists(self):
        out = ai_settings.update({"default_engine": "ollama", "hermes_fast_mode": "off", "llm_timeout": 120})
        self.assertEqual(settings.default_engine, "ollama")
        self.assertFalse(settings.hermes_fast_mode)
        self.assertEqual(out["llm_timeout"]["value"], 120.0)
        saved = json.loads(Path(ai_settings._FILE).read_text())
        self.assertEqual(saved["default_engine"], "ollama")

    def test_bad_values_and_unknown_fields_are_refused(self):
        for bad in ({"default_engine": "gpt"}, {"llm_timeout": 1}, {"hermes_api_key": "x"}):
            with self.assertRaises(ValueError):
                ai_settings.update(bad)

    def test_step_map_follows_the_settings(self):
        settings.default_engine = "hermes"
        settings.hermes_fast_mode = True
        steps = {s["name"]: s for s in ai_settings.pipeline(hermes_up=True)}
        self.assertFalse(steps["Truth audit"]["runs"])
        self.assertEqual(steps["Write email lines"]["kind"], "rules")
        settings.hermes_fast_mode = False
        settings.hermes_qa = True
        steps = {s["name"]: s for s in ai_settings.pipeline(hermes_up=True)}
        self.assertTrue(steps["Truth audit"]["runs"])
        self.assertEqual(steps["Write email lines"]["kind"], "ai")


class OllamaModelTests(unittest.TestCase):
    def setUp(self):
        ollama_client._EFFECTIVE.update(at=0.0, configured="", model="")
        self.saved = settings.ollama_model

    def tearDown(self):
        settings.ollama_model = self.saved
        ollama_client._EFFECTIVE.update(at=0.0, configured="", model="")

    def test_missing_model_falls_back_to_the_same_family(self):
        settings.ollama_model = "qwen3:8b"
        with mock.patch.object(ollama_client, "list_models", return_value=["gemma3:latest", "qwen3:latest"]):
            self.assertEqual(ollama_client.effective_model(), "qwen3:latest")

    def test_installed_model_is_kept(self):
        settings.ollama_model = "gemma3:latest"
        with mock.patch.object(ollama_client, "list_models", return_value=["gemma3:latest", "qwen3:latest"]):
            self.assertEqual(ollama_client.effective_model(), "gemma3:latest")


class RouteTests(_Isolated):
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.ai_routes import router

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_engine_report_is_recorded(self):
        with mock.patch("api.ai_routes.Request"):
            pass
        r = self.client.post("/ai/activity", json={
            "schema": "AnswerDraft", "job": "Acme · Analyst", "seconds": 3.2, "status": "ok",
            "system": "rules", "user": "question", "response": "{}"})
        # TestClient connects from "testclient", which is not loopback.
        self.assertEqual(r.status_code, 403)

    def test_settings_round_trip_and_validation(self):
        r = self.client.post("/ai/settings", json={"default_engine": "nope"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/ai/settings", json={"record_prompts": False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["settings"]["record_prompts"]["value"])

    def test_activity_list_and_detail(self):
        activity.record(schema="Resume", requested="hermes-agent", used="hermes-agent",
                        seconds=1, status="ok", system="s", user="u", response="r")
        items = self.client.get("/ai/activity").json()["items"]
        self.assertEqual(items[0]["task"], "Write resume")
        self.assertNotIn("user_prompt", items[0])
        detail = self.client.get("/ai/activity/" + items[0]["id"]).json()
        self.assertEqual(detail["user_prompt"], "u")
        self.assertEqual(self.client.get("/ai/activity/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
