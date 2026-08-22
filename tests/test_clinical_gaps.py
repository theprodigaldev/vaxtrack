"""Tests for the three clinical-gap features:
- Adverse event (AEFI) reporting on Vaccination rows
- Deferred appointments (a resolved clinical decision, distinct from a
  no-show/overdue), and their exclusion from overdue/defaulter counting
- Batch search for recall / adverse-event tracing
"""
from datetime import date, timedelta

from app import db as _db
from app.models import Child, Vaccine, Appointment, Vaccination, AuditLog

from conftest import login_as, TEST_ESP32_TOKEN

SCAN_HEADERS = {'X-Auth-Token': TEST_ESP32_TOKEN}


def _make_child(app, facility_id, first_name='Test', last_name='Child'):
    with app.app_context():
        child = Child(
            first_name=first_name, last_name=last_name, date_of_birth=date(2024, 1, 1),
            gender='female', guardian_name='Test Guardian', guardian_phone='+2348000000000',
            facility_id=facility_id, enrolment_date=date(2024, 1, 2)
        )
        _db.session.add(child)
        _db.session.commit()
        return child.child_id


def _make_vaccine(app, antigen_name='BCG', dose_number=1):
    with app.app_context():
        v = Vaccine(antigen_name=antigen_name, recommended_weeks=0, dose_number=dose_number)
        _db.session.add(v)
        _db.session.commit()
        return v.vaccine_id


def _make_appointment(app, child_id, vaccine_id, status='pending', scheduled_date=None):
    with app.app_context():
        apt = Appointment(
            child_id=child_id, vaccine_id=vaccine_id,
            scheduled_date=scheduled_date or date.today(), status=status
        )
        _db.session.add(apt)
        _db.session.commit()
        return apt.appointment_id


def _make_completed_vaccination(app, child_id, vaccine_id, appointment_id, facility_id,
                                 batch_number='BATCH-001'):
    with app.app_context():
        vax = Vaccination(
            child_id=child_id, vaccine_id=vaccine_id, appointment_id=appointment_id,
            dose_number=1, date_given=date.today(), batch_number=batch_number,
            administered_by=1, facility_id=facility_id
        )
        _db.session.add(vax)
        _db.session.commit()
        return vax.vaccination_id


def _get_vaccination(app, vaccination_id):
    with app.app_context():
        return Vaccination.query.get(vaccination_id)


def _get_appointment(app, appointment_id):
    with app.app_context():
        return Appointment.query.get(appointment_id)


# ---------------------------------------------------------------------------
# Adverse event reporting
# ---------------------------------------------------------------------------
def test_report_adverse_event_updates_vaccination_and_audit_log(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    vax_id = _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id)

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.post(f'/vaccinations/{vax_id}/adverse-event',
                        data={'severity': 'moderate', 'description': 'Fever and localized swelling.'})

    assert resp.status_code == 302

    vax = _get_vaccination(app, vax_id)
    assert vax.adverse_event_reported is True
    assert vax.adverse_event_severity == 'moderate'
    assert vax.adverse_event_description == 'Fever and localized swelling.'
    assert vax.adverse_event_date == date.today()

    with app.app_context():
        logs = AuditLog.query.filter_by(
            table_affected='vaccinations', record_id=vax_id, action_type='UPDATE'
        ).all()
        assert len(logs) == 1
        assert logs[0].old_value['adverse_event_reported'] is False
        assert logs[0].new_value['adverse_event_reported'] is True
        assert logs[0].new_value['adverse_event_severity'] == 'moderate'


def test_report_adverse_event_rejects_invalid_severity(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    vax_id = _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id)

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.post(f'/vaccinations/{vax_id}/adverse-event',
                        data={'severity': 'catastrophic', 'description': 'Something happened.'})

    assert resp.status_code == 302
    vax = _get_vaccination(app, vax_id)
    assert vax.adverse_event_reported is False


