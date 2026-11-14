# My notes

What I learned while building this project, step by step. Written mainly for my own reference later.

---

## Step 0 – Setup

**Virtual environment (venv)**
A venv is a separate Python installation for one project. Whatever I install with `pip install` goes
into `backend\.venv` and not into the global Python. So this project can have its own package versions
and they will not clash with my other projects. In .NET, it is similar to each project having its own
NuGet packages. If the venv gets corrupted, I can delete `.venv` and create it again from
`requirements.txt`.

I used Python 3.12 and not 3.15, because 3.15 is very new and some packages are not yet available for it.

**.gitignore**
It keeps unwanted files out of git: the venv, `node_modules`, caches, and later the databases, the vector
index and anything that has passwords. Once a file is pushed to GitHub, it stays in the history even if I
delete it later. So it is better to ignore such files from the beginning.
I decided to commit `data/docs`, so the sample files come along with the repo.

**Ports**
| Port  | What runs there |
|-------|-----------------|
| 4200  | Angular dev server (`ng serve`) |
| 8000  | FastAPI backend (uvicorn) |
| 11434 | Ollama |
| 1433  | SQL Server |

**Problems I faced**
- `ng new` creates its own git repo. I had to skip that because the root folder already has one.
- Northwind was imported with wrong accented letters (`MÃ©xico`). Reason: the script is in UTF-8, but
  sqlcmd read it with the old Windows codepage. I ran it again with `-f 65001` and it was fixed. This
  kind of broken text (mojibake) comes when bytes are read with the wrong encoding.
- In PowerShell, `curl` is not the real curl. It is `Invoke-WebRequest`. Use `curl.exe` or
  `Invoke-RestMethod` instead.
- `ConvertTo-Json` goes only 2 levels deep by default. For nested data, use `-Depth 5`.

---

## Step 1 – FastAPI skeleton

**uvicorn and FastAPI**
FastAPI is the framework. It gives routes, validation and the `/docs` page. It does not listen on a port
by itself. uvicorn is the server that accepts the HTTP connections and passes them to the app (ASGI).
So uvicorn is like Kestrel, and FastAPI is like ASP.NET Core.

**Order of settings (pydantic-settings)**
1. Environment variable
2. `.env` file
3. Default value in `config.py`

The first one found is used. So `THINK=true` in `.env` overrides `think: bool = False` in the code.
Note: with `extra="ignore"`, a spelling mistake in `.env` (like `CHAT_MODLE`) is ignored without any error.

**CORS**
CORS is a browser rule, not a server firewall. The browser asks the server whether this origin is
allowed, and if not, it stops the JavaScript from reading the response. PowerShell and curl do not
check CORS at all; they simply send the request. So CORS protects the user's browser from other websites
calling my API with the user's cookies. It is not real access control.

**Mistakes I made**
- `cors_origins` was a `str` instead of `list[str]`. Because of this, the check became a substring check,
  and `http://localhost:42` was also allowed. Changing it to `list[str]` fixed it.
- Relative paths like `../data` and `.env` depended on the folder from where I started uvicorn. I fixed
  it with `Path(__file__).resolve().parents[N]`, so paths are always relative to `config.py`.
- Port 8000 was still being used by the old project, so for some time I was testing the wrong app.
  Always check the title on `/docs` first.

---

## Step 2 – Streaming chat

**Why errors are sent as an event and not as a 500**
In streaming, the 200 status and the headers are sent before the first token. After that, I cannot
change the status to 500. So if something fails in the middle, the stream itself has to tell the client:
`{"type": "error", "message": "..."}`. Only errors that happen before streaming starts (like validation,
422) get a normal HTTP error.

**Why the client cannot send `system` messages**
The system prompt contains the server's rules. If the browser could send `role: system`, anyone could
send "ignore all previous instructions…". This is called prompt injection. So the schema allows only
`user` and `assistant`, and the server adds its own system prompt.

**NDJSON and SSE**
- NDJSON: one JSON object per line. Simple, and it works with a normal POST and fetch.
- SSE (Server-Sent Events): `data: ...` lines, with `EventSource` built into the browser, but
  EventSource supports only GET.
Both are better than waiting for the full answer, because the user can start reading after about 1 second
instead of waiting 6 seconds or more.

**Thinking mode**
With `think=true`, one short answer had 213 thinking events and only 20 actual tokens. It is much
slower, so I keep it off by default.

---

## Step 3 – Angular chat page

**Why fetch and not HttpClient**
HttpClient gives the body only when it is complete. fetch gives `response.body` as a stream, which I can
read piece by piece with `getReader()`. I wrapped it in an Observable so it still works like normal
Angular code.

