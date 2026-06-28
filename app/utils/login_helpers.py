"""Shared login lookup helpers (student/staff number or email)."""
from __future__ import annotations

from typing import Optional

from app.models import Lecturer, StaffProfile, Student, User


def resolve_user_from_login_id(login_id: str) -> Optional[User]:
    """Find a user by student/staff number or institutional email."""
    value = (login_id or "").strip()
    if not value:
        return None

    student = Student.query.filter_by(student_id=value).first()
    if student and student.user:
        return student.user

    lecturer = Lecturer.query.filter_by(employee_id=value).first()
    if lecturer and lecturer.user:
        return lecturer.user

    staff = StaffProfile.query.filter_by(staff_number=value).first()
    if staff and staff.user:
        return staff.user

    if "@" in value:
        return User.query.filter_by(email=value.lower()).first()

    return None


def institutional_login_id_for(user: User) -> str:
    """Return the ID students/staff use at login (for tests and docs)."""
    if user.role == "student":
        student = Student.query.filter_by(user_id=user.id).first()
        if student and student.student_id:
            return student.student_id
    elif user.role == "lecturer":
        lecturer = Lecturer.query.filter_by(user_id=user.id).first()
        if lecturer and lecturer.employee_id:
            return lecturer.employee_id
    elif user.role in ("admin", "career_advisor"):
        staff = StaffProfile.query.filter_by(user_id=user.id).first()
        if staff and staff.staff_number:
            return staff.staff_number
    return user.email
