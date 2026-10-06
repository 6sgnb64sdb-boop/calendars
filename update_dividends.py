#!/usr/bin/env python3
import csv, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yfinance as yf

ROOT=Path(__file__).resolve().parent
HOLDINGS=ROOT/"dividend_holdings.csv"
ICS=ROOT/"dividends.ics"

def tickers():
    with HOLDINGS.open(newline="",encoding="utf-8") as f:
        return [r["ticker"].strip().upper() for r in csv.DictReader(f) if r.get("ticker","").strip()]

def next_day(s):
    return (datetime.strptime(s,"%Y%m%d")+timedelta(days=1)).strftime("%Y%m%d")

def existing_events(text):
    out={}
    for block in re.findall(r"BEGIN:VEVENT\r?\n.*?END:VEVENT\r?\n?",text,re.S):
        m=re.search(r"SUMMARY:([A-Z0-9]+) dividend payment",block)
        d=re.search(r"DTSTART;VALUE=DATE:(\d{8})",block)
        if m and d: out[(m.group(1),d.group(1))]=block.replace("\n","\r\n")
    return out

def declared_date(code):
    try:
        cal=yf.Ticker(code+".AX").calendar
        if not cal: return None
        value=cal.get("Dividend Date") or cal.get("DividendDate")
        if value is None: return None
        if hasattr(value,"to_pydatetime"): value=value.to_pydatetime()
        if isinstance(value,(int,float)):
            value=datetime.fromtimestamp(value,tz=timezone.utc)
        if isinstance(value,str):
            value=datetime.fromisoformat(value.replace("Z","+00:00"))
        return value.strftime("%Y%m%d")
    except Exception as e:
        print(f"{code}: lookup failed: {e}")
        return None

def make_event(code,date):
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    iso=f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return (
      "BEGIN:VEVENT\r\n"
      f"UID:dividend-{code.lower()}-{iso}@sandy-calendars\r\n"
      f"DTSTAMP:{stamp}\r\n"
      f"DTSTART;VALUE=DATE:{date}\r\n"
      f"DTEND;VALUE=DATE:{next_day(date)}\r\n"
      f"SUMMARY:{code} dividend payment\r\n"
      "DESCRIPTION:Status: Declared\r\n"
      "TRANSP:TRANSPARENT\r\n"
      "END:VEVENT\r\n"
    )

def main():
    text=ICS.read_text(encoding="utf-8")
    events=existing_events(text)
    codes=tickers()
    print(f"Checking {len(codes)} portfolio holdings")
    for code in codes:
        date=declared_date(code)
        if date:
            key=(code,date)
            if key not in events:
                print(f"Adding {code} {date}")
                events[key]=make_event(code,date)
        else:
            print(f"{code}: no declared dividend date returned")
    ordered=sorted(events.items(),key=lambda x:(x[0][1],x[0][0]))
    header=(
      "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
      "PRODID:-//Sandy Dividend Dates//EN\r\nCALSCALE:GREGORIAN\r\n"
      "METHOD:PUBLISH\r\nX-WR-CALNAME:Dividend Dates\r\n"
      "X-WR-TIMEZONE:Australia/Brisbane\r\n"
      "REFRESH-INTERVAL;VALUE=DURATION:PT24H\r\nX-PUBLISHED-TTL:PT24H\r\n"
    )
    ICS.write_text(header+"".join(block for _,block in ordered)+"END:VCALENDAR\r\n",encoding="utf-8",newline="")

if __name__=="__main__": main()
