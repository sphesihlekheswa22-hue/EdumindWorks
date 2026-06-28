"""Quick diagnostic: real login + route health checks."""
from __future__ import annotations

import re
import sys

sys.path.insert(0, ".")

from app import create_app
from app.models import ChatSession, Lecturer, StaffProfile, Student, User


def csrf(html: bytes) -> str:
    text = html.decode("utf-8", errors="replace")
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text)
    if m:
        return m.group(1)
    m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', text)
    return m.group(1) if m else ""


def login(client, institutional_id: str, password: str) -> int:
    page = client.get("/auth/login")
    resp = client.post(
        "/auth/login",
        data={
            "institutional_id": institutional_id,
            "password": password,
            "remember": "no",
            "csrf_token": csrf(page.data),
        },
        follow_redirects=False,
    )
    return resp.status_code


def main() -> int:
    app = create_app()
    fails: list[str] = []

    with app.test_client() as client:
        with app.app_context():
            student_user = User.query.filter_by(role="student").first()
            admin_user = User.query.filter_by(role="admin").first()
            lecturer_user = User.query.filter_by(role="lecturer").first()
            student = Student.query.filter_by(user_id=student_user.id).first() if student_user else None
            lecturer = Lecturer.query.filter_by(user_id=lecturer_user.id).first() if lecturer_user else None
            staff = StaffProfile.query.filter_by(user_id=admin_user.id).first() if admin_user else None

            # Login validation
            if student_user and student:
                email_login = login(client, student_user.email, "student123")
                client.get("/auth/logout")
                id_login = login(client, student.student_id, "student123")
                dash = client.get("/dashboard", follow_redirects=True)
                if id_login not in (302, 303) or dash.status_code != 200:
                    fails.append(
                        f"student login broken (institutional={id_login}, dashboard={dash.status_code})"
                    )
                if email_login not in (302, 303):
                    fails.append(f"student email login broken (status={email_login})")

                student_paths = [
                    "/dashboard",
                    "/courses/",
                    "/ai/chat",
                    "/notifications/",
                ]
                for path in student_paths:
                    r = client.get(path, follow_redirects=True)
                    if r.status_code >= 500:
                        fails.append(f"student GET {path} -> {r.status_code}")

                session = ChatSession.query.filter_by(student_id=student.id).first()
                if session:
                    r = client.get(f"/ai/chat/{session.id}", follow_redirects=True)
                    if r.status_code >= 500:
                        fails.append(f"student GET /ai/chat/{session.id} -> {r.status_code}")

                client.get("/auth/logout")

            if admin_user and staff:
                login(client, staff.staff_number, "admin123")
                admin_paths = [
                    "/admin/users",
                    f"/admin/users/{student_user.id}/view",
                    f"/admin/users/{student_user.id}/edit",
                    "/admin/courses",
                    "/admin/enrollments",
                ]
                for path in admin_paths:
                    r = client.get(path, follow_redirects=True)
                    if r.status_code >= 500:
                        fails.append(f"admin GET {path} -> {r.status_code}")
                client.get("/auth/logout")

            if lecturer_user and lecturer:
                login(client, lecturer.employee_id, "lecturer123")
                r = client.get("/dashboard", follow_redirects=True)
                if r.status_code >= 500:
                    fails.append(f"lecturer dashboard -> {r.status_code}")
                client.get("/auth/logout")

    if fails:
        print("DIAGNOSTIC FAILURES:")
        for item in fails:
            print(" -", item)
        return 1

    print("diagnose_app: OK (login + key routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
