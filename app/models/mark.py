from app import db
from app.utils.app_time import app_now
from app.utils.percentages import clamp_pct, percentage_from_parts
from sqlalchemy import event


class Mark(db.Model):
    """Mark model - marks are recorded at MODULE level.
    
    All assessments and grades are associated with specific modules.
    Students receive marks for module-level assessments.
    """
    __tablename__ = 'marks'
    
    id = db.Column(db.Integer, primary_key=True)
    # REMOVED: course_id - marks are at module level
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False)  # NOW REQUIRED
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    assessment_type = db.Column(db.String(50), nullable=False)  # assignment, quiz, participation, project
    assessment_name = db.Column(db.String(200), nullable=False)
    mark = db.Column(db.Float, nullable=False)
    total_marks = db.Column(db.Float, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    grade = db.Column(db.String(5), nullable=True)  # A, B, C, D, F
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    feedback = db.Column(db.Text, nullable=True)
    marked_at = db.Column(db.DateTime, default=app_now)
    created_at = db.Column(db.DateTime, default=app_now)
    updated_at = db.Column(db.DateTime, default=app_now, onupdate=app_now)
    
    # Relationships
    recorder = db.relationship('User', backref='recorded_marks')
    # module and student relationships are defined via backref in Module and Student models
    
    def __repr__(self):
        return f'<Mark {self.assessment_name} - {self.mark}/{self.total_marks}>'
    
    @property
    def course_id(self):
        """Get course ID through module relationship."""
        return self.module.course_id if self.module else None
    
    def calculate_grade(self):
        """Calculate letter grade based on percentage."""
        pct = clamp_pct(self.percentage)
        if pct >= 90:
            return 'A+'
        elif pct >= 85:
            return 'A'
        elif pct >= 80:
            return 'A-'
        elif pct >= 75:
            return 'B+'
        elif pct >= 70:
            return 'B'
        elif pct >= 65:
            return 'B-'
        elif pct >= 60:
            return 'C+'
        elif pct >= 55:
            return 'C'
        elif pct >= 50:
            return 'C-'
        elif pct >= 45:
            return 'D'
        else:
            return 'F'

    def sync_percentage(self) -> None:
        """Recalculate percentage from mark/total_marks (0–100)."""
        self.percentage = percentage_from_parts(self.mark, self.total_marks)
        self.grade = self.calculate_grade()
    
    def can_record(self, user):
        """Check if user can record marks for this module."""
        from app.models.lecturer import LecturerModule
        
        if not user:
            return False
        
        if user.role == 'admin':
            return True
        
        if user.role == 'lecturer':
            lecturer = user.lecturer
            if not lecturer:
                return False
            # Must be assigned to the module
            return LecturerModule.query.filter_by(
                lecturer_id=lecturer.id,
                module_id=self.module_id
            ).first() is not None
        
        return False
    
    def to_dict(self):
        return {
            'id': self.id,
            'module_id': self.module_id,
            'course_id': self.course_id,
            'module_title': self.module.title if self.module else None,
            'student_id': self.student_id,
            'student_name': self.student.user.full_name if self.student and self.student.user else None,
            'assessment_type': self.assessment_type,
            'assessment_name': self.assessment_name,
            'mark': self.mark,
            'total_marks': self.total_marks,
            'percentage': clamp_pct(self.percentage),
            'grade': self.grade or self.calculate_grade(),
            'recorded_by': self.recorder.full_name if self.recorder else None,
            'feedback': self.feedback,
            'marked_at': self.marked_at.isoformat() if self.marked_at else None
        }


@event.listens_for(Mark, "before_insert")
@event.listens_for(Mark, "before_update")
def _mark_sync_percentage(_mapper, _connection, target: Mark) -> None:
    target.sync_percentage()
