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
  } else if (page === "history") {
    loadHistoryPage();
  } else if (page === "sql-audit") {
    loadSQLAuditPage();
  } else if (page === "store-comparison") {
    loadMSSQLStoresForComparison();
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

// SQL UPC Audit Functions

// Helper function to format table names
function formatTableName(tableName) {
  const tableMap = {
    QuotationsDetails_tbl: "Quotation Details",
    PurchaseOrdersDetails_tbl: "Purchase Order Details",
    InvoicesDetails_tbl: "Invoice Details",
    CreditMemosDetails_tbl: "Credit Memo Details",
    PurchasesReturnsDetails_tbl: "Purchase Return Details",
    QuotationDetails: "Quotation Details",
  };
  return tableMap[tableName] || tableName;
}

async function loadSQLAuditPage() {
  const select = document.getElementById("audit-store-select");
  const runBtn = document.getElementById("run-audit-btn");

  // Reset UI
  select.innerHTML = '<option value="">-- Select a store --</option>';
  runBtn.disabled = true;
  document.getElementById("audit-loading").style.display = "none";
  document.getElementById("audit-empty").style.display = "none";
  document.getElementById("audit-results").style.display = "none";

  // Load MSSQL stores
  try {
    const stores = await apiRequest("/stores");
    const mssqlStores = stores.filter(
      (s) => s.store_type === "mssql" && s.is_active,
    );

    if (mssqlStores.length === 0) {
      select.innerHTML =
        '<option value="">No active SQL stores configured</option>';
      return;
    }

    // Populate dropdown
    mssqlStores.forEach((store) => {
      const option = document.createElement("option");
      option.value = store.id;
      option.textContent = store.name;
      select.appendChild(option);
    });
  } catch (error) {
    console.error("Error loading stores:", error);
  }
}

// Store selection change handler
document
  .getElementById("audit-store-select")
  ?.addEventListener("change", (e) => {
    const runBtn = document.getElementById("run-audit-btn");
    runBtn.disabled = !e.target.value;
  });

// Run audit button handler
document
  .getElementById("run-audit-btn")
  ?.addEventListener("click", async () => {
    const select = document.getElementById("audit-store-select");
    const storeId = parseInt(select.value);

    if (!storeId) {
      alert("Please select a store to audit");
      return;
    }

    await runAudit(storeId);
  });

// Table filter dropdown handler
document
  .getElementById("audit-table-filter")
  ?.addEventListener("change", (e) => {
    filterAuditResults(e.target.value);
  });

async function runAudit(storeId) {
  const loadingEl = document.getElementById("audit-loading");
  const progressContainer = document.getElementById("audit-progress");
  const progressItems = document.getElementById("audit-progress-items");
  const emptyEl = document.getElementById("audit-empty");
  const resultsEl = document.getElementById("audit-results");
  const runBtn = document.getElementById("run-audit-btn");

  // Capture date filter values
  const dateFromInput = document.getElementById("audit-date-from");
  const dateToInput = document.getElementById("audit-date-to");
  const dateFrom = dateFromInput.value || null;
  const dateTo = dateToInput.value || null;

  // Show loading state
  loadingEl.style.display = "block";
  progressContainer.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";
  progressItems.innerHTML = "";
  runBtn.disabled = true;

  try {
    // Build request body with optional date filters
    const requestBody = { store_id: storeId };
    if (dateFrom) requestBody.date_from = dateFrom;
    if (dateTo) requestBody.date_to = dateTo;

    // Use fetch with streaming for POST + SSE
    const response = await fetch(`${API_BASE}/analysis/orphaned-upcs/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

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
          if (data.status === "starting") {
            const item = document.createElement("div");
            item.style.cssText =
              "font-size: 0.875rem; color: var(--accent-primary);";
            item.textContent = `Starting audit for ${data.store_name}...`;
            progressItems.appendChild(item);
          } else if (data.status === "checking_table") {
            const item = document.createElement("div");
            item.style.cssText =
              "font-size: 0.875rem; color: var(--text-secondary);";
            item.textContent = `🔍 Checking ${data.table_name}...`;
            item.dataset.tableName = data.table_name; // Store table name for updates
            progressItems.appendChild(item);
            progressContainer.scrollTop = progressContainer.scrollHeight;
          } else if (data.status === "chunk_progress") {
            // Find the progress item for this table
            const tableItems = Array.from(progressItems.children).filter(
              (el) => el.dataset.tableName === data.table_name,
            );
            const lastItem = tableItems[tableItems.length - 1];

            if (lastItem) {
              // Calculate percentage
              const percentage = Math.round(
                (data.records_checked / data.total_records) * 100,
              );

              // Build progress message
              let message = `🔍 ${data.table_name}: Chunk ${data.chunk}/${data.total_chunks} (${percentage}%)`;
              message += ` - ${data.records_checked}/${data.total_records} records`;

              if (data.total_orphans > 0) {
                message += ` - ${data.total_orphans} orphan${data.total_orphans !== 1 ? "s" : ""} found`;
                lastItem.style.color = "orange";
              } else {
                lastItem.style.color = "var(--text-secondary)";
              }

              lastItem.textContent = message;
              progressContainer.scrollTop = progressContainer.scrollHeight;
            }
          } else if (data.status === "table_complete") {
            // Find all items for this table and update the last one
            const tableItems = Array.from(progressItems.children).filter(
              (el) => el.dataset.tableName === data.table_name,
            );
            const lastItem = tableItems[tableItems.length - 1];

            if (lastItem) {
              if (data.orphaned_count > 0) {
                lastItem.style.color = "var(--error)";
                lastItem.textContent = `✗ ${data.table_name} - ${data.orphaned_count} orphaned UPC${data.orphaned_count !== 1 ? "s" : ""}`;
              } else {
                lastItem.style.color = "var(--success)";
                lastItem.textContent = `✓ ${data.table_name} - OK`;
              }
            }
          } else if (data.status === "table_skipped") {
            const item = document.createElement("div");
            item.style.cssText =
              "font-size: 0.875rem; color: var(--text-tertiary);";
            item.textContent = `○ ${data.table_name} - not found (skipped)`;
            progressItems.appendChild(item);
            progressContainer.scrollTop = progressContainer.scrollHeight;
          }
        } else if (eventType === "complete") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";

          if (data.total_orphaned === 0) {
            emptyEl.style.display = "block";
          } else {
            displayAuditResults(data);
          }

          // Re-enable button
          runBtn.disabled = false;
        } else if (eventType === "error") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          alert(`Error: ${data.message}`);
          runBtn.disabled = false;
        }
      }
    }
  } catch (error) {
    loadingEl.style.display = "none";
    progressContainer.style.display = "none";
    alert(`Error: ${error.message}`);
    runBtn.disabled = false;
  }
}

// Global state for audit results
let currentAuditResults = {
  store_id: null,
  orphaned_records: [],
};

function displayAuditResults(data) {
  const resultsEl = document.getElementById("audit-results");
  const tableBody = document.getElementById("audit-results-table-body");
  const orphanedCountEl = document.getElementById("audit-orphaned-count");
  const tablesCountEl = document.getElementById("audit-tables-count");
  const reconciliationActions = document.getElementById(
    "reconciliation-actions",
  );

  // Store audit results globally for reconciliation
  currentAuditResults = {
    store_id: data.store_id,
    orphaned_records: data.orphaned_records,
  };

  // Update counts
  orphanedCountEl.textContent = data.total_orphaned;
  tablesCountEl.textContent = data.tables_checked;

  // Calculate table statistics
  const tableStats = {};
  data.orphaned_records.forEach((record) => {
    const tableName = record.table_name;
    tableStats[tableName] = (tableStats[tableName] || 0) + 1;
  });

  // Render statistics badges
  const statisticsContainer = document.getElementById("audit-statistics");
  statisticsContainer.innerHTML = "";
  statisticsContainer.style.display = "flex";

  Object.keys(tableStats)
    .sort((a, b) => tableStats[b] - tableStats[a]) // Sort by count descending
    .forEach((tableName) => {
      const badge = document.createElement("div");
      badge.className = "audit-stat-badge";
      badge.dataset.tableName = tableName;

      const nameSpan = document.createElement("span");
      nameSpan.className = "badge-table-name";
      nameSpan.textContent = formatTableName(tableName);

      const countSpan = document.createElement("span");
      countSpan.className = "badge-count";
      countSpan.textContent = tableStats[tableName];

      badge.appendChild(nameSpan);
      badge.appendChild(document.createTextNode(": "));
      badge.appendChild(countSpan);

      // Click handler to filter by this table
      badge.addEventListener("click", () => {
        const filterDropdown = document.getElementById("audit-table-filter");
        filterDropdown.value = tableName;
        filterAuditResults(tableName);
      });

      statisticsContainer.appendChild(badge);
    });

  // Populate filter dropdown
  const filterDropdown = document.getElementById("audit-table-filter");
  filterDropdown.innerHTML = '<option value="">All Tables</option>';

  Object.keys(tableStats)
    .sort()
    .forEach((tableName) => {
      const option = document.createElement("option");
      option.value = tableName;
      option.textContent = `${formatTableName(tableName)} (${tableStats[tableName]})`;
      filterDropdown.appendChild(option);
    });

  // Reset filter to "All Tables"
  filterDropdown.value = "";

  // Clear table
  tableBody.innerHTML = "";

  // Populate table with orphaned records
  data.orphaned_records.forEach((record, index) => {
    const row = document.createElement("tr");
    row.dataset.tableName = record.table_name; // Store table name for filtering
    row.dataset.rowIndex = index; // Store original index for row numbering

    // Checkbox
    const checkboxTd = document.createElement("td");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "orphan-checkbox";
    checkbox.dataset.index = index;
    checkbox.dataset.tableName = record.table_name;
    checkbox.dataset.primaryKey = record.primary_key;
    checkbox.dataset.upc = record.upc;
    checkbox.dataset.productId = record.product_id || "";
    checkbox.dataset.description = record.description || "";
    checkboxTd.appendChild(checkbox);
    row.appendChild(checkboxTd);

    // Row Number
    const rowNumTd = document.createElement("td");
    rowNumTd.textContent = index + 1;
    rowNumTd.style.color = "var(--text-tertiary)";
    rowNumTd.style.fontWeight = "500";
    row.appendChild(rowNumTd);

    // Table Name
    const tableTd = document.createElement("td");
    tableTd.textContent = formatTableName(record.table_name);
    tableTd.style.color = "var(--accent-primary)";
    row.appendChild(tableTd);

    // Primary Key
    const pkTd = document.createElement("td");
    pkTd.textContent = record.primary_key;
    pkTd.style.fontFamily = "monospace";
    row.appendChild(pkTd);

    // UPC
    const upcTd = document.createElement("td");
    upcTd.textContent = record.upc;
    upcTd.style.fontFamily = "monospace";
    upcTd.style.fontWeight = "bold";
    upcTd.style.color = "var(--error)";
    row.appendChild(upcTd);

    // Description
    const descTd = document.createElement("td");
    descTd.textContent = record.description || "Unknown";
    descTd.style.color = record.description
      ? "inherit"
      : "var(--text-tertiary)";
    row.appendChild(descTd);

    tableBody.appendChild(row);
  });

  // Show results and reconciliation actions
  resultsEl.style.display = "block";
  reconciliationActions.style.display = "flex";

  // Reset checkboxes and buttons
  document.getElementById("select-all-orphans").checked = false;
  updateReconciliationButtons();
}

// Filter audit results by table name
function filterAuditResults(filterTableName) {
  const tableBody = document.getElementById("audit-results-table-body");
  const rows = tableBody.querySelectorAll("tr");
  const orphanedCountEl = document.getElementById("audit-orphaned-count");
  const filterTextEl = document.getElementById("audit-filter-text");
  const tablesCountEl = document.getElementById("audit-tables-count");

  let visibleCount = 0;
  let visibleRowNumber = 1;

  rows.forEach((row) => {
    const rowTableName = row.dataset.tableName;

    if (!filterTableName || rowTableName === filterTableName) {
      // Show row
      row.style.display = "";
      visibleCount++;

      // Update row number
      const rowNumTd = row.querySelector("td:nth-child(2)");
      if (rowNumTd) {
        rowNumTd.textContent = visibleRowNumber;
        visibleRowNumber++;
      }
    } else {
      // Hide row
      row.style.display = "none";
    }
  });

  // Update summary text
  const totalOrphaned = currentAuditResults.orphaned_records.length;

  if (!filterTableName) {
    // No filter - show all
    orphanedCountEl.textContent = totalOrphaned;
    filterTextEl.textContent = " orphaned UPCs found across";
    tablesCountEl.style.display = "inline";
  } else {
    // Filtered - show count and filter status
    orphanedCountEl.textContent = visibleCount;
    filterTextEl.textContent = ` of ${totalOrphaned} orphaned UPCs (filtered by ${formatTableName(filterTableName)})`;
    tablesCountEl.style.display = "none";
  }

  // Reset "select all" checkbox
  document.getElementById("select-all-orphans").checked = false;
  updateReconciliationButtons();
}

// Reconciliation Functions
function updateReconciliationButtons() {
  const checkboxes = document.querySelectorAll(".orphan-checkbox:checked");
  let visibleCount = 0;

  // Count only visible checked checkboxes
  checkboxes.forEach((cb) => {
    const row = cb.closest("tr");
    if (row && row.style.display !== "none") {
      visibleCount++;
    }
  });

  const selectionCount = document.getElementById("selection-count");
  const reconcileByIdBtn = document.getElementById(
    "reconcile-by-product-id-btn",
  );
  const reconcileByDescBtn = document.getElementById(
    "reconcile-by-description-btn",
  );

  selectionCount.textContent = `${visibleCount} selected`;
  reconcileByIdBtn.disabled = visibleCount === 0;
  reconcileByDescBtn.disabled = visibleCount === 0;
}

// Select All checkbox handler
document
  .getElementById("select-all-orphans")
  ?.addEventListener("change", (e) => {
    const checkboxes = document.querySelectorAll(".orphan-checkbox");
    checkboxes.forEach((cb) => {
      const row = cb.closest("tr");
      // Only check/uncheck if the row is visible
      if (row && row.style.display !== "none") {
        cb.checked = e.target.checked;
      }
    });
    updateReconciliationButtons();
  });

// Individual checkbox change handler (using event delegation)
document
  .getElementById("audit-results-table-body")
  ?.addEventListener("change", (e) => {
    if (e.target.classList.contains("orphan-checkbox")) {
      updateReconciliationButtons();

      // Update "select all" checkbox state based on VISIBLE checkboxes only
      const allCheckboxes = Array.from(
        document.querySelectorAll(".orphan-checkbox"),
      ).filter((cb) => {
        const row = cb.closest("tr");
        return row && row.style.display !== "none";
      });

      const checkedCheckboxes = allCheckboxes.filter((cb) => cb.checked);
      const selectAllCheckbox = document.getElementById("select-all-orphans");

      if (selectAllCheckbox) {
        selectAllCheckbox.checked =
          allCheckboxes.length > 0 &&
          allCheckboxes.length === checkedCheckboxes.length;
      }
    }
  });

// Global AbortController for cancelling reconciliation operations
let reconciliationAbortController = null;

// Get selected orphaned records
function getSelectedOrphanedRecords() {
  const checkboxes = document.querySelectorAll(".orphan-checkbox:checked");
  const records = [];

  checkboxes.forEach((cb) => {
    // Get the parent row
    const row = cb.closest("tr");

    // Only include if the row is visible (not filtered out)
    if (row && row.style.display !== "none") {
      records.push({
        table_name: cb.dataset.tableName,
        primary_key: parseInt(cb.dataset.primaryKey),
        upc: cb.dataset.upc,
        product_id: cb.dataset.productId
          ? parseInt(cb.dataset.productId)
          : null,
        description: cb.dataset.description || null,
      });
    }
  });

  return records;
}

// Reconcile by ProductID button handler
document
  .getElementById("reconcile-by-product-id-btn")
  ?.addEventListener("click", async () => {
    const selectedRecords = getSelectedOrphanedRecords();
    if (selectedRecords.length === 0) {
      alert("Please select at least one record to reconcile");
      return;
    }

    await reconcileOrphanedUPCs("product_id", selectedRecords);
  });

// Reconcile by Description button handler
document
  .getElementById("reconcile-by-description-btn")
  ?.addEventListener("click", async () => {
    const selectedRecords = getSelectedOrphanedRecords();
    if (selectedRecords.length === 0) {
      alert("Please select at least one record to reconcile");
      return;
    }

    await reconcileOrphanedUPCs("product_description", selectedRecords);
  });

async function reconcileOrphanedUPCs(matchType, orphanedRecords) {
  const modal = document.getElementById("reconciliation-modal");
  const modalTitle = document.getElementById("reconciliation-modal-title");
  const loadingEl = document.getElementById("reconciliation-loading");
  const progressContainer = document.getElementById("reconciliation-progress");
  const progressText = document.getElementById("reconciliation-progress-text");
  const resultsEl = document.getElementById("reconciliation-results");
  const cancelBtn = document.getElementById("cancel-reconciliation-btn");
  const updateBtn = document.getElementById("update-matched-upcs-btn");

  // Create new AbortController for this operation
  reconciliationAbortController = new AbortController();

  // Open modal and show loading
  openModal("reconciliation-modal");
  modalTitle.textContent =
    matchType === "product_id"
      ? "Reconciliation by ProductID"
      : "Reconciliation by Description";
  loadingEl.style.display = "block";
  progressContainer.style.display = "block";
  resultsEl.style.display = "none";
  progressText.textContent = "Starting reconciliation...";

  // Show cancel button, hide update button
  cancelBtn.style.display = "inline-block";
  updateBtn.style.display = "none";

  try {
    // Use SSE streaming endpoint with abort signal
    const response = await fetch(`${API_BASE}/analysis/reconcile-upcs/stream`, {
      method: "POST",
      signal: reconciliationAbortController.signal,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        store_id: currentAuditResults.store_id,
        match_type: matchType,
        orphaned_records: orphanedRecords,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();

      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // Keep incomplete message in buffer

      for (const line of lines) {
        if (!line.trim() || line.startsWith(":")) continue; // Skip heartbeats

        const eventMatch = line.match(/event: (\w+)\ndata: (.+)/s);
        if (!eventMatch) continue;

        const [, eventType, dataStr] = eventMatch;
        const data = JSON.parse(dataStr);

        if (eventType === "progress") {
          if (data.status === "checked") {
            // Update progress text
            const matchedText = data.matched ? "(✓ matched)" : "(not matched)";
            progressText.textContent = `Checking records: ${data.current}/${data.total} ${matchedText}`;
          }
        } else if (eventType === "complete") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          cancelBtn.style.display = "none";
          displayReconciliationResults(data);
        } else if (eventType === "error") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          cancelBtn.style.display = "none";
          alert(`Error: ${data.message}`);
          closeModal("reconciliation-modal");
        }
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      // Operation was cancelled by user
      progressText.textContent = "Operation cancelled by user";
      progressText.style.color = "var(--warning)";
      setTimeout(() => {
        loadingEl.style.display = "none";
        progressContainer.style.display = "none";
        cancelBtn.style.display = "none";
        progressText.style.color = "";
      }, 2000);
    } else {
      loadingEl.style.display = "none";
      progressContainer.style.display = "none";
      cancelBtn.style.display = "none";
      alert(`Error: ${error.message}`);
      closeModal("reconciliation-modal");
    }
  } finally {
    // Cleanup
    reconciliationAbortController = null;
  }
}

function displayReconciliationResults(data) {
  const loadingEl = document.getElementById("reconciliation-loading");
  const resultsEl = document.getElementById("reconciliation-results");
  const tableBody = document.getElementById(
    "reconciliation-results-table-body",
  );
  const matchedCountEl = document.getElementById(
    "reconciliation-matched-count",
  );
  const unmatchedCountEl = document.getElementById(
    "reconciliation-unmatched-count",
  );
  const updateBtn = document.getElementById("update-matched-upcs-btn");

  // Hide loading, show results
  loadingEl.style.display = "none";
  resultsEl.style.display = "block";

  // Show update button
  updateBtn.style.display = "inline-block";

  // Update counts
  matchedCountEl.textContent = data.total_matched;
  unmatchedCountEl.textContent = data.total_checked - data.total_matched;

  // Clear table
  tableBody.innerHTML = "";

  // Helper function to format table names
  const formatTableName = (tableName) => {
    const tableMap = {
      QuotationsDetails_tbl: "Quotation Details",
      PurchaseOrdersDetails_tbl: "Purchase Order Details",
      InvoicesDetails_tbl: "Invoice Details",
      CreditMemosDetails_tbl: "Credit Memo Details",
      PurchasesReturnsDetails_tbl: "Purchase Return Details",
      QuotationDetails: "Quotation Details",
    };
    return tableMap[tableName] || tableName;
  };

  // Populate table with reconciliation matches
  data.matches.forEach((match) => {
    const row = document.createElement("tr");

    // Checkbox (only for matched records)
    const checkboxTd = document.createElement("td");
    if (match.match_found) {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "match-checkbox";
      checkbox.checked = true; // Pre-select matched records
      checkbox.dataset.tableName = match.table_name;
      checkbox.dataset.primaryKey = match.primary_key;
      checkbox.dataset.orphanedUpc = match.orphaned_upc;
      checkbox.dataset.itemsTblUpc = match.items_tbl_upc;
      checkbox.dataset.matchFieldValue = match.match_field_value;
      checkboxTd.appendChild(checkbox);
    }
    row.appendChild(checkboxTd);

    // Table Name
    const tableTd = document.createElement("td");
    tableTd.textContent = formatTableName(match.table_name);
    tableTd.style.color = "var(--accent-primary)";
    row.appendChild(tableTd);

    // Primary Key
    const pkTd = document.createElement("td");
    pkTd.textContent = match.primary_key;
    pkTd.style.fontFamily = "monospace";
    row.appendChild(pkTd);

    // Orphaned UPC
    const orphanedUpcTd = document.createElement("td");
    orphanedUpcTd.textContent = match.orphaned_upc;
    orphanedUpcTd.style.fontFamily = "monospace";
    orphanedUpcTd.style.color = "var(--error)";
    row.appendChild(orphanedUpcTd);

    // Matched UPC
    const matchedUpcTd = document.createElement("td");
    if (match.match_found) {
      matchedUpcTd.textContent = match.items_tbl_upc;
      matchedUpcTd.style.fontFamily = "monospace";
      matchedUpcTd.style.color = "var(--success)";
      matchedUpcTd.style.fontWeight = "bold";
    } else {
      matchedUpcTd.textContent = "-";
      matchedUpcTd.style.color = "var(--text-tertiary)";
    }
    row.appendChild(matchedUpcTd);

    // Status
    const statusTd = document.createElement("td");
    if (match.match_found) {
      statusTd.innerHTML =
        '<span style="color: var(--success);">✓ Found</span>';
    } else {
      statusTd.innerHTML =
        '<span style="color: var(--text-tertiary);">✗ Not Found</span>';
    }
    row.appendChild(statusTd);

    // Match Field Value
    const matchFieldTd = document.createElement("td");
    matchFieldTd.textContent = match.match_field_value;
    matchFieldTd.style.fontSize = "0.875rem";
    matchFieldTd.style.color = "var(--text-secondary)";
    row.appendChild(matchFieldTd);

    tableBody.appendChild(row);
  });

  // Update "Update Selected Matches" button state
  updateMatchesUpdateButton();
}

// Select All matches checkbox handler
document
  .getElementById("select-all-matches")
  ?.addEventListener("change", (e) => {
    const checkboxes = document.querySelectorAll(".match-checkbox");
    checkboxes.forEach((cb) => {
      cb.checked = e.target.checked;
    });
    updateMatchesUpdateButton();
  });

// Individual match checkbox change handler (using event delegation)
document
  .getElementById("reconciliation-results-table-body")
  ?.addEventListener("change", (e) => {
    if (e.target.classList.contains("match-checkbox")) {
      updateMatchesUpdateButton();

      // Update "select all" checkbox state
      const allCheckboxes = document.querySelectorAll(".match-checkbox");
      const checkedCheckboxes = document.querySelectorAll(
        ".match-checkbox:checked",
      );
      const selectAllCheckbox = document.getElementById("select-all-matches");

      if (selectAllCheckbox) {
        selectAllCheckbox.checked =
          allCheckboxes.length > 0 &&
          allCheckboxes.length === checkedCheckboxes.length;
      }
    }
  });

function updateMatchesUpdateButton() {
  const checkboxes = document.querySelectorAll(".match-checkbox:checked");
  const updateBtn = document.getElementById("update-matched-upcs-btn");
  updateBtn.disabled = checkboxes.length === 0;
}

// Update matched UPCs button handler
document
  .getElementById("update-matched-upcs-btn")
  ?.addEventListener("click", async () => {
    const checkboxes = document.querySelectorAll(".match-checkbox:checked");
    if (checkboxes.length === 0) {
      alert("Please select at least one match to update");
      return;
    }

    const updates = [];
    checkboxes.forEach((cb) => {
      updates.push({
        table_name: cb.dataset.tableName,
        primary_key: parseInt(cb.dataset.primaryKey),
        orphaned_upc: cb.dataset.orphanedUpc,
        match_found: true,
        items_tbl_upc: cb.dataset.itemsTblUpc,
        match_field_value: cb.dataset.matchFieldValue,
      });
    });

    // Confirm update
    const message = `Update ${updates.length} orphaned UPC${updates.length !== 1 ? "s" : ""} with matched values from Items_tbl?`;
    if (!confirm(message)) {
      return;
    }

    await updateReconciledUPCs(updates);
  });

async function updateReconciledUPCs(updates) {
  const updateBtn = document.getElementById("update-matched-upcs-btn");
  const loadingEl = document.getElementById("reconciliation-loading");
  const progressContainer = document.getElementById("reconciliation-progress");
  const progressText = document.getElementById("reconciliation-progress-text");
  const resultsEl = document.getElementById("reconciliation-results");
  const cancelBtn = document.getElementById("cancel-reconciliation-btn");

  // Create new AbortController for this operation
  reconciliationAbortController = new AbortController();

  updateBtn.disabled = true;
  updateBtn.textContent = "Updating...";

  // Show progress UI and cancel button
  loadingEl.style.display = "block";
  progressContainer.style.display = "block";
  resultsEl.style.display = "none";
  progressText.textContent = "Starting batch updates...";
  cancelBtn.style.display = "inline-block";
  updateBtn.style.display = "none";

  try {
    // Use SSE streaming endpoint with abort signal
    const response = await fetch(
      `${API_BASE}/analysis/reconcile-upcs/update/stream`,
      {
        method: "POST",
        signal: reconciliationAbortController.signal,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          store_id: currentAuditResults.store_id,
          updates: updates,
        }),
      },
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalData = null;

    while (true) {
      const { done, value } = await reader.read();

      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // Keep incomplete message in buffer

      for (const line of lines) {
        if (!line.trim() || line.startsWith(":")) continue; // Skip heartbeats

        const eventMatch = line.match(/event: (\w+)\ndata: (.+)/s);
        if (!eventMatch) continue;

        const [, eventType, dataStr] = eventMatch;
        const data = JSON.parse(dataStr);

        if (eventType === "progress") {
          if (data.status === "updating_batch") {
            progressText.textContent = `Processing batch ${data.batch_number}/${data.total_batches}...`;
          } else if (data.status === "batch_complete") {
            const successColor =
              data.batch_updated > 0 ? "var(--success)" : "var(--error)";
            progressText.innerHTML = `Batch ${data.batch_number}/${data.total_batches}: <span style="color: ${successColor};">${data.batch_updated} updated</span>, ${data.batch_failed} failed (Total: ${data.total_updated} updated, ${data.total_failed} failed)`;
          }
        } else if (eventType === "complete") {
          finalData = data;
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          cancelBtn.style.display = "none";
        } else if (eventType === "error") {
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          cancelBtn.style.display = "none";
          alert(`Error: ${data.message}`);
          updateBtn.disabled = false;
          updateBtn.textContent = "Update Selected Matches";
          updateBtn.style.display = "inline-block";
          return;
        }
      }
    }

    // Show results if we have final data
    if (finalData) {
      let message = `Update Summary:\n\n`;
      message += `Total Updated: ${finalData.total_updated}\n`;
      message += `Total Failed: ${finalData.total_failed}\n`;

      if (finalData.total_failed > 0) {
        message += `\nFailed Updates:\n`;
        finalData.results
          .filter((r) => !r.success)
          .forEach((r) => {
            message += `• Table: ${r.table_name}, ID: ${r.primary_key} - ${r.error}\n`;
          });
      }

      alert(message);

      // Close modal
      closeModal("reconciliation-modal");

      // Re-run audit to refresh results
      const select = document.getElementById("audit-store-select");
      const storeId = parseInt(select.value);
      if (storeId) {
        await runAudit(storeId);
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      // Operation was cancelled by user
      progressText.textContent = "Operation cancelled by user";
      progressText.style.color = "var(--warning)";
      setTimeout(() => {
        loadingEl.style.display = "none";
        progressContainer.style.display = "none";
        cancelBtn.style.display = "none";
        updateBtn.style.display = "inline-block";
        progressText.style.color = "";
      }, 2000);
    } else {
      loadingEl.style.display = "none";
      progressContainer.style.display = "none";
      cancelBtn.style.display = "none";
      updateBtn.style.display = "inline-block";
      resultsEl.style.display = "block";
      alert(`Error: ${error.message}`);
    }
  } finally {
    updateBtn.disabled = false;
    updateBtn.textContent = "Update Selected Matches";
    reconciliationAbortController = null;
  }
}

// Cancel reconciliation operation button handler
document
  .getElementById("cancel-reconciliation-btn")
  ?.addEventListener("click", () => {
    if (reconciliationAbortController) {
      reconciliationAbortController.abort();
    }
  });

// ============================================
// History Page Functions
// ============================================

// Global state for history
let historyState = {
  currentPage: 0,
  pageSize: 50,
  totalRecords: 0,
  filters: {
    store_id: null,
    upc_search: null,
    success_filter: null,
    start_date: null,
    end_date: null,
  },
};

async function loadHistoryPage() {
  // Load stores for filter dropdown
  const stores = await apiRequest("/stores");
  const storeFilter = document.getElementById("history-store-filter");
  storeFilter.innerHTML = '<option value="">All Stores</option>';
  stores.forEach((store) => {
    const option = document.createElement("option");
    option.value = store.id;
    option.textContent = `${store.name} (${store.store_type})`;
    storeFilter.appendChild(option);
  });

  // Reset state
  historyState.currentPage = 0;
  historyState.filters = {
    store_id: null,
    upc_search: null,
    success_filter: null,
    start_date: null,
    end_date: null,
  };

  // Load history
  await loadHistory();
}

async function loadHistory() {
  const loadingEl = document.getElementById("history-loading");
  const emptyEl = document.getElementById("history-empty");
  const resultsEl = document.getElementById("history-results");

  loadingEl.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";

  try {
    // Build query parameters
    const params = new URLSearchParams();
    params.append("limit", historyState.pageSize);
    params.append("offset", historyState.currentPage * historyState.pageSize);

    if (historyState.filters.store_id) {
      params.append("store_id", historyState.filters.store_id);
    }
    if (historyState.filters.upc_search) {
      params.append("upc_search", historyState.filters.upc_search);
    }
    if (historyState.filters.success_filter !== null) {
      params.append("success_filter", historyState.filters.success_filter);
    }
    if (historyState.filters.start_date) {
      params.append("start_date", historyState.filters.start_date);
    }
    if (historyState.filters.end_date) {
      params.append("end_date", historyState.filters.end_date);
    }

    const data = await apiRequest(`/history/updates?${params.toString()}`);
    historyState.totalRecords = data.total;

    loadingEl.style.display = "none";

    if (data.batches.length === 0) {
      emptyEl.style.display = "block";
    } else {
      resultsEl.style.display = "block";
      displayHistoryResults(data.batches, data.total);
    }
  } catch (error) {
    loadingEl.style.display = "none";
    alert(`Error loading history: ${error.message}`);
  }
}

function displayHistoryResults(batches, total) {
  document.getElementById("history-total-count").textContent = total;

  const tbody = document.getElementById("history-results-table-body");
  tbody.innerHTML = "";

  batches.forEach((batch, index) => {
    const recordNumber =
      historyState.currentPage * historyState.pageSize + index + 1;

    // Create main batch row (collapsed by default)
    const batchRow = document.createElement("tr");
    batchRow.style.cursor = "pointer";
    batchRow.style.backgroundColor = "var(--bg-secondary)";
    batchRow.dataset.batchId = batch.batch_id;

    // Row number with expand/collapse icon
    const numCell = document.createElement("td");
    numCell.style.color = "var(--text-tertiary)";
    numCell.style.fontSize = "0.875rem";
    const expandIcon = document.createElement("span");
    expandIcon.textContent = "▶ ";
    expandIcon.style.display = "inline-block";
    expandIcon.style.transition = "transform 0.2s";
    numCell.appendChild(expandIcon);
    numCell.appendChild(document.createTextNode(recordNumber.toString()));
    batchRow.appendChild(numCell);

    // Timestamp
    const timestampCell = document.createElement("td");
    const date = new Date(batch.created_at);
    timestampCell.textContent = date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    timestampCell.style.fontSize = "0.875rem";
    batchRow.appendChild(timestampCell);

    // Stores summary
    const storesCell = document.createElement("td");
    storesCell.textContent = `${batch.total_stores} store${batch.total_stores > 1 ? "s" : ""}`;
    storesCell.style.fontWeight = "600";
    batchRow.appendChild(storesCell);

    // UPC Change
    const upcCell = document.createElement("td");
    upcCell.style.fontFamily = "monospace";
    upcCell.style.fontSize = "0.875rem";
    upcCell.innerHTML = `${batch.old_upc} <span style="color: var(--text-tertiary)">→</span> ${batch.new_upc}`;
    batchRow.appendChild(upcCell);

    // Total items updated
    const countCell = document.createElement("td");
    countCell.textContent = batch.total_items_updated;
    countCell.style.fontWeight = "600";
    countCell.style.color = "var(--success)";
    batchRow.appendChild(countCell);

    // Status summary
    const statusCell = document.createElement("td");
    if (batch.failed_stores === 0) {
      statusCell.innerHTML = `<span style="color: var(--success)">✓ All Success</span>`;
    } else if (batch.successful_stores === 0) {
      statusCell.innerHTML = `<span style="color: var(--error)">✗ All Failed</span>`;
    } else {
      statusCell.innerHTML = `<span style="color: var(--warning)">${batch.successful_stores} success, ${batch.failed_stores} failed</span>`;
    }
    statusCell.style.fontSize = "0.875rem";
    batchRow.appendChild(statusCell);

    // Empty cell for details column
    const emptyCell = document.createElement("td");
    batchRow.appendChild(emptyCell);

    // Click handler to expand/collapse
    let isExpanded = false;
    batchRow.addEventListener("click", () => {
      isExpanded = !isExpanded;
      expandIcon.style.transform = isExpanded
        ? "rotate(90deg)"
        : "rotate(0deg)";

      // Toggle visibility of detail rows
      const detailRows = tbody.querySelectorAll(
        `[data-batch-detail="${batch.batch_id}"]`,
      );
      detailRows.forEach((row) => {
        row.style.display = isExpanded ? "" : "none";
      });
    });

    tbody.appendChild(batchRow);

    // Create detail rows for each store update (hidden by default)
    batch.updates.forEach((update) => {
      const detailRow = document.createElement("tr");
      detailRow.style.display = "none";
      detailRow.style.backgroundColor = "var(--bg-tertiary)";
      detailRow.dataset.batchDetail = batch.batch_id;

      // Empty cell for indentation
      const indentCell = document.createElement("td");
      indentCell.textContent = "";
      detailRow.appendChild(indentCell);

      // Empty timestamp cell
      const emptyTimestampCell = document.createElement("td");
      detailRow.appendChild(emptyTimestampCell);

      // Store name with badge
      const storeCell = document.createElement("td");
      const storeBadge = document.createElement("span");
      storeBadge.textContent = update.store_type.toUpperCase();
      storeBadge.style.display = "inline-block";
      storeBadge.style.padding = "0.125rem 0.375rem";
      storeBadge.style.fontSize = "0.625rem";
      storeBadge.style.fontWeight = "600";
      storeBadge.style.borderRadius = "0.25rem";
      storeBadge.style.marginRight = "0.5rem";
      storeBadge.style.backgroundColor =
        update.store_type === "shopify"
          ? "var(--accent-primary)"
          : "var(--info)";
      storeBadge.style.color = "var(--text-primary)";
      storeCell.appendChild(storeBadge);
      storeCell.appendChild(document.createTextNode(update.store_name));
      detailRow.appendChild(storeCell);

      // Product/Table info
      const productCell = document.createElement("td");
      productCell.style.fontSize = "0.875rem";
      productCell.style.color = "var(--text-secondary)";
      if (update.table_name) {
        productCell.textContent = update.table_name;
      } else if (update.product_title) {
        productCell.textContent = update.product_title;
      } else {
        productCell.textContent = "-";
      }
      detailRow.appendChild(productCell);

      // Items count
      const itemsCell = document.createElement("td");
      itemsCell.textContent = update.items_updated_count;
      itemsCell.style.fontWeight = "600";
      itemsCell.style.color = update.success
        ? "var(--success)"
        : "var(--error)";
      detailRow.appendChild(itemsCell);

      // Status
      const detailStatusCell = document.createElement("td");
      if (update.success) {
        detailStatusCell.innerHTML =
          '<span style="color: var(--success)">✓ Success</span>';
      } else {
        detailStatusCell.innerHTML = `<span style="color: var(--error)" title="${update.error_message || "Failed"}">✗ Failed</span>`;
      }
      detailStatusCell.style.fontSize = "0.875rem";
      detailRow.appendChild(detailStatusCell);

      // Details button
      const detailsCell = document.createElement("td");
      const detailsBtn = document.createElement("button");
      detailsBtn.className = "btn btn-secondary";
      detailsBtn.style.padding = "0.25rem 0.5rem";
      detailsBtn.style.fontSize = "0.75rem";
      detailsBtn.textContent = "View";
      detailsBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        showHistoryDetails(update);
      });
      detailsCell.appendChild(detailsBtn);
      detailRow.appendChild(detailsCell);

      tbody.appendChild(detailRow);
    });
  });

  // Update pagination
  updateHistoryPagination(total);
}

function showHistoryDetails(item) {
  const details = [];
  if (item.product_id) details.push(`Product ID: ${item.product_id}`);
  if (item.product_title) details.push(`Product: ${item.product_title}`);
  if (item.variant_id) details.push(`Variant ID: ${item.variant_id}`);
  if (item.variant_title) details.push(`Variant: ${item.variant_title}`);
  if (item.table_name) details.push(`Table: ${item.table_name}`);
  if (item.primary_keys && item.primary_keys.length > 0) {
    details.push(`Record IDs: ${item.primary_keys.join(", ")}`);
  }
  if (item.error_message) details.push(`Error: ${item.error_message}`);

  alert(details.join("\n") || "No additional details available");
}

function updateHistoryPagination(total) {
  const totalPages = Math.ceil(total / historyState.pageSize);
  const currentPage = historyState.currentPage + 1;

  document.getElementById("history-page-info").textContent =
    `Page ${currentPage} of ${totalPages}`;

  const prevBtn = document.getElementById("history-prev-btn");
  const nextBtn = document.getElementById("history-next-btn");

  prevBtn.disabled = historyState.currentPage === 0;
  nextBtn.disabled = currentPage >= totalPages;
}

// Event listeners for history page
document
  .getElementById("apply-history-filters-btn")
  ?.addEventListener("click", async () => {
    const storeId = document.getElementById("history-store-filter").value;
    const upcSearch = document.getElementById("history-upc-filter").value;
    const successFilter = document.getElementById(
      "history-success-filter",
    ).value;
    const startDate = document.getElementById("history-start-date").value;
    const endDate = document.getElementById("history-end-date").value;

    historyState.filters = {
      store_id: storeId || null,
      upc_search: upcSearch || null,
      success_filter: successFilter === "" ? null : successFilter === "true",
      start_date: startDate ? `${startDate}T00:00:00` : null,
      end_date: endDate ? `${endDate}T23:59:59` : null,
    };
    historyState.currentPage = 0;

    await loadHistory();
  });

document
  .getElementById("clear-history-filters-btn")
  ?.addEventListener("click", async () => {
    document.getElementById("history-store-filter").value = "";
    document.getElementById("history-upc-filter").value = "";
    document.getElementById("history-success-filter").value = "";
    document.getElementById("history-start-date").value = "";
    document.getElementById("history-end-date").value = "";

    historyState.filters = {
      store_id: null,
      upc_search: null,
      success_filter: null,
      start_date: null,
      end_date: null,
    };
    historyState.currentPage = 0;

    await loadHistory();
  });

document
  .getElementById("history-prev-btn")
  ?.addEventListener("click", async () => {
    if (historyState.currentPage > 0) {
      historyState.currentPage--;
      await loadHistory();
    }
  });

document
  .getElementById("history-next-btn")
  ?.addEventListener("click", async () => {
    const totalPages = Math.ceil(
      historyState.totalRecords / historyState.pageSize,
    );
    if (historyState.currentPage < totalPages - 1) {
      historyState.currentPage++;
      await loadHistory();
    }
  });

document
  .getElementById("history-page-size")
  ?.addEventListener("change", async (e) => {
    historyState.pageSize = parseInt(e.target.value, 10);
    historyState.currentPage = 0;
    await loadHistory();
  });

// ==========================================
// Store Comparison Functions
// ==========================================

let comparisonState = {
  primaryStoreId: null,
  comparisonStoreId: null,
  categories: [],
  subcategories: [],
  results: null,
};

async function loadMSSQLStoresForComparison() {
  try {
    const response = await fetch(`${API_BASE}/stores`);
    const stores = await response.json();

    // Filter for MSSQL stores only
    const mssqlStores = stores.filter((s) => s.store_type === "mssql");

    const primarySelect = document.getElementById("comparison-primary-store");
    const comparisonSelect = document.getElementById(
      "comparison-comparison-store",
    );

    // Populate both dropdowns
    [primarySelect, comparisonSelect].forEach((select) => {
      select.innerHTML = '<option value="">Select store...</option>';
      mssqlStores.forEach((store) => {
        const option = document.createElement("option");
        option.value = store.id;
        option.textContent = store.name;
        select.appendChild(option);
      });
    });
  } catch (error) {
    console.error("Error loading MSSQL stores:", error);
  }
}

async function loadCategoriesForStore(storeId) {
  try {
    const response = await fetch(
      `${API_BASE}/stores/mssql/${storeId}/categories`,
    );
    const categories = await response.json();

    comparisonState.categories = categories;

    const categoriesSelect = document.getElementById("comparison-categories");
    categoriesSelect.innerHTML = "";

    if (categories.length === 0) {
      categoriesSelect.innerHTML =
        '<option value="">No categories found</option>';
      categoriesSelect.disabled = true;
    } else {
      categoriesSelect.disabled = false;
      categories.forEach((cat) => {
        const option = document.createElement("option");
        option.value = cat.category_id;
        option.textContent = cat.category_name;
        categoriesSelect.appendChild(option);
      });
    }

    // Reset subcategories when categories change
    const subcategoriesSelect = document.getElementById(
      "comparison-subcategories",
    );
    subcategoriesSelect.innerHTML =
      '<option value="">Select categories first...</option>';
    subcategoriesSelect.disabled = true;
  } catch (error) {
    console.error("Error loading categories:", error);
  }
}

async function loadSubcategoriesForStore(storeId, categoryIds) {
  try {
    // If no categories selected, load all subcategories
    const params = categoryIds.length > 0 ? `?category_id=${categoryIds[0]}` : "";
    const response = await fetch(
      `${API_BASE}/stores/mssql/${storeId}/subcategories${params}`,
    );
    let subcategories = await response.json();

    // If multiple categories selected, fetch for all and merge
    if (categoryIds.length > 1) {
      for (let i = 1; i < categoryIds.length; i++) {
        const resp = await fetch(
          `${API_BASE}/stores/mssql/${storeId}/subcategories?category_id=${categoryIds[i]}`,
        );
        const moreSubs = await resp.json();
        subcategories = [...subcategories, ...moreSubs];
      }
    }

    comparisonState.subcategories = subcategories;

    const subcategoriesSelect = document.getElementById(
      "comparison-subcategories",
    );
    subcategoriesSelect.innerHTML = "";

    if (subcategories.length === 0) {
      subcategoriesSelect.innerHTML =
        '<option value="">No subcategories found</option>';
      subcategoriesSelect.disabled = true;
    } else {
      subcategoriesSelect.disabled = false;
      subcategories.forEach((subcat) => {
        const option = document.createElement("option");
        option.value = subcat.subcategory_id;
        option.textContent = subcat.subcategory_name;
        subcategoriesSelect.appendChild(option);
      });
    }
  } catch (error) {
    console.error("Error loading subcategories:", error);
  }
}

async function runStoreComparison() {
  const primaryStoreId = parseInt(
    document.getElementById("comparison-primary-store").value,
  );
  const comparisonStoreId = parseInt(
    document.getElementById("comparison-comparison-store").value,
  );

  if (!primaryStoreId || !comparisonStoreId) {
    alert("Please select both stores");
    return;
  }

  // Get selected filters
  const categoriesSelect = document.getElementById("comparison-categories");
  const selectedCategories = Array.from(categoriesSelect.selectedOptions).map(
    (opt) => parseInt(opt.value),
  );

  const subcategoriesSelect = document.getElementById(
    "comparison-subcategories",
  );
  const selectedSubcategories = Array.from(
    subcategoriesSelect.selectedOptions,
  ).map((opt) => parseInt(opt.value));

  const includeDiscontinued = document.getElementById(
    "comparison-include-discontinued",
  ).checked;

  // Show loading state
  const loadingEl = document.getElementById("comparison-loading");
  const progressContainer = document.getElementById(
    "comparison-progress-container",
  );
  const progressItems = document.getElementById("comparison-progress-items");
  const emptyEl = document.getElementById("comparison-empty");
  const resultsEl = document.getElementById("comparison-results");
  const runBtn = document.getElementById("run-comparison-btn");

  loadingEl.style.display = "flex";
  progressContainer.style.display = "block";
  progressItems.innerHTML = "";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";
  runBtn.disabled = true;

  // Build request payload
  const requestBody = {
    primary_store_id: primaryStoreId,
    comparison_store_id: comparisonStoreId,
    filters: {
      category_ids: selectedCategories.length > 0 ? selectedCategories : null,
      subcategory_ids:
        selectedSubcategories.length > 0 ? selectedSubcategories : null,
      include_discontinued: includeDiscontinued,
    },
  };

  try {
    const response = await fetch(`${API_BASE}/comparison/stores/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // Keep incomplete message in buffer

      for (const line of lines) {
        if (!line.trim()) continue;

        const eventMatch = line.match(/event: (\w+)\ndata: (.+)/s);
        if (!eventMatch) {
          console.log("[COMPARISON] Could not parse SSE line:", line);
          continue;
        }

        const [, eventType, dataStr] = eventMatch;
        console.log("[COMPARISON] Received event type:", eventType);
        const data = JSON.parse(dataStr);

        if (eventType === "progress") {
          console.log("[COMPARISON] Progress event:", data);
          if (data.status === "starting") {
            const item = document.createElement("div");
            item.style.cssText =
              "font-size: 0.875rem; color: var(--accent-primary);";
            item.textContent = `Starting comparison... (${data.total_products} products to check)`;
            progressItems.appendChild(item);
          } else if (data.status === "chunk_progress") {
            // Find or create progress item
            let progressItem = progressItems.querySelector(
              "[data-progress='main']",
            );
            if (!progressItem) {
              progressItem = document.createElement("div");
              progressItem.dataset.progress = "main";
              progressItem.style.cssText =
                "font-size: 0.875rem; color: var(--text-secondary);";
              progressItems.appendChild(progressItem);
            }

            const percentage = Math.round(
              (data.products_checked / data.total_products) * 100,
            );

            let message = `🔍 Chunk ${data.chunk}/${data.total_chunks} (${percentage}%)`;
            message += ` - ${data.products_checked}/${data.total_products} products`;

            if (data.total_missing > 0) {
              message += ` - ${data.total_missing} missing`;
              progressItem.style.color = "orange";
            } else {
              progressItem.style.color = "var(--text-secondary)";
            }

            progressItem.textContent = message;
            progressContainer.scrollTop = progressContainer.scrollHeight;
          }
        } else if (eventType === "complete") {
          console.log("[COMPARISON] Complete event:", data);
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";

          if (data.total_missing === 0) {
            emptyEl.style.display = "block";
          } else {
            comparisonState.results = data;
            displayComparisonResults(data);
          }

          runBtn.disabled = false;
        } else if (eventType === "error") {
          console.log("[COMPARISON] Error event:", data);
          loadingEl.style.display = "none";
          progressContainer.style.display = "none";
          alert(`Error: ${data.message}`);
          runBtn.disabled = false;
        }
      }
    }
  } catch (error) {
    loadingEl.style.display = "none";
    progressContainer.style.display = "none";
    alert(`Error: ${error.message}`);
    runBtn.disabled = false;
  }
}

function displayComparisonResults(data) {
  const resultsEl = document.getElementById("comparison-results");
  const tableBody = document.getElementById("comparison-results-table-body");
  const missingCountEl = document.getElementById("comparison-missing-count");
  const checkedCountEl = document.getElementById("comparison-checked-count");
  const statisticsEl = document.getElementById("comparison-statistics");
  const categoryFilterEl = document.getElementById(
    "comparison-category-filter",
  );

  // Update counts
  missingCountEl.textContent = data.total_missing;
  checkedCountEl.textContent = data.total_checked;

  // Display category statistics
  const categoryStats = data.category_stats || {};
  const sortedCategories = Object.entries(categoryStats).sort(
    (a, b) => b[1] - a[1],
  );

  if (sortedCategories.length > 0) {
    statisticsEl.style.display = "flex";
    statisticsEl.innerHTML = "";

    sortedCategories.forEach(([category, count]) => {
      const badge = document.createElement("span");
      badge.className = "category-badge";
      badge.style.cssText =
        "padding: 0.25rem 0.75rem; background: var(--bg-tertiary); border-radius: var(--radius-sm); font-size: 0.75rem; cursor: pointer; transition: background 0.2s;";
      badge.innerHTML = `<strong style="color: var(--accent-primary);">${category}:</strong> <span style="color: var(--text-secondary);">${count}</span>`;
      badge.addEventListener("click", () => {
        categoryFilterEl.value = category;
        filterComparisonResults(category);
      });
      badge.addEventListener("mouseenter", () => {
        badge.style.background = "var(--bg-secondary)";
      });
      badge.addEventListener("mouseleave", () => {
        badge.style.background = "var(--bg-tertiary)";
      });
      statisticsEl.appendChild(badge);
    });
  }

  // Populate category filter dropdown
  categoryFilterEl.innerHTML = '<option value="">All Categories</option>';
  sortedCategories.forEach(([category, count]) => {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = `${category} (${count})`;
    categoryFilterEl.appendChild(option);
  });

  // Display results table
  tableBody.innerHTML = "";
  data.missing_products.forEach((product, index) => {
    const row = document.createElement("tr");
    row.dataset.category = product.category_name;

    const statusText = product.discontinued ? "Discontinued" : "Active";
    const statusColor = product.discontinued
      ? "var(--warning)"
      : "var(--success)";

    row.innerHTML = `
      <td style="color: var(--text-tertiary);">${index + 1}</td>
      <td>${product.product_id}</td>
      <td><code>${product.product_upc}</code></td>
      <td>${product.product_description}</td>
      <td style="color: var(--accent-primary);">${product.category_name}</td>
      <td style="color: var(--text-secondary);">${product.subcategory_name}</td>
      <td style="color: ${statusColor};">${statusText}</td>
    `;
    tableBody.appendChild(row);
  });

  resultsEl.style.display = "block";
}

function filterComparisonResults(category) {
  const tableBody = document.getElementById("comparison-results-table-body");
  const rows = Array.from(tableBody.getElementsByTagName("tr"));

  rows.forEach((row, index) => {
    if (!category || row.dataset.category === category) {
      row.style.display = "";
      // Renumber visible rows
      const numberCell = row.querySelector("td:first-child");
      const visibleIndex =
        rows
          .slice(0, index)
          .filter((r) => r.style.display !== "none").length + 1;
      numberCell.textContent = visibleIndex;
    } else {
      row.style.display = "none";
    }
  });
}

function exportComparisonToCSV() {
  if (!comparisonState.results) return;

  const data = comparisonState.results;
  const rows = [
    [
      "Product ID",
      "UPC",
      "Description",
      "Category",
      "Subcategory",
      "Status",
    ],
  ];

  data.missing_products.forEach((product) => {
    rows.push([
      product.product_id,
      product.product_upc,
      product.product_description,
      product.category_name,
      product.subcategory_name,
      product.discontinued ? "Discontinued" : "Active",
    ]);
  });

  const csvContent = rows.map((row) => row.join(",")).join("\n");
  const blob = new Blob([csvContent], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `store-comparison-${data.primary_store_name}-vs-${data.comparison_store_name}-${new Date().toISOString().split("T")[0]}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// Event Listeners for Store Comparison
document
  .getElementById("comparison-primary-store")
  ?.addEventListener("change", async (e) => {
    const storeId = parseInt(e.target.value);
    comparisonState.primaryStoreId = storeId;

    if (storeId) {
      await loadCategoriesForStore(storeId);
    }

    // Enable run button if both stores selected
    const comparisonStoreId = parseInt(
      document.getElementById("comparison-comparison-store").value,
    );
    document.getElementById("run-comparison-btn").disabled = !(
      storeId && comparisonStoreId
    );
  });

document
  .getElementById("comparison-comparison-store")
  ?.addEventListener("change", (e) => {
    const storeId = parseInt(e.target.value);
    comparisonState.comparisonStoreId = storeId;

    // Enable run button if both stores selected
    const primaryStoreId = parseInt(
      document.getElementById("comparison-primary-store").value,
    );
    document.getElementById("run-comparison-btn").disabled = !(
      primaryStoreId && storeId
    );
  });

document
  .getElementById("comparison-categories")
  ?.addEventListener("change", async (e) => {
    const selectedOptions = Array.from(e.target.selectedOptions);
    const categoryIds = selectedOptions.map((opt) => parseInt(opt.value));

    if (categoryIds.length > 0 && comparisonState.primaryStoreId) {
      await loadSubcategoriesForStore(
        comparisonState.primaryStoreId,
        categoryIds,
      );
    } else {
      const subcategoriesSelect = document.getElementById(
        "comparison-subcategories",
      );
      subcategoriesSelect.innerHTML =
        '<option value="">Select categories first...</option>';
      subcategoriesSelect.disabled = true;
    }
  });

document
  .getElementById("run-comparison-btn")
  ?.addEventListener("click", runStoreComparison);

document
  .getElementById("comparison-category-filter")
  ?.addEventListener("change", (e) => {
    filterComparisonResults(e.target.value);
  });

document
  .getElementById("export-comparison-btn")
  ?.addEventListener("click", exportComparisonToCSV);

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  // Load dashboard by default
  loadDashboard();

  // Load saved theme
  const savedTheme = localStorage.getItem("selectedTheme") || "current";
  setTheme(savedTheme);
});
