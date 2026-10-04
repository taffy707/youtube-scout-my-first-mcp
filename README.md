# yt-scout

A local MCP server that lets Claude research a YouTube channel: search every video's metadata, read transcripts, and have Gemini watch the exact parts that matter — then answer with timestamped citations.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (already present: `/opt/homebrew/bin/uv`).
2. `uv sync`
3. `cp .env.example .env` and fill in, **in your editor** (never paste keys into chat):
   - `GEMINI_API_KEY` — from Google AI Studio.
   - `YOUTUBE_API_KEY` — Google Cloud console → enable *YouTube Data API v3* → Credentials → API key → restrict it to *YouTube Data API v3*.
4. `uv run pytest` — offline unit tests.
5. `uv run pytest -m live` — optional real-API smoke test (uses ~2 min of Gemini allowance and ~150 YouTube quota units).

## Register with Claude Code

From this folder:

```bash
claude mcp add --scope project yt-scout -- uv run --directory "/Users/Pulse/Desktop/yt=scrap" yt-scout
```

This writes `.mcp.json` (no secrets in it — keys are read from `.env`). Restart Claude Code and approve the server.

### Claude Desktop (optional)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "yt-scout": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--directory", "/Users/Pulse/Desktop/yt=scrap", "yt-scout"]
    }
  }
}
```

## Using it

Ask Claude something like:

> Using yt-scout on @ycombinator: I'm building a startup — what KPIs should I focus on at pre-seed?

Claude indexes the channel, searches with several phrasings (and on big channels browses playlist titles, then the titles inside a promising playlist), shows you a shortlist, reads transcripts, has Gemini watch the key ranges, and answers with links that jump to the right second.

## Tools

| Tool | Cost |
|---|---|
| `index_channel` | YouTube quota (~1 unit per 50 videos) |
| `list_playlists`, `list_playlist_videos` | YouTube quota (~1 unit per 50 playlists / videos; cached 7 days) |
| `search_videos`, `get_video_details` | free (local) |
| `get_transcript` | free |
| `watch_video` | Gemini daily video allowance (`GEMINI_DAILY_VIDEO_SECONDS`, default 7 h) |
| `usage_status` | free |

`watch_video` detail levels: `skim` (low-res, 0.5 fps, 15-min chunks), `normal` (low-res, 1 fps), `high` (high-res, 2 fps). Ranges are split into `WATCH_CHUNK_SECONDS` (default 180 s) chunks watched in parallel; shorter chunks give more detailed notes.

## Troubleshooting

- **`transcripts_blocked`** — YouTube is rate-limiting caption requests from your IP. Claude falls back to `watch_video`; or retry later.
- **`budget_exceeded`** — today's Gemini allowance is used; resets 00:00 UTC. Raise `GEMINI_DAILY_VIDEO_SECONDS` only if you're on a paid tier.
- **`gemini_rejected`** — the video is private, age-restricted, region-locked, or the model name is wrong. Check `GEMINI_MODEL`.
- **Long watches time out in Claude Code** — raise the MCP tool timeout, e.g. `MCP_TOOL_TIMEOUT=600000 claude`.
- Cache lives at `~/.yt-scout/cache.db`; delete it to start fresh.
