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

    if child_id:
        child = Child.query.get_or_404(child_id)
        pending_appointments = (
            Appointment.query
            .filter_by(child_id=child_id, status='pending')
            .join(Vaccine)
            .order_by(Appointment.scheduled_date)
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
                           vaccines=vaccines)


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
