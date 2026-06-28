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

        course_summaries.append(
            {
                "course": course,
                "enrollment": enrollment,
                "average": academic["overall_score"],
                "marks_avg": academic["assignment_score"],
                "quiz_avg": academic["quiz_score"],
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
    course_scores = [row["average"] for row in course_summaries if row["average"] is not None]
    overall_percentage = round(sum(course_scores) / len(course_scores), 1) if course_scores else 0.0

    if is_at_risk:
        risk_scores = [
            row["risk_score"]
            for row in course_summaries
            if row.get("is_at_risk") and row.get("risk_score") is not None
        ]
        if risk_scores:
            overall_percentage = round(min(risk_scores), 1)
        overall_percentage = min(overall_percentage, AT_RISK_THRESHOLD - 0.1)

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
    }
