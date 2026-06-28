#!/usr/bin/env python3
"""
Full automated click-through: every GET route × roles (Flask test client).

Run from project root (DB must exist, seed_data recommended):
  python full_clickthrough.py

Exit 1 if any URL returns 404/500 for all tried roles, or BuildError.
This approximates a manual browser pass without Playwright.
"""
from __future__ import annotations

import re
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, ".")

from app import create_app, db  # noqa: E402
from app.models import (  # noqa: E402
    Assignment,
    AssignmentAttachment,
    AssignmentSubmission,
    ChatSession,
    Course,
    CourseMaterial,
    CVReview,
    Enrollment,
    InterventionMessage,
    Lecturer,
    Module,
    Notification,
    Quiz,
    QuizResult,
    Student,
    StudyPlan,
    StudyPlanItem,
    User,
)
from app.utils.login_helpers import institutional_login_id_for  # noqa: E402

SKIP_ENDPOINTS_PREFIX = (
    "auth.reset_password",
    "auth.verify_email",
)

PASSWORDS = {
    "student": "student123",
    "lecturer": "lecturer123",
    "admin": "admin123",
    "career_advisor": "career123",
}


def _csrf(html: bytes) -> Optional[str]:
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', html)
    if m:
        return m.group(1).decode()
    m = re.search(rb'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1).decode() if m else None


def login(client, user: User) -> None:
    pw = PASSWORDS.get(user.role, "student123")
    r = client.get("/auth/login")
    tok = _csrf(r.data) or ""
    login_id = institutional_login_id_for(user)
    client.post(
        "/auth/login",
        data={
            "institutional_id": login_id,
            "password": pw,
            "remember": "no",
            "csrf_token": tok,
        },
        follow_redirects=True,
    )


def logout(client) -> None:
    client.get("/auth/logout", follow_redirects=True)


class DbIds:
    """Resolve url_for() argument names from the current database."""

    def __init__(self) -> None:
        self.user = User.query.first()
        self.student = Student.query.first()
        self.lecturer = Lecturer.query.first()
        self.course = Course.query.first()
        self.module = Module.query.first()
        self.enrollment = Enrollment.query.first()
        self.quiz = Quiz.query.first()
        self.assignment = Assignment.query.first()
        self.result = QuizResult.query.first()
        self.submission = AssignmentSubmission.query.first()
        self.attachment = AssignmentAttachment.query.first()
        self.material = CourseMaterial.query.first()
        self.plan = StudyPlan.query.first()
        self.item = StudyPlanItem.query.first()
        self.session = ChatSession.query.first()
        self.review = CVReview.query.first()
        self.intervention = InterventionMessage.query.first()
        self.notification = Notification.query.first()

    def get(self, name: str) -> Any:
        m = {
            "user_id": getattr(self.user, "id", None),
            "student_id": getattr(self.student, "id", None),
            "lecturer_id": getattr(self.lecturer, "id", None),
            "course_id": getattr(self.course, "id", None),
            "module_id": getattr(self.module, "id", None),
            "enrollment_id": getattr(self.enrollment, "id", None),
            "quiz_id": getattr(self.quiz, "id", None),
            "assignment_id": getattr(self.assignment, "id", None),
            "result_id": getattr(self.result, "id", None),
            "submission_id": getattr(self.submission, "id", None),
            "attachment_id": getattr(self.attachment, "id", None),
            "material_id": getattr(self.material, "id", None),
            "plan_id": getattr(self.plan, "id", None),
            "item_id": getattr(self.item, "id", None),
            "session_id": getattr(self.session, "id", None),
            "review_id": getattr(self.review, "id", None),
            "intervention_id": getattr(self.intervention, "id", None),
            "notification_id": getattr(self.notification, "id", None),
            "token": None,
        }
        return m.get(name)


def roles_for_endpoint(endpoint: str) -> List[str]:
    """Order: try these roles when GETting."""
    if endpoint.startswith("admin."):
        return ["admin"]
    if endpoint.startswith("career.advisor") or endpoint == "career.ai_review_cv":
        return ["career_advisor", "admin"]
    if endpoint in (
        "auth.login",
        "auth.register",
        "auth.forgot_password",
        "auth.verify_registration_otp",
        "auth.verify_reset_otp",
        "auth.resend_verification",
    ):
        return ["anon"]
    if endpoint.startswith("main.") and endpoint in (
        "main.index",
        "main.about",
        "main.help",
    ):
        return ["anon", "student", "lecturer", "admin"]
    if endpoint.startswith("auth."):
        return ["student", "lecturer", "admin"]
    return ["student", "lecturer", "admin", "career_advisor"]


def main() -> int:
    app = create_app("development")
    failures: List[str] = []
    skipped: List[str] = []
    ok_count = 0

    with app.app_context():
        ids = DbIds()
        users_by_role: Dict[str, Optional[User]] = {
            "anon": None,
            "student": User.query.filter_by(role="student").first(),
            "lecturer": User.query.filter_by(role="lecturer").first(),
            "admin": User.query.filter_by(role="admin").first(),
            "career_advisor": User.query.filter_by(role="career_advisor").first(),
        }

        from flask import url_for

        rules = sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint))

        with app.test_client() as client:
            for rule in rules:
                if rule.endpoint == "static" or (rule.endpoint and "static" in rule.endpoint):
                    continue
                if "GET" not in rule.methods:
                    continue

                ep = rule.endpoint or ""
                if any(ep.startswith(p) for p in SKIP_ENDPOINTS_PREFIX):
                    skipped.append(f"{ep} (token required)")
                    continue

                kw: Dict[str, Any] = {}
                missing: List[str] = []
                for arg in rule.arguments:
                    v = ids.get(arg)
                    if v is None:
                        missing.append(arg)
                    else:
                        kw[arg] = v
                if missing:
                    skipped.append(f"{ep} missing DB: {missing}")
                    continue

                try:
                    with app.test_request_context():
                        path = url_for(ep, **kw)
                except Exception as e:
                    failures.append(f"BUILD {ep} {kw!r} -> {e}")
                    continue

                role_order = roles_for_endpoint(ep)

                best: Optional[Tuple[str, int]] = None
                for role in role_order:
                    u = users_by_role.get(role)
                    if role != "anon" and u is None:
                        continue
                    if role == "anon":
                        logout(client)
                    else:
                        login(client, u)  # type: ignore[arg-type]

                    resp = client.get(path, follow_redirects=False)
                    code = resp.status_code

                    # Accept: OK, redirect, forbidden (exists), method issues
                    if code in (200, 301, 302, 303, 307, 308, 401, 403):
                        best = (role, code)
                        break
                    if code == 404:
                        continue
                    if code >= 500:
                        best = (role, code)
                        break
                    best = (role, code)
                    break

                logout(client)

                if best is None:
                    failures.append(f"{ep} {path} -> no role succeeded (404?)")
                    continue

                role, code = best
                if code >= 500:
                    failures.append(f"{ep} {path} as {role} -> {code}")
                elif code == 404:
                    failures.append(f"{ep} {path} as {role} -> 404")
                else:
                    ok_count += 1

    print("=== Full click-through (GET routes) ===")
    print(f"OK (reachable): {ok_count}")
    print(f"Skipped (no seed row / token routes): {len(skipped)}")
    if skipped and len(skipped) <= 40:
        for s in skipped:
            print(f"  SKIP {s}")
    elif skipped:
        for s in skipped[:25]:
            print(f"  SKIP {s}")
        print(f"  ... and {len(skipped) - 25} more")

    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1

    print("\nNo 404/500/build failures on covered routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
