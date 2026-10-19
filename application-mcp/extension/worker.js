import { domTask } from "./dom.js";
import {
  readRecaptchaIndicator,
  trustedRecaptchaFrame,
  recaptchaAnchor,
} from "./verification.js";

let socket;
let busy = false;
let session;
const ready = chrome.storage.session.get("session").then((data) => {
  session = data.session;
});
const store = async () => {
  await chrome.storage.session.set({ session });
  await chrome.storage.local.set({
    applicationTab: session ? { ...session, savedAt: Date.now() } : null,
  });
};
async function restoreApplicationTab() {
  await ready;
  if (session) return;
  const saved = (await chrome.storage.local.get("applicationTab"))
    .applicationTab;
  if (!saved || Date.now() - saved.savedAt > 24 * 60 * 60 * 1000) return;
  try {
    const tab = await chrome.tabs.get(saved.tabId);
    const url = new URL(tab.url);
    if (url.protocol === "https:" && saved.domains.includes(url.hostname)) {
      session = saved;
      await chrome.storage.session.set({ session });
    }
  } catch {
    /* A closed tab is never replaced with another user's tab. */
  }
}
async function verificationStatus(frames) {
  const anchors = frames.filter((f) => recaptchaAnchor(f.url));
  if (!anchors.length) return false;
  if (
    frames.some((f) => /captcha/i.test(f.url) && !trustedRecaptchaFrame(f.url))
  )
    return false;
  for (const frame of anchors) {
    try {
      const [r] = await chrome.scripting.executeScript({
        target: { tabId: session.tabId, frameIds: [frame.frameId] },
        func: readRecaptchaIndicator,
      });
      if (!r?.result?.checked || r.result.error) return false;
    } catch {
      return false;
    }
  }
  return true;
}
function permitted(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && session?.domains.includes(u.hostname);
  } catch {
    return false;
  }
}
// Indeed's apply site embeds parts of its pages from other indeed.com hosts.
// Those frames are read (never navigated) while the application is on Indeed.
function indeedFrame(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && /(^|\.)indeed\.com$/.test(u.hostname) &&
      session?.domains.includes("smartapply.indeed.com");
  } catch {
    return false;
  }
}
chrome.tabs.onCreated.addListener(async (tab) => {
  await ready;
  if (session && tab.openerTabId === session.tabId && tab.id) {
    const previous = session.tabId;
    try {
      const loaded = await tabReady(tab.id);
      // Extension review UI and local dashboards must never become an employer tab.
      if (!loaded.url?.startsWith("https:") || session?.tabId !== previous) return;
      session.tabId = tab.id;
      session.ownedTabs ||= [];
      session.ownedTabs.push(tab.id);
      await store();
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
  await restoreApplicationTab();
  if(op==='restart'){
    const url=new URL(args.url);
    if(url.protocol!=='https:' || !args.domains.includes(url.hostname))throw new Error('Restart destination is not approved.');
    if(session && session.applicationId!==args.applicationId)throw new Error('A different application owns the Chrome tab; save it first.');
    let tab;
    if(session?.tabId){try{tab=await chrome.tabs.get(session.tabId);}catch{/* Closed tab: create the replacement below. */}}
    if(!tab)return command('open',args);
    await chrome.tabs.update(tab.id,{url:url.href,active:true});
    session={applicationId:args.applicationId,tabId:tab.id,domains:args.domains,ownedTabs:session.ownedTabs || []};
    await store();await tabReady(tab.id);return {restarted:true};
  }
  if (op === "recover") {
    if (session && session.applicationId !== args.applicationId)
      throw new Error("A different application owns the Chrome tab; defer it first.");
    const expected = new URL(args.url);
    if (expected.protocol !== "https:" || !args.domains.includes(expected.hostname))
      throw new Error("Recovery destination is not an approved employer URL.");
    const matches = (await chrome.tabs.query({})).filter(tab => tab.url === expected.href);
    if (matches.length > 1) throw new Error("Multiple matching application tabs; choose the intended tab before recovery.");
    if (matches.length === 1) {
      session = { applicationId: args.applicationId, tabId: matches[0].id, domains: args.domains, ownedTabs: [] };
      await store();
      await chrome.tabs.update(session.tabId, { active: true });
      return { recovered: true };
    }
    return command("open", args);
  }
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
    if (args.closeCompleted && permitted(tab.url)) {
      const tabs = await chrome.tabs.query({});
      const main = tabs.find(t => /^http:\/\/127\.0\.0\.1:8088\/?(?:[?#]|$)/.test(t.url || ''));
      if (main) await chrome.tabs.update(main.id, { active: true });
      else await chrome.tabs.create({ url: 'http://127.0.0.1:8088/', active: true });
      await chrome.tabs.remove(tab.id);
      await chrome.storage.session.remove('lastManagedTab');
    } else if (session.ownedTabs?.includes(tab.id))
      await chrome.storage.session.set({
        lastManagedTab: { id: tab.id, url: tab.url },
      });
    session = undefined;
    await chrome.storage.session.remove("session");
    await chrome.storage.local.remove("applicationTab");
    return { released: true };
  }
  const tab = await tabReady(session.tabId);
  if (!permitted(tab.url)) {
    let host = "";
    try {
      host = new URL(tab.url).hostname;
    } catch {
      /* not a URL */
    }
    throw new Error(
      `New domain (${host}): approve the exact employer domain, or complete login manually, then resume.`,
    );
  }
  if (op === "screenshot") {
    const frames = await chrome.webNavigation.getAllFrames({
      tabId: session.tabId,
    });
    const captchaVerified = await verificationStatus(frames);
    const checks = await chrome.scripting.executeScript({
      target: { tabId: session.tabId, allFrames: true },
      func: domTask,
      args: [{ op: "scan", captchaVerified }],
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
    const captchaVerified = await verificationStatus(frames);
    for (const frame of frames) {
      // CAPTCHA frames are judged by the page scan, which sees whether the frame
      // is actually on screen; a frame's URL alone can't tell an invisible
      // verification frame (Indeed) from a challenge you must solve.
      if (!permitted(frame.url) && !indeedFrame(frame.url)) continue;
      const [r] = await chrome.scripting.executeScript({
        target: { tabId: session.tabId, frameIds: [frame.frameId] },
        func: domTask,
        args: [{ op: "scan", captchaVerified }],
      });
      if (r?.result) {
        r.result.fields.forEach((f) => (f.frameId = frame.frameId));
        r.result.buttons.forEach((b) => (b.frameId = frame.frameId));
        r.result.attachments?.forEach((a) => (a.frameId = frame.frameId));
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
      blockers: [
        ...new Set([...blockers, ...results.flatMap((r) => r.blockers)]),
      ],
      attachments: results.flatMap((r) => r.attachments || []),
      confirmation: results.find((r) => r.confirmation)?.confirmation || "",
      diagnostics: {
        ...(top.diagnostics || {}),
        frames: frames.map((f) => { try { return new URL(f.url).hostname; } catch { return ""; } }),
        scannedFrames: results.length,
      },
    };
  }
  if (op === "indeedPart") {
    const frames = await chrome.webNavigation.getAllFrames({ tabId: session.tabId });
    let last = "Indeed control not found.";
    for (const frame of frames.filter((f) => permitted(f.url) || indeedFrame(f.url))) {
      try {
        const [r] = await chrome.scripting.executeScript({
          target: { tabId: session.tabId, frameIds: [frame.frameId] },
          func: domTask,
          args: [{ ...args, op }],
        });
        if (r?.result?.clicked) { await new Promise((res) => setTimeout(res, 1200)); return r.result; }
      } catch (e) { last = e.message; }
    }
    throw new Error(last);
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
    if(args.contentBase64){
      const [result]=await chrome.scripting.executeScript({target:{tabId:session.tabId,frameIds:[0]},func:domTask,args:[{...args,op:'attach'}]});
      if(!result?.result?.uploaded)throw new Error('Document bytes were not accepted by the upload control.');
      return result.result;
    }
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
  if (!["fill", "click", "indeedPart"].includes(op))
    throw new Error("Unknown bridge command.");
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: session.tabId, frameIds: [args.frameId || 0] },
    func: domTask,
    args: [{ ...args, op }],
  });
  if (op === "click" || op === "indeedPart") await new Promise((r) => setTimeout(r, 1200));
  return result.result;
}
// Barrier notifications from the application service. Clicking one brings the
// tracked application tab (or the dashboard) to the front.
async function notify(args) {
  const id = args.applicationId ? "rs-app-" + args.applicationId : "rs-test";
  if (args.clear) {
    await chrome.notifications.clear(id);
    return;
  }
  await chrome.notifications.create(id, {
    type: "basic",
    iconUrl: "icon128.png",
    title: String(args.title || "Resume Studio"),
    message: String(args.message || ""),
    priority: 2,
    requireInteraction: args.barrier !== "result",
  });
  await chrome.storage.session.set({
    notifiedApplication: args.applicationId || "",
  });
}
chrome.notifications.onClicked.addListener(async (notificationId) => {
  await ready;
  chrome.notifications.clear(notificationId);
  await chrome.storage.session.set({requestedQuestionApplication:notificationId.startsWith('rs-app-') ? notificationId.slice(7) : null});
  // Questions from pending jobs stay in the extension while the queue continues.
  try {
    const window = await chrome.windows.getLastFocused({windowTypes:["normal"]});
    if (window?.id) await chrome.windows.update(window.id, {focused:true});
    await chrome.action.openPopup();
    return;
  } catch { /* Older Chrome versions retain the existing dashboard fallback. */ }
  const notifiedApplication = notificationId.startsWith("rs-app-")
    ? notificationId.slice(7) : "";
  if (
    session?.tabId &&
    (!notifiedApplication || session.applicationId === notifiedApplication)
  ) {
    try {
      const tab = await chrome.tabs.update(session.tabId, { active: true });
      await chrome.windows.update(tab.windowId, { focused: true });
      return;
    } catch {
      /* Tab closed: fall through to the dashboard. */
    }
  }
  await chrome.tabs.create({ url: "http://127.0.0.1:8091/", active: true });
});
// Older versions used a new timestamp ID on every pause and never retired it.
// Clear only this extension's legacy alerts once when loading the update.
void chrome.notifications.getAll().then(async notifications => {
  for (const id of Object.keys(notifications))
    if (/^rs-\d+$/.test(id)) await chrome.notifications.clear(id);
});
function connect() {
  if (socket && [0, 1].includes(socket.readyState)) return;
  socket = new WebSocket("ws://127.0.0.1:8091/bridge");
  socket.onmessage = async (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
      if (data.op === "ping") {
        socket.send(JSON.stringify({ id: data.id, result: { alive: true, version: chrome.runtime.getManifest().version } }));
        return;
      }
      if (data.op === "notify") {
        // Notifications never wait behind a running browser operation.
        await notify(data.args || {});
        socket.send(JSON.stringify({ id: data.id, result: { shown: true } }));
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
    if (message.op === 'chrome-autofill') {
      if (!session) throw new Error('Open or resume the application first.');
      const tab = await chrome.tabs.get(session.tabId);
      if (!permitted(tab.url)) throw new Error('Unapproved application destination.');
      await chrome.tabs.update(session.tabId,{active:true});
      await chrome.windows.update(tab.windowId,{focused:true});
      const [result] = await chrome.scripting.executeScript({target:{tabId:session.tabId},func:()=>{
        const input=[...document.querySelectorAll('input')].find(el=>el.getClientRects().length && !el.disabled && !el.readOnly && /^(?:section-\S+\s+)?(?:shipping\s+|billing\s+)?(?:name|given-name|family-name|street-address|address-line1|email|tel)$/.test(el.autocomplete));
        if (!input) return false;
        input.focus();input.click();return true;
      }});
      if (!result?.result) throw new Error('Select an address or name field in Chrome, then choose your saved autofill suggestion.');
    }
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
