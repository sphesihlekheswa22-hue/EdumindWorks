"""Backfill marks and quiz results for enrolled students missing assessment data."""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from app import create_app, db
from app.models import Enrollment, Mark, Module, Quiz, QuizResult, Student, User
from app.services.risk_service import AT_RISK_THRESHOLD, recalculate_all_risk_scores
from seed_data import (
    STRUGGLING_STUDENT_EMAILS,
    _score_for_tier,
    calculate_grade,
)


def _tier_for_student(student: Student, course_id: int) -> str:
    email = (student.user.email or "").lower() if student.user else ""
    if email in STRUGGLING_STUDENT_EMAILS:
        return "struggling"

    from app.models import RiskScore

    risk = RiskScore.query.filter_by(student_id=student.id, course_id=course_id).first()
    if risk and risk.overall_score is not None and risk.overall_score < AT_RISK_THRESHOLD:
        return "struggling"
    return random.choice(["average", "strong"])


def backfill_enrolled_assessments() -> dict:
    admin = User.query.filter_by(role="admin").first()
    if not admin:
        return {"students_updated": 0, "marks_added": 0, "quiz_results_added": 0}

    marks_added = 0
    quiz_results_added = 0
    students_updated = 0
    assessment_types = ["assignment", "midterm", "final", "project"]

    for enrollment in Enrollment.query.filter_by(status="active").all():
        student = enrollment.student
        course = enrollment.course
        if not student or not course:
            continue

        module_ids = [module.id for module in (course.modules or [])]
        if not module_ids:
            continue

        existing_marks = Mark.query.filter(
            Mark.student_id == student.id,
            Mark.module_id.in_(module_ids),
        ).count()
        existing_quizzes = (
            QuizResult.query.join(Quiz, QuizResult.quiz_id == Quiz.id)
            .filter(QuizResult.student_id == student.id, Quiz.module_id.in_(module_ids))
            .count()
        )
        if existing_marks and existing_quizzes:
            continue

        tier = _tier_for_student(student, enrollment.course_id)
        student_changed = False

        if not existing_marks:
            num_marks = 4 if tier == "struggling" else random.randint(2, 4)
            for index in range(num_marks):
                module = db.session.get(Module, random.choice(module_ids))
                if not module:
                    continue
                total = random.choice([100, 50, 20])
                if tier == "struggling":
                    target_pct = random.uniform(32, min(52, 54))
                    mark_score = round(total * target_pct / 100, 1)
                    percentage = min(100.0, (mark_score / total) * 100)
                else:
                    score, percentage, _ = _score_for_tier(tier, total, 60)
                    mark_score = score

                db.session.add(
                    Mark(
                        module_id=module.id,
                        student_id=student.id,
                        assessment_type=random.choice(assessment_types),
                        assessment_name=f"{assessment_types[index % len(assessment_types)].title()} {index + 1}",
                        mark=mark_score,
                        total_marks=total,
                        percentage=percentage,
                        grade=calculate_grade(percentage),
                        recorded_by=admin.id,
                        feedback="Needs improvement." if tier == "struggling" else None,
                        marked_at=datetime.now() - timedelta(days=random.randint(1, 45)),
                    )
                )
                marks_added += 1
                student_changed = True

        if not existing_quizzes:
            quizzes = Quiz.query.filter(Quiz.module_id.in_(module_ids)).all()
            for quiz in quizzes:
                if QuizResult.query.filter_by(quiz_id=quiz.id, student_id=student.id).first():
                    continue
                if tier != "struggling" and random.random() > 0.65:
                    continue

                total = max(1, int(quiz.total_points or 100))
                score, percentage, passed = _score_for_tier(tier, total, quiz.passing_score or 60)
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
                quiz_results_added += 1
                student_changed = True

        if student_changed:
            students_updated += 1

    if marks_added or quiz_results_added:
        db.session.commit()

    return {
        "students_updated": students_updated,
        "marks_added": marks_added,
        "quiz_results_added": quiz_results_added,
    }


def main() -> int:
    app = create_app()
    with app.app_context():
        stats = backfill_enrolled_assessments()
        recalculate_all_risk_scores()
        print(
            f"Backfilled {stats['marks_added']} marks and "
            f"{stats['quiz_results_added']} quiz results "
            f"for {stats['students_updated']} students."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
