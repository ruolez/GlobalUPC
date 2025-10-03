const API_BASE = "/api";

// Global state for search results
let currentSearchResults = {
  upc: "",
  matches: [],
  total_found: 0,
};

// Flag to prevent multiple simultaneous searches
let isSearching = false;

// Navigation
document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", (e) => {
    e.preventDefault();
    const page = item.dataset.page;
    // Only navigate if this is a page navigation item (has data-page attribute)
    if (page) {
      navigateTo(page);
    }
  });
});

function navigateTo(page) {
  // Update active nav item
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.remove("active");
  });
  const targetNav = document.querySelector(`[data-page="${page}"]`);
  if (targetNav) {
    targetNav.classList.add("active");
  }

  // Show page
  document.querySelectorAll(".page").forEach((p) => {
    p.style.display = "none";
  });
  const targetPage = document.getElementById(`${page}-page`);
  if (targetPage) {
    targetPage.style.display = "block";
  }

  // Load page data
  if (page === "dashboard") {
    loadDashboard();
  } else if (page === "settings") {
    loadSettings();
  }
}

// API Functions
async function apiRequest(endpoint, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "API request failed");
    }

    if (response.status === 204) {
      return null;
    }

    return await response.json();
  } catch (error) {
    console.error("API Error:", error);
    alert(`Error: ${error.message}`);
    throw error;
  }
}

// Dashboard Functions
async function loadDashboard() {
  const stores = await apiRequest("/stores");
  const activeStores = stores.filter((s) => s.is_active);

  document.getElementById("total-stores").textContent = stores.length;
  document.getElementById("active-stores").textContent = activeStores.length;
}

// Settings Functions
async function loadSettings() {
  await loadStores();
  await loadAppSettings();
}

async function loadStores() {
  const stores = await apiRequest("/stores");
  const storesList = document.getElementById("stores-list");

  if (stores.length === 0) {
    storesList.innerHTML = `
            <div class="empty-state">
                <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="8" y="16" width="4" height="32" fill="currentColor"/>
                    <rect x="16" y="16" width="2" height="32" fill="currentColor"/>
                    <rect x="22" y="16" width="4" height="32" fill="currentColor"/>
                    <rect x="30" y="16" width="2" height="32" fill="currentColor"/>
                    <rect x="36" y="16" width="4" height="32" fill="currentColor"/>
                    <rect x="44" y="16" width="2" height="32" fill="currentColor"/>
                    <rect x="50" y="16" width="4" height="32" fill="currentColor"/>
                </svg>
                <p>No stores configured yet. Add your first store to get started.</p>
            </div>
        `;
    return;
  }

  storesList.innerHTML = stores.map((store) => createStoreCard(store)).join("");

  // Attach event listeners
  stores.forEach((store) => {
    document
      .getElementById(`toggle-${store.id}`)
      ?.addEventListener("click", () => toggleStore(store.id));
    document
      .getElementById(`delete-${store.id}`)
      ?.addEventListener("click", () => deleteStore(store.id));
  });
}

