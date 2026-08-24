#!/usr/bin/env bash
# Mercury Node installer
#
# This installer intentionally installs only the components that are present in
# this repository and whose upstream artifacts can be verified.  BTCPay Server,
# NBXplorer, llama.cpp, and accelerator/model drivers are not installed here.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

MERCURY_VERSION="0.10.0"
BITCOIN_VERSION="30.2"
LND_VERSION="0.20.1-beta"
BITCOIN_SHA256="73e76c14edc79808a0511c744d102ffbb494807ee90cbcba176568243254b532"
LND_SHA256="013489343eebe8b0213b5f52fc7570e6f873f3f17974826cb94125ee1287d306"

MIN_RAM_GB=16
MIN_DISK_GB=1000
INSTALL_ROOT="/opt/mercury"
BITCOIN_DATADIR="${MERCURY_BITCOIN_DATADIR:-/var/lib/bitcoin}"
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
fi
SOURCE_DIR="${MERCURY_SOURCE_DIR:-$SCRIPT_DIR}"
DOWNLOAD_DIR="${INSTALL_ROOT}/downloads"
BITCOIN_CONF="/etc/bitcoin/bitcoin.conf"
LND_CONF="/var/lib/lnd/lnd.conf"
AGENT_ENV="/etc/mercury/agent.env"

RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
BLU='\033[0;34m'
NC='\033[0m'

VERIFY_ONLY=false
BITCOIN_RPC_USER="mercury"
BITCOIN_RPC_PASSWORD=""

log()  { printf '%b[mercury]%b %s\n' "$BLU" "$NC" "$*"; }
ok()   { printf '%b[  ok  ]%b %s\n' "$GRN" "$NC" "$*"; }
warn() { printf '%b[ warn ]%b %s\n' "$YEL" "$NC" "$*"; }
die()  { printf '%b[ FAIL ]%b %s\n' "$RED" "$NC" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Mercury Node installer

Usage:
  sudo bash install.sh [--verify]

Options:
  --verify       Verify an existing installation without changing it.
  --help         Show this help.

The installer must run from a Mercury Node checkout.  For stdin/curl use:
  MERCURY_SOURCE_DIR=/path/to/mercury-node sudo -E bash install.sh

BTCPay Server, NBXplorer, llama.cpp, model downloads, Hailo drivers, and
Bitcoin UTXO snapshots are unsupported by this installer and are never
silently reported as installed.
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

parse_args() {
  while (($#)); do
    case "$1" in
      --verify) VERIFY_ONLY=true ;;
      --help|-h) usage; exit 0 ;;
      --snapshot|--with-btcpay|--with-nbxplorer|--with-llama)
        die "$1 is unsupported: no verified implementation is included; refusing to continue"
        ;;
      *) die "Unknown option: $1 (use --help)" ;;
    esac
    shift
  done
}

check_root() {
  [[ "$EUID" -eq 0 ]] || die "Run as root: sudo bash install.sh"
}

check_source_tree() {
  [[ -n "$SOURCE_DIR" && -d "$SOURCE_DIR" ]] ||
    die "Mercury source checkout not found; set MERCURY_SOURCE_DIR to its path"
  [[ -f "$SOURCE_DIR/src/agent/main.py" ]] ||
    die "Missing source file: src/agent/main.py"
  [[ -f "$SOURCE_DIR/src/agent/requirements.txt" ]] ||
    die "Missing source file: src/agent/requirements.txt"
  [[ -f "$SOURCE_DIR/src/cli/mercury" ]] ||
    die "Missing source file: src/cli/mercury"
  [[ -d "$SOURCE_DIR/src/cli/mercury_cli" ]] ||
    die "Missing source package: src/cli/mercury_cli"
}

