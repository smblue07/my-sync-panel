from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3, json, subprocess, hashlib, os, uuid, time
from collections import defaultdict
from functools import wraps
from datetime import datetime

# --- تنظیمات ---
DB_PATH = '/etc/x-ui/x-ui.db'
SYNC_SCRIPT_PATH = '/root/the_final_sync.py'
STATE_FILE = '/root/sync_state.json'
WHITELIST_FILE = '/root/sync_whitelist.txt' 

app = Flask(__name__)
app.secret_key = 'the-absolute-final-key-for-this-ultimate-panel-v2'

# --- توابع کمکی ---
def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, 'r') as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return {}
def save_state(state_data):
    with open(STATE_FILE, 'w') as f: json.dump(state_data, f, indent=4)
def get_whitelisted_groups():
    try:
        with open(WHITELIST_FILE, 'r') as f: return {line.strip() for line in f if line.strip()}
    except FileNotFoundError: return set()
def save_whitelisted_groups(groups_to_save):
    with open(WHITELIST_FILE, 'w') as f:
        for group in groups_to_save: f.write(f"{group}\n")
def get_all_inbounds_info():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        inbounds = conn.execute("SELECT id, remark, port, protocol, enable FROM inbounds").fetchall()
        conn.close()
        return [{'id': i['id'], 'remark': i['remark'], 'port': i['port'], 'protocol': i['protocol'], 'enable': i['enable']} for i in inbounds]
    except Exception: return []
def get_all_groups_with_full_details():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        traffic_map = {row['email']: dict(row) for row in cursor.execute("SELECT email, up, down, total, expiry_time FROM client_traffics").fetchall()}
        all_inbounds = cursor.execute("SELECT settings FROM inbounds").fetchall()
        conn.close()
        groups_with_details = defaultdict(lambda: {'clients': []})
        for inbound in all_inbounds:
            if not inbound['settings']: continue
            try:
                clients = json.loads(inbound['settings']).get('clients', [])
                for client in clients:
                    sub_id, email = client.get('subId'), client.get('email')
                    if sub_id and email:
                        if not any(c['email'] == email for c in groups_with_details[sub_id]['clients']):
                            client_traffic = traffic_map.get(email, {})
                            usage_bytes = client_traffic.get('up', 0) + client_traffic.get('down', 0)
                            total_bytes = client_traffic.get('total', 0)
                            expiry_time = client_traffic.get('expiry_time', 0)
                            expiry_date_str = 'Never'
                            if expiry_time > 0:
                                try:
                                    expiry_date_str = datetime.fromtimestamp(expiry_time / 1000).strftime('%Y-%m-%d')
                                except (ValueError, OSError): expiry_date_str = 'Invalid Date'
                            client_info = {'email': email, 'usage_gb': usage_bytes / (1024**3), 'total_gb': total_bytes / (1024**3), 'expiry_date': expiry_date_str}
                            groups_with_details[sub_id]['clients'].append(client_info)
            except (json.JSONDecodeError, TypeError): continue
        for sub_id, data in groups_with_details.items():
            if data['clients']:
                data['total_usage_group'] = sum(c['usage_gb'] for c in data['clients'])
                data['total_gb_group'] = sum(c['total_gb'] for c in data['clients'])
                data['expiry_date_group'] = data['clients'][0]['expiry_date']
        return dict(sorted(groups_with_details.items()))
    except Exception as e:
        print(f"Error getting group full details: {e}")
        return {}
def get_clients_for_subid(sub_id):
    all_groups = get_all_groups_with_full_details()
    return [client['email'] for client in all_groups.get(sub_id, {}).get('clients', [])]

# --- سیستم لاگین ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        try:
            conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
            user = conn.execute("SELECT password FROM users WHERE username = ?", (username,)).fetchone()
            conn.close()
            if user and user['password'] == password:
                session['logged_in'], session['username'] = True, username
                return redirect(request.args.get('next') or url_for('volume_adjustment'))
            else: flash('Invalid username or password.', 'danger')
        except Exception as e: flash(f'An error occurred: {e}', 'danger')
    return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
    
