import os
import sqlite3
from datetime import datetime, timedelta

import bcrypt

import config

os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
os.makedirs(config.UPLOAD_DIR, exist_ok=True)


def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('teacher', 'student'))
        );

        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            teacher_id INTEGER NOT NULL REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS class_enrollments (
            class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (class_id, student_id)
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('past_paper', 'worksheet', 'practice')),
            due_date TEXT,
            total_marks INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'published')),
            question_paper_path TEXT,
            mark_scheme_path TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            topic TEXT NOT NULL,
            question_text TEXT NOT NULL DEFAULT '',
            max_marks INTEGER NOT NULL,
            mark_scheme_text TEXT NOT NULL DEFAULT '',
            page_number INTEGER DEFAULT 1,
            order_index INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            file_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'grading', 'review', 'final')),
            uploaded_at TEXT NOT NULL,
            UNIQUE(assignment_id, student_id)
        );

        CREATE TABLE IF NOT EXISTS grade_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            ai_mark REAL,
            ai_confidence REAL,
            ai_notes TEXT,
            final_mark REAL,
            teacher_comment TEXT,
            risk_flags TEXT NOT NULL DEFAULT '',
            needs_exception_review INTEGER NOT NULL DEFAULT 0,
            auto_finalized_at TEXT,
            auto_finalize_reason TEXT,
            teacher_override_mark REAL,
            teacher_override_comment TEXT,
            teacher_override_at TEXT,
            teacher_override_by INTEGER REFERENCES users(id),
            UNIQUE(submission_id, question_id)
        );

        CREATE TABLE IF NOT EXISTS ocr_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            provider TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '',
            confidence REAL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'done', 'failed', 'skipped')),
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(submission_id, page_number, provider)
        );

        CREATE TABLE IF NOT EXISTS practice_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            label TEXT NOT NULL,
            text TEXT NOT NULL,
            source TEXT DEFAULT 'seed'
        );
        """
    )
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(questions)").fetchall()
    }
    if "question_text" not in columns:
        conn.execute(
            "ALTER TABLE questions ADD COLUMN question_text TEXT NOT NULL DEFAULT ''"
        )

    grade_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(grade_drafts)").fetchall()
    }
    grade_column_defs = {
        "risk_flags": "TEXT NOT NULL DEFAULT ''",
        "needs_exception_review": "INTEGER NOT NULL DEFAULT 0",
        "auto_finalized_at": "TEXT",
        "auto_finalize_reason": "TEXT",
        "teacher_override_mark": "REAL",
        "teacher_override_comment": "TEXT",
        "teacher_override_at": "TEXT",
        "teacher_override_by": "INTEGER REFERENCES users(id)",
    }
    for column, definition in grade_column_defs.items():
        if column not in grade_columns:
            conn.execute(
                f"ALTER TABLE grade_drafts ADD COLUMN {column} {definition}"
            )
    question_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(questions)").fetchall()
    }
    question_column_defs = {
        "syllabus_code": "TEXT",
        "subtopic": "TEXT",
        "paper_component": "TEXT",
        "calculator_allowed": "INTEGER",
        "source_paper": "TEXT",
        "source_year": "INTEGER",
        "question_number": "TEXT",
        "assessment_objective": "TEXT",
        "difficulty_teacher": "TEXT",
        "question_type_tag": "TEXT",
        "mark_structure": "TEXT",
        "requires_method_marks": "INTEGER",
        "answer_only_eligible": "INTEGER",
    }
    for column, definition in question_column_defs.items():
        if column not in question_columns:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {column} {definition}")
    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def seed_if_empty():
    conn = connect()
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count > 0:
        conn.close()
        return

    teacher_hash = hash_password("teacher123")
    student_hash = hash_password("student123")

    conn.execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
        ("teacher@school.edu", teacher_hash, "Ms. Chen", "teacher"),
    )
    conn.execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
        ("student@school.edu", student_hash, "Alex Student", "student"),
    )
    conn.execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
        ("student2@school.edu", student_hash, "Jamie Lee", "student"),
    )

    teacher_id = conn.execute(
        "SELECT id FROM users WHERE email = 'teacher@school.edu'"
    ).fetchone()["id"]
    student_id = conn.execute(
        "SELECT id FROM users WHERE email = 'student@school.edu'"
    ).fetchone()["id"]
    student2_id = conn.execute(
        "SELECT id FROM users WHERE email = 'student2@school.edu'"
    ).fetchone()["id"]

    conn.execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        ("0580 Extended - Set A", teacher_id),
    )
    class_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student_id),
    )
    conn.execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student2_id),
    )

    due = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    conn.execute(
        """
        INSERT INTO assignments (class_id, title, type, due_date, total_marks, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            class_id,
            "Mock Paper 2 - Algebra & Number",
            "past_paper",
            due,
            20,
            "published",
            datetime.now().isoformat(),
        ),
    )
    assignment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    sample_questions = [
        ("Q1a", "Number", 2, "Correct prime factorisation of 360. M1 for any two correct factors, A1 fully correct."),
        ("Q1b", "Number", 2, "LCM = 72. M1 for attempt, A1 correct answer."),
        ("Q2a", "Algebra", 3, "Expand (x+3)(x-2) = x^2 + x - 6. M1 expansion, A1 correct."),
        ("Q2b", "Algebra", 3, "Solve 3x - 7 = 11, x = 6. M1 rearrange, A1 answer."),
        ("Q3", "Statistics", 4, "Mean = 12.5, median = 12. Method marks for table and calculation."),
        ("Q4a", "Geometry", 2, "Angle sum property. Answer 65 degrees with working."),
        ("Q4b", "Trigonometry", 4, "sin(30)=0.5 used correctly. Final height 5.0m."),
    ]
    for i, (label, topic, marks, scheme) in enumerate(sample_questions):
        conn.execute(
            """
            INSERT INTO questions (assignment_id, label, topic, max_marks, mark_scheme_text, page_number, order_index)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (assignment_id, label, topic, marks, scheme, 1, i),
        )

    practice = [
        ("Algebra", "PP-2019-Q4", "Solve the simultaneous equations: 2x + y = 7 and x - y = 2."),
        ("Algebra", "PP-2020-Q2", "Factorise completely: 6x^2 - 15x."),
        ("Trigonometry", "PP-2021-Q8", "Calculate the length of side AB in triangle ABC where angle C = 90."),
        ("Statistics", "WS-Unit5-Q3", "Draw a cumulative frequency curve for the grouped data provided."),
        ("Number", "PP-2018-Q1", "Write 0.00045 in standard form."),
        ("Probability", "PP-2022-Q6", "A bag has 3 red and 5 blue balls. Find P(red then blue) without replacement."),
        ("Geometry", "WS-Unit2-Q1", "Find the interior angle of a regular octagon."),
        ("Graphs", "PP-2020-Q5", "Sketch y = 2x - 3 and find the x-intercept."),
    ]
    for topic, label, text in practice:
        conn.execute(
            "INSERT INTO practice_questions (topic, label, text, source) VALUES (?, ?, ?, ?)",
            (topic, label, text, "seed"),
        )

    conn.commit()
    conn.close()


def get_user_by_email(email: str):
    conn = connect()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row


def get_user_by_id(user_id: int):
    conn = connect()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def query_all(sql: str, params=()):
    conn = connect()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def query_one(sql: str, params=()):
    conn = connect()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def execute(sql: str, params=()):
    conn = connect()
    cur = conn.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def update_assignment_total_marks(assignment_id: int):
    conn = connect()
    total = conn.execute(
        "SELECT COALESCE(SUM(max_marks), 0) AS t FROM questions WHERE assignment_id = ?",
        (assignment_id,),
    ).fetchone()["t"]
    conn.execute(
        "UPDATE assignments SET total_marks = ? WHERE id = ?",
        (total, assignment_id),
    )
    conn.commit()
    conn.close()


def compute_topic_mastery(student_id: int):
    rows = query_all(
        """
        SELECT q.topic,
               SUM(COALESCE(gd.final_mark, 0)) AS earned,
               SUM(q.max_marks) AS possible,
               COUNT(*) AS question_count
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        JOIN submissions s ON s.id = gd.submission_id
        WHERE s.student_id = ? AND s.status = 'final' AND gd.final_mark IS NOT NULL
        GROUP BY q.topic
        """,
        (student_id,),
    )
    result = []
    for row in rows:
        possible = row["possible"] or 0
        earned = row["earned"] or 0
        pct = round(100 * earned / possible, 1) if possible else 0
        result.append(
            {
                "topic": row["topic"],
                "earned": earned,
                "possible": possible,
                "accuracy": pct,
                "question_count": row["question_count"],
            }
        )
    result.sort(key=lambda x: x["accuracy"])
    return result


def weak_topics(student_id: int, threshold: float = 60.0):
    mastery = compute_topic_mastery(student_id)
    return [m for m in mastery if m["accuracy"] < threshold]


def recommend_practice(student_id: int, limit: int = 5):
    weak = weak_topics(student_id)
    if not weak:
        mastery = compute_topic_mastery(student_id)
        if mastery:
            topic = mastery[0]["topic"]
        else:
            return query_all(
                "SELECT * FROM practice_questions ORDER BY id LIMIT ?",
                (limit,),
            )
        return query_all(
            "SELECT * FROM practice_questions WHERE topic = ? ORDER BY id LIMIT ?",
            (topic, limit),
        )

    topic = weak[0]["topic"]
    return query_all(
        "SELECT * FROM practice_questions WHERE topic = ? ORDER BY id LIMIT ?",
        (topic, limit),
    )
