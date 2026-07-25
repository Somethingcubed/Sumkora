import os
import sys
from datetime import datetime, timedelta

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import connect, hash_password, init_db, seed_if_empty, update_assignment_total_marks
from pdf_utils import save_upload


CLASS_NAME = "Creative Analytics Test Class"
PASSWORD = "student123"
TEACHER_EMAIL = "teacher@school.edu"

STUDENTS = [
    {
        "email": "creative.strong@demo.local",
        "name": "Maya Strong",
        "profile": "Already strong: usually correct, but still makes the occasional rushed arithmetic slip.",
    },
    {
        "email": "creative.weak@demo.local",
        "name": "Nina Needs Practice",
        "profile": "Currently weak: random working appears often, several omissions, low confidence on multi-step work.",
    },
    {
        "email": "creative.improving@demo.local",
        "name": "Leo Improving",
        "profile": "Improving: starts messy and incomplete, then becomes noticeably more accurate over five assignments.",
    },
]

ASSIGNMENTS = [
    {
        "title": "[Creative Text Demo] 01 - Number Fluency",
        "due_offset": -28,
        "questions": [
            {
                "label": "Q1",
                "topic": "Number",
                "subtopic": "standard form",
                "type": "number",
                "difficulty": "easy",
                "max": 2,
                "question": "A small bacterium has length \\(0.000072\\) m. Write this in standard form.",
                "scheme": "Answer: \\(7.2 \\times 10^{-5}\\). B1 for 7.2, B1 for correct power.",
            },
            {
                "label": "Q2",
                "topic": "Number",
                "subtopic": "percentage change",
                "type": "number",
                "difficulty": "medium",
                "max": 3,
                "question": "A jacket costs $64 after a 20% discount. Find the original price.",
                "scheme": "64 is 80%, so original price is 64/0.8 = 80.",
            },
            {
                "label": "Q3",
                "topic": "Number",
                "subtopic": "bounds",
                "type": "number",
                "difficulty": "hard",
                "max": 4,
                "question": "A length is measured as 12.4 cm to 1 decimal place. State the lower and upper bounds.",
                "scheme": "Lower bound 12.35 cm, upper bound 12.45 cm.",
            },
            {
                "label": "Q4",
                "topic": "Algebra",
                "subtopic": "substitution",
                "type": "solve_equation",
                "difficulty": "easy",
                "max": 2,
                "question": "Evaluate \\(3a^2-2b\\) when \\(a=4\\) and \\(b=5\\).",
                "scheme": "3(16)-10 = 38.",
            },
            {
                "label": "Q5",
                "topic": "Statistics",
                "subtopic": "mean from list",
                "type": "statistics",
                "difficulty": "medium",
                "max": 3,
                "question": "The scores are 4, 8, 8, 10, 15. Find the mean.",
                "scheme": "Total 45, divide by 5, mean 9.",
            },
        ],
    },
    {
        "title": "[Creative Text Demo] 02 - Algebra Equations",
        "due_offset": -21,
        "questions": [
            {
                "label": "Q1",
                "topic": "Algebra",
                "subtopic": "linear equations",
                "type": "solve_equation",
                "difficulty": "easy",
                "max": 2,
                "question": "Solve \\(5x-8=17\\).",
                "scheme": "5x = 25, x = 5.",
            },
            {
                "label": "Q2",
                "topic": "Algebra",
                "subtopic": "expansion",
                "type": "expand_factorise",
                "difficulty": "medium",
                "max": 3,
                "question": "Expand and simplify \\((x+6)(x-4)\\).",
                "scheme": "x^2 + 2x - 24.",
            },
            {
                "label": "Q3",
                "topic": "Algebra",
                "subtopic": "factorising",
                "type": "expand_factorise",
                "difficulty": "medium",
                "max": 3,
                "question": "Factorise completely \\(8y^2-20y\\).",
                "scheme": "4y(2y-5).",
            },
            {
                "label": "Q4",
                "topic": "Algebra",
                "subtopic": "simultaneous equations",
                "type": "solve_equation",
                "difficulty": "hard",
                "max": 5,
                "question": "Solve \\(2x+y=13\\) and \\(x-y=2\\).",
                "scheme": "Add equations after rearranging or substitute. x = 5, y = 3.",
            },
            {
                "label": "Q5",
                "topic": "Sequences",
                "subtopic": "linear nth term",
                "type": "sequences",
                "difficulty": "medium",
                "max": 4,
                "question": "Find the nth term of 7, 11, 15, 19, ...",
                "scheme": "Difference 4, nth term 4n+3.",
            },
        ],
    },
    {
        "title": "[Creative Text Demo] 03 - Probability and Statistics",
        "due_offset": -14,
        "questions": [
            {
                "label": "Q1",
                "topic": "Probability",
                "subtopic": "single event",
                "type": "probability",
                "difficulty": "easy",
                "max": 2,
                "question": "A bag has 5 red, 3 blue and 2 green counters. Find P(blue).",
                "scheme": "3/10.",
            },
            {
                "label": "Q2",
                "topic": "Probability",
                "subtopic": "without replacement",
                "type": "probability",
                "difficulty": "hard",
                "max": 5,
                "question": "Two counters are taken without replacement. Find P(red then green).",
                "scheme": "(5/10)(2/9) = 1/9.",
            },
            {
                "label": "Q3",
                "topic": "Statistics",
                "subtopic": "median and range",
                "type": "statistics",
                "difficulty": "medium",
                "max": 3,
                "question": "Find the median and range of 12, 4, 7, 18, 9, 7, 15.",
                "scheme": "Ordered 4,7,7,9,12,15,18. Median 9, range 14.",
            },
            {
                "label": "Q4",
                "topic": "Statistics",
                "subtopic": "frequency table",
                "type": "statistics",
                "difficulty": "hard",
                "max": 5,
                "question": "A frequency table has values 1,2,3,4 with frequencies 3,5,6,2. Find the mean.",
                "scheme": "Total fx = 3+10+18+8 = 39. Total frequency 16. Mean 39/16 = 2.4375.",
            },
            {
                "label": "Q5",
                "topic": "Number",
                "subtopic": "ratio",
                "type": "number",
                "difficulty": "medium",
                "max": 3,
                "question": "Share $96 in the ratio 5:7.",
                "scheme": "12 parts, one part 8, shares 40 and 56.",
            },
        ],
    },
    {
        "title": "[Creative Text Demo] 04 - Trigonometry and Mensuration",
        "due_offset": -7,
        "questions": [
            {
                "label": "Q1",
                "topic": "Trigonometry",
                "subtopic": "right triangle sine",
                "type": "trigonometry",
                "difficulty": "medium",
                "max": 4,
                "question": "A ladder is 8 m long and makes a 60 degree angle with the ground. Find the height reached.",
                "scheme": "height = 8 sin 60 = 6.93 m.",
            },
            {
                "label": "Q2",
                "topic": "Trigonometry",
                "subtopic": "tan ratio",
                "type": "trigonometry",
                "difficulty": "hard",
                "max": 5,
                "question": "A tree casts a 12 m shadow. The angle of elevation to the top is 38 degrees. Find the height.",
                "scheme": "height = 12 tan 38 = 9.38 m.",
            },
            {
                "label": "Q3",
                "topic": "Mensuration",
                "subtopic": "circle area",
                "type": "mensuration",
                "difficulty": "medium",
                "max": 3,
                "question": "Find the area of a circle with radius 4 cm.",
                "scheme": "Area = pi r^2 = 16pi = 50.3 cm^2.",
            },
            {
                "label": "Q4",
                "topic": "Mensuration",
                "subtopic": "compound volume",
                "type": "mensuration",
                "difficulty": "hard",
                "max": 5,
                "question": "A prism has cross-section area 18 cm^2 and length 11 cm. Find its volume, then convert to mm^3.",
                "scheme": "Volume 198 cm^3 = 198000 mm^3.",
            },
            {
                "label": "Q5",
                "topic": "Algebra",
                "subtopic": "formula rearrangement",
                "type": "solve_equation",
                "difficulty": "hard",
                "max": 4,
                "question": "Rearrange \\(v=u+at\\) to make \\(t\\) the subject.",
                "scheme": "t = (v-u)/a.",
            },
        ],
    },
    {
        "title": "[Creative Text Demo] 05 - Mixed Word Problems",
        "due_offset": 0,
        "questions": [
            {
                "label": "Q1",
                "topic": "Number",
                "subtopic": "reverse percentage",
                "type": "number",
                "difficulty": "medium",
                "max": 4,
                "question": "After a 15% increase, a price is $92. Find the original price.",
                "scheme": "Original price = 92/1.15 = 80.",
            },
            {
                "label": "Q2",
                "topic": "Algebra",
                "subtopic": "forming equations",
                "type": "solve_equation",
                "difficulty": "hard",
                "max": 5,
                "question": "Three consecutive integers have sum 84. Find the integers.",
                "scheme": "n+(n+1)+(n+2)=84, n=27, integers 27,28,29.",
            },
            {
                "label": "Q3",
                "topic": "Probability",
                "subtopic": "combined events",
                "type": "probability",
                "difficulty": "hard",
                "max": 5,
                "question": "A fair spinner has 1,2,3,4 and a coin is tossed. Find P(even number and heads).",
                "scheme": "P(even)=1/2 and P(heads)=1/2, combined probability 1/4.",
            },
            {
                "label": "Q4",
                "topic": "Statistics",
                "subtopic": "weighted mean",
                "type": "statistics",
                "difficulty": "hard",
                "max": 5,
                "question": "Class A has 20 students with mean 14. Class B has 30 students with mean 18. Find the combined mean.",
                "scheme": "(20*14 + 30*18)/50 = 16.4.",
            },
            {
                "label": "Q5",
                "topic": "Sequences",
                "subtopic": "quadratic sequence",
                "type": "sequences",
                "difficulty": "hard",
                "max": 6,
                "question": "The nth term is \\(n^2+3n\\). Find the 8th term and explain why the sequence is quadratic.",
                "scheme": "8th term 64+24=88. Quadratic because second difference is constant.",
            },
        ],
    },
]

