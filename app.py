#!/usr/bin/env python3
"""
公务车管理系统 - Government Vehicle Management System
SQLite + Flask + Responsive HTML
跨平台：手机/电脑浏览器均可使用
中英双语 / Bilingual (EN/ZH)
管理员/用户双角色 / Admin & User roles
"""

import sqlite3
import os
import bcrypt
import time
import hashlib
from datetime import datetime, timedelta
from functools import wraps
import secrets
from flask import Flask, render_template, request, redirect, url_for, jsonify, g, session, flash, send_file
from io import BytesIO
import csv
import uuid
from translations import TRANSLATIONS, t as _t_func, t_type as _tt_func
from ai_maintenance import parse_manual_text, extract_text_from_file, analyze_maintenance

app = Flask(__name__)
app.config['DATABASE'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vehicle.db')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16MB max upload

# Persistent secret key for sessions
_SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.secret_key')
if os.path.exists(_SECRET_FILE):
    app.secret_key = open(_SECRET_FILE).read().strip()
else:
    key = os.urandom(32).hex()
    open(_SECRET_FILE, 'w').write(key)
    app.secret_key = key

# Session Cookie Security
app.config['SESSION_COOKIE_HTTPONLY'] = True    # JS cannot read session cookie (anti-XSS)
app.config['SESSION_COOKIE_SECURE'] = True       # Only send cookie over HTTPS (Render)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # Block cross-site POST (anti-CSRF)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)  # Auto-logout after 8h

# CSRF Protection (inline implementation - no flask-wtf dependency)
def generate_csrf_token():
    """Generate and store a CSRF token in the session."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

def validate_csrf_token():
    """Validate CSRF token from form submission."""
    token = session.get('_csrf_token')
    form_token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
    if not token or not form_token or not secrets.compare_digest(token, form_token):
        return False
    return True

@app.before_request
def csrf_protect():
    """Check CSRF token on all POST/PUT/DELETE/PATCH requests."""
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        # Skip CSRF for API endpoints that use token auth
        if request.path.startswith('/api/'):
            return
        # Skip CSRF for login (rate_limit + before_request ordering can cause issues)
        if request.path == '/login':
            return
        if not validate_csrf_token():
            return jsonify({'error': 'CSRF token missing or invalid'}), 403

# Inject csrf_token into all templates
@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf_token)

# Rate Limiter (inline implementation - no flask-limiter dependency)
# Note: uses in-memory store; on PA multi-worker, limits are per-worker.
# This is acceptable since CSRF + auth provide primary protection.
_rate_limit_store = {} # {ip: [(timestamp, ...), ...]}
_rate_limit_last_cleanup = 0

def rate_limit(max_requests=5, period=60):
    """Decorator: limit requests per IP address within a time period.
    Default: 5 requests per 60 seconds (5 per minute)."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            global _rate_limit_last_cleanup
            ip = request.remote_addr or '0.0.0.0'
            now = time.time()
            # Periodic cleanup to prevent memory leak (every 5 min)
            if now - _rate_limit_last_cleanup > 300:
                _rate_limit_store.clear()
                _rate_limit_last_cleanup = now
            # Clean old entries for this IP
            if ip in _rate_limit_store:
                _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if now - t < period]
            else:
                _rate_limit_store[ip] = []
            # Check limit
            if len(_rate_limit_store[ip]) >= max_requests:
                return jsonify({'error': 'Too many requests. Please try again later.'}), 429
            _rate_limit_store[ip].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ============================================================
# Auth System - Users Table Based
# ============================================================

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

def init_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.executescript("""
    CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number TEXT NOT NULL UNIQUE,
    brand_model TEXT NOT NULL,
    vehicle_type TEXT NOT NULL DEFAULT 'sedan',
    purchase_date TEXT,
    initial_mileage REAL DEFAULT 0,
    current_mileage REAL DEFAULT 0,
    mileage_unit TEXT DEFAULT 'km',
            status TEXT DEFAULT 'active',
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

CREATE TABLE IF NOT EXISTS usage_logs (
id INTEGER PRIMARY KEY AUTOINCREMENT,
vehicle_id INTEGER NOT NULL,
created_by INTEGER NOT NULL,
usage_date TEXT NOT NULL,
driver_name TEXT NOT NULL,
purpose TEXT NOT NULL,
destination TEXT,
passengers INTEGER DEFAULT 0,
start_mileage REAL,
end_mileage REAL,
distance REAL DEFAULT 0,
start_time TEXT,
end_time TEXT,
weather TEXT,
road_condition TEXT DEFAULT 'normal',
notes TEXT,
created_at TEXT DEFAULT (datetime('now','localtime')),
FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
FOREIGN KEY (created_by) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS expense_logs (
id INTEGER PRIMARY KEY AUTOINCREMENT,
vehicle_id INTEGER NOT NULL,
created_by INTEGER NOT NULL,
expense_date TEXT NOT NULL,
expense_type TEXT NOT NULL,
amount REAL NOT NULL,
fuel_quantity REAL,
fuel_unit_price REAL,
mileage_at_expense REAL,
vendor TEXT,
invoice_number TEXT,
payment_method TEXT DEFAULT 'cash',
reimbursed INTEGER DEFAULT 0,
notes TEXT,
created_at TEXT DEFAULT (datetime('now','localtime')),
FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
FOREIGN KEY (created_by) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS maintenance_records (
id INTEGER PRIMARY KEY AUTOINCREMENT,
vehicle_id INTEGER NOT NULL,
created_by INTEGER NOT NULL,
maintenance_date TEXT NOT NULL,
maintenance_type TEXT NOT NULL,
description TEXT,
cost REAL DEFAULT 0,
vendor TEXT,
next_maintenance_mileage REAL,
next_maintenance_date TEXT,
notes TEXT,
created_at TEXT DEFAULT (datetime('now','localtime')),
FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
FOREIGN KEY (created_by) REFERENCES users(id)
);
    CREATE TABLE IF NOT EXISTS uploaded_manuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    upload_date TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    table_name TEXT,
    record_id INTEGER,
    description TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
    );
 """)

    # Insert default admin user if not exists
    # Default: admin / Admin@123, user / User@123
    existing = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing == 0:
        # Only generate bcrypt hashes when creating for the first time
        admin_hash = bcrypt.hashpw('Admin@123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user_hash = bcrypt.hashpw('User@123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ('admin', admin_hash, 'admin'))
        db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ('user', user_hash, 'user'))
        db.commit()
    # Auto-migration: add mileage_unit column if missing
    try:
        cols = [r[1] for r in db.execute("PRAGMA table_info(vehicles)").fetchall()]
        if 'mileage_unit' not in cols:
            db.execute("ALTER TABLE vehicles ADD COLUMN mileage_unit TEXT DEFAULT 'km'")
            db.commit()
    except Exception:
        pass
    # Auto-migration: add created_by to vehicles (data isolation)
    try:
        cols = [r[1] for r in db.execute("PRAGMA table_info(vehicles)").fetchall()]
        if 'created_by' not in cols:
            db.execute("ALTER TABLE vehicles ADD COLUMN created_by INTEGER DEFAULT 1 REFERENCES users(id)")
            db.commit()
    except Exception:
        pass
    # Auto-migration: add created_by to uploaded_manuals
    try:
        cols = [r[1] for r in db.execute("PRAGMA table_info(uploaded_manuals)").fetchall()]
        if 'created_by' not in cols:
            db.execute("ALTER TABLE uploaded_manuals ADD COLUMN created_by INTEGER DEFAULT 1 REFERENCES users(id)")
            db.commit()
    except Exception:
        pass
    db.close()

