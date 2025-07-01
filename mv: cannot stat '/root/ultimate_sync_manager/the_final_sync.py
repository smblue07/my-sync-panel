import sqlite3
import json
from collections import defaultdict
import os

# --- تنظیمات ---
DB_PATH = '/etc/x-ui/x-ui.db'
WHITELIST_FILE = '/root/sync_whitelist.txt'
STATE_FILE = '/root/sync_state.json'

def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, 'r') as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return {}

def save_state(state_data):
    with open(STATE_FILE, 'w') as f: json.dump(state_data, f, indent=4)

def load_whitelist():
    try:
        with open(WHITELIST_FILE, 'r') as f:
            allowed_groups = {line.strip() for line in f if line.strip()}
            if not allowed_groups:
                print("Warning: Whitelist file is empty. No groups will be synced.")
            return allowed_groups
    except FileNotFoundError:
        print(f"Error: Whitelist file not found at '{WHITELIST_FILE}'. No groups will be processed.")
        return set()

def sync_traffic_incrementally():
    state = load_state()
    allowed_groups = load_whitelist()

    if not allowed_groups:
        print("Halting: Whitelist is empty or not found.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        all_inbounds = cursor.execute("SELECT settings FROM inbounds WHERE enable = 1").fetchall()
        
        all_groups_from_db = defaultdict(list)
        for inbound in all_inbounds:
            if not inbound['settings']: continue
            try:
                clients = json.loads(inbound['settings']).get('clients', [])
                for client in clients:
                    sub_id = client.get('subId')
                    email = client.get('email')
                    if sub_id and email and sub_id in allowed_groups:
                        if email not in all_groups_from_db[sub_id]:
                            all_groups_from_db[sub_id].append(email)
            except (json.JSONDecodeError, TypeError): continue

        for sub_id, clients_in_group in all_groups_from_db.items():
            if len(clients_in_group) <= 1:
                print(f"\nGroup '{sub_id}' has only one member, skipping sync.")
                continue

            print(f"\n--- Processing group '{sub_id}' ---")

            placeholders = ','.join('?' for _ in clients_in_group)
            sql_get_traffic = f"SELECT email, up, down FROM client_traffics WHERE email IN ({placeholders})"
            cursor.execute(sql_get_traffic, clients_in_group)
            current_traffic_map = {row['email']: row['up'] + row['down'] for row in cursor.fetchall()}

            group_last_state = state.get(sub_id, {})
            last_total_usage = group_last_state.get('total_usage', 0)
            last_client_usages = group_last_state.get('client_usages', {})

            new_total_usage = last_total_usage
            for email in clients_in_group:
                current_usage = current_traffic_map.get(email, 0)
                last_usage = last_client_usages.get(email, 0)
                
                delta = current_usage if email not in last_client_usages else (current_usage - last_usage)

                if delta > 0:
                    new_total_usage += delta

            print(f"New calculated total usage: {new_total_usage / (1024**3):.2f} GB")

            sql_update_traffic = f"UPDATE client_traffics SET up = ?, down = 0 WHERE email IN ({placeholders})"
            params = [new_total_usage] + clients_in_group
            cursor.execute(sql_update_traffic, params)
            print(f"Success! Synced traffic for {len(clients_in_group)} users.")

            state[sub_id] = {
                'total_usage': new_total_usage,
                'client_usages': {email: new_total_usage for email in clients_in_group}
            }

        conn.commit()

    except sqlite3.Error as e:
        print(f"\nDatabase Error: {e}")
        if 'conn' in locals(): conn.rollback()
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
    finally:
        save_state(state)
        print("\nNew state saved to state file.")
        if 'conn' in locals() and conn: conn.close()

if __name__ == '__main__':
    sync_traffic_incrementally()
