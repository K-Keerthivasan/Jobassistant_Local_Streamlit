import path from "node:path";
import { fileURLToPath } from "node:url";
import { mkdir, open, readFile, unlink } from "node:fs/promises";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { Store } from "./store.js";
import { ChromeBridge } from "./bridge.js";
import { payloadFor, shouldNotify } from "./notify.js";
import { Service } from "./service.js";
import { Studio } from "./studio.js";
import { makeMcp } from "./tools.js";
import { httpServer } from "./http.js";

const root = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
let configuredExtensionId = process.env.APP_CHROME_EXTENSION_ID || "";
if (!configuredExtensionId) {
  try {
    const local = JSON.parse(
      await readFile(
        path.join(root, "application-mcp/config/local.json"),
        "utf8",
      ),
    );
    configuredExtensionId = local.chromeExtensionId || "";
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}
if (!/^[a-p]{32}$/.test(configuredExtensionId))
  throw new Error(
    "Configure the installed Chrome extension ID in application-mcp/config/local.json.",
  );
const data = path.join(root, "data/job-applications/engine");
await mkdir(data, { recursive: true });
const lockPath = path.join(data, "service.lock");
async function lock() {
  try {
    const file = await open(lockPath, "wx");
    await file.writeFile(String(process.pid));
    await file.close();
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
    const pid = Number(await readFile(lockPath, "utf8"));
    if (!Number.isInteger(pid) || pid <= 0)
      throw new Error(
        "Invalid engine service.lock; inspect it before restarting.",
      );
    try {
      process.kill(pid, 0);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ESRCH") {
        await unlink(lockPath);
        return lock();
      }
      throw error;
    }
    throw new Error(
      "An application service is already running. Use that instance or stop it before starting another.",
    );
  }
}
await lock();
const store = new Store(path.join(data, "applications.sqlite"));
const bridge = new ChromeBridge();
// One desktop notification per barrier change, for the kinds switched on in
// the dashboard's notification settings.
store.onSave = (previous, next) => {
  const barrier = shouldNotify(previous, next, store.notifySettings());
  if (barrier) bridge.notify({ ...payloadFor(next, barrier) });
};
const service = new Service(store, bridge, new Studio(), root, [
  path.join(root, "data/job-applications"),
]);
const server = httpServer(service, bridge, configuredExtensionId);
server.on("error", async () => {
  process.stderr.write(
    "Application service could not bind port 8091. Stop the existing instance before starting another.\n",
  );
  await unlink(lockPath);
  process.exit(1);
});
server.listen(8091, "127.0.0.1", () =>
  process.stderr.write(
    JSON.stringify({
      event: "ready",
      dashboard: "http://127.0.0.1:8091",
      chromeConfigured: !!configuredExtensionId,
    }) + "\n",
  ),
);
if (process.argv.includes("--stdio"))
  await makeMcp(service).connect(new StdioServerTransport());
const shutdown = async () => {
  bridge.socket?.close();
  server.close();
  store.db.close();
  await unlink(lockPath);
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
