import os
import logging
from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from flask_session import Session
from werkzeug.exceptions import HTTPException

from app.config import config
from app.utils.app_time import APP_TIMEZONE_LABEL, APP_TZ

# Initialize extensions
db = SQLAlchemy()
csrf = CSRFProtect()
bcrypt = Bcrypt()
migrate = Migrate()
session = Session()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app(config_name='default'):
    """Application factory for creating Flask app."""
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Production safety checks (only when production config is selected)
    if config_name == 'production':
        if not app.config.get('SECRET_KEY') or not app.config.get('SESSION_SECRET_KEY'):
            raise RuntimeError(
                "Missing production secrets. Set SECRET_KEY and SESSION_SECRET_KEY "
                "(environment variables) or run with FLASK_ENV=development."
            )
    
    # Disable Jinja2 template caching in development
    if app.config.get('DEBUG'):
        app.jinja_env.cache = {}
    
    # Add Python built-ins to Jinja2 globals
    app.jinja_env.globals.update(
        str=str,
        int=int,
        float=float,
        list=list,
        dict=dict,
        range=range,
        len=len,
        enumerate=enumerate,
        zip=zip,
        app_timezone_label=APP_TIMEZONE_LABEL,
    )
    
    # Register custom Jinja2 filters
    @app.template_filter('datetimeformat')
    def datetimeformat(value, format='%b %d, %Y'):
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime(format)

    @app.template_filter('as_app_naive')
    def as_app_naive(value):
        """Normalize aware timestamps (e.g. Postgres TIMESTAMPTZ) to app-local naive datetime."""
        if value is None:
            return None
        tz = getattr(value, "tzinfo", None)
        if tz is None:
            return value
        try:
            return value.astimezone(APP_TZ).replace(tzinfo=None)
        except Exception:
            return value
    
    @app.template_filter('markdown')
    def markdown_filter(text):
        """Simple markdown-like formatting."""
        if not text:
            return ''
        # Basic markdown-like formatting
        import re
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        text = re.sub(r'\n', '<br>', text)
        return text
    
    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)
    session.init_app(app)
    
    # ==================== CACHE CONTROL ====================
    @app.after_request
    def add_cache_headers(response):
        """Add cache control headers to prevent browser caching in development."""
        # In development, always get fresh content
        if app.config.get('DEBUG'):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    # Initialize login manager from user_loader module
    from app.utils.user_loader import login_manager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    
    # Create upload folder if not exists
    upload_folder = app.config.get('UPLOAD_FOLDER')
    if upload_folder and not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    
    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.courses import courses_bp
    from app.routes.materials import materials_bp
    from app.routes.quizzes import quizzes_bp
    from app.routes.attendance import attendance_bp
    from app.routes.marks import marks_bp
    from app.routes.ai import ai_bp
    from app.routes.career import career_bp
    from app.routes.analytics import analytics_bp
    from app.routes.admin import admin_bp
    from app.routes.assignments import assignments_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(materials_bp)
    app.register_blueprint(quizzes_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(marks_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(career_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(assignments_bp)
    from app.routes.notifications import notifications_bp
    app.register_blueprint(notifications_bp)
    
    # ==================== ERROR HANDLERS ====================
    @app.errorhandler(404)
    def not_found_error(error):
        """Handle 404 Not Found errors."""
        logger.warning(f"404 error: {request.path}")
        return render_template('error.html', error_code=404, 
                               error_message="Page Not Found",
                               error_description="The page you're looking for doesn't exist or has been moved."), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 Internal Server errors."""
        logger.error(f"500 error: {error}")
        # Rollback any failed database transactions
        db.session.rollback()
        return render_template('error.html', error_code=500, 
                               error_message="Internal Server Error",
                               error_description="Something went wrong on our end. Please try again later."), 500

    @app.errorhandler(403)
    def forbidden_error(error):
        """Handle 403 Forbidden errors."""
        try:
            user_id = getattr(current_user, "id", None)
            role = getattr(current_user, "role", None)
            is_auth = bool(getattr(current_user, "is_authenticated", False))
        except Exception:
            user_id = None
            role = None
            is_auth = False

        description = getattr(error, "description", None)
        logger.warning(
            f"403 error: {request.method} {request.path} "
            f"(auth={is_auth}, user_id={user_id}, role={role}) "
            f"description={description!r}"
        )
        return render_template('error.html', error_code=403, 
                               error_message="Access Forbidden",
                               error_description="You don't have permission to access this resource."), 403

    @app.errorhandler(400)
    def bad_request_error(error):
        """Handle 400 Bad Request errors."""
        logger.warning(f"400 error: {request.path} - {error}")
        return render_template('error.html', error_code=400, 
                               error_message="Bad Request",
                               error_description="The request couldn't be understood. Please check your input."), 400

    @app.errorhandler(405)
    def method_not_allowed_error(error):
        """Handle 405 Method Not Allowed errors."""
        logger.warning(f"405 error: {request.method} {request.path}")
        return render_template('error.html', error_code=405, 
                               error_message="Method Not Allowed",
                               error_description="The method you used is not allowed for this resource."), 405

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        """Handle all HTTP exceptions."""
        logger.warning(f"HTTP exception: {error.code} - {error.description}")
        return render_template('error.html', error_code=error.code, 
                               error_message=error.name,
                               error_description=error.description), error.code

    @app.errorhandler(Exception)
    def handle_exception(error):
        """Handle all unhandled exceptions."""
        logger.exception(f"Unhandled exception: {error}")
        # Rollback any failed database transactions
        db.session.rollback()
        return render_template('error.html', error_code=500, 
                               error_message="Internal Server Error",
                               error_description="An unexpected error occurred. Our team has been notified."), 500

    # Create database tables in development/testing only.
    # In production, schema should be managed via migrations.
    if app.config.get("DEBUG") or app.config.get("TESTING"):
        with app.app_context():
            db.create_all()

    # SQLite: add quiz timer column on existing DBs (no-op if already present)
    with app.app_context():
        try:
            from sqlalchemy import inspect, text
            insp = inspect(db.engine)
            if "quizzes" in insp.get_table_names():
                col_names = {c["name"] for c in insp.get_columns("quizzes")}
                if "time_limit_seconds" not in col_names:
                    with db.engine.begin() as conn:
                        conn.execute(
                            text("ALTER TABLE quizzes ADD COLUMN time_limit_seconds INTEGER")
                        )
                    logger.info("Added quizzes.time_limit_seconds column")
        except Exception:
            logger.exception("Could not apply quizzes.time_limit_seconds schema patch")

    return app
