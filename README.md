# ESPRIT timetable → Google Calendar

You click **Télécharger PDF** on arp.esprit.tn in your normal browser. Within ~15 seconds a small background
watcher on your PC notices `emploi_du_temps_….pdf` in your Downloads folder and:

1. reads the PDF (module, teacher, room, times, Cours / Épreuve / Événement),
2. syncs the **ESPRIT 4CCE5** Google Calendar: new sessions added, changed ones updated, cancelled ones removed,
3. **emails you the PDF** + an `.ics` file, with a summary of what changed,
4. moves the PDF to `archive\EDT_4CCE5_<week>.pdf`.

Exams (Épreuve) show in red, events (Événement) in yellow. Events you add yourself to the calendar are never touched.
Downloading the same week again is safe: only real changes are applied.

> **Why not fully automatic?** ESPRIT's portal blocks automated access (firewall on servers, reCAPTCHA on
> login, and the timetable doesn't load in automated browsers). So no script touches the portal: you
> download the PDF yourself (one click), everything after that is automatic.

---

## Setup (once)

### 1. Google side
- **Service account:** Google Cloud console → project → enable **Google Calendar API** →
  IAM & Admin → Service Accounts → create → Keys → Add key → JSON.
- **Calendar:** Google Calendar → Autres agendas **+** → Créer un agenda `ESPRIT 4CCE5` →
  Partager avec des personnes spécifiques → add the service account email → **Apporter des modifications aux événements** →
  copy **ID de l'agenda** (`…@group.calendar.google.com`).
- **Gmail app password:** https://myaccount.google.com/apppasswords (needs 2-Step Verification).

### 2. On your PC (Windows, PowerShell in the project folder)
```powershell
git pull
pip install -r requirements.txt
copy .env.example .env      # skip if you already have one
notepad .env
```
- Put the service account key in the folder as `service-account.json`.
- In `.env`: calendar ID, Gmail address, app password.

`.env`, `*.json` and `archive/` are git-ignored: your key, passwords and PDFs never get pushed.

### 3. Start the watcher
```powershell
powershell -ExecutionPolicy Bypass -File .\install_task.ps1
```
It starts now (hidden, no window) and at every Windows logon. If you get "Access denied", run it from PowerShell as administrator.

### 4. Weekly reminder
In Google Calendar create a recurring event **"📥 Télécharger l'EDT"** — every Sunday 20:00 — with a notification,
and put `https://arp.esprit.tn/online/edt` in the description so it's one tap away.

---

## Each week
Open the portal → **Emploi Du Temps** → **Télécharger PDF**. That's it: calendar + email follow automatically.
Want next week too? Click **›** on the portal and download again.

**From your phone (PC off):** download the PDF on the phone, then in the GitHub repo **inbox/ → Add file → Upload files** → commit.
The GitHub Action syncs the calendar and emails you. Repo secrets needed: `GOOGLE_SERVICE_ACCOUNT_JSON` (whole JSON content),
`GOOGLE_CALENDAR_ID`, `SMTP_USER`, `SMTP_APP_PASSWORD` (+ optional `MAIL_TO`).

---

## Apple Calendar
- **iPhone/iPad:** Settings → Apps → Calendar → Calendar Accounts → Add Account → Google, then open
  https://calendar.google.com/calendar/syncselect and tick **ESPRIT 4CCE5**.
- **Mac:** System Settings → Internet Accounts → Google → Calendars on.

---

## Troubleshooting
Everything the watcher does is in **`logs\watch.log`**.

| Problem | Fix |
|---|---|
| Nothing happens after downloading | Check `logs\watch.log`. Is the file named `emploi_du_temps…pdf` and in the folder shown on the "Watching …" line? If not, set `DOWNLOADS_DIR` / `PDF_PATTERN` in `.env`, then restart the watcher (below) |
| `ERROR … retrying in 5 min` | No internet or a Google/Gmail problem; it retries by itself |
| Google `404 Not Found` | Wrong calendar ID, or the calendar isn't shared with the service account |
| Google `403` | Calendar API not enabled, or shared with read-only permission |
| SMTP `535` | Use the app password, not your Gmail password |
| `_not_a_timetable_…` in `archive\` | That PDF matched the name pattern but isn't a timetable; ignored |

Restart the watcher after changing `.env`:
```powershell
Stop-ScheduledTask -TaskName "ESPRIT EDT watcher"; Start-ScheduledTask -TaskName "ESPRIT EDT watcher"
```
Remove it: `Unregister-ScheduledTask -TaskName "ESPRIT EDT watcher" -Confirm:$false`

## Commands
```powershell
python main.py --watch --once                 # scan Downloads once, in the console (good first test)
python main.py --pdf emploi.pdf               # process one PDF by hand
python main.py --pdf emploi.pdf --dry-run --no-mail   # show calendar changes without applying them
python main.py --pdf emploi.pdf --no-sync --no-mail   # just make out\EDT_4CCE5.ics
python esprit_edt.py emploi.pdf               # print what the parser reads
```

## Files
- `esprit_edt.py` – PDF parser + `.ics` export
- `gcal_sync.py` – Google Calendar sync (add / update / remove, only its own events)
- `main.py` – Downloads watcher, pipeline, email
- `install_task.ps1` – starts the watcher hidden at every logon
- `.github/workflows/weekly-edt.yml` – phone fallback: sync a PDF uploaded to `inbox/`
