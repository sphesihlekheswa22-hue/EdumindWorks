from datetime import datetime
from typing import List, Optional, Union
from app.utils.app_time import app_now, app_today
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, current_app
)
from flask_login import login_required, current_user
from http import HTTPStatus

from app import db
from app.models import Course, Module, Enrollment, Student, Lecturer, CourseMaterial, Quiz
from app.models.lecturer import LecturerModule
from app.forms.auth_forms import FlaskForm, StringField, TextAreaField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Optional as OptionalValidator

courses_bp = Blueprint('courses', __name__, url_prefix='/courses')


class CourseForm(FlaskForm):
    """Course creation/editing form."""
    code = StringField('Course Code', validators=[DataRequired()])
    name = StringField('Course Name', validators=[DataRequired()])
    description = TextAreaField('Description')
    credits = IntegerField('Credits', default=3)
    semester = StringField('Semester (e.g., Fall 2024)')
    year = IntegerField('Year', default=2024)
    submit = SubmitField('Save Course')


class ModuleForm(FlaskForm):
    """Module creation/editing form."""
    title = StringField('Module Title', validators=[DataRequired()])
    description = TextAreaField('Description')
    order = IntegerField('Order', default=0)
    submit = SubmitField('Save Module')


def get_course_or_404(course_id: int) -> Course:
    """Fetch course with 404 handling."""
    return Course.query.get_or_404(course_id)


def check_course_edit_permission(course: Course) -> bool:
    """
    Verify user has permission to edit course structure.
    Only admins can edit courses.
    Lecturers manage modules, not courses.
    """
    if current_user.role == 'admin':
        return True
    
    # Lecturers cannot edit course-level details
    return False


def get_student_enrollment(course_id: int) -> tuple:
    """Get student and enrollment for course access check."""
    student: Student = Student.query.filter_by(
        user_id=current_user.id
    ).first_or_404()
    
    enrollment: Optional[Enrollment] = Enrollment.query.filter_by(
        student_id=student.id,
        course_id=course_id
    ).first()
    
    return student, enrollment


@courses_bp.route('/')
@login_required
def index() -> str:
    """List courses based on user role."""
    context = {}
    
    if current_user.role == 'student':
        student: Student = Student.query.filter_by(
            user_id=current_user.id
        ).first_or_404()
        
        # Students can only view their active enrolled course(s) (institutional LMS).
        enrollments: List[Enrollment] = Enrollment.query.filter_by(
            student_id=student.id,
            status='active',
        ).all()

        enrolled_ids: List[int] = [e.course_id for e in enrollments]

        courses_q: List[Course] = []
        if enrolled_ids:
            courses_q = Course.query.filter(Course.id.in_(enrolled_ids)).order_by(Course.name).all()
        
        context.update({
            'courses': courses_q,
            'enrolled_course_ids': enrolled_ids,
            'enrollments': {e.course_id: e for e in enrollments}
        })
        
    elif current_user.role == 'lecturer':
        # Lecturers see courses where they teach at least one module
        lecturer: Lecturer = Lecturer.query.filter_by(
            user_id=current_user.id
        ).first_or_404()
        
        # Get courses through module assignments
        teaching_courses: List[Course] = lecturer.get_teaching_courses()
        
        context.update({
            'courses': teaching_courses,
            'is_lecturer_view': True
        })
        
    else:  # admin
        all_courses = Course.query.order_by(
            Course.created_at.desc()
        ).all()
        
        context.update({
            'courses': all_courses,
            'is_admin_view': True
        })
    
    return render_template('courses.html', **context)


