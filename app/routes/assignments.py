import os
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_file, abort
from app.utils.app_time import app_now
from sqlalchemy.orm import joinedload, selectinload
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import (
    Course,
    Student,
    Enrollment,
    Assignment,
    AssignmentSubmission,
    AssignmentAttachment,
    Module,
    Lecturer,
)
from http import HTTPStatus
from app.utils.access_control import (
    require_module_access,
    require_lecturer_assigned_to_module,
    can_edit_module_content,
)
from app.services.notification_service import NotificationService
from app.services import storage_supabase
import mimetypes
from flask import Response

assignments_bp = Blueprint('assignments', __name__, url_prefix='/assignments')

# Store current time for template use (Johannesburg wall clock)
now = app_now

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'zip', 'png', 'jpg', 'jpeg'}

MAX_SPEC_FILES_PER_ASSIGNMENT = 15

_DUE_DATE_FORMATS = (
    '%Y-%m-%dT%H:%M',
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d',
)


def parse_due_date(raw: str):
    """Parse HTML datetime-local and common variants; return datetime or None."""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    for fmt in _DUE_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_upload_path():
    """Get or create upload directory for assignments."""
    upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER'), 'assignments')
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    return upload_dir


def get_specs_upload_dir(assignment_id: int) -> str:
    """Directory for lecturer-uploaded assignment handouts (per assignment)."""
    d = os.path.join(get_upload_path(), 'specs', str(assignment_id))
    os.makedirs(d, exist_ok=True)
    return d


def _save_assignment_spec_files(assignment: Assignment, files) -> tuple:
    """
    Persist uploaded spec files for a new assignment. Returns (saved_count, skipped_messages).
    """
    saved = 0
    messages = []
    if not files:
        return 0, messages
    for f in files:
        if saved >= MAX_SPEC_FILES_PER_ASSIGNMENT:
            messages.append(f'Maximum {MAX_SPEC_FILES_PER_ASSIGNMENT} files per assignment.')
            break
        if not f or not getattr(f, 'filename', None) or f.filename == '':
            continue
        if not allowed_file(f.filename):
            messages.append(f'Skipped unsupported type: {f.filename}')
            continue
        orig_name = secure_filename(f.filename)
        if not orig_name:
            continue
        ts = app_now().strftime('%Y%m%d_%H%M%S')
        unique_name = f'{ts}_{saved}_{orig_name}'
        dest = os.path.join(get_specs_upload_dir(assignment.id), unique_name)
        stored_ref = None
        if storage_supabase.enabled():
            data = f.read()
            key = f"assignments/specs/{assignment.id}/{unique_name}"
            storage_supabase.put_bytes(key=key, data=data)
            stored_ref = storage_supabase.make_ref(key)
        else:
            f.save(dest)
        db.session.add(
            AssignmentAttachment(
                assignment_id=assignment.id,
                file_path=(stored_ref or dest),
                file_name=orig_name,
            )
        )
        saved += 1
    return saved, messages


def _candidate_upload_roots():
    """Upload roots to try when locating existing submission files."""
    roots = []
    cfg_root = current_app.config.get("UPLOAD_FOLDER")
    if cfg_root:
        roots.append(cfg_root)
    # also try both historical locations relative to this file
    routes_dir = os.path.dirname(os.path.abspath(__file__))  # .../app/routes
    app_pkg_dir = os.path.dirname(routes_dir)  # .../app
    roots.append(os.path.join(app_pkg_dir, "static", "uploads"))
    roots.append(os.path.join(app_pkg_dir, "app", "static", "uploads"))
    seen = set()
    out = []
    for r in roots:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def check_assignment_access(module_id: int, require_edit: bool = False) -> tuple:
    """Verify access to assignments for module."""
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


