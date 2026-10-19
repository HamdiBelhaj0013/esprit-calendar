"""Weekly ESPRIT timetable → Google Calendar + email with the fresh PDF.

  python main.py                         # full run: download from portal, sync Google Calendar, email PDF
  python main.py --pdf my.pdf            # use a PDF you already downloaded (skips the portal)
  python main.py --pdf my.pdf --no-sync --no-mail   # just produce out/*.ics (local test)
  python main.py --weeks 2               # also grab the following week

Env vars (GitHub secrets): ESPRIT_USERNAME, ESPRIT_PASSWORD, GOOGLE_SERVICE_ACCOUNT_JSON,
GOOGLE_CALENDAR_ID, SMTP_USER, SMTP_APP_PASSWORD, MAIL_TO (optional, defaults to SMTP_USER).
"""
from __future__ import annotations

import argparse
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from esprit_edt import parse_pdf, to_ics

JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]


def send_mail(weeks, pdfs: list[Path], ics: Path, reports: list[dict]):
    user, pwd = os.environ["SMTP_USER"], os.environ["SMTP_APP_PASSWORD"]
    to = os.getenv("MAIL_TO", user)
    first, last = weeks[0], weeks[-1]

    lines = []
    for wk in weeks:
        lines.append(f"Semaine du {wk.start:%d/%m} au {wk.end:%d/%m/%Y} — {len(wk.sessions)} séances")
        for s in wk.sessions:
            lines.append(f"  • {JOURS[s.start.weekday()]} {s.start:%d/%m}  {s.start:%H:%M}-{s.end:%H:%M}  {s.summary}  ({s.room})")
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

    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.gmail.com"), 465) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"Mail sent to {to}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", nargs="*", help="use local PDF(s) instead of downloading from the portal")
    ap.add_argument("--weeks", type=int, default=int(os.getenv("WEEKS", "1")))
    ap.add_argument("--out", default="out")
    ap.add_argument("--no-sync", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="show calendar changes without applying them")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(exist_ok=True)

    if args.pdf:
        pdfs = [Path(p) for p in args.pdf]
    else:
        from fetch_edt import fetch_pdfs
        pdfs = fetch_pdfs(os.environ["ESPRIT_USERNAME"], os.environ["ESPRIT_PASSWORD"], out, weeks=args.weeks)

    weeks = [wk for p in pdfs for wk in parse_pdf(p)]
    if not weeks:
        raise SystemExit("No timetable found in the PDF — the layout may have changed.")
    for wk in weeks:
        print(f"{wk.class_name} {wk.start} → {wk.end}: {len(wk.sessions)} séances")
        for s in wk.sessions:
            print(f"  {s.start:%a %d/%m %H:%M}-{s.end:%H:%M}  {s.summary}  [{s.room}]")

    ics = to_ics(weeks, out / f"EDT_{weeks[0].class_name}.ics")
    print(f"Wrote {ics}")

    reports = []
    if not args.no_sync:
        from gcal_sync import get_service, sync_week
        service, cal_id = get_service(), os.environ["GOOGLE_CALENDAR_ID"]
        for wk in weeks:
            r = sync_week(service, cal_id, wk, dry_run=args.dry_run)
            reports.append(r)
            print(f"Calendar {wk.start}: +{len(r['added'])} ~{len(r['updated'])} -{len(r['removed'])}")

    if not args.no_mail:
        send_mail(weeks, pdfs, ics, reports)


if __name__ == "__main__":
    main()
