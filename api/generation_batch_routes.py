"""Persistent sequential generation; browser disconnects do not cancel a batch."""
import json
import re
import threading
import time
import uuid
from collections import Counter
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel, Field
from resume_gen.intake import db, store, runs


class BatchItem(BaseModel):
    key_id: str | None = None
    target: dict | None = None
    options: dict = Field(default_factory=dict)


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=1000)


class GenerationQueue:
    def __init__(self, generate, connection=db.connect):
        self.generate = generate
        self.connection = connection
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.thread = None

    def initialize(self):
        with self.connection() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS generation_batches (id TEXT PRIMARY KEY, created REAL, data TEXT)')
        # A container restart never silently loses an in-flight row.
        for batch in self.list():
            for item in batch['items']:
                if item['state'] == 'running':
                    item['state'] = 'pending'
            self.save(batch)

    def save(self, batch):
        batch['counts'] = dict(Counter(item['state'] for item in batch['items']))
        batch['total'] = len(batch['items'])
        batch['complete'] = all(item['state'] in ('done', 'failed') for item in batch['items'])
        with self.connection() as conn:
            conn.execute('INSERT INTO generation_batches VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                         (batch['id'], batch['created'], json.dumps(batch)))
        return batch

    def list(self):
        with self.connection() as conn:
            return [json.loads(row['data']) for row in conn.execute('SELECT data FROM generation_batches ORDER BY created DESC')]

    def create(self, items):
        with self.lock:
            specs = [item.model_dump() for item in items]
            for old in self.list():
                if not old['complete'] and [i['spec'] for i in old['items']] == specs:
                    return old
            batch = self.save({'id': uuid.uuid4().hex, 'created': time.time(), 'items': [
                {'spec': spec, 'state': 'pending', 'attempts': 0, 'error': '', 'retry_at': 0} for spec in specs]})
            self.wake.set()
            return batch

    def step(self):
        with self.lock:
            candidate = next(((batch, index) for batch in reversed(self.list()) for index, item in enumerate(batch['items'])
                              if item['state'] == 'pending' and item['retry_at'] <= time.time()), None)
            if not candidate:
                return False
            batch, index = candidate
            item = batch['items'][index]
            item['state'] = 'running'
            item['started_at'] = time.time()
            self.save(batch)
        try:
            spec = item['spec']
            job = store.get_job(spec['key_id']) if spec.get('key_id') else None
            # What the progress banner shows while this item runs.
            target_spec = spec.get('target') or {}
            item['label'] = ' · '.join(x for x in ((job.company, job.title) if job else
                                                  (target_spec.get('company', ''), target_spec.get('title', ''))) if x)
            prior = runs.get_run(job.notes.strip()) if job and job.notes else None
            target = (prior or {}).get('target') or {}
            # Skip only a run this batch already produced (a restart mid-batch must
            # not generate twice). A run from before the batch is exactly what a
            # regenerate batch is meant to replace.
            produced_by_batch = False
            if prior and prior.get('created_at'):
                try:
                    produced_by_batch = datetime.fromisoformat(prior['created_at']).timestamp() >= batch['created']
                except ValueError:
                    produced_by_batch = False
            if prior and produced_by_batch and job.company == target.get('company') and job.title == target.get('title'):
                result = {'folder': prior['run_id'], 'skipped_existing': True}
            else:
                result = self.generate(spec)
            item.update(state='done', result=result, error='', finished_at=time.time())
            batch.pop('waiting_reason', None)
        except Exception as error:
            item['attempts'] += 1
            item['error'] = str(getattr(error, 'detail', error))[:1500]
            status = getattr(error, 'status_code', 500)
            quota = re.search(r'retry_after=(\d+)', item['error'])
            # Hermes not answering (the bridge is down or restarting) is a wait, not
            # a failure: the batch pauses and carries on once Hermes is back, instead
            # of failing every remaining job after three quick retries.
            engine_down = status == 503 or 'Hermes bridge is not answering' in item['error']
            if status == 429 or quota or engine_down:
                item['attempts'] -= 1
                item['state'] = 'pending'
                delay = int(quota.group(1)) if quota else (120 if engine_down else 900)
                batch['waiting_reason'] = ('Hermes is not answering; checking again every 2 minutes'
                                           if engine_down else 'Hermes usage limit reached')
                batch['waiting_until'] = time.time() + max(60, delay)
                for pending in batch['items']:
                    if pending['state'] == 'pending':
                        pending['retry_at'] = batch['waiting_until']
            else:
                retry = status >= 500 and item['attempts'] < 3
                item['state'] = 'pending' if retry else 'failed'
                item['retry_at'] = time.time() + 30 * item['attempts'] if retry else 0
        with self.lock:
            self.save(batch)
        return True

    def start(self):
        self.initialize()
        def work():
            while not self.stop.is_set():
                try:
                    if self.step():
                        continue
                except Exception:
                    pass  # persisted pending work remains recoverable
                self.wake.wait(5)
                self.wake.clear()
        self.thread = threading.Thread(target=work, daemon=True, name='generation-queue')
        self.thread.start()


def register(app, generate):
    queue = GenerationQueue(generate)
    app.state.generation_queue = queue
    app.on_event('startup')(queue.start)
    app.on_event('shutdown')(queue.stop.set)

    @app.post('/generation-batches', status_code=202)
    def create_batch(request: BatchRequest):
        return queue.create(request.items)

    @app.get('/generation-batches/latest')
    def latest_batch():
        return next(iter(queue.list()), None)

    @app.get('/generation-batches/{batch_id}')
    def get_batch(batch_id: str):
        batch = next((batch for batch in queue.list() if batch['id'] == batch_id), None)
        if not batch:
            raise HTTPException(404, 'Batch not found')
        return batch

    @app.post('/generation-batches/{batch_id}/retry')
    def retry_batch(batch_id: str):
        with queue.lock:
            batch = get_batch(batch_id)
            for item in batch['items']:
                if item['state'] == 'failed':
                    item.update(state='pending', attempts=0, retry_at=0)
            queue.save(batch)
            queue.wake.set()
            return batch
