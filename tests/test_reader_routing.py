"""Tests for reader-declared facility routing on POST /scan:

The ESP32 now sends facility_id in every /scan POST body - a fixed identity
per physical device, set once in firmware. Scan buffer routing, check-in
attribution, and the unregistered-scan buffer must all follow that reader
facility_id, NOT Child.facility_id (the child's home/enrolment facility).
"""
from datetime import date

from app import db as _db
from app.models import Child, Vaccine, RFIDTag, Appointment

from conftest import login_as, TEST_ESP32_TOKEN

SCAN_HEADERS = {'X-Auth-Token': TEST_ESP32_TOKEN}


def _make_child(app, home_facility_id, uid_hex='AABBCCDD', tag_status='active', antigen_name='BCG'):
    with app.app_context():
        child = Child(
            first_name='Test', last_name='Child', date_of_birth=date(2024, 1, 1),
            gender='female', guardian_name='Test Guardian', guardian_phone='+2348000000000',
            facility_id=home_facility_id, enrolment_date=date(2024, 1, 2)
        )
        _db.session.add(child)
        _db.session.flush()

        vaccine = Vaccine(antigen_name=antigen_name, recommended_weeks=0, dose_number=1)
        _db.session.add(vaccine)
        _db.session.flush()

        apt = Appointment(child_id=child.child_id, vaccine_id=vaccine.vaccine_id,
                           scheduled_date=date.today(), status='pending')
        _db.session.add(apt)

        tag = RFIDTag(uid_hex=uid_hex, child_id=child.child_id, issue_date=date(2024, 1, 2), status=tag_status)
        _db.session.add(tag)
        _db.session.commit()

        return child.child_id


# ---------------------------------------------------------------------------
# facility_id validation
# ---------------------------------------------------------------------------
def test_scan_without_facility_id_returns_400(client):
    resp = client.post('/scan', json={'uid': 'AABBCCDD'}, headers=SCAN_HEADERS)

    assert resp.status_code == 400
    assert resp.get_json()['message'] == 'Missing facility_id'


def test_scan_with_unknown_facility_id_returns_400(client):
    resp = client.post('/scan', json={'uid': 'AABBCCDD', 'facility_id': 999999}, headers=SCAN_HEADERS)

    assert resp.status_code == 400
    assert resp.get_json()['message'] == 'Unknown facility_id'


# ---------------------------------------------------------------------------
# 'found' branch: routing follows the reader, not the child's home facility
# ---------------------------------------------------------------------------
def test_found_scan_routes_to_readers_facility_not_childs_home(app, client, facility_id, facility_id_2):
    _make_child(app, home_facility_id=facility_id)  # child's home is facility_id (Surulere)

    resp = client.post('/scan', json={'uid': 'AABBCCDD', 'facility_id': facility_id_2}, headers=SCAN_HEADERS)
    assert resp.status_code == 200

    from app.rfid import _latest_scans
    assert facility_id_2 in _latest_scans
    assert facility_id not in _latest_scans


def test_checked_in_child_appears_only_under_readers_facility(app, client, facility_id, facility_id_2):
    _make_child(app, home_facility_id=facility_id)

    resp = client.post('/scan', json={'uid': 'AABBCCDD', 'facility_id': facility_id_2}, headers=SCAN_HEADERS)
    assert resp.status_code == 200

    login_as(client, 'immunisation_officer', facility_id_2)
    resp_at_reader_facility = client.get('/scan/checked-in')
    assert len(resp_at_reader_facility.get_json()['queue']) == 1

    login_as(client, 'immunisation_officer', facility_id)
    resp_at_home_facility = client.get('/scan/checked-in')
    assert resp_at_home_facility.get_json()['queue'] == []


# ---------------------------------------------------------------------------
# 'deactivated' branch: same reader-routing behavior
# ---------------------------------------------------------------------------
def test_deactivated_scan_routes_to_readers_facility_not_childs_home(app, client, facility_id, facility_id_2):
    _make_child(app, home_facility_id=facility_id, tag_status='inactive')

    resp = client.post('/scan', json={'uid': 'AABBCCDD', 'facility_id': facility_id_2}, headers=SCAN_HEADERS)
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'deactivated'

    from app.rfid import _latest_scans
    assert facility_id_2 in _latest_scans
    assert facility_id not in _latest_scans


# ---------------------------------------------------------------------------
# Unregistered-UID buffer: now facility-keyed, not global
# ---------------------------------------------------------------------------
def test_unknown_uid_visible_only_to_readers_facility_session(client, facility_id, facility_id_2):
    resp = client.post('/scan', json={'uid': 'FFFFFFFF', 'facility_id': facility_id_2}, headers=SCAN_HEADERS)
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'unknown'

    login_as(client, 'data_entry_clerk', facility_id_2)
    resp_at_reader_facility = client.get('/scan/latest-unregistered')
    assert resp_at_reader_facility.get_json()['status'] == 'unknown'
    assert resp_at_reader_facility.get_json()['uid_hex'] == 'FFFFFFFF'

    login_as(client, 'data_entry_clerk', facility_id)
    resp_at_other_facility = client.get('/scan/latest-unregistered')
    assert resp_at_other_facility.get_json()['status'] == 'idle'
