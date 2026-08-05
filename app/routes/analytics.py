from flask import Blueprint, render_template, jsonify, abort
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
from app import db
from app.utils.app_time import app_now, app_today
from app.models import (
    User, Student, Lecturer, Course, Enrollment, QuizResult,
    Attendance, Mark, CourseMaterial, Quiz, Module,
    ChatSession, ChatMessage,
)
from app.utils.percentages import clamp_pct, format_pct
from app.services.risk_service import (
    compute_academic_scores,
    compute_student_metrics,
    count_at_risk_students,
    list_at_risk_students,
)

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')


@analytics_bp.route('/dashboard')
@login_required
def dashboard():
    """Analytics dashboard."""
    if current_user.role == 'admin':
        return admin_analytics()
    elif current_user.role == 'lecturer':
        return lecturer_analytics()
    elif current_user.role == 'student':
        return student_analytics()
    else:
        abort(403)


@analytics_bp.route('/admin')
@login_required
def admin_analytics():
    """Admin analytics dashboard."""
    if current_user.role != 'admin':
        abort(403)
    
    # User statistics
    total_students = Student.query.count()
    total_lecturers = Lecturer.query.count()
    total_courses = Course.query.filter_by(is_active=True).count()
    total_users = User.query.count()
    
    # Recent activity
    new_students_30d = User.query.filter(
        User.role == 'student',
        User.created_at >= app_now() - timedelta(days=30)
    ).count()
    
    # Enrollment trends (last 30 days, daily)
    start_day = app_today() - timedelta(days=29)
    enroll_rows = db.session.query(
        func.date(Enrollment.enrolled_at).label('day'),
        func.count(Enrollment.id).label('count')
    ).filter(
        Enrollment.enrolled_at >= datetime.combine(start_day, datetime.min.time())
    ).group_by('day').order_by('day').all()
    enroll_by_day = {r.day: int(r.count) for r in enroll_rows}
    enrollment_labels = []
    enrollment_counts = []
    for i in range(30):
        d = start_day + timedelta(days=i)
        enrollment_labels.append(d.strftime('%b %d'))
        enrollment_counts.append(enroll_by_day.get(d, 0))
    
    # Course popularity
    popular_courses = db.session.query(
        Course.id,
        Course.code,
        Course.name,
        func.count(Enrollment.id).label('enrollments')
    ).join(Enrollment).group_by(Course.id).order_by(func.count(Enrollment.id).desc()).limit(10).all()
    top_courses = [
        {
            'id': row.id,
            'code': row.code,
            'name': row.name,
            'enrollments': int(row.enrollments),
            'students': int(row.enrollments),  # one enrollment per student per course
        }
        for row in popular_courses
    ]
    
    # Quiz performance + overall performance (marks)
    avg_quiz_score = clamp_pct(db.session.query(func.avg(QuizResult.percentage)).scalar() or 0)
    avg_performance = clamp_pct(db.session.query(func.avg(Mark.percentage)).scalar() or 0)

    # AI usage
    ai_sessions = ChatSession.query.count()
    ai_messages = ChatMessage.query.count()

    # Active students (students with active enrollment)
    active_students = db.session.query(func.count(func.distinct(Enrollment.student_id))).filter(
        Enrollment.status == 'active'
    ).scalar() or 0
    total_enrollments = Enrollment.query.count()

    # Grade distribution from marks (A/B/C/BelowC)
    total_marks = Mark.query.count()
    if total_marks > 0:
        a = Mark.query.filter(Mark.percentage >= 90).count()
        b = Mark.query.filter(Mark.percentage >= 80, Mark.percentage < 90).count()
        c = Mark.query.filter(Mark.percentage >= 70, Mark.percentage < 80).count()
        below_c = total_marks - (a + b + c)
        grade_a = round(a / total_marks * 100, 1)
        grade_b = round(b / total_marks * 100, 1)
        grade_c = round(c / total_marks * 100, 1)
        grade_d = round(below_c / total_marks * 100, 1)
    else:
        grade_a = grade_b = grade_c = grade_d = 0.0

    # Recent activity (real)
    recent_enrollments = Enrollment.query.order_by(Enrollment.enrolled_at.desc()).limit(5).all()
    recent_quiz_results = QuizResult.query.order_by(QuizResult.completed_at.desc()).limit(5).all()
    recent_activity = []
    for e in recent_enrollments:
        recent_activity.append({
            'type': 'enrollment',
            'title': 'New enrollment',
            'detail': f'{e.student.full_name if e.student else "Student"} → {e.course.name if e.course else "Course"}',
            'timestamp': e.enrolled_at,
        })
    for r in recent_quiz_results:
        recent_activity.append({
            'type': 'quiz',
            'title': 'Quiz submitted',
            'detail': f'{r.quiz.title if r.quiz else "Quiz"} • {format_pct(r.percentage, 1)}%',
            'timestamp': r.completed_at,
        })
    recent_activity = sorted(
        [x for x in recent_activity if x.get('timestamp')],
        key=lambda x: x['timestamp'],
        reverse=True
    )[:5]
    
    # At-risk students (computed from live marks, quizzes, attendance)
    at_risk = count_at_risk_students()
    
    return render_template(
        'admin/analytics_admin.html',
        total_students=total_students,
        total_lecturers=total_lecturers,
        total_courses=total_courses,
        total_users=total_users,
        active_students=int(active_students),
        total_enrollments=total_enrollments,
        avg_performance=round(avg_performance, 1),
        ai_sessions=ai_sessions,
        ai_messages=ai_messages,
        new_students_30d=new_students_30d,
        enrollment_labels=enrollment_labels,
        enrollment_counts=enrollment_counts,
        grade_a=grade_a,
        grade_b=grade_b,
        grade_c=grade_c,
        grade_d=grade_d,
        top_courses=top_courses,
        recent_activity=recent_activity,
        avg_quiz_score=round(avg_quiz_score, 1),
        at_risk=at_risk
    )


