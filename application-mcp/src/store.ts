import Database from "better-sqlite3";
import type { Application } from "./schema.js";
import { defaultSettings, type NotifySettings } from "./notify.js";

/** Called after every save with the previous state and reason (undefined for a new application). */
export type SaveListener = (
  previous: Pick<Application, "state" | "reason"> | undefined,
  next: Application,
) => void;

export class Store {
  db: Database.Database;
  onSave?: SaveListener;
  constructor(file: string) {
    this.db = new Database(file);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("busy_timeout = 5000");
    this.db
      .exec(`CREATE TABLE IF NOT EXISTS applications (id TEXT PRIMARY KEY, url TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL);
      CREATE UNIQUE INDEX IF NOT EXISTS active_url ON applications(url) WHERE state NOT IN ('failed','rejected');
      CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, application_id TEXT, at TEXT, kind TEXT, data TEXT);
      CREATE TABLE IF NOT EXISTS templates (host TEXT PRIMARY KEY, data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS site_mappings (host TEXT NOT NULL, label TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(host,label));
      CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS migrations (version INTEGER PRIMARY KEY);
      INSERT OR IGNORE INTO migrations VALUES (1);`);
    // Never replay a click after a crash. Require investigation of its visible result.
    for (const a of this.list()) {
      if (a.state === "submitting")
        this.save({
          ...a,
          state: "uncertain",
          reason: "Restart during submission; inspect before any retry.",
        });
      else if (["opening", "working", "review"].includes(a.state))
        this.save({
          ...a,
          state: "paused",
          approvedHash: undefined,
          reason:
            "Service restarted; resume and inspect the current Chrome tab.",
        });
    }
  }
  save(a: Application) {
    const prior = this.db
      .prepare("SELECT data FROM applications WHERE id=?")
      .get(a.id) as { data: string } | undefined;
    const previous = prior ? (JSON.parse(prior.data) as Application) : undefined;
    a.updatedAt = new Date().toISOString();
    this.db
      .prepare(
        "INSERT INTO applications VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data",
      )
      .run(a.id, a.input.jobUrl, a.state, JSON.stringify(a));
    try {
      this.onSave?.(
        previous && { state: previous.state, reason: previous.reason },
        a,
      );
    } catch {
      /* A notification problem must never block saving an application. */
    }
    return a;
  }
  notifySettings(update?: Partial<NotifySettings>): NotifySettings {
    const row = this.db
      .prepare("SELECT data FROM settings WHERE key='notifications'")
      .get() as { data: string } | undefined;
    const current = { ...defaultSettings(), ...(row ? JSON.parse(row.data) : {}) };
    if (update) {
      for (const [k, v] of Object.entries(update))
        if (k in current && typeof v === "boolean") (current as any)[k] = v;
      this.db
        .prepare(
          "INSERT INTO settings VALUES ('notifications',?) ON CONFLICT(key) DO UPDATE SET data=excluded.data",
        )
        .run(JSON.stringify(current));
    }
    return current;
  }
  get(id: string): Application {
    const row = this.db
      .prepare("SELECT data FROM applications WHERE id=?")
      .get(id) as { data: string } | undefined;
    if (!row) throw new Error("Application not found.");
    return JSON.parse(row.data);
  }
  list(): Application[] {
    return (
      this.db
        .prepare("SELECT data FROM applications ORDER BY rowid DESC")
        .all() as { data: string }[]
    ).map((r) => JSON.parse(r.data));
  }
  event(id: string, kind: string, data: unknown = {}) {
    this.db
      .prepare(
        "INSERT INTO events(application_id,at,kind,data) VALUES (?,?,?,?)",
      )
      .run(id, new Date().toISOString(), kind, JSON.stringify(data));
  }
  history(id: string) {
    return this.db
      .prepare(
        "SELECT at,kind,data FROM events WHERE application_id=? ORDER BY id",
      )
      .all(id);
  }
  mappings(
    host: string,
  ): { label: string; type: string; options: string[]; profilePath: string }[] {
    return (
      this.db
        .prepare("SELECT data FROM site_mappings WHERE host=?")
        .all(host) as { data: string }[]
    ).map((r) => JSON.parse(r.data));
  }
  saveMapping(
    host: string,
    mapping: {
      label: string;
      type: string;
      options: string[];
      profilePath: string;
    },
  ) {
    this.db
      .prepare(
        "INSERT INTO site_mappings VALUES (?,?,?) ON CONFLICT(host,label) DO UPDATE SET data=excluded.data",
      )
      .run(host, mapping.label, JSON.stringify(mapping));
  }
  template(host: string, data?: unknown): unknown {
    if (data)
      this.db
        .prepare(
          "INSERT INTO templates VALUES (?,?) ON CONFLICT(host) DO UPDATE SET data=excluded.data",
        )
        .run(host, JSON.stringify(data));
    const row = this.db
      .prepare("SELECT data FROM templates WHERE host=?")
      .get(host) as { data: string } | undefined;
    return row ? JSON.parse(row.data) : null;
  }
}
