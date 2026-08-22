"""One-off renderer for visual QA. Not part of the app runtime."""
import os
import sys
from datetime import date
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db as _db
from app.auth import auth_bp
from app.patients import patients_bp
from app.rfid import rfid_bp
from app.vaccinations import vaccinations_bp
from app.reports import reports_bp
from app.models import Facility, Child

OUT = ROOT / 'scripts' / '_ui_shots'
OUT.mkdir(exist_ok=True)

app = Flask(
    'vaxtrack_shot',
    template_folder=str(ROOT / 'app' / 'templates'),
    static_folder=str(ROOT / 'app' / 'static'),
    static_url_path='/static',
)
app.config.update(
    TESTING=True,
    SECRET_KEY='shot-secret',
    SQLALCHEMY_DATABASE_URI='sqlite:///' + str(OUT / 'shot.db').replace('\\', '/'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    ESP32_AUTH_TOKEN='x',
    ACS_CONNECTION_STRING='',
    MAIL_SENDER='',
    APP_BASE_URL='',
    EBULKSMS_USERNAME='',
    EBULKSMS_API_KEY='',
    EBULKSMS_SENDER='VAXTRACK',
    EBULKSMS_DND_SENDER='true',
)
_db.init_app(app)
app.register_blueprint(auth_bp)
app.register_blueprint(patients_bp)
app.register_blueprint(rfid_bp)
app.register_blueprint(vaccinations_bp)
app.register_blueprint(reports_bp)

with app.app_context():
    _db.drop_all()
    _db.create_all()
    fac = Facility(facility_name='Surulere PHC', lga='Surulere', state='Lagos')
    _db.session.add(fac)
    _db.session.flush()
    for i, (fn, ln, g) in enumerate((
        ('Amina', 'Bello', 'female'),
        ('Chinedu', 'Okafor', 'male'),
        ('Fatima', 'Yusuf', 'female'),
        ('Tunde', 'Adeyemi', 'male'),
    ), start=1):
        _db.session.add(Child(
            first_name=fn, last_name=ln, date_of_birth=date(2024, i, 8),
            gender=g, guardian_name=f'{ln} Guardian', guardian_phone=f'+234801000000{i}',
            facility_id=fac.facility_id, enrolment_date=date(2024, 3, 1),
        ))
    _db.session.commit()
    facility_id = fac.facility_id

client = app.test_client()

def save(name, response):
    html = response.get_data(as_text=True)
    css = (ROOT / 'app' / 'static' / 'style.css').as_uri()
    html = html.replace('href="/static/style.css"', f'href="{css}"')
    html = html.replace("url_for('static', filename='style.css')", '')
    path = OUT / f'{name}.html'
    path.write_text(html, encoding='utf-8')
    print('wrote', path, 'status', response.status_code)

save('login', client.get('/login'))

with client.session_transaction() as sess:
    sess['user_id'] = 1
    sess['username'] = 'clerk'
    sess['role'] = 'data_entry_clerk'
    sess['full_name'] = 'Aisha Mohammed'
    sess['facility_id'] = facility_id

save('dashboard-clerk', client.get('/dashboard'))
save('search-table', client.get('/children/search?q=a'))
print('done')
