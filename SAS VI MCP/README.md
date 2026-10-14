# SAS Visual Investigator MCP Server

A Model Context Protocol (MCP) server that turns a SAS Visual Investigator
(VI) environment into an agent-ready investigation toolkit: alert triage,
entity/data-hub exploration, free-text search, network (link) analysis and
investigation workflows.

Built for **SAS Retrieval Agent Manager (RAM)**: RAM pulls the container image
from GHCR and hosts it as a **Container MCP Server** (HTTP transport, base
path `/mcp`). The server signs in to VI itself with a **refresh token** — the
same recipe as the SAS Viya MCP (`ghcr.io/raedaldweik/sas-mcp-server:ram` with
`VIYA_REFRESH_TOKEN`) — so RAM needs no OAuth and no stored password.

Every tool is grounded in the official VI 2026.04 OpenAPI specs (in
[`api-specs/`](api-specs/)) — no guessed endpoints:

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
ghcr.io/raedaldweik/sas-vi-mcp:ram            ← what the RAM template references
ghcr.io/raedaldweik/sas-vi-mcp:latest         (same image)
ghcr.io/raedaldweik/sas-vi-mcp:sha-<commit>
```

> A new GHCR package is **private by default**. After the first push, open
> GitHub → Profile → Packages → `sas-vi-mcp` → Package settings and set the
> same visibility/access you gave `sas-mcp-server` and `web_search`, so RAM
> can pull it.

The image serves streamable HTTP on port **8141** at base path **`/mcp`**;
`/health` stays open for probes and reports which grant is configured.

## Step 1 — Get a refresh token (one time)

The container authenticates to VI on its own. It does that with the OAuth
**refresh-token grant**: you sign in **once** in a browser, capture a
long-lived refresh token, and the server exchanges it for access tokens from
then on — with the full identity and VI permissions of the user who signed
in, no browser and no password afterwards. This works whether the account is
a local one or comes through SSO/Entra/Okta (where the password grant cannot
be used), so it is the right choice for a RACE/Engage image as much as for a
customer environment.

It uses the **same `sas-mcp` OAuth client as the SAS Viya MCP** (grants
`authorization_code` + `refresh_token`, redirect
`http://localhost:8134/auth/callback`, one-year refresh validity).

**1a. Make sure `sas-mcp` exists on the VI environment.** An OAuth client
lives in one Viya deployment's SAS Logon:

- VI runs on the **same Viya** your SAS Viya MCP uses → it is already
  registered, skip to 1b. (Because it is the same SAS Logon and the same
  client, the SAS MCP template's `VIYA_ENDPOINT` / `VIYA_REFRESH_TOKEN` /
  `CLIENT_ID=sas-mcp` values also work as-is on the VI template — the server
  accepts those names. A separate token from 1b is still cleaner: the two
  tools then expire and get rotated independently.)
- VI is a **different Viya** (e.g. an Engage image) → register it once, as
  an administrator, exactly as you ran `register_mcp_client.py` before:

  ```sh
  cd "SAS VI MCP" && uv sync
  uv run vi-register-client --endpoint https://<vi-host> --insecure
  # or, SAS-MCP style:  uv run python examples/register_vi_client.py --insecure
  ```

  It prompts for an admin that SAS Logon authenticates directly (`sasboot`
  or a local admin); pass `--admin-token` for an SSO admin. It replaces any
  existing `sas-mcp` client and prints the registration it verified.

**1b. Sign in once and capture the token:**

```sh
uv run vi-get-refresh-token --endpoint https://<vi-host> --insecure
# or, SAS-MCP style:  uv run python examples/get_refresh_token.py --insecure
```

… or straight from the image, with no Python on your machine:

```sh
docker run --rm -it -p 8134:8134 ghcr.io/raedaldweik/sas-vi-mcp:ram \
  vi-get-refresh-token --endpoint https://<vi-host> --insecure --no-browser
```

