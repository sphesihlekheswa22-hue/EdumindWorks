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


def _assert(condition: bool, msg: str, errors: list[str]) -> None:
    if not condition:
        errors.append(msg)


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

        # Relationship sanity checks (institutional LMS expectations)
        from app.models import Student, Enrollment, Lecturer, StaffProfile, User
        from app.models.lecturer import LecturerModule

        _assert(Student.query.count() > 0, "students: expected at least 1 student", errors)
        _assert(Enrollment.query.count() > 0, "enrollments: expected at least 1 enrollment", errors)
        _assert(Lecturer.query.count() > 0, "lecturers: expected at least 1 lecturer", errors)
        _assert(LecturerModule.query.count() > 0, "lecturer_modules: expected at least 1 lecturer-module assignment", errors)

        # Admin/career advisor must have staff profiles for staff-number login
        admin_count = User.query.filter_by(role="admin").count()
        career_count = User.query.filter_by(role="career_advisor").count()
        staff_profiles = StaffProfile.query.count()
        _assert(admin_count > 0, "users: expected at least 1 admin user", errors)
        _assert(career_count > 0, "users: expected at least 1 career_advisor user", errors)
        _assert(staff_profiles >= (admin_count + career_count), "staff_profiles: expected staff profiles for all non-lecturer staff", errors)

    if errors:
        print("SEED AUDIT FAILED")
        for e in errors:
            print("-", e)
        return 1

    print("SEED AUDIT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