@assignments_bp.route('/')
@login_required
def index():
    """Student assignments list - shows all assignments across enrolled courses."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first_or_404()
    
    # Get all enrollments
    enrollments = Enrollment.query.filter_by(student_id=student.id, status='active').all()
    
    # Get assignments for each course through modules
    course_assignments = {}
    for enrollment in enrollments:
        course = Course.query.get(enrollment.course_id)
        if course:
            # Get assignments from all modules in this course
            for module in course.modules:
                assignments = Assignment.query.filter_by(module_id=module.id).all()
                for assignment in assignments:
                    # Get submission if exists
                    submission = AssignmentSubmission.query.filter_by(
                        assignment_id=assignment.id,
                        student_id=student.id
                    ).first()
                    
                    if course.id not in course_assignments:
                        course_assignments[course.id] = {
                            'course': course,
                            'assignments': []
                        }
                    
                    course_assignments[course.id]['assignments'].append({
                        'assignment': assignment,
                        'module': module,
                        'submission': submission,
                        'status': 'submitted' if submission else 'pending',
                        'graded': bool(submission and submission.mark is not None),
                    })
    
    return render_template(
        'assignments.html',
        course_assignments=course_assignments,
        now=app_now()
    )


@assignments_bp.route('/<int:assignment_id>')
@login_required
def view(assignment_id):
    """View assignment details and submission status."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first_or_404()
    assignment = (
        Assignment.query.options(selectinload(Assignment.attachments))
        .get_or_404(assignment_id)
    )
    
    # Require active enrollment (through module)
    ctx = require_module_access(assignment.module_id)
    if not ctx.has_access:
        flash('You are not enrolled in this course.', 'danger')
        return redirect(url_for('assignments.index'))
    
    # Get submission
    submission = AssignmentSubmission.query.filter_by(
        assignment_id=assignment_id,
        student_id=student.id
    ).first()
    
    return render_template(
        'assignment_detail.html',
        assignment=assignment,
        course=assignment.module.course if assignment.module else None,
        module=assignment.module,
        submission=submission,
        now=app_now()
    )


