import hashlib
import hmac
import json
import base64
from datetime import date, timedelta, datetime
from urllib.parse import urlparse

import requests
from flask import current_app

from app import db
from app.models import Appointment, Child, Vaccine, Facility, AuditLog


def send_sms(phone, message, app_config):
    """Send SMS via Africa's Talking API."""
    api_key = app_config['AT_API_KEY']
    username = app_config['AT_USERNAME']
    sender_id = app_config['AT_SENDER_ID']

    if not api_key or not username:
        return {'status': 'skipped', 'reason': 'AT credentials not configured'}

    url = 'https://api.africastalking.com/version1/messaging'
    if username == 'sandbox':
        url = 'https://api.sandbox.africastalking.com/version1/messaging'

    headers = {
        'apiKey': api_key,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }
    payload = {
        'username': username,
        'to': phone,
        'message': message,
    }
    if sender_id:
        payload['from'] = sender_id

    try:
        resp = requests.post(url, headers=headers, data=payload, timeout=10)
        return {'status': 'sent', 'response': resp.json()}
    except Exception as e:
        return {'status': 'failed', 'error': str(e)}


def send_email(to_email, subject, body, app_config, html_body=None):
    """Send email via Azure Communication Services REST API.
    When html_body is provided, both plainText and html are sent in the same
    payload so clients that prefer either format render correctly.
    """
    connection_string = app_config['ACS_CONNECTION_STRING']
    sender = app_config['MAIL_SENDER']

    if not connection_string or not sender or not to_email:
        return {'status': 'skipped', 'reason': 'ACS credentials not configured or no email'}

    # Parse connection string
    parts = {}
    for part in connection_string.split(';'):
        if '=' in part:
            key, value = part.split('=', 1)
            parts[key] = value

    endpoint = parts.get('endpoint', '').rstrip('/')
    access_key = parts.get('accesskey', '')

    if not endpoint or not access_key:
        return {'status': 'skipped', 'reason': 'Invalid ACS connection string'}

    url = f"{endpoint}/emails:send?api-version=2023-03-31"

    content = {
        "subject": subject,
        "plainText": body
    }
    if html_body:
        content["html"] = html_body

    email_payload = {
        "senderAddress": sender,
        "content": content,
        "recipients": {
            "to": [{"address": to_email}]
        }
    }

    body_json = json.dumps(email_payload)
    content_hash = base64.b64encode(
        hashlib.sha256(body_json.encode('utf-8')).digest()
    ).decode('utf-8')

    utc_now = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
    parsed = urlparse(url)
    host = parsed.hostname
    path_and_query = parsed.path + '?' + parsed.query if parsed.query else parsed.path

    string_to_sign = f"POST\n{path_and_query}\n{utc_now};{host};{content_hash}"
    decoded_key = base64.b64decode(access_key)
    signature = base64.b64encode(
        hmac.new(decoded_key, string_to_sign.encode('utf-8'), hashlib.sha256).digest()
    ).decode('utf-8')

    headers = {
        'Content-Type': 'application/json',
        'x-ms-date': utc_now,
        'x-ms-content-sha256': content_hash,
        'Authorization': f"HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature={signature}",
    }

    try:
        resp = requests.post(url, headers=headers, data=body_json, timeout=15)
        return {'status': 'sent', 'http_status': resp.status_code}
    except Exception as e:
        return {'status': 'failed', 'error': str(e)}


_HEADING_BY_TYPE = {
    'evening_before': 'Vaccination Reminder — Tomorrow',
    'morning_of': 'Vaccination Reminder — Today',
    'noon_followup': 'Vaccination Reminder — Follow-up',
}


def build_email_html(child_name, vaccine, date_str, facility_name, message_type, base_url):
    """Build a self-contained branded HTML email body. Inline CSS only —
    email clients strip <link>/<style> stylesheets, so nothing external is
    relied upon besides the logo image.
    """
    heading = _HEADING_BY_TYPE.get(message_type, 'Vaccination Reminder')
    logo_url = f"{base_url.rstrip('/')}/static/vaxtrack-logo.png"

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0; padding:0; background:#f4f4f4; font-family:Arial, Helvetica, sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4; padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff; max-width:600px; width:100%;">
          <tr>
            <td style="background:#353334; padding:24px 32px; text-align:center;">
              <img src="{logo_url}" alt="VaxTrack" height="36" style="height:36px; border:0; display:inline-block;">
            </td>
          </tr>
          <tr>
            <td style="padding:32px; color:#333333;">
              <h1 style="margin:0 0 16px; font-size:20px; color:#333333;">{heading}</h1>
              <p style="margin:0 0 20px; font-size:15px; line-height:1.6;">
                Dear Guardian,<br><br>
                This is a reminder regarding <strong>{child_name}</strong>'s upcoming vaccination appointment.
              </p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="border:2px solid #2DD4BF; border-radius:6px; margin:0 0 20px;">
                <tr>
                  <td style="padding:16px 20px;">
                    <div style="font-size:13px; color:#666666; text-transform:uppercase; letter-spacing:.03em; margin-bottom:4px;">Vaccine</div>
                    <div style="font-size:16px; font-weight:bold; color:#333333; margin-bottom:12px;">{vaccine}</div>
                    <div style="font-size:13px; color:#666666; text-transform:uppercase; letter-spacing:.03em; margin-bottom:4px;">Date</div>
                    <div style="font-size:16px; font-weight:bold; color:#333333;">{date_str}</div>
                  </td>
                </tr>
              </table>
              <p style="margin:0; font-size:15px; line-height:1.6;">
                Please attend at <strong>{facility_name}</strong>. Bring the child's RFID card if one has
                already been issued.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px; background:#fafafa; border-top:1px solid #eeeeee;">
              <p style="margin:0; font-size:12px; color:#888888; line-height:1.6;">
                {facility_name}<br>
                This is an automated message from VaxTrack — please do not reply directly to this email.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _log_notification(action, details):
    """Write notification delivery status to audit log."""
    log = AuditLog(
        user_id=None,
        action_type='INSERT',
        table_affected='notifications',
        record_id=0,
        new_value=details,
        timestamp=datetime.utcnow()
    )
    db.session.add(log)
    db.session.commit()


