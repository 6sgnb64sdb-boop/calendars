# Calendars

Calendar subscription feeds maintained for Sandy.

- `sports.ics` — sports-watching calendar in Brisbane time.
- `dividends.ics` — declared dividend payment dates for the portfolio in `dividend_holdings.csv`.
- `dividend_holdings.csv` — authoritative master list of all portfolio holdings. Dividend refreshes must start from this complete list and check every ticker for newly declared dividends; holdings must not be removed merely because they currently have no declared payment.

Calendar feeds are refreshed in place with stable iCalendar UIDs so subscribed calendar clients can receive changes without duplicate events.

## Dividend refresh rule

Every dividend-calendar refresh must read `dividend_holdings.csv` first, check all listed holdings for declared dividend payment dates, preserve valid previously declared events, add newly declared events, and write the resulting declared payment dates to `dividends.ics`. Do not infer the portfolio from the events already present in `dividends.ics`.
