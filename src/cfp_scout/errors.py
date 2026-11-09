"""Errors that reach the agent. Each one says what failed and what to do next."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError


class CfpScoutError(ToolError):
    """Base error. The message is safe to show: it never contains the API key.

    Subclassing ToolError matters: the MCP SDK hides the text of any other exception
    from the client, and a vague error would defeat the point of breaking loudly.
    """

    code = "CFP_SCOUT_ERROR"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        text = f"[{self.code}] {message}"
        if hint:
            text = f"{text} Next step: {hint}"
        super().__init__(text)


class BadInputError(CfpScoutError, ValueError):
    """A tool argument is invalid."""

    code = "BAD_INPUT"


class MissingApiKeyError(CfpScoutError):
    code = "MISSING_API_KEY"


class TinyFishApiError(CfpScoutError):
    """TinyFish rejected or failed the request (auth, wallet, rate limit, outage)."""

    code = "TINYFISH_API_ERROR"


class PageFetchError(CfpScoutError):
    """TinyFish could not read a page (blocked, timeout, not found)."""

    code = "PAGE_FETCH_FAILED"


class SiteChangedError(CfpScoutError):
    """The page loaded but no longer has the expected structure.

    Raised instead of returning an empty or partial result, so a layout change
    can never look like "no conferences found".
    """

    code = "SITE_CHANGED"


class EventNotFoundError(CfpScoutError):
    code = "EVENT_NOT_FOUND"


class OfficialSiteNotFoundError(CfpScoutError):
    code = "OFFICIAL_SITE_NOT_FOUND"


class AgentRunError(CfpScoutError):
    """The TinyFish Agent run failed or finished without a usable answer."""

    code = "AGENT_RUN_FAILED"


class AgentBudgetError(CfpScoutError):
    """The per-process Agent run limit was reached, so no more wallet funds are spent."""

    code = "AGENT_BUDGET_REACHED"


class WatchNotFoundError(CfpScoutError):
    code = "WATCH_NOT_FOUND"
