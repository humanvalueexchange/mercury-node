#!/usr/bin/env bash
# Mercury Node Installer v0.1
# https://github.com/HansHWestphal/mercury-node
#
# Usage:
#   curl -fsSL https://mercury-node.dev/install | bash
#   curl -fsSL https://mercury-node.dev/install | bash -s -- --snapshot
#   curl -fsSL https://mercury-node.dev/install | bash -s -- --verify

set -euo pipefail

# ─── Constants ────────────────────────────────────────────────────────────────
MERCURY_VERSION="0.1.0"
BITCOIN_VERSION="27.1"
LND_VERSION="0.18.3-beta"
NBXPLORER_VERSION="2.5.0"
BTCPAY_VERSION="2.0.0"
PHI_MODEL_URL="https://huggingface.co/microsoft/Phi-3.5-mini-instruct-gguf/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf"

MIN_RAM_GB=15
MIN_DISK_GB=500
REQUIRED_ARCH="aarch64"

RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
BLU='\033[0;34m'
NC='\033[0m'

SNAPSHOT_MODE=false
VERIFY_ONLY=false

# ─── Argument parsing ─────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --snapshot) SNAPSHOT_MODE=true ;;
    --verify)   VERIFY_ONLY=true ;;
    --help|-h)
      echo "Mercury Node Installer"
      echo "  --snapshot   Use UTXO snapshot for faster IBD (~4h vs ~72h)"
      echo "  --verify     Print all checksums and exit (no install)"
      exit 0 ;;
  esac
done

# ─── Helpers ──────────────────────────────────────────────────────────────────
log()  { echo -e "${BLU}[mercury]${NC} $*"; }
ok()   { echo -e "${GRN}[  ok  ]${NC} $*"; }
warn() { echo -e "${YEL}[ warn ]${NC} $*"; }
fail() { echo -e "${RED}[ FAIL ]${NC} $*"; exit 1; }

banner() {
  echo ""
  echo -e "${BLU}  ███╗   ███╗███████╗██████╗  ██████╗██╗   ██╗██████╗ ██╗   ██╗${NC}"
  echo -e "${BLU}  ████╗ ████║██╔════╝██╔══██╗██╔════╝██║   ██║██╔══██╗╚██╗ ██╔╝${NC}"
  echo -e "${BLU}  ██╔████╔██║█████╗  ██████╔╝██║     ██║   ██║██████╔╝ ╚████╔╝ ${NC}"
  echo -e "${BLU}  ██║╚██╔╝██║██╔══╝  ██╔══██╗██║     ██║   ██║██╔══██╗  ╚██╔╝  ${NC}"
  echo -e "${BLU}  ██║ ╚═╝ ██║███████╗██║  ██║╚██████╗╚██████╔╝██║  ██║   ██║   ${NC}"
  echo -e "${BLU}  ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝  ${NC}"
  echo ""
  echo -e "  ${GRN}Mercury Node v${MERCURY_VERSION}${NC} — AI-first sovereign Bitcoin Lightning node"
  echo ""
}

# ─── Phase 1: Hardware Validation ─────────────────────────────────────────────
phase1_hardware() {
  log "Phase 1/5 — Hardware validation"

  # Architecture
  local arch
  arch=$(uname -m)
  [[ "$arch" == "$REQUIRED_ARCH" ]] || fail "Requires aarch64 (ARM64). Got: $arch"
  ok "Architecture: $arch"

  # RAM
  local ram_kb ram_gb
  ram_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
  ram_gb=$((ram_kb / 1024 / 1024))
  [[ $ram_gb -ge $MIN_RAM_GB ]] || fail "Requires ${MIN_RAM_GB}GB RAM minimum. Got: ${ram_gb}GB. Use Pi 5 16GB."
  ok "RAM: ${ram_gb}GB"

  # Disk
  local disk_gb
  disk_gb=$(df / --output=avail -BG | tail -1 | tr -d 'G ')
  [[ $disk_gb -ge $MIN_DISK_GB ]] || fail "Requires ${MIN_DISK_GB}GB free disk. Got: ${disk_gb}GB."
  ok "Disk: ${disk_gb}GB available"

  # Hailo-8L detection
  if lspci 2>/dev/null | grep -qi hailo; then
    ok "Hailo-8L: detected via PCIe"
  elif ls /dev/hailo* 2>/dev/null | grep -q hailo; then
    ok "Hailo-8L: detected via /dev"
  else
    warn "Hailo-8L not detected. AI features (mercury ask) will be disabled."
    warn "Install Hailo-8L Hat and re-run installer to enable intelligence layer."
    HAILO_AVAILABLE=false
  fi

  ok "Hardware validation passed"
}

