import os
import uuid
from datetime import datetime
from typing import Union, Optional
from werkzeug.utils import secure_filename
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from http import HTTPStatus

from app import db
from app.utils.app_time import app_now
from app.models import User, Student, Lecturer, Course, Enrollment, StaffProfile
from app.utils.login_helpers import resolve_user_from_login_id
from app.forms.auth_forms import (
    LoginForm,
    StudentProfileForm, StudentCompleteProfileForm, LecturerProfileForm,
)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def _truthy_env(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def redirect_authenticated_user() -> Optional[str]:
    """Redirect already authenticated users to dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return None


@auth_bp.route('/register', methods=['GET', 'POST'])
def register() -> redirect:
    """Public registration is disabled (institutional LMS)."""
    flash('Registration is managed by your institution. Please sign in with your student or staff number.', 'info')
    return redirect(url_for('auth.login'))


def _save_profile_photo(student: Student, file_storage) -> Optional[str]:
    """Save image under UPLOAD_FOLDER/profiles/<student.id>/. Returns error message or None."""
    fn = getattr(file_storage, "filename", None) if file_storage else None
    if not fn or not str(fn).strip():
        return None
    allowed = {"png", "jpg", "jpeg", "webp"}
    raw = secure_filename(file_storage.filename)
    if not raw or "." not in raw:
        return "Please upload a valid image file."
    ext = raw.rsplit(".", 1)[1].lower()
    if ext not in allowed:
        return "Allowed image types: JPG, PNG, WebP."
    upload_root = current_app.config.get("UPLOAD_FOLDER") or ""
    dest_dir = os.path.join(upload_root, "profiles", str(student.id))
    os.makedirs(dest_dir, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(dest_dir, fname)
    file_storage.save(path)
    # URL path under static/: uploads/profiles/...
    student.profile_image = f"uploads/profiles/{student.id}/{fname}".replace("\\", "/")
    return None


@auth_bp.route('/complete_student_profile', methods=['GET', 'POST'])
@login_required
def complete_student_profile() -> Union[str, redirect]:
    """Complete student profile after registration."""
    if current_user.role != 'student':
        return redirect(url_for('main.dashboard'))

    student = Student.query.filter_by(user_id=current_user.id).first_or_404()

    sid = (student.student_id or "").strip()
    if not sid.startswith("PENDING-"):
        flash('Profile already completed.', 'info')
        return redirect(url_for('main.dashboard'))

    form = StudentCompleteProfileForm()
    courses_q = Course.query.filter_by(is_active=True).order_by(Course.code).all()
    form.course_id.choices = [("", "— Select an available course —")] + [
        (str(c.id), f"{c.code} — {c.name}") for c in courses_q
    ]

    if request.method == 'GET':
        form.student_id.data = ""

    if form.validate_on_submit():
        try:
            new_sid = (form.student_id.data or "").strip()

            course_id = int(form.course_id.data)
            course = Course.query.filter_by(id=course_id, is_active=True).first()
            if not course:
                flash('Selected course is not available.', 'danger')
                return render_template('auth/complete_profile.html', form=form, role='student')

            err = _save_profile_photo(student, form.profile_photo.data)
            if err:
                flash(err, 'danger')
                return render_template('auth/complete_profile.html', form=form, role='student')

            student.student_id = new_sid
            student.date_of_birth = form.date_of_birth.data
            student.phone = form.phone.data
            student.address = form.address.data
            # Program label comes from selected course (no separate Program/Major field)
            student.program = course.name

            existing = Enrollment.query.filter_by(student_id=student.id, course_id=course_id).first()
            if existing:
                if existing.status != "active":
                    existing.status = "active"
                    existing.enrolled_at = app_now()
            else:
                other_active = Enrollment.query.filter_by(student_id=student.id, status="active").first()
                if other_active and other_active.course_id != course_id:
                    flash(
                        'You already have an active enrollment. Finish or unenroll before choosing another course.',
                        'warning',
                    )
                    return render_template('auth/complete_profile.html', form=form, role='student')
                db.session.add(
                    Enrollment(student_id=student.id, course_id=course_id, status="active")
                )

            db.session.flush()
            enrollment = Enrollment.query.filter_by(
                student_id=student.id, course_id=course_id, status="active"
            ).first()
            if enrollment:
                from app.models.student_module_progress import StudentModuleProgress
                from app.routes.courses import _create_module_progress_records

                has_progress = (
                    db.session.query(StudentModuleProgress.id)
                    .filter_by(enrollment_id=enrollment.id)
                    .first()
                )
                if not has_progress:
                    _create_module_progress_records(enrollment)
                else:
                    db.session.commit()
            else:
                db.session.commit()
            flash('Profile completed successfully!', 'success')
            return redirect(url_for('main.dashboard'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Profile completion error: {str(e)}')
            flash('Error saving profile. Please try again.', 'danger')

    return render_template('auth/complete_profile.html', form=form, role='student')


@auth_bp.route('/complete_lecturer_profile', methods=['GET', 'POST'])
@login_required
def complete_lecturer_profile() -> Union[str, redirect]:
    """Complete lecturer profile after registration."""
    if current_user.role != 'lecturer':
        return redirect(url_for('main.dashboard'))
    
    lecturer = Lecturer.query.filter_by(user_id=current_user.id).first_or_404()
    
    if lecturer.department:
        flash('Profile already completed.', 'info')
        return redirect(url_for('main.dashboard'))
    
    form = LecturerProfileForm()
    
    if form.validate_on_submit():
        try:
            lecturer.employee_id = form.employee_id.data or lecturer.employee_id
            lecturer.department = form.department.data
            lecturer.title = form.title.data
            lecturer.phone = form.phone.data
            lecturer.office = form.office.data
            lecturer.specialization = form.specialization.data
            
            db.session.commit()
            flash('Profile completed successfully!', 'success')
            return redirect(url_for('main.dashboard'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Profile completion error: {str(e)}')
            flash('Error saving profile. Please try again.', 'danger')
    
    return render_template('auth/complete_profile.html', form=form, role='lecturer')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login() -> Union[str, redirect]:
    """Handle user login with remember me functionality."""
    if redirect_to := redirect_authenticated_user():
        return redirect_to
    
    form = LoginForm()
    
    if form.validate_on_submit():
        institutional_id = (form.institutional_id.data or "").strip()
        user = resolve_user_from_login_id(institutional_id)

        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('Your account has been deactivated. Please contact admin.', 'danger')
                return render_template('auth/login.html', form=form), HTTPStatus.FORBIDDEN
            
            # Login with remember me
            remember = form.remember.data == 'yes'
            login_user(user, remember=remember)
            
            # Redirect to dashboard
            next_page = url_for('main.dashboard')
            
            flash(f'Welcome back, {user.first_name}!', 'success')
            return redirect(next_page)
        
        flash('Invalid student/staff number, email, or password.', 'danger')
        return render_template('auth/login.html', form=form), HTTPStatus.UNAUTHORIZED
    
    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout() -> redirect:
    """Handle user logout."""
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile() -> Union[str, redirect]:
    """Handle profile management for all user roles."""
    profile_obj = None
    form = None
    
    try:
        if current_user.role == 'student':
            profile_obj = Student.query.filter_by(user_id=current_user.id).first_or_404()
            form = StudentProfileForm(obj=profile_obj)
            
            if form.validate_on_submit():
                profile_obj.student_id = form.student_id.data or profile_obj.student_id
                profile_obj.date_of_birth = form.date_of_birth.data
                profile_obj.phone = form.phone.data
                profile_obj.address = form.address.data
        
        elif current_user.role == 'lecturer':
            profile_obj = Lecturer.query.filter_by(user_id=current_user.id).first_or_404()
            form = LecturerProfileForm(obj=profile_obj)
            
            if form.validate_on_submit():
                profile_obj.employee_id = form.employee_id.data or profile_obj.employee_id
                profile_obj.department = form.department.data
                profile_obj.title = form.title.data
                profile_obj.phone = form.phone.data
                profile_obj.office = form.office.data
                profile_obj.specialization = form.specialization.data
        
        else:
            return render_template('profile.html', form=None, profile=None)
        
        if form and form.validate_on_submit():
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('auth.profile'))
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Profile update error: {str(e)}')
        flash('Error updating profile. Please try again.', 'danger')
    
    return render_template('profile.html', form=form, profile=profile_obj)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password() -> redirect:
    """Email-based password reset is disabled."""
    flash('Password reset via email is disabled. Please contact an administrator.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp() -> redirect:
    """Email-based password reset is disabled."""
    flash('Password reset via email is disabled. Please contact an administrator.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token: str) -> redirect:
    """Email-based password reset is disabled."""
    flash('Password reset via email is disabled. Please contact an administrator.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/verify-email/<token>', methods=['GET'])
def verify_email(token: str) -> redirect:
    """Email verification is disabled."""
    flash('Email verification is disabled in this system.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/resend-verification', methods=['GET', 'POST'])
@login_required
def resend_verification() -> redirect:
    """Email verification is disabled."""
    flash('Email verification is disabled in this system.', 'info')
    return redirect(url_for('main.dashboard'))