import os
import mimetypes
from typing import List, Optional, Set, Union
from werkzeug.utils import secure_filename
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    send_from_directory,
    send_file,
    current_app,
    abort,
)
from flask_login import login_required, current_user
from datetime import datetime
from http import HTTPStatus

from app import db
from app.utils.app_time import app_timestamp
from app.models import CourseMaterial, Course, Student, Module, Enrollment, Lecturer
from app.models.lecturer import LecturerModule
from app.utils.access_control import (
    require_module_access, 
    require_lecturer_assigned_to_module,
    can_edit_module_content,
    is_admin
)
from app.services.notification_service import NotificationService
from app.services import storage_supabase

materials_bp = Blueprint('materials', __name__, url_prefix='/materials')


# Configuration
ALLOWED_EXTENSIONS: Set[str] = {
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 
    'jpg', 'jpeg', 'png', 'gif', 'mp4', 'zip'
}

MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB

# Must match Postgres CHECK constraint in `database_schema_postgres.sql`
MATERIAL_CATEGORIES: Set[str] = {"lecture", "assignment", "reading", "notes", "other"}


class MaterialError(Exception):
    """Custom exception for material operations."""
    pass


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    return (
        '.' in filename and 
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def get_file_type(filename: str) -> str:
    """Determine file type category from extension."""
    ext: str = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    type_map: dict = {
        'pdf': 'pdf',
        'doc': 'document', 'docx': 'document',
        'ppt': 'presentation', 'pptx': 'presentation',
        'txt': 'text',
        'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'gif': 'image',
        'mp4': 'video',
        'zip': 'archive'
    }
    
    return type_map.get(ext, 'other')


def get_file_icon(file_type: str) -> str:
    """Get appropriate icon for file type."""
    icon_map: dict = {
        'pdf': 'file-text',
        'document': 'file-type',
        'presentation': 'presentation',
        'text': 'file-text',
        'image': 'image',
        'video': 'video',
        'archive': 'folder-archive',
        'other': 'file'
    }
    return icon_map.get(file_type, 'file')


def _candidate_upload_roots() -> List[str]:
    """
    Return upload roots to try for reading existing files.
    
    This repo historically used both `app/static/uploads` and `app/app/static/uploads`.
    Downloads should work regardless of which path the file ended up on disk.
    """
    roots: List[str] = []

    cfg_root = current_app.config.get("UPLOAD_FOLDER")
    if cfg_root:
        roots.append(cfg_root)

    app_dir = os.path.dirname(os.path.abspath(__file__))  # .../app/routes
    app_pkg_dir = os.path.dirname(app_dir)  # .../app
    roots.append(os.path.join(app_pkg_dir, "static", "uploads"))
    roots.append(os.path.join(app_pkg_dir, "app", "static", "uploads"))

    # de-dupe while preserving order
    seen = set()
    uniq: List[str] = []
    for r in roots:
        if r and r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def check_material_access(module_id: int, require_edit: bool = False) -> tuple:
    """
    Verify user access to module materials.
    Returns (module, course, student, has_edit_permission).
    """
    ctx = require_module_access(module_id)
    module = ctx.module
    course = ctx.course
    
    can_edit = False
    
    if current_user.role == 'admin':
        can_edit = True
        
    elif current_user.role == 'lecturer':
        # Must be assigned to this module
        can_edit = can_edit_module_content(module_id)
        
    elif current_user.role == 'student':
        if require_edit:
            abort(HTTPStatus.FORBIDDEN)
        if not ctx.has_access:
            abort(HTTPStatus.FORBIDDEN, 'Access to this module is not permitted')
    
    return module, course, ctx.student, can_edit


def get_upload_path(module_id: int, filename: str) -> str:
    """Generate secure upload path based on module."""
    upload_folder: str = current_app.config.get('UPLOAD_FOLDER')
    module_folder: str = os.path.join(upload_folder, 'materials', str(module_id))
    
    # Ensure directory exists
    os.makedirs(module_folder, exist_ok=True)
    
    return os.path.join(module_folder, secure_filename(filename))


@materials_bp.route('/')
@login_required
def index():
    """List all materials for enrolled courses - student view."""
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

    materials = []
    for module in modules:
        for material in module.materials:
            if material.is_published:
                materials.append({
                    'material': material,
                    'module': module,
                    'course': module.course
                })

    return render_template('materials_all.html', materials=materials)


@materials_bp.route('/course/<int:course_id>')
@login_required
def list_materials_by_course(course_id: int):
    """Redirect to first module's materials or show appropriate message."""
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
    
    return redirect(url_for('materials.list_materials', module_id=first_module.id))


@materials_bp.route('/module/<int:module_id>')
@login_required
def list_materials(module_id: int) -> str:
    """List materials for a module."""
    module, course, student, can_edit = check_material_access(module_id)
    
    # Base query - published materials for students, all for staff
    query = CourseMaterial.query.filter_by(module_id=module_id)
    
    if not can_edit:
        query = query.filter_by(is_published=True)
    
    materials: List[CourseMaterial] = query.order_by(
        CourseMaterial.category,
        CourseMaterial.created_at.desc()
    ).all()
    
    # Group by category
    categories: dict = {}
    for material in materials:
        cat: str = (material.category or 'other').strip().lower()
        if cat == 'general':
            cat = 'other'
        if cat not in MATERIAL_CATEGORIES:
            cat = 'other'
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(material)
    
    return render_template(
        'materials.html',
        course=course,
        module=module,
        materials=materials,
        categories=categories,
        can_edit=can_edit,
        allowed_extensions=list(ALLOWED_EXTENSIONS)
    )


@materials_bp.route('/module/<int:module_id>/upload', methods=['GET', 'POST'])
@login_required
def upload_material(module_id: int) -> Union[str, redirect]:
    """Upload material to module."""
    module, course, _, can_edit = check_material_access(module_id, require_edit=True)
    
    if not can_edit:
        abort(HTTPStatus.FORBIDDEN)
    
    if request.method == 'POST':
        # Debug: Log what's received
        current_app.logger.info(f"POST request.files keys: {list(request.files.keys())}")
        current_app.logger.info(f"POST request.form keys: {list(request.form.keys())}")
        
        # Validate file presence
        if 'file' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(request.url)
        
        if not allowed_file(file.filename):
            flash(
                f'Invalid file type. Allowed: {", ".join(sorted(ALLOWED_EXTENSIONS))}', 
                'danger'
            )
            return redirect(request.url)
        
        try:
            # Secure filename and save
            filename: str = secure_filename(file.filename)
            file_path: str = get_upload_path(module_id, filename)
            
            # Check for duplicate in same module
            existing: Optional[CourseMaterial] = CourseMaterial.query.filter_by(
                module_id=module_id,
                file_name=filename
            ).first()
            
            if existing:
                # Append timestamp to make unique
                name, ext = os.path.splitext(filename)
                filename = f"{name}_{int(app_timestamp())}{ext}"
                file_path = get_upload_path(module_id, filename)

            # Persist to storage:
            # - Prefer Supabase Storage in production (Render free tier disk is ephemeral)
            # - Fallback to local disk when Supabase not configured
            file_bytes: Optional[bytes] = None
            file_size: int = 0
            stored_ref: Optional[str] = None
            if storage_supabase.enabled():
                file_bytes = file.read()
                file_size = len(file_bytes)
                key = f"materials/{module_id}/{filename}"
                storage_supabase.put_bytes(key=key, data=file_bytes)
                stored_ref = storage_supabase.make_ref(key)
            else:
                file.save(file_path)
                file_size = os.path.getsize(file_path)
            
            if file_size > MAX_FILE_SIZE:
                if stored_ref:
                    try:
                        storage_supabase.delete(stored_ref)
                    except Exception:
                        pass
                elif os.path.exists(file_path):
                    os.remove(file_path)
                flash(f'File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB', 'danger')
                return redirect(request.url)
            
            # Determine publish status from checkbox.
            # UI checks this by default; if the field is missing, default to published.
            is_published = (request.form.get('is_published', 'on') == 'on')
            
            # Create database record
            material = CourseMaterial(
                module_id=module_id,
                title=request.form.get('title', '').strip() or filename,
                description=request.form.get('description', '').strip() or None,
                # Store a stable reference. If Supabase is enabled, store supabase://bucket/key
                # otherwise keep the legacy local/static path.
                file_path=(stored_ref or f'/static/uploads/materials/{module_id}/{filename}'),
                file_name=filename,
                file_type=get_file_type(filename),
                file_size=file_size,
                category=(request.form.get('category') or 'other').strip().lower(),
                is_published=is_published,
                uploaded_by=current_user.id
            )

            # Normalize category to match DB constraint (Render uses Postgres CHECK constraint).
            if (not material.category) or material.category == 'general' or material.category not in MATERIAL_CATEGORIES:
                material.category = 'other'
            
            db.session.add(material)
            db.session.commit()

            # If published, notify enrolled students
            try:
                if material.is_published:
                    if current_user.role == 'lecturer':
                        lecturer = Lecturer.query.filter_by(user_id=current_user.id).first()
                    else:
                        lecturer = None
                    enrollments = Enrollment.query.filter_by(course_id=course.id, status='active').all()
                    students = [e.student for e in enrollments if e.student and e.student.user]
                    if students:
                        NotificationService.notify_material_published(
                            lecturer=lecturer,
                            course=course,
                            module=module,
                            material=material,
                            students=students
                        )
            except Exception:
                db.session.rollback()
            
            flash(f'Material "{material.title}" uploaded successfully!', 'success')
            return redirect(url_for('materials.list_materials', module_id=module_id))
            
        except Exception as e:
            db.session.rollback()
            # Cleanup file if saved
            try:
                if 'stored_ref' in locals() and stored_ref:
                    storage_supabase.delete(stored_ref)
                elif 'file_path' in locals() and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            
            current_app.logger.error(f'Material upload error: {str(e)}')
            flash('Error uploading material. Please try again.', 'danger')
            return redirect(request.url)
    
    # GET request
    # Get existing categories from this module
    categories: List[str] = db.session.query(
        CourseMaterial.category
    ).filter_by(module_id=module_id).distinct().all()
    
    # Use lecturer-specific template (legacy root template was removed)
    return render_template(
        'lecturer/material_upload.html',
        course=course,
        module=module,
        existing_categories=[c[0] for c in categories if c[0]]
    )


@materials_bp.route('/download/<int:material_id>')
@login_required
def download_material(material_id: int):
    """Download material file."""
    material: CourseMaterial = CourseMaterial.query.get_or_404(material_id)
    
    # Access check for students
    if current_user.role == 'student':
        ctx = require_module_access(material.module_id)
        if not ctx.has_access:
            abort(HTTPStatus.FORBIDDEN)
        if not material.is_published:
            abort(HTTPStatus.FORBIDDEN)
    
    # Supabase storage ref support (recommended for Render free tier persistence)
    parsed = storage_supabase.parse_ref(material.file_path or "")
    if parsed and storage_supabase.enabled():
        bucket, key = parsed
        try:
            data = storage_supabase.get_bytes(material.file_path)
        except FileNotFoundError:
            flash("This file is missing in storage (it may have been deleted).", "warning")
            return redirect(url_for("materials.list_materials", module_id=material.module_id))
        except Exception:
            current_app.logger.exception("Supabase download_material failed")
            flash("Could not download this file right now. Please try again.", "danger")
            return redirect(url_for("materials.list_materials", module_id=material.module_id))

        from flask import Response
        download_name = (material.title or material.file_name or "material").strip() or "material"
        resp = Response(data)
        resp.headers["Content-Type"] = mimetypes.guess_type(material.file_name or "")[0] or "application/octet-stream"
        resp.headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
        return resp

    # Try multiple ways to locate the local file:
    # 1) Current canonical location: <UPLOAD_ROOT>/materials/<module_id>/<file_name>
    # 2) Legacy stored material.file_path (may contain a different module folder)
    abs_path = None

    # 1) Canonical location
    for root in _candidate_upload_roots():
        candidate = os.path.join(root, "materials", str(material.module_id), material.file_name)
        if os.path.exists(candidate):
            abs_path = candidate
            break

    # 2) Stored DB path fallback (supports /static/uploads/... and other historic shapes)
    if abs_path is None and material.file_path:
        rel = material.file_path.strip().lstrip("/").replace("\\", "/")
        # Normalize common prefixes so we can join against UPLOAD_ROOT
        # - static/uploads/<...>  -> <...>
        # - app/static/uploads/<...> -> <...>
        for prefix in ("static/uploads/", "app/static/uploads/"):
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
                break

        # If rel still contains "uploads/", strip it too.
        if rel.startswith("uploads/"):
            rel = rel[len("uploads/"):]

        for root in _candidate_upload_roots():
            candidate = os.path.join(root, *rel.split("/"))
            if os.path.exists(candidate):
                abs_path = candidate
                break

    if abs_path is None:
        flash("This file is missing on the server (it may have been moved or deleted).", "warning")
        return redirect(url_for("materials.list_materials", module_id=material.module_id))
    
    # Track download (optional analytics)
    try:
        material.download_count = (material.download_count or 0) + 1
        db.session.commit()
    except:
        db.session.rollback()
    
    return send_file(
        abs_path,
        as_attachment=True,
        download_name=material.title or material.file_name,
    )


@materials_bp.route('/delete/<int:material_id>', methods=['POST'])
@login_required
def delete_material(material_id: int) -> redirect:
    """Delete material."""
    material: CourseMaterial = CourseMaterial.query.get_or_404(material_id)
    module_id: int = material.module_id
    
    # Permission check
    can_delete: bool = False
    
    if current_user.role == 'admin':
        can_delete = True
    elif current_user.role == 'lecturer':
        can_delete = can_edit_module_content(module_id)
    
    if not can_delete:
        abort(HTTPStatus.FORBIDDEN)
    
    try:
        # Delete physical file
        upload_folder: str = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        file_path: str = os.path.join(
            upload_folder, 'materials', str(module_id), material.file_name
        )
        
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Delete database record
        db.session.delete(material)
        db.session.commit()
        
        flash('Material deleted successfully.', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Material deletion error: {str(e)}')
        flash('Error deleting material.', 'danger')
    
    return redirect(url_for('materials.list_materials', module_id=module_id))


@materials_bp.route('/<int:material_id>/toggle-publish', methods=['POST'])
@login_required
def toggle_publish(material_id: int) -> redirect:
    """Toggle material published status."""
    material: CourseMaterial = CourseMaterial.query.get_or_404(material_id)
    
    # Permission check
    can_edit: bool = False
    
    if current_user.role == 'admin':
        can_edit = True
    elif current_user.role == 'lecturer':
        can_edit = can_edit_module_content(material.module_id)
    
    if not can_edit:
        abort(HTTPStatus.FORBIDDEN)
    
    try:
        was_published = bool(material.is_published)
        material.is_published = not material.is_published
        db.session.commit()

        # If just published, notify enrolled students
        if (not was_published) and material.is_published:
            try:
                module = Module.query.get_or_404(material.module_id)
                course = Course.query.get_or_404(module.course_id)
                lecturer = Lecturer.query.filter_by(user_id=current_user.id).first() if current_user.role == 'lecturer' else None
                enrollments = Enrollment.query.filter_by(course_id=course.id, status='active').all()
                students = [e.student for e in enrollments if e.student and e.student.user]
                if students:
                    NotificationService.notify_material_published(
                        lecturer=lecturer,
                        course=course,
                        module=module,
                        material=material,
                        students=students
                    )
            except Exception:
                db.session.rollback()
        
        status: str = 'published' if material.is_published else 'unpublished'
        flash(f'Material {status}.', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Publish toggle error: {str(e)}')
        flash('Error updating material.', 'danger')
    
    return redirect(url_for('materials.list_materials', module_id=material.module_id))


@materials_bp.route('/course/<int:course_id>/upload')
@login_required
def upload_material_course_legacy(course_id: int) -> redirect:
    """Redirect old course-based upload URLs to first module's upload page."""
    # Prefer a module assigned to the current lecturer (avoids 403 on upload)
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
        return redirect(url_for('materials.upload_material', module_id=module.id))
    
    flash('No modules found in this course. Create a module first.', 'warning')
    return redirect(url_for('courses.detail', course_id=course_id))
