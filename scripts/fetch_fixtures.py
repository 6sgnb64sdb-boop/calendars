#!/usr/bin/env python3
"""Fetch upcoming NHL, MLB and soccer fixtures; output spoiler-free JSON.

Never include scores, results or standings. A source failure is reported and
does not erase previously published fixtures.
"""
import datetime as dt
import json
import pathlib
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fixtures.json"
TODAY = dt.datetime.now(dt.timezone.utc)
END = TODAY + dt.timedelta(days=30)
EVENTS = {}
ERRORS = []
COUNTS = {}

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "SandySportsCalendar/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)

def in_window(iso):
    value = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return TODAY <= value <= END

def add(uid, title, start, duration, description, location=""):
    if not in_window(start):
        return
    beginning = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
    ending = beginning + dt.timedelta(hours=duration)
    EVENTS[uid] = dict(uid=uid, title=title, start=beginning.isoformat(), end=ending.isoformat(), description=description, location=location)

def source(name, callback):
    try:
        before = len(EVENTS)
        callback()
        COUNTS[name] = len(EVENTS) - before
    except Exception as exc:
        ERRORS.append(f"{name}: {type(exc).__name__}: {exc}")

def nhl():
    data = fetch("https://api-web.nhle.com/v1/club-schedule-season/PIT/20262027")
    for game in data.get("games", []):
        start = game.get("startTimeUTC")
        if not start:
            continue
        home = game.get("homeTeam", {}).get("placeName", {}).get("default", "Home")
        away = game.get("awayTeam", {}).get("placeName", {}).get("default", "Away")
        # Club abbreviation is more reliable than nicknames in the feed.
        home_abbr = game.get("homeTeam", {}).get("abbrev", "HOME")
        away_abbr = game.get("awayTeam", {}).get("abbrev", "AWAY")
        add(f"nhl-{game['id']}", f"NHL: {away_abbr} @ {home_abbr}", start, 3, "Pittsburgh Penguins. Australia: check ESPN via Disney+, Kayo/Foxtel and NHL coverage.")

def mlb():
    params = urllib.parse.urlencode(dict(teamId=114, sportId=1, startDate=TODAY.date().isoformat(), endDate=END.date().isoformat()))
    data = fetch("https://statsapi.mlb.com/api/v1/schedule?" + params)
    for day in data.get("dates", []):
        for game in day.get("games", []):
            start = game.get("gameDate")
            if not start or game.get("status", {}).get("abstractGameState") == "Final":
                continue
            teams = game.get("teams", {})
            home = teams.get("home", {}).get("team", {}).get("name", "Home")
            away = teams.get("away", {}).get("team", {}).get("name", "Away")
            add(f"mlb-{game['gamePk']}", f"MLB: {away} @ {home}", start, 3.5, "Cleveland Guardians. Australia: MLB.TV; selected games on ESPN via Disney+/Kayo/Foxtel.", game.get("venue", {}).get("name", ""))

SOCCER = {
    "eng.1": ("Premier League", ("Leeds United", "Manchester United")),
    "eng.fa": ("FA Cup", ("Leeds United", "Manchester United")),
    "eng.league_cup": ("EFL Cup", ("Leeds United", "Manchester United")),
    "uefa.champions": ("Champions League", ("Leeds United", "Manchester United")),
    "uefa.europa": ("Europa League", ("Leeds United", "Manchester United")),
    "uefa.europa.conf": ("Conference League", ("Leeds United", "Manchester United")),
    "usa.1": ("MLS", ("Nashville SC",)),
    "fra.1": ("Ligue 1", ("Troyes",)),
    "fra.2": ("Ligue 2", ("Troyes",)),
    "uefa.nations": ("UEFA Nations League", ("England",)),
    "fifa.friendly": ("International Friendlies", ("England", "Australia")),
}
# Exact aliases avoid matching youth and women's teams.
ALIASES = {"Leeds United": ("leeds united",), "Manchester United": ("manchester united", "man united"),
           "Nashville SC": ("nashville sc", "nashville"), "Troyes": ("troyes", "es troyes"),
           "England": ("england",), "Australia": ("australia",)}

