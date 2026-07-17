from datetime import date, timedelta

from flask import Blueprint, request, render_template, redirect, url_for, flash, session

from app import db
from app.models import Child, RFIDTag, Appointment, Vaccine, MedicalNote, Facility
from app.auth import require_role, login_required, write_audit, row_to_dict

patients_bp = Blueprint('patients', __name__)


# ---------------------------------------------------------------------------
# NPI scheduling engine
# ---------------------------------------------------------------------------
def generate_appointments(child):
    """Auto-generate NPI appointments for a newly enrolled child.

    Safe to call on an existing child skips any vaccine where an appointment
    already exists for that child, and never touches completed appointments.
    """
    vaccines = Vaccine.query.all()
    for vaccine in vaccines:
        # Gap 9: skip if an appointment already exists for this child/vaccine pair
        existing = Appointment.query.filter_by(
            child_id=child.child_id,
            vaccine_id=vaccine.vaccine_id
        ).first()
        if existing:
            continue

        raw_date = child.date_of_birth + timedelta(weeks=vaccine.recommended_weeks)
        # Weekend adjustment: Saturday +2 days → Monday, Sunday +1 day → Monday
        if raw_date.weekday() == 5:
            scheduled_date = raw_date + timedelta(days=2)
        elif raw_date.weekday() == 6:
            scheduled_date = raw_date + timedelta(days=1)
        else:
            scheduled_date = raw_date

        appointment = Appointment(
            child_id=child.child_id,
            vaccine_id=vaccine.vaccine_id,
            scheduled_date=scheduled_date,
            status='pending'
        )
        db.session.add(appointment)


# ---------------------------------------------------------------------------
# Register new child
# ---------------------------------------------------------------------------
@patients_bp.route('/children', methods=['GET', 'POST'])
@require_role('data_entry_clerk', 'admin')
def register_child():
    if request.method == 'GET':
        facilities = Facility.query.all()
        scanned_uid = request.args.get('scanned_uid', '').strip().upper()
        return render_template('register_child.html', facilities=facilities, scanned_uid=scanned_uid)

    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    date_of_birth = request.form.get('date_of_birth', '')
    gender = request.form.get('gender', '')
    guardian_name = request.form.get('guardian_name', '').strip()
    guardian_phone = request.form.get('guardian_phone', '').strip()
    guardian_email = request.form.get('guardian_email', '').strip() or None
    facility_id = request.form.get('facility_id', type=int) or session.get('facility_id')

    if not all([first_name, last_name, date_of_birth, gender, guardian_name, guardian_phone]):
        flash('All required fields must be filled.', 'danger')
        return redirect(url_for('patients.register_child'))

    try:
        dob = date.fromisoformat(date_of_birth)
    except ValueError:
        flash('Invalid date format.', 'danger')
        return redirect(url_for('patients.register_child'))

    child = Child(
        first_name=first_name,
        last_name=last_name,
        date_of_birth=dob,
        gender=gender,
        guardian_name=guardian_name,
        guardian_phone=guardian_phone,
        guardian_email=guardian_email,
        facility_id=facility_id,
        enrolment_date=date.today()
    )
    db.session.add(child)
    db.session.flush()  # get child_id before audit

    # Gap 10: full row snapshot
    write_audit(session['user_id'], 'INSERT', 'children', child.child_id,
                old_value=None,
                new_value=row_to_dict(child))

    generate_appointments(child)

    # Optional RFID assignment at registration time. If the UID is a duplicate
    # we still commit the child+appointments and redirect to the assign-rfid
    # page so the clerk can supply a different card without losing the registration.
    uid_hex = request.form.get('uid_hex', '').strip().upper()
    rfid_conflict = False
    if uid_hex:
        existing_tag = RFIDTag.query.filter_by(uid_hex=uid_hex).first()
        if existing_tag:
            rfid_conflict = True
        else:
            tag = RFIDTag(
                uid_hex=uid_hex,
                child_id=child.child_id,
                issue_date=date.today(),
                status='active'
            )
            db.session.add(tag)
            db.session.flush()
            write_audit(session['user_id'], 'INSERT', 'rfid_tags', tag.tag_id,
                        old_value=None,
                        new_value=row_to_dict(tag))

    db.session.commit()

    if rfid_conflict:
        flash(f'Child "{first_name} {last_name}" registered, but RFID card {uid_hex} '
              f'is already assigned elsewhere. Assign a different card below.', 'warning')
        return redirect(url_for('patients.assign_rfid', child_id=child.child_id))

    flash(f'Child "{first_name} {last_name}" registered. Appointments generated.', 'success')
    return redirect(url_for('patients.view_child', child_id=child.child_id))


