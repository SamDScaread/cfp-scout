# Design decisions

**Target site: WikiCFP.** It has no public API that I could find, researchers use it to track deadlines, and it states its crawl rule openly. The existing `call-for-papers-mcp` project exposes one search tool. This project adds official-site verification, venue ranks, change watching and health checks.

**Listings are treated as unverified.** WikiCFP is community-edited, and a listing has one deadline field even when a conference has several tracks. So `get_call` also returns `date_lines`, and only `verify_deadline` can confirm a date.

**Agent answers are checked, not trusted.** In five real test runs, the main deadline was right every time, but other fields were not: the Agent returned the string `"null"`, cited a generic submission site, gave a page limit that could not be confirmed on the page it cited, reported an abstract deadline the page did not state, and paraphrased when asked for a verbatim quote. So Fetch re-reads the cited page, the date must appear there, and unreliable fields such as page limits were removed.

**Evidence is read from the full page body.** Cleaned markdown dropped a sidebar holding the ICRAI 2026 dates, which would have marked a correct answer as unverified.

**Respect for the source.** WikiCFP asks for at most one query every five seconds, so the server enforces that gap and caches pages for an hour. Every WikiCFP result carries CC BY-SA attribution and a source link.

**Personal data stays out.** `date_lines` drops lines with email addresses or contact details, and full call text is not returned.

**Spending is bounded.** Search and Fetch are free. Agent runs have a time limit, are never retried automatically, are cached for six hours per site, and stop after 20 runs per process (`CFP_SCOUT_MAX_AGENT_RUNS`). Fetch checks a link before an Agent run is paid for.

**Direct REST calls instead of the SDK.** The Python SDK (0.11.0) does not expose `include_selectors`, which the parsers need to keep links and metadata.

**A local watch record.** The Monitor API has no run-history endpoint, so baselines are stored in `~/.cfp-scout/watches.json` and compared on each check. `stop_watch` only deletes monitors this server created.