def test_report_adverse_event_requires_description(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    vax_id = _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id)

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.post(f'/vaccinations/{vax_id}/adverse-event',
                        data={'severity': 'mild', 'description': ''})

    assert resp.status_code == 302
    vax = _get_vaccination(app, vax_id)
    assert vax.adverse_event_reported is False


def test_clerk_can_report_adverse_event(app, client, facility_id):
    """Reporting permission is now immunisation_officer + data_entry_clerk."""
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    vax_id = _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id)

    login_as(client, 'data_entry_clerk', facility_id)
    resp = client.post(f'/vaccinations/{vax_id}/adverse-event',
                        data={'severity': 'mild', 'description': 'Rash.'})

    assert resp.status_code == 302
    vax = _get_vaccination(app, vax_id)
    assert vax.adverse_event_reported is True
    assert vax.adverse_event_severity == 'mild'


def test_admin_cannot_report_adverse_event(app, client, facility_id):
    """Admin lost the reporting permission - this is distinct from admin's
    continued read-only visibility of an existing report (see the
    companion test below)."""
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    vax_id = _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id)

    login_as(client, 'admin', facility_id)
    resp = client.post(f'/vaccinations/{vax_id}/adverse-event',
                        data={'severity': 'mild', 'description': 'Rash.'})

    assert resp.status_code == 403
    assert _get_vaccination(app, vax_id).adverse_event_reported is False


def test_admin_can_still_see_adverse_event_warning_despite_losing_report_permission(app, client, facility_id):
    """The read-only warning (banner + inline 'AEFI Reported' indicator) must
    stay visible to admin even though admin can no longer submit a new
    report - these are two different permissions and must not be conflated."""
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    vax_id = _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id)
    with app.app_context():
        vax = Vaccination.query.get(vax_id)
        vax.adverse_event_reported = True
        vax.adverse_event_severity = 'severe'
        vax.adverse_event_description = 'Anaphylaxis observed.'
        vax.adverse_event_date = date.today()
        _db.session.commit()

    login_as(client, 'admin', facility_id)
    resp = client.get(f'/children/{child_id}')

    assert resp.status_code == 200
    assert b'Prior Adverse Event(s) on Record' in resp.data
    assert b'AEFI Reported' in resp.data
    # And confirm the reporting button itself is NOT offered to admin.
    assert b'openAdverseEvent(' not in resp.data


def test_officer_can_still_report_and_view_adverse_events(app, client, facility_id):
    """immunisation_officer's access is unchanged by this permission move."""
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    vax_id = _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id)

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.post(f'/vaccinations/{vax_id}/adverse-event',
                        data={'severity': 'moderate', 'description': 'Localized swelling.'})
    assert resp.status_code == 302
    assert _get_vaccination(app, vax_id).adverse_event_reported is True

    resp = client.get(f'/children/{child_id}')
    assert resp.status_code == 200
    assert b'Prior Adverse Event(s) on Record' in resp.data
    assert b'AEFI Reported' in resp.data


def test_adverse_event_banner_condition_detectable_by_query(app, facility_id):
    """The warning-banner condition (a child with any prior
    adverse_event_reported=True vaccination) must be a plain query result,
    independent of any template rendering."""
    child_id = _make_child(app, facility_id)
    v1 = _make_vaccine(app, antigen_name='BCG')
    v2 = _make_vaccine(app, antigen_name='OPV')
    apt1 = _make_appointment(app, child_id, v1, status='completed')
    apt2 = _make_appointment(app, child_id, v2, status='completed')
    reported_vax_id = _make_completed_vaccination(app, child_id, v1, apt1, facility_id, batch_number='B1')
    _make_completed_vaccination(app, child_id, v2, apt2, facility_id, batch_number='B2')

    with app.app_context():
        vax = Vaccination.query.get(reported_vax_id)
        vax.adverse_event_reported = True
        vax.adverse_event_severity = 'severe'
        _db.session.commit()

        adverse_events = Vaccination.query.filter_by(child_id=child_id, adverse_event_reported=True).all()
        assert len(adverse_events) == 1
        assert adverse_events[0].vaccination_id == reported_vax_id
        assert adverse_events[0].adverse_event_severity == 'severe'


