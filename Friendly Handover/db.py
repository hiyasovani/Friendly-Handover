import sqlite3
import hashlib
import os
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "employee_handover.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash

def init_db():
    conn = get_connection()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('employee', 'authority')),
        department TEXT,
        designation TEXT,
        is_active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        department TEXT,
        description TEXT
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        owner_employee_id TEXT,
        details TEXT,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS handover_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id INTEGER NOT NULL,
        outgoing_employee_id TEXT NOT NULL,
        project_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        created_at TEXT NOT NULL,
        approved_by INTEGER,
        approved_at TEXT,
        share_tasks INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(requester_id) REFERENCES users(id),
        FOREIGN KEY(project_id) REFERENCES projects(id),
        FOREIGN KEY(approved_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        owner_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        file_type TEXT NOT NULL,
        extracted_text TEXT,
        is_handover_paper INTEGER NOT NULL DEFAULT 0,
        approved INTEGER NOT NULL DEFAULT 0,
        uploaded_at TEXT NOT NULL,
        FOREIGN KEY(request_id) REFERENCES handover_requests(id),
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL UNIQUE,
        report_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(request_id) REFERENCES handover_requests(id)
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(actor_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS request_integrations (
        request_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        selected INTEGER NOT NULL DEFAULT 0,
        confirmed INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(request_id, provider),
        FOREIGN KEY(request_id) REFERENCES handover_requests(id)
    );
    CREATE TABLE IF NOT EXISTS project_memory (
        request_id INTEGER PRIMARY KEY,
        memory_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(request_id) REFERENCES handover_requests(id)
    );
    CREATE TABLE IF NOT EXISTS ai_analysis_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        analysis_json TEXT NOT NULL,
        retrieval_method TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(request_id) REFERENCES handover_requests(id)
    );
    CREATE TABLE IF NOT EXISTS human_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        field_name TEXT NOT NULL,
        original_value TEXT,
        corrected_value TEXT NOT NULL,
        corrected_by INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(request_id) REFERENCES handover_requests(id),
        FOREIGN KEY(corrected_by) REFERENCES users(id)
    );
    """)
    conn.commit()
    seed_demo_data(conn)
    conn.close()

def seed_demo_data(conn=None):
    close_after = conn is None
    if conn is None:
        conn = get_connection()

    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count == 0:
        users = [
            ("AUTH-001", "Authority Admin", "admin123", "authority", "Administration", "Authority Admin"),
            ("EMP-123", "123", "user123", "employee", "Product & Operations", "Incoming Employee"),
            ("EMP-001", "Emp_1", "emp123", "employee", "Product & Operations", "Senior Product Designer"),
            ("EMP-002", "Emp_2", "emp123", "employee", "Product & Operations", "Engineering Manager"),
            ("EMP-003", "Emp_3", "emp123", "employee", "Product & Operations", "Growth Marketing Lead"),
            ("EMP-004", "Emp_4", "emp123", "employee", "Product & Operations", "Finance Analyst"),
        ]
        for employee_id, name, password, role, department, designation in users:
            conn.execute(
                """INSERT INTO users
                (employee_id, name, password_hash, role, department, designation)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (employee_id, name, hash_password(password), role, department, designation)
            )

        conn.execute(
            "INSERT INTO projects (name, department, description) VALUES (?, ?, ?)",
            ("Product & Operations Branch", "Product & Operations",
             "Ongoing branch work, client handovers, weekly reporting and project roadmap.")
        )
        project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()[0]
        sample_tasks = [
            ("Review active client handovers", "Pending", "EMP-001",
             "Review the open client handover items and confirm the next owner."),
            ("Continue weekly reporting cadence", "Pending", "EMP-001",
             "Prepare and circulate the weekly progress report."),
            ("Maintain the project roadmap", "In Progress", "EMP-001",
             "Keep milestones, dependencies and delivery dates updated."),
            ("Coordinate with branch team members", "Completed", "EMP-001",
             "Coordinate updates and follow-ups with the branch team."),
        ]
        for title, status, owner, details in sample_tasks:
            conn.execute(
                """INSERT INTO tasks (project_id, title, status, owner_employee_id, details)
                VALUES (?, ?, ?, ?, ?)""",
                (project_id, title, status, owner, details)
            )
        conn.commit()

    if close_after:
        conn.close()

