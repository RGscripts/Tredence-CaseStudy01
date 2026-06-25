"""
Student Intelligence Assistant — NotebookLM-style.
Run: streamlit run app.py
"""
import os

import pandas as pd
import streamlit as st

import load_data
from data_engine import DB_PATH, get_conn, get_table_summary, load_all_context
from llm import NOT_FOUND_MESSAGE, NO_API_KEY_MESSAGE, narrate

if not DB_PATH.exists():
    load_data.main()

st.set_page_config(
    page_title="Student Intelligence Assistant",
    page_icon="🎓",
    layout="wide",
)

st.markdown("""
<style>
.answer-card {
    background: #1E293B;
    border: 1px solid #334155;
    border-left: 4px solid #6366F1;
    border-radius: 10px;
    padding: 24px 28px;
    font-size: 1.02rem;
    line-height: 1.8;
    color: #F1F5F9;
}
.citation-row {
    display: flex; flex-wrap: wrap; gap: 6px;
    margin-top: 14px; padding-top: 12px;
    border-top: 1px solid #334155;
}
.citation-chip {
    background: #312E81; color: #A5B4FC;
    border: 1px solid #4338CA;
    border-radius: 20px; padding: 2px 10px;
    font-size: 0.75rem; font-weight: 500;
}
</style>
""", unsafe_allow_html=True)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_context():
    if "_ctx" not in st.session_state:
        st.session_state["_ctx"] = load_all_context()
    return st.session_state["_ctx"]


def _set_q(q):
    st.session_state["_qval"] = q
    st.session_state["_trigger"] = True


def _cite_tables(answer_text, summary):
    """Return table names likely cited in this answer (keyword heuristic)."""
    keywords = {
        "student_results":     ["score", "grade", "avg", "marks", "result", "course"],
        "mid_sem_marks":       ["mid", "mid-sem", "midterm"],
        "end_sem_marks":       ["end", "end-sem", "final exam", "term end"],
        "attendance":          ["attendance", "absent", "present", "days"],
        "study_hours":         ["study", "hours", "studied"],
        "assignment_scores":   ["assignment"],
        "project_performance": ["project"],
        "placement_readiness": ["placement", "placed", "cgpa", "readiness"],
        "teaching_efficiency": ["teacher", "professor", "faculty", "feedback", "avg_student_score"],
        "teacher_profile":     ["teacher", "professor", "faculty", "dr.", "prof."],
        "student_profile":     ["student", "s100"],
        "department_location": ["department", "dept", "campus", "block"],
    }
    lower = answer_text.lower()
    cited = []
    table_names = {t["table"] for t in summary}
    for table, kws in keywords.items():
        if table in table_names and any(k in lower for k in kws):
            rows = next((t["rows"] for t in summary if t["table"] == table), 0)
            cited.append((table, rows))
    return cited


# ─── LEFT SIDEBAR — NotebookLM "Sources" panel ────────────────────────────────

with st.sidebar:
    st.markdown("## 🎓 Student Intel")
    st.caption("AI analyst for academic data")
    st.divider()

    # Sources list
    conn = get_conn()
    try:
        summary = get_table_summary(conn)
    finally:
        conn.close()

    total_records = sum(t["rows"] for t in summary)
    st.markdown(f"**📂 Sources** &nbsp; <span style='color:#94A3B8;font-size:0.8rem'>{len(summary)} datasets · {total_records} records</span>", unsafe_allow_html=True)
    st.markdown("")

    for t in summary:
        with st.expander(f"📄 {t['table']}  ({t['rows']} rows)", expanded=False):
            conn2 = get_conn()
            try:
                df = pd.read_sql_query(f'SELECT * FROM "{t["table"]}" LIMIT 50', conn2)
            finally:
                conn2.close()
            st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    # Upload
    st.markdown("**＋ Add data source**")
    uploader_version = st.session_state.get("kb_ver", 0)
    uploaded = st.file_uploader("Upload CSV", type="csv", accept_multiple_files=True, key=f"up_{uploader_version}", label_visibility="collapsed")
    if uploaded:
        sig = tuple(sorted((f.name, f.size) for f in uploaded))
        if st.session_state.get("kb_sig") != sig:
            conn3 = get_conn()
            try:
                for f in uploaded:
                    f.seek(0)
                    tname = load_data.sanitize_table_name(f.name)
                    n = load_data.ingest_csv(conn3, f, tname)
                    st.success(f"`{tname}` added ({n} rows)", icon="✅")
            finally:
                conn3.close()
            st.session_state.update({"kb_sig": sig, "_ctx": None})
            st.rerun()

    if st.button("↺ Reset to default", use_container_width=True):
        if DB_PATH.exists():
            DB_PATH.unlink()
        load_data.main()
        for k in ("kb_sig", "_ctx"):
            st.session_state.pop(k, None)
        st.session_state["kb_ver"] = uploader_version + 1
        st.rerun()

    st.divider()
    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GROQ_API_KEY"):
        st.warning("Add GEMINI_API_KEY or GROQ_API_KEY to `.env` to enable AI answers.", icon="⚠️")