# --- مسیرهای اصلی برنامه ---
@app.route('/')
@login_required
def index(): return redirect(url_for('volume_adjustment'))
@app.route('/volume_adjustment')
@login_required
def volume_adjustment():
    all_groups_data = get_all_groups_with_full_details()
    whitelisted_groups = get_whitelisted_groups()
    return render_template('volume_adjustment.html', all_groups_data=all_groups_data, whitelisted_groups=whitelisted_groups)
@app.route('/add_client_page')
@login_required
def add_client_page():
    all_inbounds = get_all_inbounds_info()
    return render_template('add_client.html', all_inbounds=all_inbounds)

# --- روت های مربوط به عملیات (Actions) ---
@app.route('/add_client', methods=['POST'])
@login_required
def add_client():
    try:
        base_email = request.form['email']
        sub_id = request.form['sub_id']
        total_gb = int(request.form.get('total_gb', 0))
        expiry_days = int(request.form.get('expiry_days', 0))
        selected_inbound_ids = [int(i) for i in request.form.getlist('inbounds')]
        if not base_email or not selected_inbound_ids:
            flash('Email and at least one inbound are required.', 'danger'); return redirect(url_for('add_client_page'))
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        for i, inbound_id in enumerate(selected_inbound_ids, 1):
            unique_email = f"{base_email}-{i}" if len(selected_inbound_ids) > 1 else base_email
            new_client_uuid = str(uuid.uuid4())
            expiry_time = int((time.time() + expiry_days * 24 * 60 * 60) * 1000) if expiry_days > 0 else 0
            total_bytes = total_gb * (1024**3)
            new_client_obj = {"id": new_client_uuid, "flow": "", "email": unique_email, "limitIp": 0, "totalGB": total_bytes, "expiryTime": expiry_time, "enable": True, "tgId": "", "subId": sub_id, "reset": 0}
            settings_str = cursor.execute("SELECT settings FROM inbounds WHERE id = ?", (inbound_id,)).fetchone()[0]
            settings = json.loads(settings_str)
            settings['clients'].append(new_client_obj)
            cursor.execute("UPDATE inbounds SET settings = ? WHERE id = ?", (json.dumps(settings), inbound_id))
            cursor.execute("INSERT INTO client_traffics (inbound_id, enable, email, up, down, expiry_time, total) VALUES (?, ?, ?, ?, ?, ?, ?)", (inbound_id, True, unique_email, 0, 0, expiry_time, total_bytes))
        conn.commit(); conn.close()
        flash(f'User creation process completed for base email "{base_email}"!', 'success')
    except Exception as e: flash(f'An error occurred while adding user: {e}', 'danger')
    return redirect(url_for('add_client_page'))

@app.route('/set_individual_usage', methods=['POST'])
@login_required
def set_individual_usage():
    try:
        email = request.form['email']
        sub_id = request.form['sub_id']
        usage_gb = float(request.form.get('usage_gb', 0))
        new_usage_bytes = int(usage_gb * (1024**3))
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE client_traffics SET up = ?, down = 0 WHERE email = ?", (new_usage_bytes, email))
        conn.commit(); conn.close()
        state = load_state()
        if sub_id in state and email in state[sub_id].get('client_usages', {}):
            old_email_usage = state[sub_id]['client_usages'][email]
            state[sub_id]['total_usage'] = state[sub_id].get('total_usage', 0) + (new_usage_bytes - old_email_usage)
            state[sub_id]['client_usages'][email] = new_usage_bytes
            save_state(state)
        flash(f'Usage for user "{email}" was set to {usage_gb} GB.', 'success')
    except Exception as e: flash(f'An error occurred: {e}', 'danger')
    return redirect(url_for('volume_adjustment'))

