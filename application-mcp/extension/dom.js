// Self-contained so chrome.scripting and Playwright can execute the same code.
export function domTask(task) {
  const visible = (el) =>
    el.getClientRects().length > 0 &&
    getComputedStyle(el).visibility !== "hidden";
  const label = (el) => {
    const own =
      el.labels?.[0]?.innerText ||
      el.getAttribute("aria-label") ||
      (el.getAttribute("aria-labelledby") || "")
        .split(" ")
        .map((id) => document.getElementById(id)?.innerText || "")
        .join(" ");
    return (own || el.placeholder || el.name || el.id || "").trim();
  };
  const selector = (el) => {
    if (
      el.id &&
      document.querySelectorAll("#" + CSS.escape(el.id)).length === 1
    )
      return "#" + CSS.escape(el.id);
    const parts = [];
    while (el && el !== document.documentElement) {
      const tag = el.tagName.toLowerCase();
      const siblings = [...el.parentElement.children].filter(
        (e) => e.tagName === el.tagName,
      );
      parts.unshift(tag + ":nth-of-type(" + (siblings.indexOf(el) + 1) + ")");
      el = el.parentElement;
    }
    return "html > " + parts.join(" > ");
  };
  const protectedField = (el) =>
    /password|passcode|one.time|verification.code|captcha/i.test(
      [el.type, el.name, el.id, label(el), el.autocomplete].join(" "),
    );
  const restricted = (s) =>
    /consent|agree|certify|attest|privacy|terms|marketing|sms|talent.pool|disabilit|veteran|gender|race|ethnic|sexual|pronoun|demographic|aboriginal|indigenous|religion|date.of.birth/i.test(
      s,
    );
  const controls = [...document.querySelectorAll("input,select,textarea")];
  if (task.op === "scan") {
    const blockers = [];
    if (controls.some((el) => visible(el) && protectedField(el)))
      blockers.push("Login or verification: complete it in Chrome.");
    if (
      [...document.querySelectorAll("iframe")].some(
        (el) =>
          visible(el) &&
          /captcha|recaptcha|hcaptcha/i.test(el.src + " " + el.title),
      )
    )
      blockers.push("CAPTCHA: complete it in Chrome.");
    const body = document.body?.innerText || "";
    if (
      /job (?:is no longer|has been) (?:available|filled)|position (?:has been filled|is no longer available)|job not found|opportunity.*no longer available/i.test(
        body,
      )
    )
      blockers.push("Opportunity unavailable.");
    if (/session (?:has )?expired|please sign in to continue/i.test(body))
      blockers.push("Session expired: sign in in Chrome.");
    const fields = [];
    const radioNames = new Set();
    for (const el of controls) {
      if (
        el.disabled ||
        ["hidden", "submit", "button", "reset", "image"].includes(el.type) ||
        protectedField(el)
      )
        continue;
      if (el.type !== "file" && !visible(el)) continue;
      const field = {
        frameId: 0,
        selector: selector(el),
        label: label(el),
        type:
          el.tagName === "SELECT"
            ? "select"
            : el.tagName === "TEXTAREA"
              ? "textarea"
              : el.type,
        required: el.required || el.getAttribute("aria-required") === "true",
        value:
          el.type === "file"
            ? ""
            : el.type === "checkbox"
              ? el.checked
                ? "true"
                : ""
              : el.value,
        options: [],
        files: el.type === "file" ? [...el.files].map((f) => f.name) : [],
        accept: el.accept || "",
        invalid:
          el.getAttribute("aria-invalid") === "true" ||
          (!!el.value && !!el.validity && !el.validity.valid),
      };
      if (el.type === "radio" && el.name) {
        if (radioNames.has(el.name)) continue;
        radioNames.add(el.name);
        const radios = controls.filter(
          (r) => r.type === "radio" && r.name === el.name,
        );
        const group = el.closest('fieldset,[role="radiogroup"]');
        field.label = (
          group?.querySelector("legend")?.innerText ||
          group?.getAttribute("aria-label") ||
          el.name
        ).trim();
        field.options = radios.map(label);
        field.value = radios.find((r) => r.checked)
          ? label(radios.find((r) => r.checked))
          : "";
        field.required = radios.some((r) => r.required);
      }
      if (el.tagName === "SELECT") {
        field.options = [...el.options]
          .filter((o) => o.value && !o.disabled)
          .map((o) => o.text.trim());
        field.value = el.value ? el.selectedOptions[0]?.text.trim() || "" : "";
      }
      fields.push(field);
    }
    const buttons = [
      ...document.querySelectorAll(
        'button,a[href],input[type="submit"],input[type="button"],[role="button"]',
      ),
    ]
      .filter(visible)
      .map((el) => ({
        frameId: 0,
        selector: selector(el),
        label: (
          el.innerText ||
          el.value ||
          el.getAttribute("aria-label") ||
          ""
        ).trim(),
        ...(el.tagName === "A" ? { href: el.href } : {}),
      }));
    const confirmation =
      [
        ...document.querySelectorAll(
          '[role="status"],main,h1,h2,.confirmation,#confirmation',
        ),
      ]
        .filter(visible)
        .map((e) => e.innerText)
        .find(
          (t) =>
            t.length < 1000 &&
            /application (?:has been |was )?(?:successfully )?(?:submitted|received)|thank you for applying/i.test(
              t,
            ),
        ) || "";
    return {
      url: location.href,
      title: document.title,
      fields,
      buttons,
      blockers,
      confirmation,
    };
  }
  const matches = document.querySelectorAll(task.selector);
  if (matches.length !== 1)
    throw new Error("Field changed or selector is ambiguous; inspect again.");
  const el = matches[0];
  if (protectedField(el))
    throw new Error(
      "Credentials and verification fields require manual input.",
    );
  if (task.op === "click") {
    if (!visible(el) || el.disabled)
      throw new Error("Button is not available.");
    const text = (
      el.innerText ||
      el.value ||
      el.getAttribute("aria-label") ||
      ""
    ).trim();
    const permitted = task.submit
      ? /^(submit application|submit|send application|apply now)$/i
      : /^(next|continue|save and continue|apply|apply now|apply for this job|start application)$/i;
    if (!permitted.test(text) || (!task.submit && /submit|send/i.test(text)))
      throw new Error("Button requires manual review.");
    if (el.tagName === "A") {
      const u = new URL(el.href);
      if (u.protocol !== "https:" || !task.domains.includes(u.hostname))
        throw new Error("Navigation destination requires domain approval.");
    }
    if (el.type === "submit") {
      const u = new URL(
        el.formAction || el.closest("form")?.action || location.href,
      );
      if (
        (u.protocol !== "https:" && location.href !== "about:blank") ||
        !task.domains.includes(u.hostname)
      )
        throw new Error("Form destination requires domain approval.");
    }
    if (task.submit) {
      const form = el.closest("form");
      if (
        form &&
        (!form.checkValidity() ||
          !task.domains.includes(
            new URL(form.action || location.href).hostname,
          ))
      )
        throw new Error("Form validation or destination failed.");
    } else if (
      el.tagName !== "A" &&
      el.type === "submit" &&
      /apply/i.test(text)
    ) {
      throw new Error("Apply is a submit control; use final review.");
    }
    el.click();
    return { clicked: true };
  }
  if (task.op === "fill") {
    if (restricted(label(el)) || ["checkbox", "file"].includes(el.type))
      throw new Error("This field requires manual input or document upload.");
    if (!visible(el) || el.disabled || el.readOnly)
      throw new Error("Field unavailable.");
    if (el.tagName === "SELECT") {
      const found = [...el.options].filter(
        (o) => o.text.trim() === task.value && !o.disabled,
      );
      if (found.length !== 1) throw new Error("No exact dropdown option.");
      el.value = found[0].value;
    } else if (el.type === "radio") {
      const radio = controls.filter(
        (r) =>
          r.type === "radio" && r.name === el.name && label(r) === task.value,
      );
      if (radio.length !== 1) throw new Error("No exact radio option.");
      radio[0].click();
    } else {
      const proto =
        el.tagName === "TEXTAREA"
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, task.value);
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return { filled: true };
  }
  throw new Error("Unknown DOM operation.");
}
