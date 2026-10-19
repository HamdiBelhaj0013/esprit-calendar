# ESPRIT timetable → Google Calendar (every Sunday)

Every Sunday at 20:00 (Tunis time), a GitHub Action:

1. logs into **arp.esprit.tn** with a headless browser and clicks **Télécharger PDF** for the coming week,
2. parses the PDF (module, teacher, room, times, Cours / Épreuve / Événement),
3. syncs a dedicated **Google Calendar**: new sessions are added, changed ones updated, cancelled ones removed,
4. **emails you the new PDF** + an `.ics` file, with a summary of what changed.

Exams (Épreuve) show in red, events (Événement) in yellow. Events you add yourself to the calendar are never touched.

---

## Setup (≈20 min, once)

### 1. Create a private GitHub repo
Push this folder to a **private** repo (your timetable and secrets stay private; private repos get 2,000 free Action minutes/month, a run takes ~2).

### 2. Google Calendar API + service account
1. https://console.cloud.google.com → create a project (e.g. `esprit-calendar`).
2. **APIs & Services → Library → Google Calendar API → Enable**.
3. **IAM & Admin → Service Accounts → Create service account** (no role needed).
4. Open it → **Keys → Add key → Create new key → JSON**. Keep the downloaded file.
5. Copy the service account email (`…@…iam.gserviceaccount.com`).

### 3. The calendar
1. In Google Calendar: **Other calendars → + → Create new calendar** → name it `ESPRIT 4CCE5`.
2. Its **Settings → Share with specific people → Add** the service account email → permission **Make changes to events**.
3. **Integrate calendar → Calendar ID** (`…@group.calendar.google.com`): copy it.

### 4. Gmail app password (to email the PDF)
Needs 2-Step Verification on your Google account. https://myaccount.google.com/apppasswords → create one → copy the 16-character password.

### 5. GitHub secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `ESPRIT_USERNAME` | your ESPRIT login |
| `ESPRIT_PASSWORD` | your ESPRIT password |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | the **whole content** of the JSON key file |
| `GOOGLE_CALENDAR_ID` | the calendar ID from step 3 |
| `SMTP_USER` | your Gmail address |
| `SMTP_APP_PASSWORD` | the app password from step 4 |
| `MAIL_TO` | *(optional)* where to send the PDF, defaults to `SMTP_USER` |

### 6. First run
**Actions → ESPRIT timetable → Google Calendar → Run workflow.** After ~2 min you should get the email and see the events.
If it fails, open the run → **Artifacts** → `debug/` has a screenshot of the page where it got stuck.

---

## Apple Calendar
The Google calendar is the hub; Apple reads it:
- **iPhone/iPad:** Settings → Apps → Calendar → Calendar Accounts → Add Account → Google. Then open
  https://calendar.google.com/calendar/syncselect and tick **ESPRIT 4CCE5** (iOS only shows your main calendar until you do this).
- **Mac:** System Settings → Internet Accounts → Google → Calendars on.
- **Read-only alternative:** Google Calendar → ESPRIT calendar settings → *Secret address in iCal format* → in Apple Calendar: File → New Calendar Subscription.

---

## If the login doesn't work
The portal is a JavaScript app; the script fills the first username/password fields it finds and clicks the submit button.
- Watch it locally: `python fetch_edt.py --show` (opens a visible browser).
- If ESPRIT changes its page, override the selectors with env vars/secrets: `SEL_USER`, `SEL_PASS`, `SEL_SUBMIT`, `SEL_PDF`, `SEL_NEXT`.
- If the login uses Microsoft/Google SSO with 2FA, full automation isn't possible: use the fallback below.
- If ESPRIT blocks GitHub's servers, run it on your PC instead (below).

### Fallback: drop the PDF yourself
Upload the PDF into the repo's `inbox/` folder (GitHub website or app → Add file → Upload). The workflow runs on that push and syncs the calendar + emails you.

### Run on your Windows PC instead of GitHub
```bat
pip install -r requirements.txt
python -m playwright install chromium
:: put the same variables in a run_edt.bat with "set NAME=value" lines, then:
schtasks /create /sc weekly /d SUN /st 20:00 /tn "ESPRIT EDT" /tr "C:\path\to\run_edt.bat"
```

---

## Commands
```bash
python main.py                                     # full run (portal → calendar → email)
python main.py --weeks 2                           # this week + next week
python main.py --pdf emploi.pdf                    # use a PDF you already have
python main.py --pdf emploi.pdf --no-sync --no-mail   # just make out/EDT_4CCE5.ics
python main.py --dry-run --no-mail                 # show calendar changes without applying them
python esprit_edt.py emploi.pdf                    # print what the parser reads
```

## Files
- `esprit_edt.py` – PDF parser + `.ics` export
- `fetch_edt.py` – portal login + PDF download (Playwright)
- `gcal_sync.py` – Google Calendar sync (add / update / remove, only its own events)
- `main.py` – runs everything + sends the email
- `.github/workflows/weekly-edt.yml` – the Sunday schedule