**Line buffer and `{ stream: true }`**
Network chunks do not match my JSON lines. One chunk can have half a line or three lines. So I add the
data to a buffer, split it on `\n`, parse the complete lines, and keep the last incomplete part for the
next chunk.
`TextDecoder.decode(value, { stream: true })` solves the same problem for characters: `é` is 2 bytes,
and the two bytes can come in different chunks. Without this option, you get `�`.

**How the Stop button stops the model**
`unsubscribe()` → Observable teardown → `controller.abort()` → browser closes the connection →
uvicorn cancels my `events()` generator → `stream_chat` stops → the HTTP stream to Ollama is closed →
Ollama stops generating. One click, and the GPU is free.

**Other points**
- Use `forRoot` only once in the app. Feature modules use `forChild`.
- A lazy module should not also be imported in AppModule. Otherwise it goes into the main bundle.
- Each module imports what its own templates need (FormsModule in ChatModule, not in AppModule).
- Scroll to the bottom in `ngAfterViewChecked`, not immediately after adding text, because the DOM is
  not updated yet at that time.
- Do not send the empty assistant placeholder in the history. The backend returns 422, because the last
  message must be from the user.

**Pending items**
- Remove the user's question from the history when its answer failed (right now it stays).
- Remove the empty bubble if I press Stop before any text comes.

---

## Step 4 – Loading and chunking documents

**Why we need chunks**
An embedding converts a whole text into one vector. If a full 25-page PDF becomes one vector, it is a
mixture of everything, so it does not match any question properly. Around 1200 characters (about 300
tokens) is small enough to be about one topic and big enough to make sense on its own. Also, the model
can read only a limited amount of context, so I want to give it the 5 best pieces, not 5 full files.

**Overlap**
Neighbouring chunks share about 200 characters. If a sentence falls exactly at a cut, it would be split
into two and neither chunk would have the full sentence. With overlap, it is complete in at least one
chunk.
- Overlap 0 → sentences at the edges are lost.
- Overlap almost equal to the chunk size → the text hardly moves forward, and there are many near-duplicates.
That is why I kept the overlap below half of the chunk size.

**Where to cut**
The best boundary near the limit, in this order: paragraph → line → sentence → comma → space. I look only
in the second half of the window. Otherwise a paragraph break at character 40 would create a very small
chunk of 40 characters.

**Why every chunk has source, page and heading**
For citations later ("iso27001.pdf, page 11"), for folder permissions (`hr/...`), and so that re-indexing
can replace the chunks of exactly one file. Page numbers start from 1, like in the PDF viewer (PyMuPDF
starts from 0). A chunk never spans two pages, so the page number is always exact.

**Removing headers and footers**
Earlier, lines like the ISO copyright footer came in almost every chunk, so every search result had this
extra text. Now I compare the first and last 3 lines of each page, with digits replaced (so `Page 3`
and `Page 17` are treated as the same), and remove the lines that appear on at least half of the pages.
After this, the most repeated line in the PDF was "Control", which is real table content, so it is fine.

**Problems I faced**
- PyMuPDF `sort=True` mixed up the column order. The default order works better for this PDF.
- `doc.paragraphs` in python-docx skips tables. Use `iter_inner_content()` instead.
- Word COM: use `DispatchEx` (a separate Word instance, not my open one), always call `Quit()` in
  `finally`, and cache the converted .docx. Conversion takes 3.4 seconds; from the cache it takes 0.0 seconds.
- `~$file.docx` is a Word lock file. Skip it.
- Always use `encoding="utf-8"` when writing files on Windows.
- `--only` overwrote chunks.jsonl with a partial file. That was my mistake.
- The table of contents page (dotted lines like "6.2 ...........4") has every clause title, so it matches
  many questions without answering any of them. This is still pending.

**pytest compared with xUnit**
Plain `assert`; `@pytest.mark.parametrize` is like `[Theory]`; `pytest.raises` is like `Assert.Throws`.
`pytest.ini` must be in `backend/`, not in `tests/`. I found this only after it failed.

---

## Step 5 – Embeddings and Qdrant hybrid search

**Dense and sparse search**
- Dense (nomic embeddings) = meaning. "How much holiday do I get?" finds the "Annual leave" chunk even
  though the word "holiday" is not in it.
- Sparse (BM25) = exact words. In "Azure Repos versus GitHub", rare words like "Repos" get high weight.
- Identifiers = codes like `6.2` or `A.5.15`. The other two methods are not good at these: the tokenizer
  splits "6.2" into "6" and "2", and embeddings do not give much importance to numbers.
