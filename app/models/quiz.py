from app import db
from app.utils.app_time import app_now, APP_TZ
from app.utils.percentages import clamp_pct, percentage_from_parts
import json
from sqlalchemy import event


class Quiz(db.Model):
    """Quiz model - quizzes belong to MODULES only.
    
    All quizzes are associated with specific modules within courses.
    Students take quizzes through their enrolled course modules.
    """
    __tablename__ = 'quizzes'
    
    id = db.Column(db.Integer, primary_key=True)
    # REMOVED: course_id - quizzes belong to modules only
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False)  # NOW REQUIRED
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    time_limit = db.Column(db.Integer, default=30)  # in minutes (used when time_limit_seconds is null)
    time_limit_seconds = db.Column(db.Integer, nullable=True)  # if set, exact timer duration in seconds
    passing_score = db.Column(db.Integer, default=60)  # percentage
    is_published = db.Column(db.Boolean, default=False)
    is_ai_generated = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=app_now)
    updated_at = db.Column(db.DateTime, default=app_now, onupdate=app_now)
    due_date = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    questions = db.relationship('QuizQuestion', backref='quiz', lazy=True, cascade='all, delete-orphan')
    results = db.relationship('QuizResult', backref='quiz', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Quiz {self.title} (Module: {self.module_id})>'
    
    @property
    def course_id(self):
        """Get course ID through module relationship."""
        return self.module.course_id if self.module else None
    
    @property
    def question_count(self):
        """Get total number of questions."""
        return len(self.questions)
    
    @property
    def total_points(self):
        """Get total points for the quiz."""
        return sum(q.points for q in self.questions)
    
    def can_access(self, student):
        """Check if student can access this quiz."""
        from app.models.course import Enrollment
        
        if not student:
            return False
        
        enrollment = Enrollment.query.filter_by(
            student_id=student.id,
            course_id=self.course_id,
            status='active'
        ).first()
        
        return enrollment is not None and self.is_published
    
    def has_student_completed(self, student_id):
        """Check if student has already completed this quiz."""
        return QuizResult.query.filter_by(
            quiz_id=self.id,
            student_id=student_id
        ).first() is not None
    
    def is_past_deadline(self) -> bool:
        """True if due date is set and current app timezone time is after the deadline."""
        if self.due_date is None:
            return False
        due = self.due_date
        # Postgres TIMESTAMPTZ may come back as tz-aware; our app clock is naive wall time.
        # Normalize to app-local naive before comparing.
        if getattr(due, "tzinfo", None) is not None:
            try:
                due = due.astimezone(APP_TZ).replace(tzinfo=None)
            except Exception:
                # Best-effort fallback: drop tzinfo to avoid crashing the request.
                due = due.replace(tzinfo=None)
        return app_now() > due

    def get_timer_duration_seconds(self) -> int:
        """Countdown length when taking the quiz. Prefers time_limit_seconds; else time_limit in minutes."""
        if self.time_limit_seconds is not None:
            return max(0, int(self.time_limit_seconds))
        return max(0, int(self.time_limit or 0) * 60)

    def format_timer_display(self) -> str:
        """Short label for list cards (e.g. 40s, 30 min, 1:30)."""
        sec = self.get_timer_duration_seconds()
        if sec <= 0:
            return "Untimed"
        if sec < 60:
            return f"{sec}s"
        m, s = sec // 60, sec % 60
        if s == 0:
            return f"{m} min"
        return f"{m}:{s:02d}"
    
    def to_dict(self):
        return {
            'id': self.id,
            'module_id': self.module_id,
            'course_id': self.course_id,
            'title': self.title,
            'description': self.description,
            'time_limit': self.time_limit,
            'time_limit_seconds': self.time_limit_seconds,
            'passing_score': self.passing_score,
            'question_count': self.question_count,
            'total_points': self.total_points,
            'is_published': self.is_published,
            'is_ai_generated': self.is_ai_generated,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'due_date': self.due_date.isoformat() if self.due_date else None
        }


class QuizQuestion(db.Model):
    """Quiz question model."""
    __tablename__ = 'quiz_questions'
    
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    # REMOVED: module_id - questions belong to quizzes, not directly to modules
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), default='multiple_choice')
    points = db.Column(db.Integer, default=1)
    order = db.Column('question_order', db.Integer, default=0)
    
    # For multiple choice and true/false
    options = db.Column(db.Text, nullable=True)  # JSON string of options
    correct_answer = db.Column(db.Text, nullable=True)
    
    # For short answer
    acceptable_answers = db.Column(db.Text, nullable=True)  # JSON array
    
    created_at = db.Column(db.DateTime, default=app_now)
    
    def __repr__(self):
        return f'<QuizQuestion {self.id}>'
    
    def set_options(self, options_list):
        """Set options as JSON string."""
        self.options = json.dumps(options_list)
    
    def get_options(self):
        """Get options as a list of non-empty strings. Safe if JSON is missing or invalid."""
        if not self.options or not str(self.options).strip():
            return []
        try:
            data = json.loads(self.options)
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [str(x).strip() for x in data if x is not None and str(x).strip()]

    @property
    def normalized_question_type(self) -> str:
        """Map legacy/variant type strings to multiple_choice, true_false, or short_answer."""
        raw = (self.question_type or 'short_answer').strip().lower().replace(' ', '_').replace('-', '_')
        if raw in ('multiple_choice', 'multiplechoice', 'mc', 'multichoice', 'multi'):
            return 'multiple_choice'
        if raw in ('true_false', 'truefalse', 'tf', 'boolean'):
            return 'true_false'
        if raw in ('short_answer', 'shortanswer', 'text', 'essay'):
            return 'short_answer'
        return 'short_answer'
    
    def set_acceptable_answers(self, answers_list):
        """Set acceptable answers as JSON string."""
        self.acceptable_answers = json.dumps(answers_list)
    
    def get_acceptable_answers(self):
        """Get acceptable answers as list."""
        if not self.acceptable_answers or not str(self.acceptable_answers).strip():
            return []
        try:
            data = json.loads(self.acceptable_answers)
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [str(x).strip() for x in data if x is not None and str(x).strip()]
    
    def check_answer(self, answer):
        """Check if the given answer is correct (auto-grade)."""
        if answer is None or (isinstance(answer, str) and not str(answer).strip()):
            return False

        def norm_mc(s: str) -> str:
            return ' '.join((s or '').strip().lower().split())

        def norm_tf(s: str) -> str:
            t = (s or '').strip().lower()
            if t in ('true', 't', 'yes', 'y', '1'):
                return 'true'
            if t in ('false', 'f', 'no', 'n', '0'):
                return 'false'
            return t

        qtype = self.normalized_question_type

        if qtype == 'true_false':
            return norm_tf(str(answer)) == norm_tf(self.correct_answer or '')

        if qtype == 'multiple_choice':
            return norm_mc(str(answer)) == norm_mc(self.correct_answer or '')

        if qtype == 'short_answer':
            acceptable = self.get_acceptable_answers()
            a = norm_mc(str(answer))
            return any(a == norm_mc(x) for x in acceptable)
        return False
    
    def to_dict(self, include_correct=False):
        data = {
            'id': self.id,
            'quiz_id': self.quiz_id,
            'question_text': self.question_text,
            'question_type': self.question_type,
            'points': self.points,
            'order': self.order,
            'options': self.get_options() if self.normalized_question_type in ('multiple_choice', 'true_false') else None
        }
        if include_correct:
            data['correct_answer'] = self.correct_answer
            data['acceptable_answers'] = self.get_acceptable_answers()
        return data


