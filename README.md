# Attendee Tracker

College football home attendance for every FBS program, grouped by conference. Phase 1 covers Power 4 and Group of 5 schools: logos, stadium capacity, season record, the latest AP Top 25, a home-attendance chart by opponent, and a computed look at how record lines up with the crowd. Ticket prices are not in this version.

This repository is a portfolio site. Season snapshots in `data/live/` (2016 through 2026) are committed, so the public site serves those caches with no College Football Data API key. Attendance figures are the numbers already stored in those files. The app does not invent a crowd.

**2020 is omitted from averages as the COVID season.** The 2020 cache stays in the repo, but that year's crowds are not used in season averages, multi-year windows, or growth rates.

`CFBD_API_KEY` is optional. Leave it unset to run and host the site from the committed caches. Set it only to refresh a cache (`python -m attendee_tracker.ingest`, or `python -m attendee_tracker.refresh_current` for the current season). Never commit the key, `.env`, or quota logs.

School logos are the image URLs College Football Data publishes. That is fine for this portfolio. Revisit the trademark and CFBD terms before any commercial use. See [Logos](#logos).

If a requested season has no `data/live/{year}.json`, the site falls back to the labeled sample fixture in `data/sample_season.json` when that fixture's season matches. It does not relabel the sample as another year.

## What runs where

| Piece | Where it runs | Role |
| --- | --- | --- |
| `python -m attendee_tracker.ingest` | Your machine, or a daily cron | Calls CFBD, writes a JSON cache under `data/` |
| `python -m attendee_tracker.refresh_current` | Your machine, or the current-season cron | Re-pulls the current season from CFBD, then fills null attendance from ESPN summaries |
| `attendee_tracker` (FastAPI) | Local Python process, or the free Render web service | Reads that cache, builds conference lists, charts data, and the analysis |
| `web/` | Browser | HTML, CSS, and JavaScript. Chart.js draws the graphs. No frontend build step |

The browser never calls CFBD and never sees the API key. It only requests `/api/season` from the Python app.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if you want a different `SEASON_YEAR` or a local `PORT`. `CFBD_API_KEY` can stay blank. The committed `data/live/{year}.json` files are enough to browse 2016–2026. Get a free key at <https://collegefootballdata.com/key> only when you plan to refresh the cache. The app reads the key from the environment (or from `.env` via `setdefault`, so a real environment variable wins). Do not commit `.env`.

`SEASON_YEAR` defaults to **2026**. Change it in `.env` or pass `--year` to ingest.

## Ingest

```bash
python -m attendee_tracker.ingest
```

That pulls, for the configured season:

- `/games?year=&classification=fbs&seasonType=both` — one call for the full FBS slate, so late attendance fills in recent weeks are picked up without a per-week loop
- `/records?year=`
- `/rankings?year=` — the `poll` parameter is omitted, then the response is filtered to **AP Top 25** (CFBD only accepts `poll=cfp`)
- `/teams/fbs?year=` — skipped when the cache is under 7 days old
- `/venues` — skipped when the cache is under 14 days old

A second run inside 18 hours skips the network unless you pass `--force`. That skip is per season, so a backfill that stops halfway can be run again and will leave the fresh years alone. Useful flags:

```bash
python -m attendee_tracker.ingest --year 2026
python -m attendee_tracker.ingest --year 2024 --year 2025
python -m attendee_tracker.ingest --years 2016-2025
python -m attendee_tracker.ingest --force
python -m attendee_tracker.ingest --min-interval-hours 0
```

`--year` still refreshes one season, and it can be repeated. `--years 2016-2025` is an inclusive range. The two flags can be combined; duplicate years are ingested once. A run is capped at 30 seasons so a typo cannot walk the whole history of the sport in one shot.

### Backfill vs daily cron

A one-time backfill costs about **3–5 CFBD calls per season**: games, records, rankings, and teams when that season's team cache is missing or older than 7 days. Venues are shared. The command fetches `/venues` at most once per run, then reuses that payload for the other seasons, including when `--force` is set. Teams keep the 7-day TTL per season. Attendance is only what CFBD returns. A null stays null.

Do not put a year range on the daily cron. Cron should refresh the current season only (`python -m attendee_tracker.ingest`, or `--year` set to `SEASON_YEAR`). That stays near 3 calls a day, plus a teams call about once a week and a venues call about every two weeks.

Ten prior seasons plus the current one is on the order of 40–50 calls the day you backfill, then the usual ~100 calls a month if cron stays on the current season. The ingest command prints how many successful calls it has logged this month (`data/quota_log.jsonl`). The free tier is 1,000 calls a month.

Raw responses land in `data/raw/` (gitignored). The site reads `data/live/{year}.json`, one file per season. A failed request leaves that season's previous snapshot in place. If one year in a range fails, the other years in the run are still written.

Without a key, ingest exits with a clear error and writes nothing. It will not fabricate attendance.

### Current season refresh

Ingest stores a crowd only when CFBD has one. For 2026, CFBD has returned games, records, and rankings with null attendance on completed home games. This command re-pulls that CFBD snapshot, then fills only the nulls from ESPN:

```bash
python -m attendee_tracker.refresh_current
python -m attendee_tracker.refresh_current --year 2026
python -m attendee_tracker.refresh_current --force
```

It uses the same 18-hour freshness window as ingest unless you pass `--force`. ESPN is consulted only for completed non-neutral home games whose CFBD attendance is null: the FBS scoreboard, then each summary's `gameInfo.attendance`. A number CFBD already has is kept. If ESPN has no figure, the game stays null. Nothing is invented. A filled game records `attendance_source` of `espn_summary`. A CFBD crowd is recorded as `cfbd`. The command requires `CFBD_API_KEY`, writes `data/live/{year}.json`, and will not commit `.env` or the key.

2020 remains in the cache and remains omitted from averages, growth, Last 5, Last 10, and the loyal and soft lists.

### Daily refresh at 10:00 America/New_York

This repo does not install cron for you. On the machine that should refresh the cache, a typical crontab entry is:

```cron
CRON_TZ=America/New_York
0 10 * * * cd /path/to/attendee-tracker && . .venv/bin/activate && python -m attendee_tracker.ingest >> data/ingest.log 2>&1
```

`CRON_TZ` is supported by many cron daemons (including Vixie cron). If the host is already set to `America/New_York`, the `CRON_TZ` line can be dropped. If the host cron is UTC and does not support `CRON_TZ`, schedule 14:00 UTC during EDT and 15:00 UTC during EST instead of guessing one UTC hour year-round.

For the current season, the same cron line can call `python -m attendee_tracker.refresh_current` instead of ingest. That still pulls CFBD first, then fills null attendance from ESPN. Keep a year range off the cron.

## Run the site

```bash
python -m attendee_tracker.serve
```

Open <http://127.0.0.1:8742>. The process binds `0.0.0.0` and uses `PORT` from the environment, default `8742`. Render sets `PORT` for the public service.

- With a live cache for the season, the pages use CFBD data.
- Without one, they use the sample fixture and keep a banner on screen. `?demo=1` on `/api/season` forces that fixture even when a live cache exists.
- A request for a season that has neither a live cache nor the sample (the sample is 2026 only) returns an error. The 2026 sample is not relabeled as another year.
- `/api/season?year=` is still one season, used by the home grid.
- `/api/school/{slug}?from=2021&to=2025` is that school's home-attendance series. `/api/history?from=2021&to=2025` is the same window for every school, without per-game rows. Years with no `data/live/{year}.json` are listed in `missing_years` and are not given a crowd. Teams are matched by team id, then by school name when an older file uses a different id. Conference is stored on each season, so a realignment does not merge two programs or drop the move.
- `/api/valuations` reads the committed file `data/valuations/power_2026.json`. `?sort=valuation` (the default) orders by The Athletic rank. `?sort=nil` orders by the NIL estimate. No key is required, and a missing file is an error rather than a filled-in number.

Regenerate the committed fixture after changing the generator:

```bash
python -m attendee_tracker.sample_data
```

## How the pages behave

Schools are grouped by the conference on `/teams/fbs?year=`. SEC, Big Ten, Big 12, and ACC are Power 4. Every other FBS conference, including independents, is Group of 5 / other FBS. There is no Power 4 flag in CFBD.

Inside a conference the default order is the latest AP Top 25, with unranked schools after ranked schools, then season record. The Record control sorts by win percentage instead. Cards show the logo, name, W-L (and ties when the record has them), and stadium max capacity.

Each card also pins two figures for the season on screen:

- **Season avg** is the mean of reported non-neutral home games. Games with null attendance are left out of the mean. They are not treated as zero. The 2020 season average is not shown. That year is omitted as the COVID season.
- **Last home** is the most recent completed on-campus home game. If that game has a crowd, the card shows it, with the opponent and date. If that game's attendance is null, the card shows an em dash and **Not reported**. It does not copy an earlier crowd into that slot.

When the season has no reported attendance yet (early in the year, before games are played), both pins stay on the card as an em dash with **Awaiting attendance**. The fields are not hidden, so the layout is ready when the next season's numbers show up.

A school page has three range chips. **This season** is the per-game home chart for the season the site is showing. **Last 5 seasons** and **Last 10 seasons** end on that same year, inclusive: an active 2025 season is 2021–2025 or 2016–2025. Those views chart **average home attendance by year**, so growth (or a drop) is the point of the chart. The axis starts at zero. A year with no cache, a year where the school is absent, or a year with no reported attendance is a gap, labeled in the table, never a guessed number. 2020 is omitted as the COVID season: if it falls inside Last 5 or Last 10, that year is skipped in the average and in the change between seasons, so a last-10 window that includes 2020 uses the other seasons only. The year stays in the table, labeled omitted, and the cache file is not deleted. This season still badges completed games with null attendance as **Attendance not reported** and games that have not been played as **Not yet played**.

Below that chart, **Business & athletics news** lists recent public headlines for that program: NIL, collectives, revenue share, budgets and financing, media rights and TV deals, sponsorships and jersey patches, naming rights, stadium work, ticket revenue, athletic director moves, buyouts and contract extensions, and realignment money. Each row is the headline, the publisher, the date, and a link to the original. The page does not copy article text. It asks for the list only after the school view opens (`GET /api/school/{slug}/business-news`) and caches it under `data/news/{slug}.json` for 12 hours.

The list merges a per-school Google News search with publisher RSS when those feeds respond: Front Office Sports, Sportico, The Athletic’s college football feed, Yahoo college sports, and Football Stadium Digest. A feed item is kept only when the headline matches that school. The full name is enough for a specific program. Miami, Georgia, Washington, USC, and a bare “State” need the school name plus mascot or city, or two aliases (name, abbreviation, mascot, city). A neighbor such as Georgia Tech or Washington State is not assigned on the shorter name. Game packaging (recap, preview, odds, how to watch, rankings, highlights) sorts below a clean business headline, and a ticket pitch with no finance topic is left out. A timeout or a program with nothing on topic shows an empty state. Nothing is invented. The note under the list says this portfolio app only aggregates headlines and links out, and that Google News RSS is a prototype source rather than a commercial redistribution license.

ESPN team news JSON, On3 school pages, and Knight-Newhouse finance figures are left for a later pass. This page does not scrape them.

The analysis page fits average home capacity percentage against season win percentage (ordinary least squares and Pearson's r), plus recent form and a pregame-form check. Outliers are teams that break a weaker-record, thinner-crowd pattern. The methodology is on that page. Teams without enough reported attendance, or without a capacity, are left out and named.

The same page has two ranked lists, **Most loyal fans** and **Softest home support**. A bad record is a season win percentage at or below the median of the teams that qualify for the fit (at least two reported home games with a capacity percentage, and at least two decided games). Loyal fans are that group ordered by the highest average capacity filled. Softest home support is the same group ordered by the lowest. Each list shows at most ten teams. The rank is percent of seats, never raw attendance. A crowd total can sit beside the percentage as context. Teams with no capacity percentage, including a reported crowd at a stadium with no listed capacity, are left off both lists.

The same page also ranks **Fastest-growing fanbases** and **Fastest-falling crowds** from multi-year home attendance. The window is the last 10 seasons ending on the season the site is showing. Each season’s figure is the average of reported non-neutral home games. A blank year is skipped, not treated as zero. 2020 is omitted as the COVID season and does not count toward the five-season minimum. The sort is the compound annual change from the earliest non-2020 season to the latest, not the size of the crowd. The row shows that rate, the total change, the start and end seasons, and the latest average. Ties break by school name. Schools that list an NFL stadium as home in any cached season are left off both lists. When nobody declined, the second list is the weakest growth rates and is labeled that way. Follower counts are not shown. There is no social data source here, and none is invented.

Schools whose listed home stadium is an NFL building are kept out of those lists and out of the capacity-percentage fit. The seeded homes are UNLV at Allegiant, South Florida at Raymond James, Miami at Hard Rock, Temple at Lincoln Financial, and Pittsburgh at Acrisure (including the Heinz Field name). A team is also flagged when its listed home is Mercedes-Benz Stadium, SoFi, Levi's, Gillette, the Caesars Superdome, NRG, Lucas Oil, or MetLife. The official CFBD capacity is not replaced, and attendance is not invented. Those schools appear in **NFL home stadiums**, ordered by average reported crowd, with the official capacity and official fill labeled as not comparable to an on-campus stadium. Cards and school pages show a small NFL stadium badge. A program is flagged only while that building is the home stadium in the season file.

The valuations tab lists the 68 Power football programs (SEC, Big Ten, Big 12, ACC, and Notre Dame). Each row is the published rank, the same logo used on the school card, the school and conference, The Athletic valuation, and the NIL estimate. Valuation is the default sort. NIL budget is the other sort, and in that order the year-over-year arrows are left off, since there is no prior NIL ranking. A green arrow is spots moved up from The Athletic's July 2025 ranking, a red arrow is spots moved down, and a dash is no change. Those spots are `rank_change_spots` in the file (the same figure as prior rank minus current rank). Conference chips filter the list. A school row opens that program's existing page when the season cache has the same school name.

The dollars are not computed here. Valuations are The Athletic's July 28, 2026 hypothetical football-program sale prices. Movement is against their July 21, 2025 list. NIL is nil-ncaa.com's estimated football roster cost for 2026-27 (school revenue share to football plus third-party NIL), marked as an estimate, not a school-audited budget. The page links those sources. There is no in-season estimate.

## Deploy on Render (free)

[`render.yaml`](render.yaml) is a Render Blueprint for one free Python web service. After this repo is on GitHub:

1. Open the [Render dashboard](https://dashboard.render.com) and choose **New** → **Blueprint**.
2. Connect GitHub if Render asks, then select **lukegrantbuckley-boop/Attendee-Stats**.
3. Render reads `render.yaml`. Confirm the service and choose **Apply** (deploy).
4. When the deploy finishes, open the public `onrender.com` URL Render shows for `attendee-stats`.

The Blueprint sets:

| Setting | Value |
| --- | --- |
| Install | `pip install -r requirements.txt` |
| Start | `python -m attendee_tracker.serve` |
| Bind | `0.0.0.0` and Render's `$PORT` |
| `SEASON_YEAR` | `2026` |
| Python | `3.12.7` |

Do not put `CFBD_API_KEY` in the repo or in `render.yaml`. The free site uses the committed `data/live` caches. The default season is 2026. To refresh from CFBD later, add `CFBD_API_KEY` as a secret environment variable in the Render dashboard only. This Blueprint does not run ingest or the ESPN fill.

Free web services on Render sleep after a period with no traffic. The first request after sleep can take a minute while the process starts.

## Logos

Phase 1 uses the `logos` URLs CFBD returns for each team, hosted on `cdn.collegefootballdata.com`. [CFBD's terms](https://collegefootballdata.com/terms) do **not** grant rights to display school logos or other marks. Showing those URLs is fine for this portfolio. Revisit licensing and trademark use before any commercial deployment. If a logo URL fails to load, the card falls back to a monogram in the school's color.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Known gaps

- Attendance is often null, and CFBD does not promise when it will be filled in. The daily games pull is there so late numbers can show up later. `python -m attendee_tracker.refresh_current` fills nulls on completed non-neutral home games from ESPN summaries when ESPN has a figure. The UI leaves blanks blank.
- "Attendance" in the feed is the figure CFBD publishes (often tickets distributed / reported), not a turnstile count.
- Conference names follow that season's `/teams/fbs` response. Realignment years should be re-checked; the Power 4 set is the four conferences named above. The multi-year chart keeps each season's conference on its own row.
- History charts only include seasons that have been ingested. Until you backfill, Last 5 and Last 10 will show the years you have and name the rest as missing.
- Ticket prices are out of scope for Phase 1. There is no placeholder price data.
- Business headlines are links out to public feeds. ESPN team news, On3 school pages, and Knight-Newhouse finance numbers are not pulled yet.
- Attendance growth uses seasons that have been ingested. A program with fewer than five reported home averages in the last 10 seasons is left off both growth lists. 2020 is omitted as the COVID season from those averages and from the growth rate. Social follower history is not part of this app.