MARKS = {
    "creative.strong@demo.local": [
        [2, 3, 4, 2, 3],
        [2, 3, 3, 4, 4],
        [2, 5, 3, 4, 3],
        [4, 4, 3, 4, 4],
        [4, 5, 4, 5, 5],
    ],
    "creative.weak@demo.local": [
        [1, 0, 1, 0, 1],
        [0, 1, 0, 1, 0],
        [1, 0, 1, 0, 1],
        [0, 1, 0, 1, 0],
        [1, 0, 0, 1, 0],
    ],
    "creative.improving@demo.local": [
        [1, 0, 1, 1, 1],
        [1, 1, 1, 2, 1],
        [2, 2, 2, 2, 2],
        [3, 3, 2, 3, 2],
        [3, 4, 4, 4, 4],
    ],
}

ANSWER_TEXT = {
    "creative.strong@demo.local": {
        "good": "Clear working, final answer stated, one line slightly rushed but readable.",
        "partial": "Method is correct, but a small arithmetic or rounding slip appears.",
    },
    "creative.weak@demo.local": {
        "good": "Short correct fragment appears, but working is thin.",
        "partial": "Messy attempt; jumps between unrelated numbers and does not finish.",
        "zero": "Random working: copies numbers from the question, writes 'not sure', final answer missing.",
    },
    "creative.improving@demo.local": {
        "good": "Working is more organised now; final answer follows from the method.",
        "partial": "Starts correctly, then loses a step or leaves the final answer unfinished.",
        "zero": "Incomplete early attempt; some copied question values but no usable method.",
    },
}


