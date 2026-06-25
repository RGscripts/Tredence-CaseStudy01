"""
Data engine — NotebookLM approach.

load_all_context() dumps EVERY table as readable text so the LLM has the
complete dataset in its context window. No regex routing. No hardcoded SQL
per intent. The LLM reads everything and reasons itself.

fetch_entity_records() is kept for the structured entity-drill-down sidebar.
"""
import re
import sqlite3

from load_data import DB_PATH

ENTITY_RE = re.compile(r"\b([ST]\d{4})\b", re.IGNORECASE)

# Preferred order when presenting tables to the LLM.
_TABLE_ORDER = [
    "student_profile",
    "student_results",
    "mid_sem_marks",
    "end_sem_marks",
    "assignment_scores",
    "project_performance",
    "study_hours",
    "placement_readiness",
    "attendance",
    "teaching_efficiency",
    "teacher_profile",
    "department_location",
]


def get_conn(read_only=False):
    if read_only:
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows):
    return [dict(r) for r in rows]


def _list_tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return [r["name"] for r in rows]


def _table_columns(conn, table):
    return [r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')]


# ─────────────────────────────────────────────────────────────────────────────
# Core: load everything as text for the LLM
# ─────────────────────────────────────────────────────────────────────────────

def _build_computed_summaries(conn) -> str:
    """Pre-computes key aggregates in Python so the LLM reads facts, not raw rows.
    Prevents errors caused by the LLM miscounting P/A rows or missing joins."""
    lines = ["=== COMPUTED SUMMARIES (pre-calculated for accuracy) ==="]

    # 1. Attendance % per entity (students + teachers)
    try:
        rows = conn.execute(
            """SELECT entity_id,
                      COUNT(*) AS total_days,
                      SUM(CASE WHEN status='P' THEN 1 ELSE 0 END) AS days_present,
                      ROUND(100.0*SUM(CASE WHEN status='P' THEN 1 ELSE 0 END)/COUNT(*),1) AS attendance_pct
               FROM attendance GROUP BY entity_id ORDER BY attendance_pct ASC"""
        ).fetchall()
        if rows:
            lines.append("\n-- Attendance % per entity (sorted lowest first) --")
            lines.append("entity_id | days_present | total_days | attendance_pct")
            for r in rows:
                lines.append(f"{r['entity_id']} | {r['days_present']} | {r['total_days']} | {r['attendance_pct']}%")
    except Exception:
        pass

    # 2. Average academic score per student
    try:
        rows = conn.execute(
            """SELECT sr.student_id, sp.name,
                      ROUND(AVG(sr.score),2) AS avg_score,
                      MIN(sr.score) AS min_score, MAX(sr.score) AS max_score,
                      COUNT(*) AS courses_taken
               FROM student_results sr
               LEFT JOIN student_profile sp ON sp.student_id = sr.student_id
               GROUP BY sr.student_id ORDER BY avg_score DESC"""
        ).fetchall()
        if rows:
            lines.append("\n-- Average academic score per student (highest first) --")
            lines.append("student_id | name | avg_score | min_score | max_score | courses_taken")
            for r in rows:
                lines.append(f"{r['student_id']} | {r['name']} | {r['avg_score']} | {r['min_score']} | {r['max_score']} | {r['courses_taken']}")
    except Exception:
        pass

    # 3. Mid → End sem improvement per student
    try:
        rows = conn.execute(
            """SELECT m.student_id, sp.name,
                      ROUND(AVG(m.marks_obtained),2) AS avg_mid,
                      ROUND(AVG(e.marks_obtained),2) AS avg_end,
                      ROUND(AVG(e.marks_obtained - m.marks_obtained),2) AS avg_improvement
               FROM mid_sem_marks m
               JOIN end_sem_marks e
                 ON m.student_id=e.student_id AND m.course_code=e.course_code AND m.semester=e.semester
               LEFT JOIN student_profile sp ON sp.student_id = m.student_id
               GROUP BY m.student_id ORDER BY avg_improvement DESC"""
        ).fetchall()
        if rows:
            lines.append("\n-- Mid-sem to End-sem improvement per student (most improved first) --")
            lines.append("student_id | name | avg_mid | avg_end | avg_improvement")
            for r in rows:
                lines.append(f"{r['student_id']} | {r['name']} | {r['avg_mid']} | {r['avg_end']} | {r['avg_improvement']}")
    except Exception:
        pass

    # 4. Total study hours per student
    try:
        rows = conn.execute(
            """SELECT sh.student_id, sp.name,
                      ROUND(SUM(sh.hours_studied),1) AS total_hours,
                      ROUND(AVG(sh.hours_studied),1) AS avg_per_session
               FROM study_hours sh
               LEFT JOIN student_profile sp ON sp.student_id = sh.student_id
               GROUP BY sh.student_id ORDER BY total_hours DESC"""
        ).fetchall()
        if rows:
            lines.append("\n-- Total study hours per student (highest first) --")
            lines.append("student_id | name | total_hours | avg_per_session")
            for r in rows:
                lines.append(f"{r['student_id']} | {r['name']} | {r['total_hours']} | {r['avg_per_session']}")
    except Exception:
        pass

    # 5. Teacher performance summary
    try:
        rows = conn.execute(
            """SELECT te.teacher_id, tp.name,
                      te.avg_student_score, te.attendance_rate_pct,
                      te.student_feedback_score, te.courses_taught,
                      te.lab_sessions, te.office_hours_per_week
               FROM teaching_efficiency te
               LEFT JOIN teacher_profile tp ON tp.teacher_id = te.teacher_id
               ORDER BY te.avg_student_score DESC"""
        ).fetchall()
        if rows:
            lines.append("\n-- Teacher performance summary (best student outcomes first) --")
            lines.append("teacher_id | name | avg_student_score | attendance_rate_pct | feedback | courses | lab_sessions | office_hrs_week")
            for r in rows:
                lines.append(f"{r['teacher_id']} | {r['name']} | {r['avg_student_score']} | {r['attendance_rate_pct']}% | {r['student_feedback_score']}/5 | {r['courses_taught']} | {r['lab_sessions']} | {r['office_hours_per_week']}")
    except Exception:
        pass

    return "\n".join(lines)


def load_all_context() -> str:
    """Returns ALL data from every table as structured text, plus pre-computed
    summaries. The summaries prevent LLM errors from miscounting raw rows."""
    conn = get_conn()
    available = set(_list_tables(conn))
    order = [t for t in _TABLE_ORDER if t in available]
    order += sorted(available - set(_TABLE_ORDER))

    sections = []
    for table in order:
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        if not rows:
            continue
        cols = list(rows[0].keys())
        header = " | ".join(cols)
        body = "\n".join(
            " | ".join("" if row[c] is None else str(row[c]) for c in cols)
            for row in rows
        )
        sections.append(
            f"=== {table.upper()} ({len(rows)} rows) ===\n{header}\n{'-'*80}\n{body}"
        )

    # Append pre-computed summaries at the end so LLM can use them directly
    sections.append(_build_computed_summaries(conn))

    conn.close()
    return "\n\n".join(sections)


def get_table_summary(conn):
    """Returns list of {table, rows} for the knowledge-base overview panel."""
    result = []
    for table in _list_tables(conn):
        count = conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()["c"]
        cols = _table_columns(conn, table)
        result.append({"table": table, "columns": len(cols), "rows": count})
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Entity drill-down (sidebar browser — structured view, separate from main Q&A)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_entity_records(conn, entity_id):
    """Pull every row, across every table, that references this entity_id."""
    result = {}
    for table in _list_tables(conn):
        id_cols = [
            c for c in _table_columns(conn, table)
            if c.lower() in ("student_id", "entity_id", "teacher_id", "mentor_id")
        ]
        for col in id_cols:
            rows = conn.execute(
                f'SELECT * FROM "{table}" WHERE "{col}" = ?', (entity_id,)
            ).fetchall()
            if rows:
                result.setdefault(table, [])
                result[table].extend(_rows_to_dicts(rows))

    if "attendance" in result:
        total = len(result["attendance"])
        present = sum(1 for r in result["attendance"] if r.get("status") == "P")
        result["attendance_summary"] = {
            "present_days": present,
            "total_days": total,
            "attendance_pct": round(100.0 * present / total, 2) if total else None,
        }

    return result


def _get_student_names(conn):
    try:
        rows = conn.execute("SELECT student_id, name FROM student_profile").fetchall()
        return [(r["student_id"], r["name"]) for r in rows]
    except sqlite3.OperationalError:
        return []


def match_names(conn, question):
    """Returns (matched_ids, ambiguous_tokens) by searching student_profile names."""
    q = question.lower()
    students = _get_student_names(conn)

    matched_ids = set()
    for sid, name in students:
        if name.lower() in q:
            matched_ids.add(sid)
    if matched_ids:
        return matched_ids, []

    token_to_ids = {}
    for sid, name in students:
        for token in name.lower().split():
            if len(token) >= 4:
                token_to_ids.setdefault(token, set()).add(sid)

    q_tokens = set(re.findall(r"[a-z]{4,}", q))
    ambiguous = []
    for token in q_tokens & token_to_ids.keys():
        ids = token_to_ids[token]
        if len(ids) == 1:
            matched_ids |= ids
        else:
            ambiguous.append(token)

    return matched_ids, ambiguous


# ─────────────────────────────────────────────────────────────────────────────
# Schema relationship discovery (kept for the knowledge-base panel)
# ─────────────────────────────────────────────────────────────────────────────

def discover_relationships(conn):
    id_columns = {}
    for table in _list_tables(conn):
        for col in _table_columns(conn, table):
            norm = col.lower().replace("_", "").replace(" ", "")
            if norm.endswith("id"):
                id_columns.setdefault(norm, []).append((table, col))

    relationships = []
    for norm, entries in id_columns.items():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                table_a, col_a = entries[i]
                table_b, col_b = entries[j]
                if table_a == table_b:
                    continue
                relationships.append(
                    {"table_a": table_a, "column_a": col_a,
                     "table_b": table_b, "column_b": col_b}
                )
    return relationships
