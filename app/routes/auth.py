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
from app.models import User, Student, Lecturer, OTP, Course, Enrollment
from app.forms.auth_forms import (
    RegistrationForm, LoginForm,
    StudentProfileForm, StudentCompleteProfileForm, LecturerProfileForm,
    ForgotPasswordForm, ResetPasswordForm, OTPVerificationForm
)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def _truthy_env(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}

def _should_show_otp_onscreen() -> bool:
    # Demo-only: allow showing OTP when email is not configured.
    return current_app.debug or _truthy_env("SHOW_OTP_ONSCREEN")


def redirect_authenticated_user() -> Optional[str]:
    """Redirect already authenticated users to dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return None


@auth_bp.route('/register', methods=['GET', 'POST'])
def register() -> Union[str, redirect]:
    """Handle user registration with OTP verification."""
    if redirect_to := redirect_authenticated_user():
        return redirect_to
    
    form = RegistrationForm()
    
    if form.validate_on_submit():
        try:
            # Optional bypass for demos / when email is not configured.
            # Set DISABLE_EMAIL_OTP=true to allow direct registration.
            if _truthy_env("DISABLE_EMAIL_OTP"):
                user = User(
                    email=form.email.data,
                    first_name=form.first_name.data,
                    last_name=form.last_name.data,
                    role="student",
                )
                user.set_password(form.password.data)
                db.session.add(user)
                db.session.flush()

                profile = Student(
                    user_id=user.id,
                    student_id=f"PENDING-{user.id}",
                )
                db.session.add(profile)
                user.mark_email_verified()
                db.session.commit()

                login_user(user, remember=False)
                flash('Registration successful! Please complete your profile.', 'success')
                return redirect(url_for('auth.complete_student_profile'))

            # Store registration data in session for later use
            from flask import session
            session['registration_data'] = {
                'email': form.email.data,
                'first_name': form.first_name.data,
                'last_name': form.last_name.data,
                'password': form.password.data
            }
            
            # Generate OTP (do not commit until email succeeds or dev fallback applies)
            otp = OTP.create_otp(email=form.email.data, purpose='registration')

            from app.services.email_service import send_otp_email
            sent = send_otp_email(form.email.data, otp.otp_code, 'registration')
            if sent:
                db.session.commit()
                flash('A verification code has been sent to your email address.', 'success')
            elif _should_show_otp_onscreen():
                db.session.commit()
                flash(
                    f'Email is not configured. Development mode — your verification code is: {otp.otp_code}',
                    'warning',
                )
            else:
                db.session.rollback()
                flash(
                    'Failed to send verification email. Please check your email configuration and try again.',
                    'danger',
                )
                return render_template('auth/register.html', form=form)

            return redirect(url_for('auth.verify_registration_otp'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Registration error: {str(e)}')
            flash('Registration failed. Please try again.', 'danger')
    
    return render_template('auth/register.html', form=form)


@auth_bp.route('/verify-registration-otp', methods=['GET', 'POST'])
def verify_registration_otp() -> Union[str, redirect]:
    """Verify OTP for registration."""
    if redirect_to := redirect_authenticated_user():
        return redirect_to
    
    # Check if registration data exists in session
    from flask import session
    if 'registration_data' not in session:
        flash('Please complete the registration form first.', 'warning')
        return redirect(url_for('auth.register'))
    
    form = OTPVerificationForm()
    
    if form.validate_on_submit():
        try:
            registration_data = session['registration_data']
            email = registration_data['email']
            
            # Verify OTP
            otp = OTP.verify_otp(email, form.otp_code.data, 'registration')
            
            if not otp:
                flash('Invalid or expired OTP. Please try again.', 'danger')
                return render_template('auth/verify_otp.html', form=form, purpose='registration')
            
            # Mark OTP as used
            otp.mark_as_used()
            
            # Create user
            user = User(
                email=registration_data['email'],
                first_name=registration_data['first_name'],
                last_name=registration_data['last_name'],
                role='student'
            )
            user.set_password(registration_data['password'])
            db.session.add(user)
            db.session.flush()
            
            # Placeholder until complete profile (9-digit number entered there)
            profile = Student(
                user_id=user.id,
                student_id=f"PENDING-{user.id}",
            )
            db.session.add(profile)
            
            # Mark email as verified since OTP was verified
            user.mark_email_verified()
            
            db.session.commit()

            # Clear session data
            session.pop('registration_data', None)

            login_user(user, remember=False)

            flash('Registration successful! Please complete your profile.', 'success')
            return redirect(url_for('auth.complete_student_profile'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'OTP verification error: {str(e)}')
            flash('Verification failed. Please try again.', 'danger')
    
    return render_template('auth/verify_otp.html', form=form, purpose='registration')


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
        user: Optional[User] = User.query.filter_by(email=form.email.data).first()
        
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('Your account has been deactivated. Please contact admin.', 'danger')
                return render_template('auth/login.html', form=form), HTTPStatus.FORBIDDEN
            
            # Check if email is verified
            if not user.email_verified:
                flash('Please verify your email address before logging in. Check your inbox for the verification email.', 'warning')
                return render_template('auth/login.html', form=form), HTTPStatus.FORBIDDEN
            
            # Login with remember me
            remember = form.remember.data == 'yes'
            login_user(user, remember=remember)
            
            # Redirect to dashboard
            next_page = '/dashboard'
            
            flash(f'Welcome back, {user.first_name}!', 'success')
            return redirect(next_page)
        
        flash('Invalid email or password.', 'danger')
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
def forgot_password() -> Union[str, redirect]:
    """Handle forgot password request with OTP verification."""
    if redirect_to := redirect_authenticated_user():
        return redirect_to
    
    form = ForgotPasswordForm()
    
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user:
            try:
                # Store email in session for later use
                from flask import session
                session['reset_email'] = form.email.data
                
                # Generate and send OTP
                otp = OTP.create_otp(email=form.email.data, purpose='password_reset')
                db.session.commit()
                
                # Send OTP email
                from app.services.email_service import send_otp_email
                sent = send_otp_email(form.email.data, otp.otp_code, 'password_reset')
                if sent:
                    flash('A verification code has been sent to your email address.', 'success')
                elif _should_show_otp_onscreen():
                    flash(f'Email is not configured. Your verification code is: {otp.otp_code}', 'warning')
                else:
                    flash('Failed to send verification email. Please check your email configuration and try again.', 'danger')
                    return render_template('auth/forgot_password.html', form=form)
                
                return redirect(url_for('auth.verify_reset_otp'))
                
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f'Forgot password error: {str(e)}')
                flash('An error occurred. Please try again.', 'danger')
        else:
            # Don't reveal if email exists or not for security
            flash('If an account exists with that email, a verification code has been sent.', 'info')
            return redirect(url_for('auth.login'))
    
    return render_template('auth/forgot_password.html', form=form)


@auth_bp.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp() -> Union[str, redirect]:
    """Verify OTP for password reset."""
    if redirect_to := redirect_authenticated_user():
        return redirect_to
    
    # Check if reset email exists in session
    from flask import session
    if 'reset_email' not in session:
        flash('Please enter your email address first.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    
    form = OTPVerificationForm()
    
    if form.validate_on_submit():
        try:
            email = session['reset_email']
            
            # Verify OTP
            otp = OTP.verify_otp(email, form.otp_code.data, 'password_reset')
            
            if not otp:
                flash('Invalid or expired OTP. Please try again.', 'danger')
                return render_template('auth/verify_otp.html', form=form, purpose='password_reset')
            
            # Mark OTP as used
            otp.mark_as_used()
            db.session.commit()
            
            # Generate reset token for password reset
            user = User.query.filter_by(email=email).first()
            if not user:
                flash('User not found. Please try again.', 'danger')
                return redirect(url_for('auth.forgot_password'))
            
            token = user.generate_reset_token()
            db.session.commit()
            
            # Clear session data
            session.pop('reset_email', None)
            
            # Redirect to password reset page with token
            return redirect(url_for('auth.reset_password', token=token))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'OTP verification error: {str(e)}')
            flash('Verification failed. Please try again.', 'danger')
    
    return render_template('auth/verify_otp.html', form=form, purpose='password_reset')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token: str) -> Union[str, redirect]:
    """Handle password reset with token."""
    if redirect_to := redirect_authenticated_user():
        return redirect_to
    
    # Find user with this token
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or not user.verify_reset_token(token):
        flash('Invalid or expired reset link. Please request a new one.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    
    form = ResetPasswordForm()
    
    if form.validate_on_submit():
        try:
            # Set new password
            user.set_password(form.password.data)
            user.clear_reset_token()
            db.session.commit()
            
            flash('Your password has been reset successfully. Please login with your new password.', 'success')
            return redirect(url_for('auth.login'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Reset password error: {str(e)}')
            flash('An error occurred. Please try again.', 'danger')
    
    return render_template('auth/reset_password.html', form=form, token=token)


@auth_bp.route('/verify-email/<token>', methods=['GET'])
def verify_email(token: str) -> redirect:
    """Handle email verification with token."""
    # Find user with this token
    user = User.query.filter_by(email_verification_token=token).first()
    
    if not user or not user.verify_email_token(token):
        flash('Invalid or expired verification link. Please request a new one.', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Mark email as verified
        user.mark_email_verified()
        db.session.commit()
        
        flash('Your email has been verified successfully! You can now login.', 'success')
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Email verification error: {str(e)}')
        flash('An error occurred. Please try again.', 'danger')
        return redirect(url_for('auth.login'))


@auth_bp.route('/resend-verification', methods=['GET', 'POST'])
@login_required
def resend_verification() -> Union[str, redirect]:
    """Resend email verification link."""
    # Check if already verified
    if current_user.email_verified:
        flash('Your email is already verified.', 'info')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        try:
            from app.services.email_service import send_verification_email
            
            # Send verification email
            if send_verification_email(current_user):
                db.session.commit()
                flash('A verification email has been sent. Please check your inbox.', 'success')
            else:
                flash('Failed to send verification email. Please try again later.', 'danger')
            
            return redirect(url_for('main.dashboard'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Resend verification error: {str(e)}')
            flash('An error occurred. Please try again.', 'danger')
    
    return render_template('auth/resend_verification.html')