# ---------------------------------------------------------------------------
# Update child demographics
# ---------------------------------------------------------------------------
@patients_bp.route('/children/<int:child_id>/edit', methods=['GET', 'POST'])
@require_role('data_entry_clerk', 'admin')
def edit_child(child_id):
    child = Child.query.get_or_404(child_id)

    if request.method == 'GET':
        facilities = Facility.query.all()
        return render_template('edit_child.html', child=child, facilities=facilities)

    # Gap 10: capture full row before mutation
    old_snapshot = row_to_dict(child)

    child.first_name = request.form.get('first_name', child.first_name).strip()
    child.last_name = request.form.get('last_name', child.last_name).strip()
    child.guardian_name = request.form.get('guardian_name', child.guardian_name).strip()
    child.guardian_phone = request.form.get('guardian_phone', child.guardian_phone).strip()
    child.guardian_email = request.form.get('guardian_email', '').strip() or None

    write_audit(session['user_id'], 'UPDATE', 'children', child.child_id,
                old_value=old_snapshot,
                new_value=row_to_dict(child))
    db.session.commit()

    flash('Child record updated.', 'success')
    return redirect(url_for('patients.view_child', child_id=child.child_id))


# ---------------------------------------------------------------------------
# View child record
# ---------------------------------------------------------------------------
@patients_bp.route('/children/<int:child_id>')
@login_required
def view_child(child_id):
    child = Child.query.get_or_404(child_id)
    appointments = (
        Appointment.query
        .filter_by(child_id=child_id)
        .join(Vaccine)
        .order_by(Appointment.scheduled_date)
        .all()
    )
    rfid_tags = RFIDTag.query.filter_by(child_id=child_id).all()
    notes = MedicalNote.query.filter_by(child_id=child_id).order_by(MedicalNote.note_date.desc()).all()
    vaccines = {v.vaccine_id: v for v in Vaccine.query.all()}
    today = date.today()

    return render_template('view_child.html',
                           child=child,
                           appointments=appointments,
                           rfid_tags=rfid_tags,
                           notes=notes,
                           vaccines=vaccines,
                           today=today,
                           timedelta=timedelta)


# ---------------------------------------------------------------------------
# Search children
# ---------------------------------------------------------------------------
@patients_bp.route('/children/search')
@login_required
def search_children():
    q = request.args.get('q', '').strip()
    children = []
    if q:
        uid_child_ids = [
            tag.child_id for tag in
            RFIDTag.query.filter(RFIDTag.uid_hex.ilike(f'%{q.upper()}%')).all()
        ]
        children = Child.query.filter(
            db.or_(
                Child.first_name.ilike(f'%{q}%'),
                Child.last_name.ilike(f'%{q}%'),
                Child.guardian_name.ilike(f'%{q}%'),
                Child.guardian_phone.ilike(f'%{q}%'),
                Child.child_id.in_(uid_child_ids)
            )
        ).all()
    return render_template('search_children.html', children=children, query=q)


