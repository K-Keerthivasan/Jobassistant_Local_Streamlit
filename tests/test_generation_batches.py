import sqlite3
import tempfile
import unittest
from contextlib import contextmanager

from api.generation_batch_routes import BatchItem, GenerationQueue


class GenerationBatchTests(unittest.TestCase):
    def test_routes_register_with_the_app_runtime(self):
        from fastapi import FastAPI
        from api.generation_batch_routes import register
        app = FastAPI()
        register(app, lambda spec: {})
        self.assertIn('/generation-batches', app.openapi()['paths'])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = self.directory.name + '/batches.sqlite'

    def tearDown(self):
        self.directory.cleanup()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def test_ninety_resume_batch_recovers_midway_without_repeating_completed_items(self):
        calls = []
        def generate(spec):
            calls.append(spec['target']['title'])
            return {'folder': spec['target']['title']}
        queue = GenerationQueue(generate, self.connection)
        queue.initialize()
        items = [BatchItem(target={'title': 'Job ' + str(i)}) for i in range(90)]
        batch = queue.create(items)
        self.assertEqual(queue.create(items)['id'], batch['id'])
        for _ in range(45):
            self.assertTrue(queue.step())
        interrupted = queue.list()[0]
        interrupted['items'][45]['state'] = 'running'
        queue.save(interrupted)
        restarted = GenerationQueue(generate, self.connection)
        restarted.initialize()
        while restarted.step():
            pass
        complete = restarted.list()[0]
        self.assertTrue(complete['complete'])
        self.assertEqual(complete['counts']['done'], 90)
        self.assertEqual(len(calls), 90)
        self.assertEqual(len(set(calls)), 90)

    def test_failed_item_does_not_stop_the_remaining_jobs(self):
        def generate(spec):
            if spec['target']['title'] == 'bad':
                raise RuntimeError('Provider temporarily unavailable')
            return {'folder': 'good'}
        queue = GenerationQueue(generate, self.connection)
        queue.initialize()
        queue.create([BatchItem(target={'title': 'bad'}), BatchItem(target={'title': 'good'})])
        queue.step()
        queue.step()
        batch = queue.list()[0]
        self.assertEqual(batch['counts'], {'pending': 1, 'done': 1})
        for _ in range(2):
            batch['items'][0]['retry_at'] = 0
            queue.save(batch)
            queue.step()
            batch = queue.list()[0]
        self.assertEqual(batch['counts'], {'failed': 1, 'done': 1})
        self.assertTrue(batch['complete'])

    def test_provider_quota_waits_the_whole_batch_without_consuming_retries(self):
        def limited(spec):
            raise RuntimeError('Hermes usage limit reached; retry_after=3600')
        queue = GenerationQueue(limited, self.connection)
        queue.initialize()
        queue.create([BatchItem(target={'title': 'one'}), BatchItem(target={'title': 'two'})])
        queue.step()
        self.assertFalse(queue.step())
        batch = queue.list()[0]
        self.assertEqual(batch['counts'], {'pending': 2})
        self.assertEqual(batch['items'][0]['attempts'], 0)
        self.assertFalse(batch['complete'])


class RegenerateExistingTests(GenerationBatchTests):
    """A batch replaces runs made before it, but never redoes one it made itself."""

    def _queue(self, run_created_at, calls):
        from unittest import mock
        from types import SimpleNamespace
        import api.generation_batch_routes as gb
        job = SimpleNamespace(company='Acme', title='Analyst', notes='run1')
        prior = {'run_id': 'run1', 'created_at': run_created_at, 'target': {'company': 'Acme', 'title': 'Analyst'}}
        patches = [mock.patch.object(gb.store, 'get_job', return_value=job),
                   mock.patch.object(gb.runs, 'get_run', return_value=prior)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        queue = GenerationQueue(lambda spec: calls.append(spec['key_id']) or {'folder': 'run2'}, self.connection)
        queue.initialize()
        return queue

    def test_a_run_from_before_the_batch_is_regenerated(self):
        calls = []
        queue = self._queue('2020-01-01T00:00:00', calls)
        queue.create([BatchItem(key_id='k1')])
        queue.step()
        self.assertEqual(calls, ['k1'])
        self.assertNotIn('skipped_existing', queue.list()[0]['items'][0]['result'])

    def test_a_run_this_batch_already_made_is_not_repeated(self):
        from datetime import datetime, timedelta
        calls = []
        queue = self._queue((datetime.now() + timedelta(minutes=1)).isoformat(timespec='seconds'), calls)
        queue.create([BatchItem(key_id='k1')])
        queue.step()
        self.assertEqual(calls, [])
        self.assertTrue(queue.list()[0]['items'][0]['result']['skipped_existing'])


class EngineDownTests(GenerationBatchTests):
    def test_hermes_down_pauses_the_batch_instead_of_failing_jobs(self):
        from fastapi import HTTPException

        def generate(spec):
            raise HTTPException(status_code=503, detail='The Hermes bridge is not answering at http://x and Ollama is not running')
        queue = GenerationQueue(generate, self.connection)
        queue.initialize()
        queue.create([BatchItem(target={'title': 'A'}), BatchItem(target={'title': 'B'})])
        queue.step()
        batch = queue.list()[0]
        self.assertEqual(batch['counts'], {'pending': 2})
        self.assertEqual(batch['items'][0]['attempts'], 0, 'a wait does not use up retries')
        self.assertIn('not answering', batch['waiting_reason'])
        self.assertFalse(queue.step(), 'nothing runs until the wait is over')

    def test_progress_details_are_recorded(self):
        queue = GenerationQueue(lambda spec: {'folder': 'r'}, self.connection)
        queue.initialize()
        queue.create([BatchItem(target={'company': 'Acme', 'title': 'Analyst'})])
        queue.step()
        item = queue.list()[0]['items'][0]
        self.assertEqual(item['label'], 'Acme · Analyst')
        self.assertLessEqual(item['started_at'], item['finished_at'])


    def test_latest_follows_the_batch_being_worked_on(self):
        import time
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.generation_batch_routes import register
        app = FastAPI()
        register(app, lambda spec: {})
        queue = app.state.generation_queue
        queue.connection = self.connection
        queue.initialize()
        big = queue.create([BatchItem(target={'title': f'job {n}'}) for n in range(3)])
        big['items'][0]['state'] = 'running'
        queue.save(big)
        time.sleep(0.01)
        queue.create([BatchItem(target={'title': 'redo'})])   # newer, small, waiting
        client = TestClient(app)
        self.assertEqual(client.get('/generation-batches/latest').json()['id'], big['id'])
        big['items'][0]['state'] = 'done'
        queue.save(big)   # nothing running: the oldest unfinished batch is next in line
        self.assertEqual(client.get('/generation-batches/latest').json()['id'], big['id'])
