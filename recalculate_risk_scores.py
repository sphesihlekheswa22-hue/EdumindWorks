"""Rebuild risk scores and optionally rebalance quiz marks for struggling students."""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app import create_app
from app.services.academic_service import rebalance_at_risk_quiz_scores
from app.services.risk_service import count_at_risk_students, recalculate_all_risk_scores
from backfill_enrolled_assessments import backfill_enrolled_assessments


def main() -> int:
    parser = argparse.ArgumentParser(description="Recalculate risk scores for all students.")
    parser.add_argument(
        "--no-rebalance",
        action="store_true",
        help="Skip lowering quiz scores for at-risk students (recommended for production).",
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        help="Skip inventing missing marks/quiz results for enrollments.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if not args.no_backfill:
            backfill_stats = backfill_enrolled_assessments()
            print(
                f"Backfilled {backfill_stats['marks_added']} marks and "
                f"{backfill_stats['quiz_results_added']} quiz results "
                f"for {backfill_stats['students_updated']} students."
            )
        else:
            print("Skipped assessment backfill.")

        if not args.no_rebalance:
            quiz_stats = rebalance_at_risk_quiz_scores()
            print(
                f"Rebalanced {quiz_stats['quiz_results_updated']} quiz results "
                f"for {quiz_stats['students_adjusted']} students."
            )
        else:
            print("Skipped quiz score rebalance.")

        risk_rows = recalculate_all_risk_scores()
        at_risk = count_at_risk_students()
        print(f"Updated {risk_rows} risk score records.")
        print(f"Students currently at risk: {at_risk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
