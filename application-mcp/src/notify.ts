import type { Application } from "./schema.js";

/**
 * Desktop notifications for application barriers.
 *
 * Whenever an application lands on a state that needs the user (a login, a
 * CAPTCHA, a field to complete, the submit decision, an uncertain submission)
 * the service sends one notification through the Chrome extension, which shows
 * it with chrome.notifications and focuses the application tab on click. Each
 * barrier kind has its own on/off setting, kept in the engine database and
 * edited on the dashboard. A notification fires once per (state, reason)
 * change, never repeatedly for the same barrier.
 */
export const BARRIERS = [
  { id: "login", label: "Login, verification or expired session", on: true },
  { id: "captcha", label: "CAPTCHA", on: true },
  { id: "fields", label: "Fields to complete (consent, demographics, unknown answers)", on: true },
  { id: "documents", label: "Resume or cover letter attachment", on: true },
  { id: "domain", label: "New domain to approve", on: true },
  { id: "unavailable", label: "Job no longer available", on: true },
  { id: "review", label: "Application filled — ready for your final review", on: true },
  { id: "learned", label: "Manual answer detected and saved", on: true },
  { id: "uncertain", label: "Uncertain submission to verify", on: true },
  { id: "other", label: "Any other pause", on: true },
  { id: "result", label: "Final result (submitted, failed, rejected)", on: false },
] as const;
export type BarrierId = (typeof BARRIERS)[number]["id"];
export type NotifySettings = Record<BarrierId, boolean>;

export function defaultSettings(): NotifySettings {
  return Object.fromEntries(BARRIERS.map((b) => [b.id, b.on])) as NotifySettings;
}

/** Which barrier an application state represents, or null when it needs nobody. */
export function classify(a: Pick<Application, "state" | "reason" | "deferredAt">): BarrierId | null {
  if (a.deferredAt) return null;
  const reason = a.reason || "";
  if (a.state === "review") return "review";
  if (a.state === "uncertain") return "uncertain";
  if (["submitted", "failed", "rejected"].includes(a.state)) return "result";
  if (a.state !== "paused") return null;
  if (/captcha/i.test(reason)) return "captcha";
  // Domain first: its message also mentions completing a login.
  if (/new domain|approve the exact employer domain/i.test(reason)) return "domain";
  if (/login|verification|sign in|session expired|password|mfa/i.test(reason)) return "login";
  if (/no longer available|unavailable|filled/i.test(reason)) return "unavailable";
  if (/attach|cover letter|document|upload/i.test(reason)) return "documents";
  if (/required|consent|demograph|blank|unknown|manual|could not verify|answer|field/i.test(reason))
    return "fields";
  return "other";
}

const TITLES: Record<BarrierId, string> = {
  login: "Sign-in needed",
  captcha: "CAPTCHA to complete",
  fields: "Fields need you",
  documents: "Document attachment needs a look",
  domain: "New domain to approve",
  unavailable: "Job no longer available",
  review: "Ready to submit?",
  learned: "Answer saved",
  uncertain: "Submission uncertain",
  other: "Application paused",
  result: "Application finished",
};

export interface NotifyPayload {
  applicationId: string;
  barrier: BarrierId;
  title: string;
  message: string;
}

export function payloadFor(a: Application, barrier: BarrierId): NotifyPayload {
  const job = `${a.input.company}, ${a.input.title}`;
  const detail =
    barrier === "result" ? `${a.state}: ${a.reason || ""}` : a.reason || a.state;
  return {
    applicationId: a.id,
    barrier,
    title: `${TITLES[barrier]}: ${a.input.company}`,
    message: `${job}. ${detail}`.slice(0, 300),
  };
}

/**
 * Decide whether a save warrants a notification: the barrier kind is enabled
 * and the state or reason actually changed since the previous save.
 */
export function shouldNotify(
  previous: Pick<Application, "state" | "reason" | "preparationStage"> | undefined,
  next: Application,
  settings: NotifySettings,
): BarrierId | null {
  const barrier = classify(next);
  if (!barrier || !settings[barrier]) return null;
  if(next.preparationStage && next.preparationStage!=='needs_user' && ['fields','documents','captcha'].includes(barrier))return null;
  if (previous && previous.state === next.state && previous.preparationStage===next.preparationStage && (previous.reason || "") === (next.reason || ""))
    return null;
  return barrier;
}
