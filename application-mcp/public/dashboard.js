let applications = [];
let selected;
let queue = [];
let manualOpen = false;
const $ = (id) => document.getElementById(id);
async function api(url, body) {
  const r = await fetch(
    url,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const v = await r.json();
  if (!r.ok) throw new Error(v.error || "Request failed");
  return v;
}
async function act(fn) {
  $("error").textContent = "";
  try {
    await fn();
  } catch (e) {
    $("error").textContent = e.message;
  }
}
function button(text, fn) {
  const b = document.createElement("button");
  b.textContent = text;
  b.onclick = () => act(fn);
  return b;
}
function pre(value) {
  const p = document.createElement("pre");
  p.textContent =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return p;
}
async function tool(name, args = {}) {
  const r = await api("/tools/" + name, { applicationId: selected, ...args });
  await refresh();
  return r;
}
async function refresh() {
  const h = await api("/health");
  $("health").textContent = h.chromeConnected
    ? "Chrome connected" + (h.running ? " · running an application" : "")
    : h.extensionConfigured
      ? "Waiting for the Chrome extension. Open Chrome and click Connect."
      : "Load the extension in regular Chrome, copy its ID, and start the service with APP_CHROME_EXTENSION_ID.";
  applications = await api("/applications");
  const dropdown = $("applications");
  dropdown.replaceChildren();
  for (const a of applications) {
    const o = document.createElement("option");
    o.value = a.id;
    o.textContent = `${a.input.company} · ${a.input.title} · ${a.state}`;
    dropdown.append(o);
  }
  if (!applications.some((a) => a.id === selected))
    selected = applications[0]?.id;
  dropdown.value = selected || "";
  await render();
}
async function render() {
  const box = $("current");
  box.replaceChildren();
  const a = applications.find((a) => a.id === selected);
  if (!a) return;
  const title = document.createElement("h3");
  title.textContent = `${a.input.company} · ${a.input.title}`;
  box.append(
    title,
    pre({
      applicationId: a.id,
      state: a.state,
      action: a.reason,
      url: a.snapshot?.url || a.input.jobUrl,
    }),
  );
  box.append(
    button("Run until the next barrier", () =>
      api(`/applications/${a.id}/run`, {}).then(refresh),
    ),
    button("Stop running", () =>
      api(`/applications/${a.id}/stop-run`, {}).then(refresh),
    ),
  );
  const manual = document.createElement("details");
  manual.open = manualOpen;
  manual.ontoggle = () => (manualOpen = manual.open);
  const summary = document.createElement("summary");
  summary.textContent = "Manual steps";
  manual.append(summary);
  box.append(manual);
  for (const [text, name] of [
    ["Inspect", "inspect_application"],
    ["Fill confirmed fields", "fill_application"],
    ["Resume after manual action", "resume_application"],
    ["Review exact application", "review_application"],
    ["Verify uncertain submission", "verify_submission"],
    ["Sync verified result", "sync_application_result"],
  ])
    manual.append(button(text, () => tool(name)));
  box.append(
    button("Pause", () =>
      tool("pause_application", { reason: "Paused by user" }),
    ),
    button("Cancel attempt", () => tool("cancel_application")),
  );
  const domain = document.createElement("input");
  domain.placeholder = "Exact new employer domain";
  box.append(
    domain,
    button("Approve domain", () =>
      tool("approve_application_domain", {
        domain: domain.value,
        userConfirmed: true,
      }),
    ),
  );
  if (a.state === "uncertain") {
    const reason = document.createElement("input");
    reason.placeholder =
      "What you observed after investigating the employer site";
    box.append(
      reason,
      button("Confirm observed failure and close attempt", () =>
        tool("resolve_uncertain_application", {
          outcome: "failed",
          observedReason: reason.value,
          userConfirmed: true,
        }),
      ),
    );
  }
  if (a.snapshot) {
    const fieldsTitle = document.createElement("h4");
    fieldsTitle.textContent = "Observed answers and blanks";
    box.append(fieldsTitle, pre(a.snapshot.fields));
    for (const f of a.snapshot.fields.filter((f) => f.type === "file")) {
      const text = document.createElement("p");
      text.textContent = f.label || "Document upload";
      box.append(text);
      for (const d of a.documents)
        box.append(
          button(`Attach ${d.kind}: ${d.name}`, () =>
            tool(
              d.kind === "resume" ? "upload_resume" : "upload_cover_letter",
              { selector: f.selector, frameId: f.frameId },
            ),
          ),
        );
    }
    for (const b of a.snapshot.buttons.filter((b) =>
      /^(next|continue|save and continue|apply|apply now|apply for this job|start application)$/i.test(
        b.label,
      ),
    ))
      box.append(
        button(b.label, () =>
          tool("advance_application", {
            selector: b.selector,
            frameId: b.frameId,
          }),
        ),
      );
  }
  const docs = document.createElement("h4");
  docs.textContent = "Exact supplied documents";
  box.append(docs, pre(a.documents));
  if (
    a.documents.some(
      (d) => d.kind === "cover_letter" && !d.attached && !d.omissionReason,
    )
  ) {
    const reason = document.createElement("input");
    reason.placeholder = "Why this portal does not accept a cover letter";
    box.append(
      reason,
      button("Confirm optional cover letter omission", () =>
        tool("omit_optional_cover_letter", {
          reason: reason.value,
          userConfirmed: true,
        }),
      ),
    );
  }
  if (a.snapshot) {
    const mappings = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Teach a field from a confirmed profile fact";
    mappings.append(summary);
    const choice = document.createElement("select");
    for (const f of a.snapshot.fields.filter(
      (f) => !["checkbox", "file"].includes(f.type),
    )) {
      const o = document.createElement("option");
      o.value = JSON.stringify({ selector: f.selector, frameId: f.frameId });
      o.textContent = f.label;
      choice.append(o);
    }
    const key = document.createElement("input");
    key.placeholder = "Profile path, e.g. employmentHistory.0.title";
    mappings.append(
      choice,
      key,
      button("Confirm and remember mapping", () =>
        tool("confirm_site_field_mapping", {
          ...JSON.parse(choice.value),
          profilePath: key.value,
          userConfirmed: true,
        }),
      ),
    );
    box.append(mappings);
  }
  if (a.state === "review") {
    const p = document.createElement("p");
    p.textContent =
      "Submit this exact application: yes or no? Check every answer, attachment, blank and warning above.";
    box.append(p);
    for (const b of a.snapshot.buttons.filter((b) =>
      /^(submit application|submit|send application|apply now)$/i.test(b.label),
    )) {
      const yes = button(`Yes — ${b.label}`, () =>
        api(`/applications/${a.id}/approval`, {
          reviewHash: a.reviewHash,
          userSaidYes: true,
          selector: b.selector,
          frameId: b.frameId,
        }).then(refresh),
      );
      yes.className = "primary";
      box.append(yes);
    }
    box.append(button("No — cancel", () => tool("cancel_application")));
  }
  const history = await api(`/applications/${a.id}/history`);
  const h = document.createElement("h4");
  h.textContent = "Audit trail";
  box.append(h, pre(history.events));
  for (const [i, e] of (a.evidence || []).entries()) {
    const link = document.createElement("a");
    link.href = `/applications/${encodeURIComponent(a.id)}/evidence/${i}`;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = `View ${e.kind} screenshot · ${e.at}`;
    const line = document.createElement("p");
    line.append(link);
    box.append(line);
  }
}
$("applications").onchange = () =>
  act(async () => {
    selected = $("applications").value;
    await render();
  });
$("refresh").onclick = () => act(refresh);
$("stop").onclick = () => act(() => tool("stop_applications"));
$("queue").onclick = () =>
  act(async () => {
    const result = await api("/candidates");
    queue = result.candidates;
    $("candidates").replaceChildren();
    for (const job of queue) {
      const row = document.createElement("p");
      row.textContent = `${job.company} · ${job.title} `;
      row.append(
        button("Prepare in Chrome", async () => {
          const s = await api("/prepare", {
            job_key: job.key_id,
            run_id: job.run_id,
          });
          const a = await api("/applications", {
            jobUrl: s.job_url,
            company: s.company,
            title: s.title,
            studioSessionId: s.session_id,
            resumePath: s.documents.resume.path,
            coverLetterPath: s.documents.cover_letter?.path || null,
            mode: "review",
          });
          selected = a.id;
          await api(`/applications/${a.id}/run`, {});
          await refresh();
        }),
      );
      $("candidates").append(row);
    }
  });
$("save-answer").onclick = () =>
  act(() =>
    tool("update_answer_bank", {
      question: $("question").value,
      answer: $("answer").value,
      userConfirmed: true,
      reuseAllowed: true,
    }),
  );
async function loadNotifications() {
  const { barriers, settings } = await api("/notifications");
  $("notify").replaceChildren();
  for (const b of barriers) {
    const label = document.createElement("label");
    label.style.display = "block";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !!settings[b.id];
    box.onchange = () =>
      act(async () => {
        await api("/notifications", { [b.id]: box.checked });
      });
    label.append(box, " " + b.label);
    $("notify").append(label);
  }
}
$("notify-test").onclick = () =>
  act(async () => {
    const r = await fetch("/notifications/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!r.ok)
      throw new Error(
        "Chrome is not connected. Open the extension and click Connect, then try again.",
      );
  });
// Keep the view current while a run works in the background, and, when the
// queue option is on, prepare the next job once the current one is finished.
const FINAL_STATES = ["submitted", "failed", "rejected"];
let advancing = false;
setInterval(async () => {
  if (document.hidden) return;
  // Never redraw under someone typing into a dashboard field.
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName))
    return;
  try {
    await refresh();
    if (!$("auto-queue").checked || advancing) return;
    if (applications.some((a) => !FINAL_STATES.includes(a.state))) return;
    advancing = true;
    const { candidates } = await api("/candidates");
    const job = candidates[0];
    if (!job) {
      $("auto-queue").checked = false;
      $("error").textContent = "Queue finished: no more generated, unapplied jobs.";
      return;
    }
    const s = await api("/prepare", { job_key: job.key_id, run_id: job.run_id });
    const a = await api("/applications", {
      jobUrl: s.job_url,
      company: s.company,
      title: s.title,
      studioSessionId: s.session_id,
      resumePath: s.documents.resume.path,
      coverLetterPath: s.documents.cover_letter?.path || null,
      mode: "review",
    });
    selected = a.id;
    await api(`/applications/${a.id}/run`, {});
  } catch (e) {
    $("error").textContent = e.message;
  } finally {
    advancing = false;
  }
}, 4000);
act(refresh);
act(loadNotifications);
