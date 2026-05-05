import json
from typing import List, Dict, Union, Optional
from dataclasses import dataclass
from flask import (
    Blueprint, render_template, redirect, url_for, 
    flash, request, jsonify, abort, current_app
)
from flask_login import login_required, current_user
from datetime import datetime, time as time_of_day

from app.utils.app_time import app_now
from http import HTTPStatus

from app import db
from app.models import Quiz, QuizQuestion, QuizResult, Course, Student, Module, Enrollment, Lecturer
from app.models.lecturer import LecturerModule
from app.utils.access_control import (
    require_module_access,
    require_lecturer_assigned_to_module,
    can_edit_module_content,
    is_admin,
)
from app.services.notification_service import NotificationService
from sqlalchemy import func

quizzes_bp = Blueprint('quizzes', __name__, url_prefix='/quizzes')


def _quiz_question_counts(quiz_rows: List[Quiz]) -> Dict[int, int]:
    """Batched COUNT(quiz_questions) per quiz_id — matches rows loaded in take/submit routes."""
    if not quiz_rows:
        return {}
    ids = [q.id for q in quiz_rows]
    rows = (
        db.session.query(QuizQuestion.quiz_id, func.count(QuizQuestion.id))
        .filter(QuizQuestion.quiz_id.in_(ids))
        .group_by(QuizQuestion.quiz_id)
        .all()
    )
    tally = {int(qid): int(n) for qid, n in rows}
    return {int(q.id): int(tally.get(q.id, 0)) for q in quiz_rows}


def _parse_quiz_due_datetime(raw: Optional[str]) -> Optional[datetime]:
    """Parse due date from quiz form (date or datetime-local). Values are Johannesburg local wall time."""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().replace('Z', '')
    try:
        if len(s) == 10 and s[4] == '-' and s[7] == '-':
            d = datetime.strptime(s, '%Y-%m-%d').date()
            return datetime.combine(d, time_of_day(23, 59, 59))
        if 'T' in s and s.count(':') == 1:
            s = s + ':00'
        return datetime.fromisoformat(s)
    except ValueError:
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
            try:
                return datetime.strptime(s[:19], fmt)
            except ValueError:
                continue
    return None


@dataclass
class QuizStats:
    """Data class for quiz statistics."""
    total_questions: int
    total_points: int
    estimated_time: int  # minutes


def check_module_access(module_id: int, require_enrollment: bool = True) -> tuple:
    """
    Verify user has access to module.
    Returns (module, course, student) tuple or aborts.
    """
    ctx = require_module_access(module_id)
    module = ctx.module
    course = ctx.course
    
    if current_user.role == 'student' and require_enrollment:
        if not ctx.has_access:
            abort(HTTPStatus.FORBIDDEN, 'Active enrollment required')
        return module, course, ctx.student
    
    return module, course, None


def check_quiz_permission(quiz: Quiz, action: str = 'view') -> None:
    """Check if current user can perform action on quiz."""
    if current_user.role == 'admin':
        return
    
    if current_user.role == 'lecturer':
        # Must be assigned to the module containing this quiz
        if can_edit_module_content(quiz.module_id):
            return
    
    if action == 'take' and current_user.role == 'student':
        return
    
    abort(HTTPStatus.FORBIDDEN)


@quizzes_bp.route('/')
@login_required
def index():
    """List all quizzes for enrolled courses - student view."""
    if current_user.role != 'student':
        from flask import redirect, url_for
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

    quizzes = []
    for module in modules:
        for quiz in module.quizzes:
            if quiz.is_published:
                quizzes.append({
                    'quiz': quiz,
                    'module': module,
                    'course': module.course
                })

    results_list = QuizResult.query.filter_by(student_id=student.id).all()
    completed_quiz_ids = {r.quiz_id for r in results_list}
    results_by_quiz = {r.quiz_id: r for r in results_list}

    unique_quizzes: List[Quiz] = list({item["quiz"].id: item["quiz"] for item in quizzes}.values())
    q_counts = _quiz_question_counts(unique_quizzes)

    return render_template(
        'quizzes_all.html',
        quizzes=quizzes,
        completed_quiz_ids=completed_quiz_ids,
        results_by_quiz=results_by_quiz,
        quiz_question_counts=q_counts,
        now=app_now(),
    )


@quizzes_bp.route('/course/<int:course_id>')
@login_required
def list_quizzes_by_course(course_id: int):
    """Redirect to first module's quizzes or show appropriate message."""
    from flask import flash
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
    
    return redirect(url_for('quizzes.list_quizzes', module_id=first_module.id))


