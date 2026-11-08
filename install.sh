#!/bin/bash

################################################################################
# Global UPC Installation Script
# Version: 1.0.0
# Description: Automated installation, update, and removal script for Global UPC
# OS: Ubuntu 24.04 LTS
################################################################################

set -e  # Exit on error

# bash reads a script while it runs it, and an update rewrites this very file
# (git pull). Run from a private copy so the pull can never change the code
# being executed mid-way.
if [[ -z "${GLOBALUPC_SELF_COPY:-}" ]]; then
    _self_copy="$(mktemp /tmp/globalupc-install.XXXXXX)"
    cp "$0" "$_self_copy"
    export GLOBALUPC_SELF_COPY="$_self_copy"
    exec bash "$_self_copy" "$@"
fi
trap 'rm -f "${GLOBALUPC_SELF_COPY}"' EXIT

################################################################################
# Configuration Variables
################################################################################

APP_NAME="Global UPC"
INSTALL_DIR="/opt/globalupc"
REPO_URL="https://github.com/ruolez/GlobalUPC.git"
GITHUB_BRANCH="main"
LOG_FILE="${INSTALL_DIR}/install.log"
ENV_FILE="${INSTALL_DIR}/.env"
COMPOSE_FILE="${INSTALL_DIR}/docker-compose.prod.yml"

# Container names
CONTAINER_BACKEND="globalupc_backend"
CONTAINER_FRONTEND="globalupc_frontend"
CONTAINER_DB="globalupc_db"

# Volume names
VOLUME_POSTGRES="globalupc_postgres_data"

# Backups (pg_dump custom format)
BACKUP_DIR="${INSTALL_DIR}/backups"
BACKUP_KEEP_DAILY=7
BACKUP_KEEP_WEEKLY=4
CRON_FILE="/etc/cron.d/globalupc-backup"

################################################################################
# Color Codes
################################################################################

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

################################################################################
# Utility Functions
################################################################################

# Print colored messages
print_header() {
    echo -e "\n${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}${BOLD}  $1${NC}"
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Log function
log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] $1" | tee -a "${LOG_FILE}" 2>/dev/null || echo "[${timestamp}] $1"
}

# Error handler
error_exit() {
    print_error "$1"
    log "ERROR: $1"
    exit 1
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error_exit "This script must be run as root. Please use 'sudo ./install.sh'"
    fi
}

# Prompt for yes/no
confirm() {
    local prompt="$1"
    local default="${2:-n}"

    if [[ "$default" == "y" ]]; then
        prompt="$prompt [Y/n]: "
    else
        prompt="$prompt [y/N]: "
    fi

    read -p "$prompt" response
    response=${response:-$default}

    [[ "$response" =~ ^[Yy]$ ]]
}

################################################################################
# System Requirements Check
################################################################################

check_os() {
    print_info "Checking operating system..."

    if [[ ! -f /etc/os-release ]]; then
        error_exit "Cannot detect OS. This script is designed for Ubuntu 24.04."
    fi

    source /etc/os-release

    if [[ "$ID" != "ubuntu" ]]; then
        print_warning "This script is designed for Ubuntu, but detected: $ID"
        if ! confirm "Do you want to continue anyway?"; then
            exit 0
        fi
    fi

    print_success "OS detected: $PRETTY_NAME"
    log "OS: $PRETTY_NAME"
}

check_internet() {
    print_info "Checking internet connectivity..."

    # Use curl instead of ping - more reliable as ICMP is often blocked by firewalls
    if curl -s --head --connect-timeout 5 https://github.com &> /dev/null; then
        print_success "Internet connection active"
    elif curl -s --head --connect-timeout 5 https://google.com &> /dev/null; then
        print_success "Internet connection active"
    else
        error_exit "No internet connection. Please check your network."
    fi
}

check_command() {
    command -v "$1" &> /dev/null
}

install_docker() {
    print_header "Installing Docker"

    print_info "Updating package index..."
    apt-get update -qq

    print_info "Installing prerequisites..."
    apt-get install -y -qq \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

    print_info "Adding Docker's official GPG key..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    print_info "Setting up Docker repository..."
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

    print_info "Installing Docker Engine..."
    apt-get update -qq
    apt-get install -y -qq \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin

    print_info "Starting Docker service..."
    systemctl start docker
    systemctl enable docker

    print_success "Docker installed successfully"
    log "Docker installed: $(docker --version)"
}

