"""Lower quiz scores for at-risk students so results match failing performance."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app import create_app
from app.services.academic_service import rebalance_at_risk_quiz_scores
from app.services.risk_service import recalculate_all_risk_scores


def main() -> int:
    app = create_app()
    with app.app_context():
        stats = rebalance_at_risk_quiz_scores()
        recalculate_all_risk_scores()
        print(
            f"Adjusted {stats['quiz_results_updated']} quiz results "
            f"across {stats['students_adjusted']} struggling students."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