@quizzes_bp.route('/module/<int:module_id>')
@login_required
def list_quizzes(module_id: int) -> str:
    """List quizzes for a module with role-based filtering."""
    module, course, student = check_module_access(module_id)
    
    if current_user.role == 'student':
        # Students see only published quizzes with their results
        quizzes: List[Quiz] = Quiz.query.filter_by(
            module_id=module_id,
            is_published=True
        ).order_by(Quiz.created_at.desc()).all()
        
        results: List[QuizResult] = QuizResult.query.filter_by(
            student_id=student.id
        ).all()
        
        completed_ids: set = {r.quiz_id for r in results}
        results_map: Dict[int, QuizResult] = {r.quiz_id: r for r in results}
        q_counts = _quiz_question_counts(quizzes)
        
        return render_template(
            'quizzes.html',
            course=course,
            module=module,
            quizzes=quizzes,
            completed_quiz_ids=completed_ids,
            results=results_map,
            quiz_question_counts=q_counts,
            now=app_now(),
        )
    
    # Lecturers/Admins see all quizzes
    quizzes = Quiz.query.filter_by(module_id=module_id)\
        .order_by(Quiz.created_at.desc()).all()

    q_counts = _quiz_question_counts(quizzes)
    
    return render_template(
        'quizzes.html',
        course=course,
        module=module,
        quizzes=quizzes,
        is_instructor_view=True,
        quiz_question_counts=q_counts,
        now=app_now(),
    )


@quizzes_bp.route('/module/<int:module_id>/create', methods=['GET', 'POST'])
@login_required
def create_quiz(module_id: int) -> Union[str, redirect]:
    """Create new quiz with validation."""
    module, course, _ = check_module_access(module_id, require_enrollment=False)
    
    if current_user.role not in ['lecturer', 'admin']:
        abort(HTTPStatus.FORBIDDEN)

    # Lecturer must be assigned to the module
    if current_user.role == 'lecturer':
        require_lecturer_assigned_to_module(module_id)
    
    if request.method == 'POST':
        try:
            # Validate input
            title: str = request.form.get('title', '').strip()
            if not title:
                flash('Quiz title is required.', 'danger')
                return render_template('lecturer/quiz_form.html', course=course, module=module)
            
            raw_time_limit = (request.form.get('time_limit') or '').strip()
            raw_passing = (request.form.get('passing_score') or '').strip()
            time_limit: int = int(raw_time_limit) if raw_time_limit else 30
            passing_score: int = int(raw_passing) if raw_passing else 60
            
            if not (0 <= passing_score <= 100):
                raise ValueError("Passing score must be between 0 and 100")
            
            due_parsed = _parse_quiz_due_datetime(request.form.get('due_date'))

            quiz = Quiz(
                module_id=module_id,
                title=title,
                description=request.form.get('description', '').strip(),
                time_limit=max(1, time_limit),
                passing_score=passing_score,
                created_by=current_user.id,
                due_date=due_parsed,
            )
            
            db.session.add(quiz)
            db.session.commit()
            
            flash('Quiz created! Now add questions.', 'success')
            return redirect(url_for('quizzes.edit_quiz', quiz_id=quiz.id))
            
        except ValueError as e:
            flash(f'Invalid input: {str(e)}', 'danger')
            return render_template('lecturer/quiz_form.html', course=course, module=module, action='Create')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Quiz creation error: {str(e)}')
            flash('Error creating quiz. Please try again.', 'danger')
    
    return render_template('lecturer/quiz_form.html', course=course, module=module, action='Create')


