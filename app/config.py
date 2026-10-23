import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the repository
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present
env_path = BASE_DIR / '.env'
if env_path.exists():
    load_dotenv(env_path)


class Config:
    """Base configuration shared across environments."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'insecure-default-change-in-production')
    
    # Database resolution
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if DATABASE_URL:
        # Normalize legacy postgres:// to postgresql:// for SQLAlchemy
        if DATABASE_URL.startswith('postgres://'):
            DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        # Normalize sqlite relative paths to absolute paths
        if DATABASE_URL.startswith('sqlite:///') and not DATABASE_URL.startswith('sqlite:////'):
            rel_path = DATABASE_URL.replace('sqlite:///', '')
            # If not an absolute Windows path
            if not (len(rel_path) > 1 and rel_path[1] == ':'):
                SQLALCHEMY_DATABASE_URI = f"sqlite:///{BASE_DIR / rel_path}"
            else:
                SQLALCHEMY_DATABASE_URI = DATABASE_URL
        else:
            SQLALCHEMY_DATABASE_URI = DATABASE_URL
    elif os.environ.get('VERCEL'):
        # On Vercel serverless without external database, fall back to writable /tmp
        SQLALCHEMY_DATABASE_URI = "sqlite:////tmp/visitor_management.db"
    else:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{BASE_DIR / 'visitor_management.db'}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Security settings for cookies & sessions
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() in ('true', '1')
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Timezone & Regional Settings
    APP_TIMEZONE = os.environ.get('APP_TIMEZONE', 'Asia/Kolkata')

    # QR Credential Settings
    QR_VALIDITY_MINUTES = int(os.environ.get('QR_VALIDITY_MINUTES', 120))
    QR_ALLOW_REISSUE = os.environ.get('QR_ALLOW_REISSUE', 'true').lower() in ('true', '1')

    # Rate Limiting Settings
    RATE_LIMIT_ENABLED = os.environ.get('RATE_LIMIT_ENABLED', 'true').lower() in ('true', '1')
    RATE_LIMIT_LOGIN = os.environ.get('RATE_LIMIT_LOGIN', '10/minute')
    RATE_LIMIT_REGISTER = os.environ.get('RATE_LIMIT_REGISTER', '5/minute')
    RATE_LIMIT_APPROVAL = os.environ.get('RATE_LIMIT_APPROVAL', '30/minute')
    RATE_LIMIT_GATE = os.environ.get('RATE_LIMIT_GATE', '60/minute')

    # Public Base URL for generated external links (e.g. https://your-project.vercel.app)
    _raw_base = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    if 'smart_qr_tracking' in _raw_base.lower() or '_' in _raw_base.split('://')[-1].split('/')[0]:
        _raw_base = ''
    if not _raw_base and os.environ.get('VERCEL'):
        _raw_base = 'https://smart-qr-visitor-system.vercel.app'
    PUBLIC_BASE_URL = _raw_base

    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration with in-memory SQLite and disabled CSRF for simple test runner."""
    DEBUG = False
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key-do-not-use-in-production'
    RATE_LIMIT_ENABLED = False


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
