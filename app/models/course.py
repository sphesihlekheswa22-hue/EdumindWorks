from app import db
from app.utils.app_time import app_now, app_today


class Course(db.Model):
    """Course model representing academic courses.
    
    Courses primarily use module-level lecturer assignment (many-to-many).
    Optionally, a course may have a "primary lecturer" assigned for display
    and admin management convenience.
    """
    __tablename__ = 'courses'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    credits = db.Column(db.Integer, default=3)
    # Optional primary lecturer for this course (admin-assigned).
    lecturer_id = db.Column(db.Integer, db.ForeignKey('lecturers.id'), nullable=True, index=True)
    semester = db.Column(db.String(20), nullable=True)
    year = db.Column(db.Integer, default=lambda: app_today().year)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=app_now)
    updated_at = db.Column(db.DateTime, default=app_now, onupdate=app_now)
    
    # Relationships
    modules = db.relationship('Module', backref='course', lazy=True, cascade='all, delete-orphan')
    enrollments = db.relationship('Enrollment', backref='course', lazy=True, cascade='all, delete-orphan')
    lecturer = db.relationship('Lecturer', foreign_keys=[lecturer_id], lazy='joined')
    
    def __repr__(self):
        return f'<Course {self.code}: {self.name}>'
    
    def get_enrolled_students(self):
        """Get all enrolled students."""
        return [e.student for e in self.enrollments if e.status == 'active']
    
    def get_student_count(self):
        """Get count of enrolled students."""
        return sum(1 for e in self.enrollments if e.status == 'active')
    
    def get_lecturers(self):
        """Get all lecturers teaching this course (through modules)."""
        from app.models.lecturer import Lecturer, LecturerModule
        lecturer_ids = db.session.query(LecturerModule.lecturer_id).join(
            Module, LecturerModule.module_id == Module.id
        ).filter(
            Module.course_id == self.id
        ).distinct().all()
        return Lecturer.query.filter(Lecturer.id.in_([lid[0] for lid in lecturer_ids])).all()

    def get_primary_lecturer(self):
        """Return the admin-assigned primary lecturer if set, else first module lecturer."""
        if self.lecturer:
            return self.lecturer
        lecturers = self.get_lecturers()
        return lecturers[0] if lecturers else None
    
    @property
    def average(self):
        """Property for average grade/percentage - used by templates."""
        return self.get_average_progress()
    
    def get_average_progress(self):
        """Calculate average progress across all modules for enrolled students."""
        from app.models.student_module_progress import StudentModuleProgress
        
        enrollment_ids = [e.id for e in self.enrollments if e.status == 'active']
        if not enrollment_ids:
            return 0
        
        module_ids = [m.id for m in self.modules]
        if not module_ids:
            return 0
        
        progress_records = StudentModuleProgress.query.filter(
            StudentModuleProgress.enrollment_id.in_(enrollment_ids),
            StudentModuleProgress.module_id.in_(module_ids)
        ).all()
        
        if not progress_records:
            return 0
        
        total_completion = sum(p.completion_percentage or 0 for p in progress_records)
        return round(total_completion / len(progress_records))
    
    def to_dict(self):
        primary_lect = self.get_primary_lecturer()
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'credits': self.credits,
            'lecturer_id': self.lecturer_id,
            'lecturer_name': (primary_lect.user.full_name if primary_lect and primary_lect.user else None),
            'semester': self.semester,
            'year': self.year,
            'is_active': self.is_active,
            'student_count': self.get_student_count(),
            'module_count': len(self.modules)
        }


class Module(db.Model):
    """Module model representing course modules/chapters.
    
    This is where lecturers are assigned (many-to-many via lecturer_modules).
    All learning content (materials, quizzes, assignments, attendance, marks)
    belongs to modules, not courses directly.
    """
    __tablename__ = 'modules'
    
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    order = db.Column('module_order', db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=app_now)
    
    # Relationships - all content belongs to modules
    materials = db.relationship('CourseMaterial', backref='module', lazy=True, cascade='all, delete-orphan')
    quizzes = db.relationship('Quiz', backref='module', lazy=True, cascade='all, delete-orphan')
    assignments = db.relationship('Assignment', backref='module', lazy=True, cascade='all, delete-orphan')
    attendances = db.relationship('Attendance', backref='module', lazy=True, cascade='all, delete-orphan')
    marks = db.relationship('Mark', backref='module', lazy=True, cascade='all, delete-orphan')
    lecturer_assignments = db.relationship('LecturerModule', backref='module', lazy=True, cascade='all, delete-orphan')
    student_progress = db.relationship('StudentModuleProgress', backref='module', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Module {self.title} (Course: {self.course.code if self.course else "N/A"})>'
    
    @property
    def lecturers(self):
        """Get all lecturers assigned to this module."""
        from app.models.lecturer import Lecturer
        return [lm.lecturer for lm in self.lecturer_assignments]
    
    @property
    def primary_lecturer(self):
        """Get the primary lecturer for this module."""
        primary = next((lm for lm in self.lecturer_assignments if lm.is_primary), None)
        return primary.lecturer if primary else (self.lecturers[0] if self.lecturers else None)
    
    def is_lecturer_assigned(self, lecturer_id):
        """Check if a lecturer is assigned to this module."""
        return any(lm.lecturer_id == lecturer_id for lm in self.lecturer_assignments)
    
    def to_dict(self):
        return {
            'id': self.id,
            'course_id': self.course_id,
            'course_code': self.course.code if self.course else None,
            'title': self.title,
            'description': self.description,
            'order': self.order,
            'material_count': len(self.materials),
            'quiz_count': len(self.quizzes),
            'assignment_count': len(self.assignments),
            'lecturer_count': len(self.lecturer_assignments)
        }


class Enrollment(db.Model):
    """Enrollment model for student-course relationships.
    
    Students enroll in COURSES only. Access to modules is granted
    through course enrollment.
    """
    __tablename__ = 'enrollments'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    status = db.Column(db.String(20), default='active')  # active, completed, dropped
    enrolled_at = db.Column(db.DateTime, default=app_now)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Ensure unique enrollment per student per course
    __table_args__ = (
        db.UniqueConstraint('student_id', 'course_id', name='unique_enrollment'),
    )
    
    # Relationships
    module_progress = db.relationship('StudentModuleProgress', backref='enrollment', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Enrollment Student {self.student_id} - Course {self.course_id}>'
    
    def get_module_progress(self, module_id):
        """Get progress for a specific module."""
        return next((p for p in self.module_progress if p.module_id == module_id), None)
    
    def get_overall_progress(self):
        """Calculate overall progress across all course modules."""
        if not self.module_progress:
            return 0
        total = sum(p.completion_percentage or 0 for p in self.module_progress)
        return round(total / len(self.module_progress))
    
    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'course_id': self.course_id,
            'status': self.status,
            'overall_progress': self.get_overall_progress(),
            'enrolled_at': self.enrolled_at.isoformat() if self.enrolled_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }
