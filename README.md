# Student Intelligence Assistant

A NotebookLM-style ecosystem for student/teacher/department data: load the bundled dataset
or upload your own structured CSVs, then ask anything -- exact lookups, rankings, or open-ended
questions nobody pre-coded for. Every answer is grounded in real rows from your data; nothing
is invented, and the app tells you exactly which rows (and, for novel questions, which SQL
query) produced the answer.

## Architecture: deterministic fast path + LLM planner fallback

```
CSV files (data/ or uploaded)  -->  SQLite (one table per file)
                                            |
                                            v
                              data_engine.retrieve()  (deterministic, exact, CANONICAL)
                                  entity/name lookup, known analytics patterns
                                            |
                                   matched? --- yes --> llm.ask_llm()  --> answer
                                            |
                                            no
                                            v
                              data_engine.run_planner()  (LLM plans + writes SQL)
                                  plan -> validate -> execute (read-only) -> narrate
                                            |
                                            v
                                         answer
```

- **SQLite is the single source of truth.** Every CSV (bundled or uploaded) becomes its own table.
- **`data_engine.retrieve()`** is the trusted fast path: it recognizes student/teacher IDs (e.g.
  `S1001`, `T2001`), names, and a fixed set of analytics phrasings (best student, low attendance,
  department comparison, teacher ranking, placement readiness, list students, department-scoped
  averages, etc.) and runs exact, hand-written SQL for them. **It is canonical whenever it
  matches** -- the LLM planner never runs for a question the fast path already answered, so the
  two engines can never disagree on a number.
- **`data_engine.run_planner()`** is the fallback, invoked only when `retrieve()` finds nothing.
  It sends the live database schema (tables, columns, sample rows, auto-detected relationships)
  to the LLM, which either (a) writes one safe, read-only SQL query, (b) refuses an off-topic /
  adversarial question, or (c) reports that the loaded data is insufficient to answer. Generated
  SQL is validated (single `SELECT`/`WITH` statement only, no
  `INSERT/UPDATE/DELETE/DROP/ALTER/...`) and then executed on a **physically read-only** SQLite
  connection (`mode=ro`) -- a write attempt fails at the database level even if validation were
  somehow bypassed. On a SQL error the failure is fed back to the planner and retried (up to 2
  times) before giving up gracefully.
- **`llm.py`** owns every LLM call (`call_groq`): it never invents data, since the model only ever
  sees the rows `retrieve()` or the planner's SQL actually returned. If nothing relevant was
  found, the LLM isn't called at all -- the fixed response
  `"I could not find this information in the provided datasets."` is returned directly. This
  makes the no-hallucination guarantee structural, not just a prompt instruction.
- Default model is `llama-3.3-70b-versatile` for accuracy (the smaller `llama-3.1-8b-instant` has
  been observed to drop rows from multi-row analytics answers). If 70b's free-tier quota is
  exhausted, requests automatically retry once against `llama-3.1-8b-instant`. Identical requests
  are cached in-process so repeat testing doesn't burn quota twice. Override either model via the
  `GROQ_MODEL` / `GROQ_FALLBACK_MODEL` env vars.

## Knowledge Base / uploading your own data

The app works with **structured CSV datasets**: it automatically discovers tables, columns, and
candidate relationships (shared ID-like columns, e.g. `student_id` / `studentID` both detected).
Questions are answered when the loaded tables contain enough information; otherwise the app says
so explicitly (e.g. "the scores dataset isn't loaded") instead of guessing.

In the app, open **"📚 Knowledge Base"** to:
- See every currently loaded table, its column count, and row count.
- See how many relationships were auto-detected between tables.
- **Upload more CSVs** -- each becomes a new table, askable immediately, merged into the same
  database the rest of the app queries.
- **Reset to original dataset** -- drops all uploaded tables and reloads only the bundled
  `data/*.csv` files.

Relationship detection is deliberately conservative (exact, normalized ID-column matches only --
no fuzzy/similarity guessing), because a wrong auto-join would silently produce a confident wrong
number, which is worse than not joining at all.

## Datasets

`student_results`, `attendance`, `department_location`, and `teaching_efficiency` are the original
files provided. `student_profile`, `study_hours`, `mid_sem_marks`, `end_sem_marks`,
`assignment_scores`, `project_performance`, and `placement_readiness` are **synthetic demo data**
generated to fill out the remaining categories in the spec, kept numerically consistent with the
original files (e.g. each student's mid-sem + end-sem marks sum to their final `student_results`
score). Replace any of these CSVs with real data at any time -- just re-run `load_data.py`, or
upload them through the Knowledge Base panel.

## Setup

1. Get a free API key at https://console.groq.com/keys
2. Set it as an environment variable:
   - PowerShell: `$env:GROQ_API_KEY = "your_key_here"`
   - bash: `export GROQ_API_KEY=your_key_here`
3. Install the one dependency (Streamlit, for the UI):
   ```
   pip install -r requirements.txt
   ```
4. Load the data into SQLite:
   ```
   python load_data.py
   ```
5. Run the app:
   - **Web UI (recommended):** `streamlit run app.py` -- opens a browser tab with a question box,
     a Knowledge Base panel (upload your own CSVs here), example-question buttons, and an
     expandable "Execution plan + SQL + evidence used" / "Retrieved Records" panel for each answer
     so it's clear nothing was made up.
   - **CLI (no browser):** `python main.py`

If `GROQ_API_KEY` is not set, both the UI and the CLI still run end-to-end and show the retrieved
context/setup instructions instead of crashing, so retrieval can be demoed/tested without a key.

The SQLite database is a build artifact (not committed) -- `app.py` rebuilds it automatically from
`data/*.csv` on first run if it's missing, so a fresh clone or Streamlit Cloud deploy works with no
manual step.

## Deploying on Streamlit Community Cloud

1. Push this repo to GitHub (already done if you're reading this from there).
2. On https://share.streamlit.io, create a new app pointing at this repo, branch `main`, file `app.py`.
3. In the app's **Settings > Secrets**, add:
   ```
   GROQ_API_KEY = "your_free_groq_api_key_here"
   ```
4. Deploy. The database is built automatically on first run; no other setup is needed.

## Example questions

Exact lookups and known analytics (deterministic, instant, always correct):
- `Tell me about student S1001`
- `What is S1002's attendance?`
- `Who is the best performing student?`
- `Show me students with low attendance`
- `Compare departments`
- `Rank the teachers by performance`
- `What is the placement readiness of S1005?`
- `List all students`
- `What is the average attendance in the Computer Science department?`

Open-ended questions (answered by planning a SQL query on the fly -- you'll see the query used):
- `Which student improved the most from mid-sem to end-sem?`
- `Is there a relationship between study hours and final scores?`
- Anything about a CSV you upload yourself.

Safety / adversarial (both correctly refuse instead of guessing or executing):
- `What's the capital of France?` -- off-topic, returns the not-found message.
- `Drop the student table.` / `Delete all attendance records.` -- refused by the planner, and
  blocked again at the database level even if it weren't.
