import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { Store } from "../src/store.js";
import { Service } from "../src/service.js";
import { Studio } from "../src/studio.js";

// The Indeed queue opens Indeed postings; LinkedIn postings stay refused.
function setup(jobUrl: string) {
  const dir = mkdtempSync(path.join(tmpdir(), "indeed-"));
  const resume = path.join(dir, "resume.pdf");
  writeFileSync(resume, "%PDF test");
  const studio = new Studio();
  studio.validate = async () => ({ status: "prepared", job_url: jobUrl, company: "Acme", title: "Analyst",
    run_id: "r1", documents: { resume: { path: resume } } });
  const opened: string[] = [];
  const browser = { command: async (op: string, args: Record<string, unknown>) => {
    if (op === "open") opened.push(String(args.url));
    if (op === "scan") return { url: jobUrl, title: "Job", fields: [], buttons: [], blockers: [] };
    return {};
  } };
  const store = new Store(":memory:");
  const service = new Service(store, browser, studio, dir, [dir], async (value: string) => new URL(value));
  const input = { jobUrl, company: "Acme", title: "Analyst", resumePath: resume, studioSessionId: "s1", mode: "review" };
  return { service, store, opened, input, cleanup: () => { store.db.close(); rmSync(dir, { recursive: true, force: true }); } };
}

test("an Indeed posting opens, with Indeed's apply site approved", async () => {
  const url = "https://ca.indeed.com/viewjob?jk=d9b8550ac10e5318";
  const { service, opened, input, cleanup } = setup(url);
  try {
    const a = await service.apply(input);
    assert.deepEqual(opened, [url]);
    assert.ok(a.input.allowedDomains.includes("ca.indeed.com"));
    assert.ok(a.input.allowedDomains.includes("smartapply.indeed.com"));
  } finally { cleanup(); }
});

test("a LinkedIn posting is still refused before anything opens", async () => {
  const url = "https://ca.linkedin.com/jobs/view/123";
  const { service, opened, input, cleanup } = setup(url);
  try {
    await assert.rejects(service.apply(input), /direct employer application URL/);
    assert.deepEqual(opened, []);
  } finally { cleanup(); }
});