function createStoreCard(store) {
  const connection = store.mssql_connection || store.shopify_connection;
  const isMssql = store.store_type === "mssql";

  return `
        <div class="store-card">
            <div class="store-card-header">
                <div class="store-info">
                    <h4>${store.name}</h4>
                    <span class="store-type-badge ${store.store_type}">${store.store_type.toUpperCase()}</span>
                </div>
                <div class="store-actions">
                    <button class="btn btn-small btn-secondary" id="toggle-${store.id}">
                        ${store.is_active ? "Disable" : "Enable"}
                    </button>
                    <button class="btn btn-small btn-danger" id="delete-${store.id}">Delete</button>
                </div>
            </div>
            <div class="store-details">
                ${
                  isMssql
                    ? `
                    <div class="store-detail">
                        <span class="store-detail-label">Host</span>
                        <span class="store-detail-value">${connection.host}:${connection.port}</span>
                    </div>
                    <div class="store-detail">
                        <span class="store-detail-label">Database</span>
                        <span class="store-detail-value">${connection.database_name}</span>
                    </div>
                    <div class="store-detail">
                        <span class="store-detail-label">Username</span>
                        <span class="store-detail-value">${connection.username}</span>
                    </div>
                `
                    : `
                    <div class="store-detail">
                        <span class="store-detail-label">Shop Domain</span>
                        <span class="store-detail-value">${connection.shop_domain}</span>
                    </div>
                    <div class="store-detail">
                        <span class="store-detail-label">API Version</span>
                        <span class="store-detail-value">${connection.api_version}</span>
                    </div>
                    <div class="store-detail">
                        <span class="store-detail-label">Update SKU with Barcode</span>
                        <span class="store-detail-value">${connection.update_sku_with_barcode ? "Enabled" : "Disabled"}</span>
                    </div>
                `
                }
            </div>
            <div class="store-status">
                <span class="status-indicator ${store.is_active ? "active" : "inactive"}"></span>
                <span>${store.is_active ? "Active" : "Inactive"}</span>
            </div>
        </div>
    `;
}

async function toggleStore(storeId) {
  await apiRequest(`/stores/${storeId}/toggle`, { method: "PATCH" });
  await loadStores();
  await loadDashboard();
}

async function deleteStore(storeId) {
  if (!confirm("Are you sure you want to delete this store?")) {
    return;
  }

  await apiRequest(`/stores/${storeId}`, { method: "DELETE" });
  await loadStores();
  await loadDashboard();
}

async function loadAppSettings() {
  const settings = await apiRequest("/settings");
  const settingsList = document.getElementById("app-settings-list");

  if (settings.length === 0) {
    settingsList.innerHTML =
      '<div class="empty-state"><p>No settings configured.</p></div>';
    return;
  }

  settingsList.innerHTML = settings
    .map(
      (setting) => `
        <div class="setting-item">
            <div class="setting-info">
                <div class="setting-key">${setting.key}</div>
                ${setting.description ? `<div class="setting-description">${setting.description}</div>` : ""}
            </div>
            <div class="setting-value">${setting.value || "-"}</div>
        </div>
    `,
    )
    .join("");
}

// Modal Functions
function openModal(modalId) {
  document.getElementById(modalId).classList.add("active");
}

function closeModal(modalId) {
  document.getElementById(modalId).classList.remove("active");
}

window.closeModal = closeModal; // Make it globally available for onclick handlers

// Close modal on background click
document.querySelectorAll(".modal").forEach((modal) => {
  modal.addEventListener("click", (e) => {
    if (e.target === modal) {
      closeModal(modal.id);
    }
  });
});

// Test MSSQL Connection
async function testMSSQLConnection() {
  const statusEl = document.getElementById("mssql-test-status");
  const form = document.getElementById("mssql-form");
  const formData = new FormData(form);

  const testData = {
    host: formData.get("host"),
    port: parseInt(formData.get("port")),
    database_name: formData.get("database_name"),
    username: formData.get("username"),
    password: formData.get("password"),
  };

  // Show loading state
  statusEl.className = "test-status loading";
  statusEl.textContent = "Testing connection...";

  try {
    const response = await fetch(`${API_BASE}/test/mssql`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(testData),
    });

    const result = await response.json();

    if (result.success) {
      statusEl.className = "test-status success";
      statusEl.textContent = "✓ " + result.message;
    } else {
      statusEl.className = "test-status error";
      statusEl.textContent = "✗ " + result.message;
    }
  } catch (error) {
    statusEl.className = "test-status error";
    statusEl.textContent = "✗ Connection test failed: " + error.message;
  }
}

// MSSQL Form
document.getElementById("add-mssql-btn").addEventListener("click", () => {
  openModal("mssql-modal");
  // Clear test status when opening modal
  document.getElementById("mssql-test-status").className = "test-status";
  document.getElementById("mssql-test-status").textContent = "";
});

