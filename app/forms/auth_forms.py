from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from flask_login import current_user
from wtforms import StringField, PasswordField, SubmitField, SelectField, DateField, TextAreaField, IntegerField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError, Regexp
from app.models import Student


class LoginForm(FlaskForm):
    """User login form."""
    institutional_id = StringField('Student/Staff Number', validators=[DataRequired(), Length(min=4, max=20)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = SelectField('Remember Me', choices=[
        ('yes', 'Yes'),
        ('no', 'No')
    ], default='no')
    submit = SubmitField('Login')


class StudentProfileForm(FlaskForm):
    """Student profile edits from /auth/profile (not first-time onboarding)."""
    student_id = StringField('Student ID', validators=[DataRequired(), Length(min=5, max=20)])
    date_of_birth = DateField('Date of Birth', validators=[Optional()])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    address = StringField('Address', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Save Profile')

    def validate_student_id(self, field):
        sid = (field.data or '').strip()
        if not current_user.is_authenticated:
            return
        other = Student.query.filter(
            Student.student_id == sid,
            Student.user_id != current_user.id,
        ).first()
        if other:
            raise ValidationError('This student number is already registered.')


class StudentCompleteProfileForm(FlaskForm):
    """First-time profile after registration (OTP): course, photo, 9-digit student number."""
    student_id = StringField(
        'Student number',
        validators=[
            DataRequired(),
            Regexp(r'^\d{9}$', message='Use your 9-digit student number (e.g. 220900983).'),
        ],
    )
    date_of_birth = DateField('Date of Birth', validators=[Optional()])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    address = StringField('Address', validators=[Optional(), Length(max=200)])
    course_id = SelectField(
        'Course enrollment',
        validators=[DataRequired(message='Please select a course.')],
        choices=[],
    )
    profile_photo = FileField(
        'Profile photo (optional)',
        validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'JPG, PNG, or WebP only.')],
    )
    submit = SubmitField('Save Profile')

    def validate_student_id(self, field):
        sid = (field.data or '').strip()
        if len(sid) != 9 or not sid.isdigit():
            return
        if not current_user.is_authenticated:
            return
        other = Student.query.filter(
            Student.student_id == sid,
            Student.user_id != current_user.id,
        ).first()
        if other:
            raise ValidationError('This student number is already registered.')


class LecturerProfileForm(FlaskForm):
    """Lecturer profile additional details form."""
    employee_id = StringField('Employee ID', validators=[DataRequired(), Length(min=5, max=20)])
    department = StringField('Department', validators=[Optional(), Length(max=100)])
    title = StringField('Title (e.g., Professor, Dr.)', validators=[Optional(), Length(max=50)])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    office = StringField('Office', validators=[Optional(), Length(max=50)])
    specialization = StringField('Specialization', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Save Profile')


class ForgotPasswordForm(FlaskForm):
    """Forgot password form to request reset link."""
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')


class ResetPasswordForm(FlaskForm):
    """Reset password form to set new password."""
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')


class OTPVerificationForm(FlaskForm):
    """OTP verification form."""
    otp_code = StringField('OTP Code', validators=[DataRequired(), Length(min=6, max=6)])
    submit = SubmitField('Verify OTP')
    
    def validate_otp_code(self, otp_code):
        """Validate OTP code is 6 digits."""
        if not otp_code.data.isdigit():
            raise ValidationError('OTP must contain only digits.')
        if len(otp_code.data) != 6:
            raise ValidationError('OTP must be exactly 6 digits.')
