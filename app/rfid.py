import threading
from datetime import date, timedelta, datetime

from flask import Blueprint, request, jsonify, current_app, session

from app import db
from app.models import RFIDTag, Child, Appointment, Vaccine
from app.auth import login_required, require_role, write_audit, row_to_dict

rfid_bp = Blueprint('rfid', __name__)

# Per-facility scan buffer, keyed by facility_id so multi-facility works
_scan_lock = threading.Lock()
_latest_scans = {}  # {facility_id: {'data': dict, 'acked': bool}}

# Global single-slot buffer for unknown-UID scans. No facility can be derived
# when the UID has no matching tag, so this is not facility-scoped.
# Guarded by the same _scan_lock for simplicity.
_latest_unregistered_scan = {'data': None, 'acked': True}


def build_lcd_payload(status, overdue=None, due_today=None, due_this_week=None,
                       upcoming=None, completed=None, uid_hex=None):
    """Pre-compute the LCD state/line1/line2/led/buzzer contract so the ESP32
    firmware only has to switch on `lcd.state` and print two lines, with no
    business logic on the microcontroller. Pure function (no Flask/DB access)
    so it's directly unit-testable. See TC04/TC05/TC09 in the functional test
    matrix for the state assignments implemented here.
    """
    overdue = overdue or []
    due_today = due_today or []
    due_this_week = due_this_week or []
    upcoming = upcoming or []
    completed = completed or []

    if status == 'unknown':
        return {
            'state': 7, 'line1': 'Card Not Found', 'line2': 'Register Child',
            'led': 'red_solid', 'buzzer': '2_beeps'
        }

    if status == 'deactivated':
        return {
            'state': 8, 'line1': 'Card Deactivated', 'line2': 'See Admin',
            'led': 'red_flashing', 'buzzer': '3_beeps'
        }

    # status == 'found'
    if len(overdue) > 1:
        return {
            'state': 5, 'line1': f'{len(overdue)} Missed Vaccines',
            'line2': 'See Nurse', 'led': 'red_flashing', 'buzzer': '3_rapid_beeps'
        }

    if len(overdue) == 1:
        return {
            'state': 4, 'line1': f'MISSED: {overdue[0]["vaccine"]}',
            'line2': 'Give Now!', 'led': 'red_solid', 'buzzer': '2_short_beeps'
        }

    if not due_today and not due_this_week and not upcoming:
        return {
            'state': 6, 'line1': 'All Vaccines Done', 'line2': 'EPI Complete!',
            'led': 'green_flash_3x', 'buzzer': '3_quick_beeps'
        }

    next_pending = due_today[0] if due_today else due_this_week[0] if due_this_week else upcoming[0]
    return {
        'state': 3, 'line1': f'Next: {next_pending["vaccine"]}',
        'line2': f'Due: {next_pending["scheduled_date"]}',
        'led': 'green_solid', 'buzzer': '1_beep'
    }