@analytics_bp.route('/lecturer')
@login_required
def lecturer_analytics():
    """Lecturer analytics dashboard."""
    if current_user.role != 'lecturer':
        abort(403)
    
    lecturer = Lecturer.query.filter_by(user_id=current_user.id).first_or_404()

    def _clamp_pct(value) -> float:
        return clamp_pct(value)
    
    # Lecturer scope: only modules actually assigned to the lecturer
    assigned_modules = lecturer.get_assigned_modules()
    module_ids = [m.id for m in assigned_modules]
    courses = lecturer.get_teaching_courses()
    course_ids = [c.id for c in courses]
    
    # Course statistics
    total_students = sum(c.get_student_count() for c in courses)
    total_materials = CourseMaterial.query.filter(
        CourseMaterial.module_id.in_(module_ids)
    ).count() if module_ids else 0

    # Students per module (enrollment is course-level; we show course enrollment size per module)
    students_per_module = []
    for m in assigned_modules:
        c = m.course
        if not c:
            continue
        students_per_module.append({
            "module_id": m.id,
            "module_title": m.title,
            "module_order": m.order,
            "course_id": c.id,
            "course_code": c.code,
            "course_name": c.name,
            "students": c.get_student_count(),
        })
    students_per_module.sort(key=lambda x: (x["course_code"] or "", x["module_order"] or 0, x["module_id"]))

    # Engagement: % of enrolled students with any activity in last 14 days (quiz/submission/attendance)
    engagement_rate = 0.0
    active_today = 0
    if module_ids and course_ids:
        cutoff = app_now() - timedelta(days=14)
        active_student_ids = set()

        q_rows = QuizResult.query.join(Quiz).filter(
            Quiz.module_id.in_(module_ids),
            QuizResult.completed_at >= cutoff
        ).with_entities(QuizResult.student_id).all()
        active_student_ids.update([r[0] for r in q_rows])

        # assignment submissions (if model exists in this module)
        try:
            from app.models.assignment import AssignmentSubmission, Assignment
            assignment_ids = [a.id for a in Assignment.query.filter(Assignment.module_id.in_(module_ids)).all()]
            if assignment_ids:
                s_rows = AssignmentSubmission.query.filter(
                    AssignmentSubmission.assignment_id.in_(assignment_ids),
                    AssignmentSubmission.submitted_at >= cutoff
                ).with_entities(AssignmentSubmission.student_id).all()
                active_student_ids.update([r[0] for r in s_rows])
        except Exception:
            assignment_ids = []

        a_rows = Attendance.query.filter(
            Attendance.module_id.in_(module_ids),
            Attendance.date >= cutoff.date(),
        ).with_entities(Attendance.student_id).distinct().all()
        active_student_ids.update([r[0] for r in a_rows])

        enrolled_student_ids = Enrollment.query.filter(
            Enrollment.course_id.in_(course_ids),
            Enrollment.status == 'active'
        ).with_entities(Enrollment.student_id).distinct().all()
        enrolled_student_ids = {r[0] for r in enrolled_student_ids}
        engagement_rate = (len(active_student_ids & enrolled_student_ids) / len(enrolled_student_ids) * 100) if enrolled_student_ids else 0.0

        # Active today: students with any quiz submission today in assigned modules
        today = app_today()
        active_today = db.session.query(func.count(func.distinct(QuizResult.student_id))).join(
            Quiz, QuizResult.quiz_id == Quiz.id
        ).filter(
            Quiz.module_id.in_(module_ids),
            func.date(QuizResult.completed_at) == today
        ).scalar() or 0

    # Student scores (marks + quizzes) across assigned modules
    student_scores = []
    if module_ids and course_ids:
        student_ids = Enrollment.query.filter(
            Enrollment.course_id.in_(course_ids),
            Enrollment.status == 'active'
        ).with_entities(Enrollment.student_id).distinct().all()
        student_ids = [r[0] for r in student_ids]

        for sid in student_ids:
            student = Student.query.get(sid)
            if not student or not student.user:
                continue

            metrics = compute_academic_scores(sid, module_ids=module_ids)
            if not metrics["has_data"]:
                continue

            student_scores.append({
                "student_id": sid,
                "name": student.user.full_name,
                "avg_marks": metrics["assignment_score"],
                "avg_quizzes": metrics["quiz_score"],
                "overall": metrics["overall_score"],
            })

        student_scores.sort(key=lambda x: x["overall"], reverse=True)
    
    # Quiz performance per course
    course_performance = []
    for course in courses:
        # Get module IDs for this course
        course_module_ids = [m.id for m in course.modules]
        if course_module_ids:
            quiz_avg = db.session.query(func.avg(QuizResult.percentage)).join(
                Quiz
            ).filter(Quiz.module_id.in_(course_module_ids)).scalar()
            mark_avg = db.session.query(func.avg(Mark.percentage)).filter(
                Mark.module_id.in_(course_module_ids)
            ).scalar()
        else:
            quiz_avg = None
            mark_avg = None

        score_parts = []
        if mark_avg is not None:
            score_parts.append(_clamp_pct(mark_avg))
        if quiz_avg is not None:
            score_parts.append(_clamp_pct(quiz_avg))
        avg_score = sum(score_parts) / len(score_parts) if score_parts else 0
        
        # Pass rate from quiz results in this course
        if course_module_ids:
            total_results = QuizResult.query.join(Quiz).filter(Quiz.module_id.in_(course_module_ids)).count()
            passed_results = QuizResult.query.join(Quiz).filter(
                Quiz.module_id.in_(course_module_ids),
                QuizResult.passed == True  # noqa: E712
            ).count()
            pass_rate = (passed_results / total_results * 100) if total_results > 0 else 0
        else:
            pass_rate = 0

        # Attendance rate for course
        if course_module_ids:
            total_att = Attendance.query.filter(Attendance.module_id.in_(course_module_ids)).count()
            present_att = Attendance.query.filter(
                Attendance.module_id.in_(course_module_ids),
                Attendance.status == 'present'
            ).count()
            attendance_rate = (present_att / total_att * 100) if total_att > 0 else 0
        else:
            attendance_rate = 0

        # Submission rate (assignment submissions / enrollments * assignments)
        try:
            from app.models.assignment import Assignment, AssignmentSubmission
            if course_module_ids:
                assignment_ids = [a.id for a in Assignment.query.filter(Assignment.module_id.in_(course_module_ids)).all()]
                active_enrollments = Enrollment.query.filter_by(course_id=course.id, status='active').count()
                if assignment_ids and active_enrollments > 0:
                    submissions = AssignmentSubmission.query.filter(AssignmentSubmission.assignment_id.in_(assignment_ids)).count()
                    possible = active_enrollments * len(assignment_ids)
                    submission_rate = (submissions / possible * 100) if possible > 0 else 0
                else:
                    submission_rate = 0
            else:
                submission_rate = 0
        except Exception:
            submission_rate = 0

        course_performance.append({
            'code': course.code,
            'name': course.name,
            'avg_score': round(_clamp_pct(avg_score), 1),
            'students': course.get_student_count(),
            'student_count': course.get_student_count(),
            'pass_rate': round(pass_rate, 1),
            'attendance': round(attendance_rate, 1),
            'submission_rate': round(submission_rate, 1)
        })
    
    # Attendance rates
    attendance_rates = []
    for course in courses:
        course_module_ids = [m.id for m in course.modules]
        if course_module_ids:
            total = Attendance.query.filter(Attendance.module_id.in_(course_module_ids)).count()
            if total > 0:
                present = Attendance.query.filter(
                    Attendance.module_id.in_(course_module_ids),
                    Attendance.status == 'present'
                ).count()
                rate = (present / total) * 100
            else:
                rate = 0
        else:
            rate = 0
        attendance_rates.append({
            'code': course.code,
            'name': course.name,
            'rate': round(rate, 1)
        })
    
    # At-risk students in lecturer's courses (derived from real academic data)
    at_risk_students = list_at_risk_students(course_ids=course_ids, module_ids=module_ids or None)
    
    return render_template('analytics_lecturer.html',
                          courses=courses,
                          total_students=total_students,
                          total_materials=total_materials,
                          course_performance=course_performance,
                          attendance_rates=attendance_rates,
                          at_risk_students=at_risk_students,
                          students_per_module=students_per_module,
                          engagement_rate=round(engagement_rate, 1),
                          active_today=int(active_today),
                          student_scores=student_scores)


