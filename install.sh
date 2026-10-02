#!/bin/bash
# install.sh - one-shot setup for Termux (Android) and Linux
set -e

if command -v pkg >/dev/null 2>&1; then
    echo "[*] Termux detected"
    pkg install -y python
elif command -v apt-get >/dev/null 2>&1; then
    echo "[*] Debian/Ubuntu detected"
    sudo apt-get update && sudo apt-get install -y python3 python3-pip
elif command -v dnf >/dev/null 2>&1; then
    echo "[*] Fedora/RHEL detected"
    sudo dnf install -y python3 python3-pip
elif command -v pacman >/dev/null 2>&1; then
    echo "[*] Arch detected"
    sudo pacman -S --noconfirm python python-pip
elif command -v apk >/dev/null 2>&1; then
    echo "[*] Alpine detected"
    sudo apk add python3 py3-pip
else
    echo "[!] Unknown distro - install Python 3 yourself, then run: pip install requests"
    exit 1
fi

pip install requests
echo "[+] Done. Run: python3 username_hunter.py <username>"