class QuizResult(db.Model):
    """Quiz result model for storing student quiz attempts."""
    __tablename__ = 'quiz_results'
    
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    total_points = db.Column(db.Float, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    passed = db.Column(db.Boolean, default=False)
    time_taken = db.Column(db.Integer, nullable=True)  # in seconds
    answers = db.Column(db.Text, nullable=True)  # JSON string of answers
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, default=app_now)
    
    def __repr__(self):
        return f'<QuizResult Quiz {self.quiz_id} - Student {self.student_id}>'
    
    def set_answers(self, answers_dict):
        """Set answers as JSON string."""
        self.answers = json.dumps(answers_dict)
    
    def get_answers(self):
        """Get answers as dictionary."""
        if self.answers:
            return json.loads(self.answers)
        return {}

    def sync_percentage(self) -> None:
        """Recalculate percentage from score/total_points (0–100)."""
        self.percentage = percentage_from_parts(self.score, self.total_points)
    
    def to_dict(self):
        return {
            'id': self.id,
            'quiz_id': self.quiz_id,
            'student_id': self.student_id,
            'score': self.score,
            'total_points': self.total_points,
            'percentage': clamp_pct(self.percentage),
            'passed': self.passed,
            'time_taken': self.time_taken,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


@event.listens_for(QuizResult, "before_insert")
@event.listens_for(QuizResult, "before_update")
def _quiz_result_sync_percentage(_mapper, _connection, target: QuizResult) -> None:
    target.sync_percentage()
