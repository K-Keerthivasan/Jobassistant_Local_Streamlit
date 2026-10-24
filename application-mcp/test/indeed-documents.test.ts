import { test } from "node:test";
import assert from "node:assert/strict";
import { Store } from "../src/store.js";
import { Service } from "../src/service.js";
import { Studio } from "../src/studio.js";
import { ApplyInput, Snapshot, type Application } from "../src/schema.js";

// Indeed Easy Apply can jump to its review page with an older resume on file.
// The app must swap in this job's resume and add its cover letter, never leave it.
const review = (resumeShown: string, coverShown = "") => Snapshot.parse({
  url: "https://smartapply.indeed.com/beta/indeedapply/form/review-module",
  title: "Review the contents of this job application | Indeed",
  fields: [], buttons: [{ selector: "#submit", label: "Submit your application", frameId: 0 }], blockers: [],
  attachments: [
    { kind: "resume", name: resumeShown, frameId: 0, shownByIndeed: true },
    ...(coverShown ? [{ kind: "cover_letter", name: coverShown, frameId: 0, shownByIndeed: true }] : []),
  ],
});

function setup(snapshot: Snapshot, attached = { resume: false, cover: false }) {
  const store = new Store(":memory:");
  const a = {
    id: "i1",
    input: ApplyInput.parse({ jobUrl: "https://ca.indeed.com/viewjob?jk=1", company: "RefugeRoot Canada", title: "Video Content Creator",
      resumePath: "r.pdf", studioSessionId: "s1", allowedDomains: ["ca.indeed.com", "smartapply.indeed.com"] }),
    state: "working", ats: "indeed", snapshot,
    documents: [
      { kind: "resume", path: "r.pdf", hash: "h", name: "kk_RefugeRoot_Canada_Video_Content_Creator.pdf", attached: attached.resume },
      { kind: "cover_letter", path: "c.pdf", hash: "h", name: "kk_RefugeRoot_Canada_Video_Content_Creator_CL.pdf", attached: attached.cover },
    ],
    filled: [], reason: "", createdAt: "now", updatedAt: "now",
  } as unknown as Application;
  store.save(a);
  const calls: Record<string, unknown>[] = [];
  const browser = { command: async (op: string, args: Record<string, unknown>) => { calls.push({ op, ...args }); return {}; } };
  const service = new Service(store, browser, new Studio(), ".", []);
  const step = () => (service as any).indeedDocuments("i1") as Promise<boolean>;
  return { store, calls, step, close: () => store.db.close() };
}

test("an older resume on Indeed's review page is replaced: Edit next to Resume, once", async () => {
  const { store, calls, step, close } = setup(review("kk_DWS_StructuredCablingTechnician.pdf"));
  try {
    assert.equal(await step(), true);
    assert.deepEqual(calls.map((c) => [c.op, c.part, c.action]), [["indeedPart", "Resume", "Edit"]]);
    assert.ok(store.get("i1").indeedResumeEditAt);
    assert.equal(await step(), false, "never clicks Edit twice; the run then stops with an explicit message");
  } finally { close(); }
});

test("with this job's resume in place, the cover letter is added under Supporting documents", async () => {
  const { calls, step, close } = setup(review("kk_RefugeRoot_Canada_Video_Content_Creator.pdf"), { resume: true, cover: false });
  try {
    assert.equal(await step(), true);
    assert.deepEqual(calls.map((c) => [c.part, c.action]), [["Supporting documents", "Add"]]);
  } finally { close(); }
});

test("nothing is clicked when both documents are already this job's, or off Indeed", async () => {
  const done = setup(review("kk_RefugeRoot_Canada_Video_Content_Creator.pdf", "kk_RefugeRoot_Canada_Video_Content_Creator_CL.pdf"), { resume: true, cover: true });
  try { assert.equal(await done.step(), false); assert.equal(done.calls.length, 0); } finally { done.close(); }
  const other = setup(Snapshot.parse({ ...review("old.pdf"), url: "https://careers.example.com/review" }));
  try { assert.equal(await other.step(), false); assert.equal(other.calls.length, 0); } finally { other.close(); }
});

test('Indeed edits a stale text letter even when the correct PDFs are attached',async()=>{
  const snapshot=review('kk_RefugeRoot_Canada_Video_Content_Creator.pdf','kk_RefugeRoot_Canada_Video_Content_Creator_CL.pdf');
  snapshot.indeedTextCoverLetter=true;
  const {calls,step,close}=setup(snapshot,{resume:true,cover:true});
  try{assert.equal(await step(),true);assert.deepEqual(calls.map(c=>[c.part,c.action]),[['Supporting documents','Edit']]);assert.equal(await step(),false);}finally{close();}
});

test("the service expects the extension version in manifest.json", async () => {
  const { readFile } = await import("node:fs/promises");
  const { EXPECTED_EXTENSION_VERSION } = await import("../src/bridge.js");
  const manifest = JSON.parse(await readFile(new URL("../extension/manifest.json", import.meta.url), "utf8"));
  assert.equal(EXPECTED_EXTENSION_VERSION, manifest.version);
});