@courses_bp.route('/<int:course_id>')
@login_required
def detail(course_id: int) -> str:
    """Course detail page with role-based content."""
    course: Course = get_course_or_404(course_id)
    
    is_enrolled: bool = False
    enrollment: Optional[Enrollment] = None
    active_enrollment_other_course: Optional[Enrollment] = None
    active_enrolled_course: Optional[Course] = None
    
    if current_user.role == 'student':
        _, enrollment = get_student_enrollment(course_id)
        is_enrolled = enrollment is not None and enrollment.status == 'active'
        
        # Check for active enrollment in another course (for single-course restriction)
        if not is_enrolled:
            student: Student = Student.query.filter_by(
                user_id=current_user.id
            ).first()
            if student:
                active_enrollment_other_course = Enrollment.query.filter_by(
                    student_id=student.id,
                    status='active'
                ).first()
                if active_enrollment_other_course:
                    active_enrolled_course = Course.query.get(
                        active_enrollment_other_course.course_id
                    )
        
        # For non-enrolled students, only show active courses with limited content
        if not is_enrolled and not course.is_active:
            # Show course page but hide restricted content
            pass
    
    # Get modules ordered
    modules: List[Module] = Module.query.filter_by(
        course_id=course_id
    ).order_by(Module.order).all()
    
    # Get module-level content counts
    materials_count: int = 0
    quizzes_count: int = 0
    
    for module in modules:
        materials_count += len([m for m in module.materials if m.is_published])
        quizzes_count += len([q for q in module.quizzes if q.is_published])
    
    # Lecturer-specific: pick a sensible default module (assigned to the lecturer) for instructor tools
    lecturer_default_module = None
    if current_user.role == 'lecturer':
        lecturer = Lecturer.query.filter_by(user_id=current_user.id).first()
        if lecturer:
            lecturer_default_module = (
                Module.query.join(LecturerModule, LecturerModule.module_id == Module.id)
                .filter(LecturerModule.lecturer_id == lecturer.id, Module.course_id == course_id)
                .order_by(Module.order)
                .first()
            )

    # Prefer admin-assigned primary lecturer for display; fall back to module lecturers.
    primary_lecturer = course.get_primary_lecturer()
    lecturers = [primary_lecturer] if primary_lecturer else course.get_lecturers()
    
    lecturers_all = []
    if current_user.role == "admin":
        from app.models.user import User
        lecturers_all = (
            Lecturer.query.join(User, Lecturer.user_id == User.id)
            .filter(User.role == "lecturer")
            .order_by(User.first_name.asc(), User.last_name.asc())
            .all()
        )

    return render_template(
        'course_detail.html',
        course=course,
        is_enrolled=is_enrolled,
        enrollment=enrollment,
        modules=modules,
        materials_count=materials_count,
        quizzes_count=quizzes_count,
        lecturers=lecturers,
        lecturers_all=lecturers_all,
        active_enrolled_course=active_enrolled_course,
        lecturer_default_module=lecturer_default_module
    )