def answer_style(email, mark, max_mark):
    if mark >= max_mark - 0.5:
        return ANSWER_TEXT[email]["good"]
    if mark > 0:
        return ANSWER_TEXT[email]["partial"]
    return ANSWER_TEXT[email].get("zero", ANSWER_TEXT[email]["partial"])


def make_pdf(student, assignment, marks):
    doc = fitz.open()
    page = doc.new_page()
    y = 54
    page.insert_text((54, y), f"{student['name']} - {assignment['title']}", fontsize=13)
    y += 18
    page.insert_text((54, y), student["profile"], fontsize=9)
    y += 28
    for question, mark in zip(assignment["questions"], marks):
        lines = [
            f"{question['label']}. {question['question']}",
            f"Student working: {answer_style(student['email'], mark, question['max'])}",
            f"Visible final answer quality: {'clear' if mark >= question['max'] - 0.5 else 'unclear / wrong / omitted'}",
            f"Demo confirmed mark: {mark}/{question['max']}",
        ]
        for line in lines:
            page.insert_text((54, y), line.replace("\\", ""), fontsize=9)
            y += 14
        y += 8
        if y > 735:
            page = doc.new_page()
            y = 54
    content = doc.tobytes()
    doc.close()
    return content


def reset_for_creative_demo(conn):
    conn.execute("DELETE FROM classes")
    conn.execute("DELETE FROM users WHERE role = 'student'")


