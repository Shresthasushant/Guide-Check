#!/usr/bin/env bash
# Put Guide Check on a fresh Ubuntu VM, from the submission zip. No Git needed.
#
# On your machine:
#     scp guide-check-app-submission.zip ubuntu@<vm-ip>:~/
#     scp deploy/vm-setup.sh             ubuntu@<vm-ip>:~/
#     ssh ubuntu@<vm-ip> 'bash vm-setup.sh'
#
# The VM needs 2GB of RAM. Measured footprint is 896MB loaded, 1157MB peak
# during startup, so a 1GB instance will be killed by the OOM reaper mid-boot.
# Oracle Cloud's Always Free Ampere instances (up to 24GB) are the usual choice
# for something that has to stay up without a bill.
set -euo pipefail

APP_DIR="$HOME/guide-check"
ZIP="${1:-$HOME/guide-check-app-submission.zip}"

echo "==> packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3.11 python3.11-venv unzip

echo "==> unpacking $ZIP"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
unzip -q "$ZIP" -d "$APP_DIR"

echo "==> virtualenv"
python3.11 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> systemd service"
sudo tee /etc/systemd/system/guide-check.service >/dev/null <<SERVICE
[Unit]
Description=Guide Check
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
Environment=GUIDE_CHECK_PRELOAD=1
# 180s start timeout: the model load takes 30-45s and systemd must not give up
# on it. Restart on failure so a crash does not take the demo down for good.
TimeoutStartSec=180
ExecStart=$APP_DIR/.venv/bin/gunicorn app:app --bind 0.0.0.0:8000 \\
    --workers 1 --threads 4 --timeout 180 --preload
Restart=on-failure

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable --now guide-check

echo "==> waiting for the model to load"
for _ in $(seq 1 60); do
    if curl -sf -o /dev/null http://127.0.0.1:8000/api/suburbs; then
        echo "    up"
        break
    fi
    sleep 3
done

echo
echo "Running on port 8000. Open the port in the provider's firewall, then:"
echo "    http://$(curl -s ifconfig.me 2>/dev/null || echo '<vm-ip>'):8000"
echo
echo "Put it behind HTTPS before you hand the URL in:"
echo "    sudo apt-get install -y caddy"
echo "    sudo caddy reverse-proxy --from <your-domain> --to 127.0.0.1:8000"
echo
echo "Logs:    sudo journalctl -u guide-check -f"
echo "Restart: sudo systemctl restart guide-check"