phase_hardware() {
  log "Validating Debian 13 ARM64 Raspberry Pi host"
  require_cmd uname
  require_cmd awk
  require_cmd df

  [[ "$(uname -m)" == "aarch64" ]] ||
    die "Requires ARM64/aarch64; found $(uname -m)"

  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "debian" && "${VERSION_ID:-}" == "13" ]] ||
    die "Requires Debian 13 (trixie); found ${PRETTY_NAME:-unknown}"

  local model ram_kb ram_gb disk_gb
  model="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)"
  [[ "$model" =~ Raspberry[[:space:]]+Pi ]] ||
    die "Requires a Raspberry Pi deployment; found ${model:-unknown platform}"
  [[ "$model" =~ Raspberry[[:space:]]+Pi[[:space:]]+5 ]] ||
    die "Requires Raspberry Pi 5 hardware; found ${model:-unknown model}"
  ok "Platform: $model"

  ram_kb="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)"
  ram_gb=$((ram_kb / 1024 / 1024))
  ((ram_gb >= MIN_RAM_GB)) ||
    die "Requires at least ${MIN_RAM_GB}GiB RAM; found ${ram_gb}GiB"
  ok "Memory: ${ram_gb}GiB"

  disk_gb="$(df -P -BG / | awk 'NR == 2 {gsub(/G/, "", $4); print $4}')"
  ((disk_gb >= MIN_DISK_GB)) ||
    die "Requires at least ${MIN_DISK_GB}GiB free on /; found ${disk_gb}GiB"
  ok "Free storage: ${disk_gb}GiB"
}

ensure_user() {
  local name="$1" home="$2"
  if ! id "$name" >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$home" \
      --shell /usr/sbin/nologin "$name"
  fi
  id "$name" >/dev/null 2>&1 || die "Could not create service user: $name"
}

