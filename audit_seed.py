"""
Audit seeded database for:
- empty tables (for all SQLAlchemy models in app.models)
- NULLs in non-nullable columns

Run:
  python audit_seed.py
"""
import sys

from app import create_app, db
from sqlalchemy import func
from sqlalchemy.inspection import inspect

from app import models as models_pkg


def iter_model_classes():
    for name in getattr(models_pkg, "__all__", []):
        cls = getattr(models_pkg, name, None)
        if cls is None:
            continue
        # Only mapped classes
        if hasattr(cls, "__table__"):
            yield cls


def main() -> int:
    app = create_app("development")
    errors = []

    with app.app_context():
        for model in iter_model_classes():
            mapper = inspect(model)
            table_name = mapper.local_table.name

            # Skip association objects without their own table? (none in this project)
            try:
                total = db.session.query(func.count()).select_from(model).scalar() or 0
            except Exception as e:
                errors.append(f"{table_name}: failed to count rows: {e}")
                continue

            if total == 0:
                errors.append(f"{table_name}: EMPTY table")

            # Check NULLs for non-nullable columns (ignore primary key autoincrement)
            for col in mapper.columns:
                if col.primary_key:
                    continue
                if getattr(col, "nullable", True):
                    continue

                try:
                    nulls = (
                        db.session.query(func.count())
                        .select_from(model)
                        .filter(col.is_(None))
                        .scalar()
                        or 0
                    )
                except Exception as e:
                    errors.append(f"{table_name}.{col.key}: failed NULL check: {e}")
                    continue

                if nulls:
                    errors.append(f"{table_name}.{col.key}: {nulls} NULL(s) in non-nullable column")

    if errors:
        print("SEED AUDIT FAILED")
        for e in errors:
            print("-", e)
        return 1

    print("SEED AUDIT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

