# RAG Chat – on-premise AI

A ChatGPT-style chat application that answers questions from **your own documents, Excel sheets and
SQL Server databases**. Everything runs on your own machine: the language model, the embeddings, the
vector database and the data. No cloud API is used and no data leaves the computer.

- Answers from documents always carry citations (file, page, section).
- Number questions are answered by running real SQL, and the result is shown as a table and a chart.
- Every user signs in, and roles decide which folders, spreadsheets and databases they can use.
  Row rules can limit a user to their own region, country and so on.
- An evaluation suite measures the answer quality, so a change that makes answers worse is caught.

![Answer from a database with a chart](docs/images/sql-chart.png)

---

## Screenshots

| Answer from a document, with citation | Row-level permission (user sees only the East region) |
|---|---|
| ![Document answer](docs/images/document-answer.png) | ![Row-level filter](docs/images/row-level-filter.png) |

| Spreadsheet answer in dark mode | Admin – users and their attributes |
|---|---|
| ![Spreadsheet in dark mode](docs/images/spreadsheet-dark.png) | ![Admin users](docs/images/admin-users.png) |

| Admin – roles | Admin – row rules |
|---|---|
| ![Admin roles](docs/images/admin-roles.png) | ![Admin row rules](docs/images/admin-rules.png) |

---

## Overall architecture

```mermaid
flowchart TB
    U(["👤 User<br/>in the browser"]):::user

    subgraph FE["🖥️ Frontend · Angular 16 · port 4200"]
        UI["💬 Chat page<br/>tables · charts · admin pages"]:::fe
    end

    subgraph BE["⚙️ Backend · FastAPI · port 8000"]
        API["🔐 Login and permissions<br/>checked on every request"]:::be
        AG["🤖 Agent<br/>decides which tool to use"]:::be
        GD["🛡️ SQL guard<br/>read-only · row rules"]:::guard
    end

    subgraph AI["🧠 Ollama · local AI · port 11434"]
        LLM["qwen3:14b<br/>chat model"]:::ai
        EMB["nomic-embed-text<br/>embedding model"]:::ai
    end

    subgraph SRC["📚 Your data"]
        DOC[("📄 Documents<br/>PDF · Word · images<br/>searched with Qdrant")]:::data
        XLS[("📊 Spreadsheets<br/>Excel · CSV<br/>queried with DuckDB")]:::data
        DB[("🗄️ Databases<br/>Northwind · pubs<br/>SQL Server")]:::data
    end

    subgraph APP["🔑 App data"]
        ACC[("👥 Users · roles · audit<br/>RagChatApp")]:::app
        CH[("🕘 Saved chats<br/>SQLite")]:::app
    end

    U --> UI
    UI -- "question" --> API
    API --> AG
    AG <-- "prompt and tool calls" --> LLM
    AG -- "search" --> DOC
    DOC -. "embeddings" .- EMB
    AG -- "SQL" --> GD
    GD --> XLS
    GD --> DB
    API --> ACC
    API --> CH

    classDef user  fill:#fde68a,stroke:#b45309,stroke-width:2px,color:#111
    classDef fe    fill:#bfdbfe,stroke:#1d4ed8,stroke-width:2px,color:#111
    classDef be    fill:#c7d2fe,stroke:#4338ca,stroke-width:2px,color:#111
    classDef guard fill:#fecaca,stroke:#b91c1c,stroke-width:2px,color:#111
    classDef ai    fill:#e9d5ff,stroke:#7e22ce,stroke-width:2px,color:#111
    classDef data  fill:#bbf7d0,stroke:#15803d,stroke-width:2px,color:#111
    classDef app   fill:#fed7aa,stroke:#c2410c,stroke-width:2px,color:#111

    style FE  fill:#3b82f61a,stroke:#3b82f6,stroke-width:2px
    style BE  fill:#6366f11a,stroke:#6366f1,stroke-width:2px
    style AI  fill:#a855f71a,stroke:#a855f7,stroke-width:2px
    style SRC fill:#22c55e1a,stroke:#22c55e,stroke-width:2px
    style APP fill:#f973161a,stroke:#f97316,stroke-width:2px
```

**In simple words**

1. The user types a question in the **Angular** chat page.
2. The **backend** checks who the user is and what they are allowed to see.
3. The **agent** sends the question to the local **qwen3** model, which decides what it needs:
   a document search, a spreadsheet query or a database query.
4. Document questions are searched in **Qdrant** (the embedding model turns text into vectors).
   Number questions become SQL, which passes the **SQL guard** (read-only, row rules) before it runs.
5. The results go back to the model, it writes the answer with citations, and the answer streams to the
   browser with tables and charts.
