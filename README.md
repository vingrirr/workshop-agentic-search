# Workshop: Agentic Search for Context Engineering

This workshop discusses different agentic search techniques for context engineering.

![](/img/Agentic%20Search%20for%20Context%20Engineering.png)

**Learning outcomes:** By the end of this workshop you will have
- experimented with a few different ways to search for context across different context sources
- learned how you can expand the capabilities of search tools with Agent Skills and additional CLIs
- gained an intuition on the trade-offs for different search tools

## Two ways to run this

- **Standalone Python project (recommended)** — the code under `src/` + `scripts/`.
  No agent framework and no Elasticsearch: a small, transparent agent loop you can
  step through in the VS Code debugger, backed by **PostgreSQL (+ pgvector)**. This
  is what the rest of this README covers.
- **Original Jupyter notebooks** — under `notebooks/` (LangChain + Elasticsearch).
  See [Running the original notebooks](#running-the-original-notebooks).

## What the standalone project looks like

```
src/agentic_search/
  agent.py              # the transparent agent loop (tool calling) — the core
  llm.py                # OpenAI-compatible chat client (requests) — replaces ChatOpenAI
  embeddings.py         # Jina embeddings client + cosine similarity
  dataset.py            # session record -> Document / markdown  (rewrite this for new data)
  tools.py              # the 3 search tools (semantic / SQL query / shell)
  skills.py             # progressive-disclosure Agent Skills (replaces middleware)
  build.py              # assembles each technique into (system_prompt, tools)
  config.py             # env + paths
  datasource/
    base.py             # SearchBackend interface  (the swappable seam)
    postgres_backend.py # PostgreSQL + pgvector reference backend
    filesystem.py       # exports one .txt per session (for the shell technique)
scripts/                # one debuggable entry point per technique
prompts/                # system prompts
data/sessions.json      # source data (AI Engineer Europe 2026 schedule)
```

**Runtime dependencies are just `requests`, `python-dotenv`, and `psycopg`** — everything
else (subprocess, csv, json) is the Python standard library.

> 📐 New to the code? See **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** for a full code
> map, the agent-loop diagram, an end-to-end trace, and a debugging guide.

## Set up

### 1. Create a virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt      # or: pip install -e .
```

### 2. Start PostgreSQL with pgvector

You need a PostgreSQL database and the [`pgvector`](https://github.com/pgvector/pgvector)
extension (pgvector is only needed for semantic search — plain SQL search works without it).

**Easiest — Docker Compose** (ships pgvector, persists data in a named volume):

```bash
docker compose up -d
```

Then use this in your `.env` (next step):

```
DATABASE_URL='postgresql://workshop:workshop@localhost:5432/workshop'
```

`docker compose down` stops it (data kept); `docker compose down -v` also deletes the data.

**Already have Postgres** (local, or on another machine — use its host/IP in the URL)?
Point `DATABASE_URL` at it and enable the extension once; `prepare_data.py` also runs
`CREATE EXTENSION IF NOT EXISTS vector` for you on first index:

```bash
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

> For SQL-only (no semantic search) you don't need pgvector at all — use any Postgres and
> index with `python scripts/prepare_data.py --no-embeddings`.

### 3. Environment variables and API keys

Copy `.env.example` to `.env` and fill it in:

- **LLM** (`LITELLM_API_BASE`, `LITELLM_API_KEY`) — any OpenAI-compatible endpoint.
  These notebooks use OpenAI models through a LiteLLM gateway; any tool-calling model works.
- **PostgreSQL** (`DATABASE_URL`) — e.g. `postgresql://user:password@localhost:5432/workshop`.
- **Jina** (`JINA_API_KEY`) — for semantic search embeddings. Free key (no registration) from
  the [Jina page](https://jina.ai/api-dashboard/embedding).

### 4. Prepare the data

The examples are based on the AI Engineer Europe Conference schedule in
`data/sessions.json` (downloaded from https://www.ai.engineer/europe/schedule).

```bash
python scripts/prepare_data.py                  # index into Postgres (+ embeddings) and export files
python scripts/prepare_data.py --no-embeddings  # index without pgvector (heuristic SQL search only)
```

This (1) indexes one row per session into the `conference_schedule` table and (2) exports
one markdown file per session under `data/session_data/` (used by the shell technique).

## Run the techniques

Each technique is a script you can run directly — or launch under the debugger (see below).

```bash
python scripts/run_vanilla_search.py -q "Which sessions cover agent memory?"
python scripts/run_db_query.py       -q "How many sessions are on April 8th?"
python scripts/run_shell_search.py   -q "Are there any sessions about GEPA?"
python scripts/run_shell_search.py --jina -q "sessions on regulatory constraints"
```

## Debugging in VS Code

`.vscode/launch.json` ships a debug configuration for each technique. Open the
**Run and Debug** panel, pick e.g. *"02 - DB query tool + skill"*, and press **F5**.
Set a breakpoint in `src/agentic_search/agent.py` (`run_agent`) to watch every tool
call, or in `datasource/postgres_backend.py` to watch the SQL / vector queries.

`.vscode/settings.json` points the editor at `.venv` and adds `src/` to the analysis path.

## Course outline

| **Topic** | **Context source** | **Retrieval tool** | **Script** |
| --- | --- | --- | --- |
| Vanilla Agentic Search | PostgreSQL (pgvector) | Semantic search tool | [run_vanilla_search.py](./scripts/run_vanilla_search.py) |
| Agentic Search with DB query tool | PostgreSQL | SQL query tool (+ Agent Skills) | [run_db_query.py](./scripts/run_db_query.py) |
| Agentic Search with Shell tool | Local filesystem | Shell tool (+ `jina-grep`) | [run_shell_search.py](./scripts/run_shell_search.py) |

> The shell tool runs arbitrary shell commands with no sandboxing (like the notebook's
> `ShellTool`). Only use it in an environment you're comfortable giving an LLM shell access to.

## Changing the underlying datasource

The project is built so you can swap the data and the store independently:

- **Different data** (e.g. a different domain): rewrite `src/agentic_search/dataset.py`
  (`load_records`, `record_to_document`, `record_to_markdown`) and update the table/column
  descriptions in `prompts/system_prompt_db.md`.
- **Different store**: subclass `SearchBackend` in `src/agentic_search/datasource/base.py`
  and implement `index_documents` / `execute_query` / `semantic_search` / `query_skill`.
  `PostgresBackend` is the reference. Nothing in `tools.py`, `agent.py`, or `build.py` needs
  to change — they depend only on the interface.

For a store that is "mostly heuristic search", you can rely on `execute_query` (SQL) alone
and index with `--no-embeddings` until you decide what to embed for vector search.

## Running the original notebooks

The original LangChain + Elasticsearch notebooks are still under `notebooks/`.

```bash
pip install -r requirements-notebooks.txt   # langchain, langchain-elasticsearch, jupyter, ...
```

Those notebooks use a local Elasticsearch instance; the easiest way to run one locally is
the `start-local` script: `curl -fsSL https://elastic.co/start-local | sh`.

# Additional Resources
- [pgvector](https://github.com/pgvector/pgvector)
- [The shell tool is not a silver bullet for context engineering](https://www.elastic.co/search-labs/blog/search-tools-context-engineering)
- [Building effective database retrieval tools for context engineering](https://www.elastic.co/search-labs/blog/database-retrieval-tools-context-engineering)
- [Elastic Agent Skills](https://github.com/elastic/agent-skills/tree/main)
- [`jina-grep` CLI](https://github.com/jina-ai/jina-grep-cli)
