import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

    # Sessions: SQLAlchemy-backed so sessions survive restarts and work across
    # multiple instances (consistent with the MySQL database already in use).
    # SESSION_SQLALCHEMY is set programmatically in create_app() after the db
    # object is initialised, since it must be an object reference, not a string.
    SESSION_TYPE = 'sqlalchemy'
    SESSION_SQLALCHEMY_TABLE = 'flask_sessions'
    SESSION_PERMANENT = False
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour

    # Database
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
    DB_NAME = os.environ.get('DB_NAME', 'vaccination_db')
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
        "?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Connection resilience for Azure MySQL, which drops idle connections and
    # enforces SSL. pool_recycle evicts connections before Azure's idle timeout
    # (typically ~300 s). pool_pre_ping tests a connection before handing it out,
    # replacing it silently if the server closed it.
    # Set DB_SSL_REQUIRED=true in Azure App Service → Configuration to enable SSL.
    _ssl_required = os.environ.get('DB_SSL_REQUIRED', '').lower() in ('1', 'true')
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
        **({'connect_args': {'ssl': {'ssl_verify_cert': False}}} if _ssl_required else {}),
    }

    # eBulkSMS
    EBULKSMS_USERNAME = os.environ.get('EBULKSMS_USERNAME', '')  # account email used to log in to eBulkSMS
    EBULKSMS_API_KEY = os.environ.get('EBULKSMS_API_KEY', '')
    EBULKSMS_SENDER = os.environ.get('EBULKSMS_SENDER', 'VAXTRACK')  # 11-char max, no approval needed per eBulkSMS's FAQ
    # "true" routes DND-registered numbers through eBulkSMS's fixed DND
    # sender/number instead of dropping them, trading branding consistency
    # for actual delivery on those numbers. Kept as a one-line config flip
    # in case that trade-off is ever reconsidered.
    EBULKSMS_DND_SENDER = os.environ.get('EBULKSMS_DND_SENDER', 'true')

    # Azure Communication Services (Email via REST)
    ACS_CONNECTION_STRING = os.environ.get('ACS_CONNECTION_STRING', '')
    MAIL_SENDER = os.environ.get('MAIL_SENDER', '')

    # Base URL of this app's own deployment, used to build absolute asset URLs
    # (e.g. the logo embedded in HTML emails) from notifications.py, which runs
    # from a background APScheduler thread with no Flask request context.
    APP_BASE_URL = os.environ.get('APP_BASE_URL', '')

    # ESP32 Hardware Token
    ESP32_AUTH_TOKEN = os.environ.get('ESP32_AUTH_TOKEN', '')