Each method finds results that the others miss, so I run all three and combine them.

**nomic prefixes**
Documents get the prefix `search_document: ` and questions get `search_query: `. The model was trained on
(question, passage) pairs marked like this, so the question comes close to the passages that answer it.
Without the prefixes, the scores are clearly worse.

**RRF (Reciprocal Rank Fusion)**
`score = Σ weight / (60 + rank)` over all the lists in which a chunk appears. Weights: dense 1, BM25 1,
identifier 3 (if someone types "A.5.15", they want exactly that).
Why not simply add the scores: cosine is between 0 and 1, but BM25 has no upper limit, so they cannot be
compared directly. RRF looks only at the ranks, so the combination is fair.
For the same reason, I cannot put a threshold on the RRF score (about 0.016–0.08). It does not say how
relevant a chunk is, only how high it was ranked. So the cutoff uses the dense cosine score.

**min_score**
Dense search always returns k results, even for unrelated questions. "What is the capital of France?"
scored 0.55 against my documents. Real matches were between 0.6 and 0.9, so the cutoff is 0.6. This value
was measured, not guessed, and I must check it again when the documents change.
Exception: a chunk whose title line is the clause that was asked for. (A.5.15 on page 18 had cosine 0.597,
just below the cutoff, but it is the correct answer.)

**Identifier problem**
In the PDF, the control is written as `5.15 Access control`. The `A` is in a separate table column. So
the question had `A.5.15` and the text had `5.15`, and they did not match. Fix: store both forms
(`identifier_keys`). PDFs also do not have headings, so I detect clause titles as lines that start with
a number followed by a word in capital letters.

**Incremental indexing**
The SHA-256 of every file is stored along with its chunks. On the next run: same hash → skip; different
hash → delete the old chunks and add the new ones; file removed → delete its chunks. The second run takes
0.0 seconds instead of about 5 seconds.
Point IDs are `uuid5("iso27001.pdf#29")`, so the same chunk always gets the same ID. Adding it again
overwrites it instead of creating a duplicate.

**Problems I faced**
- Qdrant local mode allows only one process per folder. That is why indexing runs inside the backend
  (`POST /api/documents/index`) and not from a separate script while the backend is running.
- Python's `hash()` gives different values on every run, so I use `zlib.crc32` for BM25 term numbers.
  I fixed the expected values in a test.
- Endpoints that call blocking code must be `def`, not `async def`. Otherwise they block the whole server.
- If the collection config changes (for example, adding BM25), delete `data/qdrant` and index again.

**Results**
All my test questions found the correct file and page at rank 1, and unrelated questions return nothing.
Still weak: "And what about clause 6.2?" ranks Annex A 6.2 (page 20) above clause 6.2 (page 11). The
question alone is not clear enough; it needs the chat history (step 6).

**Commits**
I split step 5 into 4 commits, and each one works on its own (embeddings → store → indexer → endpoints).
GitHub Desktop can commit selected lines of a file. I used that for config.py.

**Fix done after this: Annex A numbers**
"clause 6.3" was matching Annex A control 6.3, which is a different thing. Now every page after the
"Annex A" title stores its numbers as `A.6.3`, so `6.3` means only the clause. This also fixed "What
are the objectives?", because the table of contents no longer comes first.

---

## Step 6 – The agent (tool calling and citations)

**What tool calling means**
I do not search first and then ask the model. I give the model a list of tools (name, description and
parameters), and the model decides, for example, "I want `search_documents` with query X". My code runs
the tool, sends the result back as a `tool` message, and the model either asks for another tool or writes
the answer. There are at most 4 rounds, and the last round has no tools, so the model has to answer.

**Citations**
Every passage gets a number: `[1]`, `[2]` and so on. The prompt says "cite every fact like [1]". After the
answer, I check which numbers it actually used and send only those as sources. Numbers that the model
made up are dropped.
Old `[n]` markers are removed from the chat history. Otherwise the model copies them into new answers.

**Points to remember**
- The tool call can come in any chunk of the stream, not only the last one, so collect all of them.
- The model's own tool request must be added to the history before the tool results; otherwise the model
  loses track.
- `think=False` works well for tool calls and is about 7 times faster.
- Scanned PDF pages and images have no text, so they are read with OCR (RapidOCR). It runs offline, and
  the models come with the pip package.

---

## Step 7 – Spreadsheets as SQL tables (DuckDB)

