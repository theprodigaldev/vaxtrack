"""Unit tests for build_lcd_payload() in app/rfid.py.

build_lcd_payload() is a pure function (no Flask app/request context, no DB
access), so these tests call it directly with plain dicts/lists shaped like
the appointment records the /scan route already builds.

Coverage maps to the project's functional test matrix:
- TC04: next-pending-appointment selection (state 3) across due_today /
  due_this_week / upcoming buckets.
- TC05: missed-vaccine detection (states 4 and 5).
- TC09: fully-immunised and non-found-child paths (states 6, 7, 8).
"""
from app.rfid import build_lcd_payload


def _apt(vaccine, scheduled_date, dose_number=1):
    return {
        'appointment_id': 1,
        'vaccine': vaccine,
        'dose_number': dose_number,
        'scheduled_date': scheduled_date,
        'status': 'pending',
        'completed_date': None
    }


# --- TC09: fully immunised / non-found-child paths ---------------------

def test_all_done_zero_overdue_zero_pending_gives_state_6():
    lcd = build_lcd_payload('found', overdue=[], due_today=[], due_this_week=[],
                             upcoming=[], completed=[_apt('BCG', '2025-01-01')])
    assert lcd == {
        'state': 6, 'line1': 'All Vaccines Done', 'line2': 'EPI Complete!',
        'led': 'green_flash_3x', 'buzzer': '3_quick_beeps'
    }


def test_unknown_uid_gives_state_7():
    lcd = build_lcd_payload('unknown', uid_hex='DEADBEEF')
    assert lcd == {
        'state': 7, 'line1': 'Card Not Found', 'line2': 'Register Child',
        'led': 'red_solid', 'buzzer': '2_beeps'
    }


def test_deactivated_tag_gives_state_8():
    lcd = build_lcd_payload('deactivated', uid_hex='DEADBEEF')
    assert lcd == {
        'state': 8, 'line1': 'Card Deactivated', 'line2': 'See Admin',
        'led': 'red_flashing', 'buzzer': '3_beeps'
    }


# --- TC05: missed-vaccine detection -------------------------------------

def test_exactly_one_overdue_gives_state_4_with_antigen_name():
    lcd = build_lcd_payload('found', overdue=[_apt('Measles', '2025-01-01')],
                             due_today=[], due_this_week=[], upcoming=[], completed=[])
    assert lcd['state'] == 4
    assert lcd['line1'] == 'MISSED: Measles'
    assert lcd['line2'] == 'Give Now!'
    assert lcd['led'] == 'red_solid'
    assert lcd['buzzer'] == '2_short_beeps'


def test_multiple_overdue_gives_state_5_with_count():
    overdue = [_apt('Measles', '2025-01-01'), _apt('Polio', '2025-01-08'), _apt('BCG', '2025-01-15')]
    lcd = build_lcd_payload('found', overdue=overdue, due_today=[], due_this_week=[],
                             upcoming=[], completed=[])
    assert lcd['state'] == 5
    assert lcd['line1'] == '3 Missed Vaccines'
    assert lcd['line2'] == 'See Nurse'
    assert lcd['led'] == 'red_flashing'
    assert lcd['buzzer'] == '3_rapid_beeps'


# --- TC04: next-pending-appointment selection (state 3) -----------------

def test_zero_overdue_due_today_wins_over_later_buckets():
    lcd = build_lcd_payload(
        'found',
        overdue=[],
        due_today=[_apt('Polio', '2025-06-10')],
        due_this_week=[_apt('BCG', '2025-06-12')],
        upcoming=[_apt('Yellow Fever', '2025-07-01')],
        completed=[]
    )
    assert lcd['state'] == 3
    assert lcd['line1'] == 'Next: Polio'
    assert lcd['line2'] == 'Due: 2025-06-10'
    assert lcd['led'] == 'green_solid'
    assert lcd['buzzer'] == '1_beep'


def test_zero_overdue_no_due_today_falls_back_to_due_this_week():
    lcd = build_lcd_payload(
        'found',
        overdue=[],
        due_today=[],
        due_this_week=[_apt('BCG', '2025-06-12')],
        upcoming=[_apt('Yellow Fever', '2025-07-01')],
        completed=[]
    )
    assert lcd['state'] == 3
    assert lcd['line1'] == 'Next: BCG'
    assert lcd['line2'] == 'Due: 2025-06-12'
