from app import db
from app.utils.app_time import app_now


class RiskScore(db.Model):
    """Risk score model for academic performance monitoring."""
    __tablename__ = 'risk_scores'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    risk_level = db.Column(db.String(20), nullable=False)  # low, medium, high, critical
    risk_score = db.Column(db.Float, nullable=False)  # overall performance score 0-100 (higher is better)
    attendance_score = db.Column(db.Float, nullable=True)
    quiz_score = db.Column(db.Float, nullable=True)
    assignment_score = db.Column(db.Float, nullable=True)
    overall_score = db.Column(db.Float, nullable=True)
    risk_factors = db.Column(db.Text, nullable=True)  # JSON array of risk factors
    recommendations = db.Column(db.Text, nullable=True)
    calculated_at = db.Column(db.DateTime, default=app_now)
    
    # Relationships
    course = db.relationship('Course', backref='risk_scores')
    
    def __repr__(self):
        return f'<RiskScore Student {self.student_id} - Level {self.risk_level}>'
    
    def calculate_risk_level(self):
        """Calculate risk level from the stored performance score (higher score = lower risk)."""
        score = self.overall_score if self.overall_score is not None else self.risk_score
        return performance_level_from_score(score)

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'student_id': self.student_id,
            'student_name': self.student.user.full_name if self.student and self.student.user else None,
            'course_id': self.course_id,
            'course_name': self.course.name if self.course else 'Overall',
            'risk_level': self.risk_level,
            'risk_score': self.risk_score,
            'attendance_score': self.attendance_score,
            'quiz_score': self.quiz_score,
            'assignment_score': self.assignment_score,
            'overall_score': self.overall_score,
            'risk_factors': json.loads(self.risk_factors) if self.risk_factors else [],
            'recommendations': self.recommendations,
            'calculated_at': self.calculated_at.isoformat() if self.calculated_at else None
        }


def performance_level_from_score(overall_score: float) -> str:
    if overall_score >= 75:
        return "low"
    if overall_score >= 60:
        return "medium"
    if overall_score >= 50:
        return "high"
    return "critical"