check_docker() {
    print_info "Checking for Docker..."

    if check_command docker; then
        local docker_version=$(docker --version 2>/dev/null || echo "unknown")
        print_success "Docker found: $docker_version"
        log "Docker: $docker_version"
    else
        print_warning "Docker not found"
        if confirm "Would you like to install Docker now?" "y"; then
            install_docker
        else
            error_exit "Docker is required to run ${APP_NAME}"
        fi
    fi

    # Check if Docker daemon is running
    if ! docker ps &> /dev/null; then
        print_warning "Docker daemon is not running"
        print_info "Starting Docker service..."
        systemctl start docker

        if ! docker ps &> /dev/null; then
            error_exit "Failed to start Docker daemon"
        fi
        print_success "Docker daemon started"
    fi
}

check_docker_compose() {
    print_info "Checking for Docker Compose..."

    if docker compose version &> /dev/null; then
        local compose_version=$(docker compose version 2>/dev/null || echo "unknown")
        print_success "Docker Compose found: $compose_version"
        log "Docker Compose: $compose_version"
    else
        error_exit "Docker Compose plugin not found. Please install Docker Compose."
    fi
}

install_git() {
    print_info "Installing Git..."
    apt-get update -qq
    apt-get install -y -qq git
    print_success "Git installed successfully"
}

check_git() {
    print_info "Checking for Git..."

    if check_command git; then
        local git_version=$(git --version)
        print_success "Git found: $git_version"
        log "Git: $git_version"
    else
        print_warning "Git not found"
        if confirm "Would you like to install Git now?" "y"; then
            install_git
        else
            error_exit "Git is required to install ${APP_NAME}"
        fi
    fi
}

check_requirements() {
    print_header "Checking System Requirements"

    check_os
    check_internet
    check_docker
    check_docker_compose
    check_git

    print_success "All system requirements met"
}

################################################################################
# Previous Installation Detection
################################################################################

detect_containers() {
    local containers=$(docker ps -a --filter "name=globalupc_" --format "{{.Names}}" 2>/dev/null)
    if [[ -n "$containers" ]]; then
        return 0
    else
        return 1
    fi
}

detect_volumes() {
    local volumes=$(docker volume ls --filter "name=globalupc_" --format "{{.Name}}" 2>/dev/null)
    if [[ -n "$volumes" ]]; then
        return 0
    else
        return 1
    fi
}

detect_installation() {
    if [[ -d "$INSTALL_DIR" ]] || detect_containers || detect_volumes; then
        return 0
    else
        return 1
    fi
}

show_existing_installation() {
    print_header "Existing Installation Detected"

    if [[ -d "$INSTALL_DIR" ]]; then
        print_info "Installation directory: ${INSTALL_DIR}"
    fi

    if detect_containers; then
        print_info "Containers found:"
        docker ps -a --filter "name=globalupc_" --format "  - {{.Names}} ({{.Status}})"
    fi

    if detect_volumes; then
        print_info "Volumes found:"
        docker volume ls --filter "name=globalupc_" --format "  - {{.Name}}"
    fi

    echo ""
}

################################################################################
# Configuration Functions
################################################################################

validate_ip() {
    local ip=$1
    local valid_ip_regex="^([0-9]{1,3}\.){3}[0-9]{1,3}$"
    local valid_hostname_regex="^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"

    if [[ $ip =~ $valid_ip_regex ]]; then
        # Validate each octet
        local IFS='.'
        read -ra OCTETS <<< "$ip"
        for octet in "${OCTETS[@]}"; do
            if ((octet > 255)); then
                return 1
            fi
        done
        return 0
    elif [[ $ip =~ $valid_hostname_regex ]]; then
        return 0
    else
        return 1
    fi
}

prompt_for_ip() {
    local default_ip=$(hostname -I | awk '{print $1}')

    print_header "Network Configuration"

    echo "Enter the IP address or hostname where this server will be accessible."
    echo "This will be used for:"
    echo "  • Frontend URL: http://{IP} (port 80)"
    echo "  • Backend API: http://{IP}:8001"
    echo ""

    if [[ -n "$default_ip" ]]; then
        print_info "Detected IP address: ${default_ip}"
    fi

    while true; do
        read -p "Enter server IP or hostname [${default_ip}]: " SERVER_IP
        SERVER_IP=${SERVER_IP:-$default_ip}

        if validate_ip "$SERVER_IP"; then
            print_success "Valid address: ${SERVER_IP}"
            break
        else
            print_error "Invalid IP address or hostname. Please try again."
        fi
    done

    export SERVER_IP
    log "Server IP configured: ${SERVER_IP}"
}