def main():
    init_db()
    seed_if_empty()
    conn = connect()
    reset_for_creative_demo(conn)

    teacher = conn.execute(
        "SELECT id FROM users WHERE email = ? AND role = 'teacher'",
        (TEACHER_EMAIL,),
    ).fetchone()
    if not teacher:
        teacher_hash = hash_password("teacher123")
        conn.execute(
            "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, 'teacher')",
            (TEACHER_EMAIL, teacher_hash, "Oscar"),
        )
        teacher = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (TEACHER_EMAIL,),
        ).fetchone()

    conn.execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        (CLASS_NAME, teacher["id"]),
    )
    class_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    password_hash = hash_password(PASSWORD)
    student_ids = {}
    for student in STUDENTS:
        conn.execute(
            "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, 'student')",
            (student["email"], password_hash, student["name"]),
        )
        student_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        student_ids[student["email"]] = student_id
        conn.execute(
            "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
            (class_id, student_id),
        )

    assignment_ids = []
    for assignment_index, assignment in enumerate(ASSIGNMENTS):
        due = (datetime.now() + timedelta(days=assignment["due_offset"])).strftime("%Y-%m-%d")
        conn.execute(
            """
            INSERT INTO assignments
            (class_id, title, type, due_date, total_marks, status, created_at)
            VALUES (?, ?, 'worksheet', ?, 0, 'published', ?)
            """,
            (class_id, assignment["title"], due, datetime.now().isoformat()),
        )
        assignment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        assignment_ids.append(assignment_id)
        for order, question in enumerate(assignment["questions"]):
            conn.execute(
                """
                INSERT INTO questions
                (assignment_id, label, topic, subtopic, question_text, max_marks,
                 mark_scheme_text, page_number, order_index, difficulty_teacher,
                 question_type_tag, answer_only_eligible, requires_method_marks)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    assignment_id,
                    question["label"],
                    question["topic"],
                    question["subtopic"],
                    question["question"],
                    question["max"],
                    question["scheme"],
                    order,
                    question["difficulty"],
                    question["type"],
                    1 if question["max"] <= 2 else 0,
                    1 if question["max"] >= 3 else 0,
                ),
            )
        conn.commit()
        update_assignment_total_marks(assignment_id)

    for student in STUDENTS:
        for assignment_index, assignment in enumerate(ASSIGNMENTS):
            assignment_id = assignment_ids[assignment_index]
            marks = MARKS[student["email"]][assignment_index]
            pdf_content = make_pdf(student, assignment, marks)
            path = save_upload(
                f"creative_demo_{student['email'].split('@')[0]}_{assignment_index + 1}.pdf",
                pdf_content,
            )
            conn.execute(
                """
                INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
                VALUES (?, ?, ?, 'final', ?)
                """,
                (
                    assignment_id,
                    student_ids[student["email"]],
                    path,
                    datetime.now().isoformat(),
                ),
            )
            submission_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            questions = conn.execute(
                "SELECT id, max_marks FROM questions WHERE assignment_id = ? ORDER BY order_index",
                (assignment_id,),
            ).fetchall()
            for question, mark in zip(questions, marks):
                mark = min(float(mark), float(question["max_marks"]))
                max_mark = float(question["max_marks"])
                note = answer_style(student["email"], mark, max_mark)
                conn.execute(
                    """
                    INSERT INTO grade_drafts
                    (submission_id, question_id, ai_mark, ai_confidence, ai_notes,
                     final_mark, teacher_comment, risk_flags, needs_exception_review,
                     auto_finalized_at, auto_finalize_reason)
                    VALUES (?, ?, ?, 0.99, ?, ?, ?, '[]', 0, ?, 'creative_text_demo')
                    """,
                    (
                        submission_id,
                        question["id"],
                        mark,
                        f"Text-demo confirmed mark. {note}",
                        mark,
                        note,
                        datetime.now().isoformat(),
                    ),
                )

    conn.commit()

    counts = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM users WHERE role = 'student') AS students,
          (SELECT COUNT(*) FROM classes) AS classes,
          (SELECT COUNT(*) FROM assignments) AS assignments,
          (SELECT COUNT(*) FROM submissions) AS submissions,
          (SELECT COUNT(*) FROM grade_drafts) AS grade_rows
        """
    ).fetchone()
    conn.close()

    print("Creative analytics text demo rebuilt.")
    print(f"Class: {CLASS_NAME}")
    print(
        f"Counts: {counts['students']} students, {counts['classes']} class, "
        f"{counts['assignments']} assignments, {counts['submissions']} submissions, "
        f"{counts['grade_rows']} grade rows."
    )
    print("Accounts:")
    print(f"  Teacher: {TEACHER_EMAIL} / teacher123")
    for student in STUDENTS:
        print(f"  {student['name']}: {student['email']} / {PASSWORD}")
    print("Expected patterns:")
    print("  Maya Strong: consistently high; a few partials on hard trig/mensuration/sequences.")
    print("  Nina Needs Practice: low and messy; should dominate support/review queues.")
    print("  Leo Improving: low first, visibly rising over five assignments.")


if __name__ == "__main__":
    main()
