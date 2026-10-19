"""Download the ESPRIT timetable PDF(s) from arp.esprit.tn, exactly like clicking "Télécharger PDF".

The login page has a reCAPTCHA, so the script never logs in by itself:
  1. `python fetch_edt.py --login` (or login.bat) opens a browser window. You log in yourself
     (username/password are pre-filled from .env, you tick the captcha). The session is saved
     in ./browser-profile/.
  2. The weekly run reuses that saved session in the background.
  3. When ESPRIT expires the session, the run stops with SessionExpired → main.py emails you
     to run login.bat again.

Selectors are configurable through env vars. On failure a screenshot + HTML dump goes to ./debug/.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

from esprit_edt import parse_pdf

HERE = Path(__file__).resolve().parent
BASE = os.getenv("ESPRIT_BASE_URL", "https://arp.esprit.tn")
EDT_URL = BASE + "/online/edt"
PROFILE = Path(os.getenv("BROWSER_PROFILE", HERE / "browser-profile"))
SESSION_STORAGE = PROFILE / "session_storage.json"
DEBUG = HERE / "debug"

SEL_USER = os.getenv("SEL_USER", 'input[type="email"], input[name="username"], input[name="login"], '
                                 'input[name="identifiant"], input[autocomplete="username"], input[type="text"]')
SEL_PASS = os.getenv("SEL_PASS", 'input[type="password"]')
SEL_PDF = os.getenv("SEL_PDF", 'button:has-text("charger PDF"), a:has-text("charger PDF")')
SEL_NEXT = os.getenv("SEL_NEXT", ".fc-next-button")
LOGIN_MARK = os.getenv("LOGIN_URL_MARK", "/auth/")   # login page URL: /auth/jwt/login?returnTo=...


class SessionExpired(RuntimeError):
    pass


def _debug(page, name: str):
    DEBUG.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG / f"{name}.png"), full_page=True)
        (DEBUG / f"{name}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def _check_blocked(page):
    """ESPRIT's firewall answers datacenter IPs (GitHub Actions, VPS…) with a 'Web Page Blocked!' page."""
    try:
        body = page.inner_text("body", timeout=5000)
    except Exception:
        return
    if "Web Page Blocked" in body or "Attack ID" in body:
        _debug(page, "blocked")
        raise RuntimeError("ESPRIT's firewall blocked this connection. Run it from your own network (your PC), "
                           "not from a server. If it happens on your PC, set HEADLESS=0 in .env. See debug/blocked.png")


def _open_context(p, headless: bool):
    PROFILE.mkdir(parents=True, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE), headless=headless, accept_downloads=True, locale="fr-FR",
        timezone_id="Africa/Tunis", viewport={"width": 1600, "height": 1000},
    )
    # Some apps keep their login token in sessionStorage, which a browser profile doesn't keep → restore it.
    if SESSION_STORAGE.exists():
        data = SESSION_STORAGE.read_text(encoding="utf-8")
        ctx.add_init_script(
            "(() => { try { if (location.origin !== %s) return; const d = %s;"
            " for (const k in d) if (sessionStorage.getItem(k) === null) sessionStorage.setItem(k, d[k]); }"
            " catch (e) {} })();" % (json.dumps(BASE), data)
        )
    return ctx


def _wait_logged_in_or_login(page, timeout_s: float = 25) -> str:
    """Return 'ok' once the timetable's PDF button is visible, 'login' if we land on the login page."""
    end = time.time() + timeout_s
    pdf = page.locator(SEL_PDF).first
    while time.time() < end:
        if LOGIN_MARK in page.url:
            return "login"
        try:
            if pdf.is_visible():
                return "ok"
        except Exception:
            pass
        page.wait_for_timeout(500)
    return "timeout"


