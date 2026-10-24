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
  ["indeed", /(^|\.)indeed\.com$/],
  ["smartrecruiters", /(^|\.)smartrecruiters\.com$/],
  ["icims", /(^|\.)icims\.com$/],
  ["bamboohr", /(^|\.)bamboohr\.com$/],
  ["dayforce", /(^|\.)(dayforcehcm\.com|dayforce\.com)$/],
  ["ukg", /(^|\.)(ultipro\.com|ukg\.com|ukg\.net)$/],
  ["workable", /(^|\.)workable\.com$/],
  ["jobvite", /(^|\.)jobvite\.com$/],
  ["taleo", /(^|\.)taleo\.net$/],
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
  "please type your full name.": "fullName",
  "please type your full name": "fullName",
  "please enter your full name.": "fullName",
  "please enter your full name": "fullName",
  "legal name": "fullName",
  "preferred name": "preferredName",
  email: "email",
  "email address": "email",
  phone: "phone",
  "phone number": "phone",
  "mobile phone number": "phone",
  "mobile phone": "phone",
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
  "linkedin url": "linkedin",
  portfolio: "portfolio",
  website: "portfolio",
  "website, blog or portfolio": "portfolio",
  "date available": "availableStartDate",
  "available start date": "availableStartDate",
  "earliest start date": "availableStartDate",
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
  context: { title?: string; now?: Date } = {},
) {
  const bank = (profile.commonAnswers as Record<string, string>) || {};
  const questionKey = (label: string, field?: Field) => {
    let key = normalize(label).replace(/^\*\s*|\s*\*$/g, "").trim();
    if (field?.type === "custom-select") {
      const value = normalize(field.value);
      if (value && key.endsWith(" " + value)) key = key.slice(0, -value.length).trim();
      else key = key.replace(/\s+[–—-]?\s*(?:select|choose)(?:\s*(?:one|an option))?\s*[–—-]?$/, "").trim();
    }
    return key;
  };
  return fields.map((field) => {
    if (field.history) {
      const confirmed = bank[field.label];
      if (confirmed && !sensitive(field.label) && !['checkbox','file'].includes(field.type) && (!field.options.length || field.options.includes(confirmed)))
        return {field,value:confirmed,source:'apply_profile.commonAnswers.'+field.label};
      const h = field.history;
      const rows = ((profile.tailoredResume as any)?.[h.section] || []) as Record<string, any>[];
      const peers = fields.filter(f => f.history?.section === h.section && f.history.index === h.index);
      const anchorKey = h.section === 'experience' ? 'company' : 'institution';
      const anchor = peers.find(f => f.history?.key === anchorKey)?.value;
      const matched = anchor ? rows.filter(r => normalize(r[anchorKey] || '') === normalize(anchor)) : [];
      const identityKey=h.section==='education'?'credential':'role';
      const identity=peers.find(f=>f.history?.key===identityKey)?.value;
      const identityMatches=identity?rows.filter(r=>normalize(r[identityKey] || '')===normalize(identity)):[];
      const groups = [...new Set(fields.filter(f => f.history?.section === h.section).map(f => f.history!.index))];
      const anchors = fields.filter(f => f.history?.section === h.section && f.history.key === anchorKey && f.value);
      const aligned = groups.length === rows.length && anchors.length >= 2 && anchors.every(f => normalize(rows[f.history!.index]?.[anchorKey] || '') === normalize(f.value));
      const row = identityMatches.length===1?identityMatches[0]:matched.length === 1 ? matched[0] : aligned || (h.orderedBlankRow && !anchor && !identity) ? rows[h.index] : undefined;
      let value = row?.[h.key];
      if(row && /^(?:start|end)Date$/.test(h.key)){
        const raw=String(row[h.key==='startDate'?'start':'end'] || '');
        value=/^\d{4}-\d{2}-\d{2}$/.test(raw)?raw:undefined;
      }
      if (h.key === 'bullets' && Array.isArray(value)) value = value.map((s:string) => s.replace(/\*\*/g,'')).join('\n');
      if (row && /^(start|end)(Month|Year)$/.test(h.key)) {
        const [,side,part] = h.key.match(/^(start|end)(Month|Year)$/)!;
        const date = String(row[side] || '');
        const month = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/i.exec(date);
        value = part === 'Year' ? date.match(/\b(?:19|20)\d{2}\b/)?.[0] : month ? String(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].indexOf(month[1].toLowerCase())+1) : undefined;
      }
      // A year-only resume date does not authorize inventing January.
      if (typeof value === 'string' && value.trim() && (!field.options.length || field.options.includes(value)))
        return {field,value,source:'tailored_resume.'+h.section+'.'+rows.indexOf(row!)+'.'+h.key};
      return {field,reason:'No unambiguous tailored-resume value for this history field'};
    }
    const q = questionKey(field.label, field);
    if (
      fields.filter((f) => questionKey(f.label, f) === q)
        .length !== 1
    )
      return {
        field,
        reason: "Ambiguous repeated field label; complete it manually",
      };
    if (sensitive(q) || ["checkbox", "file"].includes(field.type))
      return { field, reason: "Manual choice or document control" };
    let key = identity[q];
    if (key === "portfolio" && /\b(developer|software|engineer|data scientist|qa|systems analyst)\b/i.test(context.title || "") && profile.github)
      key = "github";
    const mapping = mappings.find(
      (m) =>
        m.label === field.label &&
        m.type === field.type &&
        JSON.stringify(m.options) === JSON.stringify(field.options),
    );
    const equivalent: Record<string, string> = {
      "where did you hear about us?": "how did you hear about us?",
      "how did you hear about this position?": "how did you hear about us?",
      "how did you hear about this job?": "how did you hear about us?",
      "are you currently eligible to work in canada?":
        "are you legally authorized to work in canada?",
    };
    const answer = Object.entries(bank).find(
      ([question]) => (equivalent[questionKey(question)] || questionKey(question)) === (equivalent[q] || q),
    );
    let value = mapping
      ? mapping.profilePath.split(".").reduce((v: any, k) => v?.[k], profile)
      : key
        ? profile[key]
        : answer?.[1];
    if (key === "province" && value === "ON" && profile.country === "Canada" &&
      (field.type === "custom-select" || field.options.includes("Ontario"))) value = "Ontario";
    if ((key === "availableStartDate" || mapping?.profilePath==='availableStartDate') && value === "Two weeks from application date") {
      const local = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(context.now || new Date());
      const date = new Date(local + "T12:00:00Z");
      date.setUTCDate(date.getUTCDate() + 14);
      const iso = date.toISOString().slice(0, 10);
      value = field.type === "date" || field.dateFormat==='YYYY-MM-DD' ? iso : field.dateFormat==='DD/MM/YYYY' ? `${iso.slice(8,10)}/${iso.slice(5,7)}/${iso.slice(0,4)}` : `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(0, 4)}`;
    }
    if (typeof value !== "string" || !value.trim())
      return { field, reason: "No confirmed exact answer" };
    if ((equivalent[q] || q) === "how did you hear about us?" && normalize(value) === "indeed" && field.options.length) {
      const exact = field.options.filter(option => /\bindeed\b/i.test(option));
      const board = field.options.filter(option => /^(?:online )?job boards?$/i.test(option.trim()));
      if (exact.length === 1) value = exact[0];
      else if (!exact.length && board.length === 1) value = board[0];
    }
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
    ...snapshot.buttons.filter(b => /^[–—-]?\s*(?:select|choose)(?:\s*(?:one|an option))?\s*[–—-]?$/i.test(b.label.trim()) &&
      !snapshot.fields.some(f => f.selector === b.selector && f.frameId === b.frameId))
      .map(() => "Unverified custom dropdown: update the Chrome bridge and inspect this control before submission."),
    ...snapshot.fields
      .filter((f) => (f.required && !f.value && !f.files.length && !(f.type === 'file' && snapshot.attachments.some(r => r.frameId === f.frameId && (r.kind === 'cover_letter' ? /cover.?letter/i.test(f.label) : /resume|résumé|\bcv\b/i.test(f.label))))) || f.invalid)
      .map((f) => `${f.invalid ? "Invalid" : "Required blank"}: ${f.label}`),
  ];
}

