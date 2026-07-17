import csv
import io
from datetime import date

from flask import Blueprint, request, render_template, Response, session

from app import db
from app.models import Child, Vaccine, Appointment, Vaccination, Facility
from app.auth import require_role

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/reports/coverage')
@require_role('admin')
def coverage_report():
    """Per-antigen coverage rates."""
    vaccines = Vaccine.query.order_by(Vaccine.recommended_weeks, Vaccine.dose_number).all()
    total_children = Child.query.count()

    coverage = []
    for v in vaccines:
        vaccinated = Vaccination.query.filter_by(vaccine_id=v.vaccine_id).count()
        rate = round((vaccinated / total_children * 100), 2) if total_children > 0 else 0.0
        coverage.append({
            'antigen': v.antigen_name,
            'dose': v.dose_number,
            'vaccinated': vaccinated,
            'total': total_children,
            'rate': rate
        })

    export = request.args.get('export')
    if export == 'csv':
        return _export_csv(
            'coverage_report.csv',
            ['Antigen', 'Dose', 'Vaccinated', 'Total Children', 'Coverage %'],
            [[c['antigen'], c['dose'], c['vaccinated'], c['total'], c['rate']] for c in coverage]
        )

    return render_template('reports_coverage.html', coverage=coverage, total_children=total_children)


@reports_bp.route('/reports/defaulters')
@require_role('admin')
def defaulters_report():
    """Children with at least one overdue pending appointment."""
    today = date.today()

    overdue_appointments = (
        db.session.query(
            Child.child_id,
            Child.first_name,
            Child.last_name,
            Child.guardian_name,
            Child.guardian_phone,
            Facility.facility_name,
            db.func.count(Appointment.appointment_id).label('overdue_count')
        )
        .join(Appointment, Appointment.child_id == Child.child_id)
        .join(Facility, Facility.facility_id == Child.facility_id)
        .filter(Appointment.status == 'pending')
        .filter(Appointment.scheduled_date < today)
        .group_by(Child.child_id, Facility.facility_name)
        .order_by(db.desc('overdue_count'))
        .all()
    )

    export = request.args.get('export')
    if export == 'csv':
        return _export_csv(
            'defaulters_report.csv',
            ['Child ID', 'First Name', 'Last Name', 'Guardian', 'Phone', 'Facility', 'Overdue Count'],
            [[d.child_id, d.first_name, d.last_name, d.guardian_name,
              d.guardian_phone, d.facility_name, d.overdue_count] for d in overdue_appointments]
        )

    return render_template('reports_defaulters.html', defaulters=overdue_appointments)


@reports_bp.route('/reports/facility')
@require_role('admin')
def facility_report():
    """Facility-level summary statistics."""
    facilities = Facility.query.all()
    stats = []

    for f in facilities:
        enrolled = Child.query.filter_by(facility_id=f.facility_id).count()
        total_appointments = (
            Appointment.query
            .join(Child)
            .filter(Child.facility_id == f.facility_id)
            .count()
        )
        completed = (
            Appointment.query
            .join(Child)
            .filter(Child.facility_id == f.facility_id, Appointment.status == 'completed')
            .count()
        )
        pending = (
            Appointment.query
            .join(Child)
            .filter(Child.facility_id == f.facility_id, Appointment.status == 'pending')
            .count()
        )
        missed = (
            Appointment.query
            .join(Child)
            .filter(Child.facility_id == f.facility_id, Appointment.status == 'overdue')
            .count()
        )
        completion_rate = round((completed / total_appointments * 100), 2) if total_appointments > 0 else 0.0

        stats.append({
            'facility_name': f.facility_name,
            'lga': f.lga,
            'enrolled': enrolled,
            'total_appointments': total_appointments,
            'completed': completed,
            'pending': pending,
            'missed': missed,
            'completion_rate': completion_rate
        })

    export = request.args.get('export')
    if export == 'csv':
        return _export_csv(
            'facility_report.csv',
            ['Facility', 'LGA', 'Enrolled', 'Total Appts', 'Completed', 'Pending', 'Missed', 'Completion %'],
            [[s['facility_name'], s['lga'], s['enrolled'], s['total_appointments'],
              s['completed'], s['pending'], s['missed'], s['completion_rate']] for s in stats]
        )

    return render_template('reports_facility.html', stats=stats)


def _export_csv(filename, headers, rows):
    """Generate a CSV file response."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
