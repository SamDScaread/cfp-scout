# Demo script

Record one real conversation in Claude Code or Claude Desktop, using these prompts in order. Show the tool calls on screen. Do not show your API key or your config file.

1. "Which robotics conferences have paper deadlines in the next 30 days? Show the name, deadline and location."
2. "Check the ICORE ranks of the three you think are most relevant, and also ICRA for comparison."
3. "Confirm the real deadline for ICRAI 2026 on its official website, and show me where you found it."
4. "Now confirm the ICRA 2027 paper deadline. Was it extended?"
5. "Watch the NOMS 2027 call for papers page so I hear about an extension, then check it and stop the watch."
6. "Run a health check."

Expected tools: `search_calls`, `get_venue_rank`, `verify_deadline`, `watch_deadline`, `check_watch`, `stop_watch`, `health_check`. Prompts 3 and 4 spend about $0.18 to $0.21 each from your TinyFish wallet, and prompt 5 about $0.01, so a full take costs about $0.40. Retakes within six hours reuse the cached answer only if the server stays running.

To show a loud failure, run the layout-change tests:

```
uv run --extra dev pytest tests/test_breaks_loudly.py -v
```