@analytics_bp.route('/student')
@login_required
def student_analytics():
    """Student analytics dashboard."""
    if current_user.role != 'student':
        abort(403)
    
    student = Student.query.filter_by(user_id=current_user.id).first()

    from app.services.academic_service import build_student_academic_summary
    academic = build_student_academic_summary(student)
    
    # Academic performance from active enrollments only
    avg_mark = academic["overall_percentage"]
    avg_quiz = (
        round(
            sum(row["quiz_avg"] for row in academic["course_summaries"] if row.get("quiz_avg") is not None)
            / max(1, sum(1 for row in academic["course_summaries"] if row.get("quiz_avg") is not None)),
            1,
        )
        if any(row.get("quiz_avg") is not None for row in academic["course_summaries"])
        else None
    )
    from app.services.risk_service import latest_quiz_results
    quiz_results = []
    for row in academic["course_summaries"]:
        course_module_ids = [module.id for module in row["course"].modules]
        quiz_results.extend(latest_quiz_results(student.id, module_ids=course_module_ids))
    quizzes_passed = sum(1 for r in quiz_results if r.passed)
    
    # Attendance scoped to active courses
    enrollments = Enrollment.query.filter_by(student_id=student.id, status='active').all()
    course_ids = [e.course_id for e in enrollments]
    attendance = Attendance.query.filter_by(student_id=student.id).all()
    if course_ids:
        active_module_ids = {m.id for m in Module.query.filter(Module.course_id.in_(course_ids)).all()}
        attendance = [a for a in attendance if a.module_id in active_module_ids]
    attendance_rate = 0
    if attendance:
        present = sum(1 for a in attendance if a.status == 'present')
        attendance_rate = (present / len(attendance)) * 100
    
    # Course progress aligned with academic summary
    course_progress = []
    for row in academic["course_summaries"]:
        course = row["course"]
        course_progress.append({
            'id': course.id,
            'name': course.name,
            'avg': row["display_average"],
            'marks_count': row["marks_count"],
            'quizzes_count': row["quiz_count"],
        })
    
    # Risk assessment from live academic data (worst active enrollment)
    risk_metrics = None
    for enrollment in enrollments:
        course_metrics = compute_student_metrics(student.id, course_id=enrollment.course_id)
        if not course_metrics["has_data"]:
            continue
        if risk_metrics is None or course_metrics["overall_score"] < risk_metrics["overall_score"]:
            risk_metrics = course_metrics

    risk = None
    if risk_metrics and risk_metrics["has_data"]:
        class RiskView:
            pass

        risk = RiskView()
        risk.risk_level = risk_metrics["risk_level"]
        risk.risk_score = risk_metrics["performance_score"]
        risk.overall_score = risk_metrics["overall_score"]
        risk.attendance_score = risk_metrics["attendance_score"]
        risk.quiz_score = risk_metrics["quiz_score"]
        risk.assignment_score = risk_metrics["assignment_score"]
        risk.risk_factors = risk_metrics["risk_factors"]
        risk.is_at_risk = risk_metrics["is_at_risk"]
    
    return render_template('analytics_student.html',
                          avg_mark=round(avg_mark, 1) if avg_mark else 0,
                          avg_quiz=round(avg_quiz, 1) if avg_quiz is not None else None,
                          quizzes_passed=quizzes_passed,
                          total_quizzes=len(quiz_results),
                          attendance_rate=round(attendance_rate, 1),
                          course_progress=course_progress,
                          risk=risk)