document
  .getElementById("test-mssql-btn")
  .addEventListener("click", testMSSQLConnection);

document.getElementById("mssql-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);

  const data = {
    name: formData.get("name"),
    store_type: "mssql",
    is_active: true,
    connection: {
      host: formData.get("host"),
      port: parseInt(formData.get("port")),
      database_name: formData.get("database_name"),
      username: formData.get("username"),
      password: formData.get("password"),
    },
  };

  await apiRequest("/stores/mssql", {
    method: "POST",
    body: JSON.stringify(data),
  });

  closeModal("mssql-modal");
  e.target.reset();
  await loadStores();
  await loadDashboard();
});

// Test Shopify Connection
async function testShopifyConnection() {
  const statusEl = document.getElementById("shopify-test-status");
  const form = document.getElementById("shopify-form");
  const formData = new FormData(form);

  const testData = {
    shop_domain: formData.get("shop_domain"),
    admin_api_key: formData.get("admin_api_key"),
    api_version: formData.get("api_version"),
  };

  // Show loading state
  statusEl.className = "test-status loading";
  statusEl.textContent = "Testing connection...";

  try {
    const response = await fetch(`${API_BASE}/test/shopify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(testData),
    });

    const result = await response.json();

    if (result.success) {
      statusEl.className = "test-status success";
      statusEl.textContent = "✓ " + result.message;
    } else {
      statusEl.className = "test-status error";
      statusEl.textContent = "✗ " + result.message;
    }
  } catch (error) {
    statusEl.className = "test-status error";
    statusEl.textContent = "✗ Connection test failed: " + error.message;
  }
}

// Shopify Form
document.getElementById("add-shopify-btn").addEventListener("click", () => {
  openModal("shopify-modal");
  // Clear test status when opening modal
  document.getElementById("shopify-test-status").className = "test-status";
  document.getElementById("shopify-test-status").textContent = "";
});

document
  .getElementById("test-shopify-btn")
  .addEventListener("click", testShopifyConnection);

document
  .getElementById("shopify-form")
  .addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);

    const data = {
      name: formData.get("name"),
      store_type: "shopify",
      is_active: true,
      connection: {
        shop_domain: formData.get("shop_domain"),
        admin_api_key: formData.get("admin_api_key"),
        api_version: formData.get("api_version"),
        update_sku_with_barcode:
          formData.get("update_sku_with_barcode") === "on",
      },
    };

    await apiRequest("/stores/shopify", {
      method: "POST",
      body: JSON.stringify(data),
    });

    closeModal("shopify-modal");
    e.target.reset();
    await loadStores();
    await loadDashboard();
  });

// Theme Switching
function setTheme(themeName) {
  const body = document.body;

  // Remove current theme
  body.removeAttribute("data-theme");

  // Set new theme (if not 'current')
  if (themeName !== "current") {
    body.setAttribute("data-theme", themeName);
  }

  // Save to localStorage
  localStorage.setItem("selectedTheme", themeName);

  // Update active state
  document.querySelectorAll(".theme-option").forEach((option) => {
    option.classList.remove("active");
  });
  document
    .querySelector(`[data-theme-name="${themeName}"]`)
    .classList.add("active");
}

// Theme option click handlers
document.addEventListener("click", (e) => {
  const themeOption = e.target.closest(".theme-option");
  if (themeOption) {
    const themeName = themeOption.dataset.themeName;
    setTheme(themeName);
  }
});

// Update UPC Functions
document
  .getElementById("search-upc-btn")
  ?.addEventListener("click", async () => {
    const upc = document.getElementById("upc-search-input").value.trim();

    if (!upc) {
      showStatus("upc-search-loading", "Please enter a UPC to search", "error");
      return;
    }

    await searchUPC(upc);
  });

// Allow Enter key to trigger search
document
  .getElementById("upc-search-input")
  ?.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      document.getElementById("search-upc-btn").click();
    }
  });

async function searchUPC(upc) {
  // Prevent multiple simultaneous searches
  if (isSearching) {
    return;
  }
  isSearching = true;

  const loadingEl = document.getElementById("upc-search-loading");
  const progressContainer = document.getElementById("search-progress");
  const progressItems = document.getElementById("progress-items");
  const emptyEl = document.getElementById("upc-search-empty");
  const resultsEl = document.getElementById("upc-search-results");
  const newUpcContainer = document.getElementById("new-upc-container");
  const updateBtn = document.getElementById("update-all-btn");
  const searchBtn = document.getElementById("search-upc-btn");

  // Disable search button while searching
  if (searchBtn) searchBtn.disabled = true;

  // Show loading state with progress
  loadingEl.style.display = "block";
  progressContainer.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";
  progressItems.innerHTML = "";

  // Hide new UPC input during search
  if (newUpcContainer) newUpcContainer.style.display = "none";
  if (updateBtn) updateBtn.style.display = "none";

  // Helper to format table names
  const formatTableName = (tableName) => {
    const tableMap = {
      Items_tbl: "Product Catalog",
      QuotationsDetails_tbl: "Quotations",
      PurchaseOrdersDetails_tbl: "Purchase Orders",
      InvoicesDetails_tbl: "Invoices",
    };
    return tableMap[tableName] || tableName;
  };

  // Create progress item
  const createProgressItem = (text, status = "pending") => {
    const item = document.createElement("div");
    item.style.cssText =
      "display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; transition: var(--transition);";

    const icon = document.createElement("span");
    icon.style.cssText = "width: 16px; height: 16px; flex-shrink: 0;";

    if (status === "pending") {
      icon.innerHTML = "⏳";
      item.style.color = "var(--text-tertiary)";
    } else if (status === "active") {
      icon.innerHTML = "🔍";
      item.style.color = "var(--accent-primary)";
      icon.style.animation = "pulse 1.5s ease-in-out infinite";
    } else if (status === "complete") {
      icon.innerHTML = "✓";
      item.style.color = "var(--success)";
    } else if (status === "found") {
      icon.innerHTML = "📦";
      item.style.color = "var(--accent-primary)";
    }

    const textSpan = document.createElement("span");
    textSpan.textContent = text;

    item.appendChild(icon);
    item.appendChild(textSpan);

    return item;
  };

  try {
    // Use fetch with streaming for POST + SSE
    const response = await fetch(`${API_BASE}/upc/search/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ upc }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const storeItems = new Map(); // Track progress items by store name

    while (true) {
      const { done, value } = await reader.read();

      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // Keep incomplete message in buffer

      for (const line of lines) {
        if (!line.trim()) continue;

        const eventMatch = line.match(/event: (\w+)\ndata: (.+)/s);
        if (!eventMatch) continue;

        const [, eventType, dataStr] = eventMatch;
        const data = JSON.parse(dataStr);

        if (eventType === "progress") {
          if (data.status === "searching_store") {
            const item = createProgressItem(data.store_name, "active");
            storeItems.set(data.store_name, item);
            progressItems.appendChild(item);
            // Auto-scroll to bottom like a terminal
            progressContainer.scrollTop = progressContainer.scrollHeight;
          } else if (data.status === "completed_store") {
            const existingItem = storeItems.get(data.store_name);
            if (existingItem) {
              const icon = existingItem.querySelector("span");
              icon.innerHTML = data.found > 0 ? "✓" : "○";
              icon.style.animation = "";
              existingItem.style.color =
                data.found > 0 ? "var(--success)" : "var(--text-tertiary)";

              const textSpan = existingItem.querySelector("span:last-child");
              if (data.found > 0) {
                textSpan.textContent = `${data.store_name} • ${data.found}`;
              } else {
                textSpan.textContent = `${data.store_name} • none`;
              }
            }
          }
        } else if (eventType === "complete") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";

          if (data.total_found === 0) {
            emptyEl.style.display = "block";
          } else {
            displayUPCResults(data);
          }

          // Re-enable search after completion
          isSearching = false;
          if (searchBtn) searchBtn.disabled = false;
        } else if (eventType === "error") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          alert(`Error: ${data.message}`);

          // Re-enable search after error
          isSearching = false;
          if (searchBtn) searchBtn.disabled = false;
        }
      }
    }
  } catch (error) {
    loadingEl.style.display = "none";
    progressContainer.style.display = "none";
    alert(`Error: ${error.message}`);
  } finally {
    // Always re-enable search button, even if error occurred
    isSearching = false;
    if (searchBtn) searchBtn.disabled = false;
  }
}

