#!/bin/bash

################################################################################
# Global UPC Installation Script
# Version: 1.0.0
# Description: Automated installation, update, and removal script for Global UPC
# OS: Ubuntu 24.04 LTS
################################################################################

set -e  # Exit on error

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

    if ping -c 1 8.8.8.8 &> /dev/null; then
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
    echo "  • Frontend URL: http://{IP}:8080"
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

# Frontend Configuration
FRONTEND_PORT=8080

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
    print_info "Applying frontend configuration..."

    local frontend_js="${INSTALL_DIR}/frontend/src/app.js"

    if [[ -f "$frontend_js" ]]; then
        # Replace localhost with SERVER_IP in API_BASE_URL
        sed -i.bak "s|http://localhost:8001|http://${SERVER_IP}:8001|g" "$frontend_js"
        print_success "Frontend configuration applied"
        log "Frontend configured with SERVER_IP: ${SERVER_IP}"
    else
        print_warning "Frontend app.js not found, skipping configuration"
    fi
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
    docker compose -f docker-compose.prod.yml build --no-cache

    if [[ $? -eq 0 ]]; then
        print_success "Containers built successfully"
        log "Docker containers built"
    else
        error_exit "Failed to build containers"
    fi
}

start_containers() {
    print_info "Starting containers..."

    cd "${INSTALL_DIR}"
    docker compose -f docker-compose.prod.yml up -d

    if [[ $? -eq 0 ]]; then
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

wait_for_health() {
    print_info "Waiting for services to be healthy..."

    local max_attempts=30
    local attempt=0

    cd "${INSTALL_DIR}"

    while [[ $attempt -lt $max_attempts ]]; do
        # Docker Compose v2 returns newline-delimited JSON, so we use jq -s to slurp into array
        local healthy=$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null | jq -s -r 'map(select(.Health == "healthy")) | length')
        local total=$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null | jq -s -r 'length')

        if [[ $healthy -eq $total ]] && [[ $total -gt 0 ]]; then
            print_success "All services are healthy"
            return 0
        fi

        attempt=$((attempt + 1))
        echo -ne "\r  Waiting for services... ($attempt/$max_attempts)"
        sleep 2
    done

    echo ""
    print_warning "Some services may not be healthy yet. Check logs with: docker compose -f docker-compose.prod.yml logs"
    return 1
}

show_access_info() {
    print_header "Installation Complete!"

    echo -e "${GREEN}${BOLD}Services Running:${NC}"
    echo -e "  ${CYAN}•${NC} Frontend:  ${BOLD}http://${SERVER_IP}:8080${NC}"
    echo -e "  ${CYAN}•${NC} Backend:   ${BOLD}http://${SERVER_IP}:8001${NC}"
    echo -e "  ${CYAN}•${NC} Database:  ${BOLD}localhost:5433${NC}"
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

    # Build and start containers
    build_containers
    start_containers

    # Wait for health checks
    wait_for_health

    # Show access information
    show_access_info

    log "Fresh installation completed"
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

    # Stop containers
    stop_containers

    # Pull latest code
    pull_latest_code

    # Re-apply configuration
    apply_frontend_config

    # Rebuild containers
    print_info "Rebuilding containers with latest code..."
    build_containers

    # Start containers (volumes will be reused)
    start_containers

    # Wait for health checks
    wait_for_health

    # Show access information
    show_access_info

    log "Update from GitHub completed"
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
    echo "  [5] Exit"
    echo ""

    if detect_installation; then
        echo -e "${YELLOW}⚠ Existing installation detected${NC}"
        echo ""
    fi
}

main_menu() {
    while true; do
        show_menu
        read -p "Select an option [1-5]: " choice

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
                echo ""
                print_info "Exiting..."
                exit 0
                ;;
            *)
                print_error "Invalid option. Please select 1-5."
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

    # Show main menu
    main_menu
}

# Run main function
main "$@"