**Why SQL and not embeddings for Excel**
Embeddings are for meaning. "Total sales in 2020" is a calculation over thousands of rows, and a search
cannot add numbers. So each sheet becomes a table in DuckDB (in memory), and the model writes SQL.

**Keeping it safe**
The model writes the SQL, so I treat it like user input:
- `sql_guard` (sqlglot) allows only ONE plain SELECT on known tables. No INSERT or DROP, no `INTO`, and
  no file functions like `read_csv('C:\...')`.
- DuckDB itself has file and network access turned off, its configuration locked, a 10-second timeout
  and a limit of 50 rows.
So there are two separate checks. If one has a gap, the other still protects.

**Problems I faced**
- The Excel file had a "Grand Total" row, so every SUM was exactly double. The loader now removes total rows.
- Rows are order lines, not orders. "How many orders" needs `COUNT(DISTINCT order_id)`, not `COUNT(*)`.
  The model did this correctly only after I added it to the prompt with an example.
- When a query fails, the error is sent back to the model along with the schema, so it can correct it.
- The model answered document questions from its own knowledge ("Compare Azure Repos with GitHub" is a
  topic it already knows). Fix: a quick search with the question before the model starts, and the prompt
  says "related passages are in Azure.docx, use search_documents". Giving the file name worked; rules
  alone did not.

---

## Step 8 – SQL Server databases (Northwind and pubs)

**Read-only user without a login**
On my machine, SQL Server uses only Windows authentication and I am sysadmin. That is far too much
permission for SQL written by a model. So every connection runs
`EXECUTE AS USER = 'chat_reader' WITH NO REVERT`. `chat_reader` has no login and only `db_datareader`.
`NO REVERT` means the connection cannot switch back. Connection pooling is turned off, so a connection
with reduced permissions is never reused for anything else.

**Tools: get_schema, then run_sql**
The model must check the schema first and use only those tables and columns. If it still uses a wrong
column, the error comes back with the real schema attached.

**Prompt rules that made a real difference**
- T-SQL: `TOP 5`, not `LIMIT 5`, and square brackets for `[Order Details]`.
- Show names, not IDs (join to the table that has the name).
- For "top N" with joins: rank on the IDs first in a CTE, then join the names. If you join first, rows
  get multiplied and the totals become too big (join fan-out).
- `databases.json` has notes like the revenue formula (`UnitPrice * Quantity * (1 - Discount)`). This is
  a small "semantic layer", so the model does not have to guess.
- If both the spreadsheet and a database can answer, the model asks which one I mean.

---

## Step 9 – ChatGPT-style UI

**Showing Markdown safely**
The model's text cannot be trusted. A prompt injection inside a document could make it write `<script>`
or `<img onerror>`. So the flow is: `marked` (Markdown to HTML) → `DOMPurify` (removes the dangerous
parts) → only then display it. `[1]` becomes a clickable citation, and links open in a new tab with
`noopener`.

**Result cards**
SQL results are shown as a table with a chart: a bar chart if there are labels and numbers, a line chart
if the labels are dates, and no chart otherwise. Chart.js runs outside NgZone (otherwise every animation
frame triggers change detection) and is destroyed along with the component. Options: sort, CSV (with BOM,
so Excel shows accented letters correctly), PNG and copy.

**Saved chats**
Conversations are saved after each answer (`/api/conversations`). Sidebar groups: Today, Previous 7 days,
Older. Rename, delete, regenerate, dark mode using CSS variables, and on mobile the sidebar opens with
a menu button.

