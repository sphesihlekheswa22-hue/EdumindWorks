"""
Seed data script to populate all tables with test data.
Run with: python seed_data.py
"""
import os
import sys
import json
from datetime import datetime, timedelta
import random

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, bcrypt
from app.utils.app_time import app_now
from app.models import (
    User, Student, Lecturer, Course, Module, Enrollment,
    StudentModuleProgress,
    CourseMaterial, Quiz, QuizQuestion, QuizResult,
    Attendance, Mark, StudyPlan, StudyPlanItem,
    ChatSession, ChatMessage, CVReview, RiskScore,
    Notification, InterventionMessage,
    Assignment, AssignmentAttachment, AssignmentSubmission,
    StaffProfile,
)

def _static_dir_candidates() -> list[str]:
    """Return possible absolute paths to the Flask static directory."""
    root = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(root, "app", "static"),
        os.path.join(root, "app", "app", "static"),
    ]


def _write_bytes_under_static(static_rel_path: str, data: bytes) -> None:
    """
    Write bytes to *all* discovered static dirs.
    `static_rel_path` must be relative to /static (e.g. 'uploads/materials/1/file.pdf').
    """
    rel = static_rel_path.lstrip("/").replace("/", os.sep)
    for static_dir in _static_dir_candidates():
        if not os.path.isdir(static_dir):
            continue
        abs_path = os.path.join(static_dir, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        if not os.path.exists(abs_path):
            with open(abs_path, "wb") as f:
                f.write(data)


def _tiny_pdf_bytes(title: str) -> bytes:
    """
    Minimal PDF bytes (enough to download/open in most viewers).
    Keeps repo/demo files tiny.
    """
    txt = (title or "EduMind Demo File").replace("(", "").replace(")", "")
    body = f"""%PDF-1.4
1 0 obj<<>>endobj
2 0 obj<< /Length 44 >>stream
BT /F1 18 Tf 72 720 Td ({txt}) Tj ET
endstream endobj
3 0 obj<< /Type /Catalog /Pages 4 0 R >>endobj
4 0 obj<< /Type /Pages /Kids [5 0 R] /Count 1 >>endobj
5 0 obj<< /Type /Page /Parent 4 0 R /MediaBox [0 0 612 792] /Contents 2 0 R >>endobj
xref
0 6
0000000000 65535 f 
0000000010 00000 n 
0000000030 00000 n 
0000000125 00000 n 
0000000173 00000 n 
0000000230 00000 n 
trailer<< /Size 6 /Root 3 0 R >>
startxref
310
%%EOF
"""
    return body.encode("utf-8", errors="ignore")

def _uploads_dir_candidates() -> list[str]:
    """Return possible absolute paths to the uploads directory (static/uploads)."""
    out = []
    for static_dir in _static_dir_candidates():
        out.append(os.path.join(static_dir, "uploads"))
    return out


def _write_bytes_under_uploads(uploads_rel_path: str, data: bytes) -> None:
    """
    Write bytes to *all* discovered uploads dirs.
    `uploads_rel_path` must be relative to /static/uploads (e.g. 'assignments/specs/1/file.pdf').
    """
    rel = uploads_rel_path.lstrip("/").replace("/", os.sep)
    for uploads_dir in _uploads_dir_candidates():
        if not os.path.isdir(uploads_dir):
            continue
        abs_path = os.path.join(uploads_dir, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        if not os.path.exists(abs_path):
            with open(abs_path, "wb") as f:
                f.write(data)


def _primary_uploads_dir() -> str:
    """Pick one uploads dir that exists (fallback to first candidate)."""
    for uploads_dir in _uploads_dir_candidates():
        if os.path.isdir(uploads_dir):
            return uploads_dir
    return _uploads_dir_candidates()[0]

def clear_all_data():
    """Clear all data from the database before seeding."""
    print("Clearing existing data...")
    
    # Import LecturerModule for clearing
    from app.models.lecturer import LecturerModule
    
    # Delete in reverse order of dependencies
    ChatMessage.query.delete()
    ChatSession.query.delete()
    StudyPlanItem.query.delete()
    StudyPlan.query.delete()
    RiskScore.query.delete()
    CVReview.query.delete()
    Notification.query.delete()
    InterventionMessage.query.delete()
    StudentModuleProgress.query.delete()
    StaffProfile.query.delete()
    AssignmentSubmission.query.delete()
    AssignmentAttachment.query.delete()
    Assignment.query.delete()
    QuizResult.query.delete()
    QuizQuestion.query.delete()
    Quiz.query.delete()
    CourseMaterial.query.delete()
    Attendance.query.delete()
    Mark.query.delete()
    Enrollment.query.delete()
    LecturerModule.query.delete()  # Clear lecturer-module assignments
    Module.query.delete()
    Course.query.delete()
    Student.query.delete()
    Lecturer.query.delete()
    User.query.delete()
    
    db.session.commit()
    print("  All existing data cleared.")

def seed_users():
    """Create users for admin, lecturers, career advisor, and students."""
    print("Seeding Users...")
    
    # Staff numbers for non-lecturer staff (admin/career advisor)
    staff_numbers = {
        "admin@edumind.com": "STAFF0001",
        "career@edumind.com": "STAFF0002",
    }

    users_data = [
        # Admin
        {'email': 'admin@edumind.com', 'first_name': 'System', 'last_name': 'Admin', 'role': 'admin', 'password': 'admin123'},
        
        # Career Advisor
        {'email': 'career@edumind.com', 'first_name': 'Sarah', 'last_name': 'Johnson', 'role': 'career_advisor', 'password': 'career123'},
        
        # Lecturers
        {'email': 'john.smith@edumind.com', 'first_name': 'John', 'last_name': 'Smith', 'role': 'lecturer', 'password': 'lecturer123'},
        {'email': 'emily.davis@edumind.com', 'first_name': 'Emily', 'last_name': 'Davis', 'role': 'lecturer', 'password': 'lecturer123'},
        {'email': 'michael.brown@edumind.com', 'first_name': 'Michael', 'last_name': 'Brown', 'role': 'lecturer', 'password': 'lecturer123'},
        {'email': 'jennifer.wilson@edumind.com', 'first_name': 'Jennifer', 'last_name': 'Wilson', 'role': 'lecturer', 'password': 'lecturer123'},
        {'email': 'david.lee@edumind.com', 'first_name': 'David', 'last_name': 'Lee', 'role': 'lecturer', 'password': 'lecturer123'},
        
        # Students
        {'email': 'alex.thompson@student.edumind.com', 'first_name': 'Alex', 'last_name': 'Thompson', 'role': 'student', 'password': 'student123'},
        {'email': 'sophia.martinez@student.edumind.com', 'first_name': 'Sophia', 'last_name': 'Martinez', 'role': 'student', 'password': 'student123'},
        {'email': 'lucas.anderson@student.edumind.com', 'first_name': 'Lucas', 'last_name': 'Anderson', 'role': 'student', 'password': 'student123'},
        {'email': 'olivia.taylor@student.edumind.com', 'first_name': 'Olivia', 'last_name': 'Taylor', 'role': 'student', 'password': 'student123'},
        {'email': 'noah.white@student.edumind.com', 'first_name': 'Noah', 'last_name': 'White', 'role': 'student', 'password': 'student123'},
        {'email': 'emma.harris@student.edumind.com', 'first_name': 'Emma', 'last_name': 'Harris', 'role': 'student', 'password': 'student123'},
        {'email': 'liam.clark@student.edumind.com', 'first_name': 'Liam', 'last_name': 'Clark', 'role': 'student', 'password': 'student123'},
        {'email': 'ava.lewis@student.edumind.com', 'first_name': 'Ava', 'last_name': 'Lewis', 'role': 'student', 'password': 'student123'},
        {'email': 'mason.walker@student.edumind.com', 'first_name': 'Mason', 'last_name': 'Walker', 'role': 'student', 'password': 'student123'},
        {'email': 'isabella.hall@student.edumind.com', 'first_name': 'Isabella', 'last_name': 'Hall', 'role': 'student', 'password': 'student123'},
        {'email': 'james.allen@student.edumind.com', 'first_name': 'James', 'last_name': 'Allen', 'role': 'student', 'password': 'student123'},
    ]
    
    users = []
    for data in users_data:
        password = data.pop('password')
        user = User(**data)
        user.set_password(password)
        db.session.add(user)
        users.append(user)
    
    db.session.commit()

    # Create StaffProfile rows for non-lecturer staff so they can log in via staff number.
    for u in users:
        if u.role in ("admin", "career_advisor"):
            sn = staff_numbers.get(u.email)
            if sn:
                db.session.add(StaffProfile(user_id=u.id, staff_number=sn))
    db.session.commit()

    print(f"  Created {len(users)} users")
    return users

def seed_students(users):
    """Create student profiles."""
    print("Seeding Students...")
    
    student_users = [u for u in users if u.role == 'student']
    students = []
    
    programs = ['Computer Science', 'Engineering', 'Business Administration', 'Mathematics', 'Physics']
    years = [1, 2, 3, 4]
    
    for i, user in enumerate(student_users):
        student = Student(
            user_id=user.id,
            student_id=f'{220900000 + i:09d}',
            date_of_birth=datetime(2000 + random.randint(0, 4), random.randint(1, 12), random.randint(1, 28)).date(),
            phone=f'+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}',
            address=f'{random.randint(100, 999)} University Ave, Campus {random.randint(1, 5)}',
            program=random.choice(programs),
            year_of_study=random.choice(years),
            enrollment_date=datetime(2023, random.randint(1, 9), 1).date()
        )
        db.session.add(student)
        students.append(student)
    
    db.session.commit()
    print(f"  Created {len(students)} students")
    return students

def seed_lecturers(users):
    """Create lecturer profiles."""
    print("Seeding Lecturers...")
    
    lecturer_users = [u for u in users if u.role == 'lecturer']
    lecturers = []
    
    departments = ['Computer Science', 'Engineering', 'Mathematics', 'Business', 'Physics']
    titles = ['Professor', 'Dr.', 'Lecturer', 'Senior Lecturer']
    specializations = ['Machine Learning', 'Data Structures', 'Calculus', 'Marketing', 'Quantum Physics']
    
    for i, user in enumerate(lecturer_users):
        lecturer = Lecturer(
            user_id=user.id,
            employee_id=f'EMP{1000 + i}',
            department=departments[i % len(departments)],
            title=titles[i % len(titles)],
            phone=f'+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}',
            office=f'Building {random.randint(1, 5)}, Room {random.randint(100, 599)}',
            hire_date=datetime(2015 + random.randint(0, 8), random.randint(1, 12), 1).date(),
            specialization=specializations[i % len(specializations)]
        )
        db.session.add(lecturer)
        lecturers.append(lecturer)
    
    db.session.commit()
    print(f"  Created {len(lecturers)} lecturers")
    return lecturers

def seed_courses(lecturers):
    """Create courses - Diploma programs."""
    print("Seeding Courses...")
    
    courses_data = [
        {'code': 'DIT', 'name': 'Diploma in Information Technology', 'credits': 120, 'description': 'Comprehensive IT diploma covering programming, databases, web development, networks, and systems analysis.'},
        {'code': 'DCE', 'name': 'Diploma in Civil Engineering', 'credits': 120, 'description': 'Civil engineering diploma covering mathematics, structural mechanics, construction technology, surveying, and fluid mechanics.'},
        {'code': 'DBM', 'name': 'Diploma in Business Management', 'credits': 120, 'description': 'Business management diploma covering management principles, accounting, marketing, business law, and entrepreneurship.'},
        {'code': 'DGD', 'name': 'Diploma in Graphic Design', 'credits': 120, 'description': 'Graphic design diploma covering visual communication, digital illustration, typography, photography, and design theory.'},
        {'code': 'DES', 'name': 'Diploma in Environmental Science', 'credits': 120, 'description': 'Environmental science diploma covering ecology, environmental management, geology, chemistry, and research methods.'},
    ]
    
    courses = []
    for i, data in enumerate(courses_data):
        course = Course(
            code=data['code'],
            name=data['name'],
            credits=data['credits'],
            description=data['description'],
            semester='Full Year',
            year=2025,
            is_active=True
        )
        db.session.add(course)
        courses.append(course)
    
    db.session.commit()
    print(f"  Created {len(courses)} courses")
    return courses

def seed_modules(courses):
    """Create course modules - specific modules for each diploma."""
    print("Seeding Modules...")
    
    modules = []
    
    # Define modules for each course
    course_modules = {
        'DIT': [
            {'title': 'Programming (Java / C#)', 'description': 'Learn programming fundamentals using Java and C# languages, including object-oriented programming concepts.'},
            {'title': 'Database Development (SQL)', 'description': 'Master database design, implementation, and management using SQL and relational database systems.'},
            {'title': 'Web Development (HTML, CSS, JavaScript)', 'description': 'Build modern web applications using HTML, CSS, and JavaScript technologies.'},
            {'title': 'Systems Analysis & Design', 'description': 'Learn to analyze business requirements and design effective information systems.'},
            {'title': 'Computer Networks', 'description': 'Understand networking concepts, protocols, and infrastructure for modern IT systems.'},
        ],
        'DCE': [
            {'title': 'Engineering Mathematics', 'description': 'Mathematical foundations for civil engineering including calculus, linear algebra, and differential equations.'},
            {'title': 'Structural Mechanics', 'description': 'Analysis of forces, stresses, and strains in structural elements and systems.'},
            {'title': 'Construction Technology', 'description': 'Modern construction methods, materials, and project management techniques.'},
            {'title': 'Surveying', 'description': 'Land surveying techniques, equipment, and measurement principles.'},
            {'title': 'Fluid Mechanics', 'description': 'Study of fluid behavior, hydraulics, and applications in civil engineering.'},
        ],
        'DBM': [
            {'title': 'Business Management', 'description': 'Fundamentals of managing organizations, leadership, and strategic planning.'},
            {'title': 'Financial Accounting', 'description': 'Accounting principles, financial statements, and business financial management.'},
            {'title': 'Marketing Principles', 'description': 'Marketing strategies, consumer behavior, and market analysis techniques.'},
            {'title': 'Business Law', 'description': 'Legal frameworks governing business operations, contracts, and commercial transactions.'},
            {'title': 'Entrepreneurship', 'description': 'Starting and managing new ventures, business planning, and innovation.'},
        ],
        'DGD': [
            {'title': 'Visual Communication Design', 'description': 'Principles of visual communication, design thinking, and creative problem-solving.'},
            {'title': 'Digital Illustration', 'description': 'Digital art creation techniques using industry-standard software and tools.'},
            {'title': 'Typography', 'description': 'The art and technique of arranging type for effective communication.'},
            {'title': 'Photography', 'description': 'Photographic techniques, composition, lighting, and digital image processing.'},
            {'title': 'Design Theory', 'description': 'Theoretical foundations of design, color theory, and design history.'},
        ],
        'DES': [
            {'title': 'Ecology', 'description': 'Study of ecosystems, biodiversity, and interactions between organisms and their environment.'},
            {'title': 'Environmental Management', 'description': 'Sustainable resource management, environmental policy, and conservation strategies.'},
            {'title': 'Geology', 'description': 'Earth science, rock formations, geological processes, and natural resource exploration.'},
            {'title': 'Chemistry', 'description': 'Chemical principles and their applications in environmental science and analysis.'},
            {'title': 'Research Methods', 'description': 'Scientific research methodology, data collection, analysis, and reporting.'},
        ],
    }
    
    for course in courses:
        if course.code in course_modules:
            for i, module_data in enumerate(course_modules[course.code]):
                module = Module(
                    course_id=course.id,
                    title=module_data['title'],
                    description=module_data['description'],
                    order=i+1
                )
                db.session.add(module)
                modules.append(module)
    
    db.session.commit()
    print(f"  Created {len(modules)} modules")
    return modules

def seed_lecturer_modules(lecturers, modules):
    """Assign lecturers to modules (many-to-many relationship)."""
    print("Seeding Lecturer-Module Assignments...")
    
    from app.models.lecturer import LecturerModule
    
    assignments = []
    
    # Get lecturer and module IDs upfront to avoid autoflush issues
    lecturer_ids = [l.id for l in lecturers]
    module_ids = [m.id for m in modules]
    
    assignment_set = set()  # Track (lecturer_id, module_id) pairs to avoid duplicates
    
    # Distribute modules among lecturers
    for i, module_id in enumerate(module_ids):
        # Assign 1-2 lecturers per module
        num_lecturers = random.randint(1, 2)
        assigned_lecturer_ids = random.sample(lecturer_ids, min(num_lecturers, len(lecturer_ids)))
        
        for j, lecturer_id in enumerate(assigned_lecturer_ids):
            # Check for duplicate
            key = (lecturer_id, module_id)
            if key in assignment_set:
                continue
            assignment_set.add(key)
            
            assignment = LecturerModule(
                lecturer_id=lecturer_id,
                module_id=module_id,
                is_primary=(j == 0)  # First lecturer is primary
            )
            db.session.add(assignment)
            assignments.append(assignment)
        
        # Commit every 20 modules to avoid buildup
        if (i + 1) % 20 == 0:
            db.session.commit()
    
    db.session.commit()
    print(f"  Created {len(assignments)} lecturer-module assignments")
    return assignments

def seed_enrollments(students, courses):
    """Create enrollments - each student enrolled in ONE course only (single-course restriction)."""
    print("Seeding Enrollments...")
    
    enrollments = []
    
    # Enroll each student in exactly 1 course (single-course restriction)
    for i, student in enumerate(students):
        # Distribute students across courses evenly
        course = courses[i % len(courses)]
        
        enrollment = Enrollment(
            student_id=student.id,
            course_id=course.id,
            status='active',
            enrolled_at=datetime(2024, random.randint(1, 9), random.randint(1, 28))
        )
        db.session.add(enrollment)
        enrollments.append(enrollment)
    
    db.session.commit()
    print(f"  Created {len(enrollments)} enrollments (1 course per student)")
    return enrollments

def seed_materials(courses, modules, users):
    """Create course materials."""
    print("Seeding Course Materials...")
    
    materials = []
    categories = ['lecture', 'assignment', 'reading', 'notes']
    
    # Use actual PDF files that exist in the uploads folder
    # File paths are relative to static folder: /static/uploads/materials/{course_id}/{filename}
    
    material_count = 0
    for course in courses:
        # Get modules for this course
        course_modules = [m for m in modules if m.course_id == course.id]
        if not course_modules:
            continue
            
        # Add 2-3 materials per course (assigned to modules)
        for i in range(random.randint(2, 3)):
            # Use actual file that exists or use a placeholder
            # For course 11, we have 'Introduction_to_INT316D_and_JEE.pdf' in the system
            if course.id == 11:
                filename = f'Introduction_to_INT316D_and_JEE.pdf'
                file_path = f'/static/uploads/materials/{course.id}/{filename}'
            else:
                # Generate unique filename
                filename = f'{course.code.lower()}_material_{i+1}.pdf'
                file_path = f'/static/uploads/materials/{course.id}/{filename}'
            
            # Pick a random module from this course
            target_module = random.choice(course_modules)
            
            # Ensure file exists for downloads
            # file_path stored as '/static/...', we write under static dir as 'uploads/...'
            _write_bytes_under_static(
                file_path.replace("/static/", "", 1),
                _tiny_pdf_bytes(f"{course.code} demo material {i+1}")
            )

            material = CourseMaterial(
                module_id=target_module.id,
                title=f'{course.code} - {random.choice(categories).title()} {i+1}',
                description=f'Course material for {course.name}',
                file_path=file_path,
                file_name=filename,
                file_type='pdf',
                file_size=random.randint(50000, 1500000),  # Realistic PDF sizes
                category=random.choice(categories),
                uploaded_by=users[0].id,  # Admin uploads
                is_published=True
            )
            db.session.add(material)
            materials.append(material)
            material_count += 1
    
    db.session.commit()
    print(f"  Created {len(materials)} course materials")
    return materials

def seed_quizzes(courses, modules, users):
    """Create quizzes (at least 5 per module)."""
    print("Seeding Quizzes...")
    
    quizzes = []
    quiz_titles = [
        'Midterm Exam',
        'Final Exam',
        'Weekly Quiz 1',
        'Weekly Quiz 2',
        'Practice Quiz'
    ]

    # 5 quizzes per module
    for module in modules:
        course = next((c for c in courses if c.id == module.course_id), None)
        course_code = course.code if course else "COURSE"
        course_name = course.name if course else "Course"

        for i, title in enumerate(quiz_titles):
            quiz = Quiz(
                module_id=module.id,
                title=f'{course_code} - {module.title} - {title}',
                description=f'{title} for {course_name} ({module.title})',
                created_by=users[0].id,
                time_limit=1,  # fallback when time_limit_seconds is not used elsewhere
                time_limit_seconds=40,
                passing_score=random.choice([50, 60, 70]),
                is_published=True,
                is_ai_generated=False,
                due_date=app_now() + timedelta(days=120),
            )
            db.session.add(quiz)
            quizzes.append(quiz)
    
    db.session.commit()
    print(f"  Created {len(quizzes)} quizzes")
    return quizzes


def seed_assignments(courses, modules, users):
    """Create module-based assignments (at least 5 per module) with downloadable spec attachments."""
    print("Seeding Assignments...")

    assignments = []
    attachment_count = 0

    lecturer_like_user_id = users[0].id if users else None  # admin as uploader/marker when needed
    uploads_root = _primary_uploads_dir()

    assignment_titles = [
        "Assignment 1",
        "Assignment 2",
        "Assignment 3",
        "Assignment 4",
        "Assignment 5",
    ]

    for module in modules:
        course = next((c for c in courses if c.id == module.course_id), None)
        course_code = course.code if course else "COURSE"
        course_name = course.name if course else "Course"

        for i, title in enumerate(assignment_titles):
            assignment = Assignment(
                module_id=module.id,
                title=f"{course_code} - {module.title} - {title}",
                description=f"Submit your work for {course_name} ({module.title}).",
                due_date=app_now() + timedelta(days=30 + i * 7),
                total_marks=random.choice([50, 75, 100]),
            )
            db.session.add(assignment)
            db.session.flush()  # ensure assignment.id exists for file paths

            # Always attach 2 spec files (real PDFs) to avoid missing file errors
            for j in range(2):
                filename = f"{course_code}_module_{module.id}_assignment_{i+1}_spec_{j+1}.pdf"
                rel = f"assignments/specs/{assignment.id}/{filename}"
                _write_bytes_under_uploads(rel, _tiny_pdf_bytes(f"{assignment.title} spec {j+1}"))

                abs_path = os.path.join(uploads_root, rel.replace("/", os.sep))
                db.session.add(
                    AssignmentAttachment(
                        assignment_id=assignment.id,
                        file_path=abs_path,
                        file_name=filename,
                    )
                )
                attachment_count += 1

            assignments.append(assignment)

    db.session.commit()
    print(f"  Created {len(assignments)} assignments")
    print(f"  Created {attachment_count} assignment attachments (spec files)")
    return assignments


def seed_assignment_submissions(assignments, students):
    """Create some student submissions with downloadable files."""
    print("Seeding Assignment Submissions...")

    submissions = []
    uploads_root = _primary_uploads_dir()

    # 0-2 submissions per assignment (random students)
    for assignment in assignments:
        if not students:
            break
        submitters = random.sample(students, k=min(len(students), random.randint(0, 2)))
        for student in submitters:
            filename = f"{student.student_id}_submission_{assignment.id}.pdf"
            rel = f"assignments/{student.id}/{filename}"
            _write_bytes_under_uploads(rel, _tiny_pdf_bytes(f"Submission {student.student_id} for {assignment.title}"))
            abs_path = os.path.join(uploads_root, rel.replace("/", os.sep))

            sub = AssignmentSubmission(
                assignment_id=assignment.id,
                student_id=student.id,
                file_path=abs_path,
                file_name=filename,
                submitted_at=app_now() - timedelta(days=random.randint(0, 10)),
                status="submitted",
            )
            db.session.add(sub)
            submissions.append(sub)

    db.session.commit()
    print(f"  Created {len(submissions)} assignment submissions")
    return submissions


def seed_student_module_progress(enrollments, modules):
    """Create module-level progress records for enrolled students (covers student_module_progress table)."""
    print("Seeding Student Module Progress...")

    progress_rows = []

    # Map course -> modules to avoid repeated filtering
    modules_by_course = {}
    for m in modules:
        modules_by_course.setdefault(m.course_id, []).append(m)

    for enr in enrollments:
        course_modules = modules_by_course.get(enr.course_id, [])
        for mod in course_modules:
            pct = random.choice([0, 10, 25, 50, 75, 100])
            status = "not_started" if pct == 0 else ("completed" if pct >= 100 else "in_progress")
            row = StudentModuleProgress(
                student_id=enr.student_id,
                module_id=mod.id,
                enrollment_id=enr.id,
                completion_status=status,
                completion_percentage=pct,
                materials_viewed=random.randint(0, 3),
                quizzes_completed=random.randint(0, 2),
                assignments_submitted=random.randint(0, 2),
                attendance_sessions=random.randint(0, 6),
                last_accessed_at=app_now() - timedelta(days=random.randint(0, 14)),
            )
            if pct > 0:
                row.started_at = app_now() - timedelta(days=random.randint(1, 30))
            if pct >= 100:
                row.completed_at = app_now() - timedelta(days=random.randint(0, 10))
            db.session.add(row)
            progress_rows.append(row)

    db.session.commit()
    print(f"  Created {len(progress_rows)} student module progress records")
    return progress_rows


def seed_interventions_and_notifications(users, students, lecturers, courses, materials, quizzes, assignments, cv_reviews):
    """Seed intervention messages + notifications so tables are never empty."""
    print("Seeding Notifications & Interventions...")

    notifications = []
    interventions = []

    # Pick admin as default sender where needed
    admin_user = next((u for u in users if getattr(u, "role", None) == "admin"), users[0] if users else None)

    # Create a few intervention messages (lecturer -> student)
    if lecturers and students:
        for i in range(min(10, len(students))):
            lec = random.choice(lecturers)
            stu = students[i]
            course = random.choice(courses) if courses else None
            msg = InterventionMessage(
                lecturer_id=lec.id,
                student_id=stu.id,
                course_id=course.id if course else None,
                subject="Check-in: How can I help?",
                content="I noticed you may benefit from extra support. Please book a consultation or reply with your questions.",
                template_used="support_checkin",
                risk_level_at_send=random.choice(["low", "medium", "high"]),
                recommended_actions="Attend tutorials; review lecture notes; attempt practice questions.",
            )
            db.session.add(msg)
            interventions.append(msg)

    # Notifications: give each user 1-3 notifications
    for u in users:
        for _ in range(random.randint(1, 3)):
            ntype = random.choice([
                "course_update", "material_published", "quiz_published", "assignment_posted", "cv_reviewed"
            ])
            title = {
                "course_update": "Course update",
                "material_published": "New material published",
                "quiz_published": "New quiz available",
                "assignment_posted": "New assignment posted",
                "cv_reviewed": "CV review update",
            }.get(ntype, "Notification")

            action_url = None
            entity_type = None
            entity_id = None

            if ntype == "material_published" and materials:
                m = random.choice(materials)
                entity_type, entity_id = "material", m.id
                action_url = "/materials/"
            elif ntype == "quiz_published" and quizzes:
                q = random.choice(quizzes)
                entity_type, entity_id = "quiz", q.id
                action_url = "/quizzes/"
            elif ntype == "assignment_posted" and assignments:
                a = random.choice(assignments)
                entity_type, entity_id = "assignment", a.id
                action_url = "/assignments/"
            elif ntype == "cv_reviewed" and cv_reviews:
                r = random.choice(cv_reviews)
                entity_type, entity_id = "cv_review", r.id
                action_url = "/career/cv-review"

            notif = Notification(
                recipient_id=u.id,
                sender_id=admin_user.id if admin_user else None,
                type=ntype,
                title=title,
                message="This is a demo notification seeded for testing the UI.",
                priority=random.choice(["low", "normal", "high"]),
                action_url=action_url,
                action_text="Open" if action_url else None,
                entity_type=entity_type,
                entity_id=entity_id,
                is_read=random.random() > 0.6,
            )
            db.session.add(notif)
            notifications.append(notif)

    db.session.commit()
    print(f"  Created {len(interventions)} intervention messages")
    print(f"  Created {len(notifications)} notifications")
    return notifications, interventions


def seed_quiz_questions(quizzes):
    """Create quiz questions (every quiz gets at least five; MC uses five options)."""
    print("Seeding Quiz Questions...")
    
    questions = []
    mc_options_pool = ['Option A', 'Option B', 'Option C', 'Option D', 'Option E']
    
    q_count = 0
    for quiz in quizzes:
        # Fixed count so every seeded quiz reliably has questions
        num_questions = 6
        
        for i in range(num_questions):
            q_type = random.choice(['multiple_choice', 'multiple_choice', 'true_false'])
            
            if q_type == 'multiple_choice':
                options = json.dumps(mc_options_pool)
                correct = random.choice(mc_options_pool)
            else:
                options = json.dumps(['True', 'False'])
                correct = random.choice(['True', 'False'])
            
            question = QuizQuestion(
                quiz_id=quiz.id,
                question_text=f'Question {i+1}: What is the correct answer regarding {quiz.title}?',
                question_type=q_type,
                points=random.randint(1, 5),
                order=i+1,
                options=options,
                correct_answer=correct
            )
            db.session.add(question)
            questions.append(question)
            q_count += 1
    
    db.session.commit()
    print(f"  Created {len(questions)} quiz questions")
    return questions

def seed_quiz_results(quizzes, students):
    """Create quiz results aligned with student performance tiers."""
    print("Seeding Quiz Results...")
    from app.utils.percentages import percentage_from_parts

    results = []
    tier_choices = (["struggling"] * 3) + (["average"] * 5) + (["strong"] * 2)
    student_tiers = {student.id: random.choice(tier_choices) for student in students}

    def score_for_tier(tier: str, total: int, passing_score: int) -> tuple[float, float, bool]:
        if tier == "struggling":
            target_pct = random.uniform(32, min(52, max(33, passing_score - 1)))
        elif tier == "average":
            target_pct = random.uniform(58, 76)
        else:
            target_pct = random.uniform(82, 98)
        score = round(total * target_pct / 100, 1)
        percentage = percentage_from_parts(score, total)
        return score, percentage, percentage >= passing_score

    for quiz in quizzes:
        num_results = random.randint(3, min(6, len(students)))
        attempted_students = random.sample(students, num_results)

        for student in attempted_students:
            total = quiz.total_points or sum(q.points for q in quiz.questions) or 100
            total = max(1, int(total))
            tier = student_tiers.get(student.id, "average")
            score, percentage, passed = score_for_tier(tier, total, quiz.passing_score or 60)

            result = QuizResult(
                quiz_id=quiz.id,
                student_id=student.id,
                score=score,
                total_points=total,
                percentage=percentage,
                passed=passed,
                time_taken=random.randint(300, 3600),
                started_at=datetime.now() - timedelta(days=random.randint(1, 30)),
                completed_at=datetime.now() - timedelta(days=random.randint(0, 29))
            )
            db.session.add(result)
            results.append(result)

    db.session.commit()
    print(f"  Created {len(results)} quiz results")
    return results

def seed_attendance(courses, modules, students, users):
    """Create attendance records."""
    print("Seeding Attendance...")
    
    attendance_records = []
    statuses = ['present', 'present', 'present', 'absent', 'late']
    
    # Create attendance for past 10 days
    for days_ago in range(10):
        date = datetime.now().date() - timedelta(days=days_ago)
        
        for course in courses[:5]:  # First 5 courses
            # Get modules for this course
            course_modules = [m for m in modules if m.course_id == course.id]
            if not course_modules:
                continue
                
            # Random 5-8 students per course per day
            num_students = random.randint(5, min(8, len(students)))
            attending_students = random.sample(students, num_students)
            
            for student in attending_students:
                # Pick a random module from this course
                target_module = random.choice(course_modules)
                
                attendance = Attendance(
                    module_id=target_module.id,
                    student_id=student.id,
                    date=date,
                    status=random.choice(statuses),
                    recorded_by=users[0].id,
                    notes=None
                )
                db.session.add(attendance)
                attendance_records.append(attendance)
    
    db.session.commit()
    print(f"  Created {len(attendance_records)} attendance records")
    return attendance_records

def seed_marks(courses, modules, students, users):
    """Create marks/grades."""
    print("Seeding Marks...")
    
    marks = []
    assessment_types = ['assignment', 'midterm', 'final', 'quiz', 'project']
    
    for course in courses:
        # Get modules for this course
        course_modules = [m for m in modules if m.course_id == course.id]
        if not course_modules:
            continue
            
        # 5-8 marks per course
        num_marks = random.randint(5, 8)
        
        for i in range(num_marks):
            student = random.choice(students)
            assessment_type = random.choice(assessment_types)
            total = random.choice([100, 50, 20, 10])
            mark_score = random.randint(int(total * 0.4), total)
            percentage = (mark_score / total) * 100
            
            # Pick a random module from this course
            target_module = random.choice(course_modules)
            
            mark = Mark(
                module_id=target_module.id,
                student_id=student.id,
                assessment_type=assessment_type,
                assessment_name=f'{assessment_type.title()} {i+1}',
                mark=mark_score,
                total_marks=total,
                percentage=percentage,
                grade=calculate_grade(percentage),
                recorded_by=users[0].id,
                feedback='Good work!' if percentage >= 60 else 'Needs improvement.',
                marked_at=datetime.now() - timedelta(days=random.randint(1, 60))
            )
            db.session.add(mark)
            marks.append(mark)
    
    db.session.commit()
    print(f"  Created {len(marks)} marks")
    return marks

def calculate_grade(percentage):
    """Calculate letter grade."""
    if percentage >= 90:
        return 'A+'
    elif percentage >= 85:
        return 'A'
    elif percentage >= 80:
        return 'A-'
    elif percentage >= 75:
        return 'B+'
    elif percentage >= 70:
        return 'B'
    elif percentage >= 65:
        return 'B-'
    elif percentage >= 60:
        return 'C+'
    elif percentage >= 55:
        return 'C'
    elif percentage >= 50:
        return 'C-'
    elif percentage >= 45:
        return 'D'
    else:
        return 'F'

def seed_study_plans(students, courses):
    """Create study plans."""
    print("Seeding Study Plans...")
    
    study_plans = []
    
    for student in students:
        # 1-3 study plans per student
        num_plans = random.randint(1, 3)
        
        for i in range(num_plans):
            plan = StudyPlan(
                student_id=student.id,
                course_id=random.choice(courses).id if random.random() > 0.3 else None,
                title=f'{student.user.first_name}\'s Study Plan {i+1}',
                description='Personalized AI-generated study plan',
                is_ai_generated=random.choice([True, False]),
                start_date=datetime.now().date(),
                end_date=datetime.now().date() + timedelta(weeks=random.randint(2, 8)),
                status=random.choice(['active', 'active', 'completed'])
            )
            db.session.add(plan)
            study_plans.append(plan)
    
    db.session.commit()
    print(f"  Created {len(study_plans)} study plans")
    return study_plans

def seed_study_plan_items(study_plans):
    """Create study plan items."""
    print("Seeding Study Plan Items...")
    
    items = []
    task_types = ['reading', 'practice', 'review', 'assignment', 'project']
    item_statuses = ['pending', 'in_progress', 'completed']
    priorities = ['low', 'medium', 'high']
    
    for plan in study_plans:
        # 5-10 items per plan
        num_items = random.randint(5, 10)
        
        for i in range(num_items):
            item = StudyPlanItem(
                study_plan_id=plan.id,
                title=f'Task {i+1}: {random.choice(task_types).title()} session',
                description=f'Complete {random.choice(task_types)} for the course',
                task_type=random.choice(task_types),
                order=i+1,
                status=random.choice(item_statuses),
                priority=random.choice(priorities),
                due_date=datetime.now().date() + timedelta(days=random.randint(1, 30)),
                estimated_time=random.randint(30, 180)
            )
            db.session.add(item)
            items.append(item)
    
    db.session.commit()
    print(f"  Created {len(items)} study plan items")
    return items

def seed_chat_sessions(students, courses):
    """Create chat sessions."""
    print("Seeding Chat Sessions...")
    
    sessions = []
    topics = ['Homework Help', 'Exam Preparation', 'Concept Review', 'Practice Problems', 'General Questions']
    
    for student in students:
        # 1-3 chat sessions per student
        num_sessions = random.randint(1, 3)
        
        for i in range(num_sessions):
            session = ChatSession(
                student_id=student.id,
                title=f'Chat: {random.choice(topics)}',
                course_id=random.choice(courses).id if random.random() > 0.4 else None,
                topic=random.choice(topics),
                is_active=random.choice([True, False]),
                created_at=datetime.now() - timedelta(days=random.randint(1, 30))
            )
            db.session.add(session)
            sessions.append(session)
    
    db.session.commit()
    print(f"  Created {len(sessions)} chat sessions")
    return sessions

def seed_chat_messages(sessions):
    """Create chat messages."""
    print("Seeding Chat Messages...")
    
    messages = []
    
    for session in sessions:
        # 2-8 messages per session
        num_messages = random.randint(2, 8)
        
        for i in range(num_messages):
            message = ChatMessage(
                session_id=session.id,
                role='user' if i % 2 == 0 else 'assistant',
                content=f'This is message {i+1} in the chat session. ' + ('How can I help you?' if i % 2 == 1 else 'I need help with this topic.'),
                is_ai=(i % 2 == 1),
                created_at=session.created_at + timedelta(minutes=i*5)
            )
            db.session.add(message)
            messages.append(message)
    
    db.session.commit()
    print(f"  Created {len(messages)} chat messages")
    return messages

def seed_cv_reviews(students):
    """Create CV reviews."""
    print("Seeding CV Reviews...")
    
    reviews = []
    statuses = ['pending', 'reviewed', 'needs_revision']
    
    for student in students[:10]:  # First 10 students
        # Use the same sample PDF for all CVs
        cv_filename = f'cv_{student.student_id}.pdf'
        cv_path = f'/static/uploads/cv/{student.id}/{cv_filename}'

        _write_bytes_under_static(
            cv_path.replace("/static/", "", 1),
            _tiny_pdf_bytes(f"CV {student.student_id}")
        )

        review = CVReview(
            student_id=student.id,
            file_path=cv_path,
            file_name=cv_filename,
            job_readiness_score=random.randint(40, 95) if random.random() > 0.3 else None,
            status=random.choice(statuses),
            strengths='Strong technical skills, good communication, proactive learning',
            weaknesses='Could improve presentation skills, needs more industry experience',
            recommendations='Continue building projects, consider internships',
            suggested_skills=json.dumps(['Python', 'Machine Learning', 'Data Analysis']),
            suggested_projects=json.dumps(['Web App', 'Mobile App', 'Data Visualization']),
            interview_tips='Practice coding problems, research company culture, prepare STAR stories',
            reviewed_by=None,
            reviewed_at=datetime.now() - timedelta(days=random.randint(1, 30)) if random.random() > 0.3 else None,
            created_at=datetime.now() - timedelta(days=random.randint(30, 90))
        )
        db.session.add(review)
        reviews.append(review)
    
    db.session.commit()
    print(f"  Created {len(reviews)} CV reviews")
    return reviews

def seed_risk_scores(students, courses):
    """Create risk scores from real attendance, quiz, and mark data."""
    print("Seeding Risk Scores...")
    from app.services.risk_service import recalculate_all_risk_scores

    count = recalculate_all_risk_scores()
    print(f"  Calculated {count} risk scores from live academic data")
    return RiskScore.query.all()

def main():
    """Main function to seed all data."""
    print("=" * 50)
    print("Starting database seeding...")
    print("=" * 50)
    
    # Create app context
    app = create_app('development')
    
    with app.app_context():
        # Use existing database - don't drop tables
        print("\nUsing existing database structure...")
        db.create_all()
        print("Database tables verified.")
        
        # Clear existing data first
        clear_all_data()
        
        # Seed all tables
        users = seed_users()
        students = seed_students(users)
        lecturers = seed_lecturers(users)
        courses = seed_courses(lecturers)
        modules = seed_modules(courses)
        lecturer_modules = seed_lecturer_modules(lecturers, modules)
        enrollments = seed_enrollments(students, courses)
        materials = seed_materials(courses, modules, users)
        quizzes = seed_quizzes(courses, modules, users)
        assignments = seed_assignments(courses, modules, users)
        assignment_submissions = seed_assignment_submissions(assignments, students)
        module_progress = seed_student_module_progress(enrollments, modules)
        quiz_questions = seed_quiz_questions(quizzes)
        quiz_results = seed_quiz_results(quizzes, students)  # Disabled
        attendance_records = seed_attendance(courses, modules, students, users)  # Disabled
        marks = seed_marks(courses, modules, students, users)  # Disabled
        study_plans = seed_study_plans(students, courses)
        study_plan_items = seed_study_plan_items(study_plans)
        chat_sessions = seed_chat_sessions(students, courses)
        chat_messages = seed_chat_messages(chat_sessions)
        cv_reviews = seed_cv_reviews(students)
        risk_scores = seed_risk_scores(students, courses)
        notifications, interventions = seed_interventions_and_notifications(
            users=users,
            students=students,
            lecturers=lecturers,
            courses=courses,
            materials=materials,
            quizzes=quizzes,
            assignments=assignments,
            cv_reviews=cv_reviews,
        )
        
        print("\n" + "=" * 50)
        print("Database seeding completed successfully!")
        print("=" * 50)
        
        print("\nSummary:")
        print(f"  Users: {len(users)}")
        print(f"  Students: {len(students)}")
        print(f"  Lecturers: {len(lecturers)}")
        print(f"  Courses: {len(courses)}")
        print(f"  Modules: {len(modules)}")
        print(f"  Lecturer-Module Assignments: {len(lecturer_modules)}")
        print(f"  Enrollments: {len(enrollments)}")
        print(f"  Course Materials: {len(materials)}")
        print(f"  Quizzes: {len(quizzes)}")
        print(f"  Assignments: {len(assignments)}")
        print(f"  Assignment Submissions: {len(assignment_submissions)}")
        print(f"  Student Module Progress: {len(module_progress)}")
        print(f"  Quiz Questions: {len(quiz_questions)}")
        print(f"  Quiz Results: {len(quiz_results)} (disabled - requires enrollments)")
        print(f"  Attendance Records: {len(attendance_records)} (disabled - requires enrollments)")
        print(f"  Marks: {len(marks)} (disabled - requires enrollments)")
        print(f"  Study Plans: {len(study_plans)}")
        print(f"  Study Plan Items: {len(study_plan_items)}")
        print(f"  Chat Sessions: {len(chat_sessions)}")
        print(f"  Chat Messages: {len(chat_messages)}")
        print(f"  CV Reviews: {len(cv_reviews)}")
        print(f"  Risk Scores: {len(risk_scores)}")
        print(f"  Notifications: {len(notifications)}")
        print(f"  Intervention Messages: {len(interventions)}")

if __name__ == '__main__':
    main()
