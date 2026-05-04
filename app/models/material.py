from app import db
from app.utils.app_time import app_now
import os


class CourseMaterial(db.Model):
    """Course material model - materials belong to MODULES only.
    
    All learning materials are associated with specific modules within courses.
    Students access materials through their enrolled course modules.
    """
    __tablename__ = 'course_materials'
    
    id = db.Column(db.Integer, primary_key=True)
    # REMOVED: course_id - materials belong to modules only
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False)  # NOW REQUIRED
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String(500), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    # Must match Postgres CHECK constraint in `database_schema_postgres.sql`
    # ('lecture','assignment','reading','notes','other')
    category = db.Column(db.String(50), default='other')
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=app_now)
    updated_at = db.Column(db.DateTime, default=app_now, onupdate=app_now)
    
    # Relationships
    uploader = db.relationship('User', backref='uploaded_materials')
    
    def __repr__(self):
        return f'<CourseMaterial {self.title} (Module: {self.module_id})>'
    
    @property
    def course_id(self):
        """Get course ID through module relationship."""
        return self.module.course_id if self.module else None
    
    @property
    def file_extension(self):
        """Get file extension."""
        return os.path.splitext(self.file_name)[1].lower()
    
    @property
    def file_size_mb(self):
        """Get file size in MB."""
        return round(self.file_size / (1024 * 1024), 2)
    
    def can_access(self, student):
        """Check if student can access this material."""
        from app.models.course import Enrollment
        
        if not student:
            return False
        
        # Must be enrolled in the course that contains this module
        enrollment = Enrollment.query.filter_by(
            student_id=student.id,
            course_id=self.course_id,
            status='active'
        ).first()
        
        return enrollment is not None and self.is_published
    
    def to_dict(self):
        return {
            'id': self.id,
            'module_id': self.module_id,
            'course_id': self.course_id,
            'title': self.title,
            'description': self.description,
            'file_name': self.file_name,
            'file_type': self.file_type,
            'file_size_mb': self.file_size_mb,
            'category': self.category,
            'uploaded_by': self.uploader.full_name if self.uploader else None,
            'is_published': self.is_published,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
