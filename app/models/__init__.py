from app.models.user import User
from app.models.student import Student
from app.models.lecturer import Lecturer, LecturerModule
from app.models.course import Course, Module, Enrollment
from app.models.student_module_progress import StudentModuleProgress
from app.models.material import CourseMaterial
from app.models.quiz import Quiz, QuizQuestion, QuizResult
from app.models.attendance import Attendance
from app.models.mark import Mark
from app.models.study_plan import StudyPlan, StudyPlanItem
from app.models.chat import ChatSession, ChatMessage
from app.models.cv_review import CVReview
from app.models.risk_score import RiskScore
from app.models.notification import Notification, InterventionMessage
from app.models.assignment import Assignment, AssignmentSubmission, AssignmentAttachment
from app.models.staff_profile import StaffProfile

__all__ = [
    'User',
    'Student',
    'Lecturer', 
    'LecturerModule',  # NEW - many-to-many lecturer-module assignments
    'Course',
    'Module',
    'Enrollment',
    'StudentModuleProgress',  # NEW - module-level progress tracking
    'CourseMaterial',
    'Quiz',
    'QuizQuestion',
    'QuizResult',
    'Attendance',
    'Mark',
    'StudyPlan',
    'StudyPlanItem',
    'ChatSession',
    'ChatMessage',
    'CVReview',
    'RiskScore',
    'Notification',
    'InterventionMessage',
    'Assignment',
    'AssignmentSubmission',
    'AssignmentAttachment',
    'StaffProfile',
]
