"""Headed-browser harness for the apply loop.

Drives your real browser (Brave by default -- that is where the LinkedIn /
Indeed logins live here; --browser chrome or isolated also work) so saved
passwords and sessions are the ones you already have. The chosen browser must
be fully closed first, because it locks its own profile directory.

    apply <url> --key <job_key> --work <dir>
        The whole thing in ONE browser session: open the posting, click Apply
        (same tab or new tab), wait through any sign-in / registration wall,
        read the form, ask the app to plan it, then fill it and attach the
        tailored resume + cover letter.

    scan <url> [--apply]     read a form and dump its controls
    fill <plan.json>         fill an already-built plan
    open <url>               just open a page and hold it

Nothing here ever clicks the final Submit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = Path(os.environ["LOCALAPPDATA"])
FALLBACK_PROFILE = ROOT / ".pw-profile"

# Your real browsers. Brave is the daily driver here, so it is the default:
# its profile is where the LinkedIn / Indeed logins actually live.
BROWSERS = {
    "brave": {
        "user_data": LOCAL / "BraveSoftware" / "Brave-Browser" / "User Data",
        "exe": Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
        "proc": "brave",
    },
    "chrome": {
        "user_data": LOCAL / "Google" / "Chrome" / "User Data",
        "exe": None,          # launched via channel="chrome"
        "proc": "chrome",
    },
}

# Reads every control on the page and returns the shape
# `apply_cli prepare --fields` expects.
JS_SCAN = r"""
() => {
  const vis = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const labelFor = el => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && l.innerText.trim()) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap && wrap.innerText.trim()) return wrap.innerText.trim();
    const grp = el.closest('fieldset,[role=group],.form-group,[class*=field],[class*=question]');
    if (grp) {
      const lg = grp.querySelector('legend,label,.label,[class*=label]');
      if (lg && lg.innerText.trim()) return lg.innerText.trim();
    }
    return (el.getAttribute('aria-label') || el.placeholder || el.name || '').trim();
  };
  const sel = el => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    if (el.name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
    const all = [...document.querySelectorAll(el.tagName.toLowerCase())];
    return `${el.tagName.toLowerCase()}:nth-of-type(${all.indexOf(el) + 1})`;
  };
  const out = [];
  const seenRadio = new Set();
  for (const el of document.querySelectorAll('input,select,textarea')) {
    const t = (el.type || '').toLowerCase();
    if (t === 'hidden' || t === 'submit' || t === 'button' || t === 'image') continue;
    if (t !== 'file' && !vis(el)) continue;          // file inputs are often hidden by design
    if (t === 'radio') {
      if (seenRadio.has(el.name)) continue;
      seenRadio.add(el.name);
    }
    const rec = {
      selector: sel(el),
      name: el.name || '',
      id: el.id || '',
      label: labelFor(el),
      type: el.tagName === 'TEXTAREA' ? 'textarea'
          : el.tagName === 'SELECT' ? 'select'
          : (t === 'radio' || t === 'checkbox' || t === 'file') ? t : 'text',
      required: el.required || el.getAttribute('aria-required') === 'true',
    };
    if (el.tagName === 'SELECT') {
      rec.options = [...el.options].map(o => o.text.trim()).filter(Boolean);
    } else if (t === 'radio') {
      rec.options = [...document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)]
        .map(r => labelFor(r)).filter(Boolean);
    }
    out.push(rec);
  }
  return out;
}
"""

APPLY_PATTERNS = [r"^apply now$", r"^apply$", r"^apply for this job$", r"^apply to this job$",
                  r"^submit application$", r"^start application$", r"^easy apply$", r"^postuler$"]


# --------------------------------------------------------------------------
# browser
# --------------------------------------------------------------------------

def _running(proc: str) -> int:
    """How many processes of `proc` are up (it holds a lock on its profile)."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq {}.exe".format(proc), "/NH"],
            capture_output=True, text=True, timeout=20).stdout.lower()
        return out.count(proc + ".exe")
    except Exception:
        return 0


