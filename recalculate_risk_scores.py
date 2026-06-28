"""Rebuild risk scores and rebalance quiz marks for struggling students."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app import create_app
from app.services.academic_service import rebalance_at_risk_quiz_scores
from app.services.risk_service import count_at_risk_students, recalculate_all_risk_scores


def main() -> int:
    app = create_app()
    with app.app_context():
        quiz_stats = rebalance_at_risk_quiz_scores()
        risk_rows = recalculate_all_risk_scores()
        at_risk = count_at_risk_students()
        print(f"Rebalanced {quiz_stats['quiz_results_updated']} quiz results for {quiz_stats['students_adjusted']} students.")
        print(f"Updated {risk_rows} risk score records.")
        print(f"Students currently at risk: {at_risk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