@rfid_bp.route('/scan', methods=['POST'])
def scan():
    """ESP32 RFID scan endpoint. Validates token, returns child record, and stores
    result in the per-facility scan buffer for dashboard polling."""
    token = request.headers.get('X-Auth-Token', '')
    expected_token = current_app.config['ESP32_AUTH_TOKEN']

    if not expected_token or token != expected_token:
        return jsonify({'status': 'unauthorized'}), 401

    data = request.get_json(silent=True)
    if not data or 'uid' not in data:
        return jsonify({'status': 'error', 'message': 'Missing UID'}), 400

    uid = data['uid'].strip().upper()

    tag = RFIDTag.query.filter_by(uid_hex=uid).first()

    if not tag:
        # No child is linked to this UID, so push to the global unregistered buffer
        # so a clerk on the dashboard or registration page can capture it.
        payload = {'status': 'unknown', 'uid_hex': uid, 'lcd': build_lcd_payload('unknown', uid_hex=uid)}
        with _scan_lock:
            _latest_unregistered_scan['data'] = payload
            _latest_unregistered_scan['acked'] = False
        return jsonify(payload), 200

    if tag.status == 'inactive':
        # Child exists but their card is deactivated. Fetch the child so the
        # facility-keyed buffer can be populated (same routing as 'found').
        child = Child.query.get(tag.child_id)
        payload = {
            'status': 'deactivated',
            'uid_hex': uid,
            'child_id': child.child_id if child else None,
            'lcd': build_lcd_payload('deactivated', uid_hex=uid),
        }
        if child:
            with _scan_lock:
                _latest_scans[child.facility_id] = {'data': payload, 'acked': False}
        return jsonify(payload), 200

    child = Child.query.get(tag.child_id)
    if not child:
        return jsonify({'status': 'error', 'message': 'Child record not found'}), 404

    appointments = (
        Appointment.query
        .filter_by(child_id=child.child_id)
        .join(Vaccine)
        .order_by(Appointment.scheduled_date)
        .all()
    )

    today = date.today()
    three_days = today + timedelta(days=3)
    now = datetime.utcnow()

    overdue = []
    due_today = []
    due_this_week = []
    upcoming = []
    completed = []

    for apt in appointments:
        vaccine = Vaccine.query.get(apt.vaccine_id)
        apt_data = {
            'appointment_id': apt.appointment_id,
            'vaccine': vaccine.antigen_name,
            'dose_number': vaccine.dose_number,
            'scheduled_date': apt.scheduled_date.isoformat(),
            'status': apt.status,
            'completed_date': apt.completed_date.isoformat() if apt.completed_date else None
        }

        # Stamp a check-in for the officer's persisted queue. Uses status !=
        # 'completed' (not == 'pending') so a manually-flagged 'overdue'
        # appointment still gets checked in. A same-day re-scan (child
        # stepped out and came back) must NOT bump checked_in_at, so it
        # doesn't unfairly bump them behind people who arrived after their
        # original check-in. checked_in_by stays NULL: this endpoint is
        # hardware-authenticated, there's no user session to attribute it to.
        if apt.status != 'completed':
            if apt.checked_in_at is None or apt.checked_in_at.date() < today:
                old_snapshot = row_to_dict(apt)
                apt.checked_in_at = now
                write_audit(None, 'UPDATE', 'appointments', apt.appointment_id,
                            old_value=old_snapshot,
                            new_value=row_to_dict(apt))

        if apt.status == 'completed':
            completed.append(apt_data)
        elif apt.scheduled_date < today:
            apt_data['status'] = 'overdue'
            overdue.append(apt_data)
        elif apt.scheduled_date == today:
            due_today.append(apt_data)
        elif apt.scheduled_date <= three_days:
            due_this_week.append(apt_data)
        else:
            upcoming.append(apt_data)

    db.session.commit()

    response_payload = {
        'status': 'found',
        'uid_hex': uid,
        'child': {
            'child_id': child.child_id,
            'first_name': child.first_name,
            'last_name': child.last_name,
            'date_of_birth': child.date_of_birth.isoformat(),
            'gender': child.gender,
            'guardian_name': child.guardian_name,
            'guardian_phone': child.guardian_phone,
            'facility_id': child.facility_id,
            'enrolment_date': child.enrolment_date.isoformat()
        },
        'appointments': {
            'overdue': overdue,
            'due_today': due_today,
            'due_this_week': due_this_week,
            'upcoming': upcoming,
            'completed': completed
        },
        'summary': {
            'total': len(appointments),
            'completed': len(completed),
            'overdue': len(overdue),
            'due_today': len(due_today),
            'upcoming': len(upcoming) + len(due_this_week)
        },
        'lcd': build_lcd_payload(
            'found',
            overdue=overdue,
            due_today=due_today,
            due_this_week=due_this_week,
            upcoming=upcoming,
            completed=completed,
            uid_hex=uid
        )
    }

    # Push into scan buffer: dashboard JS will pick this up within 2-3 seconds
    with _scan_lock:
        _latest_scans[child.facility_id] = {
            'data': response_payload,
            'acked': False
        }

    return jsonify(response_payload), 200


