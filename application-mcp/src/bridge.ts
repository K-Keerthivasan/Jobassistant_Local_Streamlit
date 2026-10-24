import { randomUUID } from "node:crypto";
import type { WebSocket } from "ws";

export interface Browser {
  extensionVersion?:string;
  command(op: string, args: Record<string, unknown>): Promise<unknown>;
  notify?(payload:Record<string,unknown>):boolean;
}
/** The extension version this service expects (extension/manifest.json). When
 * Chrome runs an older one, page-reading fixes don't apply until it's reloaded. */
export const EXPECTED_EXTENSION_VERSION = "0.3.8";

export class ChromeBridge implements Browser {
  socket?: WebSocket;
  /** Version the connected extension reported; "" until it answers a ping. */
  extensionVersion = "";
  pending = new Map<
    string,
    {
      resolve: (v: unknown) => void;
      reject: (e: Error) => void;
      timer: NodeJS.Timeout;
    }
  >();
  connect(socket: WebSocket) {
    if (this.socket?.readyState === 1) {
      socket.close(1008, "One Chrome profile only");
      return;
    }
    this.socket = socket;
    this.extensionVersion = "";
    // Learn the extension's version as soon as it connects.
    setTimeout(() => void this.refreshVersion(), 0);
    socket.on("message", (raw) => {
      try {
        const data = JSON.parse(raw.toString());
        const p = this.pending.get(data.id);
        if (!p) return;
        clearTimeout(p.timer);
        this.pending.delete(data.id);
        data.error
          ? p.reject(new Error(String(data.error)))
          : p.resolve(data.result);
      } catch {
        socket.close(1008, "Invalid response");
      }
    });
    socket.on("close", () => {
      if (this.socket === socket) this.socket = undefined;
      for (const p of this.pending.values()) {
        clearTimeout(p.timer);
        p.reject(new Error("Chrome disconnected; resume after reconnecting."));
      }
      this.pending.clear();
    });
  }
  async refreshVersion() {
    try {
      const r = (await this.command("ping", {})) as { version?: string };
      this.extensionVersion = r?.version || "unknown (before 0.3.0)";
    } catch {
      /* Disconnected; the next connection asks again. */
    }
  }
  /** Fire-and-forget desktop notification through the extension. Returns
   * false when Chrome is not connected; never throws. */
  notify(payload: Record<string, unknown>): boolean {
    if (!this.socket || this.socket.readyState !== 1) return false;
    try {
      this.socket.send(
        JSON.stringify({ id: randomUUID(), op: "notify", args: payload }),
      );
      return true;
    } catch {
      return false;
    }
  }
  command(op: string, args: Record<string, unknown>): Promise<unknown> {
    if (!this.socket || this.socket.readyState !== 1)
      return Promise.reject(
        new Error(
          "Open regular Chrome and connect the Resume Studio extension.",
        ),
      );
    return new Promise((resolve, reject) => {
      const id = randomUUID();
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("Chrome command timed out; inspect before retrying."));
      }, 30000);
      this.pending.set(id, { resolve, reject, timer });
      this.socket!.send(JSON.stringify({ id, op, args }));
    });
  }
}
