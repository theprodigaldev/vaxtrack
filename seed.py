"""
Seed script populates the database with test data.
Run: python seed.py
"""
from datetime import date, timedelta
import bcrypt

from app import create_app, db
from app.models import Facility, User, Vaccine, Child, RFIDTag, Vaccination, Appointment
from app.patients import generate_appointments


def hash_pw(plain):
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        # Skip if already seeded
        if Facility.query.first():
            print("Database already seeded. Skipping.")
            return

        # ---- Facilities (3 Lagos PHCs) ----
        facilities = [
            Facility(facility_name='Surulere PHC', lga='Surulere', state='Lagos'),
            Facility(facility_name='Ikeja General PHC', lga='Ikeja', state='Lagos'),
            Facility(facility_name='Eti-Osa PHC', lga='Eti-Osa', state='Lagos'),
        ]
        db.session.add_all(facilities)
        db.session.flush()

        # ---- Users (one per role) ----
        users = [
            User(username='admin', password_hash=hash_pw('admin123'),
                 full_name='Adebayo Ogundimu', role='admin',
                 facility_id=facilities[0].facility_id, is_active=True),
            User(username='nurse_ada', password_hash=hash_pw('nurse123'),
                 full_name='Ada Nwosu', role='immunisation_officer',
                 facility_id=facilities[0].facility_id, is_active=True),
            User(username='clerk_bola', password_hash=hash_pw('clerk123'),
                 full_name='Bola Adeyemi', role='data_entry_clerk',
                 facility_id=facilities[1].facility_id, is_active=True),
        ]
        db.session.add_all(users)
        db.session.flush()

        # ---- NPI Vaccine Schedule ----
        vaccines = [
            # Birth doses (week 0)
            Vaccine(antigen_name='BCG', recommended_weeks=0, dose_number=1, schedule_notes='At birth'),
            Vaccine(antigen_name='OPV-0', recommended_weeks=0, dose_number=0, schedule_notes='At birth'),
            Vaccine(antigen_name='HBV-0', recommended_weeks=0, dose_number=0, schedule_notes='At birth, within 24h'),
            # 6 weeks
            Vaccine(antigen_name='OPV-1', recommended_weeks=6, dose_number=1, schedule_notes='6 weeks'),
            Vaccine(antigen_name='Penta-1', recommended_weeks=6, dose_number=1, schedule_notes='6 weeks'),
            Vaccine(antigen_name='PCV-1', recommended_weeks=6, dose_number=1, schedule_notes='6 weeks'),
            Vaccine(antigen_name='Rota-1', recommended_weeks=6, dose_number=1, schedule_notes='6 weeks'),
            # 10 weeks
            Vaccine(antigen_name='OPV-2', recommended_weeks=10, dose_number=2, schedule_notes='10 weeks'),
            Vaccine(antigen_name='Penta-2', recommended_weeks=10, dose_number=2, schedule_notes='10 weeks'),
            Vaccine(antigen_name='PCV-2', recommended_weeks=10, dose_number=2, schedule_notes='10 weeks'),
            Vaccine(antigen_name='Rota-2', recommended_weeks=10, dose_number=2, schedule_notes='10 weeks'),
            # 14 weeks
            Vaccine(antigen_name='OPV-3', recommended_weeks=14, dose_number=3, schedule_notes='14 weeks'),
            Vaccine(antigen_name='Penta-3', recommended_weeks=14, dose_number=3, schedule_notes='14 weeks'),
            Vaccine(antigen_name='PCV-3', recommended_weeks=14, dose_number=3, schedule_notes='14 weeks'),
            Vaccine(antigen_name='IPV', recommended_weeks=14, dose_number=1, schedule_notes='14 weeks'),
            # 6 months
            Vaccine(antigen_name='Vitamin A-1', recommended_weeks=26, dose_number=1, schedule_notes='6 months'),
            # 9 months
            Vaccine(antigen_name='Measles-1', recommended_weeks=39, dose_number=1, schedule_notes='9 months'),
            Vaccine(antigen_name='Yellow Fever', recommended_weeks=39, dose_number=1, schedule_notes='9 months'),
            # 12 months
            Vaccine(antigen_name='Meningitis A', recommended_weeks=52, dose_number=1, schedule_notes='12 months'),
            Vaccine(antigen_name='Measles-2', recommended_weeks=65, dose_number=2, schedule_notes='15 months'),
        ]
        db.session.add_all(vaccines)
        db.session.flush()

        # ---- 20 Synthetic Children ----
        # DOBs chosen to exercise weekend adjustment edge cases
        children_data = [
            ('Chidera', 'Okafor', date(2025, 6, 14), 'Male', 'Grace Okafor', '+2348012345001', 'grace.okafor@mail.com'),      # Sat DOB
            ('Amina', 'Bello', date(2025, 6, 15), 'Female', 'Fatima Bello', '+2348012345002', 'fatima.bello@mail.com'),        # Sun DOB
            ('Emeka', 'Nwankwo', date(2025, 3, 10), 'Male', 'Ngozi Nwankwo', '+2348012345003', None),                          # Mon DOB
            ('Aisha', 'Abdullahi', date(2025, 4, 4), 'Female', 'Halima Abdullahi', '+2348012345004', None),                     # Fri DOB
            ('Olumide', 'Adeyemi', date(2025, 5, 3), 'Male', 'Shade Adeyemi', '+2348012345005', 'shade.a@mail.com'),           # Sat DOB
            ('Zainab', 'Ibrahim', date(2025, 7, 20), 'Female', 'Maryam Ibrahim', '+2348012345006', None),                       # Sun DOB
            ('Chukwuma', 'Eze', date(2025, 1, 15), 'Male', 'Nneka Eze', '+2348012345007', 'nneka.eze@mail.com'),
            ('Folake', 'Ogunleye', date(2025, 2, 28), 'Female', 'Biola Ogunleye', '+2348012345008', None),
            ('Tunde', 'Bakare', date(2025, 8, 12), 'Male', 'Funke Bakare', '+2348012345009', None),
            ('Ifeoma', 'Chukwu', date(2025, 9, 1), 'Female', 'Adaeze Chukwu', '+2348012345010', 'adaeze@mail.com'),
            ('Yusuf', 'Mohammed', date(2025, 3, 22), 'Male', 'Amina Mohammed', '+2348012345011', None),                        # Sat DOB
            ('Blessing', 'Okoro', date(2025, 4, 13), 'Female', 'Joy Okoro', '+2348012345012', 'joy.okoro@mail.com'),           # Sun DOB
            ('Damilola', 'Afolabi', date(2025, 5, 19), 'Male', 'Kemi Afolabi', '+2348012345013', None),
            ('Hadiza', 'Usman', date(2025, 6, 7), 'Female', 'Rabi Usman', '+2348012345014', None),                             # Sat DOB
            ('Obinna', 'Igwe', date(2025, 7, 1), 'Male', 'Chioma Igwe', '+2348012345015', 'chioma.igwe@mail.com'),
            ('Sade', 'Olatunji', date(2025, 8, 24), 'Female', 'Nike Olatunji', '+2348012345016', None),                        # Sun DOB
            ('Kelechi', 'Onyema', date(2025, 10, 6), 'Male', 'Uju Onyema', '+2348012345017', None),
            ('Fatimah', 'Lawal', date(2025, 11, 14), 'Female', 'Aminat Lawal', '+2348012345018', 'aminat@mail.com'),
            ('Adamu', 'Garba', date(2025, 12, 25), 'Male', 'Hassana Garba', '+2348012345019', None),                           # Thu DOB (Christmas)
            ('Ngozi', 'Obi', date(2026, 1, 4), 'Female', 'Ebere Obi', '+2348012345020', 'ebere.obi@mail.com'),                 # Sun DOB
        ]

        children = []
        for i, (fn, ln, dob, g, gn, gp, ge) in enumerate(children_data):
            fac = facilities[i % 3]
            child = Child(
                first_name=fn, last_name=ln, date_of_birth=dob, gender=g,
                guardian_name=gn, guardian_phone=gp, guardian_email=ge,
                facility_id=fac.facility_id, enrolment_date=dob
            )
            db.session.add(child)
            db.session.flush()
            generate_appointments(child)
            children.append(child)

        db.session.flush()

        # ---- 5 RFID Cards ----
        rfid_uids = ['A1B2C3D4', 'E5F6A7B8', 'C9D0E1F2', '11223344', 'AABBCCDD']
        for i, uid in enumerate(rfid_uids):
            tag = RFIDTag(
                uid_hex=uid,
                child_id=children[i].child_id,
                issue_date=children[i].enrolment_date,
                status='active'
            )
            db.session.add(tag)

        db.session.flush()

        # ---- 30 Vaccination Records ----
        # Vaccinate first 5 children with birth doses (BCG, OPV-0, HBV-0)
        # and first 3 children with 6-week doses
        nurse = users[1]  # immunisation officer
        vax_count = 0

        for i in range(5):
            child = children[i]
            # Birth doses: vaccine_id 1,2,3 (BCG, OPV-0, HBV-0)
            for v_offset in range(3):
                vaccine = vaccines[v_offset]
                apt = Appointment.query.filter_by(
                    child_id=child.child_id,
                    vaccine_id=vaccine.vaccine_id
                ).first()
                if apt:
                    vax = Vaccination(
                        child_id=child.child_id,
                        vaccine_id=vaccine.vaccine_id,
                        appointment_id=apt.appointment_id,
                        dose_number=vaccine.dose_number,
                        date_given=child.date_of_birth,
                        batch_number=f'BATCH-2025-{vax_count + 1:03d}',
                        administered_by=nurse.user_id,
                        facility_id=child.facility_id
                    )
                    apt.status = 'completed'
                    apt.completed_date = child.date_of_birth
                    db.session.add(vax)
                    vax_count += 1

        # 6-week doses for first 3 children
        for i in range(3):
            child = children[i]
            six_week_date = child.date_of_birth + timedelta(weeks=6)
            # vaccine_id 4,5,6,7 (OPV-1, Penta-1, PCV-1, Rota-1)
            for v_offset in range(3, 7):
                vaccine = vaccines[v_offset]
                apt = Appointment.query.filter_by(
                    child_id=child.child_id,
                    vaccine_id=vaccine.vaccine_id
                ).first()
                if apt:
                    vax = Vaccination(
                        child_id=child.child_id,
                        vaccine_id=vaccine.vaccine_id,
                        appointment_id=apt.appointment_id,
                        dose_number=vaccine.dose_number,
                        date_given=six_week_date,
                        batch_number=f'BATCH-2025-{vax_count + 1:03d}',
                        administered_by=nurse.user_id,
                        facility_id=child.facility_id
                    )
                    apt.status = 'completed'
                    apt.completed_date = six_week_date
                    db.session.add(vax)
                    vax_count += 1

        db.session.commit()
        print(f"Seed complete: 3 facilities, 3 users, {len(vaccines)} vaccines, "
              f"{len(children)} children, 5 RFID cards, {vax_count} vaccinations.")
        print("\nLogin credentials:")
        print("  admin / admin123       (System Administrator)")
        print("  nurse_ada / nurse123   (Immunisation Officer)")
        print("  clerk_bola / clerk123  (Data Entry Clerk)")


if __name__ == '__main__':
    seed()
