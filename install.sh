#!/bin/bash

# --- Configuration ---
# !!! آدرس ریپازیتوری گیت هاب خود را که ساخته اید، اینجا قرار دهید !!!
GITHUB_REPO_URL="https://github.com/smblue07/my-sync-panel.git"

INSTALL_DIR="/root/ultimate_sync_manager"
SYNC_SCRIPT_PATH="/root/the_final_sync.py"
WHITELIST_FILE="/root/sync_whitelist.txt"
STATE_FILE="/root/sync_state.json"
SERVICE_NAME="sync_manager"

echo "--- Ultimate 3x-ui Sync Manager Installer ---"

# --- Interactive Setup ---
read -p "Enter the port for the web panel (default: 5001): " WEB_PORT
WEB_PORT=${WEB_PORT:-5001}
echo "Web panel will be installed on port: ${WEB_PORT}"

# --- Installation Steps ---
echo "[1/6] Installing dependencies (git, python3-pip, sqlite3)..."
apt update > /dev/null 2>&1
apt install -y git python3-pip sqlite3 > /dev/null 2>&1

echo "[2/6] Installing Python packages (Flask)..."
pip3 install flask > /dev/null 2>&1

echo "[3/6] Cloning project from GitHub..."
if [ -d "${INSTALL_DIR}" ]; then
    echo "Warning: Existing directory found. Removing it."
    rm -rf ${INSTALL_DIR}
fi
git clone ${GITHUB_REPO_URL} ${INSTALL_DIR}
if [ ! -d "${INSTALL_DIR}" ]; then
    echo "Error: Failed to clone the repository. Please check the URL."
    exit 1
fi

echo "[4/6] Creating systemd service file..."
SERVICE_FILE_CONTENT="[Unit]
Description=Sync Manager UI for 3x-ui Panel
After=network.target

[Service]
User=root
WorkingDirectory=${INSTALL_DIR}
Environment=\"SYNC_MANAGER_PORT=${WEB_PORT}\"
ExecStart=/usr/bin/python3 app.py
Restart=always

[Install]
WantedBy=multi-user.target
"
echo "$SERVICE_FILE_CONTENT" > /etc/systemd/system/${SERVICE_NAME}.service

echo "[5/6] Creating initial config files..."
mv ${INSTALL_DIR}/the_final_sync.py ${SYNC_SCRIPT_PATH}
touch ${WHITELIST_FILE}
touch ${STATE_FILE}

echo "[6/6] Enabling service and configuring firewall..."
systemctl daemon-reload
systemctl enable ${SERVICE_NAME} > /dev/null 2>&1
systemctl restart ${SERVICE_NAME}

if command -v ufw &> /dev/null && ufw status | grep -q 'Status: active'; then
    ufw allow ${WEB_PORT}/tcp > /dev/null 2>&1
fi

echo "--- Installation Complete! ---"
echo "You can now access your panel at: http://<YOUR_SERVER_IP>:${WEB_PORT}"
echo "To check the service status, run: systemctl status ${SERVICE_NAME}"