**Follow-up questions**
For "And for 2019?", the model added up numbers from earlier answers instead of running a new query.
Rules in the system prompt did not help. A short reminder added to the latest user message ("look this
up with a tool, don't reuse numbers") fixed it in 3 out of 3 runs. Only the copy sent to the model has
this reminder; the user never sees it.

---

## Step 10 – Login, permissions and the admin page

**Sessions, not JWT**
Login gives a random token in an HttpOnly, SameSite=Strict cookie. JavaScript cannot read it (so XSS
cannot steal it), and other sites cannot send it (protection against CSRF). The database stores only the
SHA-256 of the token, so even if someone reads the table, they cannot log in with it. Passwords are
hashed with bcrypt.
After 5 wrong passwords in 15 minutes, the account is locked. Temporary passwords must be changed at
first login.

**Roles**
A role gives access to document folders (`hr`), spreadsheets and databases. Every endpoint AND every
agent tool checks the user's `Access` again. Hiding a button in the UI is not security.
Qdrant gets a filter on the allowed files, so passages from other files are never returned.

**What I did not expect**
At first, I removed the tools that a user was not allowed to use. Then the model simply made up an
answer ("Total sales were $1.2M"). Now every user gets every tool, and a tool they are not allowed to use
returns "no access", so the model tells the truth. Also, the common prompt does not name any database;
otherwise users would come to know that it exists.

**Angular side**
Guards for: signed in, admin, and must change password. An interceptor sends the cookie
(`withCredentials`) and handles 401 and 403. The chat `fetch` needs `credentials: 'include'`.
Admin pages (lazy loaded at `/admin`): users, roles with access chosen from the real folders, tables and
databases, and the audit log.

**Test accounts**
`python -m app.auth.cli seed-test-users`. The passwords are in `data/test-accounts.local.json`, which is
ignored by git. Never paste them anywhere.

---

## Step 11 – Row-level permissions

**Accounts moved to SQL Server**
Users, roles, sessions and the audit log moved from SQLite to a `RagChatApp` database. The app runs as
`chat_app`, which can only read and write rows. The audit log can only be added to: UPDATE and DELETE are
denied, so nobody (not even a bug in my code) can change old entries. Tests use a separate
`RagChatAppTest` database.

**How row rules work**
A rule says: table `Customers`, column `Country` must match the user's attribute `country`. When
test-sales (country = Germany) runs `SELECT * FROM Customers`, I rewrite it with sqlglot to
`SELECT * FROM (SELECT * FROM Customers WHERE Country IN ('Germany')) AS Customers`.
The name stays the same, so joins, subqueries, CTEs and UNIONs continue to work, but they see only the
filtered rows.

**Filtering through foreign keys**
A rule on Customers must also filter Orders and Order Details. Otherwise "total of all orders" would show
everyone's data. So child tables are filtered through their foreign keys:
Customers → Orders → Order Details.

**Rules I decided on**
- No attribute means no rows. When in doubt, show nothing.
- Admins are never filtered.
- Row counts and sample values of filtered tables are hidden from the schema, because they can reveal totals.
- The UI shows a "filtered" badge on results, so the user knows they are not seeing all the data.
- 25 attack cases (comments, nested subqueries, aliases, UNION tricks, etc.) are all blocked.

---

## Step 13 – Evaluation suite

**Why**
Unit tests check my code. They cannot tell me whether the ANSWERS became worse after I change a prompt,
the chunk size or the model. So I keep a fixed set of questions with known correct answers and run them
against the real app.

**Two kinds of tests**
- `pytest` → only the fast tests (156 tests, about 30 seconds). `pytest.ini` has `-m "not eval"`.
- `pytest -m eval` → the evaluation (45 cases, about 2 minutes). The backend, Ollama and SQL Server must
  be running. If the backend is down, all cases are skipped, not failed.

**How each area is checked**
- Retrieval: the correct file and page must be in the top 3. Measured as recall@3 and MRR (1 for rank 1,
  ½ for rank 2, and so on).
- SQL: I do not compare the model's SQL text, because the same query can be written in many ways. I run
  my own reference query and check that its rows are present in the model's result. Numbers can differ
  by at most 0.01.
- Documents: the facts must be in the answer, the correct passage must be cited, and for things not in
  the documents, the answer must say it could not find them.
- Judge: the local model reads the passages and checks that every statement in the answer is supported
  (LLM-as-judge, `temperature=0`, JSON output).
- Security: test-sales cannot see HR files, sees only East and Germany rows, and sees no French
  customers; test-hr gets no spreadsheets and no databases.

**Known issues**
A case with `known_issue: ...` in the YAML runs as xfail. It is shown in the report but does not reduce
the score. If it starts passing, the report lists it under "Known issues that now pass", and then I
remove the label.

**Report**
`tests/eval/reports/latest.md` and `history.jsonl`. The Change column compares with the last FULL run.
Runs with `-k`, a single file or a single area are marked PARTIAL and are never used for comparison. My
first version compared with a run of just one test, and the numbers were meaningless.

**Proof that it works**
I turned off the search hint on purpose. The documents score dropped to 88% (-12 points), and the Azure
question was answered from the model's own knowledge. After turning it back on, the score was 100% again.
So the suite really catches regressions.

**Problems I faced**
- A `?` inside an unquoted YAML value broke the parsing. Put strings with special characters in quotes.
- The model returned the first name and last name in two separate columns. Now the checker also compares
  the row's text joined together. The answer was correct; the checker was too strict.
- PowerShell 5.1 breaks the quotes in `git commit -m`. Write the message to a file and use `-F`.
