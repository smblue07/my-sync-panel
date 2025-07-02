from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3, json, os, uuid, time, base64
from collections import defaultdict
from functools import wraps
from datetime import datetime
from io import BytesIO
import qrcode
import urllib.parse

# --- تنظیمات ---
DB_PATH = '/etc/x-ui/x-ui.db'
app = Flask(__name__)
app.secret_key = 'the-absolute-final-version-for-real-this-time-v-final'

# --- توابع کمکی ---
def get_all_inbounds_info():
    try:
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
        # اضافه کردن ستون های لازم برای ساخت لینک کانفیگ
        inbounds = conn.execute("SELECT id, remark, port, protocol, enable, settings, stream_settings FROM inbounds").fetchall()
        conn.close()
        return [dict(i) for i in inbounds]
    except Exception: return []

def get_all_groups_with_full_details():
    try:
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
        traffic_map = {row['email']: dict(row) for row in conn.execute("SELECT email, up, down, total, expiry_time, enable FROM client_traffics").fetchall()}
        all_inbounds = conn.execute("SELECT settings FROM inbounds").fetchall()
        conn.close()
        groups_with_details = defaultdict(lambda: {'clients': [], 'group_status': 'inactive'})
        for inbound in all_inbounds:
            if not inbound['settings']: continue
            try:
                clients = json.loads(inbound['settings']).get('clients', [])
                for client in clients:
                    sub_id, email = client.get('subId'), client.get('email')
                    if sub_id and email and not any(c['email'] == email for c in groups_with_details[sub_id]['clients']):
                        client_traffic = traffic_map.get(email, {})
                        is_enabled = client_traffic.get('enable', True)
                        expiry_time = client_traffic.get('expiry_time', 0)
                        usage_bytes = client_traffic.get('up', 0) + client_traffic.get('down', 0)
                        total_bytes = client_traffic.get('total', 0)
                        status = "active"
                        if not is_enabled: status = "inactive"
                        elif (expiry_time > 0 and expiry_time < (time.time() * 1000)) or (total_bytes > 0 and usage_bytes >= total_bytes): status = "expired"
                        client_info = {'email': email, 'status': status, 'usage_gb': usage_bytes / (1024**3), 'total_gb': total_bytes / (1024**3)}
                        groups_with_details[sub_id]['clients'].append(client_info)
                        if status == 'active': groups_with_details[sub_id]['group_status'] = 'active'
            except (json.JSONDecodeError, TypeError): continue
        for sub_id, data in groups_with_details.items():
            if data['clients']:
                data['total_usage_group'] = sum(c['usage_gb'] for c in data['clients'])
                data['total_gb_group'] = sum(c['total_gb'] for c in data['clients'])
        return dict(sorted(groups_with_details.items()))
    except Exception as e:
        print(f"Error getting group full details: {e}"); return {}

def get_clients_for_subid(sub_id):
    return [c['email'] for c in get_all_groups_with_full_details().get(sub_id, {}).get('clients', [])]

def generate_single_config_link(client_uuid, client_email, inbound_details, stream_settings, panel_settings):
    if inbound_details['protocol'] != 'vless': return "# Protocol not supported"
    remark = urllib.parse.quote(client_email)
    address = panel_settings.get('subDomain', 'YOUR_DOMAIN.COM')
    port = inbound_details['port']
    network = stream_settings.get('network', 'ws')
    security = stream_settings.get('security', 'tls')
    ws_settings = stream_settings.get('wsSettings', {})
    path = urllib.parse.quote(ws_settings.get('path', '/'))
    host = ws_settings.get('headers', {}).get('Host', address)
    tls_settings = stream_settings.get('tlsSettings', {})
    sni = tls_settings.get('serverName', address)
    fp = tls_settings.get('fingerprint', 'chrome')
    return f"vless://{client_uuid}@{address}:{port}?type={network}&security={security}&path={path}&host={host}&sni={sni}&fp={fp}#{remark}"

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
                return redirect(request.args.get('next') or url_for('dashboard'))
            else: flash('Invalid username or password.', 'danger')
        except Exception as e: flash(f'An error occurred: {e}', 'danger')
    return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
    
# --- مسیر اصلی برنامه ---
@app.route('/')
@login_required
def index(): return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    all_inbounds = get_all_inbounds_info()
    all_groups_data = get_all_groups_with_full_details()
    results = session.pop('add_client_results', None)
    return render_template('dashboard.html', all_inbounds=all_inbounds, all_groups_data=all_groups_data, results=results)

