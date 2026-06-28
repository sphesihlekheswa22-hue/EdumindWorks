from typing import List, Dict, Optional, Union
from flask import (
    Blueprint, render_template, redirect, url_for, 
    flash, request, abort, current_app, Response
)
from flask_login import login_required, current_user
from datetime import datetime
from http import HTTPStatus

from app import db
from app.services.academic_service import build_student_academic_summary
from app.utils.percentages import clamp_pct
from app.utils.app_time import app_now
from app.utils.percentages import percentage_from_parts
from app.models import Mark, Course, Student, Enrollment, Lecturer, User, Module
from app.models.lecturer import LecturerModule
from app.utils.access_control import (
    require_module_access,
    require_lecturer_assigned_to_module,
    can_edit_module_content,
)

marks_bp = Blueprint('marks', __name__, url_prefix='/marks')


def _csv_response(filename: str, csv_text: str) -> Response:
    # Excel-friendly UTF-8 with BOM.
    bom = "\ufeff"
    resp = Response(bom + csv_text, mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


def check_mark_permission(module_id: int, require_edit: bool = False) -> tuple:
    """Verify access to marks for module."""
    ctx = require_module_access(module_id)
    module = ctx.module
    course = ctx.course
    
    if current_user.role == 'admin':
        return module, course, None, True
    
    if current_user.role == 'lecturer':
        # Must be assigned to this module
        if not can_edit_module_content(module_id):
            abort(HTTPStatus.FORBIDDEN, 'Not assigned to this module')
        return module, course, None, True
    
    if current_user.role == 'student':
        if require_edit:
            abort(HTTPStatus.FORBIDDEN)
        
        if not ctx.has_access:
            abort(HTTPStatus.FORBIDDEN, 'Not enrolled in course')
        
        return module, course, ctx.student, False
    
    abort(HTTPStatus.FORBIDDEN)


@marks_bp.route('/')
@login_required
def index():
    """Redirect to appropriate page based on user role."""
    if current_user.role == 'student':
        return redirect(url_for('courses.index'))
    elif current_user.role == 'lecturer':
        return redirect(url_for('main.dashboard'))
    else:
        return redirect(url_for('main.dashboard'))


@marks_bp.route('/course/<int:course_id>')
@login_required
def course_marks_redirect(course_id: int):
    """Redirect to first module's marks or show appropriate message."""
    course = Course.query.get_or_404(course_id)
    
    # Prefer a module the lecturer is assigned to (avoid 403 redirects)
    first_module = None
    if current_user.role == "lecturer":
        lecturer = Lecturer.query.filter_by(user_id=current_user.id).first()
        if lecturer:
            first_module = (
                Module.query.join(LecturerModule, LecturerModule.module_id == Module.id)
                .filter(LecturerModule.lecturer_id == lecturer.id, Module.course_id == course_id)
                .order_by(Module.order)
                .first()
            )

    # Fallback: first module in course
    if first_module is None:
        first_module = Module.query.filter_by(course_id=course_id).order_by(Module.order).first()
    
    if not first_module:
        flash('No modules available for this course yet.', 'info')
        return redirect(url_for('courses.detail', course_id=course_id))
    
    return redirect(url_for('marks.module_marks', module_id=first_module.id))


@marks_bp.route('/module/<int:module_id>')
@login_required
def module_marks(module_id: int) -> str:
    """View marks for a module."""
    module, course, student, can_edit = check_mark_permission(module_id)
    
    if student:
        # Student view - own marks only
        current_app.logger.info(f'Student marks view: student_id={student.id}, module_id={module_id}')
        marks: List[Mark] = Mark.query.filter_by(
            student_id=student.id,
            module_id=module_id
        ).order_by(Mark.marked_at.desc()).all()
        
        current_app.logger.info(f'Found {len(marks)} marks for student')
        
        # Calculate statistics
        overall: Dict = {
            'average': 0.0,
            'highest': 0.0,
            'lowest': 0.0,
            'count': len(marks)
        }
        
        if marks:
            percentages: List[float] = [m.percentage for m in marks]
            overall['average'] = sum(percentages) / len(percentages)
            overall['highest'] = max(percentages)
            overall['lowest'] = min(percentages)
            current_app.logger.info(f'Calculated stats: avg={overall["average"]}, highest={overall["highest"]}, lowest={overall["lowest"]}')
        
        # Grade distribution
        grade_counts: Dict[str, int] = {}
        for mark in marks:
            grade: str = mark.grade or 'N/A'
            grade_counts[grade] = grade_counts.get(grade, 0) + 1
        
        # Calculate overall percentage and grade for template
        overall_percentage: float = overall['average']
        overall_grade: str = 'N/A'
        if marks:
            # Use the calculate_grade method to get letter grade from average percentage
            temp_mark = Mark(percentage=overall_percentage, total_marks=100, mark=overall_percentage)
            overall_grade = temp_mark.calculate_grade()
            current_app.logger.info(f'Overall grade: {overall_grade}')
        
        # Get class rank - count how many students have higher average
        enrollments = Enrollment.query.filter_by(
            course_id=course.id,
            status='active'
        ).all()

        student_ids = [e.student_id for e in enrollments]

        total_students: int = len(student_ids)

        class_rank: int = 1
        if marks and overall_percentage > 0:
            # Get all students in this course with their averages for this module
            for sid in student_ids:
                other_marks = Mark.query.filter_by(
                    module_id=module_id,
                    student_id=sid
                ).all()

                if other_marks:
                    other_avg = sum(m.percentage for m in other_marks) / len(other_marks)
                    if other_avg > overall_percentage:
                        class_rank += 1
        
        current_app.logger.info(f'Rendering template with: class_rank={class_rank}, total_students={total_students}')
        
        return render_template(
            'marks_student.html',
            course=course,
            module=module,
            marks=marks,
            overall=overall,
            overall_percentage=overall_percentage,
            overall_grade=overall_grade,
            grade_counts=grade_counts,
            class_rank=class_rank,
            total_students=total_students
        )
    
    # Instructor view - all students in the course
    enrollments: List[Enrollment] = Enrollment.query.filter_by(
        course_id=course.id,
        status='active'
    ).all()
    
    student_ids: List[int] = [e.student_id for e in enrollments]
    
    # Get all marks for these students in this module
    all_marks: List[Mark] = Mark.query.filter(
        Mark.module_id == module_id,
        Mark.student_id.in_(student_ids)
    ).order_by(Mark.marked_at.desc()).all()
    
    # Organize by student
    student_marks: Dict[int, Dict] = {}
    
    for e in enrollments:
        student_marks[e.student_id] = {
            'student': e.student,
            'marks': [],
            'total': 0.0,
            'count': 0,
            'average': 0.0
        }
    
    for mark in all_marks:
        if mark.student_id in student_marks:
            student_marks[mark.student_id]['marks'].append(mark)
            student_marks[mark.student_id]['total'] += mark.percentage
            student_marks[mark.student_id]['count'] += 1
    
    # Calculate averages
    for sid, data in student_marks.items():
        if data['count'] > 0:
            data['average'] = data['total'] / data['count']
    
    # Assessment types for filtering
    assessment_types: List[str] = db.session.query(
        Mark.assessment_type
    ).filter_by(module_id=module_id).distinct().all()
    
    return render_template(
        'marks_course.html',
        course=course,
        module=module,
        student_marks=student_marks,
        marks=all_marks,
        assessment_types=[t[0] for t in assessment_types if t[0]],
        can_edit=can_edit
    )


@marks_bp.route('/module/<int:module_id>/enter', methods=['GET', 'POST'])
@login_required
def enter_marks(module_id: int) -> Union[str, redirect]:
    """Enter marks for assessment."""
    module, course, _, can_edit = check_mark_permission(module_id, require_edit=True)

    if not can_edit:
        abort(HTTPStatus.FORBIDDEN)

    if request.method == 'POST':
        try:
            assessment_type: str = request.form.get('assessment_type', '').strip()
            assessment_name: str = request.form.get('assessment_name', '').strip()
            total_marks: float = float(request.form.get('total_marks', 100))

            if not assessment_type or not assessment_name:
                flash('Assessment type and name are required.', 'danger')
                return redirect(request.url)

            if total_marks <= 0:
                flash('Total marks must be greater than 0.', 'danger')
                return redirect(request.url)

            enrollments: List[Enrollment] = Enrollment.query.filter_by(
                course_id=course.id,
                status='active'
            ).all()

            marks_entered: int = 0

            for enrollment in enrollments:
                student_id: int = enrollment.student_id
                mark_value_str: Optional[str] = request.form.get(f'mark_{student_id}')

                if not mark_value_str or not mark_value_str.strip():
                    continue

                try:
                    mark_value: float = float(mark_value_str)
                except ValueError:
                    flash(f'Invalid mark for student {enrollment.student.user.full_name}', 'warning')
                    continue

                if mark_value < 0 or mark_value > total_marks:
                    flash(
                        f'Mark for {enrollment.student.user.full_name} must be between 0 and {total_marks}',
                        'warning'
                    )
                    continue

                percentage: float = percentage_from_parts(mark_value, total_marks)

                existing: Optional[Mark] = Mark.query.filter_by(
                    module_id=module_id,
                    student_id=student_id,
                    assessment_type=assessment_type,
                    assessment_name=assessment_name
                ).first()

                if existing:
                    existing.mark = mark_value
                    existing.total_marks = total_marks
                    existing.percentage = percentage
                    existing.grade = existing.calculate_grade()
                    existing.feedback = request.form.get(f'feedback_{student_id}', '').strip()
                    existing.marked_at = app_now()
                else:
                    new_mark = Mark(
                        module_id=module_id,
                        student_id=student_id,
                        assessment_type=assessment_type,
                        assessment_name=assessment_name,
                        mark=mark_value,
                        total_marks=total_marks,
                        percentage=percentage,
                        grade='',
                        recorded_by=current_user.id,
                        feedback=request.form.get(f'feedback_{student_id}', '').strip()
                    )
                    new_mark.grade = new_mark.calculate_grade()
                    db.session.add(new_mark)

                marks_entered += 1

            db.session.commit()

            if marks_entered > 0:
                flash(f'Successfully entered/updated {marks_entered} marks.', 'success')
            else:
                flash('No marks were entered.', 'warning')

            return redirect(url_for('marks.module_marks', module_id=module_id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Mark entry error: {str(e)}')
            flash('Error saving marks. Please try again.', 'danger')

    results = db.session.query(
        Enrollment.id,
        Enrollment.student_id,
        Enrollment.status,
        Student.user_id,
        User.first_name,
        User.last_name,
        User.email
    ).join(
        Student, Enrollment.student_id == Student.id
    ).join(
        User, Student.user_id == User.id
    ).filter(
        Enrollment.course_id == course.id,
        Enrollment.status == 'active'
    ).order_by(User.last_name).all()

    assessment_types: List[str] = db.session.query(
        Mark.assessment_type
    ).filter_by(module_id=module_id).distinct().all()

    return render_template(
        'lecturer/marks_enter.html',
        course=course,
        module=module,
        students=results,
        assessment_types=[t[0] for t in assessment_types if t[0]]
    )


@marks_bp.route('/module/<int:module_id>/export.csv')
@login_required
def export_marks_csv(module_id: int) -> Response:
    """Export module marks as CSV (lecturer/admin only)."""
    import csv
    import io

    module, course, _, can_edit = check_mark_permission(module_id, require_edit=False)
    if not can_edit:
        abort(HTTPStatus.FORBIDDEN)

    marks: List[Mark] = (
        Mark.query.filter_by(module_id=module_id)
        .order_by(Mark.student_id.asc(), Mark.marked_at.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "mark_id",
        "course_code",
        "course_name",
        "module_id",
        "module_title",
        "student_id",
        "student_number",
        "student_name",
        "assessment_type",
        "assessment_name",
        "mark",
        "total_marks",
        "percentage",
        "grade",
        "feedback",
        "recorded_by",
        "marked_at",
    ])

    for m in marks:
        student_number = ""
        student_name = ""
        if m.student and getattr(m.student, "user", None):
            student_number = getattr(m.student, "student_id", "") or str(m.student.id)
            student_name = m.student.user.full_name

        recorder_name = m.recorder.full_name if getattr(m, "recorder", None) else ""
        writer.writerow([
            m.id,
            course.code if course else "",
            course.name if course else "",
            module.id if module else module_id,
            module.title if module else "",
            m.student_id,
            student_number,
            student_name,
            m.assessment_type,
            m.assessment_name,
            m.mark,
            m.total_marks,
            m.percentage,
            m.grade or (m.calculate_grade() if hasattr(m, "calculate_grade") else ""),
            (m.feedback or "").replace("\r", " ").replace("\n", " ").strip(),
            recorder_name,
            m.marked_at.isoformat() if m.marked_at else "",
        ])

    date_str = app_now().strftime("%Y-%m-%d")
    safe_code = (course.code if course else f"course-{course.id}" if course else "course").replace(" ", "_")
    safe_module = (module.title if module else f"module-{module_id}").replace(" ", "_")[:40]
    filename = f"marks-{safe_code}-{safe_module}-{date_str}.csv"
    return _csv_response(filename, output.getvalue())


@marks_bp.route('/student')
@login_required
def my_marks() -> str:
    """Student's complete marks summary."""
    if current_user.role != 'student':
        abort(HTTPStatus.FORBIDDEN)
    
    student: Student = Student.query.filter_by(
        user_id=current_user.id
    ).first_or_404()

    academic = build_student_academic_summary(student)
    enrolled_course_ids = {row["course"].id for row in academic["course_summaries"]}

    marks: List[Mark] = Mark.query.filter_by(
        student_id=student.id
    ).order_by(Mark.marked_at.desc()).all()
    marks = [
        mark for mark in marks
        if mark.module and mark.module.course_id in enrolled_course_ids
    ]

    courses_data: List[Dict] = []
    for row in academic["course_summaries"]:
        course = row["course"]
        course_marks = [
            mark for mark in marks
            if mark.module and mark.module.course_id == course.id
        ]
        courses_data.append({
            'course': course,
            'marks': course_marks,
            'average': row["average"] or 0,
            'highest': max((m.percentage for m in course_marks), default=0),
            'lowest': min((m.percentage for m in course_marks), default=0),
        })

    recent_marks: List[Mark] = marks[:5]

    return render_template(
        'marks_summary.html',
        marks=marks,
        courses=courses_data,
        gpa=academic["overall_percentage"],
        gpa_4=academic["gpa_4"],
        recent_marks=recent_marks,
        total_modules=len(academic["module_statuses"]),
        current_semester=academic["current_semester"],
        primary_course=academic["primary_course"],
        primary_course_name=academic["primary_course_name"],
        primary_course_code=academic["primary_course_code"],
        module_statuses=academic["module_statuses"],
        passing_modules=academic["passing_modules"],
        failing_modules=academic["failing_modules"],
        is_at_risk=academic["is_at_risk"],
        academic=academic,
    )


@marks_bp.route('/course/<int:course_id>/enter', methods=['GET', 'POST'])
@login_required
def enter_marks_course_legacy(course_id: int) -> redirect:
    """Redirect old course-based marks entry URLs to first module."""
    # Prefer a module assigned to the current lecturer (avoids 403 on entry)
    module = None
    if current_user.role == 'lecturer':
        lecturer = Lecturer.query.filter_by(user_id=current_user.id).first()
        if lecturer:
            module = (
                Module.query.join(LecturerModule, LecturerModule.module_id == Module.id)
                .filter(LecturerModule.lecturer_id == lecturer.id, Module.course_id == course_id)
                .order_by(Module.order)
                .first()
            )

    # Fallback: first module in course
    if module is None:
        module = Module.query.filter_by(course_id=course_id).order_by(Module.order).first()
    if module:
        return redirect(url_for('marks.enter_marks', module_id=module.id))
    
    flash('No modules found in this course.', 'warning')
    return redirect(url_for('courses.detail', course_id=course_id))