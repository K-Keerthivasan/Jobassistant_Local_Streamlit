import {test} from "node:test";
import assert from "node:assert/strict";
import {adviseNavigation} from "../src/advisor.js";
import {Snapshot} from "../src/schema.js";
const snapshot = Snapshot.parse({url:"https://example.com/job",title:"Apply",fields:[],blockers:[],buttons:[
  {selector:"#manual",label:"Apply manually",frameId:0},
  {selector:"#resume",label:"Autofill with resume",frameId:0},
  {selector:"#delete",label:"Delete account",frameId:0}
]});
test("Hermes selects only a permitted observed navigation control", async () => {
  let sent:any;
  const request = (async (_url:any, init:any) => {sent=JSON.parse(init.body);return Response.json({choices:[{message:{content:'{"index":0}'}}]});}) as typeof fetch;
  assert.equal((await adviseNavigation(snapshot,"http://localhost/v1",request))?.selector,"#manual");
  assert.equal(JSON.parse(sent.messages[1].content).controls.length,2);
  assert.ok(!JSON.stringify(sent).includes('Delete account'));
  const invalid = (async()=>Response.json({choices:[{message:{content:'{"index":999,"selector":"#delete"}'}}]})) as typeof fetch;
  assert.equal((await adviseNavigation(snapshot,"http://localhost/v1",invalid))?.selector,"#resume");
});
test("Hermes failure falls back without making a submission decision", async () => {
  const unavailable = (async()=>{throw new Error('offline');}) as typeof fetch;
  assert.equal((await adviseNavigation(snapshot,"http://localhost/v1",unavailable))?.selector,"#resume");
  const final = Snapshot.parse({...snapshot, fields:[{selector:'#name',label:'Name',required:true,type:'text',value:'Confirmed'}],buttons:[{selector:'#submit',label:'Submit',frameId:0}]});
  let calls=0;
  await adviseNavigation(final,"http://localhost/v1",(async()=>{calls++;}) as unknown as typeof fetch);
  assert.equal(calls,0);
});