# ─── Phase 2: System Foundation ───────────────────────────────────────────────
phase2_system() {
  log "Phase 2/5 — System foundation"

  apt-get update -qq
  apt-get install -y -qq \
    curl wget git build-essential \
    nginx certbot python3-certbot-nginx \
    python3 python3-pip python3-venv \
    jq unzip tar || fail "apt install failed"

  # Create system users
  for user in bitcoin lnd btcpay mercury; do
    id "$user" &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin "$user"
    ok "User: $user"
  done

  # Data directories
  install -d -m 750 -o bitcoin -g bitcoin /var/lib/bitcoind
  install -d -m 750 -o lnd     -g lnd     /var/lib/lnd
  install -d -m 750 -o btcpay  -g btcpay  /var/lib/btcpayserver
  install -d -m 750 -o mercury -g mercury /var/lib/mercury
  install -d -m 755            /usr/local/lib/mercury

  # Hailo drivers (if available)
  if [[ "${HAILO_AVAILABLE:-true}" == "true" ]]; then
    phase2_hailo
  fi

  ok "System foundation ready"
}

phase2_hailo() {
  log "Installing Hailo PCIe drivers (pinned v4.19.0)"
  # Hailo official repo
  wget -qO /tmp/hailo-all_4.19.0_arm64.deb \
    "https://hailo-hailort.s3.amazonaws.com/Hailo8/4.19.0/hailo-all_4.19.0_arm64.deb" || {
    warn "Hailo driver download failed — AI features disabled"
    HAILO_AVAILABLE=false
    return
  }
  dpkg -i /tmp/hailo-all_4.19.0_arm64.deb
  # Pin driver version — prevent kernel update breaking Hailo
  echo "hailo-all hold" | dpkg --set-selections
  ok "Hailo drivers installed and pinned at v4.19.0"
}

# ─── Phase 3: Bitcoin Stack ────────────────────────────────────────────────────
phase3_bitcoin_stack() {
  log "Phase 3/5 — Bitcoin stack"

  phase3_bitcoind
  phase3_lnd
  phase3_nbxplorer
  phase3_btcpayserver
  phase3_nginx

  ok "Bitcoin stack installed"
}

phase3_bitcoind() {
  log "Installing Bitcoin Core v${BITCOIN_VERSION}"
  wget -qO /tmp/bitcoin.tar.gz \
    "https://bitcoincore.org/bin/bitcoin-core-${BITCOIN_VERSION}/bitcoin-${BITCOIN_VERSION}-aarch64-linux-gnu.tar.gz"
  tar -xzf /tmp/bitcoin.tar.gz -C /tmp
  install -m 755 /tmp/bitcoin-${BITCOIN_VERSION}/bin/bitcoind /usr/local/bin/
  install -m 755 /tmp/bitcoin-${BITCOIN_VERSION}/bin/bitcoin-cli /usr/local/bin/

  # Config
  cat > /etc/bitcoin/bitcoin.conf << 'EOF'
mainnet=1
server=1
txindex=0
prune=0
rpcuser=mercury
rpcpassword=CHANGEME_ON_FIRST_BOOT
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
zmqpubrawblock=tcp://127.0.0.1:28332
zmqpubrawtx=tcp://127.0.0.1:28333
EOF
  chmod 640 /etc/bitcoin/bitcoin.conf
  chown bitcoin:bitcoin /etc/bitcoin/bitcoin.conf

  # Systemd
  cp /usr/local/lib/mercury/systemd/bitcoind.service /etc/systemd/system/
  systemctl daemon-reload
  ok "Bitcoin Core v${BITCOIN_VERSION}"
}

phase3_lnd() {
  log "Installing LND v${LND_VERSION}"
  wget -qO /tmp/lnd.tar.gz \
    "https://github.com/lightningnetwork/lnd/releases/download/v${LND_VERSION}/lnd-linux-arm64-v${LND_VERSION}.tar.gz"
  tar -xzf /tmp/lnd.tar.gz -C /tmp
  install -m 755 /tmp/lnd-linux-arm64-v${LND_VERSION}/lnd  /usr/local/bin/
  install -m 755 /tmp/lnd-linux-arm64-v${LND_VERSION}/lncli /usr/local/bin/

  cp /usr/local/lib/mercury/systemd/lnd.service /etc/systemd/system/
  systemctl daemon-reload
  ok "LND v${LND_VERSION}"
}

phase3_nbxplorer() {
  log "Installing NBXplorer v${NBXPLORER_VERSION}"
  # dotnet install + NBXplorer binary omitted for brevity in skeleton
  # Full implementation in scripts/install/install-nbxplorer.sh
  ok "NBXplorer v${NBXPLORER_VERSION} (skeleton)"
}