phase_packages_and_layout() {
  log "Installing Debian prerequisites and creating service layout"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl python3 python3-venv tar xz-utils systemd

  [[ "$BITCOIN_DATADIR" == /* && "$BITCOIN_DATADIR" != *[[:space:]]* ]] ||
    die "MERCURY_BITCOIN_DATADIR must be an absolute path without whitespace"

  ensure_user bitcoin "$BITCOIN_DATADIR"
  ensure_user lnd /var/lib/lnd
  ensure_user mercury /var/lib/mercury

  install -d -m 0755 -o root -g root "$INSTALL_ROOT"
  install -d -m 0755 -o root -g root "$DOWNLOAD_DIR"
  install -d -m 0750 -o bitcoin -g bitcoin "$BITCOIN_DATADIR"
  install -d -m 0750 -o lnd -g lnd /var/lib/lnd
  install -d -m 0700 -o lnd -g lnd /var/lib/mercury /var/lib/mercury/backups
  install -d -m 0755 -o root -g root /etc/bitcoin /etc/mercury
  ok "Filesystem layout: $INSTALL_ROOT, /var/lib/lnd, /var/lib/mercury"
}

download_verified() {
  local url="$1" expected="$2" destination="$3" actual
  if [[ -e "$destination" ]]; then
    [[ -f "$destination" ]] || die "Download path is not a regular file: $destination"
  else
    log "Downloading $(basename "$destination")"
    curl --fail --location --proto '=https' --tlsv1.2 --silent --show-error \
      --output "$destination" "$url"
    chmod 0644 "$destination"
  fi
  actual="$(sha256sum "$destination" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] ||
    die "Checksum mismatch for $(basename "$destination"); refusing to use it"
  ok "Verified $(basename "$destination")"
}

install_archive_member() {
  local archive="$1" member="$2" destination="$3"
  tar -tzf "$archive" | grep -Fqx "$member" ||
    die "Expected member missing from $(basename "$archive"): $member"
  tar -xOzf "$archive" "$member" | install -o root -g root -m 0755 /dev/stdin "$destination"
}

phase_bitcoin() {
  local archive
  archive="$DOWNLOAD_DIR/bitcoin-${BITCOIN_VERSION}-aarch64-linux-gnu.tar.gz"
  download_verified \
    "https://bitcoincore.org/bin/bitcoin-core-${BITCOIN_VERSION}/$(basename "$archive")" \
    "$BITCOIN_SHA256" "$archive"
  install_archive_member "$archive" \
    "bitcoin-${BITCOIN_VERSION}/bin/bitcoind" /usr/local/bin/bitcoind
  install_archive_member "$archive" \
    "bitcoin-${BITCOIN_VERSION}/bin/bitcoin-cli" /usr/local/bin/bitcoin-cli
  ok "Bitcoin Core ${BITCOIN_VERSION} binaries installed"
}

phase_lnd() {
  local archive
  archive="$DOWNLOAD_DIR/lnd-linux-arm64-v${LND_VERSION}.tar.gz"
  download_verified \
    "https://github.com/lightningnetwork/lnd/releases/download/v${LND_VERSION}/$(basename "$archive")" \
    "$LND_SHA256" "$archive"
  install_archive_member "$archive" \
    "lnd-linux-arm64-v${LND_VERSION}/lnd" /usr/local/bin/lnd
  install_archive_member "$archive" \
    "lnd-linux-arm64-v${LND_VERSION}/lncli" /usr/local/bin/lncli
  ok "LND ${LND_VERSION} binaries installed"
}

config_value() {
  local key="$1" file="$2"
  awk -F= -v key="$key" '
    $1 == key {
      sub(/^[^=]*=/, "", $0)
      print $0
      exit
    }
  ' "$file"
}

write_bitcoin_config() {
  if [[ -e "$BITCOIN_CONF" ]]; then
    BITCOIN_RPC_USER="$(config_value rpcuser "$BITCOIN_CONF")"
    BITCOIN_RPC_PASSWORD="$(config_value rpcpassword "$BITCOIN_CONF")"
    [[ -n "$BITCOIN_RPC_USER" && ${#BITCOIN_RPC_PASSWORD} -ge 32 ]] ||
      die "$BITCOIN_CONF exists without a usable rpcuser/rpcpassword; refusing to alter it"
    warn "Preserving existing $BITCOIN_CONF"
    return
  fi

  BITCOIN_RPC_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  cat > "$BITCOIN_CONF" <<EOF
# Managed by Mercury Node installer.  Do not share this file.
chain=main
server=1
txindex=1
prune=0
datadir=${BITCOIN_DATADIR}
rpcuser=${BITCOIN_RPC_USER}
rpcpassword=${BITCOIN_RPC_PASSWORD}
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
zmqpubrawblock=tcp://127.0.0.1:28332
zmqpubrawtx=tcp://127.0.0.1:28333
EOF
  chown bitcoin:bitcoin "$BITCOIN_CONF"
  chmod 0640 "$BITCOIN_CONF"
  ok "Created protected Bitcoin Core configuration"
}

write_lnd_config() {
  if [[ -e "$LND_CONF" ]]; then
    warn "Preserving existing $LND_CONF"
    return
  fi
  cat > "$LND_CONF" <<EOF
# Managed by Mercury Node installer.  Keep this file readable only by lnd.
bitcoin.active=1
bitcoin.mainnet=1
bitcoin.node=bitcoind
bitcoind.rpchost=127.0.0.1:8332
bitcoind.rpcuser=${BITCOIN_RPC_USER}
bitcoind.rpcpass=${BITCOIN_RPC_PASSWORD}
bitcoind.zmqpubrawblock=tcp://127.0.0.1:28332
bitcoind.zmqpubrawtx=tcp://127.0.0.1:28333
listen=0.0.0.0:9735
rpclisten=127.0.0.1:10009
restlisten=127.0.0.1:8080
EOF
  chown lnd:lnd "$LND_CONF"
  chmod 0600 "$LND_CONF"
  ok "Created protected LND configuration"
}

install_source_file() {
  local source="$1" destination="$2" mode="$3"
  install -o root -g root -m "$mode" "$source" "$destination"
}

install_source_tree() {
  local source_root="$1" destination_root="$2" file relative mode
  while IFS= read -r -d '' file; do
    relative="${file#"$source_root"/}"
    mode=0644
    [[ "$relative" == "mercury" ]] && mode=0755
    install -D -o root -g root -m "$mode" "$file" "$destination_root/$relative"
  done < <(find "$source_root" -type f -print0)
}

phase_mercury() {
  log "Installing Mercury agent, CLI, and Python requirements"
  install -d -m 0755 -o root -g root \
    "$INSTALL_ROOT/agent" "$INSTALL_ROOT/cli"
  install_source_file "$SOURCE_DIR/src/agent/main.py" \
    "$INSTALL_ROOT/agent/main.py" 0644
  install_source_file "$SOURCE_DIR/src/agent/requirements.txt" \
    "$INSTALL_ROOT/agent/requirements.txt" 0644
  install_source_file "$SOURCE_DIR/src/cli/mercury" \
    "$INSTALL_ROOT/cli/mercury" 0755
  install_source_tree "$SOURCE_DIR/src/cli/mercury_cli" \
    "$INSTALL_ROOT/cli/mercury_cli"
  if [[ -e /usr/local/bin/mercury && ! -L /usr/local/bin/mercury ]]; then
    die "Refusing to replace an unmanaged file: /usr/local/bin/mercury"
  fi
  if [[ -L /usr/local/bin/mercury &&
        "$(readlink /usr/local/bin/mercury)" != "$INSTALL_ROOT/cli/mercury" ]]; then
    die "Refusing to replace an unmanaged symlink: /usr/local/bin/mercury"
  fi
  ln -sfn "$INSTALL_ROOT/cli/mercury" /usr/local/bin/mercury

  if [[ ! -x "$INSTALL_ROOT/venv/bin/python" ]]; then
    python3 -m venv "$INSTALL_ROOT/venv"
  fi
  "$INSTALL_ROOT/venv/bin/python" -m pip install --disable-pip-version-check \
    --no-input --requirement "$INSTALL_ROOT/agent/requirements.txt"

  if [[ ! -e "$AGENT_ENV" ]]; then
    install -o root -g root -m 0600 /dev/null "$AGENT_ENV"
  else
    warn "Preserving existing $AGENT_ENV; installer never writes secrets there"
  fi
  ok "Mercury source installed under $INSTALL_ROOT"
}

write_unit() {
  local path="$1"
  if [[ -e "$path" ]] && ! grep -Fq "Managed by Mercury Node installer" "$path"; then
    die "Refusing to replace an unmanaged systemd unit: $path"
  fi
  cat > "$path"
  chmod 0644 "$path"
}

phase_systemd() {
  log "Installing systemd units"
  write_unit /etc/systemd/system/bitcoind.service <<EOF
# Managed by Mercury Node installer
[Unit]
Description=Bitcoin Core
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bitcoin
Group=bitcoin
ExecStart=/usr/local/bin/bitcoind -datadir=${BITCOIN_DATADIR} -conf=${BITCOIN_CONF} -pid=/run/bitcoind/bitcoind.pid
ExecStop=/usr/local/bin/bitcoin-cli -datadir=${BITCOIN_DATADIR} -conf=${BITCOIN_CONF} stop
RuntimeDirectory=bitcoind
RuntimeDirectoryMode=0750
Restart=on-failure
RestartSec=10
TimeoutStartSec=infinity
TimeoutStopSec=120
LimitNOFILE=65536
NoNewPrivileges=yes
PrivateDevices=yes
ProtectHome=yes
ReadWritePaths=${BITCOIN_DATADIR} /run/bitcoind

[Install]
WantedBy=multi-user.target
EOF

  write_unit /etc/systemd/system/lnd.service <<'EOF'
# Managed by Mercury Node installer
[Unit]
Description=Lightning Network Daemon
After=bitcoind.service
Requires=bitcoind.service

[Service]
Type=simple
User=lnd
Group=lnd
ExecStart=/usr/local/bin/lnd --lnddir=/var/lib/lnd
ExecStop=/usr/local/bin/lncli --lnddir=/var/lib/lnd stop
Restart=on-failure
RestartSec=10
TimeoutStopSec=120
NoNewPrivileges=yes
PrivateDevices=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/lnd

[Install]
WantedBy=multi-user.target
EOF

  write_unit /etc/systemd/system/mercury-agent.service <<'EOF'
# Managed by Mercury Node installer
[Unit]
Description=Mercury Agent API
Documentation=https://github.com/HansHWestphal/mercury-node
After=network-online.target lnd.service
Requires=lnd.service

[Service]
Type=simple
User=lnd
Group=lnd
WorkingDirectory=/opt/mercury/agent
EnvironmentFile=-/etc/mercury/agent.env
ExecStart=/opt/mercury/venv/bin/python /opt/mercury/agent/main.py
Restart=on-failure
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/mercury /var/lib/lnd
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mercury-agent

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable bitcoind.service lnd.service mercury-agent.service
  ok "Systemd units installed and enabled (services are not started automatically)"
}

verify_installation() {
  log "Verifying installed artifacts and service definitions"
  local bitcoin_version lnd_version
  require_cmd sha256sum
  require_cmd systemctl
  require_cmd systemd-analyze

  [[ -x /usr/local/bin/bitcoind && -x /usr/local/bin/bitcoin-cli ]] ||
    die "Bitcoin Core binaries are missing"
  [[ -x /usr/local/bin/lnd && -x /usr/local/bin/lncli ]] ||
    die "LND binaries are missing"
  [[ -x "$INSTALL_ROOT/cli/mercury" && -d "$INSTALL_ROOT/cli/mercury_cli" ]] ||
    die "Mercury CLI or mercury_cli package is missing"
  [[ -x "$INSTALL_ROOT/venv/bin/python" ]] ||
    die "Mercury Python virtual environment is missing"

  bitcoin_version="$(/usr/local/bin/bitcoind --version 2>&1 | head -n 1)"
  [[ "$bitcoin_version" == *"30.2"* ]] ||
    die "Unexpected Bitcoin Core version: $bitcoin_version"
  lnd_version="$(/usr/local/bin/lnd --version 2>&1 | head -n 1)"
  [[ "$lnd_version" == *"0.20.1-beta"* ]] ||
    die "Unexpected LND version: $lnd_version"

  PYTHONPATH="$INSTALL_ROOT/agent" "$INSTALL_ROOT/venv/bin/python" -c \
    'import fastapi, httpx, uvicorn; import main' \
    >/dev/null 2>&1 ||
    die "Mercury agent dependency/import verification failed"
  PYTHONPATH="$INSTALL_ROOT/cli" "$INSTALL_ROOT/venv/bin/python" \
    "$INSTALL_ROOT/cli/mercury" --help >/dev/null ||
    die "Mercury CLI verification failed"

  systemd-analyze verify \
    /etc/systemd/system/bitcoind.service \
    /etc/systemd/system/lnd.service \
    /etc/systemd/system/mercury-agent.service
  systemctl is-enabled bitcoind.service lnd.service mercury-agent.service >/dev/null
  [[ "$(stat -c '%a' "$LND_CONF")" == "600" ]] ||
    die "LND configuration permissions are not 0600"
  [[ "$(stat -c '%a' "$BITCOIN_CONF")" == "640" ]] ||
    die "Bitcoin configuration permissions are not 0640"
  [[ "$(stat -c '%U:%G' "$LND_CONF")" == "lnd:lnd" ]] ||
    die "LND configuration ownership is not lnd:lnd"
  [[ "$(stat -c '%U:%G' "$BITCOIN_CONF")" == "bitcoin:bitcoin" ]] ||
    die "Bitcoin configuration ownership is not bitcoin:bitcoin"
  ok "Binaries, Python imports, CLI, configs, and systemd units verified"
}

final_report() {
  cat <<EOF

Mercury Node ${MERCURY_VERSION} installed under ${INSTALL_ROOT}.

Installed:
  Bitcoin Core ${BITCOIN_VERSION} (enabled, not started)
  LND ${LND_VERSION} (enabled, not started)
  Mercury Agent API (enabled, not started)
  mercury CLI and mercury_cli package

Before starting LND, complete its wallet creation/seed ceremony locally:
  sudo systemctl start bitcoind
  sudo systemctl start lnd
  sudo -u lnd lncli --lnddir=/var/lib/lnd create

Unsupported and not installed: BTCPay Server, NBXplorer, llama.cpp, model
downloads, Hailo drivers, nginx configuration, and UTXO snapshots.
Run 'sudo bash install.sh --verify' to repeat verification.
EOF
}

main() {
  parse_args "$@"
  check_root
  if [[ "$VERIFY_ONLY" == "true" ]]; then
    verify_installation
    exit 0
  fi
  check_source_tree
  phase_hardware
  phase_packages_and_layout
  phase_bitcoin
  phase_lnd
  write_bitcoin_config
  write_lnd_config
  phase_mercury
  phase_systemd
  verify_installation
  final_report
}

main "$@"
