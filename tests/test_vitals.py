"""Tests for vitals tracking (weight/temperature), which extends the
existing MedicalNote model/table rather than creating a new one. Recorded
by the Data Entry Clerk as a standalone action, unrelated to the RFID
scan/check-in flow.
"""
from app.models import MedicalNote, AuditLog

from conftest import login_as


def _get_notes(app, child_id):
    with app.app_context():
        return MedicalNote.query.filter_by(child_id=child_id).all()


# ---------------------------------------------------------------------------
# Successful vitals recording
# ---------------------------------------------------------------------------
def test_clerk_records_vitals_creates_medical_note(client, facility_id, child_id):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '12.5', 'temperature_celsius': '36.8'})

    assert resp.status_code == 302

    notes = _get_notes(client.application, child_id)
    assert len(notes) == 1
    note = notes[0]
    assert str(note.weight_kg) == '12.50'
    assert str(note.temperature_celsius) == '36.8'
    assert note.note_text == 'Vitals recorded: 12.5 kg, 36.8°C'
    assert note.recorded_by == 1


def test_vitals_write_creates_correct_audit_log_entry(client, facility_id, child_id):
    login_as(client, 'data_entry_clerk', facility_id)

    client.post(f'/children/{child_id}/vitals',
                data={'weight_kg': '9.0', 'temperature_celsius': '37.0'})

    with client.application.app_context():
        note = MedicalNote.query.filter_by(child_id=child_id).first()
        logs = AuditLog.query.filter_by(
            table_affected='medical_notes', record_id=note.note_id, action_type='INSERT'
        ).all()
        assert len(logs) == 1
        assert logs[0].user_id == 1
        assert logs[0].old_value is None
        # row_to_dict() runs on the in-memory object pre-commit, so this
        # reflects the parsed Decimal exactly as entered (not yet re-quantized
        # to the column's declared scale by a DB round-trip).
        assert logs[0].new_value['weight_kg'] == '9.0'
        assert logs[0].new_value['temperature_celsius'] == '37.0'


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_officer_cannot_record_vitals(client, facility_id, child_id):
    login_as(client, 'immunisation_officer', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '12.5', 'temperature_celsius': '36.8'})

    assert resp.status_code == 403
    assert _get_notes(client.application, child_id) == []


def test_unauthenticated_request_redirects_to_login(client, child_id):
    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '12.5', 'temperature_celsius': '36.8'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    assert _get_notes(client.application, child_id) == []


def test_admin_can_record_vitals(client, facility_id, child_id):
    login_as(client, 'admin', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '12.5', 'temperature_celsius': '36.8'})

    assert resp.status_code == 302
    assert len(_get_notes(client.application, child_id)) == 1


# ---------------------------------------------------------------------------
# Validation bounds
# ---------------------------------------------------------------------------
def test_weight_below_minimum_rejected(client, facility_id, child_id):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '0.5', 'temperature_celsius': '36.8'})

    assert resp.status_code == 302
    assert _get_notes(client.application, child_id) == []


def test_weight_above_maximum_rejected(client, facility_id, child_id):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '30.1', 'temperature_celsius': '36.8'})

    assert resp.status_code == 302
    assert _get_notes(client.application, child_id) == []


def test_temperature_below_minimum_rejected(client, facility_id, child_id):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '12.5', 'temperature_celsius': '29.9'})

    assert resp.status_code == 302
    assert _get_notes(client.application, child_id) == []


def test_temperature_above_maximum_rejected(client, facility_id, child_id):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '12.5', 'temperature_celsius': '43.1'})

    assert resp.status_code == 302
    assert _get_notes(client.application, child_id) == []


def test_boundary_values_accepted(client, facility_id, child_id):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': '1.0', 'temperature_celsius': '30.0'})
    assert resp.status_code == 302
    assert len(_get_notes(client.application, child_id)) == 1


def test_non_numeric_input_rejected(client, facility_id, child_id):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/children/{child_id}/vitals',
                        data={'weight_kg': 'abc', 'temperature_celsius': '36.8'})

    assert resp.status_code == 302
    assert _get_notes(client.application, child_id) == []


# ---------------------------------------------------------------------------
# Regression: add_note() (officer's free-text notes) unaffected
# ---------------------------------------------------------------------------
def test_add_note_still_works_with_null_vitals_columns(client, facility_id, child_id):
    login_as(client, 'immunisation_officer', facility_id)

    resp = client.post(f'/children/{child_id}/notes', data={'note_text': 'Mild fever observed.'})

    assert resp.status_code == 302
    notes = _get_notes(client.application, child_id)
    assert len(notes) == 1
    assert notes[0].note_text == 'Mild fever observed.'
    assert notes[0].weight_kg is None
    assert notes[0].temperature_celsius is None
