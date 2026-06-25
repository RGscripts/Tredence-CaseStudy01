"""Loads CSV data into SQLite -- both the bundled data/ files on startup and
ad-hoc uploads (e.g. a Streamlit UploadedFile) added later by the user."""
import csv
import io
import re
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = Path(__file__).parent / "student_intelligence.db"


def infer_type(values):
    sample = [v for v in values if v not in ("", None)][:10]
    if not sample:
        return "TEXT"
    try:
        for v in sample:
            int(v)
        return "INTEGER"
    except ValueError:
        pass
    try:
        for v in sample:
            float(v)
        return "REAL"
    except ValueError:
        return "TEXT"


def sanitize_table_name(filename):
    """Turns an arbitrary uploaded filename into a safe SQLite table identifier."""
    stem = Path(filename).stem
    name = re.sub(r"[^0-9a-zA-Z_]", "_", stem).strip("_")
    if name and name[0].isdigit():
        name = f"t_{name}"
    return name or "uploaded_table"


def _read_csv_rows(source):
    """Reads CSV rows from either a filesystem path or a file-like object
    (e.g. a Streamlit UploadedFile, which exposes .read() like a file)."""
    if isinstance(source, (str, Path)):
        with open(source, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = [r for r in reader if r]
        return header, rows

    raw = source.read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    rows = [r for r in reader if r]
    return header, rows


def ingest_csv(conn, source, table_name):
    """Loads one CSV (path or file-like) into SQLite as `table_name`, inferring
    column types from the data. Returns the number of rows loaded."""
    header, rows = _read_csv_rows(source)
    columns = [c.strip() for c in header]
    col_values = list(zip(*rows)) if rows else [[]] * len(columns)
    types = [infer_type(vals) for vals in col_values] if rows else ["TEXT"] * len(columns)

    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    col_defs = ", ".join(f'"{c}" {t}' for c, t in zip(columns, types))
    cur.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

    placeholders = ", ".join("?" for _ in columns)
    cur.executemany(f'INSERT INTO "{table_name}" VALUES ({placeholders})', rows)
    conn.commit()
    return len(rows)


def dataset_overview(conn):
    """Knowledge Base panel data: every table's columns + row count, plus
    conservatively-detected relationships between tables (see data_engine.discover_relationships)."""
    from data_engine import _list_tables, _table_columns, discover_relationships

    tables = {}
    for table in _list_tables(conn):
        columns = _table_columns(conn, table)
        row_count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        tables[table] = {"columns": columns, "row_count": row_count}

    return {"tables": tables, "relationships": discover_relationships(conn)}


def main():
    csv_files = sorted(DATA_DIR.glob("*.csv"))
    if not csv_files:
        raise SystemExit(f"No CSV files found in {DATA_DIR}")

    conn = sqlite3.connect(DB_PATH)
    for csv_path in csv_files:
        n = ingest_csv(conn, csv_path, csv_path.stem)
        print(f"Loaded {n} rows into '{csv_path.stem}'")
    conn.close()
    print(f"\nDatabase ready at {DB_PATH}")


if __name__ == "__main__":
    main()