# --- روت های مربوط به عملیات (Actions) ---
@app.route('/add_client', methods=['POST'])
@login_required
def add_client():
    try:
        base_email = request.form['email']; sub_id = request.form.get('sub_id', '')
        total_gb = int(request.form.get('total_gb', 0)); expiry_days = int(request.form.get('expiry_days', 0))
        selected_inbound_ids = [int(i) for i in request.form.getlist('inbounds')]
        if not base_email or not selected_inbound_ids:
            flash('Email and at least one inbound are required.', 'danger'); return redirect(url_for('dashboard'))
        
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        panel_settings = {row['key']: row['value'] for row in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'sub%'").fetchall()}
        all_inbounds_map = {i['id']: i for i in get_all_inbounds_info()}
        
        created_configs_info = []
        for i, inbound_id in enumerate(selected_inbound_ids, 1):
            unique_email = f"{base_email}-{i}" if len(selected_inbound_ids) > 1 else base_email
            new_client_uuid = str(uuid.uuid4())
            expiry_time = int((time.time() + expiry_days * 24 * 60 * 60) * 1000) if expiry_days > 0 else 0
            total_bytes = total_gb * (1024**3)
            new_client_obj = {"id": new_client_uuid, "email": unique_email, "totalGB": total_bytes, "expiryTime": expiry_time, "enable": True, "subId": sub_id}
            
            inbound = all_inbounds_map.get(inbound_id)
            if not inbound: continue
            settings = json.loads(inbound['settings']); settings['clients'].append(new_client_obj)
            inbound_stream_settings = json.loads(inbound['stream_settings'])
            
            cursor.execute("UPDATE inbounds SET settings = ? WHERE id = ?", (json.dumps(settings), inbound_id))
            cursor.execute("INSERT INTO client_traffics (inbound_id, enable, email, up, down, expiry_time, total) VALUES (?, ?, ?, ?, ?, ?, ?)", (inbound_id, True, unique_email, 0, 0, expiry_time, total_bytes))
            
            link = generate_single_config_link(new_client_uuid, unique_email, inbound, inbound_stream_settings, panel_settings)
            qr_img = qrcode.make(link); buffered = BytesIO(); qr_img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            created_configs_info.append({'name': unique_email, 'link': link, 'qr_code': f"data:image/png;base64,{img_str}"})

        conn.commit(); conn.close()
        
        sub_link = f"https://{panel_settings.get('subDomain', 'YOUR_DOMAIN.COM')}:{panel_settings.get('subPort', '443')}{panel_settings.get('subPath', '/sub/')}{sub_id}"
        qr_img_sub = qrcode.make(sub_link); buffered_sub = BytesIO(); qr_img_sub.save(buffered_sub, format="PNG")
        img_str_sub = base64.b64encode(buffered_sub.getvalue()).decode("utf-8")
        
        session['add_client_results'] = {'configs': created_configs_info, 'sub_link': sub_link, 'sub_qr_code': f"data:image/png;base64,{img_str_sub}"}
        flash(f'Successfully created configs for base email "{base_email}"!', 'success')
    except Exception as e: flash(f'An error occurred while adding user: {e}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/delete_subscription', methods=['POST'])
@login_required
def delete_subscription():
    sub_id_to_delete = request.form['sub_id']
    try:
        clients_to_delete = get_clients_for_subid(sub_id_to_delete)
        if not clients_to_delete:
            flash(f'No clients found for SubID "{sub_id_to_delete}".', 'warning'); return redirect(url_for('dashboard'))
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        placeholders = ','.join('?' for _ in clients_to_delete)
        cursor.execute(f"DELETE FROM client_traffics WHERE email IN ({placeholders})", clients_to_delete)
        all_inbounds = conn.execute("SELECT id, settings FROM inbounds").fetchall()
        for inbound_id, settings_str in all_inbounds:
            if not settings_str: continue
            try:
                settings = json.loads(settings_str)
                original_client_count = len(settings.get('clients', []))
                settings['clients'] = [client for client in settings.get('clients', []) if client.get('email') not in clients_to_delete]
                if len(settings['clients']) < original_client_count:
                    cursor.execute("UPDATE inbounds SET settings = ? WHERE id = ?", (json.dumps(settings), inbound_id))
            except (json.JSONDecodeError, TypeError): continue
        conn.commit(); conn.close()
        flash(f'Subscription group "{sub_id_to_delete}" and its users have been deleted.', 'success')
    except Exception as e: flash(f'An error occurred during deletion: {e}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/toggle_subscription_status', methods=['POST'])
@login_required
def toggle_subscription_status():
    sub_id = request.form['sub_id']; action = request.form['action']
    new_status_bool = True if action == 'enable' else False; new_status_int = 1 if new_status_bool else 0
    try:
        clients_to_toggle = get_clients_for_subid(sub_id)
        if not clients_to_toggle: flash(f'No clients found for SubID "{sub_id}".', 'warning'); return redirect(url_for('dashboard'))
        conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
        placeholders = ','.join('?' for _ in clients_to_toggle)
        cursor.execute(f"UPDATE client_traffics SET enable = ? WHERE email IN ({placeholders})", [new_status_int] + clients_to_toggle)
        all_inbounds = conn.execute("SELECT id, settings FROM inbounds").fetchall()
        for inbound_id, settings_str in all_inbounds:
            if not settings_str: continue
            try:
                settings = json.loads(settings_str)
                for client in settings.get('clients', []):
                    if client.get('email') in clients_to_toggle: client['enable'] = new_status_bool
                cursor.execute("UPDATE inbounds SET settings = ? WHERE id = ?", (json.dumps(settings), inbound_id))
            except (json.JSONDecodeError, TypeError): continue
        conn.commit(); conn.close()
        flash(f'All users in subscription group "{sub_id}" have been {action}d.', 'success')
    except Exception as e: flash(f'An error occurred while toggling group status: {e}', 'danger')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    port = int(os.environ.get('SYNC_MANAGER_PORT', 5001))
    app.run(host='0.0.0.0', port=port)