create_env_file() {
    print_info "Creating environment configuration file..."

    cat > "${ENV_FILE}" << EOF
# Global UPC Environment Configuration
# Generated: $(date '+%Y-%m-%d %H:%M:%S')

# Server Network Configuration
SERVER_IP=${SERVER_IP}

# Database Configuration
POSTGRES_USER=globalupc
POSTGRES_PASSWORD=globalupc
POSTGRES_DB=globalupc

# Backend Configuration
BACKEND_PORT=8001

# Frontend Configuration (Port 80 for production)
FRONTEND_PORT=80

# Database Port (mapped from container)
DB_PORT=5433
EOF

    chmod 600 "${ENV_FILE}"
    print_success "Environment file created: ${ENV_FILE}"
    log "Environment file created"
}

load_env_file() {
    if [[ -f "${ENV_FILE}" ]]; then
        print_info "Loading existing configuration..."
        source "${ENV_FILE}"
        print_success "Configuration loaded (SERVER_IP: ${SERVER_IP})"
        log "Configuration loaded from ${ENV_FILE}"
        return 0
    else
        return 1
    fi
}

apply_frontend_config() {
    # app.js calls the API through nginx with a relative /api base, so there
    # is nothing to rewrite any more. Clean up the backup the old sed left.
    rm -f "${INSTALL_DIR}/frontend/src/app.js.bak" 2>/dev/null || true
}

################################################################################
# Installation Functions
################################################################################

clone_repository() {
    print_info "Cloning repository from GitHub..."

    if [[ -d "${INSTALL_DIR}" ]]; then
        print_warning "Installation directory already exists"
        if confirm "Remove existing directory and clone fresh?"; then
            rm -rf "${INSTALL_DIR}"
        else
            error_exit "Installation directory exists: ${INSTALL_DIR}"
        fi
    fi

    # Ensure parent directory exists and cd to it before cloning
    mkdir -p "$(dirname "${INSTALL_DIR}")"
    cd "$(dirname "${INSTALL_DIR}")" || error_exit "Cannot access installation parent directory"

    git clone -b "${GITHUB_BRANCH}" "${REPO_URL}" "${INSTALL_DIR}"

    if [[ $? -eq 0 ]]; then
        print_success "Repository cloned successfully"
        log "Repository cloned from ${REPO_URL}"
    else
        error_exit "Failed to clone repository"
    fi
}

pull_latest_code() {
    print_info "Pulling latest code from GitHub..."

    cd "${INSTALL_DIR}"

    # Stash any local changes
    git stash push -u -m "Auto-stash before update $(date '+%Y-%m-%d %H:%M:%S')"

    # Pull latest code
    git pull origin "${GITHUB_BRANCH}"

    if [[ $? -eq 0 ]]; then
        print_success "Code updated successfully"
        log "Code updated from GitHub"
    else
        error_exit "Failed to pull latest code"
    fi
}

build_containers() {
    print_info "Building Docker containers..."

    cd "${INSTALL_DIR}"
    if docker compose -f docker-compose.prod.yml build; then
        print_success "Containers built successfully"
        log "Docker containers built"
    else
        error_exit "Failed to build containers"
    fi
}

start_containers() {
    print_info "Starting containers..."

    cd "${INSTALL_DIR}"
    if docker compose -f docker-compose.prod.yml up -d; then
        print_success "Containers started"
        log "Docker containers started"
    else
        error_exit "Failed to start containers"
    fi
}

stop_containers() {
    print_info "Stopping containers..."

    if [[ -f "${COMPOSE_FILE}" ]]; then
        cd "${INSTALL_DIR}"
        docker compose -f docker-compose.prod.yml stop 2>/dev/null || true
        print_success "Containers stopped"
        log "Docker containers stopped"
    else
        print_warning "Compose file not found, stopping containers by name..."
        docker stop ${CONTAINER_BACKEND} ${CONTAINER_FRONTEND} ${CONTAINER_DB} 2>/dev/null || true
        print_success "Containers stopped (if they existed)"
        log "Docker containers stopped by name"
    fi
}

remove_containers() {
    print_info "Removing containers..."

    if [[ -f "${COMPOSE_FILE}" ]]; then
        cd "${INSTALL_DIR}"
        docker compose -f docker-compose.prod.yml down 2>/dev/null || true
    else
        print_warning "Compose file not found, removing containers by name..."
        docker rm -f ${CONTAINER_BACKEND} ${CONTAINER_FRONTEND} ${CONTAINER_DB} 2>/dev/null || true
    fi

    print_success "Containers removed"
    log "Docker containers removed"
}

remove_volumes() {
    if confirm "Remove database volumes? (This will delete all data!)" "n"; then
        print_warning "Removing volumes (data will be lost)..."
        docker volume rm ${VOLUME_POSTGRES} 2>/dev/null || true
        print_success "Volumes removed"
        log "Docker volumes removed"
    else
        print_info "Volumes preserved (data kept for future use)"
        log "Docker volumes preserved"
    fi
}