@analytics_bp.route('/api/enrollment-trend')
@login_required
def enrollment_trend_api():
    """API for enrollment trend data."""
    if current_user.role != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    # Get last 12 months of enrollment data
    data = db.session.query(
        func.extract('year', Enrollment.enrolled_at).label('year'),
        func.extract('month', Enrollment.enrolled_at).label('month'),
        func.count(Enrollment.id).label('count')
    ).filter(
        Enrollment.enrolled_at >= app_now() - timedelta(days=365)
    ).group_by('year', 'month').all()
    
    result = []
    for d in data:
        result.append({
            'year': int(d.year),
            'month': int(d.month),
            'count': d.count
        })
    
    return jsonify(result)


@analytics_bp.route('/api/quiz-performance/<int:course_id>')
@login_required
def quiz_performance_api(course_id):
    """API for quiz performance in a course."""
    if current_user.role not in ['lecturer', 'admin']:
        return jsonify({'error': 'Access denied'}), 403
    
    # Get module IDs for this course
    module_ids = [m.id for m in Module.query.filter_by(course_id=course_id).all()]
    
    if not module_ids:
        return jsonify([])
    
    results = db.session.query(
        QuizResult.student_id,
        func.avg(QuizResult.percentage).label('avg_score'),
        func.count(QuizResult.id).label('quiz_count')
    ).join(Quiz).filter(
        Quiz.module_id.in_(module_ids)
    ).group_by(QuizResult.student_id).all()
    
    result = []
    for r in results:
        student = Student.query.get(r.student_id)
        result.append({
            'student_name': student.user.full_name if student else 'Unknown',
            'avg_score': round(r.avg_score, 1),
            'quiz_count': r.quiz_count
        })
    
    return jsonify(result)