def login(headless: bool = False, wait_s: int = 300) -> None:
    """Open a browser window so YOU log in (captcha included). Saves the session for the weekly runs."""
    with sync_playwright() as p:
        ctx = _open_context(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(EDT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        _check_blocked(page)

        if LOGIN_MARK in page.url:
            user, pwd = os.getenv("ESPRIT_USERNAME", ""), os.getenv("ESPRIT_PASSWORD", "")
            try:
                if user:
                    page.locator(SEL_USER).first.fill(user, timeout=10000)
                if pwd:
                    page.locator(SEL_PASS).first.fill(pwd, timeout=10000)
            except PWTimeout:
                pass
            print("➡  Log in in the browser window (tick 'Je ne suis pas un robot', then 'Se connecter').")

        end = time.time() + wait_s
        while LOGIN_MARK in page.url and time.time() < end:
            page.wait_for_timeout(500)
        if LOGIN_MARK in page.url:
            ctx.close()
            raise RuntimeError("Login not completed in time — run login again.")

        page.wait_for_timeout(1500)
        if "/online/edt" not in page.url:
            page.goto(EDT_URL, wait_until="domcontentloaded", timeout=60000)
        state = _wait_logged_in_or_login(page, 30)
        try:
            ss = page.evaluate("() => Object.fromEntries(Object.entries(sessionStorage))")
            SESSION_STORAGE.write_text(json.dumps(ss), encoding="utf-8")
        except Exception:
            pass
        ctx.close()
    if state != "ok":
        raise RuntimeError("Logged in, but the timetable page didn't show the PDF button. See debug/.")
    print("✅ Session saved. The weekly run will reuse it.")


def _download(page, out: Path) -> Path:
    btn = page.locator(SEL_PDF).first
    btn.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(2500)  # let the calendar finish loading its events
    with page.expect_download(timeout=60000) as dl:
        btn.click()
    dl.value.save_as(str(out))
    return out


def fetch_pdfs(out_dir: str | Path = "out", weeks: int = 1, today: date | None = None,
               headless: bool | None = None) -> list[Path]:
    """Download `weeks` PDFs starting from the upcoming week (skips a week that is already over)."""
    today = today or date.today()
    if headless is None:
        headless = os.getenv("HEADLESS", "1") != "0"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    with sync_playwright() as p:
        ctx = _open_context(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(EDT_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1000)
            _check_blocked(page)
            state = _wait_logged_in_or_login(page)
            if state == "login":
                raise SessionExpired("ESPRIT session expired — run login.bat (python fetch_edt.py --login)")
            if state != "ok":
                _debug(page, "error")
                raise RuntimeError("Timetable page didn't show the 'Télécharger PDF' button. See debug/error.png")

            pdf = _download(page, out_dir / "edt_tmp.pdf")
            parsed = parse_pdf(pdf)
            # On Sunday the portal may still show the week that just ended → move forward one week.
            if parsed and parsed[0].end < today:
                page.locator(SEL_NEXT).first.click()
                pdf = _download(page, out_dir / "edt_tmp.pdf")
                parsed = parse_pdf(pdf)

            for i in range(weeks):
                if i > 0:
                    page.locator(SEL_NEXT).first.click()
                    pdf = _download(page, out_dir / "edt_tmp.pdf")
                    parsed = parse_pdf(pdf)
                wk = parsed[0] if parsed else None
                name = f"EDT_{wk.class_name}_{wk.start:%Y-%m-%d}.pdf" if wk else f"EDT_week{i + 1}.pdf"
                final = out_dir / name
                pdf.replace(final)
                paths.append(final)
        except SessionExpired:
            raise
        except Exception:
            _debug(page, "error")
            raise
        finally:
            ctx.close()
    return paths


if __name__ == "__main__":
    # python fetch_edt.py --login      → log in once (browser window opens)
    # python fetch_edt.py [weeks] [--show]   → test a download (--show = visible window)
    import sys

    from main import load_env

    load_env()
    if "--login" in sys.argv:
        login()
    else:
        nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
        print(fetch_pdfs(HERE / "out", weeks=nums[0] if nums else 1,
                         headless=False if "--show" in sys.argv else None))
