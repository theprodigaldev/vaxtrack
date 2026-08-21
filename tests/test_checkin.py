"""Tests for the persisted checked-in queue feature:
- POST /scan stamping Appointment.checked_in_at (app/rfid.py)
- GET /scan/checked-in (app/rfid.py)
- dashboard.html's per-role scan feed / queue markup

These are candidates for TC18/TC19 in the final report, beyond the
original 17-case functional test matrix.
"""
from datetime import date, datetime, timedelta

from app import db as _db
from app.models import Child, Vaccine, RFIDTag, Appointment, AuditLog

from conftest import login_as, TEST_ESP32_TOKEN

SCAN_HEADERS = {'X-Auth-Token': TEST_ESP32_TOKEN}


def _make_child_with_appointment(app, facility_id, uid_hex='AABBCCDD',
                                  apt_status='pending', scheduled_date=None,
                                  checked_in_at=None, antigen_name='BCG'):
    """Create a Child + one Vaccine/Appointment + RFIDTag, with full control
    over the appointment's status/scheduled_date/checked_in_at so each test
    can set up the exact scenario it needs."""
    with app.app_context():
        child = Child(
            first_name='Test', last_name='Child', date_of_birth=date(2024, 1, 1),
            gender='female', guardian_name='Test Guardian', guardian_phone='+2348000000000',
            facility_id=facility_id, enrolment_date=date(2024, 1, 2)
        )
        _db.session.add(child)
        _db.session.flush()

        vaccine = Vaccine(antigen_name=antigen_name, recommended_weeks=0, dose_number=1)
        _db.session.add(vaccine)
        _db.session.flush()

        apt = Appointment(
            child_id=child.child_id, vaccine_id=vaccine.vaccine_id,
            scheduled_date=scheduled_date or date.today(),
            status=apt_status, checked_in_at=checked_in_at
        )
        _db.session.add(apt)

        tag = RFIDTag(uid_hex=uid_hex, child_id=child.child_id, issue_date=date(2024, 1, 2), status='active')
        _db.session.add(tag)
        _db.session.commit()

        return child.child_id, apt.appointment_id


def _get_appointment(app, appointment_id):
    with app.app_context():
        return Appointment.query.get(appointment_id)


# ---------------------------------------------------------------------------
# POST /scan check-in stamping
# ---------------------------------------------------------------------------
def test_first_scan_of_day_sets_checked_in_at(app, client, facility_id):
    child_id, apt_id = _make_child_with_appointment(app, facility_id, checked_in_at=None)

    resp = client.post('/scan', json={'uid': 'AABBCCDD'}, headers=SCAN_HEADERS)
    assert resp.status_code == 200

    apt = _get_appointment(app, apt_id)
    assert apt.checked_in_at is not None
    assert apt.checked_in_at.date() == date.today()


def test_same_day_rescan_does_not_change_checked_in_at(app, client, facility_id):
    original = datetime.combine(date.today(), datetime.min.time()).replace(hour=8)
    child_id, apt_id = _make_child_with_appointment(app, facility_id, checked_in_at=original)

    resp = client.post('/scan', json={'uid': 'AABBCCDD'}, headers=SCAN_HEADERS)
    assert resp.status_code == 200

    apt = _get_appointment(app, apt_id)
    assert apt.checked_in_at == original


def test_new_calendar_day_rescan_refreshes_checked_in_at(app, client, facility_id):
    yesterday_stamp = datetime.combine(date.today() - timedelta(days=1), datetime.min.time()).replace(hour=9)
    child_id, apt_id = _make_child_with_appointment(app, facility_id, checked_in_at=yesterday_stamp)

    resp = client.post('/scan', json={'uid': 'AABBCCDD'}, headers=SCAN_HEADERS)
    assert resp.status_code == 200

    apt = _get_appointment(app, apt_id)
    assert apt.checked_in_at.date() == date.today()
    assert apt.checked_in_at != yesterday_stamp


def test_checkin_stamp_writes_audit_log_with_user_id_none(app, client, facility_id):
    child_id, apt_id = _make_child_with_appointment(app, facility_id, checked_in_at=None)

    client.post('/scan', json={'uid': 'AABBCCDD'}, headers=SCAN_HEADERS)

    with app.app_context():
        logs = AuditLog.query.filter_by(
            table_affected='appointments', record_id=apt_id, action_type='UPDATE'
        ).all()
        assert len(logs) >= 1
        assert all(log.user_id is None for log in logs)