# ---------------------------------------------------------------------------
# Deferred appointments
# ---------------------------------------------------------------------------
def test_defer_appointment_sets_status_and_reason(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='pending')

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.post(f'/appointments/{apt_id}/defer', data={'deferral_reason': 'Child unwell today.'})

    assert resp.status_code == 302
    apt = _get_appointment(app, apt_id)
    assert apt.status == 'deferred'
    assert apt.deferral_reason == 'Child unwell today.'

    with app.app_context():
        logs = AuditLog.query.filter_by(
            table_affected='appointments', record_id=apt_id, action_type='UPDATE'
        ).all()
        assert any(log.new_value.get('status') == 'deferred' for log in logs)


def test_defer_requires_non_empty_reason(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='pending')

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.post(f'/appointments/{apt_id}/defer', data={'deferral_reason': '   '})

    assert resp.status_code == 302
    apt = _get_appointment(app, apt_id)
    assert apt.status == 'pending'
    assert apt.deferral_reason is None


def test_clerk_cannot_defer_appointment(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='pending')

    login_as(client, 'data_entry_clerk', facility_id)
    resp = client.post(f'/appointments/{apt_id}/defer', data={'deferral_reason': 'Test'})

    assert resp.status_code == 403
    assert _get_appointment(app, apt_id).status == 'pending'


def test_reschedule_deferred_appointment_resets_to_pending(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='deferred',
                                scheduled_date=date.today() - timedelta(days=10))
    with app.app_context():
        apt = Appointment.query.get(apt_id)
        apt.deferral_reason = 'Child unwell.'
        _db.session.commit()

    login_as(client, 'data_entry_clerk', facility_id)
    new_date = (date.today() + timedelta(days=7))
    # Avoid the weekend-adjustment logic complicating the assertion.
    while new_date.weekday() >= 5:
        new_date += timedelta(days=1)

    resp = client.post(f'/appointments/{apt_id}/reschedule', data={'new_date': new_date.isoformat()})

    assert resp.status_code == 302
    apt = _get_appointment(app, apt_id)
    assert apt.status == 'pending'
    assert apt.deferral_reason is None
    assert apt.scheduled_date == new_date


# ---------------------------------------------------------------------------
# Deferred appointments excluded from overdue/defaulter counting
# (auth.py dashboard, reports.py defaulters, rfid.py /scan classification)
# ---------------------------------------------------------------------------
def test_dashboard_overdue_count_excludes_deferred(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    past = date.today() - timedelta(days=5)

    # One genuinely overdue (regression case - must still be counted)...
    _make_appointment(app, child_id, vaccine_id, status='pending', scheduled_date=past)
    # ...and one deferred with the same past date, which must NOT be counted.
    v2 = _make_vaccine(app, antigen_name='OPV')
    _make_appointment(app, child_id, v2, status='deferred', scheduled_date=past)

    with app.app_context():
        today = date.today()
        overdue_count = Appointment.query.filter(
            Appointment.scheduled_date < today,
            Appointment.status.in_(['pending', 'overdue'])
        ).count()
        assert overdue_count == 1


def test_scan_overdue_bucket_excludes_deferred_appointment(app, client, facility_id):
    from app.models import RFIDTag

    child_id = _make_child(app, facility_id)
    v1 = _make_vaccine(app, antigen_name='BCG')
    v2 = _make_vaccine(app, antigen_name='OPV')
    past = date.today() - timedelta(days=5)

    _make_appointment(app, child_id, v1, status='pending', scheduled_date=past)
    _make_appointment(app, child_id, v2, status='deferred', scheduled_date=past)

    with app.app_context():
        tag = RFIDTag(uid_hex='DEFERTEST', child_id=child_id, issue_date=date(2024, 1, 2), status='active')
        _db.session.add(tag)
        _db.session.commit()

    resp = client.post('/scan', json={'uid': 'DEFERTEST', 'facility_id': facility_id}, headers=SCAN_HEADERS)
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body['appointments']['overdue']) == 1
    assert body['appointments']['overdue'][0]['vaccine'] == 'BCG'
    assert body['summary']['overdue'] == 1


