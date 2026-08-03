from typing import List, Dict, Optional, Union
from flask import (
    Blueprint, render_template, redirect, url_for, 
    flash, request, abort, current_app, jsonify, Response
)
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from http import HTTPStatus

from app import db
from app.utils.app_time import app_now
from app.models import Attendance, Course, Student, Enrollment, Lecturer, User, Module
from app.models.lecturer import LecturerModule
from app.utils.access_control import (
    require_module_access,
    require_lecturer_assigned_to_module,
    can_edit_module_content,
)

attendance_bp = Blueprint('attendance', __name__, url_prefix='/attendance')


def _csv_response(filename: str, csv_text: str) -> Response:
    # Excel-friendly UTF-8 with BOM.
    bom = "\ufeff"
    resp = Response(bom + csv_text, mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


def check_attendance_permission(module_id: int, require_record: bool = False) -> tuple:
    """Verify access to attendance records."""
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
        if require_record:
            abort(HTTPStatus.FORBIDDEN)
        
        if not ctx.has_access:
            abort(HTTPStatus.FORBIDDEN, 'Not enrolled')
        
        return module, course, ctx.student, False
    
    abort(HTTPStatus.FORBIDDEN)


@attendance_bp.route('/')
@login_required
def index():
    """Redirect to appropriate page based on user role."""
    if current_user.role == 'student':
        return redirect(url_for('courses.index'))
    elif current_user.role == 'lecturer':
        return redirect(url_for('main.dashboard'))
    else:
        return redirect(url_for('main.dashboard'))


@attendance_bp.route('/course/<int:course_id>')
@login_required
def course_attendance_redirect(course_id: int):
    """Redirect to first module's attendance or show appropriate message."""
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
    
    return redirect(url_for('attendance.module_attendance', module_id=first_module.id))


@attendance_bp.route('/module/<int:module_id>')
@login_required
def module_attendance(module_id: int) -> str:
    """View attendance for a module."""
    module, course, student, can_record = check_attendance_permission(module_id)
    
    if student:
        # Student personal view
        records: List[Attendance] = Attendance.query.filter_by(
            student_id=student.id,
            module_id=module_id
        ).order_by(Attendance.date.desc()).all()
        
        # Calculate stats
        stats: Dict = {
            'total': len(records),
            'present': sum(1 for r in records if r.status == 'present'),
            'absent': sum(1 for r in records if r.status == 'absent'),
            'excused': sum(1 for r in records if r.status == 'excused'),
            'late': sum(1 for r in records if r.status == 'late')
        }
        
        stats['rate'] = (
            (stats['present'] / stats['total'] * 100) if stats['total'] > 0 else 0
        )
        
        return render_template(
            'attendance_student.html',
            course=course,
            module=module,
            records=records,
            stats=stats
        )
    
    # Instructor view
    enrollments: List[Enrollment] = Enrollment.query.filter_by(
        course_id=course.id,
        status='active'
    ).join(Student).join(User).order_by(User.last_name).all()
    
    students: List[Student] = [e.student for e in enrollments]
    
    # Get recent attendance dates (last 30 days)
    recent_dates: List[date] = db.session.query(
        Attendance.date
    ).filter_by(module_id=module_id).distinct().order_by(
        Attendance.date.desc()
    ).limit(30).all()
    
    recent_dates = [d[0] for d in recent_dates]
    
    # Get all records for matrix view
    all_records: List[Attendance] = Attendance.query.filter(
        Attendance.module_id == module_id,
        Attendance.date.in_(recent_dates)
    ).all()
    
    # Organize as matrix: student_id -> date -> status
    matrix: Dict[int, Dict[date, str]] = {}
    for e in enrollments:
        matrix[e.student_id] = {}
    
    for record in all_records:
        if record.student_id in matrix:
            matrix[record.student_id][record.date] = record.status
    
    # Calculate rates per student
    student_stats: Dict[int, Dict] = {}
    for e in enrollments:
        sid: int = e.student_id
        student_records: List[Attendance] = [
            r for r in all_records if r.student_id == sid
        ]
        
        present_count: int = sum(1 for r in student_records if r.status == 'present')
        total_count: int = len(student_records)
        
        student_stats[sid] = {
            'present': present_count,
            'total': total_count,
            'rate': (present_count / total_count * 100) if total_count > 0 else 0
        }
    
    return render_template(
        'attendance_course.html',
        course=course,
        module=module,
        course_modules=Module.query.filter_by(course_id=course.id).order_by(Module.order).all(),
        students=students,
        dates=recent_dates,
        matrix=matrix,
        student_stats=student_stats,
        can_record=can_record
    )


@attendance_bp.route('/module/<int:module_id>/export.csv')
@login_required
def export_attendance_csv(module_id: int) -> Response:
    """Export module attendance matrix as CSV (lecturer/admin only)."""
    import csv
    import io

    module, course, _, can_record = check_attendance_permission(module_id, require_record=False)
    if not can_record:
        abort(HTTPStatus.FORBIDDEN)

    # Export all attendance rows for the module
    records: List[Attendance] = (
        Attendance.query.filter_by(module_id=module_id)
        .order_by(Attendance.date.asc(), Attendance.student_id.asc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "attendance_id",
        "course_code",
        "course_name",
        "module_id",
        "module_title",
        "date",
        "student_id",
        "student_number",
        "student_name",
        "status",
        "notes",
        "recorded_by",
        "created_at",
        "updated_at",
    ])

    for r in records:
        student_number = ""
        student_name = ""
        if r.student and getattr(r.student, "user", None):
            student_number = getattr(r.student, "student_id", "") or str(r.student.id)
            student_name = r.student.user.full_name

        recorder_name = ""
        if getattr(r, "recorder", None):
            recorder_name = r.recorder.full_name

        writer.writerow([
            r.id,
            course.code if course else "",
            course.name if course else "",
            module.id if module else module_id,
            module.title if module else "",
            r.date.isoformat() if r.date else "",
            r.student_id,
            student_number,
            student_name,
            r.status,
            (r.notes or "").replace("\r", " ").replace("\n", " ").strip(),
            recorder_name,
            r.created_at.isoformat() if getattr(r, "created_at", None) else "",
            r.updated_at.isoformat() if getattr(r, "updated_at", None) else "",
        ])

    date_str = app_now().strftime("%Y-%m-%d")
    safe_code = (course.code if course else "course").replace(" ", "_")
    safe_module = (module.title if module else f"module-{module_id}").replace(" ", "_")[:40]
    filename = f"attendance-{safe_code}-{safe_module}-{date_str}.csv"
    return _csv_response(filename, output.getvalue())


@attendance_bp.route('/module/<int:module_id>/record', methods=['GET', 'POST'])
@login_required
def record_attendance(module_id: int) -> Union[str, redirect]:
    """Record attendance for a module session."""
    module, course, _, can_record = check_attendance_permission(module_id, require_record=True)
    
    if not can_record:
        abort(HTTPStatus.FORBIDDEN)
    
    if request.method == 'POST':
        try:
            attendance_date_str: str = request.form.get('date', '')
            if not attendance_date_str:
                flash('Date is required.', 'danger')
                return redirect(request.url)
            
            attendance_date: date = date.fromisoformat(attendance_date_str)
            
            # Validate date not in future
            if attendance_date > date.today():
                flash('Cannot record attendance for future dates.', 'danger')
                return redirect(request.url)
            
            # Get enrolled students
            enrollments: List[Enrollment] = Enrollment.query.filter_by(
                course_id=course.id,
                status='active'
            ).all()
            
            records_updated: int = 0
            records_created: int = 0
            
            for enrollment in enrollments:
                student_id: int = enrollment.student_id
                status: str = request.form.get(f'status_{student_id}', 'absent')
                notes: str = request.form.get(f'notes_{student_id}', '').strip()
                
                # Validate status
                valid_statuses: List[str] = ['present', 'absent', 'excused', 'late']
                if status not in valid_statuses:
                    status = 'absent'
                
                # Check for existing record
                existing: Optional[Attendance] = Attendance.query.filter_by(
                    module_id=module_id,
                    student_id=student_id,
                    date=attendance_date
                ).first()
                
                if existing:
                    existing.status = status
                    existing.notes = notes if notes else existing.notes
                    existing.recorded_by = current_user.id
                    existing.updated_at = app_now()
                    records_updated += 1
                else:
                    attendance = Attendance(
                        module_id=module_id,
                        student_id=student_id,
                        date=attendance_date,
                        status=status,
                        recorded_by=current_user.id,
                        notes=notes if notes else None
                    )
                    db.session.add(attendance)
                    records_created += 1
            
            db.session.commit()
            
            total: int = records_updated + records_created
            flash(
                f'Attendance recorded for {total} students '
                f'({records_created} new, {records_updated} updated).',
                'success'
            )
            
            return redirect(url_for('attendance.module_attendance', module_id=module_id))
            
        except ValueError as e:
            flash(f'Invalid date format: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Attendance recording error: {str(e)}')
            flash('Error recording attendance. Please try again.', 'danger')
    
    # GET request
    enrollments: List[Enrollment] = Enrollment.query.filter_by(
        course_id=course.id,
        status='active'
    ).join(Student).join(User).order_by(User.last_name).all()
    
    today: date = date.today()
    
    # Check for existing records today
    existing_records: List[Attendance] = Attendance.query.filter_by(
        module_id=module_id,
        date=today
    ).all()
    
    existing_dict: Dict[int, Attendance] = {r.student_id: r for r in existing_records}
    
    # Calculate attendance trend
    recent_stats: Dict = {
        'average_rate': 0.0,
        'total_sessions': 0
    }
    
    recent_records: List[Attendance] = Attendance.query.filter_by(
        module_id=module_id
    ).order_by(Attendance.date.desc()).limit(100).all()
    
    if recent_records:
        by_date: Dict[date, List[Attendance]] = {}
        for r in recent_records:
            if r.date not in by_date:
                by_date[r.date] = []
            by_date[r.date].append(r)
        
        rates: List[float] = []
        for d, records in by_date.items():
            present: int = sum(1 for r in records if r.status == 'present')
            rates.append(present / len(records) * 100)
        
        recent_stats['average_rate'] = sum(rates) / len(rates) if rates else 0
        recent_stats['total_sessions'] = len(by_date)
    
    return render_template(
        'attendance_record.html',
        course=course,
        module=module,
        students=enrollments,
        existing_records=existing_dict,
        date=today,
        recent_stats=recent_stats
    )


@attendance_bp.route('/student')
@login_required
def my_attendance() -> str:
    """Student's attendance summary across all courses."""
    if current_user.role != 'student':
        abort(HTTPStatus.FORBIDDEN)
    
    student: Student = Student.query.filter_by(
        user_id=current_user.id
    ).first_or_404()
    
    # Get all records
    records: List[Attendance] = Attendance.query.filter_by(
        student_id=student.id
    ).order_by(Attendance.date.desc()).all()
    
    # Overall stats
    overall: Dict = {
        'total': len(records),
        'present': sum(1 for r in records if r.status == 'present'),
        'absent': sum(1 for r in records if r.status == 'absent'),
        'excused': sum(1 for r in records if r.status == 'excused'),
        'late': sum(1 for r in records if r.status == 'late'),
        'rate': 0.0
    }
    
    overall['rate'] = (
        (overall['present'] / overall['total'] * 100) if overall['total'] > 0 else 0
    )
    
    # Group by module (for context about which module in the course)
    modules_data: Dict[int, Dict] = {}
    
    for record in records:
        mid: int = record.module_id
        if mid not in modules_data:
            modules_data[mid] = {
                'module': record.module,
                'course': record.module.course if record.module else None,
                'records': [],
                'stats': {
                    'present': 0, 'absent': 0, 'excused': 0, 
                    'late': 0, 'total': 0, 'rate': 0.0
                }
            }
        
        modules_data[mid]['records'].append(record)
        modules_data[mid]['stats']['total'] += 1
        modules_data[mid]['stats'][record.status] += 1
    
    # Calculate module rates
    for mid, data in modules_data.items():
        stats = data['stats']
        stats['rate'] = (
            (stats['present'] / stats['total'] * 100) 
            if stats['total'] > 0 else 0
        )
    
    # Recent activity (last 7 days)
    recent_cutoff: date = date.today() - timedelta(days=7)
    recent_records: List[Attendance] = [
        r for r in records if r.date >= recent_cutoff
    ]
    
    return render_template(
        'attendance_summary.html',
        records=records,
        modules=modules_data,
        overall=overall,
        recent_records=recent_records,
        attendance_rate=round(overall['rate'], 1),
        total_present=overall['present'],
        total_absent=overall['absent'],
        total_late=overall['late'],
        total_sessions=overall['total'],
    )


@attendance_bp.route('/course/<int:course_id>/record', methods=['GET', 'POST'])
@login_required
def record_attendance_course_legacy(course_id: int) -> redirect:
    """Redirect old course-based attendance record URLs to first module."""
    # Prefer a module assigned to the current lecturer (avoids 403 on record)
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
        return redirect(url_for('attendance.record_attendance', module_id=module.id))
    
    flash('No modules found in this course.', 'warning')
    return redirect(url_for('courses.detail', course_id=course_id))