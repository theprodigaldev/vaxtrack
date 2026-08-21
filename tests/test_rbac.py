"""Tests for the two RBAC fixes:

1. require_role()'s insufficient-role branch now returns a real HTTP 403
   (rendering app/templates/403.html) instead of a flash + 302 redirect.
2. deactivate_rfid / replace_rfid in app/patients.py are now
   data_entry_clerk-only (admin removed), per the "Data Entry Clerk handles
   all card recovery" design rule.
"""
from conftest import login_as


# ---------------------------------------------------------------------------
# TC10: insufficient role -> 403, protected content not rendered
# ---------------------------------------------------------------------------
def test_wrong_role_gets_403_and_no_form_content(client, facility_id):
    """TC10: HTTP 403 returned; no form rendered.
    immunisation_officer is not in ('data_entry_clerk', 'admin'), so hitting
    the child-registration form (data_entry_clerk/admin-only) must be
    rejected with a real 403 status, and the registration form itself must
    not appear in the response body.
    """
    login_as(client, 'immunisation_officer', facility_id)

    resp = client.get('/children')

    assert resp.status_code == 403
    assert b'name="first_name"' not in resp.data
    assert b"don't have permission" in resp.data.lower()


def test_403_response_is_not_a_redirect(client, facility_id):
    """A redirect can't correctly carry a 403 status (redirects are 3xx by
    definition) - confirm no Location header / 3xx status leaks through."""
    login_as(client, 'immunisation_officer', facility_id)

    resp = client.get('/children')

    assert resp.status_code == 403
    assert 'Location' not in resp.headers


# ---------------------------------------------------------------------------
# admin no longer allowed on RFID card-recovery routes
# ---------------------------------------------------------------------------
def test_admin_cannot_deactivate_rfid(client, facility_id, rfid_tag):
    login_as(client, 'admin', facility_id)

    resp = client.post(f'/rfid/{rfid_tag}/deactivate', data={'reason': 'lost'})

    assert resp.status_code == 403


def test_admin_cannot_replace_rfid(client, facility_id, rfid_tag):
    login_as(client, 'admin', facility_id)

    resp = client.post(f'/rfid/{rfid_tag}/replace', data={'new_uid_hex': 'NEWCARD01'})

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Regression: data_entry_clerk must still be able to use both routes
# ---------------------------------------------------------------------------
def test_data_entry_clerk_can_still_deactivate_rfid(client, facility_id, rfid_tag):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/rfid/{rfid_tag}/deactivate', data={'reason': 'lost'})

    # Success path redirects to the child record (302), not 403
    assert resp.status_code == 302
    assert '/children/' in resp.headers['Location']


def test_data_entry_clerk_can_still_replace_rfid(client, facility_id, rfid_tag):
    login_as(client, 'data_entry_clerk', facility_id)

    resp = client.post(f'/rfid/{rfid_tag}/replace', data={'new_uid_hex': 'NEWCARD01'})

    assert resp.status_code == 302
    assert '/children/' in resp.headers['Location']


# ---------------------------------------------------------------------------
# login_required must be unaffected: anonymous -> 302 to login, not 403
# ---------------------------------------------------------------------------
def test_anonymous_request_to_require_role_route_gets_302_to_login(client):
    resp = client.get('/children')

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_anonymous_request_to_login_required_route_gets_302_to_login(client, facility_id, rfid_tag):
    # view_child is @login_required (any authenticated role), not @require_role
    resp = client.get('/children/1')

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
