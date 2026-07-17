from functools import wraps
from datetime import datetime, date

import bcrypt
from flask import Blueprint, request, session, redirect, url_for, render_template, flash, jsonify

from app import db
from app.models import User, AuditLog

auth_bp = Blueprint('auth', __name__)


# ---------------------------------------------------------------------------
# RBAC decorator
# ---------------------------------------------------------------------------
def require_role(*roles):
    """Decorator that restricts access to users with the specified role(s)."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))
            if session.get('role') not in roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('auth.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def login_required(f):
    """Decorator that requires any authenticated user."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------
def row_to_dict(obj):
    """Serialise a SQLAlchemy model row to a JSON-safe dict for audit snapshots.
    Password hashes are always redacted.
    """
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if col.name == 'password_hash':
            val = '***'
        elif isinstance(val, (date, datetime)):
            val = val.isoformat()
        result[col.name] = val
    return result


def write_audit(user_id, action_type, table_affected, record_id,
                old_value=None, new_value=None):
    log = AuditLog(
        user_id=user_id,
        action_type=action_type,
        table_affected=table_affected,
        record_id=record_id,
        old_value=old_value,
        new_value=new_value,
        timestamp=datetime.utcnow()
    )
    db.session.add(log)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@auth_bp.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('auth.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    user = User.query.filter_by(username=username).first()

    if not user:
        flash('Invalid username or password.', 'danger')
        return render_template('login.html'), 401

    if not user.is_active:
        flash('Account is locked. Contact an administrator.', 'danger')
        return render_template('login.html'), 403

    if bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
        # Successful login reset failed attempts
        user.failed_attempts = 0
        db.session.commit()

        session['user_id'] = user.user_id
        session['username'] = user.username
        session['role'] = user.role
        session['full_name'] = user.full_name
        session['facility_id'] = user.facility_id

        write_audit(user.user_id, 'INSERT', 'sessions', user.user_id,
                    new_value={'action': 'login'})
        db.session.commit()

        return redirect(url_for('auth.dashboard'))
    else:
        # Failed login
        user.failed_attempts += 1
        if user.failed_attempts >= 3:
            user.is_active = False
            write_audit(None, 'UPDATE', 'users', user.user_id,
                        old_value={'is_active': True},
                        new_value={'is_active': False, 'reason': 'account_locked_3_failed_attempts'})
            db.session.commit()
            flash('Account locked after 3 failed attempts. Contact an administrator.', 'danger')
            return render_template('login.html'), 403

        db.session.commit()
        flash('Invalid username or password.', 'danger')
        return render_template('login.html'), 401


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    user_id = session.get('user_id')
    write_audit(user_id, 'DELETE', 'sessions', user_id,
                old_value={'action': 'logout'})
    db.session.commit()
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'GET':
        return render_template('change_password.html')

    old_password = request.form.get('old_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if new_password != confirm_password:
        flash('New passwords do not match.', 'danger')
        return render_template('change_password.html')

    if len(new_password) < 8:
        flash('Password must be at least 8 characters.', 'danger')
        return render_template('change_password.html')

    user = User.query.get(session['user_id'])
    if not bcrypt.checkpw(old_password.encode('utf-8'), user.password_hash.encode('utf-8')):
        flash('Current password is incorrect.', 'danger')
        return render_template('change_password.html')

    new_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    old_hash = user.password_hash
    user.password_hash = new_hash

    write_audit(user.user_id, 'UPDATE', 'users', user.user_id,
                old_value={'password_hash': '***'},
                new_value={'password_hash': '***', 'action': 'password_changed'})
    db.session.commit()

    flash('Password changed successfully.', 'success')
    return redirect(url_for('auth.dashboard'))


@auth_bp.route('/dashboard')
@login_required
def dashboard():
    from app.models import Child, Appointment, Vaccination
    role = session.get('role')
    today = date.today()
    stats = {
        'total_children': Child.query.count(),
        'pending_today': Appointment.query.filter_by(scheduled_date=today, status='pending').count(),
        'overdue': Appointment.query.filter(
            Appointment.scheduled_date < today,
            Appointment.status.in_(['pending', 'overdue'])
        ).count(),
        'total_vaccinations': Vaccination.query.count(),
    }
    return render_template('dashboard.html', role=role, stats=stats)


# ---------------------------------------------------------------------------
# Admin: user management
# ---------------------------------------------------------------------------
@auth_bp.route('/users')
@require_role('admin')
def list_users():
    users = User.query.all()
    return render_template('users.html', users=users)


@auth_bp.route('/users/create', methods=['GET', 'POST'])
@require_role('admin')
def create_user():
    if request.method == 'GET':
        from app.models import Facility
        facilities = Facility.query.all()
        return render_template('create_user.html', facilities=facilities)

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', '')
    facility_id = request.form.get('facility_id', type=int)

    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'danger')
        return redirect(url_for('auth.create_user'))

    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    new_user = User(
        username=username,
        password_hash=password_hash,
        full_name=full_name,
        role=role,
        facility_id=facility_id,
        is_active=True,
        failed_attempts=0
    )
    db.session.add(new_user)
    db.session.flush()

    write_audit(session['user_id'], 'INSERT', 'users', new_user.user_id,
                old_value=None,
                new_value=row_to_dict(new_user))
    db.session.commit()

    flash(f'User "{username}" created successfully.', 'success')
    return redirect(url_for('auth.list_users'))


@auth_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@require_role('admin')
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    old_snapshot = row_to_dict(user)
    user.is_active = not user.is_active
    user.failed_attempts = 0  # reset on toggle

    write_audit(session['user_id'], 'UPDATE', 'users', user.user_id,
                old_value=old_snapshot,
                new_value=row_to_dict(user))
    db.session.commit()

    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User "{user.username}" {status}.', 'success')
    return redirect(url_for('auth.list_users'))


@auth_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@require_role('admin')
def reset_user_password(user_id):
    """Admin resets another user's password does not require knowing the old one."""
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()

    if len(new_password) < 8:
        flash('New password must be at least 8 characters.', 'danger')
        return redirect(url_for('auth.list_users'))

    old_snapshot = row_to_dict(user)
    user.password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    write_audit(session['user_id'], 'UPDATE', 'users', user.user_id,
                old_value={**old_snapshot, 'action': 'admin_password_reset'},
                new_value={**row_to_dict(user), 'action': 'admin_password_reset'})
    db.session.commit()

    flash(f'Password for "{user.username}" has been reset.', 'success')
    return redirect(url_for('auth.list_users'))


# ---------------------------------------------------------------------------
# Admin: audit log
# ---------------------------------------------------------------------------
@auth_bp.route('/audit-log')
@require_role('admin')
def audit_log():
    page = request.args.get('page', 1, type=int)
    table_filter = request.args.get('table', '')
    action_filter = request.args.get('action', '')
    user_filter = request.args.get('user_id', '', type=str)
    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')

    query = AuditLog.query.order_by(AuditLog.timestamp.desc())

    if table_filter:
        query = query.filter(AuditLog.table_affected == table_filter)
    if action_filter:
        query = query.filter(AuditLog.action_type == action_filter)
    if user_filter:
        query = query.filter(AuditLog.user_id == int(user_filter))
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d')
            query = query.filter(AuditLog.timestamp >= date_from)
        except ValueError:
            pass
    if date_to_str:
        try:
            # Include the entire end day
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(AuditLog.timestamp <= date_to)
        except ValueError:
            pass

    logs = query.paginate(page=page, per_page=50, error_out=False)
    all_users = User.query.order_by(User.username).all()

    return render_template('audit_log.html', logs=logs,
                           table_filter=table_filter, action_filter=action_filter,
                           user_filter=user_filter, date_from=date_from_str,
                           date_to=date_to_str, all_users=all_users)
