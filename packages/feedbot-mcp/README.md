# feedbot-mcp

> MCP server that connects Claude Code to your Feedbot deployment.

This is a **thin client**. No DB, no Google service account, no business logic — it forwards Claude's tool calls to the Feedbot core API over HTTPS using a project-scoped API key.

## Install

```bash
pip install feedbot-mcp
```

Or from source:

```bash
pip install -e packages/feedbot-mcp
```

## Configure Claude Code

Reference: <https://code.claude.com/docs/en/mcp>.

### Option 1 — `claude mcp add` (CLI, recommended for first-time setup)

```bash
claude mcp add feedbot \
  --transport stdio \
  --env FEEDBOT_API_URL=http://localhost:8000 \
  --env FEEDBOT_API_KEY=fbk_live_... \
  -- feedbot-mcp
```

> All options (`--transport`, `--env`, `--scope`, `--header`) must come **before** the server name. The `--` then separates the name from the actual command.

Add `--scope project` to write the entry into `.mcp.json` (shared with the team) instead of your local user config.

### Option 2 — `.mcp.json` (committed, project-scoped)

Drop this at the root of your Claude Code project:

```json
{
  "mcpServers": {
    "feedbot": {
      "command": "feedbot-mcp",
      "args": [],
      "env": {
        "FEEDBOT_API_URL": "http://localhost:8000",
        "FEEDBOT_API_KEY": "fbk_live_..."
      }
    }
  }
}
```

Issue the API key from your project page in the Feedbot dashboard. Each Claude Code workspace should use a different key — that's how multi-project isolation works.

### Option 3 — Remote HTTP (planned, M1.5)

When the hosted Feedbot instance ships, you'll be able to skip this stdio package entirely:

```bash
claude mcp add feedbot \
  --transport http \
  --header "Authorization: Bearer fbk_live_..." \
  https://feedbot.io/mcp
```

This is the transport [Anthropic recommends for cloud services](https://code.claude.com/docs/en/mcp#option-1-add-a-remote-http-server). Until it lands, use stdio.

## Tools exposed

| Tool | Example prompt |
|---|---|
| `list_feedbacks` | *"What's in the new bug pile?"* |
| `get_feedback` | *"Pull up FB-A3F2."* |
| `update_status` | *"Mark FB-A3F2 done — fixed in PR #91."* |
| `add_note` | *"Note on FB-B7C1: needs design review."* |
| `reply_to_user` | *"Ask the reporter of FB-A3F2 for their iOS version."* |
| `search_feedbacks` | *"Have we seen this export crash before?"* |
| `get_stats` | *"How's the pipeline?"* |

## Development

```bash
pip install -e .
FEEDBOT_API_URL=http://localhost:8000 FEEDBOT_API_KEY=fbk_live_... feedbot-mcp
```

Use `claude mcp list` to verify it shows up; use `/mcp` inside Claude Code to inspect.
