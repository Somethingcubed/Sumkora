import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pdf_utils import is_valid_pdf


ROOT = "Real Submissions"


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def check_batch(batch_path):
    roster_path = os.path.join(batch_path, "roster.csv")
    assignments_path = os.path.join(batch_path, "assignments.csv")
    submissions_dir = os.path.join(batch_path, "submissions")

    roster = read_csv(roster_path)
    assignments = read_csv(assignments_path)
    issues = []

    if not roster:
        issues.append("Missing or empty roster.csv")
    if not assignments:
        issues.append("Missing or empty assignments.csv")
    if not os.path.isdir(submissions_dir):
        issues.append("Missing submissions/ folder")
        pdf_files = []
    else:
        pdf_files = [
            name for name in os.listdir(submissions_dir)
            if name.lower().endswith(".pdf")
        ]

    roster_names = [row.get("student_name", "").strip() for row in roster]
    roster_emails = [row.get("email", "").strip() for row in roster]
    for value, count in Counter(roster_names).items():
        if value and count > 1:
            issues.append(f"Duplicate student name in roster: {value}")
    for value, count in Counter(roster_emails).items():
        if value and count > 1:
            issues.append(f"Duplicate email in roster: {value}")

    expected_names = {name.lower() for name in roster_names if name}
    seen_names = set()
    for filename in pdf_files:
        student_name = os.path.splitext(filename)[0].strip()
        seen_names.add(student_name.lower())
        path = os.path.join(submissions_dir, filename)
        with open(path, "rb") as f:
            if not is_valid_pdf(f.read()):
                issues.append(f"Invalid PDF: {filename}")
        if student_name.lower() not in expected_names:
            issues.append(f"PDF has no matching roster student: {filename}")

    for name in sorted(expected_names - seen_names):
        issues.append(f"Roster student has no PDF: {name}")

    return {
        "batch": os.path.basename(batch_path),
        "roster_count": len(roster),
        "assignment_count": len(assignments),
        "pdf_count": len(pdf_files),
        "issues": issues,
    }


def main():
    if not os.path.isdir(ROOT):
        print(f"No '{ROOT}' folder found.")
        print("Create batches like: Real Submissions/2026-06-Homework-01/{roster.csv, assignments.csv, submissions/}")
        return

    batches = [
        os.path.join(ROOT, name)
        for name in sorted(os.listdir(ROOT))
        if os.path.isdir(os.path.join(ROOT, name))
    ]
    if not batches:
        print(f"No batch folders found inside '{ROOT}'.")
        return

    total_issues = 0
    for batch in batches:
        result = check_batch(batch)
        print(f"\n{result['batch']}")
        print(f"  roster students: {result['roster_count']}")
        print(f"  assignments: {result['assignment_count']}")
        print(f"  PDFs: {result['pdf_count']}")
        if result["issues"]:
            total_issues += len(result["issues"])
            print("  issues:")
            for issue in result["issues"]:
                print(f"    - {issue}")
        else:
            print("  issues: none")

    print(f"\nChecklist complete. Issues found: {total_issues}")


if __name__ == "__main__":
    main()
