# ESPRIT timetable → Google Calendar (every Sunday)

Every Sunday at 20:00, a scheduled task **on your PC**:

1. logs into **arp.esprit.tn** with a headless browser and clicks **Télécharger PDF** for the coming week,
2. parses the PDF (module, teacher, room, times, Cours / Épreuve / Événement),
3. syncs a dedicated **Google Calendar**: new sessions are added, changed ones updated, cancelled ones removed,
4. **emails you the new PDF** + an `.ics` file, with a summary of what changed.

If the PC is off on Sunday evening, it runs as soon as you turn it on.
Exams (Épreuve) show in red, events (Événement) in yellow. Events you add yourself to the calendar are never touched.

> **Why on your PC and not on GitHub?** ESPRIT's firewall blocks datacenter IPs ("Web Page Blocked!"),
> so the download has to come from your own network, like your normal browser.
> GitHub is still used as a fallback: drop a PDF into `inbox/` and it syncs (see below).

---

## Setup

### 1. Google side (done once)
- **Service account:** Google Cloud console → project → enable **Google Calendar API** →
  IAM & Admin → Service Accounts → create → Keys → Add key → JSON.
- **Calendar:** Google Calendar → Autres agendas **+** → Créer un agenda `ESPRIT 4CCE5` →
  Partager avec des personnes spécifiques → add the service account email → **Apporter des modifications aux événements** →
  copy **ID de l'agenda** (`…@group.calendar.google.com`).
- **Gmail app password:** https://myaccount.google.com/apppasswords (needs 2-Step Verification).

### 2. On your PC (Windows)
In the project folder:
```bat
git pull
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```
- Put the service account key file in the folder and name it `service-account.json`.
- Open `.env` and fill in your ESPRIT login, calendar ID, Gmail and app password.

`.env` and `*.json` are git-ignored, so your passwords and key never get pushed.

### 3. Test
```bat
python main.py --dry-run --no-mail
```
It should print the week's sessions and `Calendar …: +8 ~0 -0` without changing anything. Then the real run:
```bat
python main.py
```
→ events appear in **ESPRIT 4CCE5** and you get the email.

### 4. Schedule it
```powershell
powershell -ExecutionPolicy Bypass -File .\install_task.ps1
```
If you get "Access denied", run that from PowerShell **as administrator**.
Check it in **Planificateur de tâches** (Task Scheduler) → *ESPRIT EDT sync*. Each run writes `logs\last_run.log`.

---

## Apple Calendar
The Google calendar is the hub; Apple reads it:
- **iPhone/iPad:** Settings → Apps → Calendar → Calendar Accounts → Add Account → Google. Then open
  https://calendar.google.com/calendar/syncselect and tick **ESPRIT 4CCE5** (iOS only shows your main calendar until you do this).
- **Mac:** System Settings → Internet Accounts → Google → Calendars on.

---

## Fallback: drop the PDF yourself (works from your phone)
Download the PDF from the portal, then in the GitHub repo: **inbox/ → Add file → Upload files** → commit.
The GitHub Action syncs the calendar and emails you. It needs these repo secrets:
`GOOGLE_SERVICE_ACCOUNT_JSON` (whole JSON content), `GOOGLE_CALENDAR_ID`, `SMTP_USER`, `SMTP_APP_PASSWORD` (+ optional `MAIL_TO`).
The ESPRIT username/password secrets are not needed on GitHub any more.

---

## Troubleshooting
| Problem | Fix |
|---|---|
| `ESPRIT's firewall blocked this connection` on your PC | Add `HEADLESS=0` to `.env` (a visible Chrome window is used) |
| `Login did not complete` | Wrong credentials, or the login page changed → `python fetch_edt.py --show` to watch it, see `debug/` |
| Timeout waiting for `charger PDF` | Look at `debug/error.png`; selectors can be overridden in `.env`: `SEL_USER`, `SEL_PASS`, `SEL_SUBMIT`, `SEL_PDF`, `SEL_NEXT` |
| Google `404 Not Found` | Wrong calendar ID, or the calendar isn't shared with the service account |
| Google `403` | Calendar API not enabled, or shared with read-only permission |
| SMTP `535` | Use the app password, not your Gmail password |

## Commands
```bat
python main.py                                   :: full run (portal → calendar → email)
python main.py --weeks 2                         :: this week + next week
python main.py --pdf emploi.pdf                  :: use a PDF you already have
python main.py --pdf emploi.pdf --no-sync --no-mail   :: just make out\EDT_4CCE5.ics
python main.py --dry-run --no-mail               :: show calendar changes without applying them
python fetch_edt.py --show                       :: watch the browser log in
```

## Files
- `esprit_edt.py` – PDF parser + `.ics` export
- `fetch_edt.py` – portal login + PDF download (Playwright)
- `gcal_sync.py` – Google Calendar sync (add / update / remove, only its own events)
- `main.py` – runs everything + sends the email (reads `.env`)
- `run_edt.bat`, `install_task.ps1` – Windows scheduled task
- `.github/workflows/weekly-edt.yml` – fallback: sync a PDF uploaded to `inbox/`
