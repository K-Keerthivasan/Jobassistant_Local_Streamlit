import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { Store } from "../src/store.js";
import { Service } from "../src/service.js";
import { Studio } from "../src/studio.js";
import { ApplyInput, type Application } from "../src/schema.js";

// Follows changes made in Resume Studio: applied, removed/dismissed, regenerated.
class FakeStudio extends Studio {
  status_: Record<string, unknown> = {};
  prepared = 0;
  constructor(public dir: string) { super(); }
  override async status() { return this.status_; }
  override async request(route: string): Promise<any> {
    if (route === "/application-engine/prepare") {
      this.prepared++;
      const resume = path.join(this.dir, "new_resume.pdf");
      writeFileSync(resume, "%PDF new");
      return { session_id: "s2", documents: { resume: { path: resume } } };
    }
    return {};
  }
}

function setup(state: Application["state"] = "paused", deferred = true) {
  const dir = mkdtempSync(path.join(tmpdir(), "sync-"));
  const store = new Store(":memory:");
  const old = path.join(dir, "old_resume.pdf");
  writeFileSync(old, "%PDF old");
  const a: Application = {
    id: "a1",
    input: ApplyInput.parse({ jobUrl: "https://jobs.example.com/1", company: "Acme", title: "Analyst",
      resumePath: old, studioSessionId: "s1", runId: "run1", allowedDomains: ["jobs.example.com"] }),
    state, ats: "generic",
    documents: [{ kind: "resume", path: old, hash: "h", name: "old_resume.pdf", attached: true }],
    filled: [], reason: "Required blank: Notice period", createdAt: "now", updatedAt: "now",
    ...(deferred ? { deferredAt: "now" } : {}),
  } as Application;
  store.save(a);
  const studio = new FakeStudio(dir);
  const calls: string[] = [];
  const browser = { command: async (op: string) => { calls.push(op); return {}; } };
  const service = new Service(store, browser, studio, dir, [dir]);
  return { store, studio, service, calls, cleanup: () => { store.db.close(); rmSync(dir, { recursive: true, force: true }); } };
}

test("a job marked applied in Studio closes the open application as applied", async () => {
  const { store, studio, service, cleanup } = setup();
  try {
    studio.status_ = { job_exists: true, applied: true };
    await service.observeStudio();
    const a = store.get("a1");
    assert.equal(a.state, "submitted");
    assert.equal(a.verificationSource, "studio_record");
    assert.equal(a.deferredAt, undefined);
  } finally { cleanup(); }
});

test("a job removed or marked not relevant in Studio closes as cancelled", async () => {
  for (const status of [{ job_exists: false }, { job_exists: true, dismissed: true }, { job_exists: true, session_status: "rejected" }]) {
    const { store, studio, service, calls, cleanup } = setup("paused", false);
    try {
      studio.status_ = status;
      await service.observeStudio();
      const a = store.get("a1");
      assert.equal(a.state, "rejected", JSON.stringify(status));
      assert.ok(a.cancelledAt);
      assert.ok(calls.includes("finish"), "releases the active tab");
    } finally { cleanup(); }
  }
});

test("a regenerated job swaps in the new documents, unattached", async () => {
  const { store, studio, service, cleanup } = setup("review", false);
  try {
    studio.status_ = { job_exists: true, regenerated: true, job_key: "k1", current_run_id: "run2" };
    await service.observeStudio();
    const a = store.get("a1");
    assert.equal(studio.prepared, 1);
    assert.equal(a.input.runId, "run2");
    assert.equal(a.input.studioSessionId, "s2");
    assert.match(a.documents[0].path, /new_resume\.pdf$/);
    assert.equal(a.documents[0].attached, false);
    assert.equal(a.state, "paused", "a review made with the old documents is withdrawn");
  } finally { cleanup(); }
});

test("checks Studio at most every 15 seconds and leaves finished applications alone", async () => {
  const { store, studio, service, cleanup } = setup();
  try {
    studio.status_ = { job_exists: true };
    await service.observeStudio();
    studio.status_ = { job_exists: true, applied: true };
    await service.observeStudio();                       // throttled
    assert.equal(store.get("a1").state, "paused");
    service.studioCheckedAt = 0;
    await service.observeStudio();
    assert.equal(store.get("a1").state, "submitted");
    studio.status_ = { job_exists: false };
    service.studioCheckedAt = 0;
    await service.observeStudio();
    assert.equal(store.get("a1").state, "submitted", "a recorded outcome is never replaced");
  } finally { cleanup(); }
});
