import { createServer, type IncomingMessage } from "node:http";
import { readFile, realpath } from "node:fs/promises";
import path from "node:path";
import { WebSocketServer } from "ws";
import { z } from "zod";
import { toolset } from "./tools.js";
import { outputSchema } from "./schema.js";
import { BARRIERS } from "./notify.js";
import type { Service } from "./service.js";
import type { ChromeBridge } from "./bridge.js";

async function body(req: IncomingMessage) {
  if (req.headers["content-type"]?.split(";")[0] !== "application/json")
    throw new Error("Content-Type application/json required.");
  let data = "";
  for await (const chunk of req) {
    data += chunk;
    if (data.length > 1024 * 1024) throw new Error("Request too large.");
  }
  return JSON.parse(data || "{}");
}
export function httpServer(
  s: Service,
  bridge: ChromeBridge,
  extensionId: string,
  port = 8091,
) {
  const origin = `http://127.0.0.1:${port}`;
  const tools = toolset(s);
  const server = createServer(async (req, res) => {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader(
      "Content-Security-Policy",
      "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    );
    const json = (value: unknown, status = 200) => {
      res.statusCode = status;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(value));
    };
    if (
      req.headers.host !== `127.0.0.1:${port}` ||
      (req.headers.origin && req.headers.origin !== origin)
    ) {
      json({ error: "Host or Origin refused." }, 403);
      return;
    }
    try {
      const u = new URL(req.url || "/", origin);
      if (req.method === "GET" && ["/", "/dashboard.js"].includes(u.pathname)) {
        res.setHeader(
          "Content-Type",
          u.pathname === "/"
            ? "text/html; charset=utf-8"
            : "text/javascript; charset=utf-8",
        );
        res.end(
          await readFile(
            new URL(
              "../public/" +
                (u.pathname === "/" ? "index.html" : "dashboard.js"),
              import.meta.url,
            ),
          ),
        );
        return;
      }
      if (req.method === "GET" && u.pathname === "/health") {
        json({
          running: s.running || null,
          ok: true,
          chromeConnected: bridge.socket?.readyState === 1,
          extensionConfigured: !!extensionId,
          stopped: s.stopped,
        });
        return;
      }
      if (req.method === "GET" && u.pathname === "/applications") {
        json(s.store.list());
        return;
      }
      if (req.method === "GET" && u.pathname === "/mcp-tools") {
        json(
          Object.entries(tools).map(([name, tool]) => ({
            name,
            description: tool.description,
            inputSchema: z.toJSONSchema(tool.schema, { io: "input" }),
            outputSchema: z.toJSONSchema(outputSchema(name)),
            annotations: {
              readOnlyHint: /^(get_|detect_)/.test(name),
              destructiveHint: name === "submit_application",
              openWorldHint: !name.startsWith("get_"),
            },
          })),
        );
        return;
      }
      if (req.method === "GET" && u.pathname === "/candidates") {
        const since = new Date(Date.now() - 7 * 86400000)
          .toISOString()
          .slice(0, 10);
        json(await s.studio.request("/apply/candidates?since=" + since));
        return;
      }
      if (req.method === "POST" && u.pathname === "/prepare") {
        const input = z
          .object({ job_key: z.string(), run_id: z.string() })
          .parse(await body(req));
        json(await s.studio.request("/application-engine/prepare", input));
        return;
      }
      if (req.method === "POST" && u.pathname === "/applications") {
        json(await s.apply(await body(req)), 201);
        return;
      }
      const evidenceMatch = u.pathname.match(
        /^\/applications\/([^/]+)\/evidence\/(\d+)$/,
      );
      if (req.method === "GET" && evidenceMatch) {
        const a = s.store.get(decodeURIComponent(evidenceMatch[1]));
        const evidence = a.evidence?.[Number(evidenceMatch[2])];
        if (!evidence) throw new Error("Evidence not found.");
        const file = await realpath(evidence.path);
        const root = await realpath(
          path.join(s.root, "data/job-applications/engine/evidence", a.id),
        );
        const relative = path.relative(root, file);
        if (
          relative.startsWith("..") ||
          path.isAbsolute(relative) ||
          path.extname(file) !== ".png"
        )
          throw new Error("Evidence path refused.");
        res.setHeader("Content-Type", "image/png");
        res.end(await readFile(file));
        return;
      }
      const match = u.pathname.match(
        /^\/applications\/([^/]+)(?:\/(history|required-action|resume|approval|cancel|run|stop-run))?$/,
      );
      if (match) {
        const id = decodeURIComponent(match[1]);
        const action = match[2];
        if (req.method === "GET") {
          const a = s.store.get(id);
          json(
            action === "history"
              ? { application: a, events: s.store.history(id) }
              : action === "required-action"
                ? { state: a.state, action: a.reason }
                : a,
          );
          return;
        }
        if (req.method === "POST" && action === "run") {
          await body(req);
          json(s.startRun(id));
          return;
        }
        if (req.method === "POST" && action === "stop-run") {
          await body(req);
          json(s.stopRun());
          return;
        }
        if (req.method === "POST" && ["resume", "cancel"].includes(action)) {
          await body(req);
          json(await (action === "resume" ? s.resume(id) : s.cancel(id)));
          return;
        }
        if (req.method === "POST" && action === "approval") {
          const v = z
            .object({
              reviewHash: z.string(),
              userSaidYes: z.literal(true),
              selector: z.string(),
              frameId: z.number().default(0),
            })
            .parse(await body(req));
          json(
            await s.submit(
              id,
              v.reviewHash,
              v.userSaidYes,
              v.selector,
              v.frameId,
            ),
          );
          return;
        }
      }
      if (u.pathname === "/notifications" && req.method === "GET") {
        json({ barriers: BARRIERS, settings: s.store.notifySettings() });
        return;
      }
      if (u.pathname === "/notifications" && req.method === "POST") {
        const update = z.record(z.string(), z.boolean()).parse(await body(req));
        json({ barriers: BARRIERS, settings: s.store.notifySettings(update) });
        return;
      }
      if (u.pathname === "/notifications/test" && req.method === "POST") {
        await body(req);
        const sent = bridge.notify({
          applicationId: "",
          barrier: "other",
          title: "Resume Studio notifications are on",
          message: "You will see one of these at each application barrier you switched on.",
        });
        json({ sent }, sent ? 200 : 409);
        return;
      }
      const toolMatch = u.pathname.match(/^\/tools\/([a-z_]+)$/);
      if (req.method === "POST" && toolMatch && toolMatch[1] in tools) {
        const tool = tools[toolMatch[1] as keyof typeof tools];
        const value = tool.schema.parse(await body(req));
        json(await tool.run(value as any));
        return;
      }
      json({ error: "Not found" }, 404);
    } catch (e) {
      json({ error: (e as Error).message }, 400);
    }
  });
  const wss = new WebSocketServer({
    noServer: true,
    maxPayload: 8 * 1024 * 1024,
  });
  server.on("upgrade", (req, socket, head) => {
    if (
      !/^[a-p]{32}$/.test(extensionId) ||
      req.url !== "/bridge" ||
      req.headers.host !== `127.0.0.1:${port}` ||
      req.headers.origin !== `chrome-extension://${extensionId}`
    ) {
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => bridge.connect(ws));
  });
  const heartbeat = setInterval(() => {
    if (bridge.socket?.readyState === 1)
      bridge.command("ping", {}).catch(() => {});
  }, 20000);
  heartbeat.unref();
  server.on("close", () => {
    clearInterval(heartbeat);
    wss.close();
  });
  return server;
}
