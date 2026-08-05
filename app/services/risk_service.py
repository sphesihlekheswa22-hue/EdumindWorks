"""Academic performance and at-risk calculations from live LMS data."""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import func

from app import db
from app.models import Attendance, Course, Enrollment, Mark, Module, Quiz, QuizResult, RiskScore, Student
from app.utils.app_time import app_now


from app.utils.percentages import clamp_pct

AT_RISK_THRESHOLD = 55.0


def latest_quiz_results(student_id: int, module_ids: Optional[list[int]] = None) -> list:
    """Most recent quiz attempt per quiz, optionally scoped to modules."""
    query = (
        QuizResult.query.join(Quiz, QuizResult.quiz_id == Quiz.id)
        .filter(QuizResult.student_id == student_id)
        .order_by(QuizResult.quiz_id, QuizResult.completed_at.desc(), QuizResult.id.desc())
    )
    if module_ids:
        query = query.filter(Quiz.module_id.in_(module_ids))

    seen: set[int] = set()
    latest: list = []
    for result in query.all():
        if result.quiz_id in seen:
            continue
        seen.add(result.quiz_id)
        latest.append(result)
    return latest


def performance_level(overall_score: float) -> str:
    """Map overall performance (0-100, higher is better) to risk band."""
    if overall_score >= 75:
        return "low"
    if overall_score >= 60:
        return "medium"
    if overall_score >= 50:
        return "high"
    return "critical"


def compute_academic_scores(
    student_id: int,
    course_id: Optional[int] = None,
    module_ids: Optional[list[int]] = None,
) -> dict:
    """Marks and quiz averages for lecturer dashboards (attendance excluded)."""
    if module_ids is None and course_id:
        module_ids = [module.id for module in Module.query.filter_by(course_id=course_id).all()]

    scoped_modules = module_ids or []

    marks_query = Mark.query.filter(Mark.student_id == student_id)
    if scoped_modules:
        marks_query = marks_query.filter(Mark.module_id.in_(scoped_modules))
    marks = marks_query.all()
    assignment_score = (
        round(clamp_pct(sum(mark.percentage for mark in marks) / len(marks)), 1) if marks else None
    )

    quiz_results = latest_quiz_results(student_id, module_ids=scoped_modules or None)
    quiz_score = (
        round(clamp_pct(sum(r.percentage for r in quiz_results) / len(quiz_results)), 1)
        if quiz_results
        else None
    )

    score_parts = [score for score in (assignment_score, quiz_score) if score is not None]
    overall_score = round(sum(score_parts) / len(score_parts), 1) if score_parts else None

    return {
        "has_data": bool(score_parts),
        "assignment_score": assignment_score,
        "quiz_score": quiz_score,
        "overall_score": overall_score,
    }


def compute_student_metrics(
    student_id: int,
    course_id: Optional[int] = None,
    module_ids: Optional[list[int]] = None,
) -> dict:
    """Calculate attendance, quiz, mark averages and whether the student is at risk."""
    if module_ids is None and course_id:
        module_ids = [module.id for module in Module.query.filter_by(course_id=course_id).all()]

    scoped_modules = module_ids or []

    attendance_query = Attendance.query.filter(Attendance.student_id == student_id)
    if scoped_modules:
        attendance_query = attendance_query.filter(Attendance.module_id.in_(scoped_modules))
    attendance_records = attendance_query.all()
    if attendance_records:
        present = sum(1 for record in attendance_records if record.status == "present")
        attendance_score = clamp_pct(present / len(attendance_records) * 100)
    else:
        attendance_score = None

    marks_query = Mark.query.filter(Mark.student_id == student_id)
    if scoped_modules:
        marks_query = marks_query.filter(Mark.module_id.in_(scoped_modules))
    marks = marks_query.all()
    assignment_score = (
        clamp_pct(sum(mark.percentage for mark in marks) / len(marks)) if marks else None
    )

    quiz_results = latest_quiz_results(student_id, module_ids=scoped_modules or None)
    quiz_score = (
        round(clamp_pct(sum(r.percentage for r in quiz_results) / len(quiz_results)), 1)
        if quiz_results
        else None
    )

    weighted_parts: list[tuple[float, float]] = []
    if attendance_score is not None:
        weighted_parts.append((attendance_score, 0.25))
    if quiz_score is not None:
        weighted_parts.append((quiz_score, 0.30))
    if assignment_score is not None:
        weighted_parts.append((assignment_score, 0.45))

    if not weighted_parts:
        return {
            "has_data": False,
            "attendance_score": None,
            "quiz_score": None,
            "assignment_score": None,
            "overall_score": None,
            "performance_score": None,
            "risk_level": "low",
            "is_at_risk": False,
            "risk_factors": [],
        }

    weight_total = sum(weight for _, weight in weighted_parts)
    overall = sum(score * weight for score, weight in weighted_parts) / weight_total
    overall = round(clamp_pct(overall), 1)

    risk_factors: list[str] = []
    if attendance_score is not None and attendance_score < 75:
        risk_factors.append(f"Attendance below 75% ({attendance_score:.0f}%)")
    if quiz_score is not None and quiz_score < 55:
        risk_factors.append(f"Quiz average below 55% ({quiz_score:.0f}%)")
    if assignment_score is not None and assignment_score < 55:
        risk_factors.append(f"Assessment average below 55% ({assignment_score:.0f}%)")

    risk_level = performance_level(overall)
    is_at_risk = overall < AT_RISK_THRESHOLD

    return {
        "has_data": True,
        "attendance_score": round(attendance_score, 1) if attendance_score is not None else None,
        "quiz_score": round(quiz_score, 1) if quiz_score is not None else None,
        "assignment_score": round(assignment_score, 1) if assignment_score is not None else None,
        "overall_score": overall,
        "performance_score": overall,
        "risk_level": risk_level,
        "is_at_risk": is_at_risk,
        "risk_factors": risk_factors,
    }


