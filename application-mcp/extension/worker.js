import { domTask } from "./dom.js";

let socket;
let busy = false;
let session;
const ready = chrome.storage.session.get("session").then((data) => {
  session = data.session;
});
const store = () => chrome.storage.session.set({ session });
function permitted(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && session?.domains.includes(u.hostname);
  } catch {
    return false;
  }
}
chrome.tabs.onCreated.addListener(async (tab) => {
  await ready;
  if (session && tab.openerTabId === session.tabId && tab.id) {
    const previous = session.tabId;
    session.tabId = tab.id;
    await store();
    session.ownedTabs ||= [];
    session.ownedTabs.push(tab.id);
    await store();
    try {
      const loaded = await tabReady(tab.id);
      if (
        permitted(loaded.url) &&
        session?.tabId === tab.id &&
        session.ownedTabs.includes(previous)
      )
        await chrome.tabs.remove(previous);
    } catch {
      /* Leave login and blocked tabs open for manual takeover. */
    }
  }
});
async function tabReady(id) {
  const end = Date.now() + 15000;
  while (Date.now() < end) {
    const tab = await chrome.tabs.get(id);
    if (tab.status === "complete" && tab.url !== "about:blank") return tab;
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error("Page still loading; inspect again after it finishes.");
}
async function command(op, args) {
  await ready;
  if (op === "open") {
    const prior = (await chrome.storage.session.get("lastManagedTab"))
      .lastManagedTab;
    session = {
      applicationId: args.applicationId,
      domains: args.domains,
      ownedTabs: [],
    };
    let tab;
    if (prior) {
      try {
        const existing = await chrome.tabs.get(prior.id);
        if (existing.url === prior.url)
          tab = await chrome.tabs.update(prior.id, {
            url: args.url,
            active: true,
          });
      } catch {
        /* Closed by user. */
      }
    }
    if (!tab) tab = await chrome.tabs.create({ url: args.url, active: true });
    session.tabId = tab.id;
    session.ownedTabs = [tab.id];
    await chrome.storage.session.remove("lastManagedTab");
    await store();
    await tabReady(tab.id);
    return { tabId: tab.id };
  }
  if (!session || session.applicationId !== args.applicationId)
    throw new Error(
      "No matching application tab. Use Adopt current tab in the extension.",
    );
  session.domains = args.domains;
  await store();
  if (op === "finish") {
    const tab = await chrome.tabs.get(session.tabId);
    if (session.ownedTabs?.includes(tab.id))
      await chrome.storage.session.set({
        lastManagedTab: { id: tab.id, url: tab.url },
      });
    session = undefined;
    await chrome.storage.session.remove("session");
    return { released: true };
  }
  const tab = await tabReady(session.tabId);
  if (!permitted(tab.url))
    throw new Error(
      "New domain: approve the exact employer domain, or complete login manually, then resume.",
    );
  if (op === "screenshot") {
    const checks = await chrome.scripting.executeScript({
      target: { tabId: session.tabId, allFrames: true },
      func: domTask,
      args: [{ op: "scan" }],
    });
    if (checks.some((r) => r.result?.blockers.length))
      throw new Error(
        "Evidence capture refused while login or verification is visible.",
      );
    const target = { tabId: session.tabId };
    await chrome.debugger.attach(target, "1.3");
    try {
      return await chrome.debugger.sendCommand(
        target,
        "Page.captureScreenshot",
        { format: "png", captureBeyondViewport: false },
      );
    } finally {
      await chrome.debugger.detach(target);
    }
  }
  if (op === "scan") {
    const frames = await chrome.webNavigation.getAllFrames({
      tabId: session.tabId,
    });
    const results = [];
    const blockers = [];
    for (const frame of frames) {
      if (!permitted(frame.url)) {
        if (/captcha|recaptcha|hcaptcha/i.test(frame.url))
          blockers.push("CAPTCHA: complete it in Chrome.");
        continue;
      }
      const [r] = await chrome.scripting.executeScript({
        target: { tabId: session.tabId, frameIds: [frame.frameId] },
        func: domTask,
        args: [{ op: "scan" }],
      });
      if (r?.result) {
        r.result.fields.forEach((f) => (f.frameId = frame.frameId));
        r.result.buttons.forEach((b) => (b.frameId = frame.frameId));
        results.push(r.result);
      }
    }
    const top = results[0];
    if (!top) throw new Error("Page could not be inspected.");
    return {
      ...top,
      url: tab.url,
      fields: results.flatMap((r) => r.fields),
      buttons: results.flatMap((r) => r.buttons),
      blockers: [...blockers, ...results.flatMap((r) => r.blockers)],
      confirmation: results.find((r) => r.confirmation)?.confirmation || "",
    };
  }
  const frame = await chrome.webNavigation.getFrame({
    tabId: session.tabId,
    frameId: args.frameId || 0,
  });
  if (!frame || !permitted(frame.url))
    throw new Error("Unapproved frame destination.");
  if (op === "upload") {
    // chrome.debugger operates on the selected regular-profile tab only. No cookies or credentials are read.
    // Cross-origin iframe uploads are deliberately manual until a tested debugger target adapter exists.
    if (args.frameId)
      throw new Error(
        "Upload in an iframe requires manual file selection in Chrome.",
      );
    const target = { tabId: session.tabId };
    await chrome.debugger.attach(target, "1.3");
    try {
      const evaluation = await chrome.debugger.sendCommand(
        target,
        "Runtime.evaluate",
        {
          expression: `document.querySelector(${JSON.stringify(args.selector)})`,
          objectGroup: "resume-studio",
        },
      );
      if (!evaluation.result?.objectId)
        throw new Error("File input disappeared.");
      const node = await chrome.debugger.sendCommand(
        target,
        "DOM.describeNode",
        { objectId: evaluation.result.objectId },
      );
      const attributes = node.node.attributes || [];
      if (
        node.node.nodeName !== "INPUT" ||
        !attributes.some((v, i) => v === "type" && attributes[i + 1] === "file")
      )
        throw new Error("Upload target is not a file input.");
      await chrome.debugger.sendCommand(target, "DOM.setFileInputFiles", {
        objectId: evaluation.result.objectId,
        files: [args.path],
      });
    } finally {
      await chrome.debugger.detach(target);
    }
    return { uploaded: true };
  }
  if (!["fill", "click"].includes(op))
    throw new Error("Unknown bridge command.");
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: session.tabId, frameIds: [args.frameId || 0] },
    func: domTask,
    args: [{ ...args, op }],
  });
  if (op === "click") await new Promise((r) => setTimeout(r, 600));
  return result.result;
}
function connect() {
  if (socket && [0, 1].includes(socket.readyState)) return;
  socket = new WebSocket("ws://127.0.0.1:8091/bridge");
  socket.onmessage = async (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
      if (data.op === "ping") {
        socket.send(JSON.stringify({ id: data.id, result: { alive: true } }));
        return;
      }
      if (busy) throw new Error("A browser operation is already running.");
      busy = true;
      const result = await command(data.op, data.args);
      socket.send(JSON.stringify({ id: data.id, result }));
    } catch (e) {
      if (data?.id && socket.readyState === 1)
        socket.send(JSON.stringify({ id: data.id, error: e.message }));
    } finally {
      busy = false;
    }
  };
}
chrome.runtime.onMessage.addListener((message, _sender, respond) => {
  (async () => {
    await ready;
    if (message.op === "connect") connect();
    if (message.op === "adopt") {
      if (!message.applicationId)
        throw new Error("Enter the active application ID from the dashboard.");
      const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });
      if (!tab?.url?.startsWith("https://"))
        throw new Error("Select the employer application tab first.");
      session = {
        applicationId: message.applicationId,
        tabId: tab.id,
        domains: [],
      };
      await store();
    }
    return {
      id: chrome.runtime.id,
      connected: socket?.readyState === 1,
      session,
    };
  })().then(respond, (e) => respond({ error: e.message }));
  return true;
});
chrome.alarms.create("reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => connect());
connect();
