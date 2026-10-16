import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

test("official MCP v2 stdio initializes, lists schemas and calls a harmless tool", async () => {
  const child = spawn(
    process.execPath,
    ["--import", "tsx", "test/stdio-fixture.ts"],
    { stdio: ["pipe", "pipe", "pipe"] },
  );
  const responses = new Map<number, any>();
  const waits = new Map<number, (v: any) => void>();
  let stderr = "";
  child.stderr.on("data", (d) => (stderr += d));
  const lines = createInterface({ input: child.stdout });
  lines.on("line", (line) => {
    const r = JSON.parse(line);
    responses.set(r.id, r);
    waits.get(r.id)?.(r);
  });
  const receive = (id: number) =>
    new Promise<any>((resolve, reject) => {
      if (responses.has(id)) {
        resolve(responses.get(id));
        return;
      }
      const timer = setTimeout(
        () => reject(new Error("MCP timeout: " + stderr)),
        5000,
      );
      waits.set(id, (r) => {
        clearTimeout(timer);
        resolve(r);
      });
    });
  const send = (value: unknown) =>
    child.stdin.write(JSON.stringify(value) + "\n");
  try {
    send({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "local-test", version: "1" },
      },
    });
    const init = await receive(1);
    assert.equal(
      init.result.serverInfo.name,
      "resume-studio-chrome-applications",
    );
    send({ jsonrpc: "2.0", method: "notifications/initialized" });
    send({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
    const list = await receive(2);
    assert.ok(
      list.result.tools.find((t: any) => t.name === "submit_application")
        .outputSchema,
    );
    assert.ok(
      list.result.tools.find((t: any) => t.name === "submit_application")
        .inputSchema.properties.userSaidYes,
    );
    send({
      jsonrpc: "2.0",
      id: 3,
      method: "tools/call",
      params: {
        name: "detect_ats",
        arguments: { url: "https://jobs.lever.co/example/123" },
      },
    });
    const result = await receive(3);
    assert.equal(result.result.structuredContent.result.ats, "lever");
    assert.equal(result.result.isError, undefined);
    send({
      jsonrpc: "2.0",
      id: 4,
      method: "tools/call",
      params: { name: "get_application_history", arguments: {} },
    });
    assert.deepEqual((await receive(4)).result.structuredContent.result, []);
  } finally {
    child.kill();
    lines.close();
  }
});