def sync_risk_score_record(
    student_id: int,
    course_id: Optional[int] = None,
    module_ids: Optional[list[int]] = None,
) -> Optional[RiskScore]:
    """Persist calculated metrics on the risk_scores table."""
    metrics = compute_student_metrics(student_id, course_id=course_id, module_ids=module_ids)
    if not metrics["has_data"]:
        return None

    record = RiskScore.query.filter_by(student_id=student_id, course_id=course_id).first()
    if not record:
        record = RiskScore(student_id=student_id, course_id=course_id)
        db.session.add(record)

    record.risk_score = metrics["overall_score"]
    record.overall_score = metrics["overall_score"]
    record.attendance_score = metrics["attendance_score"]
    record.quiz_score = metrics["quiz_score"]
    record.assignment_score = metrics["assignment_score"]
    record.risk_level = metrics["risk_level"]
    record.risk_factors = json.dumps(metrics["risk_factors"])
    record.recommendations = _recommendations_for(metrics)
    record.calculated_at = app_now()
    return record


def _recommendations_for(metrics: dict) -> str:
    if not metrics.get("is_at_risk"):
        return "Keep up the good work. Maintain attendance and review module materials weekly."
    tips = []
    if any("Attendance" in factor for factor in metrics.get("risk_factors", [])):
        tips.append("Improve lecture attendance and check in on time.")
    if any("Quiz" in factor for factor in metrics.get("risk_factors", [])):
        tips.append("Review quiz feedback and practice module quizzes before deadlines.")
    if any("Assessment" in factor for factor in metrics.get("risk_factors", [])):
        tips.append("Meet with your lecturer about upcoming assignments and past marks.")
    if not tips:
        tips.append("Schedule a check-in with your lecturer for academic support.")
    return " ".join(tips)


def list_at_risk_students(
    course_ids: Optional[list[int]] = None,
    module_ids: Optional[list[int]] = None,
) -> list[dict]:
    """Students flagged at risk based on live marks, quizzes, and attendance."""
    enrollment_query = Enrollment.query.filter(Enrollment.status == "active")
    if course_ids:
        enrollment_query = enrollment_query.filter(Enrollment.course_id.in_(course_ids))
    enrollments = enrollment_query.all()

    at_risk: list[dict] = []
    seen: set[tuple[int, Optional[int]]] = set()

    for enrollment in enrollments:
        student = enrollment.student
        if not student or not student.user:
            continue

        course = enrollment.course
        course_module_ids = [module.id for module in course.modules] if course else []
        scoped_modules = module_ids or course_module_ids
        if module_ids:
            scoped_modules = [module_id for module_id in course_module_ids if module_id in module_ids]
            if not scoped_modules:
                continue

        key = (student.id, enrollment.course_id)
        if key in seen:
            continue
        seen.add(key)

        metrics = compute_student_metrics(
            student.id,
            course_id=enrollment.course_id,
            module_ids=scoped_modules or None,
        )
        if not metrics["has_data"] or not metrics["is_at_risk"]:
            continue

        at_risk.append(
            {
                "id": student.id,
                "name": student.user.full_name,
                "course_id": enrollment.course_id,
                "course_code": course.code if course else "",
                "performance_score": metrics["performance_score"],
                "risk_level": metrics["risk_level"],
                "attendance": metrics["attendance_score"],
                "avg_score": metrics["overall_score"],
                "quiz_score": metrics["quiz_score"],
                "risk_factors": metrics["risk_factors"],
            }
        )

    at_risk.sort(key=lambda row: row["performance_score"])
    return at_risk


def count_at_risk_students() -> int:
    """Count distinct active students flagged at risk in at least one enrollment."""
    return len({row["id"] for row in list_at_risk_students()})


def recalculate_all_risk_scores() -> int:
    """Rebuild risk score rows from current academic data."""
    RiskScore.query.delete()
    updated = 0

    enrollments = Enrollment.query.filter_by(status="active").all()
    seen_pairs: set[tuple[int, int]] = set()
    for enrollment in enrollments:
        pair = (enrollment.student_id, enrollment.course_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        if sync_risk_score_record(enrollment.student_id, course_id=enrollment.course_id):
            updated += 1

    for student in Student.query.all():
        if sync_risk_score_record(student.id, course_id=None):
            updated += 1

    db.session.commit()
    return updated
