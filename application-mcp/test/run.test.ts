import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { Store } from "../src/store.js";
import { Service } from "../src/service.js";
import { Studio } from "../src/studio.js";
import { Snapshot, ApplyInput, type Application } from "../src/schema.js";
import { pickFinal, pickNav } from "../src/adapters.js";

const posting = (blockers: string[] = []) =>
  Snapshot.parse({
    url: "https://jobs.example.ca/job/1",
    title: "Developer",
    fields: [],
    buttons: [
      { selector: "#home", label: "Home", frameId: 0, href: "https://jobs.example.ca/" },
      {
        selector: "#apply",
        label: "Click here to apply online",
        frameId: 0,
        href: "https://apply.employer.com/form",
      },
    ],
    blockers,
  });
const form = (name = "") =>
  Snapshot.parse({
    url: "https://apply.employer.com/form",
    title: "Apply",
    fields: [
      { selector: "#fn", label: "First name", type: "text", required: true, value: name },
    ],
    buttons: [{ selector: "#submit", label: "Submit application", frameId: 0 }],
    blockers: [],
  });

class FakeStudio extends Studio {
  override async snapshot() {
    return {};
  }
}

function setup(sequence: Snapshot[]) {
  const root = mkdtempSync(path.join(tmpdir(), "run-"));
  mkdirSync(path.join(root, "data"));
  writeFileSync(path.join(root, "data/apply_profile.json"), JSON.stringify({ firstName: "Keerthivasan" }));
  const store = new Store(":memory:");
  const input = ApplyInput.parse({
    jobUrl: "https://jobs.example.ca/job/1",
    company: "Example",
    title: "Developer",
    resumePath: "resume.pdf",
    studioSessionId: "s1",
    allowedDomains: ["jobs.example.ca"],
  });
  const a: Application = {
    id: "run1",
    input,
    state: "working",
    ats: "generic",
    documents: [
      { kind: "resume", path: "resume.pdf", hash: "h", name: "resume.pdf", attached: true },
    ],
    filled: [],
    reason: "",
    createdAt: "now",
    updatedAt: "now",
  };
  store.save(a);
  // `sequence` is what the posting page shows on successive scans (the last
  // entry repeats); clicking its apply link moves to the form.
  let i = 0;
  let onForm = false;
  let name = "";
  const clicks: Record<string, unknown>[] = [];
  const browser = {
    command: async (op: string, args: Record<string, unknown>) => {
      if (op === "scan") {
        if (onForm) return form(name);
        const page = sequence[Math.min(i, sequence.length - 1)];
        i++;
        return structuredClone(page);
      }
      if (op === "click") {
        clicks.push(args);
        onForm = true;
        return { clicked: true };
      }
      if (op === "fill") {
        name = String(args.value);
        return { filled: true };
      }
      return {};
    },
  };
  const service = new Service(store, browser, new FakeStudio(), root, [], async (value, domains) => {
    const u = new URL(value);
    if (domains && !domains.includes(u.hostname)) throw new Error("New domain");
    return u;
  });
  service.waitMs = 5;
  return { store, service, clicks, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

async function until(fn: () => boolean, ms = 3000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (fn()) return;
    await new Promise((r) => setTimeout(r, 10));
  }
  throw new Error("timed out");
}

test("navigation picks the apply link on a posting and Next before Apply on a form", () => {
  assert.equal(pickNav(posting())?.selector, "#apply");
  assert.equal(pickFinal(posting()), undefined);
  assert.equal(pickFinal(form())?.selector, "#submit");
  const step = Snapshot.parse({
    ...form(),
    buttons: [
      { selector: "#apply2", label: "Apply", frameId: 0 },
      { selector: "#next", label: "Next", frameId: 0 },
    ],
  });
  assert.equal(pickNav(step)?.selector, "#next");
});

test("a run follows the posting's apply link, fills, and stops at the submit decision", async () => {
  // posting (scan by inspect, re-scan by navigate's guard), then the form.
  const { store, service, clicks, cleanup } = setup([posting()]);
  try {
    service.startRun("run1");
    await until(() => ["review", "paused"].includes(store.get("run1").state) && !service.running);
    const a = store.get("run1");
    assert.equal(a.state, "review", a.reason);
    assert.ok(a.input.allowedDomains.includes("apply.employer.com"));
    assert.deepEqual(clicks.map((c) => c.selector), ["#apply"]);
    assert.ok(clicks.every((c) => c.submit === false), "never clicks a submit control");
    assert.equal(a.filled[0]?.value, "Keerthivasan");
  } finally {
    cleanup();
  }
});

test("a run waits at a login and carries on by itself once it clears", async () => {
  const login = "Login or verification: complete it in Chrome.";
  const { store, service, cleanup } = setup([
    posting([login]),
    posting([login]),
    posting([login]),
    posting(),
    posting(),
  ]);
  try {
    service.startRun("run1");
    await until(() => store.get("run1").state === "review" || (!service.running && store.get("run1").state === "paused"));
    assert.equal(store.get("run1").state, "review", store.get("run1").reason);
  } finally {
    cleanup();
  }
});

test("a run can be stopped and refuses a finished application", async () => {
  const { store, service, cleanup } = setup([posting(["CAPTCHA: complete it in Chrome."])]);
  try {
    service.startRun("run1");
    await until(() => store.get("run1").state === "paused");
    service.stopRun();
    await until(() => !service.running);
    const a = store.get("run1");
    store.save({ ...a, state: "submitted" });
    assert.throws(() => service.startRun("run1"), /submitted/);
  } finally {
    cleanup();
  }
});
