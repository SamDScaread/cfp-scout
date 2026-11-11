# Demo script

Record one real conversation in Claude Desktop or Claude Code, using these prompts in order. Use a fresh chat with memory and custom instructions turned off, so the conversation shows only the tools. Show the tool calls on screen. Do not show your API key, your config file or your chat history.

1. "Use CFP Scout to find robotics conferences with paper deadlines in the next 30 days. Show the name, deadline and location."
2. "Look up the ICORE rank of the five most relevant ones, and of ICRA for comparison."
3. "For the most promising one, confirm the paper deadline on its official website and show me where you found it."
4. "Start watching that page for deadline changes. Check it once now, then stop the watch."
5. "Run a health check."

Expected tools: `search_calls`, `get_venue_rank`, `verify_deadline`, `watch_deadline`, `check_watch`, `stop_watch`, `health_check`. Prompt 3 spends about $0.06 to $0.21 from your TinyFish wallet and prompt 4 about $0.01. The other prompts are free. If a take goes wrong, retry in the same conversation without restarting the client: a repeat `verify_deadline` for the same site within six hours reuses the cached answer at no cost.

To show a loud failure, run the layout-change tests:

```
uv run --extra dev pytest tests/test_breaks_loudly.py -v
```
