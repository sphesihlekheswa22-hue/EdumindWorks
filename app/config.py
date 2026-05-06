import os
import tempfile
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env file.
# Do NOT override values already set in the environment (e.g. on Render, or when
# using `$env:DATABASE_URL=...` in PowerShell).
load_dotenv(override=False)


class Config:
    """Base configuration class."""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SESSION_SECRET_KEY = os.environ.get('SESSION_SECRET_KEY', os.environ.get('SECRET_KEY', 'dev-session-key-change-in-production'))
    
    # Database
    # - Default: SQLite file at app/edumind_ai.db
    # - 3-tier demo: set DATABASE_URL to a remote Postgres URL (e.g. Neon)
    #
    # Examples:
    #   DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require
    #   SQLITE_DB_PATH=C:\path\to\edumind_ai.db
    _database_url = os.environ.get('DATABASE_URL', '').strip()
    if _database_url:
        # Some providers still hand out `postgres://...` URLs; SQLAlchemy expects `postgresql://...`.
        if _database_url.startswith("postgres://"):
            _database_url = "postgresql://" + _database_url[len("postgres://") :]
        # Allow DATABASE_URL to be the single source of truth.
        SQLALCHEMY_DATABASE_URI = _database_url
    else:
        sqlite_db_path = os.environ.get(
            'SQLITE_DB_PATH',
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'edumind_ai.db')
        )
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + sqlite_db_path
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # On Render/managed Postgres, SSL connections can be dropped while pooled.
    # Pre-ping + recycle prevents "SSL connection has been closed unexpectedly" on first query.
    _is_postgres = SQLALCHEMY_DATABASE_URI.startswith("postgresql://")
    if _is_postgres:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE_SECONDS", "280")),
            "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT_SECONDS", "30")),
            "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "5")),
            "connect_args": {
                # TCP keepalives help long-lived SSL links in some networks.
                "keepalives": 1,
                "keepalives_idle": int(os.environ.get("DB_KEEPALIVES_IDLE", "30")),
                "keepalives_interval": int(os.environ.get("DB_KEEPALIVES_INTERVAL", "10")),
                "keepalives_count": int(os.environ.get("DB_KEEPALIVES_COUNT", "5")),
            },
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}
    
    # Session
    SESSION_TYPE = 'filesystem'
    # Ensure a writable session dir on Render/Linux (repo paths may be read-only or wiped).
    SESSION_FILE_DIR = (os.environ.get("SESSION_FILE_DIR") or os.path.join(tempfile.gettempdir(), "edumind_flask_session")).strip()
    # Flask-Session signer can return bytes in some versions, which breaks cookie setting on Werkzeug.
    # Keep it off to avoid `TypeError: cannot use a string pattern on a bytes-like object` in production.
    SESSION_USE_SIGNER = False
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # File uploads
    # Prefer whichever uploads folder exists (repo may contain either `app/static/uploads`
    # or `app/app/static/uploads` depending on previous refactors/migrations).
    _app_dir = os.path.dirname(os.path.abspath(__file__))
    _upload_primary = os.path.join(_app_dir, 'static', 'uploads')
    _upload_alt = os.path.join(_app_dir, 'app', 'static', 'uploads')
    UPLOAD_FOLDER = _upload_alt if os.path.isdir(_upload_alt) else _upload_primary
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'jpg', 'png', 'jpeg'}

    # Supabase Storage (optional, recommended for Render free tier persistence)
    SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip()
    # Use service role key on the server only (never expose to the browser).
    SUPABASE_SERVICE_ROLE_KEY = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    SUPABASE_STORAGE_BUCKET = (os.environ.get("SUPABASE_STORAGE_BUCKET") or "uploads").strip() or "uploads"
    
    # NVIDIA API (for AI features) - Using OpenRouter (optional if Ollama is used)
    # Support common Render/env typos (must be an OpenRouter key for https://openrouter.ai — not raw OpenAI)
    OPENROUTER_API_KEY = (
        os.environ.get('OPENROUTER_API_KEY')
        or os.environ.get('OPEN_ROUTER_API_KEY')
        or ''
    ).strip()
    # OpenRouter expects app attribution (public URL of your app). On Render, RENDER_EXTERNAL_URL is set for you.
    _or_ref = (os.environ.get('OPENROUTER_REFERER') or os.environ.get('RENDER_EXTERNAL_URL') or '').strip()
    OPENROUTER_REFERER = _or_ref or 'http://127.0.0.1:5000'
    OPENROUTER_APP_TITLE = (os.environ.get('OPENROUTER_APP_TITLE') or 'EduMind AI').strip() or 'EduMind AI'

    # Ollama: local / self-hosted LLM (see https://ollama.com). Used when OLLAMA_BASE_URL is non-empty.
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', '').strip()
    OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3.2').strip()
    
    # Email Configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@edumindai.com')

    # Transactional email (recommended for Render; avoids Gmail/Google app passwords)
    # If RESEND_API_KEY is set, app will send emails via Resend API instead of SMTP.
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
    RESEND_FROM = os.environ.get('RESEND_FROM', '')
    
    # Pagination
    ITEMS_PER_PAGE = 20

    # All app datetimes use this IANA timezone (see app.utils.app_time)
    APP_TIMEZONE = os.environ.get('APP_TIMEZONE', 'Africa/Johannesburg')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_ECHO = False
    WTF_CSRF_ENABLED = True  # Enable CSRF even in development for testing

    # Default to local Ollama for free AI. Install Ollama, then: ollama pull llama3.2
    # To turn off Ollama in dev (e.g. OpenRouter only), set OLLAMA_BASE_URL= in .env
    if 'OLLAMA_BASE_URL' not in os.environ:
        OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
    else:
        OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', '').strip()


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = True

    # In production, secrets must be set explicitly.
    # Validation is performed in the app factory when 'production' is selected.
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SESSION_SECRET_KEY = os.environ.get('SESSION_SECRET_KEY')


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    OLLAMA_BASE_URL = ''


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
