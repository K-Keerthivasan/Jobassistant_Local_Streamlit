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

    def test_application_only_answer_is_scoped_and_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            profile = root / 'data' / 'apply_profile.json'
            profile.write_text('{}', encoding='utf-8')
            with patch.object(routes, 'ROOT', root), patch.object(routes.apply_sessions, 'get_session', return_value={'session_id':'one'}):
                response = self.client.post('/application-engine/answers', json={
                    'question':'Expected pay?', 'answer':'85000', 'confirmed':True, 'reuse':False, 'session_id':'one'})
            self.assertEqual(response.status_code, 200)
            saved = json.loads(profile.read_text(encoding='utf-8'))
            self.assertEqual(saved['applicationAnswers']['one']['Expected pay?'], '85000')
            self.assertNotIn('Expected pay?', saved.get('commonAnswers', {}))
            self.assertFalse(saved['answerProvenance']['one:Expected pay?']['reuseAllowed'])

    def test_application_only_answer_requires_a_real_session(self):
        with patch.object(routes.apply_sessions, 'get_session', return_value=None):
            response = self.client.post('/application-engine/answers', json={
                'question':'Expected pay?', 'answer':'85000', 'confirmed':True, 'reuse':False, 'session_id':'missing'})
        self.assertEqual(response.status_code, 400)

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



    def test_resume_history_uses_this_sessions_generated_run(self):
        with patch.object(routes.apply_sessions, 'get_session', return_value={'status': 'prepared', 'run_id': 'this-run'}), patch.object(routes.runs, 'get_run', return_value={'resume': {'experience': [{'company': 'Example', 'role': 'Tailored role'}], 'education': []}}) as read_run:
            response = self.client.get('/application-engine/session/resume-history')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['experience'][0]['role'], 'Tailored role')
        read_run.assert_called_once_with('this-run')


    def test_answer_context_is_scoped_and_omits_contact_details(self):
        from types import SimpleNamespace
        with patch.object(routes.apply_sessions, 'get_session', return_value={'status': 'prepared', 'run_id': 'run', 'job_key': 'job', 'company': 'Example', 'title': 'Engineer'}), patch.object(routes.runs, 'get_run', return_value={'resume': {'contact': {'email': 'private@example.com'}, 'experience': [{'role': 'Developer'}]}}), patch.object(routes.store, 'get_job', return_value=SimpleNamespace(applied=False, description='SQL role')):
            response = self.client.get('/application-engine/session/answer-context')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['description'], 'SQL role')
        self.assertNotIn('private@example.com', response.text)

    def test_answer_context_refuses_already_applied_jobs(self):
        from types import SimpleNamespace
        with patch.object(routes.apply_sessions, 'get_session', return_value={'status': 'prepared', 'run_id': 'run', 'job_key': 'job'}), patch.object(routes.runs, 'get_run', return_value={'resume': {}}), patch.object(routes.store, 'get_job', return_value=SimpleNamespace(applied=True)):
            self.assertEqual(self.client.get('/application-engine/session/answer-context').status_code, 409)

    def test_blank_choice_saves_intent_without_saving_a_fake_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            profile = root / 'data' / 'apply_profile.json'
            profile.write_text('{}', encoding='utf-8')
            with patch.object(routes, 'ROOT', root), patch.object(routes.apply_sessions, 'get_session', return_value={'session_id': 'one'}):
                response = self.client.post('/application-engine/blank-answer', json={'question': 'Middle Name', 'session_id': 'one', 'confirmed': True, 'reuse': False})
            self.assertEqual(response.status_code, 200)
            saved = json.loads(profile.read_text(encoding='utf-8'))
            self.assertTrue(saved['applicationBlankAnswers']['one']['Middle Name'])
            self.assertNotIn('commonAnswers', saved)
            self.assertNotIn('blankAnswers', saved)

    def test_blank_choice_rejects_credentials_and_missing_session(self):
        with patch.object(routes.apply_sessions, 'get_session', return_value=None):
            self.assertEqual(self.client.post('/application-engine/blank-answer', json={'question': 'Middle Name', 'session_id': 'missing', 'confirmed': True}).status_code, 400)
        self.assertEqual(self.client.post('/application-engine/blank-answer', json={'question': 'Password', 'session_id': 'one', 'confirmed': True}).status_code, 400)
