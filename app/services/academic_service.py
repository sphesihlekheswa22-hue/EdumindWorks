"""Student academic summaries for dashboards and marks pages."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func

from app import db
from app.models import Enrollment, Mark, Module, Quiz, QuizResult, Student
from app.services.risk_service import (
    AT_RISK_THRESHOLD,
    compute_academic_scores,
    compute_student_metrics,
)
from app.utils.percentages import clamp_pct

MODULE_PASS_THRESHOLD = AT_RISK_THRESHOLD


def compute_module_status(student_id: int, module: Module) -> Optional[dict]:
    """Pass/fail for a single module from marks and quiz attempts."""
    marks = Mark.query.filter_by(student_id=student_id, module_id=module.id).all()
    quiz_avg = (
        db.session.query(func.avg(QuizResult.percentage))
        .join(Quiz, QuizResult.quiz_id == Quiz.id)
        .filter(QuizResult.student_id == student_id, Quiz.module_id == module.id)
        .scalar()
    )

    parts: list[float] = []
    if marks:
        parts.append(clamp_pct(sum(mark.percentage for mark in marks) / len(marks)))
    if quiz_avg is not None:
        parts.append(clamp_pct(quiz_avg))

    if not parts:
        return None

    average = round(sum(parts) / len(parts), 1)
    passing = average >= MODULE_PASS_THRESHOLD
    return {
        "module_id": module.id,
        "module_title": module.title,
        "module_order": module.order,
        "average": average,
        "marks_avg": round(parts[0], 1) if marks else None,
        "quiz_avg": round(clamp_pct(quiz_avg), 1) if quiz_avg is not None else None,
        "status": "passing" if passing else "failing",
        "passing": passing,
    }


def build_student_academic_summary(student: Student) -> dict:
    """Dashboard / marks summary based on active enrollments only."""
    enrollments = (
        Enrollment.query.filter_by(student_id=student.id, status="active")
        .order_by(Enrollment.enrolled_at.desc())
        .all()
    )

    empty = {
        "overall_percentage": 0.0,
        "gpa_4": 0.0,
        "is_at_risk": False,
        "primary_course": None,
        "primary_course_name": None,
        "primary_course_code": None,
        "course_summaries": [],
        "module_statuses": [],
        "current_semester": "Current Semester",
        "passing_modules": [],
        "failing_modules": [],
        "total_marks": 0,
        "total_quizzes": 0,
        "total_assessments": 0,
        "enrolled_course_count": 0,
    }
    if not enrollments:
        return empty

    enrolled_course_ids = {enrollment.course_id for enrollment in enrollments}
    course_summaries: list[dict] = []
    module_statuses: list[dict] = []
    is_at_risk = False

    for enrollment in enrollments:
        course = enrollment.course
        if not course or course.id not in enrolled_course_ids:
            continue

        course_module_ids = [module.id for module in course.modules]
        academic = compute_academic_scores(
            student.id,
            course_id=course.id,
            module_ids=course_module_ids or None,
        )
        risk = compute_student_metrics(
            student.id,
            course_id=course.id,
            module_ids=course_module_ids or None,
        )
        if risk.get("is_at_risk"):
            is_at_risk = True

        course_marks = Mark.query.filter(
            Mark.student_id == student.id,
            Mark.module_id.in_(course_module_ids),
        ).all() if course_module_ids else []
        quiz_results = (
            QuizResult.query.join(Quiz, QuizResult.quiz_id == Quiz.id)
            .filter(
                QuizResult.student_id == student.id,
                Quiz.module_id.in_(course_module_ids),
            )
            .all()
            if course_module_ids
            else []
        )

        if academic["overall_score"] is not None:
            display_average = academic["overall_score"]
        else:
            display_average = None

        score_samples = [mark.percentage for mark in course_marks] + [
            result.percentage for result in quiz_results
        ]

        course_summaries.append(
            {
                "course": course,
                "enrollment": enrollment,
                "average": display_average,
                "display_average": display_average,
                "marks_avg": academic["assignment_score"],
                "quiz_avg": academic["quiz_score"],
                "marks_count": len(course_marks),
                "quiz_count": len(quiz_results),
                "has_assessments": bool(course_marks or quiz_results),
                "highest": round(max(score_samples), 1) if score_samples else None,
                "lowest": round(min(score_samples), 1) if score_samples else None,
                "is_at_risk": bool(risk.get("is_at_risk")),
                "risk_score": risk.get("overall_score"),
            }
        )

        for module in sorted(course.modules or [], key=lambda m: (m.order or 0, m.title or "")):
            status = compute_module_status(student.id, module)
            if not status:
                continue
            module_statuses.append(
                {
                    "course": course,
                    **status,
                }
            )

    primary = course_summaries[0]
    course_scores = [
        row["display_average"]
        for row in course_summaries
        if row["display_average"] is not None
    ]
    overall_percentage = (
        round(sum(course_scores) / len(course_scores), 1) if course_scores else 0.0
    )

    total_marks = sum(row["marks_count"] for row in course_summaries)
    total_quizzes = sum(row["quiz_count"] for row in course_summaries)

    gpa_4 = round((overall_percentage / 100) * 4.0, 2)
    passing_modules = [row for row in module_statuses if row["passing"]]
    failing_modules = [row for row in module_statuses if not row["passing"]]

    return {
        "overall_percentage": overall_percentage,
        "gpa_4": gpa_4,
        "is_at_risk": is_at_risk,
        "primary_course": primary["course"],
        "primary_course_name": primary["course"].name,
        "primary_course_code": primary["course"].code,
        "course_summaries": course_summaries,
        "module_statuses": module_statuses,
        "current_semester": primary["course"].semester or "Current Semester",
        "passing_modules": passing_modules,
        "failing_modules": failing_modules,
        "total_marks": total_marks,
        "total_quizzes": total_quizzes,
        "total_assessments": total_marks + total_quizzes,
        "enrolled_course_count": len(course_summaries),
    }


def _struggling_quiz_target_pct(student_id: int, quiz_id: int, passing_score: int) -> float:
    """Stable low score for a given student/quiz pair (32–52% band)."""
    import random

    rng = random.Random(student_id * 10_000 + quiz_id)
    upper = min(52.0, max(33.0, float(passing_score) - 1))
    return round(rng.uniform(32.0, upper), 1)


def rebalance_at_risk_quiz_scores() -> dict:
    """Lower inflated quiz scores for students who are failing / at risk."""
    from app.utils.percentages import percentage_from_parts

    updated = 0
    students_adjusted = 0

    for student in Student.query.all():
        if not Enrollment.query.filter_by(student_id=student.id, status="active").first():
            continue

        summary = build_student_academic_summary(student)
        struggling = bool(summary.get("is_at_risk")) or summary.get("overall_percentage", 100) < AT_RISK_THRESHOLD
        if not struggling:
            continue

        student_updates = 0
        for result in QuizResult.query.filter_by(student_id=student.id).all():
            if result.percentage <= AT_RISK_THRESHOLD:
                continue

            quiz = result.quiz
            passing_score = int(quiz.passing_score or 60) if quiz else 60
            target_pct = _struggling_quiz_target_pct(student.id, result.quiz_id, passing_score)
            total = float(result.total_points or 100)
            result.score = round(total * target_pct / 100, 1)
            result.percentage = percentage_from_parts(result.score, total)
            result.passed = result.percentage >= passing_score
            student_updates += 1

        if student_updates:
            students_adjusted += 1
            updated += student_updates

    if updated:
        db.session.commit()

    return {
        "students_adjusted": students_adjusted,
        "quiz_results_updated": updated,
    }
