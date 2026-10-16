import { test, expect } from "@playwright/test";
// The extension's actual DOM code is executed on local fixtures only.
// @ts-expect-error Browser module is plain JavaScript for Chrome MV3.
import { domTask } from "../../extension/dom.js";

test("single-page required controls, dropdowns, radio groups, upload and verified success", async ({
  page,
}) => {
  await page.setContent(`<form onsubmit="event.preventDefault();document.body.innerHTML='<h1>Your application has been received</h1>'">
  <label for="first">First name</label><input id="first" required>
  <label for="country">Country</label><select id="country" required><option value="">Choose</option><option value="ca">Canada</option></select>
  <fieldset><legend>Work arrangement</legend><label><input type="radio" name="work" value="remote" required>Remote</label><label><input type="radio" name="work" value="onsite">Onsite</label></fieldset>
  <label for="resume">Resume</label><input id="resume" type="file" accept=".pdf" required>
  <button id="submit">Submit application</button></form>`);
  let s = await page.evaluate(domTask, { op: "scan" });
  expect(s.fields.length).toBe(4);
  expect(s.fields[0].required).toBe(true);
  await page.evaluate(domTask, {
    op: "fill",
    selector: "#first",
    value: "Jordan",
  });
  await page.evaluate(domTask, {
    op: "fill",
    selector: "#country",
    value: "Canada",
  });
  await page.evaluate(domTask, {
    op: "fill",
    selector: s.fields.find((f) => f.type === "radio").selector,
    value: "Remote",
  });
  await page
    .locator("#resume")
    .setInputFiles({
      name: "tailored.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 test"),
    });
  s = await page.evaluate(domTask, { op: "scan" });
  expect(s.fields.find((f) => f.type === "file").files).toEqual([
    "tailored.pdf",
  ]);
  expect(s.fields.find((f) => f.type === "radio").value).toBe("Remote");
  // Fixture URL has an empty hostname; only the local test permits this destination.
  await page.evaluate(domTask, {
    op: "click",
    selector: "#submit",
    submit: true,
    domains: [""],
  });
  expect((await page.evaluate(domTask, { op: "scan" })).confirmation).toContain(
    "received",
  );
});
test("conditional multistep form requires a fresh scan", async ({ page }) => {
  await page.setContent(
    `<label for="experience">Experience</label><select id="experience" onchange="document.getElementById('extra').innerHTML='<label for=years>Years</label><input id=years required>'"><option value="">Choose</option><option>Yes</option></select><div id="extra"></div><button id="next" type="button" onclick="document.body.innerHTML='<label for=email>Email</label><input id=email type=email required>'">Next</button>`,
  );
  await page.evaluate(domTask, {
    op: "fill",
    selector: "#experience",
    value: "Yes",
  });
  expect(
    (await page.evaluate(domTask, { op: "scan" })).fields.map((f) => f.label),
  ).toContain("Years");
  await page.evaluate(domTask, {
    op: "click",
    selector: "#next",
    submit: false,
    domains: [],
  });
  expect((await page.evaluate(domTask, { op: "scan" })).fields[0].label).toBe(
    "Email",
  );
});
test("credentials and one-time codes are never extracted or filled", async ({
  page,
}) => {
  await page.setContent(
    '<label for="password">Password</label><input id="password" type="password" value="secret"><label for="otp">Verification code</label><input id="otp" autocomplete="one-time-code" value="123456">',
  );
  const s = await page.evaluate(domTask, { op: "scan" });
  expect(s.fields).toEqual([]);
  expect(s.blockers).toHaveLength(1);
  expect(JSON.stringify(s)).not.toContain("secret");
  expect(JSON.stringify(s)).not.toContain("123456");
  await expect(
    page.evaluate(domTask, {
      op: "fill",
      selector: "#password",
      value: "anything",
    }),
  ).rejects.toThrow(/manual/);
});
test("consent and demographic fields stay manual", async ({ page }) => {
  await page.setContent(
    '<label for="consent">I agree to the terms</label><input id="consent" type="checkbox"><label for="gender">Gender</label><input id="gender">',
  );
  await expect(
    page.evaluate(domTask, { op: "fill", selector: "#consent", value: "true" }),
  ).rejects.toThrow(/manual/);
  await expect(
    page.evaluate(domTask, { op: "fill", selector: "#gender", value: "Male" }),
  ).rejects.toThrow(/manual/);
});
test("HTML validation failure blocks final submission", async ({ page }) => {
  await page.setContent(
    '<form><label for="email">Email</label><input id="email" type="email" required><button id="submit">Submit application</button></form>',
  );
  await page.evaluate(domTask, {
    op: "fill",
    selector: "#email",
    value: "invalid",
  });
  expect((await page.evaluate(domTask, { op: "scan" })).fields[0].invalid).toBe(
    true,
  );
  await expect(
    page.evaluate(domTask, {
      op: "click",
      selector: "#submit",
      submit: true,
      domains: [""],
    }),
  ).rejects.toThrow(/validation/);
});
test("session expiration, CAPTCHA and unavailable jobs pause", async ({
  page,
}) => {
  await page.setContent(
    '<p>Your session has expired</p><iframe title="CAPTCHA" src="about:blank"></iframe><p>This position has been filled</p>',
  );
  const s = await page.evaluate(domTask, { op: "scan" });
  expect(s.blockers).toHaveLength(3);
});
test("Apply in same tab and popup both navigate with observable application forms", async ({
  page,
  context,
}) => {
  await context.route("https://fixture.example/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<label for="name">Full name</label><input id="name">',
    }),
  );
  await page.setContent(
    '<a id="apply" href="https://fixture.example/form" target="_blank">Apply</a>',
  );
  const popupPromise = context.waitForEvent("page");
  await page.evaluate(domTask, {
    op: "click",
    selector: "#apply",
    submit: false,
    domains: ["fixture.example"],
  });
  const popup = await popupPromise;
  await popup.waitForLoadState();
  expect((await popup.evaluate(domTask, { op: "scan" })).fields[0].label).toBe(
    "Full name",
  );
  await page.setContent(
    '<a id="apply" href="https://fixture.example/form">Apply</a>',
  );
  await page.evaluate(domTask, {
    op: "click",
    selector: "#apply",
    submit: false,
    domains: ["fixture.example"],
  });
  await page.waitForURL("https://fixture.example/form");
  expect((await page.evaluate(domTask, { op: "scan" })).fields[0].label).toBe(
    "Full name",
  );
});
test("unknown submit controls are not treated as navigation", async ({
  page,
}) => {
  await page.setContent('<form><button id="apply">Apply now</button></form>');
  await expect(
    page.evaluate(domTask, {
      op: "click",
      selector: "#apply",
      submit: false,
      domains: [""],
    }),
  ).rejects.toThrow(/review/);
});
