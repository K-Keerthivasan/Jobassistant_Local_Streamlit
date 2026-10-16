import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import application_engine_routes as routes


class ApplicationEngineRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(routes.router)
        self.client = TestClient(self.app)

    def test_cross_origin_is_refused(self):
        response = self.client.post('/application-engine/answers', headers={'Origin': 'https://attacker.example'}, json={
            'question': 'Notice period?', 'answer': 'Two weeks', 'confirmed': True, 'reuse': True})
        self.assertEqual(response.status_code, 403)

    def test_confirmed_answers_save_profile_provenance_without_touching_real_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            profile = root / 'data' / 'apply_profile.json'
            profile.write_text(json.dumps({'firstName': 'Jordan'}), encoding='utf-8')
            with patch.object(routes, 'ROOT', root):
                response = self.client.post('/application-engine/answers', json={
                    'question': 'Notice period?', 'answer': 'Two weeks', 'confirmed': True, 'reuse': True})
            self.assertEqual(response.status_code, 200)
            saved = json.loads(profile.read_text(encoding='utf-8'))
            self.assertEqual(saved['commonAnswers']['Notice period?'], 'Two weeks')
            self.assertEqual(saved['answerProvenance']['Notice period?']['source'], 'user_confirmed')
            self.assertEqual(saved['firstName'], 'Jordan')

    def test_sensitive_and_unconfirmed_answers_are_never_banked(self):
        for question, confirmed in [('Gender', True), ('I agree to terms', True), ('Notice period?', False)]:
            response = self.client.post('/application-engine/answers', json={
                'question': question, 'answer': 'example', 'confirmed': confirmed, 'reuse': True})
            self.assertEqual(response.status_code, 400)

    def test_confirmed_profile_fact_is_saved_with_provenance_and_credentials_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            profile = root / 'data' / 'apply_profile.json'
            profile.write_text(json.dumps({'firstName': 'Jordan'}), encoding='utf-8')
            with patch.object(routes, 'ROOT', root):
                response = self.client.post('/application-engine/profile-fact', json={
                    'key': 'employmentHistory', 'value': [{'company': 'Confirmed Employer', 'title': 'Engineer'}], 'confirmed': True})
                rejected = self.client.post('/application-engine/profile-fact', json={
                    'key': 'password', 'value': 'not-stored', 'confirmed': True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(rejected.status_code, 422)
            saved = json.loads(profile.read_text(encoding='utf-8'))
            self.assertEqual(saved['employmentHistory'][0]['company'], 'Confirmed Employer')
            self.assertEqual(saved['factProvenance']['employmentHistory']['source'], 'user_confirmed')
            self.assertNotIn('password', saved)

    def test_snapshot_is_only_saved_to_unapproved_session_and_does_not_bank_manual_answers(self):
        session = {'session_id': 'one', 'status': 'prepared', 'screening_answers': [{'answer': 'old'}]}
        with patch.object(routes.apply_sessions, 'get_session', return_value=session), \
             patch.object(routes.apply_sessions, 'save_session') as save:
            response = self.client.post('/application-engine/one/snapshot', json={
                'snapshot': {'url': 'https://employer.example/apply', 'fields': [
                    {'label': 'First name', 'value': 'Jordan', 'required': True},
                    {'label': 'Unknown optional question', 'value': '', 'required': False}], 'blockers': []},
                'documents': [], 'filled': [], 'engine_id': 'engine-one', 'review_hash': 'hash'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(save.call_args.args[0]['screening_answers'], [])
        self.assertEqual(save.call_args.args[0]['standard_fields'][0]['value'], 'Jordan')
        with patch.object(routes.apply_sessions, 'get_session', return_value={**session, 'status': 'approved'}):
            response = self.client.post('/application-engine/one/snapshot', json={
                'snapshot': {'url': 'https://employer.example'}, 'documents': [], 'engine_id': 'one', 'review_hash': 'hash'})
            self.assertEqual(response.status_code, 409)

    def test_prepare_requires_run_linked_to_unapplied_job(self):
        from types import SimpleNamespace
        from resume_gen.automation import autoapply
        job = SimpleNamespace(applied=False, company='Example', title='Engineer', apply_url='https://employer.example/job')
        with patch.object(routes.store, 'get_job', return_value=job), \
             patch.object(routes.runs, 'get_run', return_value={'run_id': 'one'}), \
             patch.object(autoapply, 'candidates', return_value=[]), \
             patch.object(autoapply, 'prepare') as prepare:
            response = self.client.post('/application-engine/prepare', json={'job_key': 'job', 'run_id': 'one'})
        self.assertEqual(response.status_code, 400)
        prepare.assert_not_called()

    def test_validation_refuses_jobs_that_were_already_applied(self):
        from types import SimpleNamespace
        session = {'session_id': 'one', 'status': 'prepared', 'job_key': 'job'}
        for applied, expected in [(False, 200), (True, 409)]:
            with patch.object(routes.apply_sessions, 'get_session', return_value=session), \
                 patch.object(routes.store, 'get_job', return_value=SimpleNamespace(applied=applied, status='generated')):
                self.assertEqual(self.client.get('/application-engine/one/validate').status_code, expected)


if __name__ == '__main__':
    unittest.main()
