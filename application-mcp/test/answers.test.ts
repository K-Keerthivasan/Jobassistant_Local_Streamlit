import {test} from 'node:test';
import assert from 'node:assert/strict';
import {draftAnswer,narrativeQuestion} from '../src/answers.js';
import {Field} from '../src/schema.js';
import {pickFinal,pickNav,detectAts} from '../src/adapters.js';
import {Snapshot} from '../src/schema.js';
const field=(label='Describe your relevant experience')=>Field.parse({selector:'#answer',label,type:'textarea',required:true});
const context={company:'Example',title:'Data Engineer',description:'Build SQL reports.',resume:{experience:[{company:'Previous',bullets:['Built SQL reports for operations teams.']}]}};
const response=(value:unknown)=>Response.json({choices:[{message:{content:JSON.stringify(value)}}]});

test('Cisco listing ignores alert Submit and selects the current job over related jobs',()=>{
 const s=Snapshot.parse({url:'https://careers.cisco.com/global/en/job/2024453/Software-Developer-hybrid',title:'Cisco',fields:[field('Email for job alerts')],blockers:[],buttons:[{selector:'#alerts',label:'Submit',frameId:0},{selector:'#related',label:'Apply Now',href:'https://careers.cisco.com/global/en/hvhapply?jobSeqNo=CISCISGLOBAL2025041EXTERNALENGLOBAL',frameId:0},{selector:'#apply',label:'Apply Now',href:'https://careers.cisco.com/global/en/hvhapply?jobSeqNo=CISCISGLOBAL2024453EXTERNALENGLOBAL',frameId:0}]});
 assert.equal(pickFinal(s),undefined);assert.equal(pickNav(s)?.selector,'#apply');
});

test('motivation and additional-information questions use resume evidence and job fit',async()=>{
 for(const label of ['Why are you interested in this position? *','Do you want to tell us anything else about yourself?']){
  const payloads:any[]=[];
  const result=await draftAnswer(field(label),context,'http://local/v1',(async(_url:any,init:any)=>{
   payloads.push(JSON.parse(init.body));return payloads.length===1?response({needsUser:false,sentences:[{text:'My experience building SQL reports aligns with the reporting responsibilities of this role.',evidence:[1]}]}):response({supported:true});
  }) as typeof fetch);
  assert.ok(result?.answer);assert.match(payloads[0].messages[0].content,/professional-fit explanation is permitted/);assert.match(payloads[1].messages[0].content,/professional-fit explanation/);
 }
});
test('AI narrative drafting uses job-specific evidence and requires a separate support check',async()=>{
  const payloads:any[]=[];
  const request=(async(_url:any,init:any)=>{payloads.push(JSON.parse(init.body));return payloads.length===1?response({needsUser:false,sentences:[{text:'I built SQL reports for operations teams.',evidence:[1]}]}):response({supported:true});}) as typeof fetch;
  const result=await draftAnswer(field(),context,'http://local/v1',request);
  assert.equal(result?.answer,'I built SQL reports for operations teams.');assert.deepEqual(result?.evidence,['Built SQL reports for operations teams.']);
  assert.equal(payloads.length,2);assert.ok(JSON.stringify(payloads[0]).includes('Build SQL reports.'));
});
test('unknown eligibility, salary, quantities and legal choices are never AI-inferred',async()=>{
  for(const question of ['How many years of experience do you have?','Describe your salary expectations','Explain your work authorization','Describe your disability','Tell us your available start date'])assert.equal(narrativeQuestion(field(question)),false);
  let calls=0;await draftAnswer(field('Describe your salary expectations'),context,'http://local/v1',(async()=>{calls++;return response({});}) as typeof fetch);assert.equal(calls,0);
});
test('AI uncertainty, invented numbers, invalid evidence and failed validation defer to the user',async()=>{
  for(const value of [{needsUser:true,sentences:[]},{needsUser:false,sentences:[{text:'I have 10 years of experience.',evidence:[1]}]},{needsUser:false,sentences:[{text:'I built reports.',evidence:[99]}]}])
    assert.equal(await draftAnswer(field(),context,'http://local/v1',(async()=>response(value)) as typeof fetch),undefined);
  let calls=0;
  assert.equal(await draftAnswer(field(),context,'http://local/v1',(async()=>++calls===1?response({needsUser:false,sentences:[{text:'I used Kubernetes.',evidence:[1]}]}):response({supported:false})) as typeof fetch),undefined);
});
test('Indeed review navigation leads to a user-only final submit page with no editable fields',()=>{
  const snapshot=Snapshot.parse({url:'https://smartapply.indeed.com/review',title:'Review',fields:[],blockers:[],buttons:[{selector:'#review',label:'Review your application',frameId:0}]});
  assert.equal(detectAts(snapshot.url),'indeed');assert.equal(pickNav(snapshot)?.selector,'#review');
  snapshot.buttons=[{selector:'#submit',label:'Submit your application',frameId:0}];assert.equal(pickFinal(snapshot)?.selector,'#submit');assert.equal(pickNav(snapshot),undefined);
});
