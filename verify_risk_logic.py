"""Verify at-risk students align with low academic performance."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app import create_app
from app.models import Enrollment
from app.services.risk_service import compute_student_metrics, list_at_risk_students


def main() -> int:
    app = create_app()
    with app.app_context():
        at_risk = list_at_risk_students()
        print(f"At-risk students: {len(at_risk)}")
        for row in at_risk:
            print(
                f"  {row['name']}: performance={row['performance_score']} "
                f"marks={row['avg_score']} quiz={row['quiz_score']} "
                f"attendance={row['attendance']} level={row['risk_level']}"
            )

        wrongly_flagged = []
        for enrollment in Enrollment.query.filter_by(status="active").all():
            metrics = compute_student_metrics(
                enrollment.student_id,
                course_id=enrollment.course_id,
            )
            if not metrics["has_data"]:
                continue
            if metrics["overall_score"] >= 70 and metrics["is_at_risk"]:
                wrongly_flagged.append(
                    (enrollment.student_id, metrics["overall_score"])
                )

        if wrongly_flagged:
            print("FAIL: high performers wrongly flagged:", wrongly_flagged)
            return 1

        print("OK: no high performers flagged as at-risk")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
