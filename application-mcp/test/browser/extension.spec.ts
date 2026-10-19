import { test, expect, chromium } from "@playwright/test";
import path from "node:path";
import { mkdir, writeFile,readFile } from "node:fs/promises";
import { Store } from "../../src/store.js";
import { ChromeBridge } from "../../src/bridge.js";
import { Service } from "../../src/service.js";
import { Studio } from "../../src/studio.js";
import { httpServer } from "../../src/http.js";
import { ApplyInput } from "../../src/schema.js";
import { documentInfo } from "../../src/security.js";
import { createServer } from "node:https";
import selfsigned from "selfsigned";

test("real MV3 bridge follows popups, fills and uploads, then observes user submission exactly once", async ({}, info) => {
  test.setTimeout(60000);
  const extensionPath = path.resolve("extension");
  const certificates = await selfsigned.generate(
    [{ name: "commonName", value: "fixture.example" }],
    { days: 1 },
  );
  const fixture = createServer(
    { key: certificates.private, cert: certificates.cert },
    (req, res) => {
      res.setHeader("Content-Type", "text/html");
      res.end(
        req.url === "/job"
          ? '<a id="apply" href="https://fixture.example:9443/form" target="_blank">Apply</a>'
          : `<form onsubmit="event.preventDefault();document.body.innerHTML='<h1>Your application has been received</h1>'"><label for="first">First name</label><input id="first" required><div><p>Resume</p><input id="resume" type="file" required accept=".pdf" onchange="const name=this.files[0].name;setTimeout(()=>{this.outerHTML='<span>'+name+'</span><button type=button aria-label=\"remove file\">Remove</button>'},350)"></div><button id="submit">Submit application</button></form>`,
      );
    },
  );
  await new Promise<void>((r) => fixture.listen(9443, "127.0.0.1", r));
  const context = await chromium.launchPersistentContext(
    info.outputPath("profile"),
    {
      channel: "chromium",
      headless: true,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`,
        "--host-resolver-rules=MAP fixture.example 127.0.0.1",
        "--ignore-certificate-errors",
        "--no-proxy-server",
      ],
    },
  );
  let server: ReturnType<typeof httpServer> | undefined;
  let store: Store | undefined;
  try {
    const worker =
      context.serviceWorkers()[0] ||
      (await context.waitForEvent("serviceworker"));
    const extensionId = new URL(worker.url()).host;
    const bridge = new ChromeBridge();
    store = new Store(":memory:");
    let confirmations = 0;
    let logs = 0;
    let learned=0;
    class LocalStudio extends Studio {
      override async request(route:string,body?:any){
        if(route!=='/application-engine/answers')throw new Error('Unexpected fixture API request');
        learned++;const file=info.outputPath('data/apply_profile.json');const profile=JSON.parse(await readFile(file,'utf8'));
        profile.applicationAnswers={test:{[body.question]:body.answer}};await writeFile(file,JSON.stringify(profile));return {saved:true};
      }
      override async validate() {
        return {};
      }
      override async snapshot() {
        return {};
      }
      override async confirm() {
        confirmations++;
        return { may_submit: true };
      }
      override async result() {
        logs++;
        return {};
      }
    }
    await mkdir(info.outputPath("data"), { recursive: true });
    await writeFile(
      info.outputPath("data/apply_profile.json"),
      JSON.stringify({ firstName: "Jordan" }),
    );
    const resume = info.outputPath("tailored.pdf");
    await writeFile(resume, "%PDF-1.4 local test resume");
    const doc = await documentInfo(resume, [info.outputDir]);
    const service = new Service(
      store,
      bridge,
      new LocalStudio(),
      info.outputDir,
      [info.outputDir],
      async (value, domains) => {
        const u = new URL(value);
        if (domains && !domains.includes(u.hostname))
          throw new Error("New domain");
        return u;
      },
    );
    server = httpServer(service, bridge, extensionId);
    await new Promise<void>((r) => server!.listen(8091, "127.0.0.1", r));
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await popup.locator("#connect").click();
    await expect.poll(() => bridge.socket?.readyState).toBe(1);
    const input = ApplyInput.parse({
      jobUrl: "https://fixture.example:9443/job",
      company: "Fixture",
      title: "Test",
      resumePath: resume,
      studioSessionId: "test",
      allowedDomains: ["fixture.example"],
    });
    store.save({
      id: "fixture-app",
      input,
      state: "working",
      ats: "generic",
      documents: [{ kind: "resume", ...doc, attached: false }],
      filled: [],
      reason: "",
      createdAt: "now",
      updatedAt: "now",
    });
    await bridge.command("open", {
      applicationId: "fixture-app",
      url: input.jobUrl,
      domains: input.allowedDomains,
    });
    let a = await service.inspect("fixture-app");
    expect(a.snapshot!.buttons[0].label).toBe("Apply");
    await context.pages().find(p=>p.url()===input.jobUrl)!.close();
    a=await service.resume(a.id);
    expect(context.pages().filter(p=>p.url()===input.jobUrl)).toHaveLength(1);
    expect(a.snapshot!.url).toBe(input.jobUrl);
    await bridge.command('restart',{applicationId:a.id,url:input.jobUrl,domains:input.allowedDomains});
    expect(context.pages().filter(p=>p.url()===input.jobUrl)).toHaveLength(1);
    a = await service.navigate(a.id, a.snapshot!.buttons[0].selector);
    expect(a.snapshot!.fields[0].label).toBe("First name");
    a = await service.preparePage(a.id);
    expect(a.snapshot!.fields[0].value).toBe("Jordan");
    expect(a.documents[0].attached).toBe(true);
    expect(a.state).toBe("review");
    expect(a.evidence).toHaveLength(1);
    const manualPage=context.pages().find(p=>p.url().includes('/form'))!;
    await manualPage.evaluate(()=>{const input=document.createElement('input');input.id='supervisor';const label=document.createElement('label');label.htmlFor='supervisor';label.textContent='Supervisor';document.querySelector('form')!.append(label,input);});
    a=await service.inspect(a.id);
    await service.watchManualAnswer(a.id,'#supervisor',0,false);
    await manualPage.locator('#supervisor').fill('Fixture Manager');await manualPage.locator('#first').click();
    await expect.poll(()=>store!.get(a.id).state,{timeout:20000}).toBe('review');
    expect(learned).toBe(1);expect(store.get(a.id).manualWatches?.[0].saved).toBe(true);
    a=store.get(a.id);
    const approvalPopup = await context.newPage();
    approvalPopup.on('pageerror', error => console.log('Popup error:', error.message));
    await approvalPopup.goto(`chrome-extension://${extensionId}/popup.html`);
    await expect(approvalPopup.locator('#review-status')).toContainText('Ready for your final Submit click');
    await expect(approvalPopup.getByRole('button', { name: 'Click final Submit yourself in Chrome' })).toBeDisabled();
    await expect(approvalPopup.locator('#review-details')).toContainText('Fixture — Test');
    const employer=context.pages().find(p=>p.url().includes('fixture.example') && p.url()!==input.jobUrl)!;
    await employer.locator('#submit').click();
    await service.observeCompletion();
    await expect.poll(() => store!.get(a.id).state).toBe('submitted');
    a = store.get(a.id);
    expect(a.state).toBe("submitted");
    expect(a.evidence!.length).toBeGreaterThanOrEqual(2);
    await expect(approvalPopup.getByRole('button', { name: 'Click final Submit yourself in Chrome' })).toBeDisabled();
    expect(confirmations).toBe(0);
    expect(context.pages().filter(p => p.url().includes('fixture.example'))).toHaveLength(0);
    expect(context.pages().some(p => p.url().startsWith('http://127.0.0.1:8088'))).toBe(true);
    await bridge.command("open", {
      applicationId: "next-fixture",
      url: input.jobUrl,
      domains: input.allowedDomains,
    });
    expect(
      context.pages().filter((p) => p.url().includes("fixture.example")),
    ).toHaveLength(1);
    expect(context.pages().find(p => p.url().includes('fixture.example'))!.url()).toBe(input.jobUrl);
    expect(logs).toBe(1);
    await expect(
      service.submit(a.id, a.reviewHash!, true, "#submit"),
    ).rejects.toThrow();
    expect(confirmations).toBe(0);
  } finally {
    await context.close();
    if (server) await new Promise<void>((r) => server!.close(() => r()));
    await new Promise<void>((r) => fixture.close(() => r()));
    store?.db.close();
  }
});
