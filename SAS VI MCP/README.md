# SAS Visual Investigator MCP Server

A Model Context Protocol (MCP) server that turns a SAS Visual Investigator
(VI) environment into an agent-ready investigation toolkit: alert triage,
entity/data-hub exploration, free-text search, network (link) analysis and
investigation workflows.

Built for **SAS Retrieval Agent Manager (RAM)**: RAM pulls the container image
from GHCR and hosts it as a **Container MCP Server** (HTTP transport, base
path `/mcp`). Every tool is grounded in the official VI 2026.04 OpenAPI specs
(in [`api-specs/`](api-specs/)) — no guessed endpoints:

| Service | Spec | What it powers |
|---|---|---|
| `svi-alert` | v6 | alerts, scorecards, scenario-fired events, dispositions |
| `svi-datahub` | v11 | entity types, records, relationships, comments, attachments |
| `svi-sand` | v10 | free-text search, graph/network expansion, related objects |
| `workflows` | v4 | investigation workflow tasks and processes (mounted under `svi-datahub`) |

## Tools

**Scope & diagnostics** — `get_investigation_scope`, `check_vi_connection`

**Alert triage** — `list_alerts`, `get_alert`, `get_alert_fired_events`
(why it fired), `get_alert_scorecard` (score composition),
`list_alert_queues`, `list_alert_strategies`, `list_alert_dispositions`,
`disposition_alert`*, `perform_alert_action`* (checkout/checkin/assign)

**Entities (data hub)** — `list_entity_types`, `list_relationship_types`,
`list_entities`, `get_entity`, `get_related_entities`,
`get_entity_comments`, `get_entity_attachments`

**Search & network** — `search_investigator` (lucene free-text across all
indexed data), `get_entity_network` (link-analysis expansion),
`find_related_entities` (multi-hop "who else is connected?")

**Workflow** — `list_workflow_tasks`, `get_workflow_task`,
`list_workflow_processes`, `complete_workflow_task`*

**Escape hatch** — `vi_api_request` (generic call against any of the four
services when no dedicated tool fits; writes gated)

\* Write tools are refused unless `VI_ALLOW_ACTIONS=true`, so a read-only
demo agent can never mutate the environment by accident.

## Container image

Pushed to GHCR by [`.github/workflows/publish-sas-vi-mcp.yml`](../.github/workflows/publish-sas-vi-mcp.yml):

```
ghcr.io/raedaldweik/sas-vi-mcp:latest
ghcr.io/raedaldweik/sas-vi-mcp:<commit-sha>
```

> A new GHCR package is **private by default**. After the first push, open
> GitHub → Profile → Packages → `sas-vi-mcp` → Package settings and set the
> same visibility/access you gave `sas-mcp-server` and `web_search`, so RAM
> can pull it.

The image serves streamable HTTP on port **8141** at base path **`/mcp`**;
`/health` stays open for probes.

## Reaching a RACE-hosted VI (cloudflared)

RAM cannot reach a RACE image directly. Start a quick tunnel on a machine
that can:

```bat
winget install Cloudflare.cloudflared
cloudflared tunnel --url https://azureuse011246.race.sas.com ^
  --no-tls-verify --http-host-header azureuse011246.race.sas.com
```

Use the printed `https://<random>.trycloudflare.com` URL as `VI_ENDPOINT`.

**Important:** a quick tunnel gets a *new random URL every time cloudflared
restarts* — when that happens, update `VI_ENDPOINT` in the RAM template and
restart the tool. For a stable URL (recommended before a big demo), create a
named tunnel on a free Cloudflare zone instead.

## Register in RAM (Container MCP Server template)

RAM → **Code Templates → Tools → Container MCP Server**:

**Settings**

| Field | Value |
|-------|-------|
| Name | `SAS_VI_MCP` |
| Description | `SAS Visual Investigator — alert triage, entity investigation, network analysis` |
| Container image | `ghcr.io/raedaldweik/sas-vi-mcp:latest` |
| Arguments | *(empty — entrypoint defaults to http-direct)* |
| Transport | **HTTP** |
| Port | **8141** |
| Base Path | **/mcp** |
| Requested CPU | `1` |
| Requested Memory | `1Gi` |

**Authentication:** None (the server signs in to VI itself; RAM reaches
`/mcp` in-cluster).

**Environment Variables**

| Name | Value | Secret |
|------|-------|--------|
| `VI_ENDPOINT` | `https://<your-tunnel>.trycloudflare.com` | |
| `VI_USERNAME` | VI user with investigator rights | |
| `VI_PASSWORD` | its password | ✅ |
| `VI_CLIENT_ID` | `sas.cli` (default; supports the password grant on RACE) | |
| `VI_SSL_VERIFY` | `false` (RACE / quick tunnel TLS) | |
| `VI_ALLOW_ACTIONS` | `false` (set `true` only to demo dispositions/workflow actions) | |
| `VI_USE_CASE` | one line describing the deployment, e.g. `Procurement integrity monitoring...` | |

Alternative credentials for SSO/federated identities: set `VI_REFRESH_TOKEN`
(secret ✅) instead of username/password, with the `VI_CLIENT_ID` /
`VI_CLIENT_SECRET` the token was issued to.

Optional extras: `MCP_API_KEY` (protect `/mcp` with a static key),
`VI_MAX_CHARS` (response size cap, default 16000), `VI_TIMEOUT` (seconds,
default 120), `HOST_PORT` (default 8141), and
`VI_ALERT_BASE`/`VI_DATAHUB_BASE`/`VI_SAND_BASE`/`VI_WORKFLOW_BASE` if an
ingress rewrites service paths.

## Verify before the demo

```bash
docker run --rm -p 8141:8141 \
  -e VI_ENDPOINT=https://<tunnel>.trycloudflare.com \
  -e VI_USERNAME=... -e VI_PASSWORD=... -e VI_SSL_VERIFY=false \
  ghcr.io/raedaldweik/sas-vi-mcp:latest

curl -s localhost:8141/health
# {"status":"healthy","service":"sas-vi-mcp","vi_endpoint_configured":true,...}
```

Then in RAM chat, ask the agent to run `check_vi_connection` — it reports
per-service reachability and pinpoints config problems (wrong tunnel URL,
bad credentials, missing permissions) in plain language.

## Local development

```bash
uv sync --dev
uv run pytest          # offline unit tests
uv run ruff check .
uv run app-http-direct # http://localhost:8141/mcp
```
