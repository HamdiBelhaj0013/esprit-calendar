"""ESPRIT timetable PDF → Google Calendar + email.

No script ever touches the ESPRIT portal: you click "Télécharger PDF" in your own browser,
and the watcher picks the file up from your Downloads folder.

  python main.py --watch                 # keep watching Downloads (what the Windows task runs, hidden)
  python main.py --watch --once          # scan Downloads once and exit (handy to test)
  python main.py --pdf emploi.pdf        # process one PDF by hand
  python main.py --pdf emploi.pdf --no-sync --no-mail   # just produce out/EDT_xxx.ics
  python main.py --pdf emploi.pdf --dry-run --no-mail   # show calendar changes without applying them

Settings come from .env (on your PC) or env vars: GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_CALENDAR_ID,
SMTP_USER, SMTP_APP_PASSWORD, MAIL_TO (optional), DOWNLOADS_DIR (optional), PDF_PATTERN (optional).
"""
from __future__ import annotations

import argparse
import os
import shutil
import smtplib
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from esprit_edt import parse_pdf, to_ics

JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "archive"
LOGS = HERE / "logs"


# ---------------------------------------------------------------- settings
def load_env(path: Path = HERE / ".env"):
    """Read KEY=value lines from .env (used when running on your PC). Real env vars win."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    sa = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if sa and not sa.lstrip().startswith("{") and not Path(sa).is_absolute():
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = str(HERE / sa)  # key file next to the script


def downloads_dir() -> Path:
    if os.getenv("DOWNLOADS_DIR"):
        return Path(os.path.expandvars(os.environ["DOWNLOADS_DIR"])).expanduser()
    if os.name == "nt":  # the real Downloads folder, even if it was moved (OneDrive, other drive…)
        try:
            import winreg

            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                value, _ = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")
                return Path(os.path.expandvars(value))
        except OSError:
            pass
    return Path.home() / "Downloads"


# ---------------------------------------------------------------- email
def _smtp_send(msg: EmailMessage):
    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.gmail.com"), 465) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_APP_PASSWORD"])
        s.send_message(msg)


def send_mail(weeks, pdfs: list[Path], ics: Path, reports: list[dict]):
    user = os.environ["SMTP_USER"]
    to = os.getenv("MAIL_TO", user)
    first, last = weeks[0], weeks[-1]

    lines = []
    for wk in weeks:
        lines.append(f"Semaine du {wk.start:%d/%m} au {wk.end:%d/%m/%Y} — {len(wk.sessions)} séances")
        for s in wk.sessions:
            lines.append(f"  • {JOURS[s.start.weekday()]} {s.start:%d/%m}  {s.start:%H:%M}-{s.end:%H:%M}  "
                         f"{s.summary}  ({s.room})")
        lines.append("")
    changes = {k: sum((r[k] for r in reports), []) for k in ("added", "updated", "removed")} if reports else None
    if changes:
        lines.append("Google Calendar :")
        for k, label in (("added", "ajoutées"), ("updated", "modifiées"), ("removed", "supprimées")):
            lines.append(f"  {len(changes[k])} {label}" + "".join(f"\n    - {x}" for x in changes[k]))

    msg = EmailMessage()
    flag = " ⚠️ changements" if changes and (changes["updated"] or changes["removed"]) else ""
    msg["Subject"] = f"📅 EDT {first.class_name} — {first.start:%d/%m} → {last.end:%d/%m}{flag}"
    msg["From"], msg["To"] = user, to
    msg.set_content("\n".join(lines))
    for f in pdfs:
        msg.add_attachment(f.read_bytes(), maintype="application", subtype="pdf", filename=f.name)
    msg.add_attachment(ics.read_bytes(), maintype="text", subtype="calendar", filename=ics.name)
    _smtp_send(msg)
    print(f"Mail sent to {to}")


# ---------------------------------------------------------------- pipeline
class NotATimetable(ValueError):
    pass


def process(pdfs: list[Path], out: Path, sync=True, mail=True, dry_run=False):
    weeks = [wk for p in pdfs for wk in parse_pdf(p)]
    if not weeks:
        raise NotATimetable("No timetable found in the PDF — the layout may have changed.")
    for wk in weeks:
        print(f"{wk.class_name} {wk.start} → {wk.end}: {len(wk.sessions)} séances")
        for s in wk.sessions:
            print(f"  {s.start:%a %d/%m %H:%M}-{s.end:%H:%M}  {s.summary}  [{s.room}]")

    out.mkdir(parents=True, exist_ok=True)
    ics = to_ics(weeks, out / f"EDT_{weeks[0].class_name}.ics")
    print(f"Wrote {ics}")

    reports = []
    if sync:
        from gcal_sync import get_service, sync_week

        service, cal_id = get_service(), os.environ["GOOGLE_CALENDAR_ID"]
        for wk in weeks:
            r = sync_week(service, cal_id, wk, dry_run=dry_run)
            reports.append(r)
            print(f"Calendar {wk.start}: +{len(r['added'])} ~{len(r['updated'])} -{len(r['removed'])}")
    if mail and os.getenv("SMTP_USER") and os.getenv("SMTP_APP_PASSWORD"):
        send_mail(weeks, pdfs, ics, reports)
    elif mail:
        print("Mail skipped (SMTP_USER / SMTP_APP_PASSWORD not set)")
    return weeks


# ---------------------------------------------------------------- Downloads watcher
def _archive(pdf: Path, weeks, failed=False) -> Path:
    ARCHIVE.mkdir(exist_ok=True)
    if failed or not weeks:
        name = f"_not_a_timetable_{pdf.name}"
    else:
        name = f"EDT_{weeks[0].class_name}_{weeks[0].start:%Y-%m-%d}.pdf"
    dest = ARCHIVE / name
    n = 2
    while dest.exists():
        dest = ARCHIVE / f"{Path(name).stem} ({n}).pdf"
        n += 1
    shutil.move(str(pdf), str(dest))
    return dest


def _stable(f: Path) -> bool:
    """True once the download is finished (size stops changing)."""
    try:
        a = f.stat().st_size
        time.sleep(1.5)
        return a > 0 and f.stat().st_size == a
    except OSError:
        return False


def scan(folder: Path, pattern: str, out: Path, max_age_days: int, retry_at: dict, sync=True, mail=True) -> int:
    done = 0
    now = time.time()
    for pdf in sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime):
        if now - pdf.stat().st_mtime > max_age_days * 86400:
            continue  # old download, leave it alone
        if retry_at.get(pdf, 0) > now or not _stable(pdf):
            continue
        print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] New file: {pdf.name}")
        try:
            weeks = process([pdf], out, sync=sync, mail=mail)
        except NotATimetable as e:
            print(f"  skipped: {e} → {_archive(pdf, None, failed=True).name}")
            continue
        except Exception as e:  # no internet, Google/Gmail error… → retry in 5 min
            print(f"  ERROR {type(e).__name__}: {e} — retrying in 5 min")
            retry_at[pdf] = now + 300
            continue
        print(f"  archived as {_archive(pdf, weeks).name}")
        retry_at.pop(pdf, None)
        done += 1
    return done


def _single_instance():
    """Only one watcher at a time (the logon task + a manual start must not both run)."""
    LOGS.mkdir(exist_ok=True)
    fh = open(LOGS / "watch.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another watcher is already running — exiting.")
        sys.exit(0)
    return fh


def _log_to_file():
    """pythonw (hidden window) has no console: send output to logs/watch.log."""
    LOGS.mkdir(exist_ok=True)
    log = LOGS / "watch.log"
    if log.exists() and log.stat().st_size > 1_000_000:
        log.replace(LOGS / "watch.old.log")
    sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)


def watch(once=False, sync=True, mail=True, out: Path = HERE / "out"):
    folder = downloads_dir()
    pattern = os.getenv("PDF_PATTERN", "emploi_du_temps*.pdf")
    max_age = int(os.getenv("MAX_AGE_DAYS", "14"))
    interval = int(os.getenv("WATCH_INTERVAL", "15"))
    retry_at: dict = {}
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Watching {folder} for {pattern} (every {interval}s)")
    while True:
        try:
            scan(folder, pattern, out, max_age, retry_at, sync=sync, mail=mail)
        except Exception as e:
            print(f"scan error: {type(e).__name__}: {e}")
        if once:
            return
        time.sleep(interval)


# ---------------------------------------------------------------- CLI
def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", nargs="*", help="process these PDF file(s)")
    ap.add_argument("--watch", action="store_true", help="watch the Downloads folder for new timetable PDFs")
    ap.add_argument("--once", action="store_true", help="with --watch: scan once and exit")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--no-sync", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="show calendar changes without applying them")
    args = ap.parse_args()

    if args.watch:
        if sys.stdout is None or os.getenv("LOG_TO_FILE") == "1":
            _log_to_file()
        lock = _single_instance()  # noqa: F841  (kept open for the process lifetime)
        watch(once=args.once, sync=not args.no_sync, mail=not args.no_mail, out=Path(args.out))
    elif args.pdf:
        try:
            process([Path(p) for p in args.pdf], Path(args.out), sync=not args.no_sync,
                    mail=not args.no_mail, dry_run=args.dry_run)
        except NotATimetable as e:
            raise SystemExit(str(e))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
