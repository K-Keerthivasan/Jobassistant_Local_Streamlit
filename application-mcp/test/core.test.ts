import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import { request } from "node:http";
import path from "node:path";
import { Store } from "../src/store.js";
import { Service } from "../src/service.js";
import { Studio } from "../src/studio.js";
import { Snapshot, ApplyInput, type Application } from "../src/schema.js";
import { plan, detectAts } from "../src/adapters.js";
import { publicAddress, documentInfo, digest } from "../src/security.js";
import { httpServer } from "../src/http.js";
import { ChromeBridge } from "../src/bridge.js";
import { toolset } from "../src/tools.js";

const input = ApplyInput.parse({
  jobUrl: "https://careers.example.com/job/1",
  company: "Example",
  title: "Engineer",
  resumePath: "resume.pdf",
  studioSessionId: "s1",
  allowedDomains: ["careers.example.com"],
});
const snapshot = () =>
  Snapshot.parse({
    url: input.jobUrl,
    title: "Apply",
    fields: [
      {
        selector: "#name",
        label: "First name",
        type: "text",
        required: true,
        value: "Jordan",
      },
    ],
    buttons: [{ selector: "#submit", label: "Submit application", frameId: 0 }],
    blockers: [],
  });
function app(): Application {
  return {
    id: "app1",
    input: structuredClone(input),
    state: "working",
    ats: "generic",
    documents: [
      {
        kind: "resume",
        path: "resume.pdf",
        hash: "hash",
        name: "resume.pdf",
        attached: true,
      },
    ],
    filled: [],
    reason: "",
    createdAt: "now",
    updatedAt: "now",
  };
}
class FakeStudio extends Studio {
  confirmations = 0;
  results = 0;
  snapshots = 0;
  failSync = false;
  override async snapshot() {
    this.snapshots++;
    return {};
  }
  override async confirm() {
    this.confirmations++;
    return { may_submit: true };
  }
  override async result() {
    if (this.failSync) throw new Error("Studio unavailable");
    this.results++;
    return {};
  }
}
function setup(state = app()) {
  const store = new Store(":memory:");
  store.save(state);
  let observed = snapshot();
  const calls: string[] = [];
  const browser = {
    command: async (op: string, args: Record<string, unknown>) => {
      calls.push(op);
      if (op === "scan") return structuredClone(observed);
      if (op === "fill") {
        observed.fields[0].value = String(args.value);
      }
      return {};
    },
  };
  const studio = new FakeStudio();
  const service = new Service(
    store,
    browser,
    studio,
    ".",
    [],
    async (value, domains) => {
      const u = new URL(value);
      if (domains && !domains.includes(u.hostname))
        throw new Error("New domain");
      return u;
    },
  );
  return {
    store,
    studio,
    service,
    calls,
    setSnapshot: (s: Snapshot) => {
      observed = s;
    },
  };
}
test("verified exact answers only; sensitive and semantically different eligibility questions remain manual", () => {
  const fields = Snapshot.parse({
    ...snapshot(),
    fields: [
      { selector: "#a", label: "First name", type: "text", required: true },
      {
        selector: "#b",
        label: "Will you now or in the future need sponsorship?",
        type: "text",
        required: true,
      },
      {
        selector: "#c",
        label: "I agree to receive marketing",
        type: "checkbox",
        required: false,
      },
      {
        selector: "#d",
        label: "Gender",
        type: "select",
        required: false,
        options: ["Male", "Female"],
      },
    ],
  }).fields;
  const p = plan(fields, {
    firstName: "Jordan",
    commonAnswers: {
      "Do you currently need sponsorship?": "No",
      Gender: "Male",
    },
  });
  assert.equal(p[0].value, "Jordan");
  for (const entry of p.slice(1)) assert.equal(entry.value, undefined);
});
test("ATS hostname detection resists lookalike suffixes", () => {
  assert.equal(detectAts("https://boards.greenhouse.io/acme"), "greenhouse");
  assert.equal(
    detectAts("https://greenhouse.io.attacker.example/acme"),
    "generic",
  );
});
test("site mappings require exact live structure; repeated labels never receive guessed values", () => {
  const field = Snapshot.parse({
    ...snapshot(),
    fields: [
      {
        selector: "#employer",
        label: "Employer",
        type: "text",
        required: true,
      },
    ],
  }).fields[0];
  const mappings = [
    {
      label: "Employer",
      type: "text",
      options: [],
      profilePath: "employmentHistory.0.company",
    },
  ];
  const profile = { employmentHistory: [{ company: "Confirmed employer" }] };
  assert.equal(plan([field], profile, mappings)[0].value, "Confirmed employer");
  assert.equal(
    plan(
      [{ ...field, type: "select", options: ["Other"] }],
      profile,
      mappings,
    )[0].value,
    undefined,
  );
  assert.equal(
    plan([field, { ...field, selector: "#second" }], profile, mappings)[0]
      .value,
    undefined,
  );
});
test("private IPv4, mapped IPv6 and localhost are refused", () => {
  for (const ip of [
    "127.0.0.1",
    "10.1.1.1",
    "169.254.169.254",
    "172.16.0.1",
    "192.168.1.1",
    "100.64.0.1",
    "::1",
    "::ffff:127.0.0.1",
    "fe80::1",
    "fc00::1",
  ])
    assert.equal(publicAddress(ip), false, ip);
  assert.equal(publicAddress("8.8.8.8"), true);
  assert.equal(publicAddress("2606:4700:4700::1111"), true);
});
test("document allowlist enforces canonical paths and hashes", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "apply-test-"));
  try {
    await mkdir(path.join(root, "approved"));
    await writeFile(path.join(root, "approved", "r.pdf"), "resume");
    await writeFile(path.join(root, "other.pdf"), "other");
    const d = await documentInfo(path.join(root, "approved", "r.pdf"), [
      path.join(root, "approved"),
    ]);
    assert.equal(d.name, "r.pdf");
    assert.equal(d.hash.length, 64);
    await assert.rejects(
      () =>
        documentInfo(path.join(root, "other.pdf"), [
          path.join(root, "approved"),
        ]),
      /outside/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
test("duplicate application URL is prevented durably", () => {
  const { store } = setup();
  assert.throws(() => store.save({ ...app(), id: "duplicate" }), /UNIQUE/);
  store.db.close();
});
test("review requires required fields, valid values and verified attachments", async () => {
  const { service, setSnapshot, store } = setup();
  const s = snapshot();
  s.fields[0].value = "";
  setSnapshot(s);
  const r = await service.review("app1");
  assert.equal(r.state, "paused");
  assert.match(r.reason, /Required blank/);
  assert.equal(r.reviewHash, undefined);
  store.db.close();
});
test("review syncs exact observed form to Studio and binds hash", async () => {
  const { service, store, studio } = setup();
  const r = await service.review("app1");
  assert.equal(r.state, "review");
  assert.equal(studio.snapshots, 1);
  assert.equal(
    r.reviewHash,
    digest({ snapshot: r.snapshot, documents: r.documents }),
  );
  store.db.close();
});
test("changed form cannot reuse review approval", async () => {
  const { service, store, studio, setSnapshot, calls } = setup();
  const r = await service.review("app1");
  const s = snapshot();
  s.fields[0].value = "Changed";
  setSnapshot(s);
  await assert.rejects(
    () => service.submit("app1", r.reviewHash!, true, "#submit"),
    /changed/,
  );
  assert.equal(studio.confirmations, 0);
  assert.equal(calls.filter((c) => c === "click").length, 0);
  store.db.close();
});
test("unapproved and uncertain submissions never click", async () => {
  const { service, store, calls } = setup();
  await assert.rejects(
    () => service.submit("app1", "invalid", true, "#submit"),
    /fresh yes/,
  );
  store.save({ ...store.get("app1"), state: "uncertain" });
  await assert.rejects(() =>
    service.submit("app1", "invalid", true, "#submit"),
  );
  assert.equal(calls.includes("click"), false);
  store.db.close();
});
test("uncertain verification stays uncertain without confirmation", async () => {
  const { service, store, studio } = setup({ ...app(), state: "uncertain" });
  assert.equal((await service.verify("app1")).state, "uncertain");
  assert.equal(studio.results, 0);
  store.db.close();
});
test("visible success is saved before sync, and sync retries never resubmit", async () => {
  const { service, store, studio, setSnapshot, calls } = setup({
    ...app(),
    state: "uncertain",
  });
  const s = snapshot();
  s.confirmation = "Your application has been received.";
  setSnapshot(s);
  studio.failSync = true;
  const result = await service.verify("app1");
  assert.equal(result.state, "submitted");
  assert.equal(result.synced, false);
  studio.failSync = false;
  assert.equal((await service.sync("app1")).synced, true);
  assert.equal(calls.includes("click"), false);
  store.db.close();
});
test("restart during submission becomes uncertain and cannot replay", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "apply-state-"));
  const file = path.join(root, "test.sqlite");
  try {
    let store = new Store(file);
    store.save({ ...app(), state: "submitting" });
    store.db.close();
    store = new Store(file);
    assert.equal(store.get("app1").state, "uncertain");
    store.db.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
test("HTTP rejects cross-origin requests, wrong hosts and non-JSON mutations", async () => {
  const { service, store } = setup();
  const server = httpServer(service, new ChromeBridge(), "");
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const addr = server.address() as { port: number };
  const url = `http://127.0.0.1:${addr.port}`;
  try {
    const post = (headers: Record<string, string>) =>
      new Promise<number>((resolve, reject) => {
        const req = request(
          url + "/applications",
          { method: "POST", headers },
          (res) => {
            res.resume();
            res.on("end", () => resolve(res.statusCode!));
          },
        );
        req.on("error", reject);
        req.end("{}");
      });
    // Configured Host remains 8091; a rebound Host is refused even on loopback.
    assert.equal((await fetch(url + "/health")).status, 403);
    assert.equal(
      await post({
        Host: "127.0.0.1:8091",
        Origin: "https://attacker.example",
        "Content-Type": "application/json",
      }),
      403,
    );
    assert.equal(
      await post({ Host: "127.0.0.1:8091", "Content-Type": "text/plain" }),
      400,
    );
  } finally {
    await new Promise<void>((r) => server.close(() => r()));
    store.db.close();
  }
});
test("all requested MCP tools have Zod input schemas", () => {
  const { service, store } = setup();
  const tools = toolset(service);
  for (const name of [
    "apply_to_job",
    "detect_ats",
    "inspect_application",
    "fill_application",
    "upload_resume",
    "upload_cover_letter",
    "answer_screening_questions",
    "review_application",
    "submit_application",
    "verify_submission",
    "pause_application",
    "resume_application",
    "get_application_status",
    "get_application_history",
    "update_answer_bank",
  ])
    assert.ok(tools[name as keyof typeof tools].schema);
  store.db.close();
});