def test_manually_flagged_overdue_still_gets_checked_in(app, client, facility_id):
    # Simulates the result of patients.py's flag_defaulter(): status='overdue',
    # not 'pending'. status != 'completed' must still trigger check-in.
    child_id, apt_id = _make_child_with_appointment(
        app, facility_id, apt_status='overdue',
        scheduled_date=date.today() - timedelta(days=5), checked_in_at=None
    )

    resp = client.post('/scan', json={'uid': 'AABBCCDD'}, headers=SCAN_HEADERS)
    assert resp.status_code == 200

    apt = _get_appointment(app, apt_id)
    assert apt.checked_in_at is not None
    assert apt.checked_in_at.date() == date.today()


# ---------------------------------------------------------------------------
# GET /scan/checked-in
# ---------------------------------------------------------------------------
def test_child_with_zero_noncompleted_appointments_not_in_queue(app, client, facility_id):
    # Even if checked_in_at happens to be set on a *completed* appointment,
    # the queue must still exclude it (status != 'completed' filter).
    _make_child_with_appointment(
        app, facility_id, apt_status='completed', checked_in_at=datetime.utcnow()
    )

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.get('/scan/checked-in')

    assert resp.status_code == 200
    assert resp.get_json()['queue'] == []


def test_child_with_one_completed_one_pending_still_in_queue(app, client, facility_id):
    with app.app_context():
        child = Child(
            first_name='Two', last_name='Vax', date_of_birth=date(2024, 1, 1),
            gender='male', guardian_name='Guardian Two', guardian_phone='+2348000000001',
            facility_id=facility_id, enrolment_date=date(2024, 1, 2)
        )
        _db.session.add(child)
        _db.session.flush()

        v1 = Vaccine(antigen_name='BCG', recommended_weeks=0, dose_number=1)
        v2 = Vaccine(antigen_name='OPV', recommended_weeks=6, dose_number=1)
        _db.session.add_all([v1, v2])
        _db.session.flush()

        now = datetime.utcnow()
        completed_apt = Appointment(child_id=child.child_id, vaccine_id=v1.vaccine_id,
                                     scheduled_date=date.today(), status='completed',
                                     checked_in_at=None)
        pending_apt = Appointment(child_id=child.child_id, vaccine_id=v2.vaccine_id,
                                   scheduled_date=date.today(), status='pending',
                                   checked_in_at=now)
        _db.session.add_all([completed_apt, pending_apt])
        _db.session.commit()
        child_id = child.child_id

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.get('/scan/checked-in')

    queue = resp.get_json()['queue']
    assert len(queue) == 1
    assert queue[0]['child_id'] == child_id
    assert queue[0]['vaccines'] == ['OPV']


def test_checked_in_queue_response_shape_and_search(app, client, facility_id):
    _make_child_with_appointment(app, facility_id, uid_hex='UID0001',
                                  checked_in_at=datetime.utcnow() - timedelta(minutes=5))

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.get('/scan/checked-in')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'ok'
    assert len(body['queue']) == 1
    assert body['queue'][0]['first_name'] == 'Test'

    # q= filters server-side on child/guardian name
    resp_match = client.get('/scan/checked-in?q=Test')
    assert len(resp_match.get_json()['queue']) == 1

    resp_no_match = client.get('/scan/checked-in?q=Nobody')
    assert resp_no_match.get_json()['queue'] == []


# ---------------------------------------------------------------------------
# Dashboard markup per role
# ---------------------------------------------------------------------------
def test_admin_dashboard_has_no_scan_feed_markup(client, facility_id):
    login_as(client, 'admin', facility_id)
    resp = client.get('/dashboard')

    assert b'RFID Scan Feed' not in resp.data
    assert b'Checked-In Queue' not in resp.data


def test_clerk_dashboard_still_has_scan_feed_markup(client, facility_id):
    login_as(client, 'data_entry_clerk', facility_id)
    resp = client.get('/dashboard')

    assert b'RFID Scan Feed' in resp.data
    assert b'id="scan-result"' in resp.data
    assert b'Checked-In Queue' not in resp.data


def test_officer_dashboard_has_checkin_queue_markup(client, facility_id):
    login_as(client, 'immunisation_officer', facility_id)
    resp = client.get('/dashboard')

    assert b'Checked-In Queue' in resp.data
    assert b'id="checkin-queue"' in resp.data
    assert b'id="checkin-search"' in resp.data
    assert b'RFID Scan Feed' not in resp.data
