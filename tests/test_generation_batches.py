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
