"""Add failing/at-risk students to an existing database without wiping data."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
import random

sys.path.insert(0, ".")

from app import create_app, db
from app.models import (
    Attendance,
    Course,
    Enrollment,
    Mark,
    Module,
    Quiz,
    QuizResult,
    Student,
    User,
)
from app.services.risk_service import recalculate_all_risk_scores
from seed_data import (
    _attendance_status_for_tier,
    _score_for_tier,
    calculate_grade,
)

NEW_FAILING_STUDENTS = [
    {"email": "nhlamulo.nxumalo@student.edumind.com", "first_name": "Nhlamulo", "last_name": "Nxumalo"},
    {"email": "ntiyiso.bila@student.edumind.com", "first_name": "Ntiyiso", "last_name": "Bila"},
    {"email": "simone.mlomo@student.edumind.com", "first_name": "Simone", "last_name": "Mlomo"},
    {"email": "junior.phatudi@student.edumind.com", "first_name": "Junior", "last_name": "Phatudi"},
    {"email": "sduduzo.ngcobo@student.edumind.com", "first_name": "Sduduzo", "last_name": "Ngcobo"},
    {"email": "sifiso.rafaba@student.edumind.com", "first_name": "Sifiso", "last_name": "Rafaba"},
    {"email": "bundas.mojakie@student.edumind.com", "first_name": "Bundas", "last_name": "Mojakie"},
    {"email": "thabo.mokoena@student.edumind.com", "first_name": "Thabo", "last_name": "Mokoena"},
    {"email": "lerato.dlamini@student.edumind.com", "first_name": "Lerato", "last_name": "Dlamini"},
    {"email": "zanele.khumalo@student.edumind.com", "first_name": "Zanele", "last_name": "Khumalo"},
]

PASSWORD = "student123"
TIER = "struggling"


def _next_student_number() -> str:
    latest = (
        Student.query.filter(Student.student_id.isnot(None))
        .order_by(Student.id.desc())
        .first()
    )
    if latest and latest.student_id and latest.student_id.isdigit():
        return f"{int(latest.student_id) + 1:09d}"
    return f"{220900000 + Student.query.count():09d}"


def _seed_academic_data(student: Student, course: Course, admin_id: int) -> None:
    modules = Module.query.filter_by(course_id=course.id).all()
    if not modules:
        return

    for days_ago in range(14):
        attendance = Attendance(
            module_id=random.choice(modules).id,
            student_id=student.id,
            date=datetime.now().date() - timedelta(days=days_ago),
            status=_attendance_status_for_tier(TIER),
            recorded_by=admin_id,
        )
        db.session.add(attendance)

    assessment_types = ["assignment", "midterm", "final", "project"]
    for index in range(4):
        total = random.choice([100, 50, 20])
        target_pct = random.uniform(32, 52)
        mark_score = round(total * target_pct / 100, 1)
        percentage = min(100.0, (mark_score / total) * 100)
        db.session.add(
            Mark(
                module_id=random.choice(modules).id,
                student_id=student.id,
                assessment_type=random.choice(assessment_types),
                assessment_name=f"{assessment_types[index % len(assessment_types)].title()} {index + 1}",
                mark=mark_score,
                total_marks=total,
                percentage=percentage,
                grade=calculate_grade(percentage),
                recorded_by=admin_id,
                feedback="Needs improvement.",
                marked_at=datetime.now() - timedelta(days=random.randint(1, 45)),
            )
        )

    quizzes = Quiz.query.filter(Quiz.module_id.in_([module.id for module in modules])).all()
    for quiz in quizzes:
        if QuizResult.query.filter_by(quiz_id=quiz.id, student_id=student.id).first():
            continue
        total = max(1, int(quiz.total_points or 100))
        score, percentage, passed = _score_for_tier(TIER, total, quiz.passing_score or 60)
        db.session.add(
            QuizResult(
                quiz_id=quiz.id,
                student_id=student.id,
                score=score,
                total_points=total,
                percentage=percentage,
                passed=passed,
                time_taken=random.randint(400, 3200),
                started_at=datetime.now() - timedelta(days=random.randint(3, 25)),
                completed_at=datetime.now() - timedelta(days=random.randint(1, 24)),
            )
        )


def main() -> int:
    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(role="admin").first()
        if not admin:
            print("No admin user found.")
            return 1

        courses = Course.query.filter_by(is_active=True).order_by(Course.id).all()
        if not courses:
            print("No active courses found.")
            return 1

        created = 0
        skipped = 0

        for index, row in enumerate(NEW_FAILING_STUDENTS):
            email = row["email"].lower()
            if User.query.filter_by(email=email).first():
                skipped += 1
                continue

            user = User(
                email=email,
                first_name=row["first_name"],
                last_name=row["last_name"],
                role="student",
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()

            student = Student(
                user_id=user.id,
                student_id=_next_student_number(),
                date_of_birth=datetime(2001, random.randint(1, 12), random.randint(1, 28)).date(),
                phone=f"+27-82-{random.randint(100, 999)}-{random.randint(1000, 9999)}",
                address=f"{random.randint(1, 120)} Campus Road, Gauteng",
                program="Diploma Programme",
                year_of_study=random.choice([1, 2, 3]),
                enrollment_date=datetime(2024, random.randint(1, 9), 1).date(),
            )
            db.session.add(student)
            db.session.flush()

            course = courses[index % len(courses)]
            db.session.add(
                Enrollment(
                    student_id=student.id,
                    course_id=course.id,
                    status="active",
                    enrolled_at=datetime.now() - timedelta(days=random.randint(30, 120)),
                )
            )
            _seed_academic_data(student, course, admin.id)
            created += 1

        db.session.commit()
        recalculate_all_risk_scores()
        print(f"Added {created} failing students ({skipped} already existed).")
        print("Default password for new students: student123")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