function displayUPCResults(data) {
  const resultsEl = document.getElementById("upc-search-results");
  const tableBody = document.getElementById("upc-results-table-body");
  const countEl = document.getElementById("upc-results-count");
  const storesEl = document.getElementById("upc-stores-count");
  const updateSection = document.getElementById("upc-update-section");

  // Store results globally for update functionality - UNCHANGED
  currentSearchResults = {
    upc: data.upc,
    matches: data.matches,
    total_found: data.total_found,
  };

  // Update counts
  countEl.textContent = data.total_found;
  storesEl.textContent = data.stores_searched;

  // Clear table
  tableBody.innerHTML = "";

  // Helper function to format table names
  const formatTableName = (tableName) => {
    const tableMap = {
      Items_tbl: "Product Catalog",
      QuotationsDetails_tbl: "Quotation Details",
      PurchaseOrdersDetails_tbl: "Purchase Order Details",
      InvoicesDetails_tbl: "Invoice Details",
    };
    return tableMap[tableName] || tableName;
  };

  // Group matches by store name
  const storeGroups = new Map();
  data.matches.forEach((match) => {
    if (!storeGroups.has(match.store_name)) {
      storeGroups.set(match.store_name, []);
    }
    storeGroups.get(match.store_name).push(match);
  });

  // Render grouped results
  let storeIndex = 0;
  storeGroups.forEach((matches, storeName) => {
    const storeId = `store-${storeIndex}`;
    const rowNumber = storeIndex + 1;
    storeIndex++;

    // Calculate total matches (sum of match_count for MSSQL, or just count for Shopify)
    const totalMatches = matches.reduce((sum, match) => {
      return sum + (match.match_count || 1);
    }, 0);

    // Create store header row (collapsed by default)
    const storeRow = document.createElement("tr");
    storeRow.className = "store-row collapsed";
    storeRow.dataset.storeId = storeId;

    const storeNameTd = document.createElement("td");
    storeNameTd.innerHTML = `<span class="row-number">${rowNumber}.</span> <span class="expand-icon">▶</span>${storeName}`;
    storeRow.appendChild(storeNameTd);

    const summaryTd = document.createElement("td");
    summaryTd.colSpan = 2;
    summaryTd.innerHTML = `<span class="match-count-green">${matches.length}</span> ${matches.length === 1 ? "product" : "products"} (<span class="match-count-orange">${totalMatches}</span> ${totalMatches === 1 ? "match" : "matches"})`;
    storeRow.appendChild(summaryTd);

    tableBody.appendChild(storeRow);

    // Create detail rows for each match (hidden by default)
    matches.forEach((match) => {
      const detailRow = document.createElement("tr");
      detailRow.className = "product-detail-row hidden";
      detailRow.dataset.storeId = storeId;

      // Empty first cell for indentation
      const emptyTd = document.createElement("td");
      detailRow.appendChild(emptyTd);

      // Product Title
      const productTd = document.createElement("td");
      productTd.textContent = match.product_title;
      detailRow.appendChild(productTd);

      // Variant / Table (different display for Shopify vs MSSQL)
      const variantTd = document.createElement("td");
      if (match.match_count !== null && match.match_count !== undefined) {
        // MSSQL result - show table name with match count
        const tableName = formatTableName(match.table_name);
        variantTd.textContent = `${tableName} (${match.match_count} ${match.match_count === 1 ? "match" : "matches"})`;
        variantTd.style.color = "var(--text-secondary)";
        variantTd.style.fontSize = "0.875rem";
      } else {
        // Shopify result - show variant title
        variantTd.textContent = match.variant_title || "Default";
        variantTd.style.color = match.variant_title
          ? "inherit"
          : "var(--text-tertiary)";
      }
      detailRow.appendChild(variantTd);

      tableBody.appendChild(detailRow);
    });
  });

  // Show results
  resultsEl.style.display = "block";

  // Show new UPC input and update button
  const newUpcContainer = document.getElementById("new-upc-container");
  const updateBtn = document.getElementById("update-all-btn");
  if (newUpcContainer) newUpcContainer.style.display = "block";
  if (updateBtn) updateBtn.style.display = "inline-block";

  // Reset update section state
  document.getElementById("new-upc-input").value = "";
  document.getElementById("update-all-btn").disabled = true;
  document.getElementById("upc-update-loading").style.display = "none";
  document.getElementById("upc-update-results").style.display = "none";

  // Hide update progress section initially
  if (updateSection) updateSection.style.display = "none";
}

