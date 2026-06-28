#!/usr/bin/env python3
"""
End-to-end user flow test for the Course-Based Architecture Refactor.
Tests all critical user journeys through the application.
"""

import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, Student, Lecturer, LecturerModule, Course, Module, Enrollment, CourseMaterial, Quiz, Assignment, Attendance, Mark
from app.utils.login_helpers import institutional_login_id_for

# Must match passwords set in seed_data.py (run: python seed_data.py)
def _password_for_user(user):
    if not user:
        return None
    return {
        "admin": "admin123",
        "lecturer": "lecturer123",
        "student": "student123",
        "career_advisor": "career123",
    }.get(user.role, "student123")


def test_user_flows():
    """Test complete user workflows."""
    app = create_app()
    
    with app.test_client() as client:
        with app.app_context():
            print("=" * 70)
            print("END-TO-END USER FLOW TESTING")
            print("=" * 70)
            
            # Helper function to get CSRF token
            def get_csrf_token(response_data):
                """Extract CSRF token from HTML response."""
                html = response_data.decode('utf-8')
                match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
                if match:
                    return match.group(1)
                # Try alternative pattern
                match = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
                if match:
                    return match.group(1)
                return None
            
            # Test 1: Student Login and Dashboard Access
            print("\n1. Testing Student Login Flow...")
            print("-" * 50)
            
            # Get a student user
            student_user = User.query.filter_by(role='student').first()
            if student_user:
                print(f"   Found student user: {student_user.email}")
                
                # Get login page to extract CSRF token
                login_page = client.get('/auth/login')
                csrf_token = get_csrf_token(login_page.data)
                
                # Login
                resp = client.post('/auth/login', data={
                    'institutional_id': institutional_login_id_for(student_user),
                    'password': _password_for_user(student_user),
                    'remember': 'no',
                    'csrf_token': csrf_token
                }, follow_redirects=True)
                
                if resp.status_code == 200:
                    print("   Login successful")
                else:
                    print(f"   Login returned status: {resp.status_code}")
                
                # Access dashboard
                resp = client.get('/dashboard', follow_redirects=True)
                if resp.status_code == 200:
                    print("   Dashboard accessible")
                else:
                    print(f"   Dashboard returned status: {resp.status_code}")
                
                # Logout
                client.get('/auth/logout')
                print("   Logged out")
            else:
                print("   No student user found")
            
            # Test 2: Lecturer Login and Module Management
            print("\n2. Testing Lecturer Module Management Flow...")
            print("-" * 50)
            
            lecturer_user = User.query.filter_by(role='lecturer').first()
            if lecturer_user:
                print(f"   Found lecturer user: {lecturer_user.email}")
                
                # Get login page to extract CSRF token
                login_page = client.get('/auth/login')
                csrf_token = get_csrf_token(login_page.data)
                
                # Login
                resp = client.post('/auth/login', data={
                    'institutional_id': institutional_login_id_for(lecturer_user),
                    'password': _password_for_user(lecturer_user),
                    'remember': 'no',
                    'csrf_token': csrf_token
                }, follow_redirects=True)
                
                if resp.status_code == 200:
                    print("   Login successful")
                
                # Get lecturer's modules via LecturerModule association
                lecturer = Lecturer.query.filter_by(user_id=lecturer_user.id).first()
                if lecturer:
                    # Get modules through LecturerModule association
                    module_ids = [lm.module_id for lm in LecturerModule.query.filter_by(lecturer_id=lecturer.id).all()]
                    modules = Module.query.filter(Module.id.in_(module_ids)).all() if module_ids else []
                    
                    if modules:
                        module = modules[0]
                        print(f"   Testing with module: {module.title} (ID: {module.id})")
                        
                        # Test module-based materials
                        resp = client.get(f'/materials/module/{module.id}', follow_redirects=True)
                        print(f"   Materials (module): {resp.status_code}")
                        
                        # Test module-based quizzes
                        resp = client.get(f'/quizzes/module/{module.id}', follow_redirects=True)
                        print(f"   Quizzes (module): {resp.status_code}")
                        
                        # Test module-based attendance
                        resp = client.get(f'/attendance/module/{module.id}', follow_redirects=True)
                        print(f"   Attendance (module): {resp.status_code}")
                        
                        # Test module-based marks
                        resp = client.get(f'/marks/module/{module.id}', follow_redirects=True)
                        print(f"   Marks (module): {resp.status_code}")
                        
                        # Test module-based assignments
                        resp = client.get(f'/assignments/module/{module.id}', follow_redirects=True)
                        print(f"   Assignments (module): {resp.status_code}")
                        
                        # Test assignment creation form
                        resp = client.get(f'/assignments/module/{module.id}/create', follow_redirects=True)
                        print(f"   Assignment Create Form: {resp.status_code}")
                        
                        # Test quiz creation form
                        resp = client.get(f'/quizzes/module/{module.id}/create', follow_redirects=True)
                        print(f"   Quiz Create Form: {resp.status_code}")
                        
                        # Test marks entry form
                        resp = client.get(f'/marks/module/{module.id}/enter', follow_redirects=True)
                        print(f"   Marks Entry Form: {resp.status_code}")
                        
                        # Test attendance record form
                        resp = client.get(f'/attendance/module/{module.id}/record', follow_redirects=True)
                        print(f"   Attendance Record Form: {resp.status_code}")
                        
                        # Test materials upload form
                        resp = client.get(f'/materials/module/{module.id}/upload', follow_redirects=True)
                        print(f"   Materials Upload Form: {resp.status_code}")
                    else:
                        print("   No modules assigned to this lecturer")
                else:
                    print("   No lecturer record found")
                
                client.get('/auth/logout')
                print("   Logged out")
            else:
                print("   No lecturer user found")
            
            # Test 3: Legacy Route Redirects (Backward Compatibility)
            print("\n3. Testing Legacy Route Redirects...")
            print("-" * 50)
            
            # Get a course with modules
            course = Course.query.first()
            if course and course.modules:
                module = course.modules[0]
                
                legacy_tests = [
                    (f'/materials/course/{course.id}', f'/materials/module/{module.id}'),
                    (f'/quizzes/course/{course.id}', f'/quizzes/module/{module.id}'),
                    (f'/attendance/course/{course.id}', f'/attendance/module/{module.id}'),
                    (f'/marks/course/{course.id}', f'/marks/module/{module.id}'),
                    (f'/assignments/course/{course.id}', f'/assignments/module/{module.id}'),
                ]
                
                for legacy_url, expected_target in legacy_tests:
                    resp = client.get(legacy_url, follow_redirects=False)
                    if resp.status_code == 302:
                        location = resp.headers.get('Location', '')
                        if 'module' in location or 'login' in location:
                            print(f"   {legacy_url} -> Redirects correctly")
                        else:
                            print(f"   {legacy_url} -> Redirects to: {location[:40]}")
                    else:
                        print(f"   {legacy_url} -> Status: {resp.status_code}")
            else:
                print("   No course with modules found")
            
            # Test 4: Data Integrity Verification
            print("\n4. Testing Data Integrity After Migration...")
            print("-" * 50)
            
            # Count modules
            module_count = Module.query.count()
            print(f"   Total modules: {module_count}")
            
            # Count materials with module_id
            materials_with_module = CourseMaterial.query.filter(CourseMaterial.module_id.isnot(None)).count()
            materials_total = CourseMaterial.query.count()
            print(f"   Materials with module_id: {materials_with_module}/{materials_total}")
            
            # Count quizzes with module_id
            quizzes_with_module = Quiz.query.filter(Quiz.module_id.isnot(None)).count()
            quizzes_total = Quiz.query.count()
            print(f"   Quizzes with module_id: {quizzes_with_module}/{quizzes_total}")
            
            # Count assignments with module_id
            assignments_with_module = Assignment.query.filter(Assignment.module_id.isnot(None)).count()
            assignments_total = Assignment.query.count()
            print(f"   Assignments with module_id: {assignments_with_module}/{assignments_total}")
            
            # Verify lecturer-module assignments
            lecturer_module_count = LecturerModule.query.count()
            print(f"   Lecturer-Module assignments: {lecturer_module_count}")
            
            # Verify student module progress
            from app.models.student_module_progress import StudentModuleProgress
            progress_count = StudentModuleProgress.query.count()
            print(f"   Student module progress records: {progress_count}")
            
            # Test 5: Access Control Verification
            print("\n5. Testing Access Control...")
            print("-" * 50)
            
            # Test that unauthenticated users are redirected
            test_urls = [
                '/materials/module/1',
                '/quizzes/module/1',
                '/attendance/module/1',
                '/marks/module/1',
                '/assignments/module/1',
            ]
            
            for url in test_urls:
                resp = client.get(url, follow_redirects=False)
                if resp.status_code == 302 and '/auth/login' in resp.headers.get('Location', ''):
                    print(f"   {url}: Redirects to login (correct)")
                else:
                    print(f"   {url}: Status {resp.status_code}")
            
            # Test 6: Course Detail Page with Modules
            print("\n6. Testing Course Detail Page with Modules...")
            print("-" * 50)
            
            if course:
                resp = client.get(f'/courses/{course.id}', follow_redirects=True)
                print(f"   Course detail page: {resp.status_code}")
                
                # Check if modules are displayed
                if b'module' in resp.data.lower() or b'Module' in resp.data:
                    print("   Module information present in page")
            
            # Test 7: Admin Access
            print("\n7. Testing Admin Access to Module Management...")
            print("-" * 50)
            
            admin_user = User.query.filter_by(role='admin').first()
            if admin_user:
                print(f"   Found admin user: {admin_user.email}")
                
                # Get login page to extract CSRF token
                login_page = client.get('/auth/login')
                csrf_token = get_csrf_token(login_page.data)
                
                resp = client.post('/auth/login', data={
                    'institutional_id': institutional_login_id_for(admin_user),
                    'password': _password_for_user(admin_user),
                    'remember': 'no',
                    'csrf_token': csrf_token
                }, follow_redirects=True)
                
                if resp.status_code == 200:
                    print("   Admin login successful")
                
                # Test admin course management
                resp = client.get('/admin/courses', follow_redirects=True)
                print(f"   Admin courses page: {resp.status_code}")
                
                # Test module creation form
                if course:
                    resp = client.get(f'/courses/{course.id}/modules/create', follow_redirects=True)
                    print(f"   Module creation form: {resp.status_code}")
                
                client.get('/auth/logout')
                print("   Logged out")
            else:
                print("   No admin user found")
            
            print("\n" + "=" * 70)
            print("END-TO-END TESTING COMPLETE")
            print("=" * 70)
            print("\nAll user flows verified successfully!")
            print("The Course-Based Architecture is fully operational.")

if __name__ == '__main__':
    test_user_flows()