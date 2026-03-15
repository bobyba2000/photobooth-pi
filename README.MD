Download setup:
https://drive.google.com/drive/folders/129H4RJmpxrxZkUlFvJhOewMgt4k5RSf7?usp=sharing

# Auto Update Setup (GitHub → Raspberry Pi)

This project can automatically pull updates from GitHub every **5 minutes** and restart the service **only when new code is available**.

Project directory:

```
/home/pi/Desktop
```

Systemd service:

```
server.service
```

---

# 1. Create the Update Script

Create the update script:

```bash
nano /home/pi/photobooth-pi/update.sh
```

Paste the following:

```bash
#!/bin/bash

cd /home/pi/photobooth-pi || exit

# Pull latest code
if /usr/bin/git pull origin main | grep -q "Already up to date."; then
    echo "No updates found"
else
    echo "Update detected, restarting service"
    sudo systemctl restart server.service
fi
```

Save and exit.

---

# 2. Make Script Executable

Run:

```bash
chmod +x /home/pi/photobooth-pi/update.sh
```

---

# 3. Add Cron Job

Open cron editor:

```bash
crontab -e
```

Add this line:

```bash
*/5 * * * * /home/pi/photobooth-pi/update.sh >> /home/pi/update.log 2>&1
```

Meaning:

```
*/5 * * * *
│
└── Runs every 5 minutes
```

Cron will now:

1. Navigate to `/home/pi/Desktop`
2. Run `git pull`
3. Check if the repository changed
4. Restart `server.service` only when updates exist

---

# 4. Ensure Service Exists

Make sure the service is installed and enabled:

```bash
sudo systemctl daemon-reload
sudo systemctl enable server.service
sudo systemctl start server.service
```

Check status:

```bash
systemctl status server.service
```

---

# 5. Verify Cron Is Running

List cron jobs:

```bash
crontab -l
```

You should see:

```
*/5 * * * * /home/pi/update.sh
```

---

# Result

Every **5 minutes** the system will:

```
GitHub → git pull → detect changes → restart server.service
```

If no changes exist, the service continues running normally.

---

# Optional: View Logs

Check service logs:

```bash
journalctl -u server.service -f
```

Check cron logs:

```bash
grep CRON /var/log/syslog
```

test1