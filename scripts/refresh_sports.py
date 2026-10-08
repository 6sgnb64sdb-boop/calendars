#!/usr/bin/env python3
"""Spoiler-safe iCalendar publisher. No external dependencies.

Input: data/fixtures.json with an 'events' array. An empty input is a no-op.
Each event needs uid, title, start (ISO 8601 with timezone, or YYYY-MM-DD);
optional end, location, description, status. UIDs MUST be stable across reschedules.
This publisher never imports results/scores.
"""
import datetime as dt
import json
import pathlib
import re
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
CAL = ROOT / "sports.ics"
SOURCE = ROOT / "data" / "fixtures.json"
TZ = ZoneInfo("Australia/Brisbane")
FORBIDDEN = re.compile(r"\\b(?:NFL|Green Bay Packers|score|final score|winner|result)\\b", re.I)

def esc(s):
    return str(s).replace("\\\\", "\\\\\\\\").replace("\\n", "\\\\n").replace(",", "\\\\,").replace(";", "\\\\;")

def stamp(value):
    if re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", value):
        return "DTSTART;VALUE=DATE:" + value.replace("-", ""), True
    d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("Timed events must have an explicit timezone offset")
    return "DTSTART;TZID=Australia/Brisbane:" + d.astimezone(TZ).strftime("%Y%m%dT%H%M%S"), False

def render(event):
    uid = event["uid"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", uid):
        raise ValueError("Invalid stable UID")
    title = event["title"]
    desc = event.get("description", "")
    if FORBIDDEN.search(title + " " + desc):
        raise ValueError("Potential spoiler or excluded NFL content")
    start_line, allday = stamp(event["start"])
    if allday:
        start = dt.date.fromisoformat(event["start"])
        end = dt.date.fromisoformat(event["end"]) if event.get("end") else start + dt.timedelta(days=1)
        end_line = "DTEND;VALUE=DATE:" + end.strftime("%Y%m%d")
    else:
        if not event.get("end"):
            raise ValueError("Timed event requires end")
        end_line = stamp(event["end"])[0].replace("DTSTART", "DTEND", 1)
    lines = ["BEGIN:VEVENT", "UID:" + uid + "@sandy-calendars",
             "DTSTAMP:" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
             start_line, end_line, "SUMMARY:" + esc(title)]
    if event.get("location"):
        lines.append("LOCATION:" + esc(event["location"]))
    if desc:
        lines.append("DESCRIPTION:" + esc(desc))
    lines.extend(["STATUS:" + event.get("status", "CONFIRMED"), "END:VEVENT"])
    return "\\r\\n".join(lines)

def main():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    fresh = data.get("events", [])
    if not fresh:
        print("No verified source events supplied; preserving existing calendar unchanged.")
        return
    raw = CAL.read_text(encoding="utf-8")
    blocks = re.findall(r"BEGIN:VEVENT.*?END:VEVENT", raw, re.S)
    by_uid = {}
    for block in blocks:
        m = re.search(r"^UID:(.+)$", block, re.M)
        if m:
            by_uid[m.group(1).strip()] = block.strip()
    for event in fresh:
        by_uid[event["uid"] + "@sandy-calendars"] = render(event)
    # Preserve previously published events; do not drop unrefreshed sports.
    # Trim only after all tracked sports have complete verified source coverage.
    header = raw.split("BEGIN:VEVENT")[0].rstrip()
    output = header + "\\r\\n" + "\\r\\n".join(by_uid.values()) + "\\r\\nEND:VCALENDAR\\r\\n"
    if output.replace("\\r\\n", "\\n") != raw.replace("\\r\\n", "\\n"):
        CAL.write_bytes(output.encode("utf-8"))
        print(f"Published {len(by_uid)} events.")
    else:
        print("No changes.")

if __name__ == "__main__":
    main()
