"""Parse an ESPRIT "Emploi du Temps" PDF (arp.esprit.tn → Télécharger PDF) into events,
and export them as an .ics file.

Layout of the PDF (one page per week):
  - header: class name ("4CCE5") and week range ("18/10/2026 - 24/10/2026")
  - one column per day, with a "dd/mm" label on top
  - one filled box per session:  TITLE (1-2 lines) / "S. Teacher" / "ROOM | 09:00 - 12:15"
  - legend at the bottom maps box colours to Cours / Épreuve / Événement
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pdfplumber

TZ = ZoneInfo("Africa/Tunis")

RANGE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})")
DAY_RE = re.compile(r"^(\d{2})/(\d{2})$")
TIME_RE = re.compile(r"^(?P<room>.*?)\s*\|\s*(?P<h1>\d{1,2}):(?P<m1>\d{2})\s*-\s*(?P<h2>\d{1,2}):(?P<m2>\d{2})\s*$")
TEACHER_RE = re.compile(r"^[A-ZÀ-Ý]\.\s*\S")          # "S. Emna", "B. BASSEM"
CLASS_RE = re.compile(r"^\d[A-Z]{2,}\d*$")             # "4CCE5"
LEGEND_LABELS = ("Cours", "Épreuve", "Événement")
KEEP_UPPER = {"UNIX", "SGBD", "IA", "ML", "IOT", "API", "UML", "SQL", "J2EE", "JEE", "DEVOPS", "TCP/IP", "IP"}


@dataclass
class Session:
    day: date
    start: datetime
    end: datetime
    title: str            # as printed, upper case
    teacher: str
    room: str
    kind: str             # Cours / Épreuve / Événement
    class_name: str

    @property
    def nice_title(self) -> str:
        return pretty_title(self.title)

    @property
    def key(self) -> str:
        """Stable identity of a session slot (used to diff with Google Calendar)."""
        raw = f"{self.class_name}|{self.start.isoformat()}|{self.title}"
        return hashlib.sha1(raw.encode()).hexdigest()[:20]

    @property
    def summary(self) -> str:
        prefix = {"Épreuve": "📝 Épreuve – ", "Événement": "📌 "}.get(self.kind, "")
        return prefix + self.nice_title

    @property
    def description(self) -> str:
        lines = [f"Module : {self.nice_title}"]
        if self.teacher:
            lines.append(f"Enseignant : {self.teacher}")
        lines.append(f"Salle : {self.room}")
        lines.append(f"Type : {self.kind}")
        lines.append(f"Source : ESPRIT emploi du temps {self.class_name}")
        return "\n".join(lines)

    @property
    def fingerprint(self) -> str:
        """Changes when anything shown in the calendar changes."""
        raw = "|".join([self.summary, self.start.isoformat(), self.end.isoformat(), self.room, self.description])
        return hashlib.sha1(raw.encode()).hexdigest()[:20]


@dataclass
class Week:
    class_name: str
    start: date
    end: date
    sessions: list[Session] = field(default_factory=list)


def pretty_title(t: str) -> str:
    words = t.replace("&", " & ").split()
    out = []
    for i, w in enumerate(words):
        if w.upper() in KEEP_UPPER or any(c.isdigit() for c in w):
            out.append(w.upper())
        else:
            out.append(w.capitalize() if i == 0 else w.lower())
    return " ".join(out).replace(" & ", " & ")


def _lines(words):
    """Group words into text lines (top to bottom)."""
    rows: list[list] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) < 3:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [" ".join(x["text"] for x in sorted(r, key=lambda x: x["x0"])).strip() for r in rows]


def _color_distance(a, b) -> float:
    a, b = tuple(a or (0, 0, 0)), tuple(b or (0, 0, 0))
    if len(a) != len(b):
        return 9.0
    return sum((x - y) ** 2 for x, y in zip(a, b))


def parse_pdf(path: str | Path) -> list[Week]:
    weeks: list[Week] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            week = _parse_page(page)
            if week:
                weeks.append(week)
    return weeks


def _parse_page(page) -> Week | None:
    words = page.extract_words(keep_blank_chars=True, x_tolerance=2)
    text_all = " ".join(w["text"] for w in words)

    m = RANGE_RE.search(text_all)
    if not m:
        return None
    d1, m1, y1, d2, m2, y2 = map(int, m.groups())
    week_start, week_end = date(y1, m1, d1), date(y2, m2, d2)

    class_name = next((w["text"].strip() for w in words if CLASS_RE.match(w["text"].strip())), "ESPRIT")

    # Day columns: "dd/mm" labels in the header row
    day_cols = []
    for w in words:
        dm = DAY_RE.match(w["text"].strip())
        if dm:
            dd, mm = int(dm.group(1)), int(dm.group(2))
            year = week_start.year + (1 if mm < week_start.month else 0)
            day_cols.append(((w["x0"] + w["x1"]) / 2, w["bottom"], date(year, mm, dd)))
    if not day_cols:
        return None
    header_bottom = max(c[1] for c in day_cols)

    # Legend: small squares followed by a label
    legend = {}
    small = [r for r in page.rects if (r["x1"] - r["x0"]) < 20 and (r["bottom"] - r["top"]) < 20]
    for r in small:
        right = [w for w in words if w["x0"] >= r["x1"] and w["x0"] - r["x1"] < 15 and abs(w["top"] - r["top"]) < 8]
        if right:
            label = right[0]["text"].strip()
            if label in LEGEND_LABELS:
                legend[label] = r.get("non_stroking_color")
    legend_top = min((r["top"] for r in small), default=page.height)

    # Session boxes (deduplicated: each box is drawn twice — fill + stroke)
    boxes = {}
    for r in page.rects:
        w_, h_ = r["x1"] - r["x0"], r["bottom"] - r["top"]
        if w_ > 50 and h_ > 20 and r["top"] > header_bottom and r["bottom"] < legend_top:
            boxes[(round(r["x0"]), round(r["top"]), round(r["x1"]), round(r["bottom"]))] = r.get("non_stroking_color")

    week = Week(class_name, week_start, week_end)
    for (x0, top, x1, bottom), color in sorted(boxes.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        inside = [w for w in words if w["x0"] >= x0 - 1 and w["x1"] <= x1 + 1 and w["top"] >= top - 1 and w["bottom"] <= bottom + 1]
        lines = _lines(inside)
        t_idx = next((i for i, l in enumerate(lines) if TIME_RE.match(l)), None)
        if t_idx is None:
            continue
        tm = TIME_RE.match(lines[t_idx])
        before = lines[:t_idx]
        teacher = ""
        if before and TEACHER_RE.match(before[-1]):
            teacher = before.pop()
        title = re.sub(r"\s+", " ", " ".join(before)).strip() or "Séance"

        cx = (x0 + x1) / 2
        day = min(day_cols, key=lambda c: abs(c[0] - cx))[2]
        kind = min(legend, key=lambda k: _color_distance(legend[k], color)) if legend else "Cours"

        start = datetime(day.year, day.month, day.day, int(tm["h1"]), int(tm["m1"]), tzinfo=TZ)
        end = datetime(day.year, day.month, day.day, int(tm["h2"]), int(tm["m2"]), tzinfo=TZ)
        week.sessions.append(Session(day, start, end, title, teacher, tm["room"].strip(), kind, class_name))

    week.sessions.sort(key=lambda s: s.start)
    return week


def to_ics(weeks: list[Week], out_path: str | Path) -> Path:
    from icalendar import Calendar, Event

    cal = Calendar()
    cal.add("prodid", "-//esprit-calendar//EDT//FR")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"ESPRIT {weeks[0].class_name if weeks else ''}".strip())
    cal.add("x-wr-timezone", "Africa/Tunis")
    now = datetime.now(TZ)
    for wk in weeks:
        for s in wk.sessions:
            ev = Event()
            ev.add("uid", f"{s.key}@esprit-calendar")
            ev.add("dtstamp", now)
            ev.add("dtstart", s.start)
            ev.add("dtend", s.end)
            ev.add("summary", s.summary)
            ev.add("location", s.room)
            ev.add("description", s.description)
            ev.add("categories", [s.kind])
            cal.add_component(ev)
    if hasattr(cal, "add_missing_timezones"):  # icalendar >= 6: embed VTIMEZONE for strict clients
        cal.add_missing_timezones()
    out = Path(out_path)
    out.write_bytes(cal.to_ical())
    return out


if __name__ == "__main__":
    import sys

    for wk in parse_pdf(sys.argv[1]):
        print(f"{wk.class_name}  {wk.start} → {wk.end}  ({len(wk.sessions)} séances)")
        for s in wk.sessions:
            print(f"  {s.start:%a %d/%m %H:%M}-{s.end:%H:%M}  {s.summary:<45} {s.room:<14} {s.teacher}  [{s.kind}]")
