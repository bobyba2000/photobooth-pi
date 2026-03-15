#!/bin/bash

cd /home/pi/photobooth-pi || exit

if /usr/bin/git pull origin main | grep -q "Already up to date."; then
    echo "No updates found"
else
    echo "Update detected, restarting service"
    sudo /bin/systemctl restart server.service
fi