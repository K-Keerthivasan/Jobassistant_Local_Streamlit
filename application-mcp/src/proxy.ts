/** Stdio clients share the single running Chrome service rather than starting rival instances. */
import { McpServer } from "@modelcontextprotocol/server";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { z } from "zod";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import path from "node:path";

const base = "http://127.0.0.1:8091";
async function request(route: string, body?: unknown) {
  const response = await fetch(base + route, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    redirect: "error",
    signal: AbortSignal.timeout(45000),
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      value.error || `Application service error ${response.status}`,
    );
  return value;
}
try {
  await request("/health");
} catch {
  const root = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
  await promisify(execFile)(
    "powershell.exe",
    [
      "-NoProfile",
      "-File",
      path.join(root, "tools/start_application_services.ps1"),
    ],
    { cwd: root, windowsHide: true, timeout: 45000 },
  );
}
const catalog = z
  .array(
    z.object({
      name: z.string(),
      description: z.string(),
      inputSchema: z.record(z.string(), z.unknown()),
      outputSchema: z.record(z.string(), z.unknown()),
      annotations: z.object({
        readOnlyHint: z.boolean(),
        destructiveHint: z.boolean(),
        openWorldHint: z.boolean(),
      }),
    }),
  )
  .parse(await request("/mcp-tools"));
const mcp = new McpServer(
  { name: "resume-studio-chrome-applications", version: "0.1.0" },
  {
    instructions:
      "Use the main regular Chrome profile only, one application at a time. Fill only verified facts. Pause for login, CAPTCHA, consent, demographics and missing facts. Show the complete review and ask: Submit this exact application: yes or no? Require a fresh user yes and Studio permission before submission. Never retry an uncertain submission.",
  },
);
for (const tool of catalog) {
  const output = z.fromJSONSchema(tool.outputSchema);
  mcp.registerTool(
    tool.name,
    {
      description: tool.description,
      inputSchema: z.fromJSONSchema(tool.inputSchema),
      outputSchema: output,
      annotations: tool.annotations,
    },
    async (args: unknown) => {
      try {
        const value = output.parse({
          result: await request("/tools/" + tool.name, args),
        }) as Record<string, unknown>;
        return {
          content: [{ type: "text" as const, text: JSON.stringify(value) }],
          structuredContent: value,
        };
      } catch (error) {
        return {
          isError: true,
          content: [{ type: "text" as const, text: (error as Error).message }],
        };
      }
    },
  );
}
await mcp.connect(new StdioServerTransport());
