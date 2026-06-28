"""Fix quiz and mark percentages stored above 100 or below 0."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app import create_app, db
from app.models import Mark, QuizResult


def main() -> int:
    app = create_app()
    with app.app_context():
        quiz_fixed = 0
        for result in QuizResult.query.all():
            before = result.percentage
            result.sync_percentage()
            if result.percentage != before:
                quiz_fixed += 1

        mark_fixed = 0
        for mark in Mark.query.all():
            before = mark.percentage
            mark.sync_percentage()
            if mark.percentage != before:
                mark_fixed += 1

        db.session.commit()
        print(f"Fixed {quiz_fixed} quiz results and {mark_fixed} marks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
