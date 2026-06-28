"""Rebuild risk_scores from live attendance, quiz, and mark data."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app import create_app
from app.services.risk_service import count_at_risk_students, recalculate_all_risk_scores


def main() -> int:
    app = create_app()
    with app.app_context():
        updated = recalculate_all_risk_scores()
        at_risk = count_at_risk_students()
        print(f"Updated {updated} risk score records.")
        print(f"Students currently at risk: {at_risk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
