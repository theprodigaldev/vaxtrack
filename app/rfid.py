import threading
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, current_app, session

from app import db
from app.models import RFIDTag, Child, Appointment, Vaccine
from app.auth import login_required, require_role

rfid_bp = Blueprint('rfid', __name__)

# Per-facility scan buffer — keyed by facility_id so multi-facility works
_scan_lock = threading.Lock()
_latest_scans = {}  # {facility_id: {'data': dict, 'acked': bool}}

# Global single-slot buffer for unknown-UID scans. No facility can be derived
# when the UID has no matching tag, so this is not facility-scoped.
# Guarded by the same _scan_lock for simplicity.
_latest_unregistered_scan = {'data': None, 'acked': True}


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
        # No child is linked to this UID — push to the global unregistered buffer
        # so a clerk on the dashboard or registration page can capture it.
        payload = {'status': 'unknown', 'uid_hex': uid}
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
        }
    }

    # Push into scan buffer — dashboard JS will pick this up within 2-3 seconds
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
    Not scoped by facility — any authorised clerk sees the same pending scan,
    since there is no child record to derive a facility from.
    """
    with _scan_lock:
        if _latest_unregistered_scan['acked']:
            return jsonify({'status': 'idle'}), 200
        _latest_unregistered_scan['acked'] = True
        return jsonify(_latest_unregistered_scan['data']), 200
