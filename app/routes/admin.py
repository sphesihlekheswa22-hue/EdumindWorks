from functools import wraps
from typing import List, Optional, Union
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, jsonify, abort, current_app, Response
)
from flask_login import login_required, current_user
from datetime import datetime
from app.utils.app_time import app_now
from http import HTTPStatus

from app import db
from sqlalchemy.orm import joinedload
from app.models import User, Student, Lecturer, Course, Enrollment, StaffProfile, Mark

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def _csv_response(filename: str, csv_text: str) -> Response:
    # Excel-friendly UTF-8 with BOM, and correct content-disposition for downloads.
    bom = "\ufeff"
    resp = Response(bom + csv_text, mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


class AdminRequiredError(Exception):
    """Custom exception for admin privilege violations."""
    pass


def admin_required(f):
    """Decorator to require admin role with proper error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if current_user.role != 'admin':
            # Return 403 Forbidden instead of redirect for security
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function


_INVALID_NAME_MESSAGE = (
    'Enter a valid name using letters only. Numbers and symbols are not allowed.'
)


def _is_valid_name_part(name_part: str) -> bool:
    """Allow Unicode letters with spaces, hyphens, or apostrophes between names."""
    part = (name_part or '').strip()
    if not part:
        return False

    has_letter = False
    for char in part:
        if char.isalpha():
            has_letter = True
        elif char in " -'":
            continue
        else:
            return False
    return has_letter


def _is_valid_full_name(full_name: str) -> bool:
    """Reject empty names and values containing digits or symbols."""
    cleaned = (full_name or '').strip()
    if not cleaned:
        return False

    parts = cleaned.split(None, 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ''

    if not _is_valid_name_part(first_name):
        return False
    if last_name and not _is_valid_name_part(last_name):
        return False
    return True


@admin_bp.errorhandler(AdminRequiredError)
def handle_admin_error(error):
    """Handle admin-specific errors."""
    flash(str(error), 'danger')
    return redirect(url_for('main.dashboard'))


@admin_bp.route('/')
@login_required
@admin_required
def index():
    """Avoid bare /admin/ 404 during demos; send admins to user management."""
    return redirect(url_for('admin.users'))


@admin_bp.route('/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users() -> str:
    """Display user management interface with filtering and creation."""
    if request.method == 'POST':
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        role = (request.form.get('role') or '').strip()

        valid_roles = {'student', 'lecturer', 'admin', 'career_advisor'}
        if not first_name or not last_name or not email or not password:
            flash('All user fields are required.', 'danger')
            return redirect(url_for('admin.users'))
        if not _is_valid_name_part(first_name) or not _is_valid_name_part(last_name):
            flash(_INVALID_NAME_MESSAGE, 'danger')
            return redirect(url_for('admin.users'))
        if role not in valid_roles:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('admin.users'))
        if User.query.filter_by(email=email).first():
            flash('A user with that email already exists.', 'warning')
            return redirect(url_for('admin.users'))

        try:
            user = User(
                first_name=first_name,
                last_name=last_name,
                email=email,
                role=role,
                is_active=True
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            if role == 'student':
                db.session.add(Student(user_id=user.id, student_id=f"STU{user.id:06d}"))
            elif role == 'lecturer':
                db.session.add(Lecturer(user_id=user.id, employee_id=f"EMP{user.id:06d}"))

            db.session.commit()
            flash(f'User "{user.full_name}" created.', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error creating admin user {email}: {str(e)}')
            flash('Failed to create user. Please try again.', 'danger')
        return redirect(url_for('admin.users'))

    role: Optional[str] = request.args.get('role', type=str)
    
    query = User.query.order_by(User.created_at.desc())
    
    if role and role in ['student', 'lecturer', 'admin', 'career_advisor']:
        query = query.filter_by(role=role)
    
    # Load related institutional IDs for display in the admin user list.
    users_list: List[User] = query.options(
        joinedload(User.student),
        joinedload(User.lecturer),
        joinedload(User.staff_profile),
    ).all()
    
    # Efficiently calculate all stats in one go
    stats = {
        'total': len(users_list),
        'active': sum(1 for u in users_list if u.is_active),
        'by_role': {
            'student': sum(1 for u in users_list if u.role == 'student'),
            'lecturer': sum(1 for u in users_list if u.role == 'lecturer'),
            'admin': sum(1 for u in users_list if u.role == 'admin'),
            'career_advisor': sum(1 for u in users_list if u.role == 'career_advisor')
        }
    }
    
    return render_template(
        'admin/admin_users.html',
        users=users_list, 
        role=role,
        stats=stats
    )


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_user_active(user_id: int) -> Union[str, tuple]:
    """Toggle user active status with validation."""
    user: User = User.query.get_or_404(user_id)
    
    # Prevent self-deactivation
    if user.id == current_user.id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': 'You cannot deactivate your own account.'
            }), HTTPStatus.BAD_REQUEST
        
        flash('You cannot deactivate yourself.', 'danger')
        return redirect(url_for('admin.users'))
    
    try:
        user.is_active = not user.is_active
        db.session.commit()
        
        status_msg = 'activated' if user.is_active else 'deactivated'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'message': f'User {status_msg} successfully.',
                'is_active': user.is_active
            })
        
        flash(f'User {status_msg} successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error toggling user {user_id}: {str(e)}')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': 'An error occurred. Please try again.'
            }), HTTPStatus.INTERNAL_SERVER_ERROR
        
        flash('An error occurred. Please try again.', 'danger')
    
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/view')
@login_required
@admin_required
def view_user(user_id: int) -> str:
    """Display user profile for admin review."""
    user: User = User.query.options(
        joinedload(User.student).joinedload(Student.enrollments).joinedload(Enrollment.course),
        joinedload(User.lecturer),
        joinedload(User.staff_profile),
    ).get_or_404(user_id)
    return render_template('admin/admin_user_view.html', user=user)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id: int) -> str:
    """Edit user profile."""
    user: User = User.query.get_or_404(user_id)
    if request.method == 'POST':
        prev_email = (user.email or "").strip().lower()
        full_name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        role = request.form.get('role')
        is_active = 'is_active' in request.form
        form_data = {
            'full_name': full_name,
            'email': email,
            'role': role,
            'is_active': is_active,
        }

        if not _is_valid_full_name(full_name):
            flash(_INVALID_NAME_MESSAGE, 'danger')
            return render_template('user_edit.html', user=user, form_data=form_data)

        valid_roles = {'student', 'lecturer', 'admin', 'career_advisor'}
        if role not in valid_roles:
            flash('Invalid role selected.', 'danger')
            return render_template('user_edit.html', user=user, form_data=form_data)

        user.full_name = full_name
        user.email = email
        user.role = role
        user.is_active = is_active

        db.session.commit()
        flash('User updated successfully!', 'success')

        return redirect(url_for('admin.users'))
    return render_template('user_edit.html', user=user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id: int) -> str:
    """Delete user with cascade handling."""
    from app.models.notification import Notification, InterventionMessage
    from app.models.attendance import Attendance
    from app.models.material import Material
    from app.models.quiz import Quiz

    user: User = User.query.get_or_404(user_id)
    
    if user.id == current_user.id:
        flash('You cannot delete yourself.', 'danger')
        return redirect(url_for('admin.users'))
    
    try:
        Notification.query.filter(
            (Notification.recipient_id == user.id) | (Notification.sender_id == user.id)
        ).delete(synchronize_session=False)

        if user.lecturer:
            InterventionMessage.query.filter_by(lecturer_id=user.lecturer.id).delete(synchronize_session=False)

        Mark.query.filter_by(recorded_by=user.id).update(
            {Mark.recorded_by: current_user.id}, synchronize_session=False
        )
        Attendance.query.filter_by(recorded_by=user.id).update(
            {Attendance.recorded_by: current_user.id}, synchronize_session=False
        )
        Material.query.filter_by(uploaded_by=user.id).update(
            {Material.uploaded_by: current_user.id}, synchronize_session=False
        )
        Quiz.query.filter_by(created_by=user.id).update(
            {Quiz.created_by: current_user.id}, synchronize_session=False
        )

        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error deleting user {user_id}: {str(e)}')
        flash('Error deleting user. They may have associated records.', 'danger')
    
    return redirect(url_for('admin.users'))


@admin_bp.route('/courses')
@login_required
@admin_required
def courses() -> str:
    """Display course management interface."""
    courses_list: List[Course] = Course.query.order_by(
        Course.created_at.desc()
    ).all()
    
    # Get lecturers for each course
    course_lecturers = {}
    for course in courses_list:
        course_lecturers[course.id] = course.get_lecturers()
    
    stats = {
        'total': len(courses_list),
        'active': sum(1 for c in courses_list if c.is_active),
        'total_enrollments': db.session.query(Enrollment).count(),
        'total_students': sum(c.get_student_count() for c in courses_list)
    }
    
    return render_template(
        'admin/admin_courses.html',
        courses=courses_list,
        course_lecturers=course_lecturers,
        stats=stats
    )


@admin_bp.route('/courses/<int:course_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_course_active(course_id: int) -> str:
    """Toggle course active status."""
    course: Course = Course.query.get_or_404(course_id)
    
    try:
        course.is_active = not course.is_active
        db.session.commit()
        
        status = 'activated' if course.is_active else 'deactivated'
        flash(f'Course {status} successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error toggling course {course_id}: {str(e)}')
        flash('Error updating course status.', 'danger')
    
    return redirect(url_for('admin.courses'))


@admin_bp.route('/courses/<int:course_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_course(course_id: int) -> str:
    """Delete course with related cleanup."""
    from app.models.notification import InterventionMessage
    from app.models.risk_score import RiskScore

    course: Course = Course.query.get_or_404(course_id)
    
    try:
        Enrollment.query.filter_by(course_id=course_id).delete(synchronize_session=False)
        InterventionMessage.query.filter_by(course_id=course_id).delete(synchronize_session=False)
        RiskScore.query.filter_by(course_id=course_id).delete(synchronize_session=False)
        db.session.delete(course)
        db.session.commit()
        flash('Course deleted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error deleting course {course_id}: {str(e)}')
        flash('Error deleting course. It may have associated records.', 'danger')
    
    return redirect(url_for('admin.courses'))


@admin_bp.route('/courses/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_course() -> str:
    """Add a new course."""
    from app.models.lecturer import Lecturer
    from app.models.user import User
    lecturers = (
        Lecturer.query.join(User, Lecturer.user_id == User.id)
        .order_by(User.first_name.asc(), User.last_name.asc())
        .all()
    )
    if request.method == 'POST':
        try:
            code = (request.form.get('code') or '').strip().upper()
            name = (request.form.get('name') or '').strip()
            description = (request.form.get('description') or '').strip() or None
            credits = request.form.get('credits', type=int) or 3
            semester = (request.form.get('semester') or '').strip() or None
            year = request.form.get('year', type=int)
            lecturer_id = request.form.get('lecturer_id', type=int)

            if not code or not name:
                flash('Course code and name are required.', 'danger')
                return redirect(url_for('admin.add_course'))

            if lecturer_id:
                lecturer = Lecturer.query.get(lecturer_id)
                if not lecturer or not lecturer.user or lecturer.user.role != 'lecturer':
                    flash('Invalid lecturer selected.', 'danger')
                    return redirect(url_for('admin.add_course'))

            new_course = Course(
                name=name,
                code=code,
                description=description,
                credits=credits,
                semester=semester,
                year=year,
                lecturer_id=lecturer_id or None,
                is_active='is_active' in request.form
            )
            db.session.add(new_course)
            db.session.commit()
            flash('Course added successfully!', 'success')
            return redirect(url_for('admin.courses'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error adding course: {str(e)}')
            flash('An error occurred. Please try again.', 'danger')
    return render_template('course_form.html', action='Add', course=None, lecturers=lecturers)


@admin_bp.route('/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_course(course_id: int) -> str:
    """Edit an existing course."""
    from app.models.lecturer import Lecturer
    from app.models.user import User
    lecturers = (
        Lecturer.query.join(User, Lecturer.user_id == User.id)
        .order_by(User.first_name.asc(), User.last_name.asc())
        .all()
    )
    course = Course.query.get_or_404(course_id)
    if request.method == 'POST':
        try:
            code = (request.form.get('code') or '').strip().upper()
            name = (request.form.get('name') or '').strip()
            description = (request.form.get('description') or '').strip() or None
            credits = request.form.get('credits', type=int) or 3
            semester = (request.form.get('semester') or '').strip() or None
            year = request.form.get('year', type=int)
            lecturer_id = request.form.get('lecturer_id', type=int)

            if not code or not name:
                flash('Course code and name are required.', 'danger')
                return redirect(url_for('admin.edit_course', course_id=course_id))

            if lecturer_id:
                lecturer = Lecturer.query.get(lecturer_id)
                if not lecturer or not lecturer.user or lecturer.user.role != 'lecturer':
                    flash('Invalid lecturer selected.', 'danger')
                    return redirect(url_for('admin.edit_course', course_id=course_id))

            course.name = name
            course.code = code
            course.description = description
            course.credits = credits
            course.semester = semester
            course.year = year
            course.lecturer_id = lecturer_id or None
            course.is_active = 'is_active' in request.form
            course.updated_at = app_now()
            db.session.commit()
            flash('Course updated successfully!', 'success')
            return redirect(url_for('admin.courses'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error editing course {course_id}: {str(e)}')
            flash('An error occurred. Please try again.', 'danger')
    return render_template('course_form.html', action='Edit', course=course, lecturers=lecturers)


@admin_bp.route('/enrollments')
@login_required
@admin_required
def enrollments() -> str:
    """Display enrollment management with filtering."""
    status: str = request.args.get('status', 'all')
    
    query = Enrollment.query
    
    if status != 'all':
        query = query.filter_by(status=status)
    
    enrollments_list = query.order_by(Enrollment.enrolled_at.desc()).all()
    
    # Calculate statistics
    stats = {
        'total': Enrollment.query.count(),
        'active': Enrollment.query.filter_by(status='active').count(),
        'pending': Enrollment.query.filter_by(status='pending').count(),
        'completed': Enrollment.query.filter_by(status='completed').count(),
        'dropped': Enrollment.query.filter_by(status='dropped').count()
    }
    
    return render_template(
        'admin/admin_enrollments.html',
        enrollments=enrollments_list,
        students=Student.query.order_by(Student.id.desc()).all(),
        courses=Course.query.order_by(Course.name.asc()).all(),
        status=status,
        stats=stats
    )


@admin_bp.route('/enrollments/create', methods=['POST'])
@login_required
@admin_required
def create_enrollment() -> str:
    """Create a new enrollment from admin panel."""
    student_id = request.form.get('student_id', type=int)
    course_id = request.form.get('course_id', type=int)
    status = (request.form.get('status') or 'active').strip()
    valid_statuses = {'active', 'pending', 'completed', 'dropped'}

    if not student_id or not course_id:
        flash('Student and course are required.', 'danger')
        return redirect(url_for('admin.enrollments'))
    if status not in valid_statuses:
        flash('Invalid enrollment status.', 'danger')
        return redirect(url_for('admin.enrollments'))

    if not Student.query.get(student_id) or not Course.query.get(course_id):
        flash('Invalid student or course selected.', 'danger')
        return redirect(url_for('admin.enrollments'))

    existing = Enrollment.query.filter_by(student_id=student_id, course_id=course_id).first()
    if existing:
        try:
            existing.status = status
            existing.completed_at = app_now() if status == 'completed' else None
            db.session.commit()
            flash('Enrollment status updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error updating enrollment status: {str(e)}')
            flash('Failed to update enrollment status. Please try again.', 'danger')
        return redirect(url_for('admin.enrollments'))

    try:
        enrollment = Enrollment(student_id=student_id, course_id=course_id, status=status)
        if status == 'completed':
            enrollment.completed_at = app_now()
        db.session.add(enrollment)
        db.session.commit()
        flash('Enrollment created successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error creating enrollment: {str(e)}')
        flash('Failed to create enrollment. Please try again.', 'danger')

    return redirect(url_for('admin.enrollments'))


@admin_bp.route('/enrollments/<int:enrollment_id>/view')
@login_required
@admin_required
def view_enrollment(enrollment_id: int) -> str:
    """View enrollment details."""
    enrollment = Enrollment.query.get_or_404(enrollment_id)
    return render_template(
        'admin/admin_enrollment_detail.html',
        enrollment=enrollment,
        lecturers=enrollment.course.get_lecturers(),
        valid_statuses=['active', 'pending', 'completed', 'dropped'],
        edit_mode=False
    )


@admin_bp.route('/enrollments/<int:enrollment_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_enrollment(enrollment_id: int) -> str:
    """Edit enrollment status from detail page."""
    enrollment = Enrollment.query.get_or_404(enrollment_id)
    valid_statuses = ['active', 'pending', 'completed', 'dropped']

    if request.method == 'POST':
        new_status: Optional[str] = request.form.get('status')
        if not new_status or new_status not in valid_statuses:
            flash('Invalid status provided.', 'danger')
            return redirect(url_for('admin.edit_enrollment', enrollment_id=enrollment_id))

        try:
            enrollment.status = new_status
            enrollment.completed_at = app_now() if new_status == 'completed' else None
            db.session.commit()
            flash('Enrollment updated successfully!', 'success')
            return redirect(url_for('admin.view_enrollment', enrollment_id=enrollment_id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error editing enrollment {enrollment_id}: {str(e)}')
            flash('Failed to update enrollment.', 'danger')

    return render_template(
        'admin/admin_enrollment_detail.html',
        enrollment=enrollment,
        lecturers=enrollment.course.get_lecturers(),
        valid_statuses=valid_statuses,
        edit_mode=True
    )


@admin_bp.route('/enrollments/<int:enrollment_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_enrollment(enrollment_id: int) -> str:
    """Remove an enrollment from admin panel."""
    enrollment = Enrollment.query.get_or_404(enrollment_id)
    try:
        db.session.delete(enrollment)
        db.session.commit()
        flash('Enrollment removed successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error deleting enrollment {enrollment_id}: {str(e)}')
        flash('Failed to remove enrollment.', 'danger')
    return redirect(url_for('admin.enrollments'))


@admin_bp.route('/enrollments/<int:enrollment_id>/status', methods=['POST'])
@login_required
@admin_required
def update_enrollment_status(enrollment_id: int) -> str:
    """Update enrollment status with validation."""
    enrollment: Enrollment = Enrollment.query.get_or_404(enrollment_id)
    
    new_status: Optional[str] = request.form.get('status')
    valid_statuses = ['active', 'pending', 'completed', 'dropped']
    
    if not new_status or new_status not in valid_statuses:
        flash('Invalid status provided.', 'danger')
        return redirect(url_for('admin.enrollments'))
    
    try:
        enrollment.status = new_status
        
        if new_status == 'completed':
            enrollment.completed_at = app_now()
        else:
            enrollment.completed_at = None
        
        db.session.commit()
        flash(f'Enrollment status updated to {new_status}!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error updating enrollment {enrollment_id}: {str(e)}')
        flash('Error updating enrollment status.', 'danger')
    
    return redirect(url_for('admin.enrollments'))


@admin_bp.route('/settings')
@login_required
@admin_required
def settings() -> str:
    """System settings page."""
    tab = (request.args.get('tab') or 'system').strip()
    if tab not in {'system', 'roles'}:
        tab = 'system'
    return render_template('admin/admin_settings.html', tab=tab)


@admin_bp.route('/reports/users.csv')
@login_required
@admin_required
def export_users_csv() -> Response:
    """Export users as CSV (optionally filtered by role/status)."""
    import csv
    import io

    role = request.args.get("role", type=str)
    status = request.args.get("status", type=str)  # active|inactive|all

    query = User.query.order_by(User.created_at.desc())
    if role in {"student", "lecturer", "admin", "career_advisor"}:
        query = query.filter_by(role=role)
    if status == "active":
        query = query.filter_by(is_active=True)
    elif status == "inactive":
        query = query.filter_by(is_active=False)

    users_list = query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "email", "first_name", "last_name", "role", "is_active", "created_at"])
    for u in users_list:
        writer.writerow([
            u.id,
            u.email,
            u.first_name,
            u.last_name,
            u.role,
            bool(u.is_active),
            getattr(u, "created_at", None).isoformat() if getattr(u, "created_at", None) else "",
        ])

    date_str = app_now().strftime("%Y-%m-%d")
    suffix = f"-{role}" if role in {"student", "lecturer", "admin", "career_advisor"} else ""
    return _csv_response(f"users{suffix}-{date_str}.csv", output.getvalue())


@admin_bp.route('/reports/courses.csv')
@login_required
@admin_required
def export_courses_csv() -> Response:
    """Export courses as CSV (optionally filtered by status)."""
    import csv
    import io

    statuses_raw = (request.args.get("status") or "").strip()
    statuses = {s.strip() for s in statuses_raw.split(",") if s.strip()}
    # If no status specified, export all.

    query = Course.query.order_by(Course.created_at.desc())
    if statuses:
        allowed = {"active", "inactive"}
        statuses = statuses & allowed
        if statuses == {"active"}:
            query = query.filter(Course.is_active.is_(True))
        elif statuses == {"inactive"}:
            query = query.filter(Course.is_active.is_(False))

    courses_list = query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "code", "name", "credits", "semester", "year", "is_active", "students", "modules", "lecturers"])
    for c in courses_list:
        lecturers = c.get_lecturers() if hasattr(c, "get_lecturers") else []
        lecturer_names = ", ".join([getattr(l.user, "full_name", "") for l in lecturers if getattr(l, "user", None)])
        writer.writerow([
            c.id,
            c.code,
            c.name,
            c.credits,
            c.semester or "",
            c.year or "",
            bool(c.is_active),
            c.get_student_count() if hasattr(c, "get_student_count") else "",
            len(getattr(c, "modules", []) or []),
            lecturer_names,
        ])

    date_str = app_now().strftime("%Y-%m-%d")
    return _csv_response(f"courses-{date_str}.csv", output.getvalue())


@admin_bp.route('/reports/enrollments.csv')
@login_required
@admin_required
def export_enrollments_csv() -> Response:
    """Export enrollments as CSV (optionally filtered by course/status)."""
    import csv
    import io

    status = request.args.get("status", type=str)  # active|pending|completed|dropped|all
    course_id = request.args.get("course_id", type=int)

    query = Enrollment.query
    if course_id:
        query = query.filter_by(course_id=course_id)
    if status and status != "all":
        query = query.filter_by(status=status)

    enrollments_list = query.order_by(Enrollment.enrolled_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "student_id", "student_name", "course_id", "course_code", "course_name", "status", "enrolled_at", "completed_at"])
    for e in enrollments_list:
        student_name = ""
        student_sid = ""
        if e.student and getattr(e.student, "user", None):
            student_name = e.student.user.full_name
            student_sid = getattr(e.student, "student_id", "") or str(e.student.id)
        writer.writerow([
            e.id,
            student_sid,
            student_name,
            e.course_id,
            e.course.code if e.course else "",
            e.course.name if e.course else "",
            e.status,
            e.enrolled_at.isoformat() if e.enrolled_at else "",
            e.completed_at.isoformat() if getattr(e, "completed_at", None) else "",
        ])

    date_str = app_now().strftime("%Y-%m-%d")
    return _csv_response(f"enrollments-{date_str}.csv", output.getvalue())