# ---------------------------------------------------------------------------
# Assign RFID tag
# ---------------------------------------------------------------------------
@patients_bp.route('/children/<int:child_id>/assign-rfid', methods=['GET', 'POST'])
@require_role('data_entry_clerk', 'admin')
def assign_rfid(child_id):
    child = Child.query.get_or_404(child_id)

    if request.method == 'GET':
        return render_template('assign_rfid.html', child=child)

    uid_hex = request.form.get('uid_hex', '').strip().upper()
    if not uid_hex:
        flash('RFID UID is required.', 'danger')
        return redirect(url_for('patients.assign_rfid', child_id=child_id))

    # Check if UID is already registered globally
    existing_uid = RFIDTag.query.filter_by(uid_hex=uid_hex).first()
    if existing_uid:
        flash('This RFID UID is already assigned to another record.', 'danger')
        return redirect(url_for('patients.assign_rfid', child_id=child_id))

    # Gap 12: enforce one active tag per child deactivate any existing active tag
    active_tag = RFIDTag.query.filter_by(child_id=child_id, status='active').first()
    if active_tag:
        old_tag_snapshot = row_to_dict(active_tag)
        active_tag.status = 'inactive'
        active_tag.deactivation_reason = f'Superseded by new card {uid_hex}'
        write_audit(session['user_id'], 'UPDATE', 'rfid_tags', active_tag.tag_id,
                    old_value=old_tag_snapshot,
                    new_value=row_to_dict(active_tag))

    tag = RFIDTag(
        uid_hex=uid_hex,
        child_id=child.child_id,
        issue_date=date.today(),
        status='active'
    )
    db.session.add(tag)
    db.session.flush()

    # Gap 10: full row snapshot
    write_audit(session['user_id'], 'INSERT', 'rfid_tags', tag.tag_id,
                old_value=None,
                new_value=row_to_dict(tag))
    db.session.commit()

    flash(f'RFID card {uid_hex} assigned to {child.first_name} {child.last_name}.', 'success')
    return redirect(url_for('patients.view_child', child_id=child_id))


# ---------------------------------------------------------------------------
# RFID card management deactivate / replace
# Gap 3: Data Entry Clerk (+ admin) handles card recovery, not Officer
# ---------------------------------------------------------------------------
@patients_bp.route('/rfid/<int:tag_id>/deactivate', methods=['POST'])
@require_role('data_entry_clerk', 'admin')
def deactivate_rfid(tag_id):
    tag = RFIDTag.query.get_or_404(tag_id)
    reason = request.form.get('reason', 'Not specified')

    # Gap 10: full row snapshot before mutation
    old_snapshot = row_to_dict(tag)
    tag.status = 'inactive'
    tag.deactivation_reason = reason

    write_audit(session['user_id'], 'UPDATE', 'rfid_tags', tag.tag_id,
                old_value=old_snapshot,
                new_value=row_to_dict(tag))
    db.session.commit()

    flash(f'RFID card {tag.uid_hex} deactivated.', 'success')
    return redirect(url_for('patients.view_child', child_id=tag.child_id))


@patients_bp.route('/rfid/<int:tag_id>/replace', methods=['POST'])
@require_role('data_entry_clerk', 'admin')
def replace_rfid(tag_id):
    old_tag = RFIDTag.query.get_or_404(tag_id)
    new_uid = request.form.get('new_uid_hex', '').strip().upper()
    reason = request.form.get('reason', 'Card replacement')

    if not new_uid:
        flash('New RFID UID is required.', 'danger')
        return redirect(url_for('patients.view_child', child_id=old_tag.child_id))

    existing = RFIDTag.query.filter_by(uid_hex=new_uid).first()
    if existing:
        flash('This RFID UID is already in use.', 'danger')
        return redirect(url_for('patients.view_child', child_id=old_tag.child_id))

    # Gap 10: full row snapshot of old tag before mutation
    old_tag_snapshot = row_to_dict(old_tag)
    old_tag.status = 'inactive'
    old_tag.deactivation_reason = reason

    new_tag = RFIDTag(
        uid_hex=new_uid,
        child_id=old_tag.child_id,
        issue_date=date.today(),
        status='active'
    )
    db.session.add(new_tag)
    db.session.flush()

    old_tag.replaced_by_tag_id = new_tag.tag_id

    write_audit(session['user_id'], 'UPDATE', 'rfid_tags', old_tag.tag_id,
                old_value=old_tag_snapshot,
                new_value=row_to_dict(old_tag))
    write_audit(session['user_id'], 'INSERT', 'rfid_tags', new_tag.tag_id,
                old_value=None,
                new_value=row_to_dict(new_tag))
    db.session.commit()

    flash(f'Card replaced. Old: {old_tag.uid_hex} → New: {new_uid}.', 'success')
    return redirect(url_for('patients.view_child', child_id=old_tag.child_id))


