import pytest
from resume_gen.subskilling import Analysis, Gap, verified_analysis, source_text

def test_audit_requires_real_job_and_candidate_quotes():
    g=Gap(skill='Python',requirement_quote='Python required',category='resume_visibility',explanation='Present in profile',candidate_evidence='Built Python tools',next_step='Surface existing evidence next time')
    result=Analysis(description_sufficient=True,fit_explanation='Evidence is available',gaps=[g])
    assert verified_analysis(result,'Python required','Built Python tools')['gaps'][0]['category']=='resume_visibility'
    with pytest.raises(ValueError): verified_analysis(result,'Java required','Built Python tools')
    with pytest.raises(ValueError): verified_analysis(result,'Python required','No relevant evidence')

def test_unconfirmed_gap_never_becomes_candidate_fact():
    g=Gap(skill='Kubernetes',requirement_quote='Kubernetes required',category='not_evidenced',explanation='Ask candidate',next_step='Build a deployment project')
    data=verified_analysis(Analysis(description_sufficient=True,fit_explanation='Unconfirmed',gaps=[g]),'Kubernetes required','Python')
    assert data['gaps'][0]['candidate_evidence']==''

def test_source_rejects_non_https():
    with pytest.raises(ValueError): source_text('http://127.0.0.1/private')

def test_permanent_skill_requires_evidence_and_confirmation(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.subskilling_routes import register
    from resume_gen import subskilling,config
    monkeypatch.setattr(subskilling,'DB',tmp_path/'skills.sqlite')
    monkeypatch.setattr(config,'ROOT',tmp_path)
    (tmp_path/'data').mkdir()
    app=FastAPI();register(app);client=TestClient(app)
    assert client.post('/subskilling/skills',json={'name':'Python','status':'confirmed'}).status_code==400
    assert client.post('/subskilling/skills',json={'name':'Python','status':'learning'}).status_code==200
    import json
    path=tmp_path/'data'/'apply_profile.json'
    assert json.loads(path.read_text())['confirmedSkillEvidence']==[]
    assert client.post('/subskilling/skills',json={'name':'Python','status':'confirmed','evidence':'Built a parser','user_confirmed':True}).status_code==200
    assert json.loads(path.read_text())['confirmedSkillEvidence'][0]['evidence']=='Built a parser'