@quizzes_bp.route('/<int:quiz_id>/submit', methods=['POST'])
@login_required
def submit_quiz(quiz_id: int) -> Union[redirect, tuple]:
    """Submit quiz answers with automatic grading."""
    quiz: Quiz = Quiz.query.get_or_404(quiz_id)
    
    if current_user.role != 'student':
        return jsonify({'error': 'Students only'}), HTTPStatus.FORBIDDEN
    
    # Require active enrollment and published quiz (server-side guard)
    ctx = require_module_access(quiz.module_id)
    if not ctx.has_access:
        abort(HTTPStatus.FORBIDDEN, 'Access denied')
    
    if not quiz.is_published:
        abort(HTTPStatus.FORBIDDEN, 'Quiz not available')

    if quiz.is_past_deadline():
        flash('This quiz is past its due date and can no longer be submitted.', 'warning')
        return redirect(url_for('quizzes.preview_quiz', quiz_id=quiz_id))

    student: Student = Student.query.filter_by(user_id=current_user.id).first_or_404()
    
    # Check for existing result
    existing: Optional[QuizResult] = QuizResult.query.filter_by(
        quiz_id=quiz_id,
        student_id=student.id
    ).first()
    
    if existing:
        flash('You have already completed this quiz.', 'info')
        return redirect(url_for('quizzes.quiz_result', result_id=existing.id))
    
    try:
        started_at: Optional[datetime] = None
        raw_started = request.form.get('started_at')
        if raw_started:
            try:
                rs = str(raw_started).strip().replace('Z', '')
                started_at = datetime.fromisoformat(rs)
                if getattr(started_at, 'tzinfo', None) is not None:
                    started_at = started_at.replace(tzinfo=None)
            except ValueError:
                started_at = None

        # Process answers
        answers: Dict[str, Optional[str]] = {}
        score: int = 0
        total_points: int = 0
        
        questions: List[QuizQuestion] = QuizQuestion.query\
            .filter_by(quiz_id=quiz_id)\
            .order_by(QuizQuestion.order)\
            .all()
        
        limit_sec = quiz.get_timer_duration_seconds()
        if started_at and limit_sec > 0:
            elapsed = (app_now() - started_at).total_seconds()
            if elapsed > limit_sec + 120:
                flash('Your session exceeded the time limit; only answers received in time are counted.', 'warning')

        for question in questions:
            answer: Optional[str] = request.form.get(f'question_{question.id}')
            answers[str(question.id)] = answer
            
            total_points += question.points
            if answer and question.check_answer(answer):
                score += question.points
        
        # Calculate metrics
        percentage: float = (score / total_points * 100) if total_points > 0 else 0
        
        # Cap percentage at 100 to prevent invalid values
        if percentage > 100:
            percentage = 100.0
        elif percentage < 0:
            percentage = 0.0
        
        passed: bool = percentage >= quiz.passing_score
        
        time_taken: int = 0
        if started_at:
            time_taken = int((app_now() - started_at).total_seconds())
        
        # Save result
        result = QuizResult(
            quiz_id=quiz_id,
            student_id=student.id,
            score=score,
            total_points=total_points,
            percentage=round(percentage, 2),
            passed=passed,
            time_taken=time_taken,
            started_at=started_at or app_now()
        )
        result.set_answers(answers)
        
        db.session.add(result)
        db.session.commit()
        
        # Flash appropriate message
        if passed:
            flash(f'Congratulations! You passed with {percentage:.1f}%', 'success')
        else:
            flash(f'Quiz completed. Score: {percentage:.1f}% (Pass: {quiz.passing_score}%)', 'warning')
        
        return redirect(url_for('quizzes.quiz_result', result_id=result.id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Quiz submission error: {str(e)}')
        flash('Error submitting quiz. Please contact support.', 'danger')
        return redirect(url_for('quizzes.list_quizzes', module_id=quiz.module_id))


@quizzes_bp.route('/<int:quiz_id>/preview')
@login_required
def preview_quiz(quiz_id: int) -> Union[str, redirect]:
    """Read-only view of quiz questions (e.g. after the due date)."""
    quiz: Quiz = Quiz.query.get_or_404(quiz_id)

    if current_user.role != 'student':
        return redirect(url_for('quizzes.edit_quiz', quiz_id=quiz_id))

    ctx = require_module_access(quiz.module_id)
    if not ctx.has_access:
        abort(HTTPStatus.FORBIDDEN)

    if not quiz.is_published:
        flash('This quiz is not available.', 'warning')
        return redirect(url_for('quizzes.list_quizzes', module_id=quiz.module_id))

    questions = QuizQuestion.query.filter_by(quiz_id=quiz_id).order_by(QuizQuestion.order).all()
    course = Course.query.get_or_404(quiz.course_id)

    return render_template(
        'quiz_preview.html',
        quiz=quiz,
        questions=questions,
        course=course,
    )


@quizzes_bp.route('/<int:quiz_id>/take')
@login_required
def take_quiz(quiz_id: int) -> Union[str, redirect]:
    """Display quiz for students to take."""
    quiz: Quiz = Quiz.query.get_or_404(quiz_id)
    
    if current_user.role != 'student':
        flash('Only students can take quizzes.', 'danger')
        return redirect(url_for('quizzes.list_quizzes', module_id=quiz.module_id))
    
    # Require active enrollment
    ctx = require_module_access(quiz.module_id)
    if not ctx.has_access:
        abort(HTTPStatus.FORBIDDEN)
    student = ctx.student
    
    # Check if already completed
    existing = QuizResult.query.filter_by(
        quiz_id=quiz_id,
        student_id=student.id
    ).first()
    
    if existing:
        flash('You have already completed this quiz.', 'info')
        return redirect(url_for('quizzes.quiz_result', result_id=existing.id))
    
    # Check if quiz is published
    if not quiz.is_published:
        flash('This quiz is not available yet.', 'warning')
        return redirect(url_for('quizzes.list_quizzes', module_id=quiz.module_id))

    if quiz.is_past_deadline():
        flash('The due date has passed. You can review the questions below, but answers are not accepted.', 'warning')
        return redirect(url_for('quizzes.preview_quiz', quiz_id=quiz_id))
    
    # Get questions
    questions = QuizQuestion.query.filter_by(quiz_id=quiz_id).order_by(QuizQuestion.order).all()
    
    if not questions:
        flash('No questions in this quiz yet.', 'warning')
        return redirect(url_for('quizzes.list_quizzes', module_id=quiz.module_id))
    
    # Get the course for this quiz
    course = Course.query.get_or_404(quiz.course_id)
    
    return render_template('quiz_take.html', quiz=quiz, questions=questions, course=course, current_time=app_now())


@quizzes_bp.route('/result/<int:result_id>')
@login_required
def quiz_result(result_id: int) -> str:
    """Display quiz result after submission."""
    result: QuizResult = QuizResult.query.get_or_404(result_id)
    
    # Check permission - only the student who took the quiz can view results
    if current_user.role == 'student':
        student: Student = Student.query.filter_by(user_id=current_user.id).first_or_404()
        if result.student_id != student.id:
            abort(HTTPStatus.FORBIDDEN)
    
    quiz: Quiz = Quiz.query.get_or_404(result.quiz_id)
    course: Course = Course.query.get_or_404(quiz.course_id)
    
    # Get answers for display
    answers = result.get_answers() if hasattr(result, 'get_answers') else {}
    
    # Get questions for review
    questions = QuizQuestion.query.filter_by(quiz_id=quiz.id).order_by(QuizQuestion.order).all()
    
    return render_template('quiz_result.html', 
                          result=result, 
                          quiz=quiz, 
                          course=course, 
                          answers=answers,
                          questions=questions)


@quizzes_bp.route('/<int:quiz_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_quiz(quiz_id: int) -> Union[str, redirect]:
    """Edit existing quiz."""
    quiz: Quiz = Quiz.query.get_or_404(quiz_id)
    
    # Check permission
    check_quiz_permission(quiz, 'edit')
    
    course = Course.query.get_or_404(quiz.course_id)
    module = Module.query.get_or_404(quiz.module_id)
    
    # Get questions
    questions = QuizQuestion.query.filter_by(quiz_id=quiz_id).order_by(QuizQuestion.order).all()
    
    # Handle quiz updates + question form submission
    if request.method == 'POST':
        # If the edit form posts quiz fields, update them (enhanced UI)
        posted_title = request.form.get('title')
        posted_time_limit = request.form.get('time_limit')
        posted_passing = request.form.get('passing_score')
        posted_due = request.form.get('due_date')
        if posted_title is not None or posted_time_limit is not None or posted_passing is not None or posted_due is not None:
            try:
                if posted_title is not None:
                    t = (posted_title or '').strip()
                    if t:
                        quiz.title = t
                if 'description' in request.form:
                    quiz.description = (request.form.get('description') or '').strip() or None
                if posted_time_limit is not None and str(posted_time_limit).strip():
                    quiz.time_limit = max(1, int(posted_time_limit))
                if posted_passing is not None and str(posted_passing).strip():
                    ps = int(posted_passing)
                    if not (0 <= ps <= 100):
                        raise ValueError("Passing score must be between 0 and 100")
                    quiz.passing_score = ps
                if posted_due is not None:
                    quiz.due_date = _parse_quiz_due_datetime(posted_due)
                db.session.commit()
                flash('Quiz updated successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f'Quiz update error: {str(e)}')
                flash('Could not update quiz. Please check your inputs.', 'danger')
            return redirect(url_for('quizzes.edit_quiz', quiz_id=quiz_id))

        question_text = request.form.get('question_text', '').strip()
        if question_text:
            question_type = request.form.get('question_type', 'multiple_choice')
            if question_type not in ('multiple_choice', 'true_false'):
                flash('Only True/False or five-option multiple choice questions are allowed.', 'danger')
                return redirect(url_for('quizzes.edit_quiz', quiz_id=quiz_id))

            points = int(request.form.get('points', 1))
            
            # Create new question
            new_question = QuizQuestion(
                quiz_id=quiz_id,
                question_text=question_text,
                question_type=question_type,
                points=points,
                order=len(questions) + 1
            )
            
            if question_type == 'multiple_choice':
                option_texts = [(o or '').strip() for o in request.form.getlist('options[]')]
                if len(option_texts) != 5 or not all(option_texts):
                    flash('Multiple choice requires exactly five non-empty answer choices.', 'danger')
                    return redirect(url_for('quizzes.edit_quiz', quiz_id=quiz_id))

                correct_idx = request.form.get('correct_option_mc', '0')
                try:
                    correct_idx_int = int(correct_idx)
                except ValueError:
                    correct_idx_int = 0

                new_question.set_options(option_texts)
                if 0 <= correct_idx_int < len(option_texts):
                    new_question.correct_answer = option_texts[correct_idx_int]
                else:
                    new_question.correct_answer = option_texts[0]
            
            else:  # true_false
                correct_idx = request.form.get('correct_option_tf', '0')
                correct_val = 'True' if str(correct_idx) == '0' else 'False'
                new_question.set_options(['True', 'False'])
                new_question.correct_answer = correct_val
            
            db.session.add(new_question)
            db.session.commit()
            flash('Question added successfully!', 'success')
        else:
            flash('Question text is required.', 'danger')
        
        return redirect(url_for('quizzes.edit_quiz', quiz_id=quiz_id))
    
    return render_template('lecturer/quiz_edit.html', quiz=quiz, course=course, module=module, questions=questions)


@quizzes_bp.route('/<int:quiz_id>/publish', methods=['POST'])
@login_required
def publish_quiz(quiz_id: int) -> redirect:
    """Publish or unpublish a quiz."""
    quiz: Quiz = Quiz.query.get_or_404(quiz_id)
    
    # Check permission - only lecturer/admin can publish
    check_quiz_permission(quiz, 'edit')

    toggling_on = not quiz.is_published
    if toggling_on:
        q_count = QuizQuestion.query.filter_by(quiz_id=quiz.id).count()
        if q_count == 0:
            flash(
                'Add at least one question before publishing this quiz. Students cannot take an empty quiz.',
                'danger',
            )
            return redirect(url_for('quizzes.edit_quiz', quiz_id=quiz.id))
    
    # Toggle published status
    quiz.is_published = not quiz.is_published
    db.session.commit()

    # If just published, notify enrolled students
    if quiz.is_published:
        try:
            module = Module.query.get_or_404(quiz.module_id)
            course = Course.query.get_or_404(module.course_id)
            lecturer = Lecturer.query.filter_by(user_id=current_user.id).first() if current_user.role == 'lecturer' else None
            enrollments = Enrollment.query.filter_by(course_id=course.id, status='active').all()
            students = [e.student for e in enrollments if e.student and e.student.user]
            if students:
                NotificationService.notify_quiz_published(
                    lecturer=lecturer,
                    course=course,
                    module=module,
                    quiz=quiz,
                    students=students
                )
        except Exception:
            current_app.logger.exception('notify_quiz_published failed (quiz publish state was saved)')
    
    action = 'published' if quiz.is_published else 'unpublished'
    flash(f'Quiz "{quiz.title}" has been {action}.', 'success')
    
    return redirect(url_for('quizzes.list_quizzes', module_id=quiz.module_id))


@quizzes_bp.route('/<int:quiz_id>/delete', methods=['POST'])
@login_required
def delete_quiz(quiz_id: int) -> redirect:
    """Delete a quiz (lecturer owner or admin only)."""
    quiz: Quiz = Quiz.query.get_or_404(quiz_id)

    # Permission check
    check_quiz_permission(quiz, 'edit')

    module_id = quiz.module_id
    try:
        db.session.delete(quiz)
        db.session.commit()
        flash('Quiz deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Quiz deletion error: {str(e)}')
        flash('Error deleting quiz.', 'danger')

    return redirect(url_for('quizzes.list_quizzes', module_id=module_id))


@quizzes_bp.route('/course/<int:course_id>/create', methods=['GET', 'POST'])
@login_required
def create_quiz_course_legacy(course_id: int) -> redirect:
    """Redirect old course-based quiz creation URLs to first module."""
    # Prefer a module assigned to the current lecturer (avoids 403 on create)
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
        return redirect(url_for('quizzes.create_quiz', module_id=module.id))
    
    flash('No modules found in this course.', 'warning')
    return redirect(url_for('courses.detail', course_id=course_id))