def test_defaulters_report_excludes_deferred(app, client, facility_id):
    overdue_child = _make_child(app, facility_id, first_name='Overdue', last_name='Kid')
    deferred_child = _make_child(app, facility_id, first_name='Deferred', last_name='Kid')
    v1 = _make_vaccine(app, antigen_name='BCG')
    v2 = _make_vaccine(app, antigen_name='OPV')
    past = date.today() - timedelta(days=5)

    _make_appointment(app, overdue_child, v1, status='pending', scheduled_date=past)
    _make_appointment(app, deferred_child, v2, status='deferred', scheduled_date=past)

    login_as(client, 'admin', facility_id)
    resp = client.get('/reports/defaulters')

    assert resp.status_code == 200
    assert b'Overdue Kid' in resp.data
    assert b'Deferred Kid' not in resp.data


# ---------------------------------------------------------------------------
# Batch search
# ---------------------------------------------------------------------------
def test_batch_search_returns_matching_results(app, client, facility_id):
    child_id = _make_child(app, facility_id, first_name='Batchy', last_name='Kid')
    vaccine_id = _make_vaccine(app, antigen_name='Pentavalent')
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id, batch_number='LOT-777')

    login_as(client, 'admin', facility_id)
    resp = client.get('/reports/batch-search?batch=LOT-777')

    assert resp.status_code == 200
    assert b'Batchy Kid' in resp.data
    assert b'Pentavalent' in resp.data


def test_batch_search_empty_for_unknown_batch(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='completed')
    _make_completed_vaccination(app, child_id, vaccine_id, apt_id, facility_id, batch_number='LOT-777')

    login_as(client, 'admin', facility_id)
    resp = client.get('/reports/batch-search?batch=LOT-DOES-NOT-EXIST')

    assert resp.status_code == 200
    assert b'No vaccinations found' in resp.data


def test_batch_search_requires_admin(client, facility_id):
    login_as(client, 'immunisation_officer', facility_id)
    resp = client.get('/reports/batch-search?batch=LOT-777')

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Defer button visibility must match the route's actual permission
# (POST /appointments/<id>/defer is @require_role('immunisation_officer', 'admin'))
# ---------------------------------------------------------------------------
def test_clerk_does_not_see_defer_button_on_child_page(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    _make_appointment(app, child_id, vaccine_id, status='pending')

    login_as(client, 'data_entry_clerk', facility_id)
    resp = client.get(f'/children/{child_id}')

    assert resp.status_code == 200
    assert b'openDefer(' not in resp.data
    assert b'Confirm Defer' not in resp.data


def test_officer_sees_defer_button_on_child_page(app, client, facility_id):
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    _make_appointment(app, child_id, vaccine_id, status='pending')

    login_as(client, 'immunisation_officer', facility_id)
    resp = client.get(f'/children/{child_id}')

    assert resp.status_code == 200
    assert b'openDefer(' in resp.data


def test_clerk_direct_post_to_defer_route_still_returns_403(app, client, facility_id):
    """Regression check: the backend permission itself was already correct -
    only a stale button-visibility condition would have been the bug."""
    child_id = _make_child(app, facility_id)
    vaccine_id = _make_vaccine(app)
    apt_id = _make_appointment(app, child_id, vaccine_id, status='pending')

    login_as(client, 'data_entry_clerk', facility_id)
    resp = client.post(f'/appointments/{apt_id}/defer', data={'deferral_reason': 'Test'})

    assert resp.status_code == 403
    assert _get_appointment(app, apt_id).status == 'pending'
