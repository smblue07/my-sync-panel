#!/bin/bash

# --- Configuration ---
# !!! آدرس ریپازیتوری گیت هاب خود را اینجا قرار دهید !!!
GITHUB_REPO_URL="https://github.com/smblue07/my-sync-panel.git"

INSTALL_DIR="/root/ultimate_sync_manager"
SYNC_SCRIPT_PATH="/root/the_final_sync.py"
WHITELIST_FILE="/root/sync_whitelist.txt"
STATE_FILE="/root/sync_state.json"
SERVICE_NAME="sync_manager"

echo "--- Ultimate 3x-ui Sync Manager Installer v3.1 (Single Language) ---"

# --- Interactive Setup ---
read -p "Enter the port for the web panel (default: 5001): " WEB_PORT
WEB_PORT=${WEB_PORT:-5001}
echo "Web panel will be installed on port: ${WEB_PORT}"

# --- Installation Steps ---
echo "[1/5] Installing dependencies..."
apt-get update > /dev/null 2>&1
apt-get install -y git python3-pip sqlite3 > /dev/null 2>&1

echo "[2/5] Installing Python packages..."
pip3 install flask "qrcode[pil]" gunicorn > /dev/null 2>&1

echo "[3/5] Cloning project from GitHub..."
rm -rf ${INSTALL_DIR}
git clone ${GITHUB_REPO_URL} ${INSTALL_DIR}
if [ ! -d "${INSTALL_DIR}" ]; then
    echo "Error: Failed to clone the repository."
    exit 1
fi

cd ${INSTALL_DIR}

echo "[4/5] Creating systemd service file..."
SERVICE_FILE_CONTENT="[Unit]
Description=Gunicorn instance to serve the Ultimate Sync Manager
After=network.target x-ui.service
BindsTo=x-ui.service
[Service]
User=root
WorkingDirectory=${INSTALL_DIR}
Environment=\"SYNC_MANAGER_PORT=${WEB_PORT}\"
ExecStart=/usr/local/bin/gunicorn --workers 3 --bind 0.0.0.0:\${SYNC_MANAGER_PORT} 'app:app'
Restart=always
[Install]
WantedBy=multi-user.target
"
echo "$SERVICE_FILE_CONTENT" > /etc/systemd/system/${SERVICE_NAME}.service

echo "[5/5] Finalizing installation..."
mv ${INSTALL_DIR}/the_final_sync.py ${SYNC_SCRIPT_PATH}
touch ${WHITELIST_FILE}
touch ${STATE_FILE}

systemctl daemon-reload
systemctl enable ${SERVICE_NAME} > /dev/null 2>&1
systemctl restart ${SERVICE_NAME}

if command -v ufw &> /dev/null && ufw status | grep -q 'Status: active'; then
    ufw allow ${WEB_PORT}/tcp > /dev/null 2>&1
fi

echo "--- Installation Complete! ---"
echo "Your panel is running at: http://<YOUR_SERVER_IP>:${WEB_PORT}"