@courses_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create() -> Union[str, redirect]:
    """Create new course."""
    if current_user.role != 'admin':
        abort(HTTPStatus.FORBIDDEN)
    
    form = CourseForm()
    
    if form.validate_on_submit():
        try:
            course = Course(
                code=form.code.data.strip().upper(),
                name=form.name.data.strip(),
                description=form.description.data.strip() if form.description.data else None,
                credits=form.credits.data or 3,
                semester=form.semester.data.strip() if form.semester.data else None,
                year=form.year.data or app_today().year,
                # REMOVED: lecturer_id - courses don't have single lecturers
            )
            
            db.session.add(course)
            db.session.commit()
            
            flash(f'Course "{course.name}" created successfully!', 'success')
            return redirect(url_for('courses.detail', course_id=course.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Course creation error: {str(e)}')
            flash('Error creating course. Please try again.', 'danger')
    
    return render_template(
        'course_form.html',
        form=form,
        action='Create'
    )


@courses_bp.route('/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(course_id: int) -> Union[str, redirect]:
    """Edit existing course."""
    course: Course = get_course_or_404(course_id)
    
    if not check_course_edit_permission(course):
        abort(HTTPStatus.FORBIDDEN)
    
    form = CourseForm(obj=course)
    
    if form.validate_on_submit():
        try:
            course.code = form.code.data.strip().upper()
            course.name = form.name.data.strip()
            course.description = form.description.data.strip() if form.description.data else None
            course.credits = form.credits.data or 3
            course.semester = form.semester.data.strip() if form.semester.data else None
            course.year = form.year.data or app_today().year
            
            db.session.commit()
            
            flash(f'Course "{course.name}" updated successfully!', 'success')
            return redirect(url_for('courses.detail', course_id=course.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Course update error: {str(e)}')
            flash('Error updating course. Please try again.', 'danger')
    
    return render_template(
        'course_form.html',
        form=form,
        action='Edit',
        course=course
    )


@courses_bp.route('/<int:course_id>/enroll', methods=['POST'])
@login_required
def enroll(course_id: int) -> redirect:
    """Enroll student in course."""
    if current_user.role != 'student':
        flash('Only students can enroll in courses.', 'danger')
        return redirect(url_for('courses.detail', course_id=course_id))
    
    course: Course = get_course_or_404(course_id)
    student: Student = Student.query.filter_by(
        user_id=current_user.id
    ).first_or_404()
    
    try:
        # Check for existing active enrollment in ANY course (single-course restriction)
        active_enrollment: Optional[Enrollment] = Enrollment.query.filter_by(
            student_id=student.id,
            status='active'
        ).first()
        
        if active_enrollment and active_enrollment.course_id != course_id:
            # Student already enrolled in a different course
            enrolled_course: Course = Course.query.get(active_enrollment.course_id)
            flash(f'You are already enrolled in "{enrolled_course.name}". Please cancel your current enrollment before enrolling in a new course.', 'warning')
            return redirect(url_for('courses.detail', course_id=course_id))
        
        # Check existing enrollment in THIS course
        existing: Optional[Enrollment] = Enrollment.query.filter_by(
            student_id=student.id,
            course_id=course_id
        ).first()
        
        if existing:
            if existing.status == 'active':
                flash('You are already enrolled in this course.', 'info')
            elif existing.status == 'dropped':
                existing.status = 'active'
                existing.enrolled_at = app_now()
                db.session.commit()
                
                # Create module progress records for new enrollment
                _create_module_progress_records(existing)
                
                flash('Re-enrolled successfully!', 'success')
            else:  # completed
                flash('You have completed this course. Contact admin to re-enroll.', 'warning')
        else:
            enrollment = Enrollment(
                student_id=student.id,
                course_id=course_id,
                status='active'
            )
            db.session.add(enrollment)
            db.session.commit()
            
            # Create module progress records
            _create_module_progress_records(enrollment)
            
            flash(f'Successfully enrolled in {course.name}!', 'success')
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Enrollment error: {str(e)}')
        flash('Error enrolling in course. Please try again.', 'danger')
    
    return redirect(url_for('courses.detail', course_id=course_id))


def _create_module_progress_records(enrollment: Enrollment):
    """Create progress records for all modules in the course."""
    from app.models.student_module_progress import StudentModuleProgress
    
    modules = Module.query.filter_by(course_id=enrollment.course_id).all()
    for module in modules:
        progress = StudentModuleProgress(
            student_id=enrollment.student_id,
            module_id=module.id,
            enrollment_id=enrollment.id,
            completion_status='not_started'
        )
        db.session.add(progress)
    
    db.session.commit()


@courses_bp.route('/<int:course_id>/unenroll', methods=['POST'])
@login_required
def unenroll(course_id: int) -> redirect:
    """Unenroll student from course."""
    # Institutional LMS: students cannot cancel/drop enrollment themselves.
    abort(HTTPStatus.FORBIDDEN)
    
    student: Student = Student.query.filter_by(
        user_id=current_user.id
    ).first_or_404()
    
    enrollment: Optional[Enrollment] = Enrollment.query.filter_by(
        student_id=student.id,
        course_id=course_id,
        status='active'
    ).first()
    
    if not enrollment:
        flash('You are not enrolled in this course.', 'warning')
        return redirect(url_for('courses.detail', course_id=course_id))
    
    try:
        enrollment.status = 'dropped'
        db.session.commit()
        flash('Successfully unenrolled from course.', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Unenrollment error: {str(e)}')
        flash('Error processing unenrollment.', 'danger')
    
    return redirect(url_for('courses.detail', course_id=course_id))


@courses_bp.route('/modules')
@login_required
def all_modules():
    """List all modules for enrolled courses - student view."""
    if current_user.role != 'student':
        return redirect(url_for('courses.index'))

    student: Student = Student.query.filter_by(
        user_id=current_user.id
    ).first_or_404()

    enrollments: List[Enrollment] = Enrollment.query.filter_by(
        student_id=student.id, status='active'
    ).all()

    course_ids: List[int] = [e.course_id for e in enrollments]

    modules: List[Module] = Module.query.filter(
        Module.course_id.in_(course_ids)
    ).order_by(Module.course_id, Module.order).all()

    return render_template('modules.html', modules=modules)


@courses_bp.route('/modules/<int:module_id>')
@login_required
def module_hub(module_id: int):
    """
    Module hub page.
    
    Clicking a module should take the user to module-scoped content (assignments/quizzes/materials),
    not back to the course page.
    """
    from app.utils.access_control import require_module_access
    from app.models import Assignment, Quiz, CourseMaterial

    ctx = require_module_access(module_id)
    module = ctx.module
    course = ctx.course

    # Role-based edit capability: lecturers/admins can manage module content.
    can_edit = current_user.role in ["admin", "lecturer"]

    assignments_count = Assignment.query.filter_by(module_id=module_id).count()
    quizzes_count = Quiz.query.filter_by(module_id=module_id).count()
    materials_count = CourseMaterial.query.filter_by(module_id=module_id).count()

    return render_template(
        "module_hub.html",
        course=course,
        module=module,
        can_edit=can_edit,
        assignments_count=assignments_count,
        quizzes_count=quizzes_count,
        materials_count=materials_count,
    )


@courses_bp.route('/modules/content-management')
@login_required
def module_content_management() -> str:
    """
    Lecturer/Admin hub for module-level content management.
    Lecturers only see modules they are assigned to.
    """
    if current_user.role not in ['lecturer', 'admin']:
        abort(HTTPStatus.FORBIDDEN)

    modules: List[Module] = []
    if current_user.role == 'admin':
        modules = Module.query.order_by(Module.course_id, Module.order).all()
    else:
        lecturer: Lecturer = Lecturer.query.filter_by(user_id=current_user.id).first_or_404()
        modules = lecturer.get_assigned_modules()
        # Ensure stable ordering (by course then module order)
        modules = sorted(modules, key=lambda m: (m.course_id or 0, m.order or 0, m.id))

    # Group modules by course for nicer UI
    courses_map: dict[int, dict] = {}
    for m in modules:
        course = m.course
        if not course:
            continue
        if course.id not in courses_map:
            courses_map[course.id] = {"course": course, "modules": []}
        courses_map[course.id]["modules"].append(m)

    grouped = list(courses_map.values())
    grouped.sort(key=lambda x: (x["course"].name or "", x["course"].code or ""))

    return render_template('lecturer/module_content_management.html', grouped=grouped)


@courses_bp.route('/materials')
@login_required
def all_materials():
    """List all materials for enrolled courses - student view."""
    if current_user.role != 'student':
        return redirect(url_for('courses.index'))

    student: Student = Student.query.filter_by(
        user_id=current_user.id
    ).first_or_404()

    enrollments: List[Enrollment] = Enrollment.query.filter_by(
        student_id=student.id, status='active'
    ).all()

    course_ids: List[int] = [e.course_id for e in enrollments]

    modules: List[Module] = Module.query.filter(
        Module.course_id.in_(course_ids)
    ).all()

    materials = []
    for module in modules:
        for material in module.materials:
            if material.is_published:
                materials.append({
                    'material': material,
                    'module': module,
                    'course': module.course
                })

    return render_template('materials_all.html', materials=materials)


@courses_bp.route('/<int:course_id>/modules/create', methods=['GET', 'POST'])
@login_required
def create_module(course_id: int) -> Union[str, redirect]:
    """Create module for course."""
    
    course: Course = get_course_or_404(course_id)
    
    # Check permission - only admins or assigned lecturers can create modules
    can_edit = False
    if current_user.role == 'admin':
        can_edit = True
    elif current_user.role == 'lecturer':
        # Lecturers can create modules if they're teaching this course
        lecturer = Lecturer.query.filter_by(user_id=current_user.id).first_or_404()
        if lecturer.is_assigned_to_course(course_id):
            can_edit = True
    
    if not can_edit:
        flash('Permission denied: You cannot create modules for this course.', 'danger')
        return redirect(url_for('courses.detail', course_id=course_id))
    
    # Get existing modules
    existing_modules: List[Module] = Module.query.filter_by(
        course_id=course_id
    ).order_by(Module.order).all()

    # Lecturer options (admin can assign module lecturers at creation time)
    lecturers = []
    if current_user.role == "admin":
        from app.models.user import User
        lecturers = (
            Lecturer.query.join(User, Lecturer.user_id == User.id)
            .filter(User.role == "lecturer")
            .order_by(User.first_name.asc(), User.last_name.asc())
            .all()
        )
    
    # Calculate next order
    last_module: Optional[Module] = Module.query.filter_by(
        course_id=course_id
    ).order_by(Module.order.desc()).first()
    last_order = last_module.order if last_module and last_module.order is not None else 0
    next_order: int = last_order + 1
    
    # Initialize form
    form = ModuleForm()
    
    # Handle POST - use request.form directly for more control
    if request.method == 'POST':
        current_app.logger.info(f'POST REQUEST - Form data: {dict(request.form)}')
        
        # Get form data directly from request
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        
        if not title:
            flash('Module title is required!', 'danger')
            current_app.logger.error('ERROR: No title provided')
        else:
            try:
                # Get position type from request
                position_type = request.form.get('position_type', 'manual')
                relative_module_id = request.form.get('relative_module')
                
                # Determine order based on position_type (integer ordering only)
                # NOTE: Module.order is an Integer column, so we shift/reindex instead of using fractional values.
                if position_type == 'auto':
                    order = next_order
                elif position_type == 'first':
                    order = 1
                    for mod in existing_modules:
                        mod.order = (mod.order or 0) + 1
                elif position_type in ['after', 'before'] and relative_module_id:
                    ref_module = Module.query.get(int(relative_module_id))
                    if ref_module and ref_module.order is not None:
                        if position_type == 'after':
                            order = ref_module.order + 1
                        else:
                            order = max(1, ref_module.order)
                        # Shift modules at/after insertion point
                        for mod in existing_modules:
                            if mod.id == ref_module.id and position_type == 'after':
                                continue
                            if mod.order is not None and mod.order >= order:
                                mod.order += 1
                    else:
                        order = next_order
                else:
                    # Manual order from form (sanitize to integer)
                    order_val = request.form.get('order', '')
                    order = int(order_val) if order_val.isdigit() else next_order
                    if order < 1:
                        order = 1
                    for mod in existing_modules:
                        if mod.order is not None and mod.order >= order:
                            mod.order += 1
                
                module = Module(
                    course_id=course_id,
                    title=title,
                    description=description if description else None,
                    order=order
                )
                
                db.session.add(module)
                db.session.commit()
                
                # Lecturer assignment
                if current_user.role == 'admin':
                    from app.models.lecturer import LecturerModule

                    selected_ids = [int(x) for x in request.form.getlist("lecturer_ids") if str(x).isdigit()]
                    primary_id = request.form.get("primary_lecturer_id", type=int)

                    if primary_id and primary_id not in selected_ids:
                        selected_ids.append(primary_id)

                    # If none selected, default to course's assigned lecturer (if set)
                    if not selected_ids and course.lecturer_id:
                        selected_ids = [int(course.lecturer_id)]
                        primary_id = int(course.lecturer_id)

                    # Create lecturer-module links
                    if selected_ids:
                        for lid in sorted(set(selected_ids)):
                            lm = LecturerModule(
                                lecturer_id=lid,
                                module_id=module.id,
                                is_primary=(lid == primary_id) if primary_id else False,
                            )
                            db.session.add(lm)
                        db.session.commit()

                elif current_user.role == 'lecturer':
                    # If lecturer created module, auto-assign them as primary
                    lecturer = Lecturer.query.filter_by(user_id=current_user.id).first()
                    if lecturer:
                        lecturer.assign_to_module(module.id, is_primary=True)
                        db.session.commit()
                
                flash(f'Module "{module.title}" created successfully!', 'success')
                return redirect(url_for('courses.detail', course_id=course_id))
                
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f'Module creation error: {str(e)}')
                flash(f'Error creating module: {str(e)}', 'danger')
    
    # Set default order for GET request
    form.order.data = next_order
    
    return render_template('module_form.html', 
                         form=form, 
                         course=course, 
                         existing_modules=existing_modules, 
                         next_order=next_order,
                         lecturers=lecturers)


@courses_bp.route('/modules/<int:module_id>/assign-lecturer', methods=['POST'])
@login_required
def assign_lecturer_to_module(module_id: int) -> redirect:
    """Assign a lecturer to a module."""
    if current_user.role != 'admin':
        abort(HTTPStatus.FORBIDDEN)
    
    module = Module.query.get_or_404(module_id)
    lecturer_id = request.form.get('lecturer_id')
    is_primary = request.form.get('is_primary') == 'on'
    
    if not lecturer_id:
        flash('Please select a lecturer.', 'danger')
        return redirect(url_for('courses.detail', course_id=module.course_id))
    
    try:
        lecturer = Lecturer.query.get_or_404(int(lecturer_id))
        
        if lecturer.assign_to_module(module.id, is_primary=is_primary):
            db.session.commit()
            flash(f'{lecturer.full_name} assigned to module successfully!', 'success')
        else:
            flash('Lecturer is already assigned to this module.', 'info')
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Lecturer assignment error: {str(e)}')
        flash('Error assigning lecturer.', 'danger')
    
    return redirect(url_for('courses.detail', course_id=module.course_id))


@courses_bp.route('/modules/<int:module_id>/remove-lecturer/<int:lecturer_id>', methods=['POST'])
@login_required
def remove_lecturer_from_module(module_id: int, lecturer_id: int) -> redirect:
    """Remove a lecturer from a module."""
    if current_user.role != 'admin':
        abort(HTTPStatus.FORBIDDEN)
    
    module = Module.query.get_or_404(module_id)
    
    try:
        lecturer = Lecturer.query.get_or_404(lecturer_id)
        
        if lecturer.unassign_from_module(module.id):
            db.session.commit()
            flash(f'{lecturer.full_name} removed from module.', 'success')
        else:
            flash('Lecturer was not assigned to this module.', 'info')
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Lecturer removal error: {str(e)}')
        flash('Error removing lecturer.', 'danger')
    
    return redirect(url_for('courses.detail', course_id=module.course_id))