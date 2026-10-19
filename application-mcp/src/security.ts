import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import { realpath, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";

export function publicAddress(ip: string): boolean {
  if (isIP(ip) === 4) {
    const [a, b] = ip.split(".").map(Number);
    return !(
      a === 0 ||
      a === 10 ||
      a === 127 ||
      a >= 224 ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 198 && (b === 18 || b === 19))
    );
  }
  // Only globally routable IPv6 unicast. Reject mapped IPv4 and special ranges.
  return (
    isIP(ip) === 6 &&
    /^[23]/i.test(ip) &&
    !ip.toLowerCase().startsWith("2001:db8")
  );
}
export async function safeUrl(value: string, domains?: string[]) {
  const u = new URL(value);
  if (
    u.protocol !== "https:" ||
    u.username ||
    u.password ||
    (u.port && u.port !== "443")
  )
    throw new Error(
      "Employer URLs must use HTTPS without credentials or custom ports.",
    );
  if (domains && !domains.includes(u.hostname))
    throw new Error(`New domain requires approval: ${u.hostname}`);
  const addresses = await lookup(u.hostname, { all: true });
  if (!addresses.length || addresses.some((a) => !publicAddress(a.address)))
    throw new Error("Private network destination refused.");
  return u;
}
export async function documentInfo(file: string, roots: string[]) {
  const resolved = await realpath(file);
  const approved = await Promise.all(roots.map((r) => realpath(r)));
  if (
    !approved.some((root) => {
      const rel = path.relative(root, resolved);
      return rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel);
    })
  )
    throw new Error("Document is outside approved upload directories.");
  if (
    ![".pdf", ".doc", ".docx", ".txt"].includes(
      path.extname(resolved).toLowerCase(),
    )
  )
    throw new Error("Unsupported document type.");
  const info = await stat(resolved);
  if (!info.isFile() || info.size === 0 || info.size > 20 * 1024 * 1024)
    throw new Error("Document must be a nonempty file under 20 MB.");
  return {
    path: resolved,
    hash: createHash("sha256")
      .update(await readFile(resolved))
      .digest("hex"),
    name: path.basename(resolved),
  };
}
export const digest = (value: unknown) =>
  createHash("sha256").update(JSON.stringify(value)).digest("hex");

/** Translate only a validated local artifact beneath the shared workspace. */
export function chromeDocumentPath(file: string, root: string, windowsRoot?: string) {
  if (!windowsRoot) return file;
  if (!/^[A-Za-z]:[\\/]/.test(windowsRoot)) throw new Error('Windows workspace must be an absolute drive path.');
  const relative = path.relative(path.join(root, 'data/job-applications'), file);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Upload is outside the shared application directory.');
  return path.win32.join(windowsRoot, 'data', 'job-applications', ...relative.split(path.sep));
}

export function containerDocumentPath(file: string, root: string, windowsRoot?: string) {
  if (!windowsRoot || !path.win32.isAbsolute(file) || file.startsWith('/')) return file;
  const relative = path.win32.relative(path.win32.join(windowsRoot, 'data/job-applications'), file);
  if (!relative || relative.startsWith('..') || path.win32.isAbsolute(relative)) throw new Error('Stored document is outside the shared application directory.');
  return path.join(root, 'data/job-applications', ...relative.split(path.win32.sep));
}
export const normalize = (s: string) =>
  s.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
export const sensitive = (s: string) =>
  /password|passcode|one.time|verification.code|captcha|consent|agree|certify|attest|privacy|terms|marketing|sms|talent.pool|disabilit|veteran|gender|race|ethnic|sexual|pronoun|demographic|aboriginal|indigenous|religion|date.of.birth/i.test(
    s,
  );