def _browser(pw, which: str = "brave"):
    """Drive your real browser so its saved logins are the ones in play."""
    if which == "isolated":
        return pw.chromium.launch_persistent_context(
            str(FALLBACK_PROFILE), headless=False, viewport=None,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"])

    cfg = BROWSERS[which]
    n = _running(cfg["proc"])
    if n:
        print("\n{} is running ({} processes). It locks its own profile, so close\n"
              "every {} window and re-run. (Or pass --browser isolated to use a\n"
              "throwaway profile, where you'd have to log in again.)"
              .format(which.title(), n, which.title()), flush=True)
        sys.exit(2)

    args = ["--profile-directory=Default", "--start-maximized",
            "--disable-blink-features=AutomationControlled"]
    kw = {"headless": False, "viewport": None, "args": args}
    if cfg["exe"] and cfg["exe"].exists():
        kw["executable_path"] = str(cfg["exe"])
    else:
        kw["channel"] = which
    try:
        return pw.chromium.launch_persistent_context(str(cfg["user_data"]), **kw)
    except Exception as e:
        print("{} launch failed ({}: {}); falling back to the throwaway profile."
              .format(which.title(), type(e).__name__, str(e)[:120]), flush=True)
        return pw.chromium.launch_persistent_context(
            str(FALLBACK_PROFILE), headless=False, viewport=None,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"])


def _page(ctx, url):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    if url:
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(2500)
    return page


def _live(ctx) -> list:
    return [p for p in ctx.pages if not p.is_closed()]


def _newest(ctx, current):
    """The tab the application actually landed in.

    LinkedIn/Indeed sometimes open the employer's form in a NEW TAB and
    sometimes navigate in place, so both have to work.
    """
    pages = _live(ctx)
    if not pages:
        return current
    for p in reversed(pages):
        if p is not current:
            try:
                if p.url and not p.url.startswith(("about:", "chrome:")):
                    return p
            except Exception:
                continue
    return current if current in pages else pages[-1]


def _click_apply(ctx, page):
    """Click an obvious Apply button/link. Returns (clicked, active_page)."""
    for pat in APPLY_PATTERNS:
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=re.compile(pat, re.I)).first
                if not (loc.count() and loc.is_visible()):
                    continue
                before = len(_live(ctx))
                loc.click(timeout=8000)
                page.wait_for_timeout(4000)
                if len(_live(ctx)) > before:          # opened in a new tab
                    nxt = _newest(ctx, page)
                    try:
                        nxt.bring_to_front()
                        nxt.wait_for_load_state("domcontentloaded", timeout=45_000)
                        nxt.wait_for_timeout(2500)
                    except Exception:
                        pass
                    return True, nxt
                try:                                   # navigated in place
                    page.wait_for_load_state("domcontentloaded", timeout=30_000)
                except Exception:
                    pass
                return True, page
            except Exception:
                continue
    return False, page


def _is_login(page, fields: list) -> bool:
    """A short form with a password box is a sign-in wall, not the application."""
    if len(fields) > 4:
        return False
    try:
        if page.locator("input[type=password]:visible").count():
            return True
    except Exception:
        pass
    blob = " ".join((f.get("label", "") + " " + f.get("name", "")).lower() for f in fields)
    return "password" in blob


def _wait_for_form(ctx, page, minimum: int, timeout_s: int):
    """Poll every live tab until one shows a real application form.

    Sign-in and registration pages are skipped, so this simply keeps waiting
    while you log in or create the account. Returns (fields, page).
    """
    waited, best, warned = 0, [], False
    while waited < timeout_s:
        cand = _newest(ctx, page)
        if cand is not page:
            print("  followed new tab -> " + cand.url[:100], flush=True)
            page = cand
            try:
                page.bring_to_front()
            except Exception:
                pass

        got, where = [], page
        for p in reversed(_live(ctx)):
            try:
                g = p.evaluate(JS_SCAN)
            except Exception:
                continue
            if len(g) > len(got):
                got, where = g, p
        page = where
        if len(got) > len(best):
            best = got
        if len(best) >= minimum and not _is_login(page, best):
            return best, page

        if not warned and _is_login(page, best):
            warned = True
            bar = "=" * 68
            print("\n" + bar, flush=True)
            print("  SIGN IN NEEDED - this employer wants an account.", flush=True)
            print("  Log in (or register) in the browser window that just opened.", flush=True)
            print("  Let the browser save the password; it is once per employer.", flush=True)
            print("  I keep watching and read the form as soon as you are through.", flush=True)
            print(bar + "\n", flush=True)

        page.wait_for_timeout(3000)
        waited += 3
        if waited % 30 == 0:
            print("  ...waiting for a form ({}s, {} controls, {})".format(
                waited, len(best), page.url[:90]), flush=True)
    return best, page


def _hold(ctx, page, msg, timeout_s: int):
    """Keep the browser open until YOU close it (or the time runs out).

    Multi-step forms (ADP, Workday, Greenhouse) navigate on every Next, so
    navigation must NOT end the session -- only closing the browser does.
    """
    print("\n" + msg, flush=True)
    print("CURRENT URL: " + page.url, flush=True)
    print("Close the browser window when you're done and I'll move to the next job.",
          flush=True)
    last, waited = page.url, 0
    while waited < timeout_s:
        try:
            if not _live(ctx):
                print("BROWSER CLOSED - treating this one as finished.", flush=True)
                return "closed"
            cur = _newest(ctx, page)
            if cur.url != last:
                print("  step -> " + cur.url[:110], flush=True)
                last = cur.url
            cur.wait_for_timeout(5000)
        except Exception:
            print("BROWSER CLOSED - treating this one as finished.", flush=True)
            return "closed"
        waited += 5
        if waited % 120 == 0:
            print("  ...still open ({}s)".format(waited), flush=True)
    return "timeout"


def _apply_plan(page, plan):
    """Fill every planned control. Returns (done, failed)."""
    done, failed = [], []
    for item in plan.get("fields", []):
        sel, v, t = item.get("selector"), item.get("value"), item.get("type", "text")
        if not sel or v in (None, ""):
            continue
        try:
            loc = page.locator(sel).first
            if t == "file":
                loc.set_input_files(v)
            elif t == "select":
                loc.select_option(label=v)
            elif t in ("radio", "checkbox"):
                page.get_by_label(v, exact=False).first.check()
            else:
                loc.fill(str(v))
            done.append("{} = {}".format(item.get("label", sel)[:50], str(v)[:60]))
        except Exception as e:
            failed.append("{}: {} {}".format(
                item.get("label", sel)[:50], type(e).__name__, str(e)[:80]))
    return done, failed


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def _signature(fields) -> tuple:
    """Identity of a form step, so we can tell when the page moved on."""
    return tuple(sorted((f.get("selector", ""), f.get("label", "")) for f in fields))


def _plan_step(key, page, fields, work, step):
    """Ask the app to plan this step, then fill it. Returns (sid, unanswered)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from session_plan import build_plan, load_session, report

    fpath = work / "fields_{}.json".format(step)
    fpath.write_text(json.dumps(fields, indent=2), encoding="utf-8")

    cmd = [sys.executable, "-m", "resume_gen.automation.apply_cli", "prepare",
           key, "--fields", str(fpath), "--url", page.url]
    env = dict(os.environ, PYTHONPATH="src", PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
    m = re.search(r"session\s+([0-9a-f]{8,})", r.stdout or "")
    if not m:
        print("PREPARE FAILED on step {}:".format(step), flush=True)
        print((r.stdout or "")[-1200:], flush=True)
        print((r.stderr or "")[-600:], flush=True)
        return None, []
    sid = m.group(1)

    d = load_session(sid)
    plan, skipped, unanswered = build_plan(d, fields)
    (work / "plan_{}.json".format(step)).write_text(
        json.dumps(plan, indent=2), encoding="utf-8")
    report(plan, skipped, unanswered, d.get("warnings", []) if step == 1 else [])

    done, failed = _apply_plan(page, plan)
    print("step {}: filled {}, failed {}".format(step, len(done), len(failed)), flush=True)
    for x in done:
        print("  OK   " + x, flush=True)
    for x in failed:
        print("  MISS " + x, flush=True)
    if unanswered:
        print("NEEDS AN ANSWER ({}):".format(len(unanswered)), flush=True)
        for u in unanswered:
            print("  ? {} [{}] {}".format(
                u.get("label", "")[:70], u.get("type"),
                " | ".join(u.get("options", [])[:6])), flush=True)
    return sid, unanswered


def cmd_apply(args):
    """One browser session, all the way through a multi-step form.

    open -> Apply -> (you log in) -> plan+fill step -> you click Next ->
    plan+fill the next step -> ... -> you submit and close the window.
    """
    from playwright.sync_api import sync_playwright

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        ctx = _browser(pw, args.browser)
        page = _page(ctx, args.url)

        for _ in range(2):
            clicked, page = _click_apply(ctx, page)
            if not clicked:
                break
            print("  clicked Apply -> " + page.url[:110], flush=True)

        fields, page = _wait_for_form(ctx, page, args.min, args.timeout)
        if not fields:
            print("NO FORM FOUND after {}s.".format(args.timeout), flush=True)
            _hold(ctx, page, "No form detected -- drive it manually if you like.", args.hold)
            ctx.close()
            return 1

        # Pin to the tab holding the form; never wander back to the job advert.
        print("\nform: {} controls on {}".format(len(fields), page.url[:100]), flush=True)
        sid, _ = _plan_step(args.key, page, fields, work, 1)
        if sid:
            print("SESSION {}   (apply_cli done {} after you submit)".format(sid, sid),
                  flush=True)

        print("\nFilled. Click Next / Continue and I'll fill each following step.", flush=True)
        print("Close the browser window when the application is submitted.", flush=True)

        seen = {_signature(fields)}
        step, waited = 1, 0
        while waited < args.hold:
            if page.is_closed() or not _live(ctx):
                print("BROWSER CLOSED - finished.", flush=True)
                break
            try:
                page.wait_for_timeout(4000)
                waited += 4
                cur = page.evaluate(JS_SCAN)
            except Exception:
                print("BROWSER CLOSED - finished.", flush=True)
                break
            if len(cur) < args.min:
                continue
            sig = _signature(cur)
            if sig in seen or _is_login(page, cur):
                continue
            seen.add(sig)
            step += 1
            print("\n--- step {}: {} controls on {} ---".format(
                step, len(cur), page.url[:90]), flush=True)
            _plan_step(args.key, page, cur, work, step)
            print("Filled. Continue, or close the window when submitted.", flush=True)

        ctx.close()
    return 0


CDP_PORT = 9222


def cmd_serve(args):
    """Launch YOUR browser with a debug port, then get out of the way.

    You drive it normally -- browse, log in, click Apply. When a form needs
    filling, `attach` connects to this same window and fills it.
    """
    cfg = BROWSERS[args.browser]
    n = _running(cfg["proc"])
    if n:
        print("{} is running ({} procs). Close it first so it can be relaunched\n"
              "with the debug port.".format(args.browser.title(), n), flush=True)
        return 2
    exe = cfg["exe"]
    if not (exe and exe.exists()):
        print("no executable for " + args.browser, flush=True)
        return 2
    cmd = [str(exe),
           "--remote-debugging-port={}".format(args.port),
           "--user-data-dir={}".format(cfg["user_data"]),
           "--profile-directory=Default",
           "--restore-last-session"]
    subprocess.Popen(cmd, close_fds=True)
    print("launched {} with debug port {}".format(args.browser, args.port), flush=True)
    print("Use it normally. I attach to this window when you need a form filled.",
          flush=True)
    return 0


def _cdp(pw, port):
    return pw.chromium.connect_over_cdp("http://127.0.0.1:{}".format(port))


def _target_page(browser):
    """The tab YOU are looking at.

    Ranked by focus first, then visibility, then how much of a form it has --
    so the tab on screen wins even if another tab has more inputs.
    """
    best, best_score, fields = None, None, []
    for ctx in browser.contexts:
        for p in ctx.pages:
            try:
                if p.url.startswith(("about:", "chrome:", "brave:", "devtools:")):
                    continue
                state = p.evaluate(
                    "() => ({focus: document.hasFocus(),"
                    " visible: document.visibilityState === 'visible'})")
                got = p.evaluate(JS_SCAN)
            except Exception:
                continue
            score = (bool(state.get("focus")), bool(state.get("visible")), len(got))
            if best_score is None or score > best_score:
                best, best_score, fields = p, score, got
    if best is not None:
        print("tab: focused={} visible={} controls={}".format(*best_score), flush=True)
    return best, fields


def guess_job(page, limit: int = 5):
    """Work out which queued job this page belongs to, so you needn't name it.

    Matches the company name against the page title/URL; falls back to the
    LinkedIn/ATS url stored on the job.
    """
    import sqlite3
    con = sqlite3.connect(ROOT / "data" / "resume.db")
    try:
        blob = ((page.title() or "") + " " + page.url).lower()
    except Exception:
        blob = page.url.lower()

    hits = []
    for key, company, title, data in con.execute(
            "select key_id, company, title, data from jobs where applied = 0"):
        d = json.loads(data)
        if d.get("irrelevant"):
            continue
        url = (d.get("apply_url") or "").lower()
        score = 0
        co = (company or "").strip().lower()
        # strip the usual corporate suffixes before matching
        co_core = re.sub(r"\b(inc|ltd|llc|corp|corporation|limited|group|canada)\b\.?", "",
                         co).strip(" .,-")
        if co_core and len(co_core) > 3 and co_core in blob:
            score += 3
        if url and url in blob:
            score += 5
        for tok in re.findall(r"[a-z0-9]{4,}", url):
            if tok in blob and tok not in ("https", "http", "www", "jobs", "linkedin",
                                           "indeed", "careers", "com"):
                score += 1
        if score:
            hits.append((score, key, company, title))
    hits.sort(reverse=True)
    return hits[:limit]


def cmd_attach(args):
    """Connect to the browser you're already driving and fill the form on screen."""
    from playwright.sync_api import sync_playwright

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        try:
            browser = _cdp(pw, args.port)
        except Exception as e:
            print("Could not attach on port {} ({}).".format(args.port, type(e).__name__),
                  flush=True)
            print("Start the browser with:  apply_browser serve", flush=True)
            return 2

        page, fields = _target_page(browser)
        if not page:
            print("No open tab with a form.", flush=True)
            return 1
        print("attached: {} controls on {}".format(len(fields), page.url[:100]), flush=True)

        key = args.key
        if key in ("", "auto", None):
            hits = guess_job(page)
            if not hits:
                print("Could not tell which job this is -- pass --key <key_id>.", flush=True)
                return 1
            print("job guess:", flush=True)
            for sc, k, co, ti in hits:
                print("  {:3}  {}  {}  {}".format(sc, k, (co or "")[:26], (ti or "")[:40]),
                      flush=True)
            if len(hits) > 1 and hits[0][0] == hits[1][0]:
                print("AMBIGUOUS - pass --key to pick one.", flush=True)
                return 1
            key = hits[0][1]
            print("using {}  {} - {}".format(key, hits[0][2], hits[0][3]), flush=True)

        if len(fields) < args.min:
            print("Too few controls to be a form -- open the application page first.",
                  flush=True)
            for f in fields:
                print("  [{}] {}".format(f["type"], f["label"][:70]), flush=True)
            return 1
        try:
            page.bring_to_front()
        except Exception:
            pass
        sid, _ = _plan_step(key, page, fields, work, args.step)
        if sid:
            print("SESSION {}   (apply_cli done {} after you submit)".format(sid, sid),
                  flush=True)
        browser.close()          # detaches only; your window stays open
    return 0


def cmd_scan(args):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _browser(pw, args.browser)
        page = _page(ctx, args.url)
        if args.apply:
            for _ in range(2):
                clicked, page = _click_apply(ctx, page)
                if not clicked:
                    break
                print("  clicked Apply -> " + page.url[:110], flush=True)
        fields, page = _wait_for_form(ctx, page, args.min, args.timeout)
        Path(args.out).write_text(json.dumps(fields, indent=2), encoding="utf-8")
        print("{} controls -> {}".format(len(fields), args.out))
        print("FINAL URL: " + page.url)
        for f in fields:
            print("  {} [{:8}] {:60} {}".format(
                "*" if f["required"] else " ", f["type"], f["label"][:60], f["selector"]))
        ctx.close()


def cmd_fill(args):
    from playwright.sync_api import sync_playwright
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    with sync_playwright() as pw:
        ctx = _browser(pw, args.browser)
        page = _page(ctx, plan.get("url") or plan.get("apply_url"))
        done, failed = _apply_plan(page, plan)
        print("filled {}, failed {}".format(len(done), len(failed)))
        for d in done:
            print("  OK   " + d)
        for f in failed:
            print("  MISS " + f)
        _hold(ctx, page,
              "FORM FILLED. Review it, fix anything marked MISS, then submit yourself.",
              args.hold)
        ctx.close()


def cmd_open(args):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _browser(pw, args.browser)
        page = _page(ctx, args.url)
        _hold(ctx, page, "Page open. Click Apply / sign in as needed.", args.hold)
        print("LANDED ON: " + page.url)
        ctx.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="apply_browser")
    ap.add_argument("--browser", default="brave", choices=["brave", "chrome", "isolated"],
                    help="which real browser profile to drive (default: brave)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("apply", help="open -> Apply -> wait for login -> plan -> fill")
    a.add_argument("url")
    a.add_argument("--key", required=True, help="job key_id from the DB")
    a.add_argument("--work", required=True, help="scratch dir for fields/plan json")
    a.add_argument("--min", type=int, default=3)
    a.add_argument("--timeout", type=int, default=1500,
                   help="seconds to wait for the form, including your login")
    a.add_argument("--hold", type=int, default=2400)
    a.set_defaults(fn=cmd_apply)

    sv = sub.add_parser("serve", help="launch your browser with a debug port; you drive it")
    sv.add_argument("--port", type=int, default=CDP_PORT)
    sv.set_defaults(fn=cmd_serve)

    at = sub.add_parser("attach", help="fill the form in the browser you're driving")
    at.add_argument("--key", default="auto",
                help="job key_id, or 'auto' to detect it from the page")
    at.add_argument("--work", required=True)
    at.add_argument("--port", type=int, default=CDP_PORT)
    at.add_argument("--min", type=int, default=2)
    at.add_argument("--step", type=int, default=1)
    at.set_defaults(fn=cmd_attach)

    s = sub.add_parser("scan")
    s.add_argument("url")
    s.add_argument("--out", default="fields.json")
    s.add_argument("--apply", action="store_true", help="click an Apply button first")
    s.add_argument("--min", type=int, default=4)
    s.add_argument("--timeout", type=int, default=240)
    s.set_defaults(fn=cmd_scan)

    f = sub.add_parser("fill")
    f.add_argument("plan")
    f.add_argument("--hold", type=int, default=1800)
    f.set_defaults(fn=cmd_fill)

    o = sub.add_parser("open")
    o.add_argument("url")
    o.add_argument("--hold", type=int, default=1800)
    o.set_defaults(fn=cmd_open)

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