# Initialize database & ensure uploads dir (runs at import time for gunicorn/Render)
init_db()
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============================================================
# Audit Logging
# ============================================================
def log_audit(action, table_name=None, record_id=None, description=None):
    """Log an audit event. Uses session + request for context."""
    try:
        audit_db = sqlite3.connect(app.config['DATABASE'])
        audit_db.execute("PRAGMA journal_mode=WAL")
        audit_db.execute("""
            INSERT INTO audit_logs (user_id, username, action, table_name, record_id, description, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session.get('user_id'),
            session.get('username'),
            action,
            table_name,
            record_id,
            description,
            request.remote_addr,
            request.headers.get('User-Agent', '')[:256],
        ))
        audit_db.commit()
        audit_db.close()
    except Exception:
        pass  # Never let audit logging break the main flow

@app.context_processor
def inject_translations():
    lang = session.get('lang', 'zh')
    return {
        't': lambda key, default=None: default if default is not None and _t_func(key, lang) == key else _t_func(key, lang),
        'tt': _tt_func,
        'lang': lang
    }

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        if session.get('user_role') != 'admin':
            flash(_t_func('admin.access_denied', session.get('lang', 'zh')), 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# Data isolation helpers: user can only see own data; admin sees all
def _is_admin():
    return session.get('user_role') == 'admin'

def _user_id():
    return session.get('user_id')

def user_filter_clause(table_alias=''):
    """Returns (' AND created_by=?', [user_id]) or ('', []) for admins."""
    if _is_admin():
        return '', []
    prefix = f'{table_alias}.' if table_alias else ''
    return f' AND {prefix}created_by=?', [_user_id()]

def apply_user_filter(sql, table_alias=''):
    """Append user filter to SQL WHERE clause if user is not admin."""
    if _is_admin():
        return sql, []
    prefix = f'{table_alias}.' if table_alias else ''
    where_ins = ' WHERE' if ' WHERE ' not in sql.upper() and 'WHERE' not in sql else ' AND'
    return sql + f'{where_ins} {prefix}created_by=?', [_user_id()]

def user_visible_where(table_alias=''):
    """Returns WHERE clause fragment for list queries."""
    if _is_admin():
        return ''
    prefix = f'{table_alias}.' if table_alias else ''
    return f' AND {prefix}created_by={_user_id()}'

def user_visible_params():
    """Returns WHERE params if user, empty list if admin."""
    if _is_admin():
        return []
    return [_user_id()]

@app.route('/login', methods=['GET', 'POST'])
@rate_limit(max_requests=5, period=60)
def login():
    error = None
    lang = session.get('lang', 'zh')
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username and password:
            db = sqlite3.connect(app.config['DATABASE'])
            db.row_factory = sqlite3.Row
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            db.close()
            if user:
                # Verify password - support both bcrypt and legacy SHA256
                verified = False
                stored_hash = user['password_hash']
                # Check if it's a bcrypt hash (starts with $2b$, $2a$, or $2y$)
                if stored_hash.startswith(('$2b$', '$2a$', '$2y$')):
                    try:
                        verified = bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
                    except Exception:
                        verified = False
                else:
                    # Legacy SHA256 hash - verify and auto-upgrade to bcrypt
                    import hashlib
                    sha256_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
                    if sha256_hash == stored_hash:
                        verified = True
                        # Auto-upgrade to bcrypt
                        try:
                            new_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            upgrade_db = sqlite3.connect(app.config['DATABASE'])
                            upgrade_db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user['id']))
                            upgrade_db.commit()
                            upgrade_db.close()
                        except Exception:
                            pass  # Non-critical: upgrade failure doesn't block login

                if verified:
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['user_role'] = user['role']
                    session['logged_in'] = True
                    # Audit log
                    log_audit('login', description=f'User {username} logged in')
                    return redirect(url_for('dashboard'))
                else:
                    error = _t_func('login.error', lang)
            else:
                error = _t_func('login.error', lang)
        else:
            error = _t_func('login.error', lang)
    return render_template('login.html', error=error, lang=lang, t=lambda k: _t_func(k, lang))

@app.route('/manifest.json')
def manifest():
 return send_file('static/manifest.json', mimetype='application/manifest+json')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============================================================
# Admin - User Management (Admin Only)
# ============================================================

@app.route('/admin/users')
@admin_required
def admin_users():
    """List all users - admin only"""
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY role DESC, username").fetchall()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@admin_required
def admin_user_add():
    """Add new user - admin only"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')
        if username and password:
            # Hash password with bcrypt
            pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            db = get_db()
            try:
                db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                           (username, pw_hash.decode('utf-8'), role))
                db.commit()
                log_audit('user_create', 'users', description=f'Created user {username}')
                flash(_t_func('admin.user_added', session.get('lang', 'zh')), 'success')
                return redirect(url_for('admin_users'))
            except sqlite3.IntegrityError:
                flash(_t_func('admin.username_exists', session.get('lang', 'zh')), 'error')
                return redirect(url_for('admin_users'))
    return render_template('admin_user_form.html', user=None)

