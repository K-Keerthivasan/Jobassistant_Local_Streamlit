import type { Field, Snapshot } from "./schema.js";
import { normalize, sensitive } from "./security.js";

export interface Adapter {
  name: string;
  matches(host: string): boolean;
  tested: boolean;
}
// Detection is distinct from tested form support. All portals use live generic inspection.
export const adapters: Adapter[] = [
  ["greenhouse", /(^|\.)(greenhouse\.io|greenhouse\.com)$/],
  ["lever", /(^|\.)lever\.co$/],
  ["ashby", /(^|\.)ashbyhq\.com$/],
  ["workday", /(^|\.)myworkdayjobs\.com$/],
  ["smartrecruiters", /(^|\.)smartrecruiters\.com$/],
  ["icims", /(^|\.)icims\.com$/],
].map(([name, pattern]) => ({
  name: String(name),
  matches: (host: string) => (pattern as RegExp).test(host),
  tested: false,
}));
export const detectAts = (url: string) =>
  adapters.find((a) => a.matches(new URL(url).hostname))?.name || "generic";

const identity: Record<string, string> = {
  "first name": "firstName",
  "given name": "firstName",
  "last name": "lastName",
  surname: "lastName",
  "full name": "fullName",
  "legal name": "fullName",
  "preferred name": "preferredName",
  email: "email",
  "email address": "email",
  phone: "phone",
  "phone number": "phone",
  address: "address",
  "street address": "address",
  city: "city",
  province: "province",
  state: "province",
  country: "country",
  "postal code": "postalCode",
  "zip code": "postalCode",
  linkedin: "linkedin",
  "linkedin profile": "linkedin",
  portfolio: "portfolio",
  website: "portfolio",
  github: "github",
};
export function plan(
  fields: Field[],
  profile: Record<string, unknown>,
  mappings: {
    label: string;
    type: string;
    options: string[];
    profilePath: string;
  }[] = [],
) {
  const bank = (profile.commonAnswers as Record<string, string>) || {};
  return fields.map((field) => {
    const q = normalize(field.label).replace(/\s*\*$/, "");
    if (
      fields.filter((f) => normalize(f.label).replace(/\s*\*$/, "") === q)
        .length !== 1
    )
      return {
        field,
        reason: "Ambiguous repeated field label; complete it manually",
      };
    if (sensitive(q) || ["checkbox", "file"].includes(field.type))
      return { field, reason: "Manual choice or document control" };
    const key = identity[q];
    const mapping = mappings.find(
      (m) =>
        m.label === field.label &&
        m.type === field.type &&
        JSON.stringify(m.options) === JSON.stringify(field.options),
    );
    const answer = Object.entries(bank).find(
      ([question]) => normalize(question) === q,
    );
    const value = mapping
      ? mapping.profilePath.split(".").reduce((v: any, k) => v?.[k], profile)
      : key
        ? profile[key]
        : answer?.[1];
    if (typeof value !== "string" || !value.trim())
      return { field, reason: "No confirmed exact answer" };
    if (field.options.length && !field.options.includes(value))
      return {
        field,
        reason: "Confirmed answer does not exactly match an option",
      };
    return {
      field,
      value,
      source: mapping
        ? `apply_profile.${mapping.profilePath} (confirmed site mapping)`
        : key
          ? `apply_profile.${key}`
          : `apply_profile.commonAnswers.${answer![0]}`,
    };
  });
}
export function reviewProblems(snapshot: Snapshot) {
  return [
    ...snapshot.blockers,
    ...snapshot.fields
      .filter((f) => (f.required && !f.value && !f.files.length) || f.invalid)
      .map((f) => `${f.invalid ? "Invalid" : "Required blank"}: ${f.label}`),
  ];
}

// Controls the auto-run may click to move toward the form: the posting's own
// apply link and in-form Next/Continue steps. Never a submit control.
const NAV =
  /^(next|continue|save and continue|save & continue|apply|apply now|apply online|click here to apply(?: online)?|apply for this (?:job|position|role)|apply to this (?:job|position|role)|start(?: your| my)? application|begin application|i'?m interested)$/i;
export const isNavLabel = (label: string) =>
  NAV.test(label.trim().replace(/\s+/g, " ")) && !/submit|send/i.test(label);
// Final submission controls. Only clicked after a fresh yes on the review.
export const FINAL = /^(submit application|submit|send application|apply now|apply)$/i;

/** Pick the next navigation control: in-form steps first, then apply links. */
export function pickNav(snapshot: Snapshot) {
  const candidates = snapshot.buttons.filter(
    (b) =>
      isNavLabel(b.label) &&
      (!b.href || /^https:/i.test(b.href)) &&
      // A non-link "Apply" on a page with form fields is the final submit.
      !(!b.href && /apply/i.test(b.label) && snapshot.fields.length > 0),
  );
  const rank = (label: string) =>
    /^(next|continue|save)/i.test(label.trim()) ? 0 : 1;
  return candidates.sort((x, y) => rank(x.label) - rank(y.label))[0];
}

/** The final submit control of a form page, if one is visible. */
export function pickFinal(snapshot: Snapshot) {
  if (!snapshot.fields.length) return undefined;
  return snapshot.buttons.find(
    (b) => !b.href && FINAL.test(b.label.trim().replace(/\s+/g, " ")),
  );
}