phase3_btcpayserver() {
  log "Installing BTCPay Server v${BTCPAY_VERSION}"
  # Full implementation in scripts/install/install-btcpay.sh
  ok "BTCPay Server v${BTCPAY_VERSION} (skeleton)"
}

phase3_nginx() {
  log "Configuring nginx"
  cp /usr/local/lib/mercury/config/nginx-mercury.conf /etc/nginx/sites-available/mercury
  ln -sf /etc/nginx/sites-available/mercury /etc/nginx/sites-enabled/
  rm -f /etc/nginx/sites-enabled/default
  nginx -t && systemctl reload nginx
  ok "nginx configured"
}

# ─── Phase 4: Seed Ceremony (Interactive) ─────────────────────────────────────
phase4_seed_ceremony() {
  log "Phase 4/5 — Wallet seed ceremony"
  echo ""
  echo -e "${YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${YEL}  IMPORTANT: Your 24-word seed phrase is about to be generated.${NC}"
  echo -e "${YEL}                                                               ${NC}"
  echo -e "${YEL}  You are the ONLY person on Earth who will control this       ${NC}"
  echo -e "${YEL}  wallet. Write down all 24 words on paper. Store it safely.  ${NC}"
  echo -e "${YEL}  Anyone with these words can take your Bitcoin.               ${NC}"
  echo -e "${YEL}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  read -r -p "Press ENTER when you have paper and pen ready..."

  # Start LND for wallet creation
  systemctl start lnd
  sleep 5

  # Interactive wallet creation
  sudo -u lnd lncli --lnddir=/var/lib/lnd create

  ok "Wallet created. Seed ceremony complete."
}

# ─── Phase 5: Mercury Agent ────────────────────────────────────────────────────
phase5_mercury_agent() {
  log "Phase 5/5 — Mercury agent"

  # Install mercury-agent Python service
  python3 -m venv /var/lib/mercury/venv
  /var/lib/mercury/venv/bin/pip install -q \
    fastapi uvicorn grpcio grpcio-tools requests

  # Deploy agent source
  cp -r /usr/local/lib/mercury/src/agent/* /var/lib/mercury/
  chown -R mercury:mercury /var/lib/mercury

  # Deploy mercury CLI
  install -m 755 /usr/local/lib/mercury/src/cli/mercury /usr/local/bin/mercury

  # Systemd service
  cp /usr/local/lib/mercury/systemd/mercury-agent.service /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable mercury-agent
  systemctl start mercury-agent

  # Download Phi-3.5-mini for Hailo if available
  if [[ "${HAILO_AVAILABLE:-true}" == "true" ]]; then
    log "Downloading Phi-3.5-mini model (~2.2GB) — this may take a few minutes"
    mkdir -p /var/lib/mercury/models
    wget -q --show-progress -O /var/lib/mercury/models/phi-3.5-mini.gguf "$PHI_MODEL_URL"
    chown mercury:mercury /var/lib/mercury/models/phi-3.5-mini.gguf
    ok "Phi-3.5-mini downloaded"
  fi

  ok "Mercury agent running"
}

# ─── Final Report ──────────────────────────────────────────────────────────────
final_report() {
  echo ""
  echo -e "${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GRN}  Mercury Node v${MERCURY_VERSION} installed successfully.              ${NC}"
  echo -e "${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo "  Try it now:"
  echo ""
  echo -e "    ${BLU}mercury status${NC}          — Node health at a glance"
  echo -e "    ${BLU}mercury sync${NC}            — Bitcoin sync progress"
  echo -e "    ${BLU}mercury ask \"hello\"${NC}     — Talk to your node"
  echo ""
  if [[ "$SNAPSHOT_MODE" == "false" ]]; then
    echo -e "  ${YEL}Note:${NC} Bitcoin Core is syncing from genesis. This takes ~72 hours."
    echo       "  Your Lightning node is active now. Chain sync runs in the background."
    echo       "  Run 'mercury sync' to check progress."
  fi
  echo ""
  echo -e "  Docs:   https://github.com/HansHWestphal/mercury-node"
  echo ""
}

# ─── Main ──────────────────────────────────────────────────────────────────────
main() {
  [[ $EUID -eq 0 ]] || fail "Run as root: sudo bash install.sh"

  banner

  if [[ "$VERIFY_ONLY" == "true" ]]; then
    log "Verify mode — printing checksums only, no install"
    # TODO: print all binary checksums
    exit 0
  fi

  phase1_hardware
  phase2_system
  phase3_bitcoin_stack
  phase4_seed_ceremony
  phase5_mercury_agent
  final_report
}

main "$@"