def send_reminders(app, job_type):
    """
    Core reminder logic used by all 3 scheduled jobs.
    job_type: 'evening_before' | 'morning_of' | 'noon_followup'
    Wrapped in a broad try/except so a single failure never crashes APScheduler.
    """
    try:
        with app.app_context():
            today = date.today()
            tomorrow = today + timedelta(days=1)

            if job_type == 'evening_before':
                target_date = tomorrow
                msg_template = (
                    "Reminder: {child_name}'s {vaccine} vaccination is scheduled for "
                    "tomorrow ({date}) at {facility}. Please attend on time."
                )
                subject = "Vaccination Reminder - Tomorrow"
                send_sms_flag = False
                send_email_flag = True
            elif job_type == 'morning_of':
                target_date = today
                msg_template = (
                    "Reminder: {child_name}'s {vaccine} vaccination is due TODAY ({date}) "
                    "at {facility}. Please bring the child and RFID card."
                )
                subject = "Vaccination Reminder - Today"
                send_sms_flag = True
                send_email_flag = True
            else:  # noon_followup
                target_date = today
                msg_template = (
                    "Hi, this is a follow-up. {child_name}'s {vaccine} vaccination was "
                    "scheduled for today ({date}). If you haven't visited {facility} yet, "
                    "please come in or call the facility."
                )
                subject = "Vaccination Reminder - Follow-up"
                send_sms_flag = False
                send_email_flag = True

            appointments = (
                Appointment.query
                .filter_by(scheduled_date=target_date, status='pending')
                .all()
            )

            config = app.config
            sent_count = 0

            for apt in appointments:
                try:
                    child = Child.query.get(apt.child_id)
                    vaccine = Vaccine.query.get(apt.vaccine_id)
                    facility = Facility.query.get(child.facility_id)

                    message = msg_template.format(
                        child_name=f"{child.first_name} {child.last_name}",
                        vaccine=f"{vaccine.antigen_name} (Dose {vaccine.dose_number})",
                        date=target_date.strftime('%A, %d %B %Y'),
                        facility=facility.facility_name
                    )

                    if send_sms_flag:
                        sms_result = send_sms(child.guardian_phone, message, config)
                    else:
                        sms_result = {'status': 'skipped', 'reason': f'{job_type} is email-only'}

                    if send_email_flag:
                        html_body = build_email_html(
                            child_name=f"{child.first_name} {child.last_name}",
                            vaccine=f"{vaccine.antigen_name} (Dose {vaccine.dose_number})",
                            date_str=target_date.strftime('%A, %d %B %Y'),
                            facility_name=facility.facility_name,
                            message_type=job_type,
                            base_url=config.get('APP_BASE_URL', '')
                        )
                        email_result = send_email(child.guardian_email, subject, message, config,
                                                   html_body=html_body)
                    else:
                        email_result = {'status': 'skipped', 'reason': f'{job_type} is SMS-only'}

                    _log_notification('INSERT', {
                        'job_type': job_type,
                        'child_id': child.child_id,
                        'appointment_id': apt.appointment_id,
                        'sms_result': sms_result,
                        'email_result': email_result
                    })

                    sent_count += 1

                except Exception as per_appt_err:
                    # Log individual failures but continue processing other appointments
                    _log_notification('INSERT', {
                        'job_type': job_type,
                        'appointment_id': apt.appointment_id,
                        'error': str(per_appt_err)
                    })

            if sent_count > 0:
                print(f"[Notifications] {job_type}: Sent {sent_count} reminders")

    except Exception as job_err:
        # Last-resort catch prevents APScheduler thread from dying
        print(f"[Notifications] CRITICAL {job_type} job failed: {job_err}")
