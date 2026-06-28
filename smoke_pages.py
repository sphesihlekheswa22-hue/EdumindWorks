"""Quick HTTP smoke checks for demo / lecture presentation."""
from __future__ import annotations

import re
import sys

sys.path.insert(0, ".")
from app import create_app, db  # noqa: E402
from app.models import User, Lecturer, LecturerModule  # noqa: E402
from app.utils.login_helpers import institutional_login_id_for  # noqa: E402


def _csrf(html: bytes) -> str | None:
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', html)
    if m:
        return m.group(1).decode()
    m = re.search(rb'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1).decode() if m else None


def main() -> int:
    app = create_app("development")
    fails: list[str] = []

    with app.test_client() as client:
        paths_anon = ["/", "/auth/login"]
        for p in paths_anon:
            r = client.get(p)
            if r.status_code != 200:
                fails.append(f"anon GET {p} -> {r.status_code}")

        # Student session
        with app.app_context():
            su = User.query.filter_by(role="student").first()
            lu = User.query.filter_by(role="lecturer").first()
            au = User.query.filter_by(role="admin").first()

        for label, user, pw in (
            ("student", su, "student123"),
            ("lecturer", lu, "lecturer123"),
            ("admin", au, "admin123"),
        ):
            if not user:
                continue
            with app.app_context():
                login_id = institutional_login_id_for(user)
            login_page = client.get("/auth/login")
            tok = _csrf(login_page.data)
            client.post(
                "/auth/login",
                data={
                    "institutional_id": login_id,
                    "password": pw,
                    "remember": "no",
                    "csrf_token": tok or "",
                },
                follow_redirects=True,
            )

            role_paths: list[str] = []
            if label == "student":
                role_paths = [
                    "/dashboard",
                    "/courses/",
                    "/quizzes/",
                    "/assignments/",
                    "/materials/",
                    "/notifications/",
                    "/ai/chat",
                ]
            elif label == "lecturer":
                with app.app_context():
                    lec = Lecturer.query.filter_by(user_id=user.id).first()
                    lm = (
                        LecturerModule.query.filter_by(lecturer_id=lec.id).first()
                        if lec
                        else None
                    )
                    mid = lm.module_id if lm else None
                role_paths = ["/dashboard", "/courses/modules/content-management"]
                if mid:
                    role_paths += [
                        f"/materials/module/{mid}",
                        f"/quizzes/module/{mid}",
                        f"/attendance/module/{mid}",
                        f"/marks/module/{mid}",
                        f"/assignments/module/{mid}",
                    ]
            elif label == "admin":
                role_paths = [
                    "/admin/",
                    "/admin/courses",
                    "/admin/users",
                    "/admin/enrollments",
                    "/analytics/admin",
                ]

            for p in role_paths:
                r = client.get(p, follow_redirects=True)
                if r.status_code >= 400:
                    fails.append(f"{label} GET {p} -> {r.status_code}")

            client.get("/auth/logout")

    if fails:
        print("FAILURES:")
        for f in fails:
            print(" ", f)
        return 1
    print("smoke_pages: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