@assignments_bp.route('/<int:assignment_id>/submit', methods=['GET', 'POST'])
@login_required
def submit(assignment_id):
    """Submit assignment."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first_or_404()
    assignment = (
        Assignment.query.options(selectinload(Assignment.attachments))
        .get_or_404(assignment_id)
    )
    
    # Require active enrollment
    ctx = require_module_access(assignment.module_id)
    if not ctx.has_access:
        flash('You are not enrolled in this course.', 'danger')
        return redirect(url_for('assignments.index'))
    
    # Check if already submitted
    existing = AssignmentSubmission.query.filter_by(
        assignment_id=assignment_id,
        student_id=student.id
    ).first()
    
    if request.method == 'POST':
        file = request.files.get('file')
        
        if not file or file.filename == '':
            flash('Please select a file to upload.', 'warning')
            return redirect(request.url)
        
        if not allowed_file(file.filename):
            flash('Invalid file type. Allowed: PDF, DOC, DOCX, TXT, ZIP, PNG, JPG', 'danger')
            return redirect(request.url)
        
        filename = secure_filename(file.filename)
        
        # Create student-specific subfolder
        student_dir = os.path.join(get_upload_path(), str(student.id))
        if not os.path.exists(student_dir):
            os.makedirs(student_dir)
        
        # Save file with unique name
        timestamp = app_now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{assignment.id}_{timestamp}_{filename}"
        file_path = os.path.join(student_dir, unique_filename)
        stored_ref = None
        if storage_supabase.enabled():
            data = file.read()
            key = f"assignments/submissions/{assignment.id}/{student.id}/{unique_filename}"
            storage_supabase.put_bytes(key=key, data=data)
            stored_ref = storage_supabase.make_ref(key)
        else:
            file.save(file_path)
        
        # Create or update submission
        if existing:
            # Delete old file
            if existing.file_path:
                parsed = storage_supabase.parse_ref(existing.file_path)
                if parsed and storage_supabase.enabled():
                    try:
                        storage_supabase.delete(existing.file_path)
                    except Exception:
                        pass
                elif os.path.exists(existing.file_path):
                    os.remove(existing.file_path)
            existing.file_path = (stored_ref or file_path)
            existing.file_name = filename
            existing.submitted_at = app_now()
            existing.status = 'submitted'
            flash('Assignment resubmitted successfully!', 'success')
        else:
            submission = AssignmentSubmission(
                assignment_id=assignment_id,
                student_id=student.id,
                file_path=(stored_ref or file_path),
                file_name=filename,
                status='submitted'
            )
            db.session.add(submission)
            flash('Assignment submitted successfully!', 'success')
        
        db.session.commit()
        return redirect(url_for('assignments.view', assignment_id=assignment_id))
    
    return render_template(
        'assignment_submit.html',
        assignment=assignment,
        course=assignment.module.course if assignment.module else None,
        module=assignment.module,
        submission=existing,
        now=app_now()
    )


# Lecturer routes
@assignments_bp.route('/module/<int:module_id>/manage')
@login_required
def manage_module(module_id: int):
    """Manage assignments for a module - lecturer view."""
    module, course, _, can_edit = check_assignment_access(module_id)
    
    if not can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    assignments = (
        Assignment.query.options(selectinload(Assignment.attachments))
        .filter_by(module_id=module_id)
        .all()
    )
    
    # Get submission counts
    for assignment in assignments:
        assignment.submitted_count = AssignmentSubmission.query.filter_by(
            assignment_id=assignment.id
        ).count()
        assignment.graded_count = AssignmentSubmission.query.filter(
            AssignmentSubmission.assignment_id == assignment.id,
            AssignmentSubmission.mark.isnot(None)
        ).count()
    
    return render_template(
        'lecturer/assignment_manage.html',
        course=course,
        module=module,
        assignments=assignments
    )


@assignments_bp.route('/module/<int:module_id>/create', methods=['GET', 'POST'])
@login_required
def create(module_id: int):
    """Create new assignment for a module."""
    module, course, _, can_edit = check_assignment_access(module_id, require_edit=True)
    
    if not can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        due_date = request.form.get('due_date')
        try:
            total_marks = float(request.form.get('total_marks') or 100)
        except (TypeError, ValueError):
            total_marks = 100.0
        
        if not title:
            flash('Title is required.', 'warning')
            return redirect(request.url)
        
        due_date_obj = parse_due_date(due_date) if due_date else None
        
        assignment = Assignment(
            module_id=module_id,
            title=title,
            description=description,
            due_date=due_date_obj,
            total_marks=total_marks
        )
        db.session.add(assignment)
        skip_file_msgs = []
        try:
            db.session.flush()
            spec_files = request.files.getlist('spec_files')
            _, skip_file_msgs = _save_assignment_spec_files(assignment, spec_files)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('assignment create or spec file save failed')
            flash('Could not create the assignment or save attached files. Please try again.', 'danger')
            return redirect(request.url)

        for msg in skip_file_msgs:
            flash(msg, 'warning')

        # Notify enrolled students (course-level enrollment) that a new assignment is available
        try:
            if current_user.role == 'lecturer':
                lecturer = Lecturer.query.filter_by(user_id=current_user.id).first()
            else:
                lecturer = None
            enrollments = Enrollment.query.filter_by(course_id=course.id, status='active').all()
            students = [e.student for e in enrollments if e.student and e.student.user]
            if students:
                NotificationService.notify_assignment_posted(
                    lecturer=lecturer,
                    course=course,
                    module=module,
                    assignment=assignment,
                    students=students
                )
        except Exception:
            current_app.logger.exception('notify_assignment_posted failed (assignment was saved)')
        
        flash('Assignment created successfully!', 'success')
        return redirect(url_for('assignments.manage_module', module_id=module_id))
    
    return render_template(
        'lecturer/assignment_create.html',
        course=course,
        module=module
    )


@assignments_bp.route('/submissions/<int:assignment_id>')
@login_required
def view_submissions(assignment_id):
    """View all submissions for an assignment - lecturer view."""
    assignment = (
        Assignment.query.options(selectinload(Assignment.attachments))
        .get_or_404(assignment_id)
    )
    module = Module.query.get_or_404(assignment.module_id)
    
    # Check access
    _, course, _, can_edit = check_assignment_access(module.id)
    
    if not can_edit:
        flash('You do not have permission to view these submissions.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Get all submissions with student info
    submissions = (
        AssignmentSubmission.query.options(
            joinedload(AssignmentSubmission.student).joinedload(Student.user)
        )
        .filter_by(assignment_id=assignment_id)
        .all()
    )
    graded_submission_count = sum(1 for s in submissions if s.mark is not None)
    
    return render_template(
        'lecturer/assignment_submissions.html',
        assignment=assignment,
        course=course,
        module=module,
        submissions=submissions,
        graded_submission_count=graded_submission_count,
    )


@assignments_bp.route('/submissions/<int:submission_id>/download')
@login_required
def download_submission(submission_id):
    """Download a student submission file."""
    submission = AssignmentSubmission.query.get_or_404(submission_id)
    assignment = Assignment.query.get(submission.assignment_id)
    module = Module.query.get(assignment.module_id)
    
    # Check access
    _, _, _, can_edit = check_assignment_access(module.id)
    
    if not can_edit:
        flash('You do not have permission to download this file.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    file_path = submission.file_path
    parsed = storage_supabase.parse_ref(file_path or "")
    if parsed and storage_supabase.enabled():
        try:
            data = storage_supabase.get_bytes(file_path)
        except FileNotFoundError:
            flash('File not found (it may have been moved or deleted).', 'warning')
            return redirect(url_for('assignments.view_submissions', assignment_id=assignment.id))
        except Exception:
            current_app.logger.exception("Supabase download_submission failed")
            flash('Could not download this file right now. Please try again.', 'danger')
            return redirect(url_for('assignments.view_submissions', assignment_id=assignment.id))

        resp = Response(data)
        resp.headers["Content-Type"] = mimetypes.guess_type(submission.file_name or "")[0] or "application/octet-stream"
        resp.headers["Content-Disposition"] = f'attachment; filename="{submission.file_name or "submission"}"'
        return resp
    if not file_path or not os.path.exists(file_path):
        # Try to recover from previous upload-folder locations.
        # Keep the filename if the stored path is absolute but root changed.
        basename = os.path.basename(file_path) if file_path else None
        student_dir = os.path.basename(os.path.dirname(file_path)) if file_path else None

        recovered = None
        if basename:
            for root in _candidate_upload_roots():
                # Most common: UPLOAD_FOLDER/assignments/<student_id>/<filename>
                if student_dir:
                    candidate = os.path.join(root, "assignments", student_dir, basename)
                    if os.path.exists(candidate):
                        recovered = candidate
                        break
                # Fallback: UPLOAD_FOLDER/assignments/<filename>
                candidate2 = os.path.join(root, "assignments", basename)
                if os.path.exists(candidate2):
                    recovered = candidate2
                    break

        if not recovered:
            flash('File not found (it may have been moved or deleted).', 'warning')
            return redirect(url_for('assignments.view_submissions', assignment_id=assignment.id))

        file_path = recovered
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=submission.file_name,
    )


@assignments_bp.route('/attachments/<int:attachment_id>/download')
@login_required
def download_assignment_attachment(attachment_id):
    """Download a lecturer-uploaded assignment handout (students and authorized staff)."""
    att = AssignmentAttachment.query.get_or_404(attachment_id)
    assignment = Assignment.query.get_or_404(att.assignment_id)

    if current_user.role == 'student':
        student = Student.query.filter_by(user_id=current_user.id).first_or_404()
        if not assignment.can_access(student):
            abort(HTTPStatus.FORBIDDEN)
    elif current_user.role in ('lecturer', 'admin'):
        _, _, _, allowed = check_assignment_access(assignment.module_id)
        if not allowed:
            abort(HTTPStatus.FORBIDDEN)
    else:
        abort(HTTPStatus.FORBIDDEN)

    file_path = att.file_path
    parsed = storage_supabase.parse_ref(file_path or "")
    if parsed and storage_supabase.enabled():
        try:
            data = storage_supabase.get_bytes(file_path)
        except FileNotFoundError:
            flash('File not found (it may have been moved or deleted).', 'warning')
            if current_user.role == 'student':
                return redirect(url_for('assignments.view', assignment_id=assignment.id))
            return redirect(url_for('assignments.view_submissions', assignment_id=assignment.id))
        except Exception:
            current_app.logger.exception("Supabase download_assignment_attachment failed")
            flash('Could not download this file right now. Please try again.', 'danger')
            if current_user.role == 'student':
                return redirect(url_for('assignments.view', assignment_id=assignment.id))
            return redirect(url_for('assignments.view_submissions', assignment_id=assignment.id))

        resp = Response(data)
        resp.headers["Content-Type"] = mimetypes.guess_type(att.file_name or "")[0] or "application/octet-stream"
        resp.headers["Content-Disposition"] = f'attachment; filename="{att.file_name or "attachment"}"'
        return resp
    if not file_path or not os.path.isfile(file_path):
        basename = os.path.basename(file_path) if file_path else None
        recovered = None
        if basename:
            spec_dir = str(assignment.id)
            for root in _candidate_upload_roots():
                candidate = os.path.join(root, 'assignments', 'specs', spec_dir, basename)
                if os.path.isfile(candidate):
                    recovered = candidate
                    break
        if not recovered:
            flash('File not found (it may have been moved or deleted).', 'warning')
            if current_user.role == 'student':
                return redirect(url_for('assignments.view', assignment_id=assignment.id))
            return redirect(url_for('assignments.view_submissions', assignment_id=assignment.id))
        file_path = recovered

    return send_file(
        file_path,
        as_attachment=True,
        download_name=att.file_name or os.path.basename(file_path),
    )


@assignments_bp.route('/submissions/<int:submission_id>/grade', methods=['GET', 'POST'])
@login_required
def grade_submission(submission_id):
    """Grade a student submission."""
    submission = (
        AssignmentSubmission.query.options(
            joinedload(AssignmentSubmission.student).joinedload(Student.user)
        ).get_or_404(submission_id)
    )
    assignment = Assignment.query.get(submission.assignment_id)
    module = Module.query.get(assignment.module_id)
    
    # Check access
    _, course, _, can_edit = check_assignment_access(module.id)
    
    if not can_edit:
        flash('You do not have permission to grade this submission.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        mark = request.form.get('mark')
        feedback = request.form.get('feedback', '').strip()
        
        if not mark:
            flash('Mark is required.', 'warning')
            return redirect(request.url)
        
        try:
            mark_value = float(mark)
            if mark_value < 0 or mark_value > assignment.total_marks:
                flash(f'Mark must be between 0 and {assignment.total_marks}.', 'warning')
                return redirect(request.url)
        except ValueError:
            flash('Invalid mark value.', 'warning')
            return redirect(request.url)
        
        submission.mark = mark_value
        submission.feedback = feedback
        submission.status = 'graded'
        submission.graded_at = app_now()
        submission.graded_by = current_user.id
        submission.grade = submission.calculate_grade()
        
        db.session.commit()
        flash('Submission graded successfully!', 'success')
        return redirect(url_for('assignments.view_submissions', assignment_id=assignment.id))
    
    return render_template(
        'lecturer/assignment_grade.html',
        submission=submission,
        assignment=assignment,
        course=course,
        module=module
    )


@assignments_bp.route('/module/<int:module_id>')
@login_required
def module_list(module_id: int):
    """List assignments for a module - redirects to manage for lecturers, or shows student view."""
    module, course, student, can_edit = check_assignment_access(module_id)
    
    if can_edit:
        # Lecturers go to management view
        return redirect(url_for('assignments.manage_module', module_id=module_id))
    
    # Students see assignments for this module
    assignments = Assignment.query.filter_by(module_id=module_id).all()
    
    # Get submissions
    assignment_data = []
    for assignment in assignments:
        submission = AssignmentSubmission.query.filter_by(
            assignment_id=assignment.id,
            student_id=student.id
        ).first() if student else None
        
        assignment_data.append({
            'assignment': assignment,
            'submission': submission,
            'status': 'submitted' if submission else 'pending',
            'graded': bool(submission and submission.mark is not None),
        })
    
    return render_template(
        'assignments.html',
        course_assignments={
            course.id: {
                'course': course,
                'module': module,
                'assignments': assignment_data
            }
        },
        current_module=module,
        current_course=course,
        now=app_now()
    )


@assignments_bp.route('/course/<int:course_id>/overview')
@login_required
def course_overview(course_id: int):
    """
    Per-course assignment hub: lecturers see every module they teach in this course;
    students see all assignments for an enrolled course; admins see all modules.
    """
    course = Course.query.get_or_404(course_id)

    if current_user.role == 'admin':
        modules = Module.query.filter_by(course_id=course_id).order_by(Module.order).all()
        return render_template(
            'lecturer/assignment_course_overview.html',
            course=course,
            modules=modules,
            viewer_role='admin',
        )

    if current_user.role == 'lecturer':
        lecturer = Lecturer.query.filter_by(user_id=current_user.id).first_or_404()
        if not lecturer.is_assigned_to_course(course_id):
            flash('You are not assigned to any module in this course.', 'danger')
            return redirect(url_for('main.lecturer_dashboard'))
        modules = sorted(
            lecturer.get_assigned_modules(course_id=course_id),
            key=lambda m: (m.order or 0, m.id),
        )
        return render_template(
            'lecturer/assignment_course_overview.html',
            course=course,
            modules=modules,
            viewer_role='lecturer',
        )

    if current_user.role == 'student':
        student = Student.query.filter_by(user_id=current_user.id).first_or_404()
        enrollment = Enrollment.query.filter_by(
            student_id=student.id,
            course_id=course_id,
            status='active',
        ).first()
        if not enrollment:
            flash('You are not enrolled in this course.', 'warning')
            return redirect(url_for('courses.index'))

        course_assignments = {course.id: {'course': course, 'assignments': []}}
        ordered_modules = Module.query.filter_by(course_id=course_id).order_by(Module.order).all()
        for module in ordered_modules:
            for assignment in Assignment.query.filter_by(module_id=module.id).all():
                submission = AssignmentSubmission.query.filter_by(
                    assignment_id=assignment.id,
                    student_id=student.id,
                ).first()
                course_assignments[course.id]['assignments'].append({
                    'assignment': assignment,
                    'module': module,
                    'submission': submission,
                    'status': 'submitted' if submission else 'pending',
                    'graded': bool(submission and submission.mark is not None),
                })

        return render_template(
            'assignments.html',
            course_assignments=course_assignments,
            now=app_now(),
        )

    flash('Access denied.', 'danger')
    return redirect(url_for('main.dashboard'))


# Legacy route redirects for backward compatibility
@assignments_bp.route('/course/<int:course_id>')
@login_required
def course_list_legacy(course_id: int):
    """Redirect old course-based assignment URLs to first module."""
    # Find first module in course
    module = Module.query.filter_by(course_id=course_id).order_by(Module.order).first()
    if module:
        return redirect(url_for('assignments.module_list', module_id=module.id))
    
    flash('No modules found in this course.', 'warning')
    return redirect(url_for('courses.detail', course_id=course_id))


@assignments_bp.route('/course/<int:course_id>/manage')
@login_required
def manage_course_legacy(course_id: int):
    """Redirect old course-based assignment management URLs to first module."""
    # Find first module in course
    module = Module.query.filter_by(course_id=course_id).order_by(Module.order).first()
    if module:
        return redirect(url_for('assignments.manage_module', module_id=module.id))
    
    flash('No modules found in this course.', 'warning')
    return redirect(url_for('courses.detail', course_id=course_id))


@assignments_bp.route('/course/<int:course_id>/create', methods=['GET', 'POST'])
@login_required
def create_course_legacy(course_id: int):
    """Redirect old course-based assignment creation URLs to first module."""
    # Find first module in course
    module = Module.query.filter_by(course_id=course_id).order_by(Module.order).first()
    if module:
        return redirect(url_for('assignments.create', module_id=module.id))
    
    flash('No modules found in this course.', 'warning')
    return redirect(url_for('courses.detail', course_id=course_id))