# ---------------------------------------------------------------------------
# Add medical note
# ---------------------------------------------------------------------------
@patients_bp.route('/children/<int:child_id>/notes', methods=['POST'])
@require_role('immunisation_officer', 'admin')
def add_note(child_id):
    child = Child.query.get_or_404(child_id)
    note_text = request.form.get('note_text', '').strip()

    if not note_text:
        flash('Note text is required.', 'danger')
        return redirect(url_for('patients.view_child', child_id=child_id))

    note = MedicalNote(
        child_id=child.child_id,
        note_text=note_text,
        note_date=date.today(),
        recorded_by=session['user_id']
    )
    db.session.add(note)
    db.session.flush()

    # Gap 10: full row snapshot
    write_audit(session['user_id'], 'INSERT', 'medical_notes', note.note_id,
                old_value=None,
                new_value=row_to_dict(note))
    db.session.commit()

    flash('Medical note added.', 'success')
    return redirect(url_for('patients.view_child', child_id=child_id))


# ---------------------------------------------------------------------------
# Flag defaulter
# Gap 2 + 15: appointment status is now 'overdue', not 'missed'
# ---------------------------------------------------------------------------
@patients_bp.route('/children/<int:child_id>/flag-defaulter', methods=['POST'])
@require_role('immunisation_officer', 'admin')
def flag_defaulter(child_id):
    child = Child.query.get_or_404(child_id)
    today = date.today()

    overdue_appointments = Appointment.query.filter(
        Appointment.child_id == child_id,
        Appointment.status == 'pending',
        Appointment.scheduled_date < today
    ).all()

    count = 0
    for apt in overdue_appointments:
        old_snapshot = row_to_dict(apt)
        apt.status = 'overdue'
        # Gap 10: full row snapshot per appointment
        write_audit(session['user_id'], 'UPDATE', 'appointments', apt.appointment_id,
                    old_value=old_snapshot,
                    new_value=row_to_dict(apt))
        count += 1

    db.session.commit()

    flash(f'{count} overdue appointment(s) flagged for {child.first_name} {child.last_name}.', 'warning')
    return redirect(url_for('patients.view_child', child_id=child_id))


# ---------------------------------------------------------------------------
# RFID card lookup (web-based, for data entry clerk)
# ---------------------------------------------------------------------------
@patients_bp.route('/rfid/lookup', methods=['GET', 'POST'])
@require_role('data_entry_clerk', 'admin', 'immunisation_officer')
def rfid_lookup():
    uid = ''
    if request.method == 'POST':
        uid = request.form.get('uid_hex', '').strip().upper()
        if not uid:
            flash('Please enter a card UID.', 'warning')
            return render_template('rfid_lookup.html', uid='')
        tag = RFIDTag.query.filter_by(uid_hex=uid).first()
        if tag:
            return redirect(url_for('patients.view_child', child_id=tag.child_id))
        flash(f'No child record is linked to card UID: {uid}', 'warning')
    return render_template('rfid_lookup.html', uid=uid)


# ---------------------------------------------------------------------------
# Reschedule an appointment (data entry clerk + admin)
# ---------------------------------------------------------------------------
@patients_bp.route('/appointments/<int:appointment_id>/reschedule', methods=['POST'])
@require_role('data_entry_clerk', 'admin')
def reschedule_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    new_date_str = request.form.get('new_date', '')

    try:
        new_date = date.fromisoformat(new_date_str)
    except ValueError:
        flash('Invalid date format.', 'danger')
        return redirect(url_for('patients.view_child', child_id=appointment.child_id))

    # Weekend adjustment
    if new_date.weekday() == 5:
        new_date = new_date + timedelta(days=2)
    elif new_date.weekday() == 6:
        new_date = new_date + timedelta(days=1)

    old_snapshot = row_to_dict(appointment)
    appointment.scheduled_date = new_date
    if appointment.status == 'overdue':
        appointment.status = 'pending'

    write_audit(session['user_id'], 'UPDATE', 'appointments', appointment.appointment_id,
                old_value=old_snapshot,
                new_value=row_to_dict(appointment))
    db.session.commit()

    flash(f'Appointment rescheduled to {new_date.strftime("%d %B %Y")}.', 'success')
    return redirect(url_for('patients.view_child', child_id=appointment.child_id))
