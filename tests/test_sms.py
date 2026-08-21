"""Tests for the eBulkSMS send_sms() implementation and the morning_of
SMS template length fix in app/notifications.py.
"""
from datetime import date
from unittest.mock import patch, MagicMock

from app import db as _db
from app.models import Child, Vaccine, Appointment
from app.notifications import send_sms, send_reminders

BASE_CONFIG = {
    'EBULKSMS_USERNAME': 'ops@example.com',
    'EBULKSMS_API_KEY': 'test-api-key',
    'EBULKSMS_SENDER': 'VAXTRACK',
    'EBULKSMS_DND_SENDER': 'true',
}


def _mock_response(json_body):
    resp = MagicMock()
    resp.json.return_value = json_body
    return resp


# ---------------------------------------------------------------------------
# send_sms()
# ---------------------------------------------------------------------------
def test_send_sms_skipped_when_username_missing():
    config = {**BASE_CONFIG, 'EBULKSMS_USERNAME': ''}
    result = send_sms('+2348012345678', 'hello', config)
    assert result == {'status': 'skipped', 'reason': 'eBulkSMS credentials not configured'}


def test_send_sms_skipped_when_api_key_missing():
    config = {**BASE_CONFIG, 'EBULKSMS_API_KEY': ''}
    result = send_sms('+2348012345678', 'hello', config)
    assert result == {'status': 'skipped', 'reason': 'eBulkSMS credentials not configured'}


def test_send_sms_maps_success_status():
    body = {'response': {'status': 'SUCCESS', 'totalsent': '1', 'cost': '1'}}
    with patch('app.notifications.requests.post', return_value=_mock_response(body)):
        result = send_sms('+2348012345678', 'hello', BASE_CONFIG)

    assert result == {'status': 'sent', 'response': body}


def test_send_sms_maps_insufficient_credit():
    body = {'response': {'status': 'INSUFFICIENT_CREDIT', 'totalsent': '0', 'cost': '0'}}
    with patch('app.notifications.requests.post', return_value=_mock_response(body)):
        result = send_sms('+2348012345678', 'hello', BASE_CONFIG)

    assert result == {'status': 'failed', 'error': 'insufficient_credit'}


def test_send_sms_maps_unrecognised_status_preserving_literal_string():
    body = {'response': {'status': 'AUTH_FAILURE', 'totalsent': '0', 'cost': '0'}}
    with patch('app.notifications.requests.post', return_value=_mock_response(body)):
        result = send_sms('+2348012345678', 'hello', BASE_CONFIG)

    assert result == {'status': 'failed', 'error': 'AUTH_FAILURE'}


def test_send_sms_network_error_returns_failed():
    with patch('app.notifications.requests.post', side_effect=ConnectionError('boom')):
        result = send_sms('+2348012345678', 'hello', BASE_CONFIG)

    assert result['status'] == 'failed'
    assert 'boom' in result['error']


def test_send_sms_request_body_shape_and_msisdn_normalisation():
    body = {'response': {'status': 'SUCCESS', 'totalsent': '1', 'cost': '1'}}
    with patch('app.notifications.requests.post', return_value=_mock_response(body)) as mock_post:
        send_sms('+2348012345678', 'hello', BASE_CONFIG)

    _, kwargs = mock_post.call_args
    assert kwargs['headers'] == {'Content-Type': 'application/json'}
    sms = kwargs['json']['SMS']
    assert sms['auth'] == {'username': 'ops@example.com', 'apikey': 'test-api-key'}
    assert sms['message']['sender'] == 'VAXTRACK'
    assert sms['message']['messagetext'] == 'hello'
    assert sms['recipients']['gsm'][0]['msidn'] == '2348012345678'  # no leading '+'
    assert sms['dndsender'] == '1'


# ---------------------------------------------------------------------------
# morning_of msg_template length (TC-motivated: was overflowing 160 chars)
# ---------------------------------------------------------------------------
def _seed_appointment(app, facility_id, first_name, last_name, antigen_name, dose_number):
    with app.app_context():
        from app.models import Facility
        child = Child(
            first_name=first_name, last_name=last_name, date_of_birth=date(2024, 1, 1),
            gender='female', guardian_name='Guardian Name', guardian_phone='+2348012345678',
            facility_id=facility_id, enrolment_date=date(2024, 1, 2)
        )
        _db.session.add(child)
        _db.session.flush()

        vaccine = Vaccine(antigen_name=antigen_name, recommended_weeks=0, dose_number=dose_number)
        _db.session.add(vaccine)
        _db.session.flush()

        apt = Appointment(child_id=child.child_id, vaccine_id=vaccine.vaccine_id,
                           scheduled_date=date.today(), status='pending')
        _db.session.add(apt)
        _db.session.commit()


def _capture_sms_message(app):
    captured = {}

    def fake_send_sms(phone, message, app_config):
        captured['message'] = message
        return {'status': 'skipped', 'reason': 'test'}

    with patch('app.notifications.send_sms', side_effect=fake_send_sms):
        send_reminders(app, 'morning_of')

    return captured.get('message')


def test_morning_of_message_under_160_chars_realistic_name(app, facility_id):
    _seed_appointment(app, facility_id, 'Blessing', 'Adeyemi', 'Pentavalent', 3)

    message = _capture_sms_message(app)

    assert message is not None
    assert len(message) <= 160


def test_morning_of_message_under_160_chars_long_name(app, facility_id):
    _seed_appointment(app, facility_id, 'Chukwuemeka Ifeanyichukwu', 'Nwachukwu-Obiajulu',
                       'Pneumococcal Conjugate', 2)

    message = _capture_sms_message(app)

    assert message is not None
    assert len(message) <= 160


def test_morning_of_message_does_not_reference_date_or_facility(app, facility_id):
    """The rewritten template dropped {date}/{facility} entirely - confirm the
    formatted message has no leftover braces (a stale-kwarg symptom)."""
    _seed_appointment(app, facility_id, 'Amara', 'Nwosu', 'BCG', 1)

    message = _capture_sms_message(app)

    assert '{' not in message and '}' not in message
