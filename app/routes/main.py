from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from app.utils.app_time import app_now, app_today
from app.services.academic_service import build_student_academic_summary, active_module_ids_for_student
from app.services.risk_service import latest_quiz_results
from app.models import (
    User, Student, Lecturer, Course, Enrollment,
    Quiz, QuizResult, Attendance, Mark, StudyPlan, ChatSession, CVReview,
    AssignmentSubmission, Module,
)

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Home page."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard based on user role."""
    if current_user.role == 'student':
        return redirect(url_for('main.student_dashboard'))
    elif current_user.role == 'lecturer':
        return redirect(url_for('main.lecturer_dashboard'))
    elif current_user.role == 'admin':
        return redirect(url_for('main.admin_dashboard'))
    elif current_user.role == 'career_advisor':
        return redirect(url_for('main.career_advisor_dashboard'))
    else:
        flash('Unknown role. Please contact admin.', 'danger')
        return redirect(url_for('auth.logout'))


@main_bp.route('/dashboard/student')
@login_required
def student_dashboard():
    """Student dashboard."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('main.index'))
    if student.student_id and student.student_id.startswith('PENDING-'):
        flash('Please complete your profile to continue.', 'info')
        return redirect(url_for('auth.complete_student_profile'))

    # Get enrolled courses with progress and academic averages
    enrollments = Enrollment.query.filter_by(student_id=student.id, status='active').all()
    academic = build_student_academic_summary(student)
    summary_by_course = {
        row["course"].id: row for row in academic["course_summaries"]
    }
    enrolled_courses = []
    for e in enrollments:
        course_summary = summary_by_course.get(e.course_id, {})
        enrolled_courses.append({
            'course': e.course,
            'enrollment': e,
            'progress': e.get_overall_progress(),
            'academic_average': course_summary.get('average'),
        })
    
    # Get recent quiz results (scoped to active/pending enrollments)
    active_module_ids = active_module_ids_for_student(student.id)
    scoped_quiz_results = latest_quiz_results(
        student.id, module_ids=active_module_ids or None
    )
    recent_quizzes = sorted(
        scoped_quiz_results,
        key=lambda r: r.completed_at or datetime.min,
        reverse=True,
    )[:5]
    quizzes_taken = len(scoped_quiz_results)
    quizzes_passed = sum(1 for r in scoped_quiz_results if r.passed)
    
    # Get upcoming study plans
    study_plans = StudyPlan.query.filter_by(student_id=student.id, status='active')\
        .order_by(StudyPlan.created_at.desc()).limit(3).all()
    
    # Get recent chat sessions
    chat_sessions = ChatSession.query.filter_by(student_id=student.id)\
        .order_by(ChatSession.updated_at.desc()).limit(3).all()
    ai_session_count = ChatSession.query.filter_by(student_id=student.id).count()

    # Get upcoming assignments
    course_ids = [e.course_id for e in enrollments]
    if course_ids:
        from app.models import Assignment
        module_ids = [m.id for m in Module.query.filter(Module.course_id.in_(course_ids)).all()]
        upcoming_assignments = Assignment.query.filter(
            Assignment.module_id.in_(module_ids),
            Assignment.due_date.isnot(None),
            Assignment.due_date >= app_now()
        ).join(Assignment.module).join(Module.course).order_by(Assignment.due_date).limit(5).all()
    else:
        upcoming_assignments = []

    attendance_records = Attendance.query.filter_by(student_id=student.id).all()
    if course_ids:
        enrolled_module_ids = {
            module.id
            for module in Module.query.filter(Module.course_id.in_(course_ids)).all()
        }
        attendance_records = [
            record for record in attendance_records if record.module_id in enrolled_module_ids
        ]
    attendance_rate = 0
    if attendance_records:
        present = sum(1 for a in attendance_records if a.status == 'present')
        attendance_rate = (present / len(attendance_records)) * 100

    completed_assignments = AssignmentSubmission.query.filter_by(
        student_id=student.id, status='graded'
    ).count()

    return render_template(
        'student/dashboard_student.html',
        enrolled_courses=enrolled_courses,
        recent_quizzes=recent_quizzes,
        quizzes_taken=quizzes_taken,
        quizzes_passed=quizzes_passed,
        study_plans=study_plans,
        chat_sessions=chat_sessions,
        ai_session_count=ai_session_count,
        upcoming_assignments=upcoming_assignments,
        gpa=academic["gpa_4"],
        grade_percentage=academic["overall_percentage"],
        academic=academic,
        attendance_rate=round(attendance_rate, 1),
        completed_assignments=completed_assignments,
        overall_gpa=academic["gpa_4"],
        student=student,
    )


@main_bp.route('/dashboard/lecturer')
@login_required
def lecturer_dashboard():
    """Lecturer dashboard."""
    if current_user.role != 'lecturer':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    lecturer = Lecturer.query.filter_by(user_id=current_user.id).first()
    
    # Get teaching courses (through module assignments)
    courses = lecturer.get_teaching_courses()

    # Default module for quick actions: first module actually assigned to this lecturer
    assigned_modules = lecturer.get_assigned_modules()
    quick_action_module = assigned_modules[0] if assigned_modules else None

    # Pending grading count (ungraded assignment submissions for lecturer's assigned modules)
    from app.models.assignment import Assignment, AssignmentSubmission
    from app.models.course import Module
    module_ids = [m.id for m in lecturer.get_assigned_modules()]
    if module_ids:
        assignment_ids = [a.id for a in Assignment.query.filter(Assignment.module_id.in_(module_ids)).all()]
        pending_grading_count = (
            AssignmentSubmission.query.filter(
                AssignmentSubmission.assignment_id.in_(assignment_ids),
                AssignmentSubmission.mark.is_(None)
            ).count()
            if assignment_ids else 0
        )
    else:
        pending_grading_count = 0
    
    # Get total students
    total_students = sum(c.get_student_count() for c in courses)
    
    # Get recent quiz results for their courses (through modules)
    from app.models import Module
    course_ids = [c.id for c in courses]
    if course_ids:
        # Get module IDs for these courses
        module_ids = [m.id for m in Module.query.filter(Module.course_id.in_(course_ids)).all()]
        if module_ids:
            recent_quizzes = QuizResult.query.join(Quiz).filter(
                Quiz.module_id.in_(module_ids)
            ).order_by(QuizResult.completed_at.desc()).limit(5).all()
        else:
            recent_quizzes = []
    else:
        recent_quizzes = []
    
    # Engagement/insight metrics (course-wide across assigned modules)
    engagement_rate = 0.0
    submission_rate = 0.0
    quiz_average = 0.0
    avg_completion = 0.0

    if module_ids:
        # Quiz average (QuizResult percentage) across assigned modules
        quiz_average = db.session.query(db.func.avg(QuizResult.percentage)).join(
            Quiz, QuizResult.quiz_id == Quiz.id
        ).filter(Quiz.module_id.in_(module_ids)).scalar() or 0

        # Assignment submission rate
        if assignment_ids:
            enrolled_students = Enrollment.query.filter(
                Enrollment.course_id.in_([c.id for c in courses]),
                Enrollment.status == 'active'
            ).count()
            possible = enrolled_students * len(assignment_ids) if enrolled_students > 0 else 0
            submitted = AssignmentSubmission.query.filter(
                AssignmentSubmission.assignment_id.in_(assignment_ids)
            ).count()
            submission_rate = (submitted / possible * 100) if possible > 0 else 0

        # Engagement rate: fraction of students with any activity in last 14 days (quiz, submission, or attendance)
        cutoff = app_now() - timedelta(days=14)
        active_student_ids = set()

        # recent quizzes
        q_rows = QuizResult.query.join(Quiz).filter(
            Quiz.module_id.in_(module_ids),
            QuizResult.completed_at >= cutoff
        ).with_entities(QuizResult.student_id).all()
        active_student_ids.update([r[0] for r in q_rows])

        # recent submissions
        if assignment_ids:
            s_rows = AssignmentSubmission.query.filter(
                AssignmentSubmission.assignment_id.in_(assignment_ids),
                AssignmentSubmission.submitted_at >= cutoff
            ).with_entities(AssignmentSubmission.student_id).all()
            active_student_ids.update([r[0] for r in s_rows])

        # recent attendance
        a_rows = Attendance.query.filter(
            Attendance.module_id.in_(module_ids)
        ).with_entities(Attendance.student_id).all()
        active_student_ids.update([r[0] for r in a_rows])

        enrolled_student_ids = Enrollment.query.filter(
            Enrollment.course_id.in_([c.id for c in courses]),
            Enrollment.status == 'active'
        ).with_entities(Enrollment.student_id).distinct().all()
        enrolled_student_ids = {r[0] for r in enrolled_student_ids}
        engagement_rate = (len(active_student_ids & enrolled_student_ids) / len(enrolled_student_ids) * 100) if enrolled_student_ids else 0

        # Avg completion: average of StudentModuleProgress completion_percentage for enrollments in these modules
        from app.models.student_module_progress import StudentModuleProgress
        prog_rows = StudentModuleProgress.query.filter(
            StudentModuleProgress.module_id.in_(module_ids)
        ).with_entities(StudentModuleProgress.completion_percentage).all()
        if prog_rows:
            avg_completion = sum(p[0] or 0 for p in prog_rows) / len(prog_rows)

    return render_template(
        'lecturer/dashboard_lecturer.html',
        courses=courses,
        total_students=total_students,
        recent_quizzes=recent_quizzes,
        lecturer=lecturer,
        quick_action_module=quick_action_module,
        pending_grading_count=pending_grading_count,
        engagement_rate=round(engagement_rate, 1),
        submission_rate=round(submission_rate, 1),
        quiz_average=round(quiz_average, 1),
        avg_completion=round(avg_completion, 1),
        active_courses=len(courses),
        student_growth=0
    )


@main_bp.route('/dashboard/admin')
@login_required
def admin_dashboard():
    """Admin dashboard."""
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Get statistics
    total_students = Student.query.count()
    total_lecturers = Lecturer.query.count()
    total_courses = Course.query.filter_by(is_active=True).count()
    total_users = User.query.count()
    
    # Recent registrations
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()

    # Registrations last 7 days (for dashboard chart)
    from sqlalchemy import func
    start_date = app_today() - timedelta(days=6)
    rows = db.session.query(
        func.date(User.created_at).label('day'),
        func.count(User.id).label('count')
    ).filter(
        User.created_at >= datetime.combine(start_date, datetime.min.time())
    ).group_by('day').order_by('day').all()

    counts_by_day = {r.day: int(r.count) for r in rows}
    registration_labels = []
    registration_counts = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        registration_labels.append(day.strftime('%a'))
        registration_counts.append(counts_by_day.get(day, 0))
    
    return render_template('admin/dashboard_admin.html',
                           total_students=total_students,
                           total_lecturers=total_lecturers,
                           total_courses=total_courses,
                           total_users=total_users,
                           recent_users=recent_users,
                           registration_labels=registration_labels,
                           registration_counts=registration_counts)


@main_bp.route('/dashboard/career')
@login_required
def career_advisor_dashboard():
    """Career advisor dashboard."""
    if current_user.role != 'career_advisor':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Get pending CV reviews
    pending_reviews = CVReview.query.filter_by(status='pending').all()
    reviewed_count = CVReview.query.filter_by(status='reviewed').count()
    
    return render_template('career/dashboard_career.html',
                           pending_reviews=pending_reviews,
                           reviewed_count=reviewed_count)


@main_bp.route('/about')
def about():
    """About page."""
    return render_template('about.html')


@main_bp.route('/help')
def help():
    """Help page."""
    return render_template('help.html')
