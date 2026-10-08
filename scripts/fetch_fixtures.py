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

def main():
    source("NHL Pittsburgh", nhl)
    source("MLB Cleveland", mlb)
    source("Hawthorn AFL/AFLW", hawthorn)
    source("UCI cycling championships", cycling)
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
