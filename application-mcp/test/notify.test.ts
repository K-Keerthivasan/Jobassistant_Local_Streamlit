import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { classify, defaultSettings, payloadFor, shouldNotify } from "../src/notify.js";
import { Store } from "../src/store.js";
import type { Application } from "../src/schema.js";

const app = (state: Application["state"], reason: string): Application =>
  ({
    id: "a1",
    input: {
      jobUrl: "https://jobs.example.com/1",
      resumePath: "r.pdf",
      coverLetterPath: null,
      profileId: "default",
      mode: "review",
      company: "Loblaw",
      title: "Associate Product Manager",
      studioSessionId: "s1",
      allowedDomains: [],
    },
    state,
    reason,
    ats: "generic",
    documents: [],
  }) as unknown as Application;

test("each barrier reason maps to its own category", () => {
  assert.equal(classify(app("paused", "CAPTCHA: complete it in Chrome.")), "captcha");
  assert.equal(classify(app("paused", "Login or verification: complete it in Chrome.")), "login");
  assert.equal(classify(app("paused", "Session expired: sign in in Chrome.")), "login");
  assert.equal(classify(app("paused", "Opportunity unavailable.")), "unavailable");
  assert.equal(classify(app("paused", "New domain: approve the exact employer domain, or complete login manually, then resume.")), "domain");
  assert.equal(classify(app("paused", "Resume attachment has not been verified.")), "documents");
  assert.equal(classify(app("paused", "Required field blank: Gender")), "fields");
  assert.equal(classify(app("paused", "Service restarted; resume and inspect the current Chrome tab.")), "other");
  assert.equal(classify(app("review", "Submit this exact application: yes or no?")), "review");
  assert.equal(classify(app("uncertain", "No confirmation seen.")), "uncertain");
  assert.equal(classify(app("submitted", "Visible employer confirmation verified.")), "result");
  assert.equal(classify(app("working", "")), null);
});

test("notifies once per change, only for enabled barriers", () => {
  const settings = defaultSettings();
  const captcha = app("paused", "CAPTCHA: complete it in Chrome.");
  assert.equal(shouldNotify(undefined, captcha, settings), "captcha");
  assert.equal(shouldNotify({ state: "paused", reason: captcha.reason }, captcha, settings), null);
  assert.equal(shouldNotify({ state: "working", reason: "" }, captcha, { ...settings, captcha: false }), null);
  // Results are off by default.
  assert.equal(shouldNotify({ state: "submitting", reason: "" }, app("submitted", "ok"), settings), null);
});

test("payload names the job and the barrier", () => {
  const p = payloadFor(app("review", "Submit this exact application: yes or no?"), "review");
  assert.match(p.title, /Ready to submit\?: Loblaw/);
  assert.match(p.message, /Associate Product Manager/);
});
test("deferred applications do not send another action notification", () => {
  const pending = { ...app("paused", "CAPTCHA"), deferredAt: new Date().toISOString() };
  assert.equal(shouldNotify(undefined, pending, defaultSettings()), null);
});

test("store persists settings and reports state changes to its listener", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "notify-"));
  try {
    const store = new Store(path.join(dir, "a.sqlite"));
    assert.equal(store.notifySettings().captcha, true);
    assert.equal(store.notifySettings({ captcha: false, bogus: true } as any).captcha, false);
    assert.equal("bogus" in store.notifySettings(), false);
    const seen: (string | undefined)[] = [];
    store.onSave = (previous, next) => seen.push(`${previous?.state ?? "new"}->${next.state}`);
    const a = app("working", "");
    store.save(a);
    store.save({ ...a, state: "paused", reason: "CAPTCHA: complete it in Chrome." });
    assert.deepEqual(seen, ["new->working", "working->paused"]);
    store.db.close();
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
