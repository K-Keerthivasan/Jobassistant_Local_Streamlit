import { randomUUID } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { ApplyInput, Snapshot, type Application } from "./schema.js";
import {
  detectAts,
  isNavLabel,
  pickFinal,
  pickNav,
  plan,
  reviewProblems,
} from "./adapters.js";
import { digest, documentInfo, safeUrl, sensitive } from "./security.js";
import { Store } from "./store.js";
import type { Browser } from "./bridge.js";
import { Studio } from "./studio.js";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const DONE = ["review", "submitting", "uncertain", "submitted", "failed", "rejected"];
// How long a run waits for you at one barrier before giving up the wait.
const WAIT_MINUTES = 30;

export class Service {
  busy = false;
  stopped = false;
  /** Application id the auto-run is driving, if any. */
  running?: string;
  runCancel = false;
  waitMs = 4000;
  constructor(
    public store: Store,
    public browser: Browser,
    public studio: Studio,
    public root: string,
    public uploadRoots: string[],
    public validateUrl: typeof safeUrl = safeUrl,
  ) {}
  async exclusive<T>(action: () => Promise<T>) {
    if (this.busy) throw new Error("One application operation at a time.");
    this.busy = true;
    try {
      return await action();
    } finally {
      this.busy = false;
    }
  }
  active(id: string, allowPaused = false) {
    const a = this.store.get(id);
    if (
      this.stopped ||
      ["submitted", "failed", "rejected", "submitting", "uncertain"].includes(
        a.state,
      ) ||
      (!allowPaused && a.state === "paused")
    )
      throw new Error(
        "Application requires resume or investigation before this operation.",
      );
    return a;
  }
  async command(
    a: Application,
    op: string,
    args: Record<string, unknown> = {},
  ) {
    if (this.stopped && op !== "finish")
      throw new Error("Application service is stopped. Resume explicitly.");
    try {
      return await this.browser.command(op, {
        ...args,
        applicationId: a.id,
        domains: a.input.allowedDomains,
      });
    } catch (e) {
      if (
        ![
          "submitting",
          "uncertain",
          "submitted",
          "rejected",
          "failed",
        ].includes(a.state)
      ) {
        a.state = "paused";
        a.reason = (e as Error).message;
        a.approvedHash = undefined;
        this.store.save(a);
        this.store.event(a.id, "human_required", { reason: a.reason });
      }
      throw e;
    }
  }
  /**
   * Drive one application on its own until it needs the user: follow the
   * posting's apply link, fill confirmed answers, attach the documents, click
   * Next/Continue, and stop at the submit decision. At a login, CAPTCHA or a
   * field only the user can answer it pauses (which sends a notification),
   * watches the page, and carries on by itself once the barrier is gone.
   * It never clicks a submit control.
   */
  startRun(id: string) {
    if (this.running && this.running !== id)
      throw new Error("Another application is already running.");
    if (this.running === id) return { running: id };
    const a = this.store.get(id);
    if (DONE.includes(a.state))
      throw new Error(`Nothing to run: the application is ${a.state}.`);
    this.stopped = false;
    this.running = id;
    this.runCancel = false;
    this.store.event(id, "auto_run_started", {});
    void this.runLoop(id)
      .catch((e) => {
        const cur = this.store.get(id);
        if (!DONE.includes(cur.state)) {
          cur.state = "paused";
          cur.reason = `Auto-run stopped: ${(e as Error).message}`;
          this.store.save(cur);
        }
        this.store.event(id, "auto_run_error", { error: (e as Error).message });
      })
      .finally(() => {
        if (this.running === id) this.running = undefined;
        this.store.event(id, "auto_run_ended", {});
      });
    return { running: id };
  }
  stopRun() {
    this.runCancel = true;
    return { stopping: this.running || null };
  }
  private async pauseFor(id: string, reason: string) {
    const a = this.store.get(id);
    a.state = "paused";
    a.reason = reason;
    a.approvedHash = undefined;
    this.store.save(a);
    this.store.event(id, "human_required", { reason });
  }
  /** Watch the page while paused; true once the barrier is gone. */
  private async waitForUser(id: string) {
    const start = this.store.get(id);
    const key = (s?: Snapshot) =>
      s
        ? JSON.stringify([
            s.url,
            s.fields.map((f) => f.selector),
            reviewProblems(s).length,
          ])
        : "";
    const before = key(start.snapshot);
    const end = Date.now() + WAIT_MINUTES * 60_000;
    while (Date.now() < end) {
      await sleep(this.waitMs);
      if (this.runCancel || this.stopped) return false;
      const cur = this.store.get(id);
      if (cur.state !== "paused") return true; // resumed from the dashboard
      let snap: Snapshot;
      try {
        snap = Snapshot.parse(
          await this.browser.command("scan", {
            applicationId: id,
            domains: cur.input.allowedDomains,
          }),
        );
      } catch {
        continue; // still on a login or another domain: keep waiting
      }
      if (snap.blockers.length) continue;
      const blanks = reviewProblems(snap).length;
      if (key(snap) !== before || blanks === 0) {
        cur.state = "working";
        cur.reason = "";
        this.store.save(cur);
        this.store.event(id, "barrier_cleared", { url: snap.url });
        return true;
      }
    }
    await this.pauseFor(
      id,
      `Waited ${WAIT_MINUTES} minutes at this step. Click Run when you are ready.`,
    );
    return false;
  }
  private async runLoop(id: string) {
    let lastNav = false;
    for (let step = 0; step < 80; step++) {
      if (this.runCancel || this.stopped) return;
      let a = this.store.get(id);
      if (DONE.includes(a.state)) return;
      if (a.state === "paused") {
        // Our own apply/next click led to the employer's application site:
        // approve that exact host once, as part of following the posting.
        const host = /New domain[^(]*\(([a-z0-9.-]+)\)/i.exec(a.reason)?.[1];
        if (host && lastNav && !a.input.allowedDomains.includes(host)) {
          const u = await this.validateUrl("https://" + host);
          a.input.allowedDomains.push(u.hostname);
          a.state = "working";
          a.reason = "";
          this.store.save(a);
          this.store.event(id, "domain_followed_from_apply", { domain: u.hostname });
          lastNav = false;
          continue;
        }
        if (!(await this.waitForUser(id))) return;
        continue;
      }
      a = await this.exclusive(() => this.inspectInternal(this.active(id, true)));
      if (a.state === "paused") continue;
      lastNav = false;

      a = await this.fill(id);
      if (a.state === "paused") continue;

      for (const doc of a.documents.filter((d) => !d.attached && !d.omissionReason)) {
        const files = a.snapshot!.fields.filter((f) => f.type === "file");
        const field =
          files.find((f) =>
            doc.kind === "resume"
              ? /resume|résumé|\bcv\b/i.test(f.label)
              : /cover/i.test(f.label),
          ) ||
          (doc.kind === "resume" && files.length === 1 ? files[0] : undefined);
        if (!field || field.files.length) continue;
        try {
          a = await this.upload(id, doc.kind, field.selector, field.frameId);
        } catch (e) {
          await this.pauseFor(id, `Document upload: ${(e as Error).message}`);
          break;
        }
      }
      a = this.store.get(id);
      if (a.state === "paused") continue;

      const snapshot = a.snapshot!;
      if (pickFinal(snapshot)) {
        a = await this.review(id);
        if (a.state === "review") return; // the submit decision is yours
        continue; // review found problems and paused; wait for them
      }
      const blanks = reviewProblems(snapshot);
      if (blanks.length) {
        await this.pauseFor(id, `Fields need you: ${blanks.join("; ")}`);
        continue;
      }
      const nav = pickNav(snapshot);
      if (!nav) {
        await this.pauseFor(
          id,
          "No Apply or Next control found on this page; move the application forward in Chrome.",
        );
        continue;
      }
      if (nav.href) {
        const host = new URL(nav.href).hostname;
        if (!a.input.allowedDomains.includes(host)) {
          const u = await this.validateUrl(nav.href);
          a.input.allowedDomains.push(u.hostname);
          this.store.save(a);
          this.store.event(id, "domain_followed_from_apply", { domain: u.hostname });
        }
      }
      await this.navigate(id, nav.selector, nav.frameId);
      lastNav = true;
      await sleep(1500);
    }
    await this.pauseFor(id, "Auto-run step limit reached; continue in Chrome or click Run.");
  }
  async apply(raw: unknown) {
    return this.exclusive(async () => {
      if (this.stopped) throw new Error("Service stopped; resume explicitly.");
      const input = ApplyInput.parse(raw);
      if (input.mode === "automatic")
        throw new Error(
          "Standing automatic submission is disabled: project instructions require a fresh yes per application.",
        );
      if (
        this.store
          .list()
          .some((a) => !["submitted", "failed", "rejected"].includes(a.state))
      )
        throw new Error("Finish or cancel the active application first.");
      const u = await this.validateUrl(input.jobUrl);
      if (/(^|\.)(indeed\.com|linkedin\.com)$/.test(u.hostname))
        throw new Error("Use the direct employer application URL.");
      input.jobUrl = u.href;
      input.allowedDomains = [
        ...new Set([u.hostname, ...input.allowedDomains]),
      ];
      for (const host of input.allowedDomains)
        await this.validateUrl("https://" + host);
      const studio = await this.studio.validate(input.studioSessionId);
      if (
        studio.status !== "prepared" ||
        studio.job_url !== input.jobUrl ||
        studio.company !== input.company ||
        studio.title !== input.title ||
        !studio.run_id
      )
        throw new Error(
          "A matching prepared Resume Studio session with generated documents is required.",
        );
      const documents = [];
      for (const [kind, file] of [
        ["resume", input.resumePath],
        ["cover_letter", input.coverLetterPath],
      ] as const) {
        if (!file) continue;
        const info = await documentInfo(file, this.uploadRoots);
        const known =
          studio.documents?.[kind]?.path &&
          path.resolve(studio.documents[kind].path) === info.path;
        if (!known)
          throw new Error(
            "Use the exact documents in the Resume Studio approval packet.",
          );
        documents.push({ kind, ...info, attached: false });
      }
      const now = new Date().toISOString();
      const a: Application = {
        id: randomUUID(),
        input,
        state: "opening",
        ats: detectAts(input.jobUrl),
        documents,
        filled: [],
        reason: "",
        createdAt: now,
        updatedAt: now,
      };
      this.store.save(a);
      this.store.event(a.id, "created", { url: input.jobUrl, ats: a.ats });
      await this.command(a, "open", { url: input.jobUrl });
      return this.inspectInternal(a);
    });
  }
  async inspectInternal(a: Application) {
    const snapshot = Snapshot.parse(await this.command(a, "scan"));
    await this.validateUrl(snapshot.url, a.input.allowedDomains);
    a.snapshot = snapshot;
    a.ats = detectAts(snapshot.url);
    a.state = snapshot.blockers.length ? "paused" : "working";
    a.reason = snapshot.blockers.join("; ");
    a.reviewHash = undefined;
    a.approvedHash = undefined;
    this.store.template(new URL(snapshot.url).hostname, {
      ats: a.ats,
      fields: snapshot.fields.map(({ value, files, ...f }) => f),
      observedAt: new Date().toISOString(),
      tested: false,
    });
    this.store.event(a.id, "inspected", {
      url: snapshot.url,
      fieldCount: snapshot.fields.length,
      blockers: snapshot.blockers,
    });
    return this.store.save(a);
  }
  inspect(id: string) {
    return this.exclusive(() => this.inspectInternal(this.active(id)));
  }
  async fill(id: string) {
    return this.exclusive(async () => {
      const a = await this.inspectInternal(this.active(id));
      if (a.state === "paused") return a;
      const profile = JSON.parse(
        await readFile(path.join(this.root, "data/apply_profile.json"), "utf8"),
      );
      const planned = plan(
        a.snapshot!.fields,
        profile,
        this.store.mappings(new URL(a.snapshot!.url).hostname),
      );
      for (const entry of planned) {
        if (!entry.value || entry.field.value) continue;
        await this.command(a, "fill", {
          frameId: entry.field.frameId,
          selector: entry.field.selector,
          value: entry.value,
        });
        const observed = Snapshot.parse(await this.command(a, "scan"));
        const filled = observed.fields.find(
          (f) =>
            f.frameId === entry.field.frameId &&
            f.selector === entry.field.selector,
        );
        if (filled?.value !== entry.value) {
          a.state = "paused";
          a.reason = `Could not verify field: ${entry.field.label}`;
          return this.store.save(a);
        }
        a.filled.push({
          label: entry.field.label,
          value: entry.value,
          source: entry.source!,
        });
        this.store.save(a);
        this.store.event(a.id, "field_filled", {
          label: entry.field.label,
          source: entry.source,
        });
        // Dynamic controls may change; stop this pass and require a fresh plan when they do.
        if (
          observed.fields.map((f) => f.selector).join() !==
          a.snapshot!.fields.map((f) => f.selector).join()
        )
          break;
      }
      return this.inspectInternal(a);
    });
  }
  async upload(id: string, kind: string, selector: string, frameId = 0) {
    return this.exclusive(async () => {
      const a = await this.inspectInternal(this.active(id));
      if (a.state === "paused") return a;
      const doc = a.documents.find((d) => d.kind === kind);
      if (!doc) throw new Error("No supplied document of this type.");
      const info = await documentInfo(doc.path, this.uploadRoots);
      if (info.hash !== doc.hash)
        throw new Error("Document changed since preparation.");
      const field = a.snapshot!.fields.find(
        (f) =>
          f.selector === selector && f.frameId === frameId && f.type === "file",
      );
      if (!field) throw new Error("Choose an observed file input.");
      if (
        a.documents.some(
          (d) =>
            d.kind !== kind &&
            d.attached &&
            d.selector === selector &&
            d.frameId === frameId,
        )
      )
        throw new Error(
          "This input already contains a different application document. Choose its correct document type control.",
        );
      if (
        (kind === "resume" && /cover.?letter/i.test(field.label)) ||
        (kind === "cover_letter" && /resume|résumé|\bcv\b/i.test(field.label))
      )
        throw new Error("Document type does not match the upload label.");
      const ext = path.extname(doc.path).toLowerCase();
      const mime: Record<string, string> = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx":
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
      };
      if (
        field.accept &&
        !field.accept
          .split(",")
          .some(
            (t) =>
              t.trim().toLowerCase() === ext ||
              t.trim().toLowerCase() === mime[ext] ||
              t.trim() === "*/*",
          )
      )
        throw new Error("Document type does not match this upload input.");
      await this.command(a, "upload", { selector, frameId, path: doc.path });
      const snapshot = Snapshot.parse(await this.command(a, "scan"));
      if (
        !snapshot.fields
          .find((f) => f.selector === selector && f.frameId === frameId)
          ?.files.includes(doc.name)
      )
        throw new Error(
          "Document attachment was not verified; inspect the website.",
        );
      doc.attached = true;
      doc.selector = selector;
      doc.frameId = frameId;
      this.store.event(a.id, "document_attached", {
        kind,
        path: doc.path,
        hash: doc.hash,
        url: snapshot.url,
        selector,
      });
      return this.inspectInternal(a);
    });
  }
  async navigate(id: string, selector: string, frameId = 0) {
    return this.exclusive(async () => {
      const a = await this.inspectInternal(this.active(id));
      if (a.state === "paused") return a;
      const button = a.snapshot!.buttons.find(
        (b) => b.selector === selector && b.frameId === frameId,
      );
      if (!button || !isNavLabel(button.label))
        throw new Error("Only an observed navigation control may be used.");
      if (button.href)
        await this.validateUrl(button.href, a.input.allowedDomains);
      await this.command(a, "click", { selector, frameId, submit: false });
      return this.inspectInternal(a);
    });
  }
  async review(id: string) {
    return this.exclusive(async () => {
      const a = await this.inspectInternal(this.active(id));
      const problems = reviewProblems(a.snapshot!);
      if (!a.documents.find((d) => d.kind === "resume")?.attached)
        problems.push("Resume attachment has not been verified.");
      if (
        a.documents.some(
          (d) => d.kind === "cover_letter" && !d.attached && !d.omissionReason,
        )
      )
        problems.push(
          "Supplied cover letter has not been attached; attach it or explicitly omit it if the portal does not accept one.",
        );
      for (const doc of a.documents.filter((d) => d.attached)) {
        const field = a.snapshot!.fields.find(
          (f) => f.selector === doc.selector && f.frameId === doc.frameId,
        );
        if (field && !field.files.includes(doc.name))
          problems.push(`Attachment changed: ${doc.kind}`);
      }
      if (problems.length) {
        a.state = "paused";
        a.reason = problems.join("; ");
        return this.store.save(a);
      }
      a.state = "review";
      a.reason = "Submit this exact application: yes or no?";
      a.reviewHash = digest({ snapshot: a.snapshot, documents: a.documents });
      await this.studio.snapshot(a.input.studioSessionId, {
        snapshot: a.snapshot,
        documents: a.documents,
        filled: a.filled,
        engine_id: a.id,
        review_hash: a.reviewHash,
      });
      this.store.event(a.id, "review_ready", { hash: a.reviewHash });
      await this.captureInternal(a);
      return this.store.save(a);
    });
  }
  async submit(
    id: string,
    hash: string,
    yes: boolean,
    selector: string,
    frameId = 0,
  ) {
    return this.exclusive(async () => {
      const a = this.active(id);
      if (
        !yes ||
        a.state !== "review" ||
        !a.reviewHash ||
        hash !== a.reviewHash
      )
        throw new Error("A fresh yes for this exact review is required.");
      const snapshot = Snapshot.parse(await this.command(a, "scan"));
      if (
        digest({ snapshot, documents: a.documents }) !== hash ||
        reviewProblems(snapshot).length
      )
        throw new Error("Form changed; review and approve again.");
      const button = snapshot.buttons.find(
        (b) => b.selector === selector && b.frameId === frameId,
      );
      if (
        !button ||
        !/^(submit application|submit|send application|apply now)$/i.test(
          button.label,
        )
      )
        throw new Error(
          "Choose the exact final submission control from the review.",
        );
      for (const d of a.documents)
        if ((await documentInfo(d.path, this.uploadRoots)).hash !== d.hash)
          throw new Error("Document changed; prepare again.");
      await this.studio.validate(a.input.studioSessionId);
      const decision = await this.studio.confirm(a.input.studioSessionId);
      if (!decision.may_submit || decision.already_decided)
        throw new Error(
          "Resume Studio did not issue a fresh submission authorization.",
        );
      a.approvedHash = hash;
      a.approvedAt = new Date().toISOString();
      a.state = "submitting";
      this.store.save(a);
      this.store.event(a.id, "submission_started", { hash, url: snapshot.url });
      try {
        await this.command(a, "click", { selector, frameId, submit: true });
      } catch {
        a.state = "uncertain";
        a.reason =
          "Submission may have occurred; inspect the site before any retry.";
        return this.store.save(a);
      }
      a.state = "uncertain";
      this.store.save(a);
      return this.verifyInternal(a);
    });
  }
  async verifyInternal(a: Application) {
    if (!["uncertain", "submitting"].includes(a.state))
      throw new Error("No submission attempt is awaiting verification.");
    const snapshot = Snapshot.parse(await this.command(a, "scan"));
    if (!snapshot.confirmation) {
      a.state = "uncertain";
      a.reason =
        "No visible submission confirmation. Investigate in Chrome; do not resubmit.";
      return this.store.save(a);
    }
    a.state = "submitted";
    a.confirmation = snapshot.confirmation;
    a.reason = "Visible employer confirmation verified.";
    a.snapshot = snapshot;
    this.store.save(a);
    this.store.event(a.id, "submission_verified", {
      url: snapshot.url,
      confirmation: snapshot.confirmation,
    });
    await this.captureInternal(a);
    try {
      await this.studio.result(
        a.input.studioSessionId,
        "submitted",
        `${snapshot.url}: ${snapshot.confirmation}`,
        true,
      );
      a.synced = true;
    } catch {
      a.synced = false;
      a.reason += " Resume Studio sync failed; use sync_application_result.";
    }
    await this.command(a, "finish");
    return this.store.save(a);
  }
  verify(id: string) {
    return this.exclusive(() => this.verifyInternal(this.store.get(id)));
  }
  async captureInternal(a: Application) {
    try {
      const response = (await this.browser.command("screenshot", {
        applicationId: a.id,
        domains: a.input.allowedDomains,
      })) as { data: string };
      if (
        typeof response.data !== "string" ||
        response.data.length > 8 * 1024 * 1024
      )
        throw new Error("Screenshot unavailable or too large.");
      const bytes = Buffer.from(response.data, "base64");
      if (bytes.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a")
        throw new Error("Invalid screenshot image.");
      const directory = path.join(
        this.root,
        "data/job-applications/engine/evidence",
        a.id,
      );
      await mkdir(directory, { recursive: true });
      const file = path.join(directory, Date.now() + ".png");
      await writeFile(file, bytes, { flag: "wx" });
      const evidence = {
        kind: a.state,
        path: file,
        url: a.snapshot?.url || a.input.jobUrl,
        at: new Date().toISOString(),
      };
      (a.evidence ||= []).push(evidence);
      this.store.event(a.id, "screenshot_saved", evidence);
      this.store.save(a);
    } catch {
      this.store.event(a.id, "screenshot_unavailable", {
        reason: "Page capture unavailable; structured observations retained.",
      });
    }
  }
  capture(id: string) {
    return this.exclusive(async () => {
      const a = this.active(id, true);
      if (a.snapshot?.blockers.length)
        throw new Error("Resolve login or verification before capture.");
      await this.captureInternal(a);
      return this.store.save(a);
    });
  }
  async sync(id: string) {
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (a.state !== "submitted" || !a.confirmation)
        throw new Error("No verified result to sync.");
      await this.studio.result(
        a.input.studioSessionId,
        "submitted",
        `${a.snapshot?.url}: ${a.confirmation}`,
        true,
      );
      a.synced = true;
      return this.store.save(a);
    });
  }
  resolveUncertain(
    id: string,
    outcome: "failed" | "rejected",
    reason: string,
    confirmed: boolean,
  ) {
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (a.state !== "uncertain" || !confirmed || !reason.trim())
        throw new Error(
          "Inspect the employer site and explicitly confirm the observed failure before resolving uncertainty.",
        );
      await this.studio.result(
        a.input.studioSessionId,
        outcome,
        `User investigated uncertain submission: ${reason}`,
        false,
      );
      a.state = outcome;
      a.reason = reason;
      this.store.event(id, "uncertainty_resolved_by_user", { outcome, reason });
      this.store.save(a);
      await this.command(a, "finish");
      return a;
    });
  }
  pause(id: string, reason: string) {
    return this.exclusive(async () => {
      const a = this.active(id, true);
      a.state = "paused";
      a.reason = reason;
      a.approvedHash = undefined;
      this.store.event(id, "paused", { reason });
      return this.store.save(a);
    });
  }
  resume(id: string) {
    return this.exclusive(async () => {
      this.stopped = false;
      return this.inspectInternal(this.active(id, true));
    });
  }
  cancel(id: string) {
    return this.exclusive(async () => {
      const a = this.active(id, true);
      a.state = "rejected";
      a.reason = "Cancelled by user";
      this.store.save(a);
      await this.studio.result(
        a.input.studioSessionId,
        "rejected",
        a.reason,
        false,
      );
      await this.command(a, "finish");
      return a;
    });
  }
  async allowDomain(id: string, domain: string, confirmed: boolean) {
    return this.exclusive(async () => {
      if (!confirmed)
        throw new Error("User confirmation required for a new domain.");
      const a = this.active(id, true);
      const u = await this.validateUrl("https://" + domain);
      if (u.hostname !== domain)
        throw new Error("Enter an exact hostname only.");
      a.input.allowedDomains.push(u.hostname);
      this.store.event(id, "domain_approved", { domain: u.hostname });
      return this.store.save(a);
    });
  }
  async omitCover(id: string, reason: string, confirmed: boolean) {
    return this.exclusive(async () => {
      if (!confirmed || !reason.trim())
        throw new Error(
          "Confirm why this portal does not accept the optional cover letter.",
        );
      const a = this.active(id, true);
      const doc = a.documents.find((d) => d.kind === "cover_letter");
      if (!doc || doc.attached)
        throw new Error(
          "Only an unattached optional cover letter can be omitted.",
        );
      doc.omissionReason = reason;
      a.reviewHash = undefined;
      this.store.event(id, "cover_letter_omitted", { reason });
      return this.store.save(a);
    });
  }
  async mapping(
    id: string,
    selector: string,
    frameId: number,
    profilePath: string,
    confirmed: boolean,
  ) {
    return this.exclusive(async () => {
      if (!confirmed)
        throw new Error("Confirm the exact profile mapping first.");
      const a = this.active(id, true);
      const field = a.snapshot?.fields.find(
        (f) => f.selector === selector && f.frameId === frameId,
      );
      if (
        !field ||
        sensitive(field.label) ||
        ["checkbox", "file"].includes(field.type)
      )
        throw new Error("This control cannot be mapped.");
      if (
        a.snapshot!.fields.filter((f) => f.label === field.label).length !==
          1 ||
        sensitive(profilePath)
      )
        throw new Error(
          "Repeated labels and sensitive profile paths require manual completion.",
        );
      const profile = JSON.parse(
        await readFile(path.join(this.root, "data/apply_profile.json"), "utf8"),
      );
      const value = profilePath
        .split(".")
        .reduce((v: any, key) => v?.[key], profile);
      if (
        typeof value !== "string" ||
        !value.trim() ||
        (field.options.length && !field.options.includes(value))
      )
        throw new Error(
          "The profile path must contain a confirmed value matching this exact control.",
        );
      const host = new URL(a.snapshot!.url).hostname;
      this.store.saveMapping(host, {
        label: field.label,
        type: field.type,
        options: field.options,
        profilePath,
      });
      this.store.event(id, "site_mapping_confirmed", {
        host,
        label: field.label,
        profilePath,
      });
      return this.store.mappings(host);
    });
  }
  async answer(
    question: string,
    answer: string,
    confirmed: boolean,
    reuse: boolean,
  ) {
    if (!confirmed || sensitive(question))
      throw new Error(
        "Only user-confirmed, non-sensitive reusable answers may be saved.",
      );
    return this.studio.request("/application-engine/answers", {
      question,
      answer,
      confirmed,
      reuse,
    });
  }
}