What happens — the same flow as the SAS Viya MCP's `get_refresh_token.py`:

1. It prints a SAS Logon URL (and opens it). Sign in as the VI user the agent
   should act as — a user with investigator rights.
2. SAS Logon redirects the browser to `http://localhost:8134/auth/callback`,
   where the helper is listening.
3. The helper prints the three lines for RAM, plus the token's expiry date:

   ```
   VI_ENDPOINT=https://<vi-host>
   VI_CLIENT_ID=sas-mcp
   VI_REFRESH_TOKEN=eyJ...
   ```

`--insecure` is for RACE/Engage self-signed certificates and cloudflared quick
tunnels (it maps to `VI_SSL_VERIFY=false` in the container). `--endpoint` can
be omitted when `VI_ENDPOINT` (or `VIYA_ENDPOINT`) is set in a `.env` — see
[`.env.sample`](.env.sample). Port 8134 is only the local listener for this
one-time sign-in; it is unrelated to the container's port 8141.

**No admin available?** Use the built-in `sas.cli` client instead, which needs
no registration: `vi-get-refresh-token --client-id sas.cli --insecure`. SAS
Logon then shows the authorization code on a page for you to paste back (no
localhost redirect, so no CSP concern). Set `VI_CLIENT_ID=sas.cli` in RAM.
Its refresh-token validity is whatever that deployment configured for
`sas.cli`; the helper prints the expiry either way.

A refresh token only works with the client it was issued to, so
`VI_CLIENT_ID` in RAM must always match the client used here.

## Step 2 — Reach the VI image from RAM (cloudflared)

RAM cannot reach a RACE/Engage image directly. Start a quick tunnel on a
machine that can:

```bat
winget install Cloudflare.cloudflared
cloudflared tunnel --url https://azureuse011246.race.sas.com ^
  --no-tls-verify --http-host-header azureuse011246.race.sas.com
```

Use the printed `https://<random>.trycloudflare.com` URL as `VI_ENDPOINT`.
The refresh token is not tied to the hostname, so it is fine to obtain it
against the RACE host directly and point the container at the tunnel.

**Important:** a quick tunnel gets a *new random URL every time cloudflared
restarts* — when that happens, update `VI_ENDPOINT` in the RAM template and
restart the tool. For a stable URL (recommended before a big demo), create a
named tunnel on a free Cloudflare zone instead.

## Step 3 — Register in RAM (Container MCP Server template)

RAM → **Code Templates → Tools → Container MCP Server**, exactly like the
SAS Viya MCP:

**Settings**

| Field | Value |
|-------|-------|
| Name | `SAS_VI_MCP` |
| Description | `SAS Visual Investigator — alert triage, entity investigation, network analysis` |
| Container image | `ghcr.io/raedaldweik/sas-vi-mcp:ram` |
| Arguments | *(empty — entrypoint defaults to http-direct)* |
| Transport | **HTTP** |
| Port | **8141** |
| Base Path | **/mcp** |
| Requested CPU | `0.5` |
| Requested Memory | `1Gi` |

**Authentication:** None (the server signs in to VI itself; RAM reaches
`/mcp` in-cluster).

**Environment Variables**

| Name | Default Value | Secret |
|------|---------------|--------|
| `VI_ENDPOINT` | `https://<your-tunnel>.trycloudflare.com` | ✅ |
| `VI_REFRESH_TOKEN` | the token from Step 1 | ✅ |
| `VI_CLIENT_ID` | `sas-mcp` (or `sas.cli` if Step 1 used it) | |
| `VI_SSL_VERIFY` | `false` (RACE/Engage / quick tunnel TLS) | |
| `VI_ALLOW_ACTIONS` | `false` (set `true` only to demo dispositions/workflow actions) | |
| `VI_USE_CASE` | one line describing the deployment, e.g. `Procurement integrity monitoring...` | |