def soccer(league, label, followed):
    # ESPN accepts individual dates; scan the rolling 14-day football window.
    for day_offset in range(14):
        day = (TODAY + dt.timedelta(days=day_offset)).strftime("%Y%m%d")
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={day}&limit=500"
        data = fetch(url)
        for event in data.get("events", []):
            competitors = (event.get("competitions") or [{}])[0].get("competitors", [])
            if len(competitors) != 2:
                continue
            names = [c.get("team", {}).get("displayName", "") for c in competitors]
            if not any(any(n.lower() in ALIASES[t] for n in names) for t in followed):
                continue
            if any(any(token in n.lower() for token in (" women", " u17", " u19", " u20", " u21", " u23", " youth")) for n in names):
                continue
            if event.get("status", {}).get("type", {}).get("completed"):
                continue
            start = event.get("date")
            if not start:
                continue
            home = next((c.get("team", {}).get("displayName", "") for c in competitors if c.get("homeAway") == "home"), names[0])
            away = next((c.get("team", {}).get("displayName", "") for c in competitors if c.get("homeAway") == "away"), names[1])
            viewing = "Stan Sport" if league in ("eng.1", "uefa.champions", "uefa.europa", "uefa.europa.conf") else "Australian broadcaster to be confirmed"
            add(f"soccer-{league}-{event['id']}", f"{label}: {home} v {away}", start, 2.5, "Australia viewing: " + viewing)

def hawthorn():
    """Use verified Hawthorn AFL/AFLW fixtures; rolling 14-day window.

    Source data must be reviewed for new seasons, finals and reschedules.
    This deliberately does not scrape scores or results pages.
    """
    payload = json.loads((ROOT / "data" / "hawthorn_fixtures.json").read_text(encoding="utf-8"))
    window_end = TODAY + dt.timedelta(days=14)
    for event in payload.get("events", []):
        start = dt.datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
        if not TODAY <= start <= window_end:
            continue
        add(event["uid"], event["title"], event["start"],
            (dt.datetime.fromisoformat(event["end"].replace("Z", "+00:00")) - start).total_seconds() / 3600,
            event.get("description", ""), event.get("location", ""))

def cycling():
    """Load UCI-verified event dates not already represented in the calendar.

    Static seed is not a live UCI feed; session times must be verified separately.
    """
    payload = json.loads((ROOT / "data" / "cycling_events.json").read_text(encoding="utf-8"))
    cutoff = TODAY + dt.timedelta(days=45)
    for event in payload.get("events", []):
        start_date = dt.date.fromisoformat(event["start"])
        end_date = dt.date.fromisoformat(event["end"])
        if end_date < TODAY.date() or start_date > cutoff.date():
            continue
        # Calendar publisher supports date-only all-day events; retain stable IDs.
        EVENTS[event["uid"]] = dict(uid=event["uid"], title=event["title"],
            start=event["start"], end=event["end"], location=event.get("location", ""),
            description=event.get("description", ""))