@app.route('/admin/users/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def admin_user_edit(id):
    """Edit user password/role - admin only"""
    db = get_db()
    if request.method == 'POST':
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')
        if password:
            # Hash password with bcrypt
            pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.execute("UPDATE users SET password_hash=?, role=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (pw_hash, role, id))
        else:
            db.execute("UPDATE users SET role=?, updated_at=datetime('now','localtime') WHERE id=?", (role, id))
        db.commit()
        user = db.execute("SELECT username FROM users WHERE id=?", (id,)).fetchone()
        log_audit('user_update', 'users', id, f'Updated user {user["username"] if user else id}')
        flash(_t_func('admin.user_updated', session.get('lang', 'zh')), 'success')
        return redirect(url_for('admin_users'))
    user = db.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
    return render_template('admin_user_form.html', user=user)

@app.route('/admin/users/delete/<int:id>', methods=['POST'])
@admin_required
def admin_user_delete(id):
    """Delete user - admin only (cannot delete self)"""
    if session.get('user_id') == id:
        flash(_t_func('admin.cannot_delete_self', session.get('lang', 'zh')), 'error')
    else:
        db = get_db()
        try:
            # Step 1: Reassign all user's data to admin (id=1) to preserve records
            # This avoids FK constraint violations since user record will be deleted
            admin_id = 1
            # Ensure admin user exists
            admin = db.execute("SELECT id FROM users WHERE id=?", (admin_id,)).fetchone()
            if not admin:
                # Use current admin's id as fallback
                admin_id = session.get('user_id')
            db.execute("UPDATE vehicles SET created_by=? WHERE created_by=?", (admin_id, id))
            db.execute("UPDATE usage_logs SET created_by=? WHERE created_by=?", (admin_id, id))
            db.execute("UPDATE expense_logs SET created_by=? WHERE created_by=?", (admin_id, id))
            db.execute("UPDATE maintenance_records SET created_by=? WHERE created_by=?", (admin_id, id))
            # Step 2: Delete records that reference user directly (not via created_by)
            db.execute("DELETE FROM audit_logs WHERE user_id=?", (id,))
            # Step 3: Handle uploaded_manuals - reassign via vehicle ownership
            try:
                db.execute("UPDATE uploaded_manuals SET created_by=? WHERE created_by=?", (admin_id, id))
            except Exception:
                pass
            # Step 4: Clear AI analysis cache
            try:
                db.execute("DELETE FROM ai_analysis_cache WHERE created_by=?", (id,))
            except Exception:
                pass
            # Step 5: Now safe to delete the user
            db.execute("DELETE FROM users WHERE id=?", (id,))
            db.commit()
            log_audit('user_delete', 'users', id, f'Deleted user {id}')
            flash(_t_func('admin.user_deleted', session.get('lang', 'zh')), 'success')
        except Exception as e:
            db.rollback()
            flash(f'Delete failed: {str(e)}', 'error')
    return redirect(url_for('admin_users'))

# ============================================================
# Database teardown
# ============================================================

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ============================================================
# Routes - Pages
# ============================================================

@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    user_where, user_params = user_filter_clause()
    # Stats - user only sees own records
    vehicle_count = db.execute(f"SELECT COUNT(*) FROM vehicles WHERE status='active'{user_where}", user_params).fetchone()[0]
    this_month = datetime.now().strftime('%Y-%m')
    usage_this_month = db.execute(
        f"SELECT COUNT(*), COALESCE(SUM(distance),0) FROM usage_logs WHERE usage_date LIKE ?{user_where}",
        [this_month+'%'] + user_params).fetchone()
    expense_this_month = db.execute(
        f"SELECT COALESCE(SUM(amount),0) FROM expense_logs WHERE expense_date LIKE ?{user_where}",
        [this_month+'%'] + user_params).fetchone()[0]
    # Recent usage - user only sees own
    recent_usage = db.execute(f"""
 SELECT ul.*, v.plate_number, v.brand_model, v.mileage_unit
 FROM usage_logs ul JOIN vehicles v ON ul.vehicle_id=v.id
 WHERE 1=1{user_where.replace('created_by','ul.created_by')}
 ORDER BY ul.usage_date DESC, ul.created_at DESC LIMIT 10
    """, user_params).fetchall()
    # Recent expenses - user only sees own
    recent_expenses = db.execute(f"""
 SELECT el.*, v.plate_number, v.brand_model, v.mileage_unit
 FROM expense_logs el JOIN vehicles v ON el.vehicle_id=v.id
 WHERE 1=1{user_where.replace('created_by','el.created_by')}
 ORDER BY el.expense_date DESC, el.created_at DESC LIMIT 10
    """, user_params).fetchall()
    # Monthly expense breakdown (last 6 months)
    six_months_ago = (datetime.now() - timedelta(days=180)).strftime('%Y-%m')
    monthly_expenses = db.execute(f"""
        SELECT strftime('%Y-%m', expense_date) as month,
               SUM(amount) as total,
               SUM(CASE WHEN expense_type='fuel' THEN amount ELSE 0 END) as fuel,
               SUM(CASE WHEN expense_type='maintenance' THEN amount ELSE 0 END) as maintenance,
               SUM(CASE WHEN expense_type='insurance' THEN amount ELSE 0 END) as insurance,
               SUM(CASE WHEN expense_type NOT IN ('fuel','maintenance','insurance') THEN amount ELSE 0 END) as other
        FROM expense_logs
        WHERE expense_date >= ?{user_where}
        GROUP BY strftime('%Y-%m', expense_date)
        ORDER BY month
    """, [six_months_ago+'-01'] + user_params).fetchall()
    # Upcoming maintenance - user only sees vehicles they maintain
    upcoming = db.execute(f"""
 SELECT mr.*, v.plate_number, v.brand_model, v.current_mileage, v.mileage_unit
 FROM maintenance_records mr JOIN vehicles v ON mr.vehicle_id=v.id
 WHERE v.status='active' AND (mr.next_maintenance_date <= date('now','+30 days')
 OR (mr.next_maintenance_mileage IS NOT NULL AND mr.next_maintenance_mileage - v.current_mileage <= 500)){user_where.replace('created_by','mr.created_by')}
 ORDER BY mr.next_maintenance_date LIMIT 5
    """, user_params).fetchall()

    return render_template('dashboard.html',
                           vehicle_count=vehicle_count,
                           usage_count=usage_this_month[0],
                           usage_distance=usage_this_month[1],
                           expense_total=expense_this_month,
                           recent_usage=recent_usage,
                           recent_expenses=recent_expenses,
                           monthly_expenses=monthly_expenses,
                           upcoming=upcoming
                           )

# --- Vehicles ---
@app.route('/vehicles')
@login_required
def vehicles():
    db = get_db()
    user_where, user_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT * FROM vehicles WHERE 1=1{user_where} ORDER BY plate_number", user_params).fetchall()
    return render_template('vehicles.html', vehicles=vehicles_list)

@app.route('/vehicles/add', methods=['GET','POST'])
@login_required
def vehicle_add():
    if request.method == 'POST':
        db = get_db()
        db.execute("""
            INSERT INTO vehicles (plate_number, brand_model, vehicle_type, purchase_date, initial_mileage, current_mileage, mileage_unit, notes, created_by)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (request.form['plate_number'], request.form['brand_model'],
              request.form.get('vehicle_type','sedan'), request.form.get('purchase_date'),
              request.form.get('initial_mileage',0), request.form.get('initial_mileage',0),
              request.form.get('mileage_unit','km'),
              request.form.get('notes',''), session.get('user_id')))
        db.commit()
        log_audit('vehicle_add', 'vehicles', description=f"Added vehicle {request.form['plate_number']}")
        return redirect(url_for('vehicles'))
    return render_template('vehicle_form.html', vehicle=None)

@app.route('/vehicles/edit/<int:id>', methods=['GET','POST'])
@login_required
def vehicle_edit(id):
    db = get_db()
    # Data isolation: non-admin can only edit own vehicles
    vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (id,)).fetchone()
    if not vehicle:
        flash(_t_func('common.not_found', session.get('lang','zh')), 'error')
        return redirect(url_for('vehicles'))
    if session.get('role') != 'admin' and vehicle['created_by'] != session.get('user_id'):
        flash(_t_func('common.no_permission', session.get('lang','zh')), 'error')
        return redirect(url_for('vehicles'))
    if request.method == 'POST':
        db.execute("""
            UPDATE vehicles SET plate_number=?, brand_model=?, vehicle_type=?,
            purchase_date=?, current_mileage=?, mileage_unit=?, status=?, notes=?
            WHERE id=?
        """, (request.form['plate_number'], request.form['brand_model'],
              request.form.get('vehicle_type','sedan'), request.form.get('purchase_date'),
              request.form.get('current_mileage',0), request.form.get('mileage_unit','km'),
              request.form.get('status','active'),
              request.form.get('notes',''), id))
        db.commit()
        log_audit('vehicle_update', 'vehicles', id, f"Updated vehicle {request.form['plate_number']}")
        return redirect(url_for('vehicles'))
    return render_template('vehicle_form.html', vehicle=vehicle)

# --- Usage Logs ---
@app.route('/usage')
@login_required
def usage_list():
    db = get_db()
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    vehicle_filter = request.args.get('vehicle_id','')
    date_from = request.args.get('date_from','')
    date_to = request.args.get('date_to','')
    where_parts = []
    params = []
    # Data isolation: user only sees own records
    if not _is_admin():
        where_parts.append("ul.created_by=?")
        params.append(_user_id())
    if vehicle_filter:
        where_parts.append("ul.vehicle_id=?")
        params.append(vehicle_filter)
    if date_from:
        where_parts.append("ul.usage_date>=?")
        params.append(date_from)
    if date_to:
        where_parts.append("ul.usage_date<=?")
        params.append(date_to)
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    total = db.execute(f"SELECT COUNT(*) FROM usage_logs ul JOIN vehicles v ON ul.vehicle_id=v.id{where_sql}", params).fetchone()[0]
    logs = db.execute(f"""
 SELECT ul.*, v.plate_number, v.brand_model, v.mileage_unit
 FROM usage_logs ul JOIN vehicles v ON ul.vehicle_id=v.id
 {where_sql}
 ORDER BY ul.usage_date DESC, ul.created_at DESC
 LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()
    # Vehicle dropdown: user only sees own vehicles
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    total_pages = (total + per_page - 1) // per_page
    return render_template('usage_list.html', logs=logs, vehicles=vehicles_list,
                           page=page, total_pages=total_pages, vehicle_filter=vehicle_filter,
                           date_from=date_from, date_to=date_to)

@app.route('/usage/add', methods=['GET','POST'])
@login_required
def usage_add():
    db = get_db()
    if request.method == 'POST':
        vid = request.form['vehicle_id']
        start_m = request.form.get('start_mileage') or None
        end_m = request.form.get('end_mileage') or None
        start_m = float(start_m) if start_m else None
        end_m = float(end_m) if end_m else None
        distance = 0
        if start_m and end_m and end_m > start_m:
            distance = end_m - start_m
        db.execute("""
INSERT INTO usage_logs (vehicle_id, usage_date, driver_name, purpose,
 destination, passengers, start_mileage, end_mileage, distance, start_time, end_time,
 weather, road_condition, notes, created_by)
 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (vid, request.form['usage_date'], request.form['driver_name'],
              request.form['purpose'],
              request.form.get('destination',''), request.form.get('passengers',0),
              start_m, end_m, distance, request.form.get('start_time',''),
              request.form.get('end_time',''), request.form.get('weather',''),
              request.form.get('road_condition','normal'), request.form.get('notes',''),
              session.get('user_id')))
        # Update vehicle mileage
        if end_m:
            db.execute("UPDATE vehicles SET current_mileage=? WHERE id=? AND ? > current_mileage", (end_m, vid, end_m))
        db.commit()
        log_audit('usage_add', 'usage_logs', description=f'Added usage for vehicle {vid}')
        return redirect(url_for('usage_list'))
    # Vehicle dropdown: user only sees own vehicles
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('usage_form.html', log=None, vehicles=vehicles_list, today=today)

@app.route('/usage/edit/<int:id>', methods=['GET','POST'])
@login_required
def usage_edit(id):
    db = get_db()
    log = db.execute("SELECT * FROM usage_logs WHERE id=?", (id,)).fetchone()
    if not log:
        flash(_t_func('common.not_found', session.get('lang','zh')), 'error')
        return redirect(url_for('usage_list'))
    # Data isolation: non-admin can only edit own records
    if session.get('role') != 'admin' and log['created_by'] != session.get('user_id'):
        flash(_t_func('common.no_permission', session.get('lang','zh')), 'error')
        return redirect(url_for('usage_list'))
    if request.method == 'POST':
        vid = request.form['vehicle_id']
        start_m = request.form.get('start_mileage') or None
        end_m = request.form.get('end_mileage') or None
        start_m = float(start_m) if start_m else None
        end_m = float(end_m) if end_m else None
        distance = 0
        if start_m and end_m and end_m > start_m:
            distance = end_m - start_m
        db.execute("""
UPDATE usage_logs SET vehicle_id=?, usage_date=?, driver_name=?,
 purpose=?, destination=?, passengers=?, start_mileage=?, end_mileage=?,
 distance=?, start_time=?, end_time=?, weather=?, road_condition=?, notes=?
 WHERE id=?
 """, (vid, request.form['usage_date'], request.form['driver_name'],
       request.form['purpose'],
       request.form.get('destination',''), request.form.get('passengers',0),
       start_m, end_m, distance, request.form.get('start_time',''),
       request.form.get('end_time',''), request.form.get('weather',''),
       request.form.get('road_condition',''), request.form.get('notes',''), id))
        if end_m:
            db.execute("UPDATE vehicles SET current_mileage=? WHERE id=? AND ? > current_mileage", (end_m, vid, end_m))
        db.commit()
        log_audit('usage_update', 'usage_logs', id, 'Updated usage log')
        return redirect(url_for('usage_list'))
    # Vehicle dropdown: user only sees own vehicles
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    return render_template('usage_form.html', log=log, vehicles=vehicles_list, today='')

# --- Expenses ---
@app.route('/expenses')
@login_required
def expense_list():
    db = get_db()
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    vehicle_filter = request.args.get('vehicle_id','')
    type_filter = request.args.get('expense_type','')
    date_from = request.args.get('date_from','')
    date_to = request.args.get('date_to','')
    where_parts = []
    params = []
    # Data isolation: user only sees own records
    if not _is_admin():
        where_parts.append("el.created_by=?")
        params.append(_user_id())
    if vehicle_filter:
        where_parts.append("el.vehicle_id=?")
        params.append(vehicle_filter)
    if type_filter:
        where_parts.append("el.expense_type=?")
        params.append(type_filter)
    if date_from:
        where_parts.append("el.expense_date>=?")
        params.append(date_from)
    if date_to:
        where_parts.append("el.expense_date<=?")
        params.append(date_to)
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    total = db.execute(f"SELECT COUNT(*) FROM expense_logs el JOIN vehicles v ON el.vehicle_id=v.id{where_sql}", params).fetchone()[0]
    logs = db.execute(f"""
 SELECT el.*, v.plate_number, v.brand_model, v.mileage_unit
 FROM expense_logs el JOIN vehicles v ON el.vehicle_id=v.id
 {where_sql}
 ORDER BY el.expense_date DESC, el.created_at DESC
 LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()
    # Summary for filtered results
    summary = db.execute(f"""
        SELECT expense_type, COUNT(*) as cnt, SUM(amount) as total
        FROM expense_logs el WHERE 1=1{' AND el.created_by=?' if not _is_admin() else ''}
        GROUP BY expense_type ORDER BY total DESC
    """, [_user_id()] if not _is_admin() else []).fetchall()
    # Vehicle dropdown: user only sees own vehicles
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    total_pages = (total + per_page - 1) // per_page
    return render_template('expense_list.html', logs=logs, vehicles=vehicles_list,
                           page=page, total_pages=total_pages, vehicle_filter=vehicle_filter,
                           type_filter=type_filter, date_from=date_from, date_to=date_to)

@app.route('/expenses/add', methods=['GET','POST'])
@login_required
def expense_add():
    db = get_db()
    if request.method == 'POST':
        fuel_q = request.form.get('fuel_quantity') or None
        fuel_p = request.form.get('fuel_unit_price') or None
        mileage = request.form.get('mileage_at_expense') or None
        db.execute("""
        INSERT INTO expense_logs (vehicle_id, expense_date, expense_type, amount,
        fuel_quantity, fuel_unit_price, mileage_at_expense, vendor, invoice_number,
        payment_method, reimbursed, notes, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (request.form['vehicle_id'], request.form['expense_date'],
              request.form['expense_type'], request.form['amount'],
              float(fuel_q) if fuel_q else None, float(fuel_p) if fuel_p else None,
              float(mileage) if mileage else None,
              request.form.get('vendor',''), request.form.get('invoice_number',''),
              request.form.get('payment_method','cash'),
              1 if request.form.get('reimbursed') else 0,
              request.form.get('notes',''), session['user_id']))
        db.commit()
        return redirect(url_for('expense_list'))
    # Vehicle dropdown: user only sees own vehicles
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('expense_form.html', log=None, vehicles=vehicles_list, today=today)

@app.route('/expenses/edit/<int:id>', methods=['GET','POST'])
@login_required
def expense_edit(id):
    db = get_db()
    log = db.execute("SELECT * FROM expense_logs WHERE id=?", (id,)).fetchone()
    if not log:
        flash(_t_func('common.not_found', session.get('lang','zh')), 'error')
        return redirect(url_for('expense_list'))
    # Data isolation: non-admin can only edit own records
    if session.get('role') != 'admin' and log['created_by'] != session.get('user_id'):
        flash(_t_func('common.no_permission', session.get('lang','zh')), 'error')
        return redirect(url_for('expense_list'))
    if request.method == 'POST':
        fuel_q = request.form.get('fuel_quantity') or None
        fuel_p = request.form.get('fuel_unit_price') or None
        mileage = request.form.get('mileage_at_expense') or None
        db.execute("""
            UPDATE expense_logs SET vehicle_id=?, expense_date=?, expense_type=?, amount=?,
            fuel_quantity=?, fuel_unit_price=?, mileage_at_expense=?, vendor=?,
            invoice_number=?, payment_method=?, reimbursed=?, notes=? WHERE id=?
            """, (request.form['vehicle_id'], request.form['expense_date'],
            request.form['expense_type'], request.form['amount'],
            float(fuel_q) if fuel_q else None, float(fuel_p) if fuel_p else None,
            float(mileage) if mileage else None,
            request.form.get('vendor',''), request.form.get('invoice_number',''),
            request.form.get('payment_method','cash'),
            1 if request.form.get('reimbursed') else 0,
            request.form.get('notes',''), id))
        db.commit()
        return redirect(url_for('expense_list'))
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    return render_template('expense_form.html', log=log, vehicles=vehicles_list, today='')

# --- Maintenance ---
@app.route('/maintenance')
@login_required
def maintenance_list():
    db = get_db()
    user_where, user_params = user_filter_clause('mr')
    records = db.execute(f"""
 SELECT mr.*, v.plate_number, v.brand_model, v.current_mileage, v.mileage_unit
 FROM maintenance_records mr JOIN vehicles v ON mr.vehicle_id=v.id
 WHERE 1=1{user_where}
 ORDER BY mr.maintenance_date DESC LIMIT 50
    """, user_params).fetchall()
    return render_template('maintenance_list.html', records=records)

@app.route('/maintenance/add', methods=['GET','POST'])
@login_required
def maintenance_add():
    db = get_db()
    if request.method == 'POST':
        db.execute("""
        INSERT INTO maintenance_records (vehicle_id, maintenance_date, maintenance_type,
        description, cost, vendor, next_maintenance_mileage, next_maintenance_date, notes, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (request.form['vehicle_id'], request.form['maintenance_date'],
              request.form['maintenance_type'], request.form.get('description',''),
              request.form.get('cost',0), request.form.get('vendor',''),
              request.form.get('next_maintenance_mileage') or None,
              request.form.get('next_maintenance_date') or None,
              request.form.get('notes',''), session['user_id']))
        db.commit()
        log_audit('maintenance_add', 'maintenance_records', description=f'Added maintenance for vehicle {request.form["vehicle_id"]}')
        return redirect(url_for('maintenance_list'))
    # Vehicle dropdown: user only sees own vehicles
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('maintenance_form.html', record=None, vehicles=vehicles_list, today=today)

# --- Mobile Quick Entry ---
@app.route('/mobile')
@login_required
def mobile_home():
 db = get_db()
 user_v_where, user_v_params = user_filter_clause()
 vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
 today = datetime.now().strftime('%Y-%m-%d')
 return render_template('mobile_home.html', vehicles=vehicles_list, today=today, lang=session.get('lang','zh'), t=lambda k: _t_func(k, session.get('lang','zh')), tt=lambda p,v: _tt_func(p,v, session.get('lang','zh')))

@app.route('/mobile/usage', methods=['GET','POST'])
@login_required
def mobile_usage():
    db = get_db()
    if request.method == 'POST':
        vehicle_id = request.form['vehicle_id']
        usage_date = request.form.get('usage_date', datetime.now().strftime('%Y-%m-%d'))
        driver = request.form['driver']
        purpose = request.form['purpose']
        destination = request.form.get('destination','')
        start_m = request.form.get('start_mileage') or None
        end_m = request.form.get('end_mileage') or None
        distance = 0
        if start_m and end_m:
            try: distance = float(end_m) - float(start_m)
            except: pass
        db.execute("""INSERT INTO usage_logs
        (vehicle_id, usage_date, driver_name, purpose, destination,
        start_mileage, end_mileage, distance, start_time, end_time, weather, road_condition, notes, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (vehicle_id, usage_date, driver, purpose, destination,
                    start_m, end_m, distance, request.form.get('start_time'),
                    request.form.get('end_time'), request.form.get('weather','clear'),
                    request.form.get('road_condition','normal'),request.form.get('notes',''), session['user_id']))
        db.commit()
        log_audit('mobile_usage_add', 'usage_logs', description=f'Mobile usage for vehicle {vehicle_id}')
        # Update vehicle mileage
        if end_m:
            try: db.execute("UPDATE vehicles SET current_mileage=? WHERE id=? AND (? > current_mileage OR current_mileage IS NULL)", (float(end_m), vehicle_id, float(end_m)))
            except: pass
        db.commit()
        return render_template('mobile_success.html', message=_t_func('mobile.success', session.get('lang','zh')), action='usage', lang=session.get('lang','zh'), t=lambda k: _t_func(k, session.get('lang','zh')))
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('mobile_usage.html', vehicles=vehicles_list, today=today, lang=session.get('lang','zh'), t=lambda k: _t_func(k, session.get('lang','zh')), tt=lambda p,v: _tt_func(p,v, session.get('lang','zh')))

@app.route('/mobile/expense', methods=['GET','POST'])
@login_required
def mobile_expense():
    db = get_db()
    if request.method == 'POST':
        vehicle_id = request.form['vehicle_id']
        expense_date = request.form.get('expense_date', datetime.now().strftime('%Y-%m-%d'))
        expense_type = request.form['expense_type']
        amount = request.form['amount']
        db.execute("""INSERT INTO expense_logs
        (vehicle_id, expense_date, expense_type, amount, fuel_quantity, fuel_unit_price,
        mileage_at_expense, vendor, invoice_number, payment_method, reimbursed, notes, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (vehicle_id, expense_date, expense_type, amount,
                    request.form.get('fuel_quantity') or None,
                    request.form.get('fuel_unit_price') or None,
                    request.form.get('mileage_at_expense') or None,
                    request.form.get('vendor', ''),
                    request.form.get('invoice_number', ''),
                    request.form.get('payment_method', 'cash'),
                    0, request.form.get('notes',''), session['user_id']))
        db.commit()
        log_audit('mobile_expense_add', 'expense_logs', description=f'Mobile expense for vehicle {vehicle_id}')
        return render_template('mobile_success.html', message=_t_func('mobile.success', session.get('lang','zh')), action='expense', lang=session.get('lang','zh'), t=lambda k: _t_func(k, session.get('lang','zh')))
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('mobile_expense.html', vehicles=vehicles_list, today=today, lang=session.get('lang','zh'), t=lambda k: _t_func(k, session.get('lang','zh')), tt=lambda p,v: _tt_func(p,v, session.get('lang','zh')))

# --- Reports / Analysis ---
@app.route('/reports')
@login_required
def reports():
    db = get_db()
    period = request.args.get('period', 'monthly')
    vehicle_id = request.args.get('vehicle_id', '')
    current_year = datetime.now().year
    year = request.args.get('year', str(current_year))

    # Data isolation filter
    user_v_where, user_v_params = user_filter_clause()
    is_admin = session.get('role') == 'admin'

    # Determine mileage unit for display
    selected_vehicle_unit = 'km' # default
    if vehicle_id:
        sv = db.execute("SELECT mileage_unit FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        if sv and sv['mileage_unit']:
            selected_vehicle_unit = sv['mileage_unit']

    # Expense analysis by type
    if period == 'monthly':
        expense_group = "strftime('%Y-%m', expense_date)"
        usage_group = "strftime('%Y-%m', usage_date)"
    elif period == 'quarterly':
        expense_group = "'Q' || cast(strftime('%m', expense_date) as integer)/3+1 || ' ' || strftime('%Y', expense_date)"
        usage_group = "'Q' || cast(strftime('%m', usage_date) as integer)/3+1 || ' ' || strftime('%Y', usage_date)"
    else:
        expense_group = "strftime('%Y', expense_date)"
        usage_group = "strftime('%Y', usage_date)"

    where_parts = ["1=1"]
    params = []

    if vehicle_id:
        where_parts.append("el.vehicle_id=?")
        params.append(vehicle_id)
    if year:
        where_parts.append("el.expense_date LIKE ?")
        params.append(year + '%')
    # Data isolation: non-admin only sees own expense records
    if not is_admin:
        where_parts.append("el.created_by=?")
        params.append(session.get('user_id'))

    where_sql = " AND ".join(where_parts)

    expense_by_period = db.execute(f"""
        SELECT {expense_group} as period_label,
        SUM(amount) as total,
        SUM(CASE WHEN expense_type='fuel' THEN amount ELSE 0 END) as fuel,
        SUM(CASE WHEN expense_type='maintenance' THEN amount ELSE 0 END) as maintenance,
        SUM(CASE WHEN expense_type='insurance' THEN amount ELSE 0 END) as insurance,
        SUM(CASE WHEN expense_type='toll' THEN amount ELSE 0 END) as toll,
        SUM(CASE WHEN expense_type='parking' THEN amount ELSE 0 END) as parking,
        SUM(CASE WHEN expense_type NOT IN ('fuel','maintenance','insurance','toll','parking') THEN amount ELSE 0 END) as other,
        COUNT(*) as record_count
        FROM expense_logs el WHERE {where_sql}
        GROUP BY {expense_group} ORDER BY period_label
        """, params).fetchall()

    # Usage analysis - build separate where clause
    usage_where_parts = ["1=1"]
    usage_params = []
    if vehicle_id:
        usage_where_parts.append("ul.vehicle_id=?")
        usage_params.append(vehicle_id)
    if year:
        usage_where_parts.append("ul.usage_date LIKE ?")
        usage_params.append(year + '%')
    # Data isolation: non-admin only sees own usage records
    if not is_admin:
        usage_where_parts.append("ul.created_by=?")
        usage_params.append(session.get('user_id'))

    usage_where_sql = " AND ".join(usage_where_parts)

    usage_by_period = db.execute(f"""
        SELECT {usage_group} as period_label,
        COUNT(*) as trip_count,
        SUM(distance) as total_distance,
        AVG(distance) as avg_distance,
        COUNT(DISTINCT driver_name) as driver_count
        FROM usage_logs ul
        WHERE {usage_where_sql}
        GROUP BY {usage_group} ORDER BY period_label
        """, usage_params).fetchall()

    # Per-vehicle cost (with data isolation)
    vc_where_parts = ["1=1"]
    vc_params = []
    if vehicle_id:
        vc_where_parts.append("el.vehicle_id=?")
        vc_params.append(vehicle_id)
    if year:
        vc_where_parts.append("el.expense_date LIKE ?")
        vc_params.append(year + '%')
    if not is_admin:
        vc_where_parts.append("el.created_by=?")
        vc_params.append(session.get('user_id'))
    vc_where_sql = " AND ".join(vc_where_parts)

    vehicle_costs = db.execute(f"""
        SELECT v.plate_number, v.brand_model,
        COUNT(*) as record_count,
        SUM(el.amount) as total_cost,
        SUM(CASE WHEN el.expense_type='fuel' THEN el.amount ELSE 0 END) as fuel_cost,
        SUM(CASE WHEN el.expense_type='maintenance' THEN el.amount ELSE 0 END) as maint_cost,
        v.current_mileage, v.mileage_unit
        FROM expense_logs el JOIN vehicles v ON el.vehicle_id=v.id
        WHERE {vc_where_sql}
        GROUP BY el.vehicle_id ORDER BY total_cost DESC
        """, vc_params).fetchall()

    # Fuel efficiency (with data isolation)
    fe_params = []
    fe_where = "el.expense_type='fuel' AND el.fuel_quantity > 0"
    if not is_admin:
        fe_where += " AND el.created_by=?"
        fe_params.append(session.get('user_id'))

    fuel_efficiency = db.execute(f"""
        SELECT v.plate_number, v.brand_model,
        SUM(el.fuel_quantity) as total_fuel,
        SUM(el.amount) as total_fuel_cost,
        AVG(el.fuel_unit_price) as avg_unit_price,
        v.current_mileage,
        (SELECT SUM(distance) FROM usage_logs WHERE vehicle_id=v.id) as total_distance
        FROM expense_logs el JOIN vehicles v ON el.vehicle_id=v.id
        WHERE {fe_where}
        GROUP BY el.vehicle_id ORDER BY total_fuel_cost DESC
        """, fe_params).fetchall()

    vehicles_list = db.execute(f"SELECT id, plate_number, brand_model, mileage_unit FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number", user_v_params).fetchall()

    # Year list for dropdown
    year_list = list(range(current_year, current_year - 5, -1))

    return render_template('reports.html',
        expense_by_period=expense_by_period,
        usage_by_period=usage_by_period,
        vehicle_costs=vehicle_costs,
        fuel_efficiency=fuel_efficiency,
        vehicles=vehicles_list,
        period=period, year=year, vehicle_id=vehicle_id,
        year_list=year_list, datetime=datetime,
        selected_vehicle_unit=selected_vehicle_unit
    )

# --- Export CSV ---
@app.route('/export/<table>')
@login_required
def export_csv(table):
    db = get_db()
    allowed = {'vehicles': ('vehicles', 'v', ''),
               'usage_logs': ('usage_logs', 'ul', 'vehicles v ON ul.vehicle_id=v.id'),
               'expense_logs': ('expense_logs', 'el', 'vehicles v ON el.vehicle_id=v.id')}
    if table not in allowed:
        return "Invalid table", 400
    tbl_name, prefix, join_clause = allowed[table]
    user_where, user_params = user_filter_clause(prefix)
    if join_clause:
        rows = db.execute(f"SELECT {prefix}.*, v.plate_number, v.brand_model FROM {tbl_name} {prefix} JOIN {join_clause} WHERE 1=1{user_where} ORDER BY {prefix}.created_at DESC", user_params).fetchall()
        cursor = db.execute(f"SELECT {prefix}.*, v.plate_number, v.brand_model FROM {tbl_name} {prefix} JOIN {join_clause} WHERE 1=1{user_where} ORDER BY {prefix}.created_at DESC", user_params)
    else:
        rows = db.execute(f"SELECT * FROM {tbl_name} {prefix} WHERE 1=1{user_where} ORDER BY {prefix}.created_at DESC", user_params).fetchall()
        cursor = db.execute(f"SELECT * FROM {tbl_name} {prefix} WHERE 1=1{user_where} ORDER BY {prefix}.created_at DESC", user_params)
    columns = [desc[0] for desc in cursor.description]
    # Build CSV in memory using StringIO for text, then encode to bytes
    import io as _io
    text_buf = _io.StringIO()
    writer = csv.writer(text_buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[col] for col in columns])
    csv_bytes = text_buf.getvalue().encode('utf-8-sig')  # BOM for Excel
    buf = BytesIO(csv_bytes)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
        download_name=f"{table}_{datetime.now().strftime('%Y%m%d')}.csv",
        mimetype='text/csv')

# --- Delete records ---
@app.route('/delete/<table>/<int:id>', methods=['POST'])
@admin_required
def delete_record(table, id):
    allowed = {'vehicles': 'vehicles', 'usage_logs': 'usage_logs', 'expense_logs': 'expense_logs', 'maintenance_records': 'maintenance_records'}
    if table not in allowed:
        return "Invalid table", 400
    db = get_db()
    # Cascade delete: when deleting a vehicle, also delete related records
    if table == 'vehicles':
        db.execute("DELETE FROM usage_logs WHERE vehicle_id=?", (id,))
        db.execute("DELETE FROM expense_logs WHERE vehicle_id=?", (id,))
        db.execute("DELETE FROM maintenance_records WHERE vehicle_id=?", (id,))
        db.execute("DELETE FROM uploaded_manuals WHERE vehicle_id=?", (id,))
        try:
            db.execute("DELETE FROM ai_analysis_cache WHERE vehicle_id=?", (id,))
        except Exception:
            pass
    db.execute(f"DELETE FROM {allowed[table]} WHERE id=?", (id,))
    db.commit()
    log_audit(f'{table}_delete', table, id, f'Deleted {table} {id}')
    return redirect(request.referrer or url_for('dashboard'))


# ============================================================
# Database Backup
# ============================================================
def backup_db(backup_dir=None, keep_days=7):
    """Create a backup of the database and remove old backups."""
    import shutil, os
    from datetime import datetime, timedelta
    
    db_path = app.config['DATABASE']
    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
    
    os.makedirs(backup_dir, exist_ok=True)
    
    # Create backup with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'vehicle_{timestamp}.db'
    backup_path = os.path.join(backup_dir, backup_name)
    
    try:
        shutil.copy2(db_path, backup_path)
        # Also backup WAL and SHM if they exist
        for ext in ['-wal', '-shm']:
            wal_path = db_path + ext
            if os.path.exists(wal_path):
                shutil.copy2(wal_path, backup_path + ext)
        
        # Remove old backups
        cutoff = datetime.now() - timedelta(days=keep_days)
        for f in os.listdir(backup_dir):
            if f.startswith('vehicle_') and f.endswith('.db'):
                f_path = os.path.join(backup_dir, f)
                f_mtime = datetime.fromtimestamp(os.path.getmtime(f_path))
                if f_mtime < cutoff:
                    os.remove(f_path)
                    # Also remove wal/shm if exist
                    for ext in ['-wal', '-shm']:
                        if os.path.exists(f_path + ext):
                            os.remove(f_path + ext)
        
        return True, backup_path
    except Exception as e:
        return False, str(e)



@app.route('/admin/backup', methods=['POST'])
@admin_required
def admin_backup():
    """Create database backup - admin only."""
    success, result = backup_db()
    if success:
        flash(f'Backup created: {os.path.basename(result)}', 'success')
        # Log audit
        log_audit('backup_create', description=f'Backup created: {result}')
    else:
        flash(f'Backup failed: {result}', 'error')
    return redirect(request.referrer or url_for('admin_users'))

@app.route('/admin/backups')
@admin_required
def admin_backups():
    """List database backups - admin only."""
    import os
    backup_dir = os.path.join(os.path.dirname(app.config['DATABASE']), 'backups')
    backups = []
    if os.path.exists(backup_dir):
        for f in sorted(os.listdir(backup_dir), reverse=True):
            if f.startswith('vehicle_') and f.endswith('.db'):
                f_path = os.path.join(backup_dir, f)
                size = os.path.getsize(f_path)
                mtime = os.path.getmtime(f_path)
                backups.append({'name': f, 'path': f_path, 'size': size, 'mtime': mtime})
    return render_template('backups.html', backups=backups, backup_dir=backup_dir)


# ============================================================
# i18n - Language Switching
# ============================================================

@app.context_processor
def inject_i18n():
    lang = session.get('lang', 'zh')
    def _t(key):
        return _t_func(key, lang)
    def _tt(prefix, value):
        return _tt_func(prefix, value, lang)
    return dict(t=_t, tt=_tt, lang=lang)

@app.before_request
def set_lang():
    if 'lang' not in session:
        session['lang'] = 'zh'
    lang_arg = request.args.get('lang')
    if lang_arg in ('zh', 'en'):
        session['lang'] = lang_arg

@app.route('/set-lang/<lang>')
@login_required
def set_language(lang):
    if lang in ('zh', 'en'):
        session['lang'] = lang
    return redirect(request.referrer or url_for('dashboard'))

# ============================================================
# AI Maintenance Analysis
# ============================================================

@app.route('/maintenance/ai-analysis', methods=['GET', 'POST'])
@login_required
def ai_analysis():
    """AI-powered maintenance analysis with RAG."""
    db = get_db()
    user_v_where, user_v_params = user_filter_clause()
    vehicles_list = db.execute(
        f"SELECT id, plate_number, brand_model, current_mileage FROM vehicles WHERE status='active'{user_v_where} ORDER BY plate_number",
        user_v_params
    ).fetchall()
    lang = session.get('lang', 'zh')
    vehicle_id = request.form.get('vehicle_id', '') or request.args.get('vehicle_id', '')
    
    ai_analysis_text = None
    ai_error = None
    manual_info = None
    current_mileage = 0
    
    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id', '')
        manual_files = request.files.getlist('manual_files')  # Support multiple files
        
        # Handle multiple file uploads
        uploaded_count = 0
        for manual_file in manual_files:
            if manual_file and manual_file.filename:
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                ext = manual_file.filename.rsplit('.', 1)[-1].lower() if '.' in manual_file.filename else ''
                if ext in ('pdf', 'txt'):
                    safe_name = f"{vehicle_id}_{uuid.uuid4().hex[:8]}.{ext}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
                    manual_file.save(filepath)
                    try:
                        # Extract text using new ai_maintenance module
                        from ai_maintenance import extract_text_from_file
                        extracted = extract_text_from_file(filepath, ext)
                        
                        db.execute("""INSERT INTO uploaded_manuals
                            (vehicle_id, filename, original_filename, file_type, file_size, extracted_text, created_by)
                            VALUES (?,?,?,?,?,?,?)""",
                            (vehicle_id, safe_name, manual_file.filename, ext,
                             os.path.getsize(filepath), extracted[:100000], session.get('user_id')))  # Limit text length
                        db.commit()
                        uploaded_count += 1
                    except Exception as e:
                        ai_error = f"Upload error: {str(e)}"
        
        # Run AI analysis if vehicle selected
        if vehicle_id and not ai_error:
            try:
                vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (int(vehicle_id),)).fetchone()
                history = db.execute(
                    "SELECT maintenance_date, description, cost, maintenance_type, mileage_at_service FROM maintenance_records WHERE vehicle_id=? ORDER BY maintenance_date DESC",
                    (int(vehicle_id),)).fetchall()

                if vehicle:
                    from ai_maintenance import get_manual_text_for_vehicle, analyze_maintenance_ai
                    manual_text = get_manual_text_for_vehicle(int(vehicle_id))

                    ai_analysis_text, ai_error = analyze_maintenance_ai(
                        vehicle={
                            'plate_number': vehicle['plate_number'],
                            'brand_model': vehicle['brand_model'],
                            'current_mileage': vehicle['current_mileage'],
                            'purchase_date': vehicle['purchase_date']
                        },
                        history=[{
                            'maintenance_date': h['maintenance_date'],
                            'description': h['description'],
                            'cost': h['cost'],
                            'maintenance_type': h['maintenance_type'] if 'maintenance_type' in h.keys() else '',
                            'mileage_at_service': h['mileage_at_service'] if 'mileage_at_service' in h.keys() else 0
                        } for h in history],
                        manual_text=manual_text,
                        lang=lang
                    )

                    current_mileage = vehicle['current_mileage']

                    if ai_analysis_text:
                        log_audit('maintenance_ai_analysis', 'maintenance_records', description=f'AI analysis for vehicle {vehicle_id}')

            except Exception as e:
                ai_error = f"Analysis error: {str(e)}"
    
    # Get existing manuals for selected vehicle
    existing_manuals = []
    if vehicle_id:
        existing_manuals = db.execute(
            "SELECT id, filename, original_filename, file_type, file_size, upload_date FROM uploaded_manuals WHERE vehicle_id=? ORDER BY upload_date DESC",
            (vehicle_id,)).fetchall()
    
    return render_template('ai_analysis.html', 
                         vehicles=vehicles_list, 
                         vehicle_id=vehicle_id,
                         selected_vehicle_mileage=current_mileage,
                         results=None,  # Not used in AI mode
                         ai_analysis=ai_analysis_text,
                         ai_error=ai_error,
                         manual_info=manual_info,
                         existing_manuals=existing_manuals,
                         lang=lang)
    if vehicle_id:
        existing_manual = db.execute(
            "SELECT * FROM uploaded_manuals WHERE vehicle_id=? ORDER BY upload_date DESC LIMIT 1",
            (vehicle_id,)).fetchone()

    selected_vehicle = None
    if vehicle_id:
        selected_vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()

    return render_template('ai_analysis.html',
        vehicles=vehicles_list, vehicle_id=vehicle_id,
        selected_vehicle=selected_vehicle,
        results=results, current_mileage=current_mileage,
        existing_manual=existing_manual, manual_info=manual_info)

# ============================================================
# Async AI Analysis API (avoids PA free tier timeout)
# Uses background thread + database polling pattern
# ============================================================

# In-memory task status cache (survives within one worker process)
_ai_task_cache = {}

def _run_ai_analysis_task(task_id, vehicle_id, lang, user_id):
    """Background thread: run AI analysis and store result in DB."""
    import sqlite3 as _sq
    import traceback as _tb
    try:
        db_path = app.config.get('DATABASE', '/home/IvanTso/vehicle-management/vehicle_management.db')
        
        conn = _sq.connect(db_path)
        conn.row_factory = _sq.Row
        db = conn.cursor()
        
        vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        if not vehicle:
            _ai_task_cache[task_id] = {'status': 'error', 'error': '车辆不存在'}
            conn.close()
            return
        
        history = db.execute(
            "SELECT maintenance_date, description, cost, maintenance_type, mileage_at_service FROM maintenance_records WHERE vehicle_id=? ORDER BY maintenance_date DESC",
            (vehicle_id,)).fetchall()
        
        from ai_maintenance import get_manual_text_for_vehicle, analyze_maintenance_ai
        
        manual_text = get_manual_text_for_vehicle(vehicle_id)
        
        ai_text, ai_err = analyze_maintenance_ai(
            vehicle={
                'plate_number': vehicle['plate_number'],
                'brand_model': vehicle['brand_model'],
                'current_mileage': vehicle['current_mileage'],
                'purchase_date': vehicle['purchase_date']
            },
            history=[{
                'maintenance_date': h['maintenance_date'],
                'description': h['description'],
                'cost': h['cost'],
                'maintenance_type': h['maintenance_type'] if 'maintenance_type' in h.keys() else '',
                'mileage_at_service': h['mileage_at_service'] if 'mileage_at_service' in h.keys() else 0
            } for h in history],
            manual_text=manual_text,
            lang=lang
        )
        
        if ai_text:
            # Store in DB for persistence
            db.execute(
                "CREATE TABLE IF NOT EXISTS ai_analysis_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER, analysis_text TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_by INTEGER)")
            db.execute("DELETE FROM ai_analysis_cache WHERE vehicle_id=?", (vehicle_id,))
            db.execute("INSERT INTO ai_analysis_cache (vehicle_id, analysis_text, created_by) VALUES (?,?,?)",
                (vehicle_id, ai_text, user_id))
            conn.commit()
            _ai_task_cache[task_id] = {'status': 'ok', 'analysis': ai_text}
        else:
            _ai_task_cache[task_id] = {'status': 'error', 'error': ai_err or '分析失败，请稍后重试'}
        
        conn.close()
    except Exception as e:
        err_detail = f"{type(e).__name__}: {str(e)}"
        try:
            err_detail += "\n" + _tb.format_exc()[-500:]
        except:
            pass
        _ai_task_cache[task_id] = {'status': 'error', 'error': err_detail}


@app.route('/api/ai-analysis/start', methods=['POST'])
@login_required
def api_ai_analysis_start():
    """Start AI analysis in background thread, return task_id immediately."""
    import threading, uuid
    
    vehicle_id = request.form.get('vehicle_id', type=int)
    lang = session.get('lang', 'zh')
    user_id = session.get('user_id')
    
    if not vehicle_id:
        return jsonify({'error': '请选择车辆'}), 400
    
    # Data isolation: non-admin can only analyze own vehicles
    db = get_db()
    vehicle = db.execute("SELECT created_by FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if not vehicle:
        return jsonify({'error': '车辆不存在'}), 404
    if session.get('role') != 'admin' and vehicle['created_by'] != user_id:
        return jsonify({'error': '无权限分析此车辆'}), 403
    
    task_id = str(uuid.uuid4())[:8]
    _ai_task_cache[task_id] = {'status': 'running'}
    
    t = threading.Thread(target=_run_ai_analysis_task, args=(task_id, vehicle_id, lang, user_id))
    t.daemon = True
    t.start()
    
    return jsonify({'status': 'started', 'task_id': task_id, 'vehicle_id': vehicle_id})


@app.route('/api/ai-analysis/poll/<task_id>', methods=['GET'])
@login_required
def api_ai_analysis_poll(task_id):
    """Poll for AI analysis result by task_id. Falls back to DB cache for multi-worker PA."""
    result = _ai_task_cache.get(task_id)
    if result and result.get('status') == 'ok':
        return jsonify(result)
    if result and result.get('status') == 'error':
        return jsonify(result)
    # Memory cache lost (multi-worker PA) or still running — check DB cache
    vid = request.args.get('vehicle_id', type=int)
    if vid:
        db = get_db()
        # Data isolation check
        if session.get('role') != 'admin':
            vehicle = db.execute("SELECT created_by FROM vehicles WHERE id=?", (vid,)).fetchone()
            if not vehicle or vehicle['created_by'] != session.get('user_id'):
                return jsonify({'status': 'none', 'error': '无权限'})
        try:
            db.execute("CREATE TABLE IF NOT EXISTS ai_analysis_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER, analysis_text TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_by INTEGER)")
            row = db.execute("SELECT analysis_text, created_at FROM ai_analysis_cache WHERE vehicle_id=? ORDER BY created_at DESC LIMIT 1", (vid,)).fetchone()
            if row and row['analysis_text']:
                return jsonify({'status': 'ok', 'analysis': row['analysis_text'], 'created_at': row['created_at']})
        except Exception:
            pass
    if result and result.get('status') == 'running':
        return jsonify({'status': 'running'})
    if not result:
        return jsonify({'status': 'not_found', 'error': '任务不存在或已过期，请重新分析'})
    return jsonify(result)


@app.route('/api/ai-analysis/latest/<int:vehicle_id>', methods=['GET'])
@login_required
def api_ai_analysis_latest(vehicle_id):
    """Get latest cached AI analysis for a vehicle."""
    db = get_db()
    # Data isolation: non-admin can only view analysis for own vehicles
    if session.get('role') != 'admin':
        vehicle = db.execute("SELECT created_by FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        if not vehicle or vehicle['created_by'] != session.get('user_id'):
            return jsonify({'status': 'none', 'error': '无权限或暂无分析记录'})
    db.execute(
        "CREATE TABLE IF NOT EXISTS ai_analysis_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER, analysis_text TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_by INTEGER)")
    row = db.execute("SELECT analysis_text, created_at FROM ai_analysis_cache WHERE vehicle_id=? ORDER BY created_at DESC LIMIT 1", (vehicle_id,)).fetchone()
    if row:
        return jsonify({'status': 'ok', 'analysis': row['analysis_text'], 'created_at': row['created_at']})
    return jsonify({'status': 'none', 'error': '暂无分析记录'})


# ============================================================
# Main
# ============================================================

if __name__ == '__main__':
 init_db()
 print("\n ===================================================")
 print(" 公务车管理系统 - Government Vehicle Management System")
 print(" ===================================================")
 print(" 本机访问: http://localhost:5000")
 print(" 局域网访问: http://<你的IP>:5000")
 print(" 手机访问: 确保手机和电脑在同一WiFi下")
 print(" ===================================================\n")
 app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')

# PythonAnywhere WSGI import point
# PA will import 'app' from this module
application = app

