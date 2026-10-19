"""Log into arp.esprit.tn with a headless browser and download the timetable PDF(s)
exactly like clicking "Télécharger PDF".

The login form is rendered by JavaScript, so selectors are configurable through env vars
if ESPRIT ever changes its page. On any failure a screenshot + HTML dump is saved in ./debug/.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

from esprit_edt import parse_pdf

BASE = os.getenv("ESPRIT_BASE_URL", "https://arp.esprit.tn")
EDT_URL = BASE + "/online/edt"

SEL_USER = os.getenv("SEL_USER", 'input[type="email"], input[name="username"], input[name="login"], '
                                 'input[name="identifiant"], input[autocomplete="username"], input[type="text"]')
SEL_PASS = os.getenv("SEL_PASS", 'input[type="password"]')
SEL_SUBMIT = os.getenv("SEL_SUBMIT", 'button[type="submit"], input[type="submit"], button:has-text("Connexion"), '
                                     'button:has-text("Se connecter"), button:has-text("Login")')
SEL_PDF = os.getenv("SEL_PDF", 'button:has-text("charger PDF"), a:has-text("charger PDF")')
SEL_NEXT = os.getenv("SEL_NEXT", ".fc-next-button")

DEBUG = Path("debug")


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
        raise RuntimeError("ESPRIT's firewall blocked this connection. Run the script from your own network "
                           "(your PC), not from a server. See debug/blocked.png")


def _login_if_needed(page, user: str, password: str):
    pw = page.locator(SEL_PASS).first
    try:
        pw.wait_for(state="visible", timeout=8000)
    except PWTimeout:
        return  # already logged in (no password field on screen)
    page.locator(SEL_USER).first.fill(user)
    pw.fill(password)
    page.locator(SEL_SUBMIT).first.click()
    try:
        pw.wait_for(state="detached", timeout=30000)
    except PWTimeout:
        _debug(page, "login_failed")
        raise RuntimeError("Login did not complete — check credentials / selectors (see debug/login_failed.png)")


def _download(page, out: Path) -> Path:
    btn = page.locator(SEL_PDF).first
    btn.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(2500)  # let the calendar finish loading its events
    with page.expect_download(timeout=60000) as dl:
        btn.click()
    dl.value.save_as(str(out))
    return out


def fetch_pdfs(user: str, password: str, out_dir: str | Path = "out", weeks: int = 1,
               today: date | None = None, headless: bool | None = None) -> list[Path]:
    """Download `weeks` PDFs starting from the upcoming week (skips a week that is already over)."""
    today = today or date.today()
    if headless is None:
        headless = os.getenv("HEADLESS", "1") != "0"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(accept_downloads=True, locale="fr-FR", timezone_id="Africa/Tunis",
                                  viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()
        try:
            page.goto(EDT_URL, wait_until="networkidle", timeout=60000)
            _check_blocked(page)
            _login_if_needed(page, user, password)
            if "/online/edt" not in page.url:
                page.goto(EDT_URL, wait_until="networkidle", timeout=60000)
                _check_blocked(page)

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
        except Exception:
            _debug(page, "error")
            raise
        finally:
            browser.close()
    return paths


if __name__ == "__main__":
    # Local debugging:  python fetch_edt.py [weeks] [--show]   (--show opens a visible browser window)
    import sys

    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    from main import load_env

    load_env()
    print(fetch_pdfs(os.environ["ESPRIT_USERNAME"], os.environ["ESPRIT_PASSWORD"],
                     weeks=nums[0] if nums else 1, headless=False if "--show" in sys.argv else None))
