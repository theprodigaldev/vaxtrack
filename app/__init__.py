from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session

db = SQLAlchemy()
sess = Session()


def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    db.init_app(app)
    app.config['SESSION_SQLALCHEMY'] = db  # required by Flask-Session SQLAlchemy backend
    sess.init_app(app)

    from app.auth import auth_bp
    from app.rfid import rfid_bp
    from app.patients import patients_bp
    from app.vaccinations import vaccinations_bp
    from app.reports import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(rfid_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(vaccinations_bp)
    app.register_blueprint(reports_bp)

    from app.scheduler import init_scheduler
    init_scheduler(app)

    with app.app_context():
        from app import models  # noqa: F401
        db.create_all()

    return app
