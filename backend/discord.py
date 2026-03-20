"""
Discord webhook integration for JukeBoxx notifications.
"""
import logging
import httpx
from database import get_setting

log = logging.getLogger("jukeboxx.discord")

# Discord embed colors
COLOR_GREEN  = 0x1DB954   # completed
COLOR_RED    = 0xE74C3C   # failed
COLOR_BLUE   = 0x3498DB   # info
COLOR_ORANGE = 0xE67E22   # warning / new release


async def send_discord(title: str, description: str, color: int = COLOR_BLUE, fields: list | None = None):
    """Post an embed to the configured Discord webhook. Silently no-ops if not configured."""
    webhook_url = await get_setting("discord_webhook_url", "")
    if not webhook_url:
        return
    embed: dict = {"title": title, "description": description, "color": color}
    if fields:
        embed["fields"] = fields
    try:
        async with httpx.AsyncClient(timeout=10) as hc:
            resp = await hc.post(webhook_url, json={"embeds": [embed]})
            if resp.status_code not in (200, 204):
                log.debug(f"Discord webhook returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.debug(f"Discord webhook error: {e}")


async def notify_dispatch_result(dispatched: int, breakdown: dict):
    """Called after a multi-source dispatch cycle."""
    if await get_setting("discord_notify_dispatch", "0") != "1":
        return
    if dispatched == 0:
        return
    parts = ", ".join(f"{v} via {k}" for k, v in breakdown.items())
    await send_discord(
        title=f"JukeBoxx — {dispatched} track{'s' if dispatched != 1 else ''} dispatched",
        description=parts or "Auto-dispatch completed.",
        color=COLOR_BLUE,
    )


async def notify_download_complete(title: str, artist: str, source: str):
    """Called when a unified_download is marked completed."""
    if await get_setting("discord_notify_download_complete", "1") != "1":
        return
    await send_discord(
        title="JukeBoxx — Download Complete",
        description=f"**{title}** by *{artist}* — via {source}",
        color=COLOR_GREEN,
    )


async def notify_new_releases(releases: list):
    """Called when new releases are detected. releases = [{artist, album, type}]"""
    if await get_setting("discord_notify_new_release", "1") != "1":
        return
    if not releases:
        return
    lines = "\n".join(f"• **{r['artist']}** — {r['album']} ({r['type']})" for r in releases[:10])
    if len(releases) > 10:
        lines += f"\n_…and {len(releases) - 10} more_"
    await send_discord(
        title=f"JukeBoxx — {len(releases)} New Release{'s' if len(releases) != 1 else ''} Found",
        description=lines,
        color=COLOR_ORANGE,
    )
