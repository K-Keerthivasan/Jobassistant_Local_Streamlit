import { randomUUID } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { ApplyInput, Snapshot, type Application } from "./schema.js";
import { detectAts, plan, reviewProblems } from "./adapters.js";
import { digest, documentInfo, safeUrl, sensitive } from "./security.js";
import { Store } from "./store.js";
import type { Browser } from "./bridge.js";
import { Studio } from "./studio.js";

export class Service {
  busy = false;
  stopped = false;
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
      if (
        !button ||
        !/^(next|continue|save and continue|apply|apply now|apply for this job|start application)$/i.test(
          button.label,
        )
      )
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
