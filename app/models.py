from datetime import datetime, date
from app import db


class Facility(db.Model):
    __tablename__ = 'facilities'

    facility_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    facility_name = db.Column(db.String(200), nullable=False)
    lga = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)

    children = db.relationship('Child', backref='facility', lazy=True)
    users = db.relationship('User', backref='facility', lazy=True)


class Child(db.Model):
    __tablename__ = 'children'

    child_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    guardian_name = db.Column(db.String(200), nullable=False)
    guardian_phone = db.Column(db.String(20), nullable=False)
    guardian_email = db.Column(db.String(200), nullable=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.facility_id'), nullable=False)
    enrolment_date = db.Column(db.Date, nullable=False, default=date.today)

    rfid_tags = db.relationship('RFIDTag', backref='child', lazy=True)
    appointments = db.relationship('Appointment', backref='child', lazy=True)
    vaccinations = db.relationship('Vaccination', backref='child', lazy=True)
    medical_notes = db.relationship('MedicalNote', backref='child', lazy=True)


class RFIDTag(db.Model):
    __tablename__ = 'rfid_tags'

    tag_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    uid_hex = db.Column(db.String(20), unique=True, nullable=False)
    child_id = db.Column(db.Integer, db.ForeignKey('children.child_id'), nullable=False)
    issue_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.Enum('active', 'inactive', name='tag_status'), nullable=False, default='active')
    deactivation_reason = db.Column(db.String(255), nullable=True)
    replaced_by_tag_id = db.Column(db.Integer, db.ForeignKey('rfid_tags.tag_id'), nullable=True)

    replacement = db.relationship('RFIDTag', remote_side=[tag_id], uselist=False)


class Vaccine(db.Model):
    __tablename__ = 'vaccines'

    vaccine_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    antigen_name = db.Column(db.String(50), nullable=False)
    recommended_weeks = db.Column(db.Integer, nullable=False)
    dose_number = db.Column(db.Integer, nullable=False)
    schedule_notes = db.Column(db.String(255), nullable=True)

    appointments = db.relationship('Appointment', backref='vaccine', lazy=True)


class Appointment(db.Model):
    __tablename__ = 'appointments'

    appointment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    child_id = db.Column(db.Integer, db.ForeignKey('children.child_id'), nullable=False)
    vaccine_id = db.Column(db.Integer, db.ForeignKey('vaccines.vaccine_id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.Enum('pending', 'completed', 'overdue', name='appointment_status'), nullable=False, default='pending')
    completed_date = db.Column(db.Date, nullable=True)


class Vaccination(db.Model):
    __tablename__ = 'vaccinations'

    vaccination_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    child_id = db.Column(db.Integer, db.ForeignKey('children.child_id'), nullable=False)
    vaccine_id = db.Column(db.Integer, db.ForeignKey('vaccines.vaccine_id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.appointment_id'), nullable=False)
    dose_number = db.Column(db.Integer, nullable=False)
    date_given = db.Column(db.Date, nullable=False)
    batch_number = db.Column(db.String(50), nullable=False)
    administered_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.facility_id'), nullable=False)

    appointment = db.relationship('Appointment', backref='vaccination', uselist=False)
    administrator = db.relationship('User', backref='vaccinations_given')
    vaccination_facility = db.relationship('Facility', backref='vaccinations_done')


class MedicalNote(db.Model):
    __tablename__ = 'medical_notes'

    note_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    child_id = db.Column(db.Integer, db.ForeignKey('children.child_id'), nullable=False)
    note_text = db.Column(db.Text, nullable=False)
    note_date = db.Column(db.Date, nullable=False, default=date.today)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)

    recorder = db.relationship('User', backref='medical_notes_recorded')


class User(db.Model):
    __tablename__ = 'users'

    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.Enum('admin', 'immunisation_officer', 'data_entry_clerk', name='user_role'), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.facility_id'), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)


class AuditLog(db.Model):
    __tablename__ = 'audit_log'

    log_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)
    action_type = db.Column(db.Enum('INSERT', 'UPDATE', 'DELETE', name='audit_action'), nullable=False)
    table_affected = db.Column(db.String(100), nullable=False)
    record_id = db.Column(db.Integer, nullable=False)
    old_value = db.Column(db.JSON, nullable=True)
    new_value = db.Column(db.JSON, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship('User', backref='audit_logs')
