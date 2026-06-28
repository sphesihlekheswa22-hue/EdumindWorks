"""Lower quiz scores for at-risk students so results match failing performance."""
from __future__ import annotations

import random
import sys

sys.path.insert(0, ".")

from app import create_app, db
from app.models import Enrollment, QuizResult, Student
from app.services.risk_service import AT_RISK_THRESHOLD, compute_student_metrics, recalculate_all_risk_scores
from app.utils.percentages import percentage_from_parts


def _target_pct_for_at_risk(passing_score: int) -> float:
    upper = min(52.0, max(33.0, float(passing_score) - 1))
    return round(random.uniform(32.0, upper), 1)


def main() -> int:
    app = create_app()
    with app.app_context():
        updated = 0
        students_checked = 0

        for student in Student.query.all():
            enrollments = Enrollment.query.filter_by(student_id=student.id, status="active").all()
            if not enrollments:
                continue

            at_risk = any(
                compute_student_metrics(student.id, course_id=enrollment.course_id).get("is_at_risk")
                for enrollment in enrollments
            )
            if not at_risk:
                continue

            students_checked += 1
            for result in QuizResult.query.filter_by(student_id=student.id).all():
                if result.percentage <= AT_RISK_THRESHOLD:
                    continue

                quiz = result.quiz
                passing_score = int(quiz.passing_score or 60) if quiz else 60
                target_pct = _target_pct_for_at_risk(passing_score)
                total = float(result.total_points or 100)
                result.score = round(total * target_pct / 100, 1)
                result.percentage = percentage_from_parts(result.score, total)
                result.passed = result.percentage >= passing_score
                updated += 1

        db.session.commit()
        recalculate_all_risk_scores()
        print(f"Adjusted {updated} quiz results across {students_checked} at-risk students.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
