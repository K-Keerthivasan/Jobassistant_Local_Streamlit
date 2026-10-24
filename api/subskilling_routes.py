"""Skill subskilling API and UI, independent of resume rewrites."""
from typing import Literal
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import threading
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from resume_gen import subskilling as s
_profile_lock = threading.Lock()

class SkillIn(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    status: Literal['learning','confirmed','not_yet']
    evidence: str = Field(default='',max_length=3000)
    user_confirmed: bool = False

class Control(BaseModel):
    action: Literal['start','pause','retry']

def register(app):
    @app.get('/subskilling.js')
    def script(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'subskilling.js',media_type='application/javascript')

    @app.get('/subskilling')
    def status(): return s.status()

    @app.post('/subskilling/control')
    def control(req:Control):
        if req.action=='pause':
            with s.connect() as c: c.execute('INSERT OR REPLACE INTO config VALUES (1,0)')
            return {'paused':True}
        if req.action=='retry':
            with s.connect() as c: c.execute("UPDATE audit SET status='queued' WHERE status='needs_review'")
        return s.start()

    @app.post('/subskilling/skills')
    def save(req:SkillIn):
        if not req.name.strip(): raise HTTPException(400,'Enter a skill name')
        if req.status=='confirmed' and (not req.user_confirmed or not req.evidence.strip()):
            raise HTTPException(400,'Confirm the skill and describe where you used it')
        with s.connect() as c:
            c.execute('INSERT OR REPLACE INTO skills VALUES (?,?,?,?)',(req.name.strip().casefold(),req.status,req.evidence.strip(),datetime.now(timezone.utc).isoformat()))
        with _profile_lock:
            from resume_gen.config import ROOT
            path=ROOT/'data'/'apply_profile.json'
            profile=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            entries=[e for e in profile.get('confirmedSkillEvidence',[]) if e['skill'].casefold()!=req.name.strip().casefold()]
            if req.status=='confirmed': entries.append({'skill':req.name.strip(),'evidence':req.evidence.strip(),'source':'user_confirmed','at':datetime.now(timezone.utc).isoformat()})
            profile['confirmedSkillEvidence']=entries
            temporary=path.with_suffix('.subskilling.tmp')
            temporary.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(temporary,path)
        return {'saved':True}

    @app.on_event('startup')
    def recover():
        with s.connect() as c: c.execute("UPDATE audit SET status='queued' WHERE status='running'")
        s.launch()
