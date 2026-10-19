// Self-contained so chrome.scripting and Playwright can execute the same code.
export async function domTask(task) {
  // UKG and other web components keep their public controls in open shadow roots.
  const roots = [document];
  for (let i = 0; i < roots.length; i++)
    for (const el of roots[i].querySelectorAll("*"))
      if (el.shadowRoot) roots.push(el.shadowRoot);
  const queryAll = (css) => roots.flatMap(root => [...root.querySelectorAll(css)]);
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
    const root = el.getRootNode();
    const prefix = root.host ? selector(root.host) + " >>> " : "";
    if (
      el.id &&
      root.querySelectorAll("#" + CSS.escape(el.id)).length === 1
    )
      return prefix + "#" + CSS.escape(el.id);
    const parts = [];
    while (el && el !== document.documentElement) {
      const tag = el.tagName.toLowerCase();
      const siblings = [...(el.parentElement || root).children].filter(
        (e) => e.tagName === el.tagName,
      );
      parts.unshift(tag + ":nth-of-type(" + (siblings.indexOf(el) + 1) + ")");
      el = el.parentElement;
    }
    return prefix + (root.host ? "" : "html > ") + parts.join(" > ");
  };
  const protectedField = (el) =>
    /password|passcode|one.time|verification.code|captcha/i.test(
      [el.type, el.name, el.id, label(el), el.autocomplete].join(" "),
    );
  const restricted = (s) =>
    /consent|agree|certify|attest|privacy|terms|marketing|sms|talent.pool|disabilit|veteran|gender|race|ethnic|sexual|pronoun|demographic|aboriginal|indigenous|religion|date.of.birth/i.test(
      s,
    );
  const controls = queryAll("input,select,textarea");
  const historyContext = (el) => {
    const dayforce=(el.id || '').match(/_(educationHistory|workHistory)_(\d+)_(\w+)$/);
    if(dayforce){
      const keys={degreeName:'credential',majorName:'credential',schoolName:'institution',title:'role',companyName:'company',description:'bullets',effectiveStart:'startDate',effectiveEnd:'endDate'};
      return {section:dayforce[1]==='educationHistory'?'education':'experience',index:Number(dayforce[2]),key:keys[dayforce[3]] || dayforce[3],orderedBlankRow:true};
    }
    const ancestors = [];
    for (let p = el; p && ancestors.length < 10; p = p.parentElement) ancestors.push(p);
    const tags = ancestors.map(p => [p.id, p.getAttribute('data-automation-id')].filter(Boolean).join(' '));
    const match = tags.join(' ').match(/(workExperience|education)[-\[]([0-9]+)/i);
    if (!match || Number(match[2]) < 1) return undefined;
    let key = '';
    const name = label(el).replace(/\*/g, '').trim().toLowerCase();
    const keys = {'job title':'role','company':'company','location':'location','role description':'bullets',
      'school or university':'institution','field of study':'credential'};
    key = keys[name] || '';
    if (/^(month|year)$/.test(name)) {
      const dateGroup = tags.find(t => /(?:startDate|endDate|firstYearAttended|lastYearAttended)/i.test(t));
      if (dateGroup) key = (/startDate|firstYearAttended/i.test(dateGroup) ? 'start' : 'end') + (name === 'month' ? 'Month' : 'Year');
    }
    return {section:/workExperience/i.test(match[1]) ? 'experience' : 'education', index:Number(match[2])-1, key};
  };
  const widgetLabel = (el) => {
    const clean = (text) => {
      const selected = (el.innerText || '').trim();
      return selected && text !== selected && text.endsWith(selected) ? text.slice(0,-selected.length).trim() : text;
    };
    const own = clean(label(el));
    if ((el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) && own && !/^(?:open|select|choose|clear)/i.test(own)) return own;
    for (let p = el.parentElement, i = 0; p && i < 4; p = p.parentElement, i++) {
      const labels = [...p.querySelectorAll("label")].filter(visible);
      if (labels.length === 1 && labels[0].innerText.trim().length < 160) return clean(labels[0].innerText.trim());
      if (labels.length > 1) break;
    }
    return own;
  };
  const widgets = queryAll('button,[role="combobox"]').filter(el =>
    !controls.includes(el) && visible(el) && !el.disabled && !/clear selection/i.test(el.getAttribute('aria-label') || el.innerText || '') &&
    (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-haspopup') === 'listbox' ||
      /^(?:province|state|country)\b/i.test(widgetLabel(el))));
  const uploadContext = (el) => {
    for (
      let p = el.parentElement, depth = 0;
      p && p.tagName !== "FORM" && depth < 7;
      p = p.parentElement, depth++
    ) {
      const text = p.innerText || "";
      const heading = text.match(
        /(?:^|\n)\s*(Cover Letter|Resume(?:\s*\/\s*CV)?|Résumé|CV)\s*\*?\s*(?:\n|$)/i,
      );
      if (
        heading &&
        text.length < 12000 &&
        p.querySelectorAll("input[type=file]").length <= 1
      )
        return { element: p, label: heading[1] };
    }
    return null;
  };
  if (task.op === "scan") {
    const blockers = [];
    if (controls.some((el) => visible(el) && protectedField(el)))
      blockers.push("Login or verification: complete it in Chrome.");
    if (
      queryAll("iframe").some(
        (el) =>
          visible(el) &&
          /captcha|recaptcha|hcaptcha/i.test(el.src + " " + el.title) &&
          !task.captchaVerified,
      )
    )
      blockers.push("CAPTCHA: complete it in Chrome.");
    const body = document.body?.innerText || "";
    if (
      /job (?:is no longer|has been) (?:available|filled)|position (?:has been filled|is no longer available)|job not found|opportunity[^\n]{0,100}no longer available|(?:job|position|posting|vacancy) (?:has )?(?:expired|closed)|(?:no longer|not) accepting applications|(?:404|410)\s*(?:[-:]\s*)?(?:page |job )?(?:not found|gone)/i.test(
        body,
      )
    )
      blockers.push("Opportunity unavailable.");
    if (/session (?:has )?expired|please sign in to continue|(?:application |session |this )?link (?:has |is )?(?:expired|invalid|no longer active)|(?:session|application)[^\n]{0,40}timed out|your session is no longer valid|page (?:was )?not found/i.test(body))
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
      if (
        /please leave.*blank|honeypot/i.test(label(el)) ||
        el.getAttribute("aria-hidden") === "true"
      )
        continue;
      if (el.type !== "file" && !visible(el)) continue;
      const field = {
        frameId: 0,
        selector: selector(el),
        history: historyContext(el),
        uploadRole:el.type==='file' ? /(?:^|_)files_resume$/i.test(el.name || el.id)?'resume':/(?:^|_)files_coverLetter$/i.test(el.name || el.id)?'cover_letter':/import|attachment:/i.test(label(el))?'resume_import':undefined : undefined,
        label:
          el.type === "file"
            ? /(?:^|_)files_resume$/i.test(el.name || el.id)?'Resume':/(?:^|_)files_coverLetter$/i.test(el.name || el.id)?'Cover Letter':uploadContext(el)?.label || label(el)
            : label(el),
        type:
          el.tagName === "SELECT"
            ? "select"
            : el.tagName === "TEXTAREA"
              ? "textarea"
              : el.type,
        required:
          el.required ||
          el.getAttribute("aria-required") === "true" ||
          /\*\s*$/.test(label(el)),
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
        maxLength: el.maxLength > 0 ? el.maxLength : undefined,
        focused:el.getRootNode().activeElement===el,
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
      if (field.history) {
        const dateLabel=/^(start|end)(Month|Year)$/.test(field.history.key)?field.history.key.replace(/(Month|Year)$/,' $1'):field.label;
        field.label = `${field.history.section==='education'?'Education':'Work experience'} ${field.history.index + 1} · ${dateLabel}`;
      }
      fields.push(field);
    }
    for (const el of widgets) {
      const text = (el.innerText || '').trim();
      const name = widgetLabel(el);
      if (!name || protectedField(el)) continue;
      fields.push({frameId:0,selector:selector(el),label:name,type:'custom-select',required:el.getAttribute('aria-required') === 'true' || /\*/.test(name),
        value:/^[–—-]?\s*(?:select|choose)(?:\s*(?:one|an option))?\s*[–—-]?$/i.test(text) ? '' : text,
        options:[],files:[],accept:'',invalid:el.getAttribute('aria-invalid') === 'true'});
    }
    const attachments = [];
    for (const button of document.querySelectorAll("button,[role=button]")) {
      if (
        !visible(button) ||
        !/^(?:replace resume|replace cover letter|remove file|delete(?: file)?|remove(?: attachment)?)(?:\s|$)/i.test(
          (button.getAttribute("aria-label") || button.innerText || "").trim(),
        )
      )
        continue;
      const context = uploadContext(button);
      if (!context) continue;
      const lines = [
        ...(context.element.innerText || "").split("\n"),
        ...[...context.element.querySelectorAll("span,p,a")].map(
          (e) => e.innerText || "",
        ),
      ]
        .map((s) => s.trim())
        .filter(Boolean);
      for (const name of lines.filter(
        (s) =>
          s.length <= 255 &&
          !/[\\/]/.test(s) &&
          /\.(pdf|docx?|txt|rtf)$/i.test(s),
      )) {
        const receipt = {
          kind: /cover/i.test(context.label) ? "cover_letter" : "resume",
          name,
          frameId: 0,
        };
        if (
          !attachments.some(
            (a) => a.kind === receipt.kind && a.name === receipt.name,
          )
        )
          attachments.push(receipt);
      }
    }
    // Workday uses a trash icon rather than BambooHR's "remove file" control.
    // Accept a filename only in its resume section with a visible success receipt.
    for (const node of queryAll('div,section')) {
      if (!visible(node) || !/Successfully Uploaded!/i.test(node.innerText || '')) continue;
      const context = uploadContext(node);
      if (!context) continue;
      const text = node.innerText || '';
      if (text.length > 1000) continue;
      for (const name of text.split('\n').map(s => s.trim()).filter(s => s.length <= 255 && !/[\\/]/.test(s) && /\.(pdf|docx?|txt|rtf)$/i.test(s))) {
        const kind = /cover/i.test(context.label) ? 'cover_letter' : 'resume';
        if (!attachments.some(a => a.kind === kind && a.name === name)) attachments.push({kind,name,frameId:0});
      }
    }
    const buttons = [
      ...queryAll(
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
        ...(() => {
          if(!/^Update$/i.test((el.innerText || el.value || '').trim()))return {};
          const form=el.closest('form');
          const input=form?.querySelector('input[id*="_educationHistory_"]');
          const match=input?.id.match(/_educationHistory_(\d+)_/);
          return match?{educationIndex:Number(match[1])}:{};
        })(),
      }));
    const confirmation =
      [
        ...queryAll(
          '[role="status"],main,h1,h2,p,.confirmation,#confirmation,main div',
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
    const educationAdd = buttons.find(b => /^\+?\s*Add Education History$/i.test(b.label));
    let educationSection;
    if (educationAdd) {
      const add = queryAll('button,[role="button"]').find(node => selector(node) === educationAdd.selector);
      for(let p=add?.parentElement,depth=0;p && depth<7;p=p.parentElement,depth++){
        const text=p.innerText || '';
        if([...p.querySelectorAll('h1,h2,h3,h4,legend,[role="heading"]')].some(h=>/^Education History$/i.test(h.innerText.trim())) && !/Employment History|Work Experience/i.test(text) && text.length<12000){
          educationSection={text,hasRecords:[...p.querySelectorAll('button,[role="button"]')].some(b=>/^(?:edit|delete)(?: record)?$/i.test((b.innerText || b.getAttribute('aria-label') || '').trim()))};
          break;
        }
      }
    }
    return {
      url: location.href,
      title: document.title,
      fields,
      buttons,
      blockers,
      confirmation,
      supportsFocus:true,
      supportsByteUploads:true,
      educationSection,
      reviewText: !blockers.length && buttons.some(b=>/^submit(?: your)? application$/i.test(b.label.trim())) ? (document.querySelector('main')?.innerText || body).slice(0,16000) : '',
      attachments,
    };
  }
  let contexts = [document];
  const segments = task.selector.split(" >>> ");
  let matches = [];
  for (let i = 0; i < segments.length; i++) {
    matches = contexts.flatMap(root => [...root.querySelectorAll(segments[i])]);
    contexts = matches.map(el => el.shadowRoot).filter(Boolean);
  }
  if (matches.length !== 1)
    throw new Error("Field changed or selector is ambiguous; inspect again.");
  const el = matches[0];
  if (protectedField(el))
    throw new Error(
      "Credentials and verification fields require manual input.",
    );
  if(task.op==='attach'){
    if(el.tagName!=='INPUT' || el.type!=='file' || el.disabled || !task.name || /[\\/]/.test(task.name))throw new Error('Invalid file upload target.');
    if(typeof task.contentBase64!=='string' || task.contentBase64.length>7*1024*1024)throw new Error('Invalid document payload.');
    const bytes=Uint8Array.from(atob(task.contentBase64),c=>c.charCodeAt(0));
    if(!bytes.length || bytes.length!==task.size)throw new Error('Document byte count does not match.');
    const transfer=new DataTransfer();transfer.items.add(new File([bytes],task.name,{type:task.mime || 'application/octet-stream'}));
    el.files=transfer.files;
    if(el.files[0]?.size!==task.size)throw new Error('Browser did not accept the complete document.');
    el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
    return {uploaded:true,name:task.name,size:bytes.length};
  }
  if (task.op === "click") {
    if (!visible(el) || el.disabled)
      throw new Error("Button is not available.");
    const text = (
      el.innerText ||
      el.value ||
      el.getAttribute("aria-label") ||
      ""
    ).trim();
    const educationUpdate = task.educationUpdate === true && /^Update$/i.test(text) && (()=>{
      const form=el.closest('form');
      const fields=[...(form?.querySelectorAll('input,select,textarea') || [])];
      return fields.some(f=>/_educationHistory_\d+_/.test(f.id)) && !fields.some(f=>/_workHistory_\d+_/.test(f.id)) && fields.every(f=>!f.required || f.disabled || f.checkValidity());
    })();
    const permitted = task.submit
      ? /^(submit your application|submit application|submit|send application|apply now)$/i
      : /^(\+?\s*add education history|next|continue|continue application|review your application|review application|apply on company site|save and continue|save & continue|apply|apply now|apply online|click here to apply(?: online)?|apply for this (?:job|position|role)|apply to this (?:job|position|role)|autofill with resume|apply manually|apply without an account|start(?: your| my)? application|begin application|i'?m interested)$/i;
    if (
      (!educationUpdate && !permitted.test(text.replace(/\s+/g, " "))) ||
      (!task.submit && /submit|send/i.test(text))
    )
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
    if (widgets.includes(el) || el.getAttribute('role') === 'combobox') {
      if (restricted(widgetLabel(el))) throw new Error('This choice requires personal confirmation in Chrome.');
      el.click();
      const normalize = value => value.normalize('NFKC').replace(/\s+/g,' ').trim().toLocaleLowerCase();
      let searched = false;
      for (let attempt = 0; attempt < 15; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 100));
        const ids = (el.getAttribute('aria-controls') || el.getAttribute('aria-owns') || '').split(/\s+/).filter(Boolean);
        const lists = ids.map(id => el.getRootNode().getElementById?.(id)).filter(Boolean);
        const all = lists.length ? lists.flatMap(list => [...list.querySelectorAll('[role="option"],li,[data-value]')]) : queryAll('[role="option"],[role="listbox"] li,[role="listbox"] [data-value]');
        const options = all.filter(option => visible(option) && option.getAttribute('aria-disabled') !== 'true' && !option.disabled && normalize(option.innerText || option.getAttribute('aria-label') || '') === normalize(task.value));
        if (options.length === 1) { options[0].click(); return {filled:true}; }
        if (options.length > 1) throw new Error('Dropdown option is ambiguous.');
        if (!searched && attempt >= 2) {
          const searchRoots = lists.length ? lists : [el.parentElement];
          const searches = (el.tagName === 'INPUT' ? [el] : searchRoots.flatMap(root => [...root.querySelectorAll('input[role="searchbox"],input[type="search"],input[placeholder*="Search" i]')])).filter(input => visible(input) && !input.disabled && !input.readOnly && !protectedField(input));
          if (searches.length === 1) {
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(searches[0],task.value);
            searches[0].dispatchEvent(new Event('input',{bubbles:true}));
            searched=true;
          }
        }
      }
      throw new Error('No exact custom dropdown option.');
    }
    if (restricted(label(el)) || ["checkbox", "file"].includes(el.type))
      throw new Error("This field requires manual input or document upload.");
    if (!visible(el) || el.disabled || el.readOnly)
      throw new Error("Field unavailable.");
    if (el.tagName === "SELECT") {
      const found = [...el.options].filter(
        (o) => o.text.normalize('NFKC').replace(/\s+/g,' ').trim().toLowerCase() === task.value.normalize('NFKC').replace(/\s+/g,' ').trim().toLowerCase() && !o.disabled,
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