// Expand/collapse store rows click handler
document
  .getElementById("upc-results-table-body")
  ?.addEventListener("click", (e) => {
    const storeRow = e.target.closest(".store-row");
    if (!storeRow) return;

    const storeId = storeRow.dataset.storeId;
    const isCollapsed = storeRow.classList.contains("collapsed");

    // Toggle store row state
    storeRow.classList.toggle("collapsed");
    storeRow.classList.toggle("expanded");

    // Toggle all product detail rows for this store
    const detailRows = document.querySelectorAll(
      `.product-detail-row[data-store-id="${storeId}"]`,
    );
    detailRows.forEach((row) => {
      row.classList.toggle("hidden");
    });

    // Update icon
    const icon = storeRow.querySelector(".expand-icon");
    if (icon) {
      icon.textContent = isCollapsed ? "▼" : "▶";
    }
  });

// Update UPC functionality
document.getElementById("new-upc-input")?.addEventListener("input", (e) => {
  const newUPC = e.target.value.trim();
  const updateBtn = document.getElementById("update-all-btn");

  // Enable button only if new UPC is provided and different from old UPC
  if (updateBtn) {
    updateBtn.disabled = !newUPC || newUPC === currentSearchResults.upc;
  }
});

document.getElementById("new-upc-input")?.addEventListener("keypress", (e) => {
  if (e.key === "Enter") {
    const updateBtn = document.getElementById("update-all-btn");
    if (updateBtn && !updateBtn.disabled) {
      updateBtn.click();
    }
  }
});

