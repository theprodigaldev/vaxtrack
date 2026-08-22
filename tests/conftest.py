import os
from datetime import date

import pytest
from flask import Flask

from app import db as _db
from app.auth import auth_bp
from app.patients import patients_bp
from app.rfid import rfid_bp
from app.vaccinations import vaccinations_bp
from app.reports import reports_bp
from app.models import Facility, Child, RFIDTag, Vaccine, Appointment

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')
_STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'static')
TEST_ESP32_TOKEN = 'test-esp32-token'


@pytest.fixture
def app():
    """Minimal Flask app wired with just the blueprints under test (auth +
    patients + rfid), backed by an in-memory SQLite DB.

    Deliberately does NOT go through app.create_app(): that factory also
    boots a real APScheduler background thread and hardcodes a MySQL DSN,
    neither of which these route tests need or should depend on.
    """
    flask_app = Flask('vaxtrack_test', template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    flask_app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        ESP32_AUTH_TOKEN=TEST_ESP32_TOKEN,
        # Blank so send_email()/send_sms() short-circuit to 'skipped' rather
        # than KeyError'ing on a missing config key or making a real request.
        ACS_CONNECTION_STRING='',
        MAIL_SENDER='',
        APP_BASE_URL='',
        EBULKSMS_USERNAME='',
        EBULKSMS_API_KEY='',
        EBULKSMS_SENDER='VAXTRACK',
        EBULKSMS_DND_SENDER='true',
    )
    _db.init_app(flask_app)
    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(patients_bp)
    flask_app.register_blueprint(rfid_bp)
    # Registered only because base.html's sidebar builds url_for() links to
    # these blueprints for some roles; none of their routes are exercised.
    flask_app.register_blueprint(vaccinations_bp)
    flask_app.register_blueprint(reports_bp)

    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def facility_id(app):
    with app.app_context():
        fac = Facility(facility_name='Surulere Clinic', lga='Surulere', state='Lagos')
        _db.session.add(fac)
        _db.session.commit()
        return fac.facility_id


@pytest.fixture
def facility_id_2(app):
    """A second, distinct facility - for tests proving a reader's declared
    facility_id routes scans there even when it differs from the child's
    home facility (facility_id fixture)."""
    with app.app_context():
        fac = Facility(facility_name='Ikeja Clinic', lga='Ikeja', state='Lagos')
        _db.session.add(fac)
        _db.session.commit()
        return fac.facility_id


@pytest.fixture
def rfid_tag(app, facility_id):
    """An active RFID tag on a real child, for the data_entry_clerk
    regression-check tests that need a genuine row to operate on."""
    with app.app_context():
        child = Child(
            first_name='Test', last_name='Child', date_of_birth=date(2024, 1, 1),
            gender='female', guardian_name='Test Guardian', guardian_phone='+2348000000000',
            facility_id=facility_id, enrolment_date=date(2024, 1, 2)
        )
        _db.session.add(child)
        _db.session.flush()

        tag = RFIDTag(uid_hex='AABBCCDD', child_id=child.child_id, issue_date=date(2024, 1, 2), status='active')
        _db.session.add(tag)
        _db.session.commit()
        return tag.tag_id


@pytest.fixture(autouse=True)
def _reset_rfid_scan_buffers():
    """app/rfid.py's _latest_scans / _latest_unregistered_scans are
    module-level dicts, not tied to the per-test DB fixture. Since the
    in-memory DB resets its autoincrement IDs every test, a leftover buffer
    entry from an earlier test could collide with a facility_id reused in a
    later test. Clear both before and after every test for isolation."""
    from app import rfid as rfid_module
    rfid_module._latest_scans.clear()
    rfid_module._latest_unregistered_scans.clear()
    yield
    rfid_module._latest_scans.clear()
    rfid_module._latest_unregistered_scans.clear()


def login_as(client, role, facility_id, user_id=1):
    """Set session keys the way auth.login() does after a successful
    password check, bypassing real authentication since these tests target
    RBAC enforcement, not the login flow itself."""
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['username'] = f'{role}_user'
        sess['role'] = role
        sess['full_name'] = f'{role.title()} User'
        sess['facility_id'] = facility_id
