import json
from pathlib import Path
from datetime import datetime, timezone
from resume_gen.profile import load_profile
from resume_gen.models import Resume
from resume_gen.render.docx_renderer import render_resume
from resume_gen.render.pdf_export import to_pdf
from resume_gen.intake.runs import save_run
from resume_gen.intake.store import list_queue
from pypdf import PdfReader
p=load_profile()
def experience(company, bullets):
 e=next(x for x in p['experience'] if x['company']==company)
 return {k:e.get(k,'') for k in ['company','role','location','start','end']} | {'bullets':bullets}
r=Resume(fullName=p['full_name'],headline='Network Administrator',contact={**p['contact'],'location':'Ontario, Canada','links':[x for x in p['contact']['links'] if x['label'].lower()=='linkedin']},summaryPoints=[
'Application and IT support professional experienced in resolving operating-system, hardware, account and network issues, with a 95% first-contact resolution rate at Certify Technologies.',
'Hands-on experience with Windows workstation deployment and hardening, Active Directory, Microsoft 365 and Entra ID account administration.',
'Networking fundamentals in TCP/IP, DNS, DHCP and VPN, with router setup and basic firewall rules; brings production troubleshooting, log analysis and clear client communication.'
],skills=['Networking fundamentals (TCP/IP, DNS, DHCP, VPN)','Router setup and basic firewall rules','Windows imaging and hardening','Active Directory','Microsoft 365','Entra ID','Linux','Ticketing and ticket lifecycle','Remote support tools','Hardware support','Process documentation','PowerShell (familiar)'],experience=[
experience('Certify Technologies',[
'Resolved operating-system, hardware, account and network issues through phone and ticket-based support, maintaining a 95% first-contact resolution rate.',
'Built and imaged Windows 11 workstations for new hires, including driver installation, application provisioning, hardening and burn-in checks.',
'Administered user accounts in Active Directory, Microsoft 365 and Entra ID, managing support tickets from initial investigation through closure.',
'Participated in production support rotations and post-incident reviews, using log analysis to diagnose and resolve integration issues.',
'Troubleshot SQL Server, MongoDB and Firebase integrations, investigating schema, query and application-connectivity issues.',
'Worked with QA, product and operations teams on requirements, validation and release sign-off.'
]),experience('K2 Digital Media',[
'Maintain production client websites and applications, providing post-launch troubleshooting, performance improvements and ongoing maintenance.',
'Design and manage PostgreSQL, Supabase and Firebase databases, including data structure, queries and data integrity.',
'Use Docker locally and deploy production applications to Google Cloud Run.',
'Translate technical issues for non-technical clients, define requirements and delivery schedules, and communicate project status and risks.'
]),experience('Bill Gosling Outsourcing',[
'Handle high-volume phone and email contact while meeting daily targets and maintaining calm communication under pressure.',
'Document customer interactions accurately in CRM systems, maintaining audit-ready records across multiple software workflows.'
])],education=p['education'],licences=p.get('licences',[]))
out=Path('/app/output/pdf');out.mkdir(parents=True,exist_ok=True)
base=out/'Keerthivasan_Network_Administrator_Revised'
render_resume(r,base.with_suffix('.docx'),profile=p)
pdf=to_pdf(base.with_suffix('.docx'))
print('Pages:',len(PdfReader(pdf).pages))
base.with_suffix('.json').write_text(r.model_dump_json(indent=2))
job=next(j for j in list_queue() if j.company=='City of Owen Sound' and j.title=='Network Administrator')
run_id='City_of_Owen_Sound_Network_Administrator_Revised_20261021'
save_run({'run_id':run_id,'created_at':datetime.now(timezone.utc).isoformat(),'persona_label':'IT Support — Network role focus','target':job.to_target_role().model_dump(),'resume':r.model_dump(),'qa':{'notes':['Evidence-grounded manual rewrite; no claim of three years dedicated network administration.']},'qa_has_violations':False,'revision_note':'New resume requested by user; previous generated run preserved.'})
print('Saved:',run_id)
