import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { Store } from "../src/store.js";
import { Service } from "../src/service.js";
import { Studio } from "../src/studio.js";
import { makeMcp } from "../src/tools.js";
const store = new Store(":memory:");
const service = new Service(
  store,
  {
    command: async () => {
      throw new Error("No browser in protocol-only test.");
    },
  },
  new Studio(),
  ".",
  [],
);
await makeMcp(service).connect(new StdioServerTransport());
