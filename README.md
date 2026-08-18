# MCP Servers — SAS Retrieval Agent Manager toolkit

Everything needed to run the MCP fleet in SAS Retrieval Agent Manager (RAM).

## What's here

### [`SAS VI MCP/`](SAS%20VI%20MCP/)
The **SAS Visual Investigator MCP server** — alert triage, entity
investigation, free-text search, network (link) analysis, and investigation
workflows, grounded in the official VI 2026.04 OpenAPI specs (included in
`SAS VI MCP/api-specs/`). Ships as a container:

```
ghcr.io/raedaldweik/sas-vi-mcp:latest      (HTTP · port 8141 · base path /mcp)
```

Built and pushed automatically by
[`.github/workflows/publish-sas-vi-mcp.yml`](.github/workflows/publish-sas-vi-mcp.yml).
See the folder's README for the full RAM registration recipe, environment
variables, and the cloudflared tunnel setup for RACE-hosted VI.

### [`RAM Assets/`](RAM%20Assets/)
Per-MCP agent kits for RAM — one folder for each MCP tool:

- `system_prompt.md` — paste into the agent's Instructions
- `retrieval_prompt.md` — paste into Retrieval Settings (keeps `{context}`)
- `rag-pdfs/` — small knowledge-base PDFs to upload into the agent's
  collection (RAM requires a RAG collection per agent)

Covered MCPs: **SAS VI**, **SAS Viya** (official `sas-mcp-server`),
**TomTom Maps**, **Web Search** (Tavily), **SAS Use Case** (scoped Viya).

## The full RAM fleet

| MCP tool | Image | Port | Base path |
|---|---|---|---|
| SAS Viya (official) | `ghcr.io/raedaldweik/sas-mcp-server:ram` | 8134 | `/mcp` |
| SAS Visual Investigator | `ghcr.io/raedaldweik/sas-vi-mcp:latest` | 8141 | `/mcp` |
| Web Search (Tavily) | `ghcr.io/raedaldweik/web_search:latest` | 8140 | `/mcp` |
| TomTom Maps | tomtom mcp image | — | `/mcp` |
| SAS Use Case (scoped) | sas_use_case image | 8134 | `/mcp` |