The SAS Viya MCP's names are accepted as aliases — `VIYA_ENDPOINT`,
`VIYA_REFRESH_TOKEN`, `CLIENT_ID`, `CLIENT_SECRET`, `SSL_VERIFY` — so you can
copy that template's table and just swap the values (`VI_*` wins when both
are set).

Password-grant alternative for a local (non-SSO) account: set `VI_USERNAME`
and `VI_PASSWORD` (secret ✅) instead of `VI_REFRESH_TOKEN`, with
`VI_CLIENT_ID=sas.cli` (the `sas-mcp` client has no password grant). A
refresh token, when present, always wins.

Optional extras: `MCP_API_KEY` (protect `/mcp` with a static key),
`VI_CLIENT_SECRET` (confidential clients only), `VI_MAX_CHARS` (response size
cap, default 16000), `VI_TIMEOUT` (seconds, default 120), `HOST_PORT`
(default 8141), and `VI_ALERT_BASE`/`VI_DATAHUB_BASE`/`VI_SAND_BASE`/
`VI_WORKFLOW_BASE` if an ingress rewrites service paths.

## Verify before the demo

```bash
docker run --rm -p 8141:8141 \
  -e VI_ENDPOINT=https://<tunnel>.trycloudflare.com \
  -e VI_REFRESH_TOKEN=... -e VI_CLIENT_ID=sas-mcp -e VI_SSL_VERIFY=false \
  ghcr.io/raedaldweik/sas-vi-mcp:ram

curl -s localhost:8141/health
# {"status":"healthy","service":"sas-vi-mcp","vi_endpoint_configured":true,
#  "credentials_configured":true,"auth_mode":"refresh_token","client_id":"sas-mcp",...}
```

Then in RAM chat, ask the agent to run `check_vi_connection` — it reports
the grant in use, per-service reachability, and pinpoints config problems
(wrong tunnel URL, expired token, missing permissions) in plain language.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `sign-in failed (400/401) using the refresh_token grant` | The token expired or was revoked, or `VI_CLIENT_ID` is not the client it was issued to. Re-run `vi-get-refresh-token`, update `VI_REFRESH_TOKEN` (and `VI_CLIENT_ID`) in the template, restart the tool. The helper prints each token's expiry date. |
| `Could not reach SAS Logon at …` | The cloudflared quick tunnel restarted with a new URL — update `VI_ENDPOINT`. |
| Sign-in URL rejected with `invalid_client` / `unauthorized_client` for `sas-mcp` | The client is not registered on *this* Viya (VI is a different deployment from your SAS MCP's). Run `vi-register-client` once as an admin (Step 1a). |
| `SAS Logon returned no refresh token for client …` | That client lacks the `refresh_token` grant. Re-register it with `vi-register-client`, or use `--client-id sas.cli`. |
| Browser signs in but never redirects back to `localhost:8134` | SAS Logon's `form-action` Content-Security-Policy blocks localhost redirects (same fix as for the SAS Viya MCP: remove `form-action` from SAS Logon Manager's CSP for the one-time sign-in). Or avoid the redirect: `vi-get-refresh-token --code-on-page` works with a client registered by `vi-register-client` and with `sas.cli`. |
| `sas.cli` refuses the sign-in URL | That deployment's `sas.cli` has no authorization-code grant. Use the other built-in client `--client-id vscode` (Viya 2022.11+) and set `VI_CLIENT_ID=vscode`, or register `sas-mcp`. |
| `vi-register-client`: admin sign-in fails | The prompt uses the password grant, which SSO accounts cannot use. Pass `--admin-token` (a bearer token from `sas-viya auth` or the environment's Consul token). |
| `sign-in failed … using the password grant` | SSO/federated users cannot use `VI_USERNAME`/`VI_PASSWORD`; switch to a refresh token. |

## Local development

```bash
uv sync --dev
uv run pytest          # offline unit tests
uv run ruff check .
uv run app-http-direct # http://localhost:8141/mcp
```
