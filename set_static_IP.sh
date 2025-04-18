#!/bin/bash

# Set a static IP for eth0 or wlan0 on a Raspberry Pi using dhcpcd.conf
# Before launching this script, you must make it executable by running: chmod +x set_static_ip.sh
# Then run it with root: sudo ./set_static_ip.sh
# This script is intended for Raspberry Pi OS and may not work on other distributions.


# === CONFIGURE HERE ===
INTERFACE="eth0"                   # Change to wlan0 for Wi-Fi
STATIC_IP="192.168.1.42"           # Desired static IP
ROUTER_IP="192.168.1.1"            # Usually your gateway
DNS="8.8.8.8 1.1.1.1"              # Google and Cloudflare DNS
# =======================

DHCPCD_FILE="/etc/dhcpcd.conf"

echo "Configuring static IP on $INTERFACE..."

# Backup dhcpcd.conf
sudo cp "$DHCPCD_FILE" "${DHCPCD_FILE}.bak"

# Remove previous static IP config for the interface
sudo sed -i "/^interface $INTERFACE/,+5d" "$DHCPCD_FILE"

# Append new static config
echo -e "\ninterface $INTERFACE\nstatic ip_address=$STATIC_IP/24\nstatic routers=$ROUTER_IP\nstatic domain_name_servers=$DNS" | sudo tee -a "$DHCPCD_FILE"

echo "   Static IP configuration applied:"
echo "   Interface: $INTERFACE"
echo "   IP:        $STATIC_IP"
echo "   Router:    $ROUTER_IP"
echo "   DNS:       $DNS"

echo "Restarting dhcpcd service..."
sudo systemctl restart dhcpcd

echo "Done. You may need to reconnect to this device at $STATIC_IP."
