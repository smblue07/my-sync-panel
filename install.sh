#!/bin/bash

# --- Configuration ---
# !!! آدرس ریپازیتوری گیت هاب خود را اینجا قرار دهید !!!
GITHUB_REPO_URL="https://github.com/smblue07/my-sync-panel.git"

INSTALL_DIR="/root/ultimate_sync_manager"
SYNC_SCRIPT_PATH="/root/the_final_sync.py"
WHITELIST_FILE="/root/sync_whitelist.txt"
STATE_FILE="/root/sync_state.json"
SERVICE_NAME="sync_manager"

echo "--- Ultimate 3x-ui Sync Manager Installer v2.0 ---"

# --- Interactive Setup ---
read -p "Enter the port for the web panel (default: 5001): " WEB_PORT
WEB_PORT=${WEB_PORT:-5001}
echo "Web panel will be installed on port: ${WEB_PORT}"

# --- Installation Steps ---
echo "[1/7] Updating system and installing dependencies..."
apt update > /dev/null 2>&1
apt install -y git python3-pip sqlite3 > /dev/null 2>&1

echo "[2/7] Installing Python packages (Flask, Babel, qrcode)..."
# نصب تمام کتابخانه های پایتون مورد نیاز
pip3 install flask flask-babel "qrcode[pil]" > /dev/null 2>&1

echo "[3/7] Cloning project from GitHub..."
if [ -d "${INSTALL_DIR}" ]; then
    echo "Warning: Existing directory found. Removing it."
    rm -rf ${INSTALL_DI}
fi
git clone ${GITHUB_REPO_URL} ${INSTALL_DIR}
if [ ! -d "${INSTALL_DIR}" ]; then
    echo "Error: Failed to clone the repository. Please check the URL."
    exit 1
fi

# رفتن به پوشه پروژه برای اجرای دستورات بعدی
cd ${INSTALL_DIR}

echo "[4/7] Preparing for translations..."
# اجرای دستور babel برای ساخت فایل الگو. این کار در آینده به شما کمک می کند.
pybabel extract -F babel.cfg -o messages.pot . > /dev/null 2>&1


echo "[5/7] Creating systemd service file..."
SERVICE_FILE_CONTENT="[Unit]
Description=Gunicorn instance to serve the Ultimate Sync Manager
After=network.target 3x-ui.service
BindsTo=3x-ui.service

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

echo "[6/7] Creating initial config files..."
mv ${INSTALL_DIR}/the_final_sync.py ${SYNC_SCRIPT_PATH}
touch ${WHITELIST_FILE}
touch ${STATE_FILE}

echo "[7/7] Enabling service and configuring firewall..."
systemctl daemon-reload
systemctl enable ${SERVICE_NAME} > /dev/null 2>&1
systemctl restart ${SERVICE_NAME}

if command -v ufw &> /dev/null && ufw status | grep -q 'Status: active'; then
    ufw allow ${WEB_PORT}/tcp > /dev/null 2>&1
fi

echo "--- Installation Complete! ---"
echo "Panel is running at: http://<YOUR_SERVER_IP>:${WEB_PORT}"
echo "To check service status: systemctl status ${SERVICE_NAME}"
echo "To add translations, edit the .po file in the 'translations' directory on your server, then run 'pybabel compile'."
