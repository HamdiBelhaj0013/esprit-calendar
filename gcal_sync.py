"""Sync parsed ESPRIT sessions into a Google Calendar (via a service account).

Only events created by this tool are touched (tagged with a private extended property),
so anything you add yourself to the same calendar is left alone.
For each week in the PDF:   new session → insert   changed → update   gone → delete
"""
from __future__ import annotations

import json
import os
from datetime import datetime, time, timedelta

from esprit_edt import TZ, Week

TAG = "esprit_edt"
COLORS = {"Épreuve": "11", "Événement": "5"}  # Tomato for exams, Banana for events; Cours = calendar colour


def get_service(sa_json: str | None = None):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_json = sa_json or os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(sa_json) if sa_json.strip().startswith("{") else json.load(open(sa_json))
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar.events"]
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _body(s) -> dict:
    body = {
        "summary": s.summary,
        "location": s.room,
        "description": s.description,
        "start": {"dateTime": s.start.isoformat(), "timeZone": "Africa/Tunis"},
        "end": {"dateTime": s.end.isoformat(), "timeZone": "Africa/Tunis"},
        "extendedProperties": {"private": {"src": TAG, "key": s.key, "fp": s.fingerprint}},
    }
    if s.kind in COLORS:
        body["colorId"] = COLORS[s.kind]
    return body


def _existing(service, calendar_id: str, week: Week) -> list[dict]:
    t_min = datetime.combine(week.start, time.min, TZ).isoformat()
    t_max = datetime.combine(week.end + timedelta(days=1), time.min, TZ).isoformat()
    items, token = [], None
    while True:
        res = service.events().list(
            calendarId=calendar_id, timeMin=t_min, timeMax=t_max, singleEvents=True,
            privateExtendedProperty=f"src={TAG}", pageToken=token, maxResults=250,
        ).execute()
        items += res.get("items", [])
        token = res.get("nextPageToken")
        if not token:
            return items


def sync_week(service, calendar_id: str, week: Week, dry_run: bool = False) -> dict:
    """Returns {"added": [...], "updated": [...], "removed": [...]} (event summaries)."""
    current = {e["extendedProperties"]["private"]["key"]: e for e in _existing(service, calendar_id, week)}
    wanted = {s.key: s for s in week.sessions}
    report = {"added": [], "updated": [], "removed": []}

    for key, s in wanted.items():
        label = f"{s.start:%a %d/%m %H:%M} {s.summary}"
        if key not in current:
            report["added"].append(label)
            if not dry_run:
                service.events().insert(calendarId=calendar_id, body=_body(s)).execute()
        elif current[key]["extendedProperties"]["private"].get("fp") != s.fingerprint:
            report["updated"].append(label)
            if not dry_run:
                service.events().update(calendarId=calendar_id, eventId=current[key]["id"], body=_body(s)).execute()

    for key, ev in current.items():
        if key not in wanted:
            report["removed"].append(f"{ev['start'].get('dateTime', '')[:16]} {ev.get('summary', '')}")
            if not dry_run:
                service.events().delete(calendarId=calendar_id, eventId=ev["id"]).execute()
    return report