# ─── MAIN AREA ────────────────────────────────────────────────────────────────

# Header
st.markdown("## Ask anything about your academic data")
st.caption("The AI reads all loaded sources and reasons over them — grounded answers, no hallucination.")

# Search bar
if "_qval" not in st.session_state:
    st.session_state["_qval"] = ""

col_input, col_btn = st.columns([8, 1])
with col_input:
    question = st.text_input(
        "question",
        value=st.session_state["_qval"],
        placeholder="e.g.  Which teacher is most likely to be fired?   |   Who improved the most?   |   Students below 70% attendance",
        label_visibility="collapsed",
    )
    st.session_state["_qval"] = question
with col_btn:
    ask_clicked = st.button("Ask →", type="primary", use_container_width=True)

# Compact quick actions — 4 most important only
st.markdown("")
c1, c2, c3, c4 = st.columns(4)
c1.button("🏆 Best Student",    key="qa1", on_click=_set_q, args=("Who is the best performing student overall?",),           use_container_width=True)
c2.button("🔥 Fire Teacher?",   key="qa2", on_click=_set_q, args=("Which teacher is most at risk of being fired and why?",), use_container_width=True)
c3.button("⚠️ At-Risk Students",key="qa3", on_click=_set_q, args=("Which students are at academic risk?",),                  use_container_width=True)
c4.button("📈 Most Improved",   key="qa4", on_click=_set_q, args=("Which student improved the most from mid-sem to end-sem?",), use_container_width=True)

st.divider()

should_run = ask_clicked or st.session_state.pop("_trigger", False)


# ─── Answer rendering ─────────────────────────────────────────────────────────

def render_answer(q):
    with st.spinner("Reading sources and reasoning…"):
        ctx = _get_context()
        answer = narrate(q, ctx)

    if not answer:
        st.info("No relevant information found in the loaded sources.")
        return
    if any(s in answer for s in ("LLM request failed", "temporarily exhausted", "rate-limited")):
        st.error("The AI service is temporarily unavailable — please wait 30 s and retry.", icon="🚫")
        return
    if answer == NOT_FOUND_MESSAGE:
        st.info("This information is not present in the loaded datasets.")
        return
    if answer.startswith(NO_API_KEY_MESSAGE):
        st.warning(answer)
        return

    # Determine cited tables (heuristic)
    conn4 = get_conn()
    try:
        summ = get_table_summary(conn4)
    finally:
        conn4.close()
    cited = _cite_tables(answer, summ)
    chips_html = "".join(
        f'<span class="citation-chip">📄 {t} &nbsp;({r} rows)</span>'
        for t, r in cited
    ) if cited else '<span class="citation-chip">📄 All sources</span>'

    answer_html = (
        answer
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace("\n\n", "<br><br>").replace("\n", "<br>")
    )

    st.markdown(
        f"""<div class="answer-card">
        {answer_html}
        <div class="citation-row">{chips_html}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_empty():
    st.markdown("#### 💡 Try these questions")
    examples = [
        ("🎓", "Student Performance",  ["Who is the best performing student overall?", "CGPA ranking of all students", "Which student studies the most hours?", "Who improved most from mid to end sem?"]),
        ("👩‍🏫", "Teacher & Department", ["Which teacher is most likely to be fired?", "Who is the best teacher?", "Compare all departments by average score", "Which course has the lowest average score?"]),
        ("🔍", "Deep Analysis",        ["Students with attendance below 70%", "Who scored above 85 in any subject?", "Is there a pattern between study hours and grades?", "How did S1001 perform in Sem1 vs Sem2?"]),
    ]
    cols = st.columns(3)
    for col, (icon, label, qs) in zip(cols, examples):
        with col:
            st.markdown(f"**{icon} {label}**")
            for ex in qs:
                if st.button(ex, key=f"ex_{ex}", use_container_width=True):
                    _set_q(ex)
                    st.rerun()


if should_run and question.strip():
    render_answer(question)
elif should_run:
    st.info("Please type a question first.")
else:
    render_empty()
