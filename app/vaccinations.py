from datetime import date

from flask import Blueprint, request, render_template, redirect, url_for, flash, session

from app import db
from app.models import Child, Vaccine, Appointment, Vaccination
from app.auth import require_role, write_audit, row_to_dict

vaccinations_bp = Blueprint('vaccinations', __name__)


@vaccinations_bp.route('/vaccinations', methods=['GET'])
@require_role('immunisation_officer', 'admin')
def vaccination_form():
    """Show vaccination recording form."""
    child_id = request.args.get('child_id', type=int)
    appointment_id = request.args.get('appointment_id', type=int)

    if not child_id:
        return redirect(url_for('patients.search_children'))

    child = None
    appointment = None
    vaccine = None
    pending_appointments = []
    adverse_events = []

    if child_id:
        child = Child.query.get_or_404(child_id)
        pending_appointments = (
            Appointment.query
            .filter_by(child_id=child_id, status='pending')
            .join(Vaccine)
            .order_by(Appointment.scheduled_date)
            .all()
        )
        # Prior AEFI history for this child: decision support for the
        # clinician recording a new dose, not a block on doing so.
        adverse_events = (
            Vaccination.query
            .filter_by(child_id=child_id, adverse_event_reported=True)
            .all()
        )

    if appointment_id:
        appointment = Appointment.query.get(appointment_id)
        if appointment:
            vaccine = Vaccine.query.get(appointment.vaccine_id)
            child = Child.query.get(appointment.child_id)

    vaccines = {v.vaccine_id: v for v in Vaccine.query.all()}

    return render_template('record_vaccination.html',
                           child=child,
                           appointment=appointment,
                           vaccine=vaccine,
                           pending_appointments=pending_appointments,
                           vaccines=vaccines,
                           adverse_events=adverse_events)


@vaccinations_bp.route('/vaccinations', methods=['POST'])
@require_role('immunisation_officer', 'admin')
def record_vaccination():
    """Record a vaccination single transaction for all writes."""
    appointment_id = request.form.get('appointment_id', type=int)
    batch_number = request.form.get('batch_number', '').strip()
    date_given_str = request.form.get('date_given', '')

    if not all([appointment_id, batch_number, date_given_str]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('vaccinations.vaccination_form'))

    try:
        date_given = date.fromisoformat(date_given_str)
    except ValueError:
        flash('Invalid date format.', 'danger')
        return redirect(url_for('vaccinations.vaccination_form'))

    appointment = Appointment.query.get_or_404(appointment_id)
    vaccine = Vaccine.query.get(appointment.vaccine_id)
    child = Child.query.get(appointment.child_id)

    try:
        # 1. Insert Vaccination record
        vaccination = Vaccination(
            child_id=child.child_id,
            vaccine_id=vaccine.vaccine_id,
            appointment_id=appointment.appointment_id,
            dose_number=vaccine.dose_number,
            date_given=date_given,
            batch_number=batch_number,
            administered_by=session['user_id'],
            facility_id=session['facility_id']
        )
        db.session.add(vaccination)

        # 2. Full snapshot before mutation (Gap 10)
        old_apt_snapshot = row_to_dict(appointment)

        # 3. Update Appointment status
        appointment.status = 'completed'
        appointment.completed_date = date_given

        # 4. Flush to get vaccination_id
        db.session.flush()

        # 5. Audit log full row snapshots (Gap 10)
        write_audit(session['user_id'], 'INSERT', 'vaccinations', vaccination.vaccination_id,
                    old_value=None,
                    new_value=row_to_dict(vaccination))
        write_audit(session['user_id'], 'UPDATE', 'appointments', appointment.appointment_id,
                    old_value=old_apt_snapshot,
                    new_value=row_to_dict(appointment))

        # Single commit for entire transaction
        db.session.commit()

        flash(f'{vaccine.antigen_name} (Dose {vaccine.dose_number}) recorded for '
              f'{child.first_name} {child.last_name}.', 'success')
        return redirect(url_for('patients.view_child', child_id=child.child_id))

    except Exception as e:
        db.session.rollback()
        flash(f'Error recording vaccination: {str(e)}', 'danger')
        return redirect(url_for('vaccinations.vaccination_form',
                                child_id=child.child_id))


# ---------------------------------------------------------------------------
# Report an adverse event following immunisation (AEFI)
# ---------------------------------------------------------------------------
@vaccinations_bp.route('/vaccinations/<int:vaccination_id>/adverse-event', methods=['POST'])
@require_role('immunisation_officer', 'admin')
def report_adverse_event(vaccination_id):
    vaccination = Vaccination.query.get_or_404(vaccination_id)

    severity = request.form.get('severity', '')
    description = request.form.get('description', '').strip()

    if severity not in ('mild', 'moderate', 'severe'):
        flash('Please select a valid severity.', 'danger')
        return redirect(url_for('patients.view_child', child_id=vaccination.child_id))

    if not description:
        flash('A description of the adverse event is required.', 'danger')
        return redirect(url_for('patients.view_child', child_id=vaccination.child_id))

    old_snapshot = row_to_dict(vaccination)
    vaccination.adverse_event_reported = True
    vaccination.adverse_event_severity = severity
    vaccination.adverse_event_description = description
    vaccination.adverse_event_date = date.today()

    write_audit(session['user_id'], 'UPDATE', 'vaccinations', vaccination.vaccination_id,
                old_value=old_snapshot,
                new_value=row_to_dict(vaccination))
    db.session.commit()

    flash('Adverse event reported.', 'warning')
    return redirect(url_for('patients.view_child', child_id=vaccination.child_id))
