from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from flask_babel import Babel, _
import sqlite3, json, subprocess, hashlib, os, uuid, time
from collections import defaultdict
from functools import wraps
from datetime import datetime

# --- تنظیمات ---
DB_PATH = '/etc/x-ui/x-ui.db'
SYNC_SCRIPT_PATH = '/root/the_final_sync.py'
STATE_FILE = '/root/sync_state.json'
# فایل لیست سفید را دوباره اضافه می کنیم
WHITELIST_FILE = '/root/sync_whitelist.txt' 

app = Flask(__name__)
app.secret_key = 'a-super-duper-secret-key-for-i18n-and-dark-mode'

# --- پیکربندی Babel برای چند زبانه کردن ---
babel = Babel(app)
app.config['LANGUAGES'] = {
    'en': 'English',
    'fa': 'فارسی'
}

@babel.localeselector
def get_locale():
    # اگر کاربر زبانی را در نشست (session) انتخاب کرده، از آن استفاده کن
    if 'language' in session:
        return session['language']
    # در غیر این صورت، بهترین زبان را از هدرهای مرورگر کاربر انتخاب کن
    return request.accept_languages.best_match(app.config['LANGUAGES'].keys())

@app.before_request
def before_request():
    # زبان فعلی را در g ذخیره می کنیم تا در تمام قالب ها در دسترس باشد
    g.locale = str(get_locale())

# --- روت جدید برای تغییر زبان ---
@app.route('/language/<language>')
def set_language(language=None):
    session['language'] = language
    # کاربر را به صفحه ای که از آن آمده بود باز می گردانیم
    return redirect(request.referrer)


# --- تمام توابع کمکی و روت های دیگر ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

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
        return dict(sorted(groups_with_details.items()))
    except Exception as e:
        print(f"Error getting group full details: {e}")
        return {}

# ... (تمام روت های دیگر شما باید در اینجا باشند و متن هایشان با _() پوشانده شوند) ...
# (این یک مثال است و شما باید این الگو را برای تمام روت های خود اعمال کنید)
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
                flash(_('You were successfully logged in'), 'success')
                return redirect(request.args.get('next') or url_for('volume_adjustment'))
            else:
                flash(_('Invalid username or password.'), 'danger')
        except Exception as e:
            flash(_('An error occurred: %(error)s', error=e), 'danger')
    return render_template('login.html')

if __name__ == '__main__':
    port = int(os.environ.get('SYNC_MANAGER_PORT', 5001))
    app.run(host='0.0.0.0', port=port)