document.getElementById("update-all-btn")?.addEventListener("click", () => {
  const newUPC = document.getElementById("new-upc-input").value.trim();

  if (!newUPC) {
    alert("Please enter a new UPC");
    return;
  }

  if (newUPC === currentSearchResults.upc) {
    alert("New UPC must be different from the current UPC");
    return;
  }

  if (currentSearchResults.matches.length === 0) {
    alert("No search results to update");
    return;
  }

  // Confirm before updating
  const message = `Update ${currentSearchResults.total_found} item${currentSearchResults.total_found !== 1 ? "s" : ""} from UPC "${currentSearchResults.upc}" to "${newUPC}"?`;
  if (confirm(message)) {
    updateUPC(currentSearchResults.upc, newUPC, currentSearchResults.matches);
  }
});

async function updateUPC(oldUPC, newUPC, matches) {
  const loadingEl = document.getElementById("upc-update-loading");
  const progressContainer = document.getElementById("update-progress");
  const progressItems = document.getElementById("update-progress-items");
  const resultsEl = document.getElementById("upc-update-results");
  const updateBtn = document.getElementById("update-all-btn");
  const updateSection = document.getElementById("upc-update-section");

  // Show update section and loading state
  if (updateSection) updateSection.style.display = "block";
  loadingEl.style.display = "block";
  progressContainer.style.display = "block";
  resultsEl.style.display = "none";
  progressItems.innerHTML = "";
  updateBtn.disabled = true;

  // Create progress item
  const createProgressItem = (text, status = "pending") => {
    const item = document.createElement("div");
    item.style.cssText =
      "display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; transition: var(--transition);";

    const icon = document.createElement("span");
    icon.style.cssText = "width: 16px; height: 16px; flex-shrink: 0;";

    if (status === "pending") {
      icon.innerHTML = "⏳";
      item.style.color = "var(--text-tertiary)";
    } else if (status === "active") {
      icon.innerHTML = "🔄";
      item.style.color = "var(--accent-primary)";
      icon.style.animation = "pulse 1.5s ease-in-out infinite";
    } else if (status === "success") {
      icon.innerHTML = "✓";
      item.style.color = "var(--success)";
    } else if (status === "error") {
      icon.innerHTML = "✗";
      item.style.color = "var(--error)";
    }

    const textSpan = document.createElement("span");
    textSpan.textContent = text;

    item.appendChild(icon);
    item.appendChild(textSpan);

    return item;
  };

  try {
    // Use fetch with streaming for POST + SSE
    const response = await fetch(`${API_BASE}/upc/update/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        old_upc: oldUPC,
        new_upc: newUPC,
        matches: matches,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const storeItems = new Map(); // Track progress items by store name

    while (true) {
      const { done, value } = await reader.read();

      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // Keep incomplete message in buffer

      for (const line of lines) {
        if (!line.trim()) continue;

        const eventMatch = line.match(/event: (\w+)\ndata: (.+)/s);
        if (!eventMatch) continue;

        const [, eventType, dataStr] = eventMatch;
        const data = JSON.parse(dataStr);

        if (eventType === "progress") {
          if (data.status === "updating_store") {
            const item = createProgressItem(data.store_name, "active");
            storeItems.set(data.store_name, item);
            progressItems.appendChild(item);
            // Auto-scroll to bottom like a terminal
            progressContainer.scrollTop = progressContainer.scrollHeight;
          } else if (data.status === "updated_store") {
            const existingItem = storeItems.get(data.store_name);
            if (existingItem) {
              const icon = existingItem.querySelector("span");
              icon.innerHTML = data.success ? "✓" : "✗";
              icon.style.animation = "";
              existingItem.style.color = data.success
                ? "var(--success)"
                : "var(--error)";

              const textSpan = existingItem.querySelector("span:last-child");
              textSpan.textContent = `${data.store_name} • ${data.updated}`;
            }
          }
        } else if (eventType === "complete") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          displayUpdateResults(data);
        } else if (eventType === "error") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          alert(`Error: ${data.message}`);
          updateBtn.disabled = false;
        }
      }
    }
  } catch (error) {
    loadingEl.style.display = "none";
    progressContainer.style.display = "none";
    alert(`Error: ${error.message}`);
    updateBtn.disabled = false;
  }
}

function displayUpdateResults(data) {
  const resultsEl = document.getElementById("upc-update-results");
  const tableBody = document.getElementById("upc-update-results-table-body");
  const countEl = document.getElementById("upc-update-count");

  // Update count
  countEl.textContent = data.total_updated;

  // Clear table
  tableBody.innerHTML = "";

  // Populate table
  data.results.forEach((result) => {
    const row = document.createElement("tr");

    // Store Name
    const storeTd = document.createElement("td");
    storeTd.textContent = result.store_name;
    row.appendChild(storeTd);

    // Updated Count
    const countTd = document.createElement("td");
    countTd.textContent = result.updated_count;
    countTd.style.fontFamily = "monospace";
    row.appendChild(countTd);

    // Status
    const statusTd = document.createElement("td");
    if (result.success) {
      statusTd.innerHTML =
        '<span style="color: var(--success);">✓ Success</span>';
    } else {
      statusTd.innerHTML = `<span style="color: var(--error);">✗ Failed${result.error ? ": " + result.error : ""}</span>`;
      statusTd.style.fontSize = "0.875rem";
    }
    row.appendChild(statusTd);

    tableBody.appendChild(row);
  });

  // Show results
  resultsEl.style.display = "block";

  // Clear search results and hide update inputs after successful update
  if (data.total_updated > 0) {
    // Clear the search results
    currentSearchResults = {
      upc: "",
      matches: [],
      total_found: 0,
    };

    // Optionally hide search results and update form
    setTimeout(() => {
      document.getElementById("upc-search-results").style.display = "none";
      document.getElementById("new-upc-input").value = "";
      document.getElementById("update-all-btn").disabled = true;
      const newUpcContainer = document.getElementById("new-upc-container");
      const updateBtn = document.getElementById("update-all-btn");
      if (newUpcContainer) newUpcContainer.style.display = "none";
      if (updateBtn) updateBtn.style.display = "none";
    }, 3000); // Wait 3 seconds before clearing
  }
}

// Tool card click handlers
document.addEventListener("click", (e) => {
  const toolCard = e.target.closest(".tool-card");
  if (toolCard) {
    e.preventDefault();
    const page = toolCard.dataset.page;
    if (page) {
      navigateTo(page);
    }
  }
});

// Config Import/Export Functions
async function exportConfiguration() {
  try {
    const response = await fetch(`${API_BASE}/config/export`);

    if (!response.ok) {
      throw new Error(`Export failed: ${response.statusText}`);
    }

    const data = await response.json();

    // Create filename with timestamp
    const now = new Date();
    const timestamp = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const filename = `globalupc-config-${timestamp}.json`;

    // Create blob and download
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    alert(`Configuration exported successfully!\nFile: ${filename}`);
  } catch (error) {
    console.error("Export error:", error);
    alert(`Export failed: ${error.message}`);
  }
}

async function importConfiguration(file) {
  try {
    // Read file
    const text = await file.text();
    const config = JSON.parse(text);

    // Validate basic structure
    if (!config.version || !config.mssql_stores || !config.shopify_stores) {
      throw new Error("Invalid configuration file format");
    }

    // Confirm import
    const totalStores =
      config.mssql_stores.length + config.shopify_stores.length;
    if (
      !confirm(
        `Import ${totalStores} store configuration(s)?\n\nThis will add ${config.mssql_stores.length} MSSQL and ${config.shopify_stores.length} Shopify stores.\nExisting stores with duplicate shop domains will be skipped.`,
      )
    ) {
      return;
    }

    // Call import API
    const response = await fetch(`${API_BASE}/config/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Import failed");
    }

    const result = await response.json();

    // Build result message
    let message = `Import Summary:\n\n`;
    message += `Total: ${result.total_stores}\n`;
    message += `Created: ${result.created}\n`;
    message += `Skipped: ${result.skipped}\n`;
    message += `Failed: ${result.failed}\n`;

    // Add details if any failures or skips
    if (result.skipped > 0 || result.failed > 0) {
      message += `\nDetails:\n`;
      result.results.forEach((r) => {
        if (r.status === "skipped" || r.status === "failed") {
          message += `• ${r.name} (${r.store_type}): ${r.status}${r.reason ? " - " + r.reason : ""}\n`;
        }
      });
    }

    alert(message);

    // Reload stores list and dashboard
    await loadStores();
    await loadDashboard();
  } catch (error) {
    console.error("Import error:", error);
    alert(`Import failed: ${error.message}`);
  }
}

// Export button handler
document
  .getElementById("export-config-btn")
  ?.addEventListener("click", exportConfiguration);

// Import button handler
document.getElementById("import-config-btn")?.addEventListener("click", () => {
  document.getElementById("import-config-file").click();
});

// File input change handler
document
  .getElementById("import-config-file")
  ?.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) {
      importConfiguration(file);
      // Reset file input
      e.target.value = "";
    }
  });

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  // Load dashboard by default
  loadDashboard();

  // Load saved theme
  const savedTheme = localStorage.getItem("selectedTheme") || "current";
  setTheme(savedTheme);
});
