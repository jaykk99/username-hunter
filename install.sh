#!/bin/bash
# xname-hunter installer - one command, Termux & Linux
#
#   curl -sSL https://raw.githubusercontent.com/jaykk99/username-hunter/main/install.sh | bash
#
# Installs python + deps, fetches the tool to ~/.xname-hunter,
# and links the `xname-hunter` command into your PATH.
#
# Env overrides: XNAME_DIR (install location), BIN_DIR (where the
# command link goes), SKIP_DEPS=1 (skip system package installs).
set -e

REPO_URL="https://github.com/jaykk99/username-hunter"
INSTALL_DIR="${XNAME_DIR:-$HOME/.xname-hunter}"

echo "[*] installing xname-hunter..."

# 1. system packages
if [ -z "$SKIP_DEPS" ]; then
    if command -v pkg >/dev/null 2>&1; then
        echo "[*] Termux detected"
        pkg install -y python git
        BIN_DIR="${BIN_DIR:-$PREFIX/bin}"
    elif command -v apt-get >/dev/null 2>&1; then
        echo "[*] Debian/Ubuntu detected"
        sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip git
    elif command -v dnf >/dev/null 2>&1; then
        echo "[*] Fedora/RHEL detected"
        sudo dnf install -y -q python3 python3-pip git
    elif command -v pacman >/dev/null 2>&1; then
        echo "[*] Arch detected"
        sudo pacman -S --noconfirm python python-pip git
    elif command -v apk >/dev/null 2>&1; then
        echo "[*] Alpine detected"
        sudo apk add python3 py3-pip git
    else
        echo "[!] unknown distro - install python3, pip and git yourself, then re-run"
        exit 1
    fi
fi

# 2. python deps
if command -v pip3 >/dev/null 2>&1; then PIP=pip3; else PIP=pip; fi
$PIP install -q requests 2>/dev/null \
    || $PIP install -q --break-system-packages requests 2>/dev/null \
    || true

# 3. fetch or update the tool
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "[*] updating existing install..."
    git -C "$INSTALL_DIR" pull -q
else
    rm -rf "$INSTALL_DIR"
    git clone -q "$REPO_URL" "$INSTALL_DIR"
fi
chmod +x "$INSTALL_DIR/username_hunter.py"

# 4. pick a bin dir on PATH
SUDO=""
if [ -z "$BIN_DIR" ]; then
    if [ -w /usr/local/bin ]; then
        BIN_DIR=/usr/local/bin
    elif command -v sudo >/dev/null 2>&1; then
        BIN_DIR=/usr/local/bin
        SUDO=sudo
    else
        BIN_DIR="$HOME/.local/bin"
        mkdir -p "$BIN_DIR"
    fi
fi

# 5. link the command
$SUDO ln -sf "$INSTALL_DIR/username_hunter.py" "$BIN_DIR/xname-hunter"

echo "[+] done."
case ":$PATH:" in
    *":$BIN_DIR:"*) echo "[+] run it: xname-hunter <username>" ;;
    *) echo "[!] $BIN_DIR is not on your PATH - run: $BIN_DIR/xname-hunter <username>" ;;
esac