def log_action(actor_id, action, details=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO audit_logs (actor_id, action, details, created_at) VALUES (?, ?, ?, ?)",
        (actor_id, action, details, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()

def get_user_by_login(employee_id, name, password, role):
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM users
        WHERE employee_id = ? AND lower(name) = lower(?) AND role = ? AND is_active = 1""",
        (employee_id.strip(), name.strip(), role)
    ).fetchone()
    conn.close()
    if row and verify_password(password, row["password_hash"]):
        return dict(row)
    return None

def get_user_by_id(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_employees():
    conn = get_connection()
    rows = conn.execute(
        "SELECT employee_id, name, department, designation FROM users WHERE role='employee' AND is_active=1 ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_projects():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_tasks(project_id, owner_employee_id=None):
    conn = get_connection()
    if owner_employee_id:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id=? AND owner_employee_id=? ORDER BY id",
            (project_id, owner_employee_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id=? ORDER BY id", (project_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_request(requester_id, outgoing_employee_id, project_id):
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO handover_requests
        (requester_id, outgoing_employee_id, project_id, status, created_at)
        VALUES (?, ?, ?, 'Pending', ?)""",
        (requester_id, outgoing_employee_id, project_id,
         datetime.now().isoformat(timespec="seconds"))
    )
    request_id = cur.lastrowid
    conn.commit()
    conn.close()
    return request_id

def add_document(request_id, owner_id, filename, stored_path, file_type,
                 extracted_text, is_handover_paper=False):
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO documents
        (request_id, owner_id, filename, stored_path, file_type, extracted_text,
         is_handover_paper, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (request_id, owner_id, filename, stored_path, file_type, extracted_text,
         int(is_handover_paper), datetime.now().isoformat(timespec="seconds"))
    )
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    return doc_id

def get_requests_for_employee(user_id):
    conn = get_connection()
    rows = conn.execute(
        """SELECT r.*, p.name AS project_name, u.name AS outgoing_name
        FROM handover_requests r
        JOIN projects p ON p.id=r.project_id
        JOIN users u ON u.employee_id=r.outgoing_employee_id
        WHERE r.requester_id=? ORDER BY r.id DESC""",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_requests():
    conn = get_connection()
    rows = conn.execute(
        """SELECT r.*, p.name AS project_name, u.name AS requester_name,
        u.employee_id AS requester_employee_id
        FROM handover_requests r
        JOIN projects p ON p.id=r.project_id
        JOIN users u ON u.id=r.requester_id
        ORDER BY r.id DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_request(request_id):
    conn = get_connection()
    row = conn.execute(
        """SELECT r.*, p.name AS project_name, u.name AS requester_name,
        u.employee_id AS requester_employee_id
        FROM handover_requests r
        JOIN projects p ON p.id=r.project_id
        JOIN users u ON u.id=r.requester_id
        WHERE r.id=?""", (request_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def get_documents(request_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM documents WHERE request_id=? ORDER BY id", (request_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def approve_request(request_id, authority_id, approved_document_ids, share_tasks=True):
    conn = get_connection()
    docs = conn.execute(
        "SELECT id FROM documents WHERE request_id=?", (request_id,)
    ).fetchall()
    allowed_ids = {r["id"] for r in docs}
    chosen_ids = set(approved_document_ids) & allowed_ids
    conn.execute("UPDATE documents SET approved=0 WHERE request_id=?", (request_id,))
    for doc_id in chosen_ids:
        conn.execute("UPDATE documents SET approved=1 WHERE id=? AND request_id=?",
                     (doc_id, request_id))
    conn.execute(
        """UPDATE handover_requests
        SET status='Approved', approved_by=?, approved_at=?, share_tasks=?
        WHERE id=?""",
        (authority_id, datetime.now().isoformat(timespec="seconds"),
         int(share_tasks), request_id)
    )
    conn.commit()
    conn.close()

def reject_request(request_id, authority_id):
    conn = get_connection()
    conn.execute(
        "UPDATE handover_requests SET status='Rejected', approved_by=?, approved_at=? WHERE id=?",
        (authority_id, datetime.now().isoformat(timespec="seconds"), request_id)
    )
    conn.commit()
    conn.close()

def save_report(request_id, report_text):
    conn = get_connection()
    conn.execute(
        """INSERT INTO reports (request_id, report_text, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(request_id) DO UPDATE SET
        report_text=excluded.report_text, created_at=excluded.created_at""",
        (request_id, report_text, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()

def get_report(request_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM reports WHERE request_id=?", (request_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_approved_documents(request_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM documents WHERE request_id=? AND approved=1 ORDER BY id",
        (request_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_request_integrations(request_id, providers, confirmed=False):
    conn = get_connection()
    conn.execute("DELETE FROM request_integrations WHERE request_id=?", (request_id,))
    chosen = list(providers) or ["__none__"]
    for provider in chosen:
        conn.execute(
            "INSERT INTO request_integrations (request_id, provider, selected, confirmed) VALUES (?, ?, 1, ?)",
            (request_id, provider, int(confirmed))
        )
    conn.commit()
    conn.close()

def get_request_integrations(request_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT provider FROM request_integrations WHERE request_id=? AND selected=1 AND provider!='__none__' ORDER BY provider",
        (request_id,)
    ).fetchall()
    conn.close()
    return [r["provider"] for r in rows]

def mark_request_integrations_confirmed(request_id):
    conn = get_connection()
    conn.execute("UPDATE request_integrations SET confirmed=1 WHERE request_id=?", (request_id,))
    conn.commit()
    conn.close()


def save_project_memory(request_id, memory_json):
    """Persist the latest structured AI reconstruction for this handover request."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO project_memory (request_id, memory_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(request_id) DO UPDATE SET
        memory_json=excluded.memory_json, updated_at=excluded.updated_at""",
        (request_id, memory_json, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()


def get_project_memory(request_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM project_memory WHERE request_id=?", (request_id,)).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    try:
        result["memory"] = json.loads(result.pop("memory_json"))
    except (TypeError, ValueError):
        result["memory"] = None
    return result


def save_analysis_history(request_id, analysis, retrieval_method=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO ai_analysis_history (request_id, analysis_json, retrieval_method, created_at) VALUES (?, ?, ?, ?)",
        (request_id, json.dumps(analysis, ensure_ascii=False, default=str), retrieval_method,
         datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()


def get_analysis_history(request_id, limit=10):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM ai_analysis_history WHERE request_id=? ORDER BY id DESC LIMIT ?",
        (request_id, int(limit))
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_human_correction(request_id, field_name, original_value, corrected_value, corrected_by=None):
    """Store a review correction separately; original source/evidence is never overwritten."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO human_corrections
        (request_id, field_name, original_value, corrected_value, corrected_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (request_id, field_name, original_value, corrected_value, corrected_by,
         datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()


def get_human_corrections(request_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM human_corrections WHERE request_id=? ORDER BY id",
        (request_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
