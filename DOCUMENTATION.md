# Student Intelligence Assistant — Project Documentation

**Internship Case Study | Tredence**  
Model: Gemini 1.5 Flash (free) · Stack: Python, Streamlit, SQLite

---

## What It Does

A web app that reads 12 structured college datasets and answers any natural-language question about students, teachers, or departments — with exact numbers, rankings, and reasoning. No hallucination. Grounded entirely in the loaded data.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                                 │
│  12 CSV Files  ──►  load_data.py  ──►  student_intelligence.db     │
│  (student_profile, results, mid/end sem, study_hours, attendance…) │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│                        ENGINE LAYER                                  │
│  data_engine.py                                                      │
│  ├─ Dumps ALL 12 tables as readable text                             │
│  └─ Pre-computes: attendance %, avg scores, mid→end improvement,    │
│     study hour totals, teacher rankings (SQL → facts)               │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│                          LLM LAYER                                   │
│  llm.py                                                              │
│  ├─ PRIMARY:  Gemini 1.5 Flash  (Google AI — free tier)             │
│  └─ FALLBACK: Groq Llama-3.3-70B (if Gemini rate-limits)           │
│  System prompt enforces: analyst reasoning, no hallucination,       │
│  full rankings, explain the WHY, exact numbers only                 │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│                           UI LAYER                                   │
│  app.py (Streamlit)                                                  │
│  ├─ Sidebar: NotebookLM-style Sources panel (live table preview)    │
│  ├─ Search bar + 4 quick-action buttons                             │
│  ├─ Answer card with citation chips (which tables were used)        │
│  └─ CSV uploader (add any new dataset on the fly)                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Datasets (12 Tables)

| # | File | What It Stores |
|---|------|----------------|
| 1 | `student_profile.csv` | Name, batch, mentor, CGPA |
| 2 | `student_results.csv` | Semester grades & scores |
| 3 | `mid_sem_marks.csv` | Mid-semester exam marks (out of 50) |
| 4 | `end_sem_marks.csv` | End-semester exam marks (out of 100) |
| 5 | `study_hours.csv` | Daily study hours per subject |
| 6 | `assignment_scores.csv` | Assignment submission scores |
| 7 | `project_performance.csv` | Project grades |
| 8 | `placement_readiness.csv` | CGPA, skills, placement status |
| 9 | `attendance.csv` | Daily P/A for students & teachers |
| 10 | `teaching_efficiency.csv` | Teacher KPIs (feedback, avg score) |
| 11 | `teacher_profile.csv` | Teacher name, department, designation |
| 12 | `department_location.csv` | Room, building, campus mapping |

---

## Requirements Satisfied

| Requirement | How |
|-------------|-----|
| Read input data files | All 12 CSVs auto-loaded into SQLite on first run |
| Apply logic from a logic file | `SYSTEM_PROMPT` in `llm.py` — 5-step analyst reasoning rules |
| Answer questions about college students | Covers grades, attendance, study habits, improvement, placement |
| Use a free model | Gemini 1.5 Flash via Google AI Studio (free tier, 1M token context) |
| NotebookLM-inspired | Same principle: full context in one window, no chunking |
| No hallucination | Pre-computed SQL summaries + strict system prompt |
| Enriched beyond given data | Added: study_hours, mid_sem_marks, end_sem_marks, placement_readiness |

---

## Why Gemini 1.5 Flash = NotebookLM

NotebookLM is Google's product — it runs on Gemini. This system uses the exact same underlying model (Gemini 1.5 Flash) via the free Google AI Studio API. The architecture mirrors NotebookLM's core idea: **load all sources into context → let the model reason over everything at once** — instead of the standard RAG approach of chunking and retrieving fragments.

---

## How to Run

```bash
# 1. Install dependencies
pip install streamlit pandas

# 2. Add your free API key to .env
echo "GEMINI_API_KEY=your_key_here" > .env

# 3. Launch
streamlit run app.py
```

Get a free Gemini API key at: https://aistudio.google.com/apikey

---

## Sample Questions the System Answers

- *"Who is the best performing student overall?"*
- *"Which teacher is most at risk of being fired and why?"*
- *"Which student improved the most from mid-sem to end-sem?"*
- *"Students with attendance below 70%"*
- *"Is there a pattern between study hours and grades?"*