// Controls the auto-run may click to move toward the form: the posting's own
// apply link and in-form Next/Continue steps. Never a submit control.
const NAV =
  /^(next|continue|continue application|review your application|review application|apply on company site|save and continue|save & continue|apply|apply now|apply online|click here to apply(?: online)?|apply for this (?:job|position|role)|apply to this (?:job|position|role)|autofill with resume|apply manually|apply without an account|start(?: your| my)? application|begin application|i'?m interested)$/i;
export const isNavLabel = (label: string) =>
  NAV.test(label.trim().replace(/\s+/g, " ")) && !/submit|send/i.test(label);
// Final submission controls. Only clicked after a fresh yes on the review.
export const FINAL =
  /^(submit your application|submit application|submit|send application|apply now|apply)$/i;

/** Pick the next navigation control: in-form steps first, then apply links. */
export const hasApplicationFields = (snapshot: Snapshot) => snapshot.fields.some(f =>
  f.type !== "search" && !/^(?:language|search(?: jobs)?|link to this job)$/i.test(f.label.trim()));
export function pickNav(snapshot: Snapshot) {
  const cisco=ciscoPosting(snapshot);
  if(cisco)return snapshot.buttons.find(b=>{
    if(!/^apply now$/i.test(b.label.trim()) || !b.href)return false;
    try{const u=new URL(b.href);return u.origin==='https://careers.cisco.com' && u.pathname==='/global/en/hvhapply' && u.searchParams.get('jobSeqNo')===`CISCISGLOBAL${cisco}EXTERNALENGLOBAL`;}catch{return false;}
  });
  const candidates = snapshot.buttons.filter(
    (b) =>
      isNavLabel(b.label) &&
      (!b.href || /^https:/i.test(b.href)) &&
      // A non-link "Apply" on a page with form fields is the final submit.
      !(!b.href && /^(apply|apply now)$/i.test(b.label.trim()) && hasApplicationFields(snapshot)),
  );
  const rank = (label: string) =>
    /^(next|continue|save|autofill with resume)/i.test(label.trim()) ? 0 : 1;
  return candidates.sort((x, y) => rank(x.label) - rank(y.label))[0];
}

/** The final submit control of a form page, if one is visible. */
export function pickFinal(snapshot: Snapshot) {
  if(ciscoPosting(snapshot))return undefined;
  if (!hasApplicationFields(snapshot) && !snapshot.buttons.some(b=>!b.href && /^submit(?: your)? application$/i.test(b.label.trim()))) return undefined;
  return snapshot.buttons.find(
    (b) => !b.href && FINAL.test(b.label.trim().replace(/\s+/g, " ")),
  );
}
function ciscoPosting(snapshot:Snapshot){
  const u=new URL(snapshot.url);
  return u.origin==='https://careers.cisco.com'?u.pathname.match(/^\/global\/en\/job\/(\d+)\//)?.[1]:undefined;
}