@rfid_bp.route('/scan/latest')
@login_required
def scan_latest():
    """Lightweight polling endpoint for the dashboard.
    Returns the latest unacknowledged scan for the user's facility, then marks
    it acknowledged so it fires only once per scan event.
    """
    fid = session.get('facility_id')
    with _scan_lock:
        scan = _latest_scans.get(fid)
        if not scan or scan['acked']:
            return jsonify({'status': 'idle'}), 200
        _latest_scans[fid]['acked'] = True
        return jsonify(scan['data']), 200


@rfid_bp.route('/scan/latest-unregistered')
@require_role('data_entry_clerk', 'admin')
def scan_latest_unregistered():
    """Global polling endpoint for unknown (unregistered) RFID scans.
    Returns the latest unacknowledged unknown-UID scan and marks it acknowledged.
    Not scoped by facility: any authorised clerk sees the same pending scan,
    since there is no child record to derive a facility from.
    """
    with _scan_lock:
        if _latest_unregistered_scan['acked']:
            return jsonify({'status': 'idle'}), 200
        _latest_unregistered_scan['acked'] = True
        return jsonify(_latest_unregistered_scan['data']), 200


@rfid_bp.route('/scan/checked-in')
@require_role('data_entry_clerk', 'immunisation_officer', 'admin')
def scan_checked_in():
    """Persisted, searchable check-in queue for the Immunisation Officer's
    dashboard (admin included for API completeness/testing; nothing in the
    UI calls this for admin). Scoped to the caller's facility. One entry per
    child, listing all their still-pending vaccines, ordered ascending by
    their earliest check-in today (first-come, first-served).
    """
    facility_id = session.get('facility_id')
    q = request.args.get('q', '').strip()
    today = date.today()

    rows_query = (
        db.session.query(Child, Appointment, Vaccine)
        .join(Appointment, Appointment.child_id == Child.child_id)
        .join(Vaccine, Vaccine.vaccine_id == Appointment.vaccine_id)
        .filter(
            Child.facility_id == facility_id,
            Appointment.checked_in_at.isnot(None),
            Appointment.status != 'completed'
        )
    )

    if q:
        rows_query = rows_query.filter(
            db.or_(
                Child.first_name.ilike(f'%{q}%'),
                Child.guardian_name.ilike(f'%{q}%')
            )
        )

    by_child = {}
    for child, apt, vaccine in rows_query.all():
        # Filtered in Python rather than via a SQL DATE() function so the
        # same code behaves identically across MySQL (prod) and SQLite (tests).
        if apt.checked_in_at.date() != today:
            continue

        entry = by_child.get(child.child_id)
        if entry is None:
            entry = {
                'child_id': child.child_id,
                'first_name': child.first_name,
                'last_name': child.last_name,
                'guardian_name': child.guardian_name,
                'vaccines': [],
                'checked_in_at': apt.checked_in_at
            }
            by_child[child.child_id] = entry

        entry['vaccines'].append(vaccine.antigen_name)
        if apt.checked_in_at < entry['checked_in_at']:
            entry['checked_in_at'] = apt.checked_in_at

    queue = sorted(by_child.values(), key=lambda e: e['checked_in_at'])

    return jsonify({
        'status': 'ok',
        'queue': [
            {
                'child_id': e['child_id'],
                'first_name': e['first_name'],
                'last_name': e['last_name'],
                'guardian_name': e['guardian_name'],
                'vaccines': e['vaccines'],
                'checked_in_at': e['checked_in_at'].isoformat()
            }
            for e in queue
        ]
    }), 200