remove_installation_dir() {
    if [[ -d "${INSTALL_DIR}" ]]; then
        if confirm "Remove installation directory?" "n"; then
            print_info "Removing installation directory..."
            rm -rf "${INSTALL_DIR}"
            print_success "Installation directory removed"
            log "Installation directory removed"
        else
            print_info "Installation directory preserved"
        fi
    fi
}

container_health() {
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || echo "missing"
}

# wait_for_health [timeout_seconds] [containers...]
wait_for_health() {
    local timeout="${1:-180}"
    shift || true
    local containers=("$@")
    if [[ ${#containers[@]} -eq 0 ]]; then
        containers=("${CONTAINER_DB}" "${CONTAINER_BACKEND}" "${CONTAINER_FRONTEND}")
    fi

    print_info "Waiting for services to be healthy (up to ${timeout}s)..."
    local waited=0
    while [[ $waited -lt $timeout ]]; do
        local all_ok=1 states=""
        for c in "${containers[@]}"; do
            local st
            st="$(container_health "$c")"
            states="${states} ${c#globalupc_}=${st}"
            [[ "$st" == "healthy" ]] || all_ok=0
        done
        if [[ $all_ok -eq 1 ]]; then
            echo ""
            print_success "All services are healthy"
            return 0
        fi
        echo -ne "\r  ${states} (${waited}s)   "
        sleep 2
        waited=$((waited + 2))
    done

    echo ""
    print_warning "Services not healthy after ${timeout}s:${states}"
    return 1
}

show_access_info() {
    print_header "Installation Complete!"

    echo -e "${GREEN}${BOLD}Services Running:${NC}"
    echo -e "  ${CYAN}•${NC} Frontend:  ${BOLD}http://${SERVER_IP}${NC}"
    echo -e "  ${CYAN}•${NC} API:       ${BOLD}http://${SERVER_IP}/api/${NC} (through nginx)"
    echo -e "  ${CYAN}•${NC} Backend:   ${BOLD}http://127.0.0.1:8001${NC} (this server only)"
    echo -e "  ${CYAN}•${NC} Database:  ${BOLD}127.0.0.1:5433${NC} (this server only)"
    echo -e "  ${CYAN}•${NC} Backups:   ${BOLD}${BACKUP_DIR}${NC} (daily, ${CRON_FILE})"
    echo ""

    echo -e "${YELLOW}${BOLD}Useful Commands:${NC}"
    echo -e "  ${CYAN}•${NC} View logs:     ${BOLD}cd ${INSTALL_DIR} && docker compose -f docker-compose.prod.yml logs -f${NC}"
    echo -e "  ${CYAN}•${NC} Restart:       ${BOLD}cd ${INSTALL_DIR} && docker compose -f docker-compose.prod.yml restart${NC}"
    echo -e "  ${CYAN}•${NC} Stop:          ${BOLD}cd ${INSTALL_DIR} && docker compose -f docker-compose.prod.yml stop${NC}"
    echo -e "  ${CYAN}•${NC} Update:        ${BOLD}sudo ${INSTALL_DIR}/install.sh${NC} (select option 2)"
    echo ""

    echo -e "${BLUE}Configuration saved to:${NC} ${ENV_FILE}"
    echo ""
}

################################################################################
# Main Installation Modes
################################################################################

fresh_install() {
    print_header "Fresh Installation"

    # Check requirements
    check_requirements

    # Prompt for configuration
    prompt_for_ip

    # Clone repository
    clone_repository

    # Create environment file
    create_env_file

    # Apply frontend configuration
    apply_frontend_config

    # Build, start the database, bring the schema up to date, then the rest
    build_containers
    cd "${INSTALL_DIR}"
    docker compose -f docker-compose.prod.yml up -d db
    wait_for_health 120 "${CONTAINER_DB}" || error_exit "Database did not become healthy"
    run_database_migrations || error_exit "Database migrations failed"
    start_containers

    # Wait for health checks
    wait_for_health 240 || true

    install_backup_cron

    # Show access information
    show_access_info

    log "Fresh installation completed"
}

psql_db() {
    docker exec -i ${CONTAINER_DB} psql -X -q -v ON_ERROR_STOP=1 -U globalupc -d globalupc "$@"
}

# Migrations run against the live database BEFORE the new backend starts, while
# the old version keeps serving: every migration must stay backward compatible
# (add tables/columns/indexes; never drop or rename what running code reads).
# Applied files are recorded in schema_migrations. The first run on an existing
# install re-applies every file once (they are all idempotent) and records them;
# a failure there is only a warning, as before. After that a failing migration
# stops the update before anything is swapped.
run_database_migrations() {
    print_info "Checking for database migrations..."

    local migrations_dir="${INSTALL_DIR}/backend/migrations"
    if [[ ! -d "$migrations_dir" ]]; then
        print_info "No migrations directory found, skipping"
        return 0
    fi

    local migration_files=()
    mapfile -t migration_files < <(find "$migrations_dir" -name "*.sql" -type f | sort)
    if [[ ${#migration_files[@]} -eq 0 ]]; then
        print_info "No migration files found, skipping"
        return 0
    fi

    local max_attempts=30 attempt=0
    print_info "Waiting for database to be ready..."
    until docker exec ${CONTAINER_DB} pg_isready -U globalupc -d globalupc &> /dev/null; do
        attempt=$((attempt + 1))
        if [[ $attempt -ge $max_attempts ]]; then
            print_error "Database not ready, cannot run migrations"
            return 1
        fi
        sleep 2
    done
    print_success "Database is ready"

    local bootstrap=0
    if [[ "$(psql_db -tAc "SELECT to_regclass('public.schema_migrations') IS NOT NULL")" != "t" ]]; then
        bootstrap=1
        print_info "First tracked run: re-applying every migration once and recording it"
        psql_db -c "CREATE TABLE IF NOT EXISTS schema_migrations (
                        filename   TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now())" || return 1
    fi

    local applied=0 skipped=0
    local migration_file
    for migration_file in "${migration_files[@]}"; do
        local filename
        filename=$(basename "$migration_file")
        if [[ "$(psql_db -tAc "SELECT 1 FROM schema_migrations WHERE filename = '${filename}'")" == "1" ]]; then
            skipped=$((skipped + 1))
            continue
        fi
        print_info "Running migration: $filename"
        if psql_db < "$migration_file"; then
            psql_db -c "INSERT INTO schema_migrations (filename) VALUES ('${filename}') ON CONFLICT DO NOTHING" || return 1
            print_success "Migration applied: $filename"
            log "Migration applied: $filename"
            applied=$((applied + 1))
        elif [[ $bootstrap -eq 1 ]]; then
            psql_db -c "INSERT INTO schema_migrations (filename) VALUES ('${filename}') ON CONFLICT DO NOTHING" || return 1
            print_warning "Migration reported errors on re-run (recorded, as before): $filename"
            log "Migration warning (bootstrap): $filename"
        else
            print_error "Migration failed: $filename"
            log "Migration FAILED: $filename"
            return 1
        fi
    done

    print_success "Database migrations completed (${applied} applied, ${skipped} already applied)"
}

################################################################################
# Backups
################################################################################

# backup_database [label] -> prints the file path
backup_database() {
    local label="${1:-manual}"
    mkdir -p "${BACKUP_DIR}"
    chmod 700 "${BACKUP_DIR}"
    local file="${BACKUP_DIR}/globalupc-$(date '+%Y%m%d-%H%M%S')-${label}.dump"
    if docker exec ${CONTAINER_DB} pg_dump -U globalupc -d globalupc -Fc > "${file}.part" && [[ -s "${file}.part" ]]; then
        mv "${file}.part" "${file}"
        chmod 600 "${file}"
        log "Backup written: ${file}" >&2
        echo "${file}"
        return 0
    fi
    rm -f "${file}.part"
    return 1
}

# Keep the newest N daily dumps plus the newest dump of each of the last M weeks.
prune_backups() {
    [[ -d "${BACKUP_DIR}" ]] || return 0
    local keep
    keep=$(
        {
            ls -1t "${BACKUP_DIR}"/globalupc-*-daily.dump 2>/dev/null | head -n "${BACKUP_KEEP_DAILY}"
            ls -1t "${BACKUP_DIR}"/globalupc-*-daily.dump 2>/dev/null \
                | awk -F'globalupc-' '{ split($2, a, "-"); cmd = "date -d " substr(a[1],1,8) " +%G%V"; cmd | getline wk; close(cmd); if (!(wk in seen)) { seen[wk] = 1; print } }' \
                | head -n "${BACKUP_KEEP_WEEKLY}"
            # Pre-update / manual dumps: keep the newest 10.
            ls -1t "${BACKUP_DIR}"/globalupc-*.dump 2>/dev/null | grep -v -- '-daily.dump' | head -n 10
        } | sort -u
    )
    local f
    for f in "${BACKUP_DIR}"/globalupc-*.dump; do
        [[ -e "$f" ]] || continue
        grep -qxF "$f" <<< "$keep" || rm -f "$f"
    done
}

install_backup_cron() {
    mkdir -p "${BACKUP_DIR}"
    cat > "${CRON_FILE}" <<CRON
# Global UPC: nightly PostgreSQL backup (written by install.sh)
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 2 * * * root ${INSTALL_DIR}/install.sh --backup-daily >> ${INSTALL_DIR}/backup.log 2>&1
CRON
    chmod 644 "${CRON_FILE}"
    print_success "Nightly backup scheduled (02:30, ${BACKUP_DIR})"
    log "Backup cron installed"
}

restore_database() {
    print_header "Restore Database from Backup"
    local files
    mapfile -t files < <(ls -1t "${BACKUP_DIR}"/globalupc-*.dump 2>/dev/null)
    if [[ ${#files[@]} -eq 0 ]]; then
        print_warning "No backups found in ${BACKUP_DIR}"
        return
    fi
    local i
    for i in "${!files[@]}"; do
        echo "  [$((i + 1))] $(basename "${files[$i]}")  ($(du -h "${files[$i]}" | cut -f1))"
    done
    echo ""
    read -p "Backup to restore (number, empty = cancel): " pick
    [[ -n "$pick" && "$pick" =~ ^[0-9]+$ && $pick -ge 1 && $pick -le ${#files[@]} ]] || { print_info "Cancelled"; return; }
    local file="${files[$((pick - 1))]}"
    print_warning "This replaces ALL current data with $(basename "$file")."
    confirm "Continue?" "n" || { print_info "Cancelled"; return; }

    local safety
    safety=$(backup_database "pre-restore") && print_success "Current data saved first: ${safety}"
    cd "${INSTALL_DIR}"
    docker compose -f docker-compose.prod.yml stop backend
    if docker exec -i ${CONTAINER_DB} pg_restore -U globalupc -d globalupc --clean --if-exists --no-owner < "$file"; then
        print_success "Restore complete"
    else
        print_warning "pg_restore reported errors (see above); data may be partially restored"
    fi
    docker compose -f docker-compose.prod.yml up -d backend
    wait_for_health 180 "${CONTAINER_BACKEND}" || true
    log "Database restored from ${file}"
}

backup_menu() {
    print_header "Backup / Restore"
    echo "  [1] Back up now"
    echo "  [2] Restore from a backup"
    echo "  [3] (Re)install nightly backup schedule"
    echo "  [4] Back"
    echo ""
    read -p "Select an option [1-4]: " bchoice
    case $bchoice in
        1)
            local f
            if f=$(backup_database "manual"); then print_success "Backup written: $f"; else print_error "Backup failed"; fi
            ;;
        2) restore_database ;;
        3) install_backup_cron ;;
        *) ;;
    esac
}

image_for() {
    docker compose -f docker-compose.prod.yml config --images 2>/dev/null | grep -E -- "-$1\$" | head -1
}

update_from_github() {
    print_header "Update from GitHub"

    if [[ ! -d "${INSTALL_DIR}" ]]; then
        error_exit "Installation directory not found. Please run fresh install first."
    fi

    # Load existing configuration
    if ! load_env_file; then
        print_warning "No existing configuration found"
        prompt_for_ip
        create_env_file
    fi

    cd "${INSTALL_DIR}"
    local prev_commit
    prev_commit=$(git rev-parse HEAD)

    # Nothing is stopped until the new images are built and the schema is
    # migrated: a failed pull, build, backup or migration leaves the running
    # version untouched.
    pull_latest_code

    # Continue with the freshly pulled installer, so the new update logic
    # (and anything it needs) applies to this very update.
    GLOBALUPC_SELF_COPY="" exec bash "${INSTALL_DIR}/install.sh" --finish-update "$prev_commit"
}

finish_update() {
    local prev_commit="$1"
    cd "${INSTALL_DIR}"
    load_env_file > /dev/null || true

    apply_frontend_config

    # Remember the running images so a failed start can be rolled back.
    local svc img
    for svc in backend frontend; do
        img=$(image_for "$svc")
        if [[ -n "$img" ]] && docker image inspect "$img" &> /dev/null; then
            docker tag "$img" "${img%%:*}:previous"
        fi
    done

    print_info "Building new images (the current version keeps running)..."
    if ! docker compose -f docker-compose.prod.yml build; then
        print_error "Build failed. The current version is still running."
        git reset -q --hard "$prev_commit"
        log "Update aborted: build failed"
        return 1
    fi
    print_success "Images built"

    if [[ "$(container_health "${CONTAINER_DB}")" != "healthy" ]]; then
        print_info "Starting database..."
        docker compose -f docker-compose.prod.yml up -d db
        wait_for_health 120 "${CONTAINER_DB}" || { print_error "Database is not healthy"; return 1; }
    fi

    print_info "Backing up the database..."
    local backup_file
    if backup_file=$(backup_database "pre-update"); then
        print_success "Backup written: ${backup_file}"
    else
        print_error "Backup failed. Update stopped; the current version is still running."
        git reset -q --hard "$prev_commit"
        return 1
    fi

    if ! run_database_migrations; then
        print_error "Migration failed. The current version is still running."
        print_info "Backup taken just before: ${backup_file}"
        git reset -q --hard "$prev_commit"
        log "Update aborted: migration failed"
        return 1
    fi

    # Swap: only the app containers are recreated; the database keeps running.
    # Browsers and API clients see a short "restarting" blip (JSON 502/503 with
    # Retry-After from nginx) and retry.
    print_info "Switching to the new version..."
    docker compose -f docker-compose.prod.yml up -d --no-deps backend
    if ! wait_for_health 180 "${CONTAINER_BACKEND}"; then
        print_error "New backend did not become healthy. Rolling back..."
        docker logs --tail 80 "${CONTAINER_BACKEND}" 2>&1 | sed 's/^/    /'
        rollback_images
        git reset -q --hard "$prev_commit"
        log "Update rolled back: backend unhealthy"
        return 1
    fi
    docker compose -f docker-compose.prod.yml up -d --no-deps frontend
    if ! wait_for_health 60 "${CONTAINER_FRONTEND}"; then
        print_error "New frontend did not become healthy. Rolling back..."
        rollback_images
        git reset -q --hard "$prev_commit"
        log "Update rolled back: frontend unhealthy"
        return 1
    fi
    # Autoheal and anything else in the file (pinned image changes etc.).
    docker compose -f docker-compose.prod.yml up -d

    [[ -f "${CRON_FILE}" ]] || install_backup_cron
    prune_backups

    show_access_info
    log "Update from GitHub completed ($(git rev-parse --short HEAD))"
}

rollback_images() {
    local svc img
    for svc in backend frontend; do
        img=$(image_for "$svc")
        if [[ -n "$img" ]] && docker image inspect "${img%%:*}:previous" &> /dev/null; then
            docker tag "${img%%:*}:previous" "$img"
        fi
    done
    docker compose -f docker-compose.prod.yml up -d --no-deps --no-build backend frontend
    if wait_for_health 180 "${CONTAINER_BACKEND}" "${CONTAINER_FRONTEND}"; then
        print_success "Previous version restored and healthy"
    else
        print_error "Previous version is not healthy either; check: docker compose -f docker-compose.prod.yml logs backend"
    fi
}

remove_only() {
    print_header "Remove Installation"

    if ! detect_installation; then
        print_warning "No installation detected"
        return
    fi

    show_existing_installation

    if ! confirm "Are you sure you want to remove the installation?" "n"; then
        print_info "Removal cancelled"
        return
    fi

    # Stop and remove containers
    stop_containers
    remove_containers

    # Ask about volumes
    remove_volumes

    # Ask about installation directory
    remove_installation_dir

    print_success "Removal complete"
    log "Installation removed"
}

remove_and_reinstall() {
    print_header "Remove and Reinstall"

    if detect_installation; then
        show_existing_installation

        if ! confirm "Remove existing installation and reinstall?" "n"; then
            print_info "Operation cancelled"
            return
        fi

        # Keep a copy of the data outside the volume before it is deleted
        if [[ "$(container_health "${CONTAINER_DB}")" == "healthy" ]]; then
            local saved
            if saved=$(backup_database "pre-reinstall"); then
                mkdir -p /root/globalupc-backups
                cp "$saved" /root/globalupc-backups/
                print_success "Data backed up to /root/globalupc-backups/$(basename "$saved")"
            else
                print_warning "Backup before reinstall failed"
                confirm "Delete the data anyway?" "n" || return
            fi
        fi

        # Remove existing installation
        stop_containers
        remove_containers

        # Always remove volumes for clean reinstall
        print_warning "Removing volumes for clean reinstall..."
        docker volume rm ${VOLUME_POSTGRES} 2>/dev/null || true

        # Remove installation directory
        if [[ -d "${INSTALL_DIR}" ]]; then
            rm -rf "${INSTALL_DIR}"
        fi

        print_success "Previous installation removed"
    fi

    # Proceed with fresh install
    fresh_install
}

configure_iframe_embedding() {
    print_header "Configure Iframe Embedding"

    # Check installation exists
    if [[ ! -d "${INSTALL_DIR}" ]]; then
        error_exit "Installation not found. Please install first."
    fi

    local nginx_conf="${INSTALL_DIR}/frontend/nginx.conf"
    if [[ ! -f "$nginx_conf" ]]; then
        error_exit "nginx.conf not found at ${nginx_conf}"
    fi

    # Prompt for dashboard IP
    echo "Enter the IP address of the dashboard that will embed this application."
    echo "This IP will be added to the allowed iframe sources."
    echo ""

    while true; do
        read -p "Dashboard IP address: " DASHBOARD_IP
        if validate_ip "$DASHBOARD_IP"; then
            print_success "Valid IP: ${DASHBOARD_IP}"
            break
        else
            print_error "Invalid IP address. Please try again."
        fi
    done

    # Check if IP already exists in the CSP header
    if grep -q "http://${DASHBOARD_IP}" "$nginx_conf"; then
        print_warning "IP ${DASHBOARD_IP} is already configured in nginx.conf"
        if ! confirm "Continue anyway?"; then
            print_info "No changes made"
            return
        fi
    fi

    # Update nginx.conf Content-Security-Policy
    print_info "Updating nginx configuration..."

    # Use sed to update the Content-Security-Policy line
    # Match the frame-ancestors line and append the new IP before the closing quote
    sed -i.bak "s|\(frame-ancestors 'self'[^\"]*\)\"|\\1 http://${DASHBOARD_IP}\"|" "$nginx_conf"

    print_success "nginx.conf updated with allowed IP: ${DASHBOARD_IP}"
    log "Iframe embedding configured for IP: ${DASHBOARD_IP}"

    # Restart only the frontend container
    print_info "Restarting frontend container (nginx only)..."
    cd "${INSTALL_DIR}"
    docker compose -f docker-compose.prod.yml restart frontend

    if [[ $? -eq 0 ]]; then
        print_success "Frontend container restarted"
        print_info "Backend and database containers remain unchanged"
    else
        print_error "Failed to restart frontend container"
    fi

    echo ""
    print_success "Iframe embedding configured successfully!"
    print_info "Dashboard at http://${DASHBOARD_IP} can now embed this application"
    log "Iframe embedding configuration completed"
}

################################################################################
# Main Menu
################################################################################

show_menu() {
    clear
    print_header "${APP_NAME} - Installation Manager"

    echo -e "${CYAN}${BOLD}Main Menu:${NC}"
    echo ""
    echo "  [1] Fresh Install"
    echo "  [2] Update from GitHub"
    echo "  [3] Remove Installation Only"
    echo "  [4] Remove and Reinstall"
    echo "  [5] Configure Iframe Embedding"
    echo "  [6] Backup / Restore Database"
    echo "  [7] Exit"
    echo ""

    if detect_installation; then
        echo -e "${YELLOW}⚠ Existing installation detected${NC}"
        echo ""
    fi
}

main_menu() {
    while true; do
        show_menu
        read -p "Select an option [1-7]: " choice

        case $choice in
            1)
                if detect_installation; then
                    print_warning "Installation already exists!"
                    if ! confirm "Continue with fresh install? (This may conflict with existing installation)"; then
                        continue
                    fi
                fi
                fresh_install
                read -p "Press Enter to continue..."
                ;;
            2)
                update_from_github
                read -p "Press Enter to continue..."
                ;;
            3)
                remove_only
                read -p "Press Enter to continue..."
                ;;
            4)
                remove_and_reinstall
                read -p "Press Enter to continue..."
                ;;
            5)
                if ! detect_installation; then
                    print_error "No installation found. Please install first."
                    sleep 2
                    continue
                fi
                configure_iframe_embedding
                read -p "Press Enter to continue..."
                ;;
            6)
                if ! detect_installation; then
                    print_error "No installation found. Please install first."
                    sleep 2
                    continue
                fi
                backup_menu
                read -p "Press Enter to continue..."
                ;;
            7)
                echo ""
                print_info "Exiting..."
                exit 0
                ;;
            *)
                print_error "Invalid option. Please select 1-7."
                sleep 2
                ;;
        esac
    done
}

################################################################################
# Main Execution
################################################################################

main() {
    # Check if running as root
    check_root

    # Initialize log file
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
    touch "$LOG_FILE" 2>/dev/null || LOG_FILE="/tmp/globalupc-install.log"

    log "========== Installation script started =========="
    log "Script version: 1.0.0"
    log "User: $(whoami)"
    log "Date: $(date)"

    case "${1:-}" in
        --backup-daily)
            local f
            if f=$(backup_database "daily"); then echo "$(date '+%F %T') backup ok: $f"; else echo "$(date '+%F %T') backup FAILED"; exit 1; fi
            prune_backups
            exit 0
            ;;
        --finish-update)
            finish_update "${2:-}" || { read -p "Press Enter to continue..." _ < /dev/tty || true; exit 1; }
            read -p "Press Enter to continue..." _ < /dev/tty || true
            exit 0
            ;;
    esac

    # Show main menu
    main_menu
}

# Run main function
main "$@"