def road_calendar():
    """Discover men's major road races from a public subscription calendar.

    Conservative allowlist avoids women's races, development events and duplicates
    with already-published manually scheduled races. Dates are all-day until
    official start times are verified. This is a third-party feed, not UCI API.
    """
    url = "https://calendar.google.com/calendar/ical/5c9dc1a627cf55f1653d17573c2df58075d949559ec87e484b0cf90fa78bbf6d%40group.calendar.google.com/public/basic.ics"
    request = urllib.request.Request(url, headers={"User-Agent": "SandySportsCalendar/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read().decode("utf-8-sig")
    # Unfold iCalendar continuation lines, without importing any outcomes.
    raw = raw.replace("\r\n", "\n")
    raw = __import__("re").sub(r"\n[ \t]", "", raw)
    allow = ("paris-roubaix", "milano-sanremo", "milan-san remo", "ronde van vlaanderen",
             "tour of flanders", "liège-bastogne-liège", "liege-bastogne-liege",
             "il lombardia", "tour de france", "giro d'italia", "giro d’italia",
             "vuelta a españa", "vuelta ciclista a españa", "paris-nice",
             "tirreno-adriatico", "tour de suisse", "tour de romandie",
             "tour de pologne", "critérium du dauphiné", "criterium du dauphine",
             "tour of guangxi", "strade bianche", "amstel gold race",
             "la flèche wallonne", "la fleche wallonne", "gent-wevelgem",
             "omloop nieuwsblad", "san sebastián", "san sebastian",
             "tour down under", "cadel evans great ocean road race",
             "gp québec", "gp quebec", "gp montréal", "gp montreal",
             "tour of britain", "e3 saxo classic", "dwars door vlaanderen",
             "es chborn-frankfurt", "eschborn-frankfurt", "tour of california")
    blocked = ("women", "woman", "femmes", "feminine", "féminin", "femenina",
               "ladies", "junior", "under 23", "u23", "u19", "u17", "espoirs",
               "development", "amateur", "gran fondo")
    today = TODAY.date()
    stats = {"feed_events": 0, "eligible_races": 0, "outside_window": 0, "unsupported_dates": 0, "existing_races": 0, "added": 0}
    for block in raw.split("BEGIN:VEVENT")[1:]:
        stats["feed_events"] += 1
        lines = dict(line.split(":", 1) for line in block.split("END:VEVENT")[0].split("\n")
                     if ":" in line and line.split(":", 1)[0] in ("SUMMARY", "DTSTART;VALUE=DATE", "DTSTART", "UID"))
        title = lines.get("SUMMARY", "").replace("\\,", ",").replace("\\;", ";").strip()
        low = title.casefold()
        if not any(term in low for term in allow) or any(term in low for term in blocked):
            continue
        stats["eligible_races"] += 1
        datevalue = lines.get("DTSTART;VALUE=DATE", lines.get("DTSTART", ""))
        if not __import__("re").fullmatch(r"\d{8}", datevalue):
            stats["unsupported_dates"] += 1
            continue  # Ignore ambiguous time zones until individually verified.
        day = dt.datetime.strptime(datevalue, "%Y%m%d").date()
        if not today <= day <= today + dt.timedelta(days=45):
            stats["outside_window"] += 1
            continue
        # Do not create duplicates of manually published stage/race entries.
        if ("lombardia" in low and day.year == 2026) or ("guangxi" in low and day.year == 2026):
            stats["existing_races"] += 1
            continue
        key = __import__("re").sub(r"[^a-z0-9]+", "-", low).strip("-")[:85]
        uid = f"road-{day.isoformat()}-{key}"
        stats["added"] += 1
        EVENTS[uid] = dict(uid=uid, title="Cycling: " + title,
                           start=day.isoformat(), end=(day + dt.timedelta(days=1)).isoformat(),
                           description="Men's professional road race. Date from The Inner Ring public cycling calendar; start time and Australian broadcaster unconfirmed.")

    COUNTS["Men road feed diagnostics"] = stats
    print("Men road feed diagnostics:", json.dumps(stats, sort_keys=True))


def marathons():
    """Import verified World Marathon Majors dates without guessing future editions."""
    payload = json.loads((ROOT / "data" / "marathon_events.json").read_text(encoding="utf-8"))
    cutoff = TODAY.date() + dt.timedelta(days=45)
    for event in payload.get("events", []):
        start_date = dt.date.fromisoformat(event["start"])
        end_date = dt.date.fromisoformat(event["end"])
        if end_date < TODAY.date() or start_date > cutoff:
            continue
        EVENTS[event["uid"]] = dict(uid=event["uid"], title=event["title"],
            start=event["start"], end=event["end"], location=event.get("location", ""),
            description=event.get("description", ""))

def athletics():
    """Import manually verified major athletics dates; no speculative recurrence."""
    payload = json.loads((ROOT / "data" / "athletics_events.json").read_text(encoding="utf-8"))
    cutoff = TODAY.date() + dt.timedelta(days=45)
    for event in payload.get("events", []):
        start_date = dt.date.fromisoformat(event["start"])
        end_date = dt.date.fromisoformat(event["end"])
        if end_date < TODAY.date() or start_date > cutoff:
            continue
        EVENTS[event["uid"]] = dict(uid=event["uid"], title=event["title"],
            start=event["start"], end=event["end"], location=event.get("location", ""),
            description=event.get("description", ""))

def main():
    source("NHL Pittsburgh", nhl)
    source("MLB Cleveland", mlb)
    source("Hawthorn AFL/AFLW", hawthorn)
    source("UCI cycling championships", cycling)
    source("World Marathon Majors", marathons)
    source("Major athletics", athletics)
    source("Men road calendar", road_calendar)
    for league, (label, followed) in SOCCER.items():
        source("Football " + league, lambda l=league, n=label, t=followed: soccer(l, n, t))
    # Never replace previously collected source data with an empty response.
    if not EVENTS:
        print("No verified future fixtures retrieved; leaving data file unchanged.")
        print("Errors:", ERRORS)
        return 1
    # Publish successful sources even when another source is unavailable.
    # Keep previously published fixtures; report source failures in logs.
    if ERRORS:
        print("WARNING: Some sources failed; successful sports will still publish:")
        for error in ERRORS:
            print(error)
    OUT.write_text(json.dumps({"events": list(EVENTS.values()), "generated_at": TODAY.isoformat(), "coverage": COUNTS}, indent=2) + "\n", encoding="utf-8")
    print("Upcoming events collected:", len(EVENTS))
    print("Source counts:", COUNTS)
    return 0

if __name__ == "__main__":
    sys.exit(main())
