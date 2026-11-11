# CFP Scout

**WikiCFP has no API, and its listings go stale. CFP Scout turns it into typed tools your agent can call, then checks the real deadline on the conference's own website.**

Built on [TinyFish](https://www.tinyfish.ai) for the Site to MCP bounty.

> Demo: *add your recording link here before submitting*

Ask your agent things like:

> Which robotics conferences have deadlines in the next 30 days? Which are ranked? Confirm the real deadline for the best one, and tell me if it gets extended.

## Tools

| Tool | What it does | TinyFish endpoint | Cost |
| --- | --- | --- | --- |
| `search_calls(topic, deadline_within_days, limit, start_page)` | Upcoming calls by topic, soonest deadline first | Fetch | Free |
| `get_call(event_id)` | Dates, location, categories, official link, per-track date lines | Fetch | Free |
| `get_venue_rank(acronym, edition)` | ICORE rank (A*, A, B, C) | Fetch | Free |
| `verify_deadline(event_id, official_url, conference_name)` | Confirms the deadline on the official site, with an evidence link | Agent, Fetch, Search as fallback | About $0.06 to $0.21 |
| `watch_deadline(url, conference_name, schedule_cron)` | Starts a recurring check, to catch extensions | Monitor | $0.005 per check |
| `check_watch(monitor_id)` | Reports which deadline lines changed | Monitor | $0.005 |
| `stop_watch(monitor_id)` | Deletes the watch and stops its charges | Monitor | Free |
| `health_check(include_agent, include_watch)` | Probes every site and reports what is broken | Fetch, plus Agent and Monitor if asked | Free, or up to about $0.21 |

Every tool has typed inputs and a typed output schema. Example result from `verify_deadline`, using a real ICRA 2027 run, with some fields left out:

```json
{
  "conference_name": "ICRA 2027",
  "status": "verified",
  "verification_method": "date_match",
  "deadline": "2026-09-16",
  "was_extended": true,
  "submissions_closed": true,
  "notification_date": "2027-01-31",
  "timezone": "PST",
  "evidence_url": "https://2027.ieee-icra.org/contribute/call-for-icra-2027-papers-now-accepting-submissions/",
  "agent_steps": 13,
  "estimated_cost_usd": 0.208
}
```

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), git, and a [TinyFish API key](https://agent.tinyfish.ai/api-keys).

**Claude Code:** set `TINYFISH_API_KEY` in your environment, then add this to `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "cfp-scout": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/SamDScaread/cfp-scout", "cfp-scout"],
      "env": { "TINYFISH_API_KEY": "${TINYFISH_API_KEY}" }
    }
  }
}
```

**Claude Desktop, Cursor and other local clients:** use the same `command` and `args`, and put your key in `env` in that client's own config file. Never commit that file.

`verify_deadline` can take up to 2 minutes. Claude Code allows that by default. Some clients stop tool calls sooner, so raise the limit if yours times out, because a run that was cut off is still charged.

This server speaks MCP over stdio. Clients that only accept a remote URL, such as ChatGPT connectors, need a bridge or a hosted deployment, which this project does not include.

**Check that it works:**

```
uvx --from git+https://github.com/SamDScaread/cfp-scout cfp-scout-health
```

## How TinyFish is used

**Fetch does the reading.** It renders WikiCFP's listing and event pages and the ICORE ranking portal, and parsers turn them into typed fields. Fetch also checks that a conference link works before any paid Agent run, and independently re-reads whichever page the Agent cites.

**Agent does the clicking.** Every conference builds its site differently, with dates under "Important Dates", "Call for Papers", a sidebar or an announcement. No fixed scraper can cover them all. The Agent gets the site and a goal, navigates to the deadline, and returns structured JSON with an evidence URL.

**Search finds the site** when WikiCFP's link is missing or dead. The result must name the conference, and the output warns that it came from search.

**Monitor watches for extensions.** Deadlines move. The ICRA 2027 page marks its deadline "Extended", while its FAQ still says there is no plan to extend. Monitor re-reads the page on a schedule, and `check_watch` compares its deadline lines against a saved baseline.

## Why you can trust the output

The Agent's answer is treated as a claim. Fetch re-reads the cited page, and the date must appear there:

- `verified`: the quote or date was found on `evidence_url`.
- `unverified`: the date could not be found there, so `deadline` is withheld and `warnings` explains why.
- `not_found`: the site does not state a deadline the Agent could find.

If the official site disagrees with WikiCFP, `matches_wikicfp` is false and a warning says so.

## When a site changes

Tools fail loudly. Each parser separates a real empty result from a changed layout, so a redesign can never look like "no conferences found":

```
[SITE_CHANGED] WikiCFP category page for 'robotics' has neither a results table nor the home page content.
Next step: Run health_check, then update parsers.py for the new layout.
```

Three things catch this:

- `health_check` probes the live sites from your agent.
- `cfp-scout-health` does the same from a terminal or CI, and exits 1 if anything broke. Add `--include-agent` (about $0.20) or `--include-watch` (about $0.01) to test the paid tools too.
- `.github/workflows/health.yml` runs it daily, so a failure reaches the maintainer first. Add `TINYFISH_API_KEY` as a repository secret to enable it.

`tests/test_breaks_loudly.py` shows the failures against altered copies of real pages.

## Limits

- **WikiCFP coverage:** it mostly covers computing and engineering, is community-edited, and lists many small venues first. Some major venues are missing: RSS 2027 was not listed in November 2026. For those, call `verify_deadline` with `official_url` directly.
- **ICORE coverage:** it ranks computing venues only. An unlisted venue is not necessarily a poor one, and this tool does not judge whether a conference is predatory.
- **Speed:** WikiCFP pages take about 5 seconds each, because this server honours its crawl limit.
- **Deadlines:** `verify_deadline` covers the main paper track. Use `date_lines` from `get_call` for other tracks, and check `evidence_url` before relying on a date.
- **Watches:** Monitor reads a page's main content, so dates in a sidebar may be missed. Prefer a dedicated call for papers page.

## Data and responsible use

WikiCFP content is licensed [CC BY-SA 3.0](http://creativecommons.org/licenses/by-sa/3.0/), and results include attribution. The server keeps to WikiCFP's limit of [one query every five seconds](http://www.wikicfp.com/cfp/data.jsp). Rankings come from the [ICORE portal](https://portal.core.edu.au/conf-ranks/). Your API key is read from the environment and never logged. Design choices are explained in [docs/DECISIONS.md](docs/DECISIONS.md).

## Develop

```
uv run --extra dev pytest
```

MIT licensed. Developed with Claude as a coding assistant.