6. Users, roles and the audit log are kept in **RagChatApp** (SQL Server); saved chats in **SQLite**.

**How one question is answered**

```mermaid
sequenceDiagram
    actor U as User
    participant A as Angular
    participant F as FastAPI agent
    participant M as Ollama (qwen3 14b)
    participant T as Tools (Qdrant / DuckDB / SQL Server)

    U->>A: "Top 5 customers by revenue in 1997?"
    A->>F: POST /api/chat (history + question)
    F->>F: check the user's access, build the prompt<br/>(only sources this user may use)
    F->>M: prompt + tools
    M-->>F: tool call: get_schema(northwind)
    F->>T: read schema (as chat_reader)
    T-->>F: tables and columns
    F->>M: schema
    M-->>F: tool call: run_sql(SELECT ...)
    F->>F: SQL guard + row-level rewrite
    F->>T: run query (timeout, row limit)
    T-->>F: rows
    F-->>A: table event (shown as table + chart)
    F->>M: rows
    M-->>F: answer tokens
    F-->>A: tokens stream (NDJSON), then sources
    A-->>U: answer with chart and citations
```

---

## Models used

| Purpose | Model | Size | Notes |
|---|---|---|---|
| Chat, tool calling, SQL writing | `qwen3:14b` (Ollama) | 9.3 GB | Thinking mode is off (`THINK=false`): about 7 times faster and reliable for tool calls. Context window 16,384 tokens. |
| Embeddings for document search | `nomic-embed-text` (Ollama) | 274 MB | Uses the `search_document:` / `search_query:` prefixes. |
| Keyword search | BM25 (sparse vectors in Qdrant) | – | Finds rare exact words like "Repos". |
| OCR for scanned pages and images | RapidOCR (ONNX Runtime) | comes with the pip package | Runs offline. |
| Answer checking in the evaluation | `qwen3:14b` as judge | – | `temperature=0`, JSON output. |

Tested on a laptop with an RTX 5090 (24 GB VRAM) and 64 GB RAM. A GPU with about 12 GB VRAM can run
`qwen3:14b`; with less memory, a smaller model such as `qwen3:8b` can be set in `.env` (`CHAT_MODEL=...`).

---

## Tech stack

| Layer | Used |
|---|---|
| Frontend | Angular 16 (NgModules), marked + DOMPurify (safe Markdown), Chart.js |
| Backend | Python 3.12, FastAPI, uvicorn, pydantic-settings |
| LLM runtime | Ollama |
| Vector search | Qdrant (local mode), hybrid search: dense + BM25 + identifiers, merged with RRF |
| Spreadsheets | pandas + DuckDB (in memory, sandboxed) |
| Databases | SQL Server with Windows authentication, pyodbc, ODBC Driver 18 |
| SQL safety | sqlglot (only one SELECT on known tables, row-level rewrite) |
| Documents | PyMuPDF (PDF), python-docx (Word), Word COM via pywin32 (old `.doc`), RapidOCR |
| Accounts | SQL Server database `RagChatApp`, bcrypt, server-side sessions |
| Tests | pytest, ruff |

---

## Setup

The commands are for **Windows (PowerShell)**, because the app uses Windows authentication for SQL Server
and Word for old `.doc` files.

### 1. Install the requirements

| Tool | Version used |
|---|---|
| Python | 3.12 |
| Node.js + Angular CLI | Node 18 or later, `npm install -g @angular/cli@16` |
| Ollama | latest, from ollama.com |
| SQL Server | 2019 or later (Developer or Express edition) with Windows authentication |
| ODBC Driver 18 for SQL Server | from Microsoft |
| Microsoft Word | optional, only needed for old `.doc` files |

### 2. Download the models

```bash
ollama pull qwen3:14b
```

```bash
ollama pull nomic-embed-text
```

### 3. Prepare SQL Server

Import the Microsoft sample databases **Northwind** (`instnwnd.sql`) and **pubs** (`instpubs.sql`).
Use `-f 65001` so that accented names are read as UTF-8:

```bash
sqlcmd -S localhost -E -f 65001 -i instnwnd.sql
```

```bash
sqlcmd -S localhost -E -f 65001 -i instpubs.sql
```

Then run the two scripts of this project. Both are safe to run again.

```bash
sqlcmd -S localhost -E -i db-scripts\create_chat_reader.sql
```

```bash
sqlcmd -S localhost -E -i db-scripts\create_app_database.sql
```

- `create_chat_reader.sql` creates `chat_reader` in Northwind and pubs: a user without login that can only read.
  All SQL written by the model runs as this user.
- `create_app_database.sql` creates the `RagChatApp` database (users, roles, row rules, sessions, audit log)
  and the `chat_app` user that the app uses for it.

### 4. Backend

