# RAM Assets — system prompts + RAG documents for every MCP

One folder per MCP tool registered in SAS Retrieval Agent Manager. Each
folder contains:

| File | Where it goes in RAM |
|---|---|
| `system_prompt.md` | **Agents → your agent → Instructions** (the agent's system prompt) |
| `retrieval_prompt.md` | **Retrieval Settings → prompt** — keep the `{context}` placeholder; set Top K 4–6 |
| `rag-pdfs/*.pdf` | Upload to a **Collection** attached to the agent (this is the RAG — RAM requires a collection per agent) |

## Wiring an agent (same flow for all five)

1. **Sources / Collections**: create a collection named after the MCP (e.g.
   `sas-vi-context`) and upload the PDFs from `rag-pdfs/`.
2. **Agents**: create the agent, attach the collection **and** the matching
   MCP tool (Code Templates → Tools).
3. Paste `system_prompt.md` into the agent instructions.
4. Paste `retrieval_prompt.md` into Retrieval Settings (it keeps `{context}`).

## The five MCPs

| Folder | MCP tool in RAM | Container image |
|---|---|---|
| `SAS VI MCP` | SAS_VI_MCP (this repo) | `ghcr.io/raedaldweik/sas-vi-mcp:latest`, port 8141 |
| `SAS Viya MCP` | SAS_MCP | `ghcr.io/raedaldweik/sas-mcp-server:ram`, port 8134 |
| `SAS Use Case MCP` | use-case-scoped SAS MCP | `ghcr.io/raedaldweik/sas_use_case` image, port 8134 |
| `TomTom Maps MCP` | TomTom maps/traffic | tomtom mcp image |
| `Web Search MCP` | Tavily news & web | `ghcr.io/raedaldweik/web_search:latest`, port 8140 |