@app.route('/sync_sum_group', methods=['POST'])
@login_required
def sync_sum_group():
    try:
        sub_id = request.form['sub_id']
        clients_in_group = get_clients_for_subid(sub_id)
        if not clients_in_group: flash(f'Group "{sub_id}" not found.', 'warning'); return redirect(url_for('volume_adjustment'))
        conn = sqlite3.connect(DB_PATH)
        placeholders = ','.join('?' for _ in clients_in_group)
        traffic_rows = conn.execute(f"SELECT up, down FROM client_traffics WHERE email IN ({placeholders})", clients_in_group).fetchall()
        total_usage_bytes = sum(row[0] + row[1] for row in traffic_rows)
        conn.execute(f"UPDATE client_traffics SET up = ?, down = 0 WHERE email IN ({placeholders})", [total_usage_bytes] + clients_in_group)
        conn.commit(); conn.close()
        state = load_state(); state[sub_id] = {'total_usage': total_usage_bytes, 'client_usages': {email: total_usage_bytes for email in clients_in_group}}; save_state(state)
        flash(f'Group "{sub_id}" synced by SUM. New total usage: {total_usage_bytes / (1024**3):.2f} GB.', 'success')
    except Exception as e: flash(f'An error occurred during SUM sync: {e}', 'danger')
    return redirect(url_for('volume_adjustment'))

@app.route('/sync_max_group', methods=['POST'])
@login_required
def sync_max_group():
    try:
        sub_id = request.form['sub_id']
        clients_in_group = get_clients_for_subid(sub_id)
        if not clients_in_group: flash(f'Group "{sub_id}" not found.', 'warning'); return redirect(url_for('volume_adjustment'))
        conn = sqlite3.connect(DB_PATH)
        placeholders = ','.join('?' for _ in clients_in_group)
        traffic_rows = conn.execute(f"SELECT up, down FROM client_traffics WHERE email IN ({placeholders})", clients_in_group).fetchall()
        max_usage_bytes = max(row[0] + row[1] for row in traffic_rows) if traffic_rows else 0
        conn.execute(f"UPDATE client_traffics SET up = ?, down = 0 WHERE email IN ({placeholders})", [max_usage_bytes] + clients_in_group)
        conn.commit(); conn.close()
        state = load_state(); state[sub_id] = {'total_usage': max_usage_bytes * len(clients_in_group), 'client_usages': {email: max_usage_bytes for email in clients_in_group}}; save_state(state)
        flash(f'Group "{sub_id}" synced by MAX. New usage set to: {max_usage_bytes / (1024**3):.2f} GB.', 'success')
    except Exception as e: flash(f'An error occurred during MAX sync: {e}', 'danger')
    return redirect(url_for('volume_adjustment'))
    
@app.route('/set_limits', methods=['POST'])
@login_required
def set_limits():
    try:
        sub_id = request.form['sub_id']
        new_total_gb_str = request.form.get('new_total_gb')
        new_expiry_days_str = request.form.get('new_expiry_days')
        clients_in_group = get_clients_for_subid(sub_id)
        if not clients_in_group: flash(f'Group "{sub_id}" not found.', 'warning'); return redirect(url_for('volume_adjustment'))
        update_fields, update_params = [], []
        if new_total_gb_str: update_fields.append("total = ?"); update_params.append(int(float(new_total_gb_str) * (1024**3)))
        if new_expiry_days_str: update_fields.append("expiry_time = ?"); update_params.append(int((time.time() + int(new_expiry_days_str) * 24 * 60 * 60) * 1000))
        if not update_fields: flash('No new values provided to set.', 'info'); return redirect(url_for('volume_adjustment'))
        conn = sqlite3.connect(DB_PATH)
        placeholders = ','.join('?' for _ in clients_in_group)
        sql_update = f"UPDATE client_traffics SET {', '.join(update_fields)} WHERE email IN ({placeholders})"
        conn.execute(sql_update, update_params + clients_in_group)
        conn.commit(); conn.close()
        flash(f'Successfully updated limits for group "{sub_id}".', 'success')
    except Exception as e: flash(f'An error occurred: {e}', 'danger')
    return redirect(url_for('volume_adjustment'))

if __name__ == '__main__':
    port = int(os.environ.get('SYNC_MANAGER_PORT', 5001))
    app.run(host='0.0.0.0', port=port)