```bash
cd backend
```

```bash
py -3.12 -m venv .venv
```

```bash
.\.venv\Scripts\pip install -r requirements-dev.txt
```

Settings have defaults in `backend/app/config.py`. To change any of them, create `backend/.env`, for example:

```ini
CHAT_MODEL=qwen3:14b
EMBED_MODEL=nomic-embed-text
THINK=false
SQL_SERVER=localhost
```

Create your admin account (it asks for the password):

```bash
.\.venv\Scripts\python -m app.auth.cli create-admin your-name
```

Start the backend:

```bash
.\.venv\Scripts\python -m uvicorn app.main:app --reload --reload-dir app --port 8000
```

Check http://localhost:8000/api/health – it shows whether Ollama and the chat model are ready.

### 5. Frontend

```bash
cd frontend
```

```bash
npm install
```

```bash
npm start
```

Open http://localhost:4200 and sign in with the admin account.

### 6. Index the documents

Documents must be indexed once, and again after files change (only changed files are processed).
Sign in to the app as admin first, then open http://localhost:8000/docs, choose
`POST /api/documents/index` and click **Try it out → Execute**. The same browser session cookie is used.

---

## Adding your own data

| Data | Where to put it |
|---|---|
| PDF, Word (`.docx`, `.doc`), images (`.png`, `.jpg`) | `data/docs/`. Sub-folders work as permission folders, for example `data/docs/hr/` is visible only to roles with the `hr` folder. Run the indexing again after adding files. |
| Excel and CSV (`.xlsx`, `.xls`, `.csv`) | `data/docs/`. Each sheet becomes a SQL table. Changes are picked up automatically. |
| SQL Server databases | Add an entry to `backend/databases.json` (name, database, description, notes such as formulas), and create `chat_reader` in that database (add it to `db-scripts/create_chat_reader.sql`). |

Users, roles, user attributes and row rules are managed on the **Admin** page.

---

## Security in short

- The model's SQL runs as read-only users (`chat_reader` in SQL Server; DuckDB without file or network access),
  and must pass the SQL guard: only one SELECT, only known tables, timeout and row limit.
- Row rules rewrite each query so a user sees only their rows. Rules follow foreign keys
  (a rule on Customers also limits Orders and Order Details). A user without the attribute sees no rows.
- Every endpoint and every tool checks the user's permissions again. Document search is filtered to the
  allowed files.
- Sessions use an HttpOnly, SameSite=Strict cookie; only a hash of the token is stored. Passwords use
  bcrypt, and accounts are locked after 5 wrong passwords in 15 minutes.
- The model's answer is cleaned with DOMPurify before it is shown (protection against prompt injection
  writing HTML).
- The audit log can only be added to; UPDATE and DELETE are denied in the database.

---

## Tests

From the `backend` folder:

```bash
.\.venv\Scripts\python -m pytest
```

Runs the fast unit and integration tests (about 30 seconds).

```bash
.\.venv\Scripts\python -m pytest -m eval
```

Runs the evaluation against the running app (about 2 minutes; backend, Ollama and SQL Server must be
running, and test accounts are created with `python -m app.auth.cli seed-test-users`). It checks:

| Area | What is measured |
|---|---|
| retrieval | the right file and page in the top 3 (recall@3, MRR) |
| sql | the model's result contains the rows of a reference query |
| documents | facts present, right passage cited, "not found" when the answer is not in the documents |
| judge | the local model checks every statement is supported by the passages |
| security | users get only what their role and row rules allow |

The report is written to `backend/tests/eval/reports/latest.md`, with the change since the last full run.

---

## Project structure

```
backend/
  app/
    agent.py          tool-calling loop, prompts, citations
    tools/            search_documents, query_tables, get_schema, run_sql
    ingest/           loaders (PDF, Word, OCR), chunker, embeddings, Qdrant store, indexer
    tables/           Excel/CSV -> DuckDB
    databases/        SQL Server connections, schema cache, queries
    sql_guard.py      read-only SQL check
    row_filter.py     row-level rewrite
    auth/             accounts, sessions, roles, CLI
    routers/          REST endpoints
  databases.json      databases the model may use, with notes
  tests/              fast tests, and tests/eval for the evaluation
frontend/src/app/
  chat/               chat page, sidebar, result cards, charts
  auth/               sign-in and change-password pages, guards, interceptor
  admin/              users, roles, row rules, audit log
db-scripts/           SQL Server setup scripts
data/docs/            sample documents and spreadsheet
docs/NOTES.md         what I learned in each step of building this
```

---

## Learning notes

This project was built step by step as a learning exercise. The reasons behind each decision and the
problems I faced are written in [docs/NOTES.md](docs/NOTES.md).
