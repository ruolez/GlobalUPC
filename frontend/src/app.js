const API_BASE = "/api";

// Global state for search results
let currentSearchResults = {
  upc: "",
  matches: [],
  total_found: 0,
};

// Flag to prevent multiple simultaneous searches
let isSearching = false;

// Track current audit store ID for exclusion feature
let currentAuditStoreId = null;

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
  exitPriceFullscreen();

  // Stop dashboard auto-refresh whenever leaving the dashboard
  if (typeof stopDashboardAutoRefresh === "function" && page !== "dashboard") {
    stopDashboardAutoRefresh();
  }

  if (window.location.search) {
    window.history.replaceState({}, "", window.location.pathname);
  }

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

  // Autofocus on UPC search input when navigating to update-upc page
  if (page === "update-upc") {
    setTimeout(() => {
      const searchInput = document.getElementById("upc-search-input");
      if (searchInput) searchInput.focus();
    }, 100);
  }

  // Load page data
  if (page === "dashboard") {
    loadDashboard();
    startDashboardAutoRefresh();
  } else if (page === "settings") {
    loadSettings();
  } else if (page === "history") {
    loadHistoryPage();
  } else if (page === "sql-audit") {
    loadSQLAuditPage();
  } else if (page === "item-tracker") {
    loadItemTrackerPage();
  } else if (page === "price-updates") {
    loadPriceUpdatesPage();
  } else if (page === "sales") {
    loadSalesPage();
  } else if (page === "shopify-sales") {
    loadShopifySalesPage();
  } else if (page === "shopify-analytics") {
    loadShopifyAnalyticsPage();
  } else if (page === "quotations-in-progress") {
    loadQuotationsInProgressPage();
  } else if (page === "inventory-time") {
    loadInventoryTimePage();
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

// Toast notification function
function showToast(message, type = "info") {
  // Create toast container if it doesn't exist
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.style.position = "fixed";
    container.style.top = "1rem";
    container.style.right = "1rem";
    container.style.zIndex = "10000";
    container.style.display = "flex";
    container.style.flexDirection = "column";
    container.style.gap = "0.5rem";
    document.body.appendChild(container);
  }

  // Create toast element
  const toast = document.createElement("div");
  toast.style.padding = "0.75rem 1rem";
  toast.style.borderRadius = "var(--radius-md)";
  toast.style.boxShadow = "0 4px 12px rgba(0, 0, 0, 0.4)";
  toast.style.minWidth = "300px";
  toast.style.maxWidth = "500px";
  toast.style.fontSize = "0.875rem";
  toast.style.fontWeight = "500";
  toast.style.animation = "slideIn 0.3s ease-out";
  toast.style.transition = "opacity 0.3s";

  // Set color based on type
  if (type === "success") {
    toast.style.background = "rgba(16, 185, 129, 0.15)";
    toast.style.color = "var(--success)";
    toast.style.border = "1px solid rgba(16, 185, 129, 0.3)";
  } else if (type === "error") {
    toast.style.background = "rgba(239, 68, 68, 0.15)";
    toast.style.color = "var(--error)";
    toast.style.border = "1px solid rgba(239, 68, 68, 0.3)";
  } else if (type === "warning") {
    toast.style.background = "rgba(245, 158, 11, 0.15)";
    toast.style.color = "var(--warning, #f59e0b)";
    toast.style.border = "1px solid rgba(245, 158, 11, 0.3)";
  } else {
    toast.style.background = "var(--bg-secondary)";
    toast.style.color = "var(--text-primary)";
    toast.style.border = "1px solid var(--border-color)";
  }

  toast.textContent = message;
  container.appendChild(toast);

  // Auto-remove after 3 seconds
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => {
      container.removeChild(toast);
      // Remove container if empty
      if (container.children.length === 0) {
        document.body.removeChild(container);
      }
    }, 300);
  }, 3000);
}

// ===== Dashboard =====

const DASHBOARD_AUTOREFRESH_MS = 60000;
const dashboardState = {
  refreshTimer: null,
  refreshing: false,
  bound: false,
};

async function loadDashboard() {
  bindDashboardOnce();
  setDashboardRefreshSpinner(true);
  try {
    await loadDashboardStats();
    setDashboardUpdatedNow();
  } catch (e) {
    console.error("Dashboard load failed", e);
    showToast(e.message || "Dashboard failed to load", "error");
  } finally {
    setDashboardRefreshSpinner(false);
  }
}

function bindDashboardOnce() {
  if (dashboardState.bound) return;
  dashboardState.bound = true;
  const refreshBtn = document.getElementById("dashboard-refresh-btn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      if (dashboardState.refreshing) return;
      loadDashboard();
    });
  }
  // Pause auto-refresh while tab is hidden
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopDashboardAutoRefresh();
    } else if (isDashboardVisible()) {
      startDashboardAutoRefresh();
    }
  });
}

function isDashboardVisible() {
  const el = document.getElementById("dashboard-page");
  return el && el.style.display !== "none";
}

function startDashboardAutoRefresh() {
  stopDashboardAutoRefresh();
  dashboardState.refreshTimer = setInterval(() => {
    if (document.hidden || !isDashboardVisible()) return;
    loadDashboard();
  }, DASHBOARD_AUTOREFRESH_MS);
}

function stopDashboardAutoRefresh() {
  if (dashboardState.refreshTimer) {
    clearInterval(dashboardState.refreshTimer);
    dashboardState.refreshTimer = null;
  }
}

function setDashboardRefreshSpinner(active) {
  dashboardState.refreshing = active;
  const btn = document.getElementById("dashboard-refresh-btn");
  if (!btn) return;
  btn.classList.toggle("is-spinning", active);
  btn.disabled = active;
}

function setDashboardUpdatedNow() {
  const el = document.getElementById("dashboard-updated");
  if (!el) return;
  const t = new Date();
  const h = t.getHours();
  const m = t.getMinutes();
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = ((h + 11) % 12) + 1;
  el.textContent = `Updated ${h12}:${String(m).padStart(2, "0")} ${ampm}`;
}

async function loadDashboardStats() {
  let stats;
  try {
    stats = await apiRequest("/dashboard/stats");
  } catch (e) {
    renderDashboardStatsError();
    throw e;
  }
  renderDashboardKpi(stats);
}

function renderDashboardStatsError() {
  ["kpi-stores", "kpi-in-progress", "kpi-upc-7d", "kpi-price-7d"].forEach((id) => {
    const v = document.getElementById(`${id}-value`);
    const m = document.getElementById(`${id}-meta`);
    if (v) v.textContent = "—";
    if (m) m.textContent = "Failed to load";
  });
}

function renderDashboardKpi(stats) {
  // Stores tile
  const stores = stats.stores || {};
  setText("kpi-stores-value", `${stores.active ?? 0} / ${stores.total ?? 0}`);
  const typeBits = [];
  const types = stores.by_type || {};
  if (types.mssql) typeBits.push(`${types.mssql} MSSQL`);
  if (types.shopify) typeBits.push(`${types.shopify} Shopify`);
  setText(
    "kpi-stores-meta",
    typeBits.length ? typeBits.join(" · ") : "no stores configured",
  );

  // In Progress tile
  const ip = stats.in_progress || {};
  const ipTile = document.getElementById("kpi-in-progress");
  if (!ip.configured) {
    setText("kpi-in-progress-value", "—");
    setText(
      "kpi-in-progress-meta",
      "Admin store not configured",
    );
    if (ipTile) {
      ipTile.classList.add("is-warning");
      ipTile.dataset.page = "settings";
    }
  } else if (ip.error) {
    setText("kpi-in-progress-value", "—");
    setText("kpi-in-progress-meta", "Admin DB unreachable");
    if (ipTile) {
      ipTile.classList.add("is-warning");
      ipTile.dataset.page = "quotations-in-progress";
    }
  } else {
    setText("kpi-in-progress-value", String(ip.total ?? 0));
    setText(
      "kpi-in-progress-meta",
      ip.oldest_started_at
        ? `oldest: ${formatRelative(ip.oldest_started_at)}`
        : "no open quotations",
    );
    if (ipTile) {
      ipTile.classList.remove("is-warning");
      ipTile.dataset.page = "quotations-in-progress";
    }
  }

  // UPC Updates · 7d
  const upc = stats.upc_updates_7d || {};
  setText("kpi-upc-7d-value", String(upc.batches ?? 0));
  setText(
    "kpi-upc-7d-meta",
    upc.batches > 0 && upc.success_rate != null
      ? `${formatPct(upc.success_rate)} success`
      : "no batches",
  );

  // Price Updates · 7d
  const price = stats.price_updates_7d || {};
  setText("kpi-price-7d-value", String(price.batches ?? 0));
  setText(
    "kpi-price-7d-meta",
    price.batches > 0 && price.success_rate != null
      ? `${formatPct(price.success_rate)} success`
      : "no batches",
  );
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function formatPct(v) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

function formatRelative(iso) {
  if (!iso) return "";
  const t = new Date(iso);
  const now = new Date();
  const diffMs = now - t;
  if (isNaN(diffMs)) return "";
  const sec = Math.max(0, Math.floor(diffMs / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.floor(hr / 24);
  if (days < 30) return `${days}d ago`;
  const mon = Math.floor(days / 30);
  if (mon < 12) return `${mon}mo ago`;
  return `${Math.floor(mon / 12)}y ago`;
}

// Settings Functions
async function loadSettings() {
  await loadStores();
  await loadExclusions();
  await loadStoreMirrors();
  await loadItemTrackerExclusions();
  await loadShopifySalesSettings();
  await loadAdminStoreSetting();
  await loadInventoryTimeSettings();

  // Set dropdown value to saved preference
  const savedLandingPage = getDefaultLandingPage();
  const dropdown = document.getElementById("default-landing-page");
  if (dropdown) {
    dropdown.value = savedLandingPage;
  }
}

// ===== Settings sub-navigation =====

const SETTINGS_TAB_KEY = "settingsActiveTab";
const settingsCounts = { stores: 0, exclusionsUpc: 0, exclusionsIt: 0 };

function setSettingsBadge(elId, count) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (count > 0) {
    el.textContent = String(count);
    el.classList.add("has-value");
  } else {
    el.textContent = "";
    el.classList.remove("has-value");
  }
}

function refreshExclusionsCombinedBadge() {
  const total = settingsCounts.exclusionsUpc + settingsCounts.exclusionsIt;
  setSettingsBadge("settings-badge-exclusions", total);
}

function activateSettingsTab(tabId) {
  if (!tabId) return;
  const items = document.querySelectorAll(".settings-subnav-item");
  if (items.length === 0) return;
  const valid = Array.from(items).some(
    (b) => b.dataset.settingsTab === tabId,
  );
  const target = valid ? tabId : "stores";
  items.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.settingsTab === target);
  });
  document.querySelectorAll(".settings-panel").forEach((panel) => {
    panel.style.display =
      panel.dataset.settingsPanel === target ? "" : "none";
  });
  try {
    localStorage.setItem(SETTINGS_TAB_KEY, target);
  } catch (e) {
    /* ignore quota / private mode errors */
  }
}

function activateExclusionTab(tabId) {
  const buttons = document.querySelectorAll(".tab-pill[data-exclusion-tab]");
  if (buttons.length === 0) return;
  buttons.forEach((b) =>
    b.classList.toggle("active", b.dataset.exclusionTab === tabId),
  );
  document
    .querySelectorAll(".tab-pill-panel[data-exclusion-panel]")
    .forEach((p) => {
      p.style.display = p.dataset.exclusionPanel === tabId ? "" : "none";
    });
}

function bindStoresSearch() {
  const input = document.getElementById("stores-search");
  if (!input || input.dataset.bound === "1") return;
  input.dataset.bound = "1";

  const applyFilter = () => {
    const q = input.value.trim().toLowerCase();
    const cards = document.querySelectorAll("#stores-list .store-card");
    let visible = 0;
    cards.forEach((card) => {
      const text = card.textContent.toLowerCase();
      const match = q === "" || text.includes(q);
      card.style.display = match ? "" : "none";
      if (match) visible += 1;
    });
    const emptyMsg = document.getElementById("stores-empty-search");
    if (emptyMsg) {
      emptyMsg.style.display =
        q !== "" && visible === 0 && cards.length > 0 ? "block" : "none";
    }
  };

  input.addEventListener("input", applyFilter);
}

function initSettingsTabs() {
  const subnav = document.querySelector(".settings-subnav");
  if (subnav && subnav.dataset.bound !== "1") {
    subnav.dataset.bound = "1";
    subnav.addEventListener("click", (e) => {
      const btn = e.target.closest(".settings-subnav-item");
      if (!btn) return;
      activateSettingsTab(btn.dataset.settingsTab);
    });
  }

  const pills = document.querySelector(".tab-pills");
  if (pills && pills.dataset.bound !== "1") {
    pills.dataset.bound = "1";
    pills.addEventListener("click", (e) => {
      const btn = e.target.closest(".tab-pill[data-exclusion-tab]");
      if (!btn) return;
      activateExclusionTab(btn.dataset.exclusionTab);
    });
  }

  bindStoresSearch();

  let initial = "stores";
  try {
    const saved = localStorage.getItem(SETTINGS_TAB_KEY);
    if (saved) initial = saved;
  } catch (e) {
    /* ignore */
  }
  activateSettingsTab(initial);
}

// Store Mirrors Functions
async function loadStoreMirrors() {
  const loadingEl = document.getElementById("mirrors-loading");
  const emptyEl = document.getElementById("mirrors-empty");
  const resultsEl = document.getElementById("mirrors-results");
  const tableBody = document.getElementById("mirrors-table-body");
  const countEl = document.getElementById("mirrors-count");
  const sourceSelect = document.getElementById("mirror-source-store");
  const mirrorSelect = document.getElementById("mirror-mirror-store");

  if (!loadingEl) return;

  loadingEl.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";

  try {
    const [mirrorsData, stores] = await Promise.all([
      apiRequest("/store-mirrors"),
      apiRequest("/stores"),
    ]);

    const activeStores = stores.filter((s) => s.is_active);
    const existingMirrors = mirrorsData.mirrors || [];

    const mirrorStoreIds = new Set(existingMirrors.map((m) => m.mirror_store_id));
    const sourceStoreIds = new Set(existingMirrors.map((m) => m.source_store_id));

    sourceSelect.innerHTML = '<option value="">Select source...</option>';
    mirrorSelect.innerHTML = '<option value="">Select mirror...</option>';

    activeStores.forEach((store) => {
      if (!mirrorStoreIds.has(store.id)) {
        const opt = document.createElement("option");
        opt.value = store.id;
        opt.textContent = `${store.name} (${store.store_type === "mssql" ? "BACKOFFICE" : "SHOPIFY"})`;
        sourceSelect.appendChild(opt);
      }
    });

    activeStores.forEach((store) => {
      if (!sourceStoreIds.has(store.id)) {
        const opt = document.createElement("option");
        opt.value = store.id;
        opt.textContent = `${store.name} (${store.store_type === "mssql" ? "BACKOFFICE" : "SHOPIFY"})`;
        mirrorSelect.appendChild(opt);
      }
    });

    loadingEl.style.display = "none";

    if (existingMirrors.length === 0) {
      emptyEl.style.display = "block";
      return;
    }

    resultsEl.style.display = "block";
    countEl.textContent = existingMirrors.length;

    tableBody.innerHTML = "";
    existingMirrors.forEach((mirror) => {
      const row = document.createElement("tr");

      const sourceTd = document.createElement("td");
      sourceTd.style.fontWeight = "500";
      sourceTd.textContent = `${mirror.source_store_name} (${mirror.source_store_type === "mssql" ? "BACKOFFICE" : "SHOPIFY"})`;
      row.appendChild(sourceTd);

      const arrowTd = document.createElement("td");
      arrowTd.style.textAlign = "center";
      arrowTd.style.color = "var(--text-tertiary)";
      arrowTd.style.fontSize = "1.25rem";
      arrowTd.innerHTML = "&rarr;";
      row.appendChild(arrowTd);

      const mirrorTd = document.createElement("td");
      mirrorTd.style.fontWeight = "500";
      mirrorTd.textContent = `${mirror.mirror_store_name} (${mirror.mirror_store_type === "mssql" ? "BACKOFFICE" : "SHOPIFY"})`;
      row.appendChild(mirrorTd);

      const dateTd = document.createElement("td");
      const date = new Date(mirror.created_at);
      dateTd.textContent = date.toLocaleDateString() + " " + date.toLocaleTimeString();
      dateTd.style.color = "var(--text-secondary)";
      dateTd.style.fontSize = "0.875rem";
      row.appendChild(dateTd);

      const actionsTd = document.createElement("td");
      actionsTd.style.textAlign = "center";
      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn-icon";
      deleteBtn.title = "Remove mirror";
      deleteBtn.innerHTML = "\u{1F5D1}\u{FE0F}";
      deleteBtn.style.cursor = "pointer";
      deleteBtn.style.fontSize = "1rem";
      deleteBtn.style.padding = "0.25rem 0.5rem";
      deleteBtn.style.background = "transparent";
      deleteBtn.style.border = "1px solid var(--border-color)";
      deleteBtn.style.borderRadius = "var(--radius-sm)";
      deleteBtn.style.transition = "all 0.2s";
      deleteBtn.onclick = async () => {
        if (!confirm(`Remove mirror: ${mirror.source_store_name} \u2192 ${mirror.mirror_store_name}?`)) return;
        try {
          await apiRequest(`/store-mirrors/${mirror.id}`, { method: "DELETE" });
          row.style.transition = "opacity 0.3s";
          row.style.opacity = "0";
          setTimeout(() => {
            row.remove();
            const remaining = tableBody.querySelectorAll("tr").length;
            countEl.textContent = remaining;
            if (remaining === 0) {
              resultsEl.style.display = "none";
              emptyEl.style.display = "block";
            }
            loadStoreMirrors();
          }, 300);
          showToast("\u2713 Mirror removed", "success");
        } catch (error) {
          showToast(`\u2717 Failed to remove mirror: ${error.message}`, "error");
        }
      };
      deleteBtn.onmouseover = () => {
        deleteBtn.style.background = "var(--error)";
        deleteBtn.style.borderColor = "var(--error)";
        deleteBtn.style.color = "#fff";
      };
      deleteBtn.onmouseout = () => {
        deleteBtn.style.background = "transparent";
        deleteBtn.style.borderColor = "var(--border-color)";
        deleteBtn.style.color = "inherit";
      };
      actionsTd.appendChild(deleteBtn);
      row.appendChild(actionsTd);

      tableBody.appendChild(row);
    });
  } catch (error) {
    console.error("Error loading store mirrors:", error);
    loadingEl.style.display = "none";
    emptyEl.style.display = "block";
    showToast(`\u2717 Failed to load mirrors: ${error.message}`, "error");
  }
}

async function addStoreMirror() {
  const sourceId = document.getElementById("mirror-source-store").value;
  const mirrorId = document.getElementById("mirror-mirror-store").value;

  if (!sourceId || !mirrorId) {
    showToast("Please select both a source and mirror store", "error");
    return;
  }

  if (sourceId === mirrorId) {
    showToast("Source and mirror store cannot be the same", "error");
    return;
  }

  try {
    await apiRequest("/store-mirrors", {
      method: "POST",
      body: JSON.stringify({
        source_store_id: parseInt(sourceId),
        mirror_store_id: parseInt(mirrorId),
      }),
    });
    showToast("\u2713 Mirror added successfully", "success");
    await loadStoreMirrors();
  } catch (error) {
    showToast(`\u2717 Failed to add mirror: ${error.message}`, "error");
  }
}

// UPC Exclusions Functions
async function loadExclusions(storeId = null) {
  const loadingEl = document.getElementById("exclusions-loading");
  const emptyEl = document.getElementById("exclusions-empty");
  const resultsEl = document.getElementById("exclusions-results");
  const tableBody = document.getElementById("exclusions-table-body");
  const countEl = document.getElementById("exclusions-count");
  const storeFilter = document.getElementById("exclusions-store-filter");

  // Show loading state
  loadingEl.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";

  try {
    // Populate store filter dropdown if not already done
    if (storeFilter && storeFilter.options.length === 1) {
      const stores = await apiRequest("/stores");
      const mssqlStores = stores.filter((s) => s.store_type === "mssql");
      mssqlStores.forEach((store) => {
        const option = document.createElement("option");
        option.value = store.id;
        option.textContent = store.name;
        storeFilter.appendChild(option);
      });
    }

    // Fetch exclusions
    const endpoint = storeId
      ? `/exclusions?store_id=${storeId}`
      : "/exclusions";
    const data = await apiRequest(endpoint);

    loadingEl.style.display = "none";

    settingsCounts.exclusionsUpc = data.total || 0;
    setSettingsBadge("badge-exclusion-upc", data.total || 0);
    refreshExclusionsCombinedBadge();

    if (data.total === 0) {
      emptyEl.style.display = "block";
      return;
    }

    // Show results
    resultsEl.style.display = "block";
    countEl.textContent = data.total;

    // Clear and populate table
    tableBody.innerHTML = "";
    data.exclusions.forEach((exclusion) => {
      const row = document.createElement("tr");

      // Store Name
      const storeTd = document.createElement("td");
      storeTd.textContent = exclusion.store_name;
      storeTd.style.fontWeight = "500";
      row.appendChild(storeTd);

      // UPC
      const upcTd = document.createElement("td");
      upcTd.textContent = exclusion.upc;
      upcTd.style.fontFamily = "monospace";
      upcTd.style.fontWeight = "bold";
      upcTd.style.color = "var(--accent-primary)";
      row.appendChild(upcTd);

      // Excluded Date
      const dateTd = document.createElement("td");
      const date = new Date(exclusion.excluded_at);
      dateTd.textContent =
        date.toLocaleDateString() + " " + date.toLocaleTimeString();
      dateTd.style.color = "var(--text-secondary)";
      dateTd.style.fontSize = "0.875rem";
      row.appendChild(dateTd);

      // Notes
      const notesTd = document.createElement("td");
      notesTd.textContent = exclusion.notes || "—";
      notesTd.style.color = exclusion.notes
        ? "inherit"
        : "var(--text-tertiary)";
      notesTd.style.fontSize = "0.875rem";
      row.appendChild(notesTd);

      // Actions
      const actionsTd = document.createElement("td");
      actionsTd.style.textAlign = "center";
      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn-icon";
      deleteBtn.title = "Remove exclusion";
      deleteBtn.innerHTML = "🗑️";
      deleteBtn.style.cursor = "pointer";
      deleteBtn.style.fontSize = "1rem";
      deleteBtn.style.padding = "0.25rem 0.5rem";
      deleteBtn.style.background = "transparent";
      deleteBtn.style.border = "1px solid var(--border-color)";
      deleteBtn.style.borderRadius = "var(--radius-sm)";
      deleteBtn.style.transition = "all 0.2s";
      deleteBtn.onclick = async () => {
        if (
          !confirm(
            `Remove exclusion for UPC ${exclusion.upc}?\n\nThis UPC will appear in future audit results for ${exclusion.store_name}.`,
          )
        ) {
          return;
        }

        try {
          await apiRequest(`/exclusions/${exclusion.id}`, { method: "DELETE" });

          // Fade out and remove row
          row.style.transition = "opacity 0.3s";
          row.style.opacity = "0";
          setTimeout(() => {
            row.remove();
            // Update count
            const remainingRows = tableBody.querySelectorAll("tr").length;
            countEl.textContent = remainingRows;

            // Show empty state if no more exclusions
            if (remainingRows === 0) {
              resultsEl.style.display = "none";
              emptyEl.style.display = "block";
            }
          }, 300);

          showToast(`✓ Exclusion removed successfully`, "success");
        } catch (error) {
          console.error("Error deleting exclusion:", error);
          showToast(`✗ Failed to delete exclusion: ${error.message}`, "error");
        }
      };
      deleteBtn.onmouseover = () => {
        deleteBtn.style.background = "var(--error)";
        deleteBtn.style.borderColor = "var(--error)";
        deleteBtn.style.color = "#fff";
      };
      deleteBtn.onmouseout = () => {
        deleteBtn.style.background = "transparent";
        deleteBtn.style.borderColor = "var(--border-color)";
        deleteBtn.style.color = "inherit";
      };
      actionsTd.appendChild(deleteBtn);
      row.appendChild(actionsTd);

      tableBody.appendChild(row);
    });
  } catch (error) {
    console.error("Error loading exclusions:", error);
    loadingEl.style.display = "none";
    emptyEl.style.display = "block";
    showToast(`✗ Failed to load exclusions: ${error.message}`, "error");
  }
}

// Item Tracker Exclusions Functions
async function loadItemTrackerExclusions() {
  const loadingEl = document.getElementById("item-tracker-exclusions-loading");
  const emptyEl = document.getElementById("item-tracker-exclusions-empty");
  const resultsEl = document.getElementById("item-tracker-exclusions-results");
  const tableBody = document.getElementById(
    "item-tracker-exclusions-table-body",
  );
  const countEl = document.getElementById("item-tracker-exclusions-count");

  // Show loading state
  loadingEl.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";

  try {
    const data = await apiRequest("/item-tracker/exclusions");

    loadingEl.style.display = "none";

    settingsCounts.exclusionsIt = data.total || 0;
    setSettingsBadge("badge-exclusion-it", data.total || 0);
    refreshExclusionsCombinedBadge();

    if (data.total === 0) {
      emptyEl.style.display = "block";
      return;
    }

    // Show results
    resultsEl.style.display = "block";
    countEl.textContent = data.total;

    // Clear and populate table
    tableBody.innerHTML = "";
    data.exclusions.forEach((exclusion) => {
      const row = document.createElement("tr");

      // Business Name
      const nameTd = document.createElement("td");
      nameTd.textContent = exclusion.business_name;
      nameTd.style.fontWeight = "500";
      row.appendChild(nameTd);

      // Scope
      const scopeTd = document.createElement("td");
      let scopeText = "All";
      let scopeStyle = "color: var(--text-secondary);";
      if (exclusion.void_status === 0) {
        scopeText = "Non-voided only";
        scopeStyle = "color: var(--success);";
      } else if (exclusion.void_status === 1) {
        scopeText = "Voided only";
        scopeStyle = "color: var(--warning);";
      }
      scopeTd.textContent = scopeText;
      scopeTd.style.cssText = scopeStyle + " font-size: 0.8125rem;";
      row.appendChild(scopeTd);

      // Excluded Date
      const dateTd = document.createElement("td");
      const date = new Date(exclusion.excluded_at);
      dateTd.textContent =
        date.toLocaleDateString() + " " + date.toLocaleTimeString();
      dateTd.style.color = "var(--text-secondary)";
      dateTd.style.fontSize = "0.875rem";
      row.appendChild(dateTd);

      // Notes
      const notesTd = document.createElement("td");
      notesTd.textContent = exclusion.notes || "—";
      notesTd.style.color = exclusion.notes
        ? "inherit"
        : "var(--text-tertiary)";
      notesTd.style.fontSize = "0.875rem";
      row.appendChild(notesTd);

      // Actions
      const actionsTd = document.createElement("td");
      actionsTd.style.textAlign = "center";
      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn-icon";
      deleteBtn.title = "Restore (remove exclusion)";
      deleteBtn.innerHTML = "🗑️";
      deleteBtn.style.cursor = "pointer";
      deleteBtn.style.fontSize = "1rem";
      deleteBtn.style.padding = "0.25rem 0.5rem";
      deleteBtn.style.background = "transparent";
      deleteBtn.style.border = "1px solid var(--border-color)";
      deleteBtn.style.borderRadius = "var(--radius-sm)";
      deleteBtn.style.transition = "all 0.2s";
      deleteBtn.onclick = async () => {
        if (
          !confirm(
            `Restore "${exclusion.business_name}"?\n\nThis customer/supplier will appear in future Item Tracker searches.`,
          )
        ) {
          return;
        }

        try {
          await apiRequest(`/item-tracker/exclusions/${exclusion.id}`, {
            method: "DELETE",
          });

          // Fade out and remove row
          row.style.transition = "opacity 0.3s";
          row.style.opacity = "0";
          setTimeout(() => {
            row.remove();
            // Update count
            const remainingRows = tableBody.querySelectorAll("tr").length;
            countEl.textContent = remainingRows;

            // Show empty state if no more exclusions
            if (remainingRows === 0) {
              resultsEl.style.display = "none";
              emptyEl.style.display = "block";
            }
          }, 300);

          showToast(`✓ Exclusion removed successfully`, "success");
        } catch (error) {
          console.error("Error deleting exclusion:", error);
          showToast(`✗ Failed to delete exclusion: ${error.message}`, "error");
        }
      };
      deleteBtn.onmouseover = () => {
        deleteBtn.style.background = "var(--error)";
        deleteBtn.style.borderColor = "var(--error)";
        deleteBtn.style.color = "#fff";
      };
      deleteBtn.onmouseout = () => {
        deleteBtn.style.background = "transparent";
        deleteBtn.style.borderColor = "var(--border-color)";
        deleteBtn.style.color = "inherit";
      };
      actionsTd.appendChild(deleteBtn);
      row.appendChild(actionsTd);

      tableBody.appendChild(row);
    });
  } catch (error) {
    console.error("Error loading Item Tracker exclusions:", error);
    loadingEl.style.display = "none";
    emptyEl.style.display = "block";
    showToast(
      `✗ Failed to load Item Tracker exclusions: ${error.message}`,
      "error",
    );
  }
}

// Shopify Sales Settings Functions
async function loadShopifySalesSettings() {
  const input = document.getElementById("shopify-sales-sku-prefixes");
  if (!input) return;

  try {
    const resp = await fetch(`${API_BASE}/settings/shopify_sales_sku_exclude_prefixes`);
    if (resp.ok) {
      const data = await resp.json();
      input.value = data.value || "";
    }
  } catch {
    input.value = "";
  }

  const s2sSelect = document.getElementById("shopify-sales-s2s-store");
  if (!s2sSelect) return;

  try {
    const stores = await apiRequest("/stores");
    const mssqlStores = stores.filter(
      (s) => s.store_type === "mssql" && s.is_active,
    );
    s2sSelect.innerHTML = '<option value="">— None —</option>';
    mssqlStores.forEach((store) => {
      const opt = document.createElement("option");
      opt.value = store.id;
      opt.textContent = store.name;
      s2sSelect.appendChild(opt);
    });

    const s2sResp = await fetch(`${API_BASE}/settings/shopify_sales_s2s_store_id`);
    if (s2sResp.ok) {
      const setting = await s2sResp.json();
      if (setting.value) s2sSelect.value = setting.value;
    }
  } catch {}
}

async function saveShopifySalesSkuPrefixes() {
  const input = document.getElementById("shopify-sales-sku-prefixes");
  const value = input.value.trim();

  try {
    const patchResp = await fetch(`${API_BASE}/settings/shopify_sales_sku_exclude_prefixes`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
    if (!patchResp.ok) {
      await apiRequest("/settings", {
        method: "POST",
        body: JSON.stringify({
          key: "shopify_sales_sku_exclude_prefixes",
          value,
          description: "Comma-separated SKU prefixes to exclude from Shopify Sales reports",
        }),
      });
    }
    showToast("✓ SKU exclusion prefixes saved", "success");
  } catch (error) {
    showToast(`✗ Failed to save: ${error.message}`, "error");
  }
}

document
  .getElementById("shopify-sales-sku-prefixes-save")
  ?.addEventListener("click", saveShopifySalesSkuPrefixes);

async function saveShopifySalesS2sStore() {
  const select = document.getElementById("shopify-sales-s2s-store");
  const value = select.value;

  try {
    const patchResp = await fetch(`${API_BASE}/settings/shopify_sales_s2s_store_id`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
    if (!patchResp.ok) {
      await apiRequest("/settings", {
        method: "POST",
        body: JSON.stringify({
          key: "shopify_sales_s2s_store_id",
          value,
          description: "MSSQL store ID for Shopify Sales cost lookup (UnitPriceC)",
        }),
      });
    }
    showToast("✓ Cost lookup store saved", "success");
  } catch (error) {
    showToast(`✗ Failed to save: ${error.message}`, "error");
  }
}

document
  .getElementById("shopify-sales-s2s-store-save")
  ?.addEventListener("click", saveShopifySalesS2sStore);

async function excludeBusinessName(businessName, voidStatus) {
  if (
    !confirm(
      `Exclude "${businessName}" from all Item Tracker results?\n\nThis customer/supplier will no longer appear in search results.`,
    )
  ) {
    return;
  }

  try {
    await apiRequest("/item-tracker/exclusions", {
      method: "POST",
      body: JSON.stringify({
        business_name: businessName,
        void_status: voidStatus,
      }),
    });

    showToast(`✓ "${businessName}" excluded successfully`, "success");

    // Re-run search to refresh results
    if (
      document.getElementById("item-tracker-upc-input") &&
      document.getElementById("item-tracker-upc-input").value.trim()
    ) {
      searchItemTracker();
    }
  } catch (error) {
    console.error("Error excluding business name:", error);
    if (error.message && error.message.includes("already excluded")) {
      showToast(`Already excluded: ${businessName}`, "warning");
    } else {
      showToast(`✗ Failed to exclude: ${error.message}`, "error");
    }
  }
}

async function loadStores() {
  const stores = await apiRequest("/stores");
  const storesList = document.getElementById("stores-list");

  settingsCounts.stores = stores.length;
  setSettingsBadge("settings-badge-stores", stores.length);
  const subtitle = document.getElementById("stores-subtitle");
  if (subtitle) {
    if (stores.length === 0) {
      subtitle.textContent = "MSSQL databases and Shopify storefronts";
    } else {
      const active = stores.filter((s) => s.is_active).length;
      subtitle.textContent = `${stores.length} configured · ${active} active`;
    }
  }

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

  storesList.innerHTML = stores
    .map((store, index) => createStoreCard(store, index + 1))
    .join("");

  // Re-apply any active search filter after re-render
  const searchInput = document.getElementById("stores-search");
  if (searchInput && searchInput.value) {
    searchInput.dispatchEvent(new Event("input"));
  }

  // Attach event listeners
  stores.forEach((store) => {
    // Collapse/expand functionality
    const storeCard = document.querySelector(
      `.store-card[data-store-id="${store.id}"]`,
    );
    const header = storeCard?.querySelector(".store-card-header");
    header?.addEventListener("click", (e) => {
      // Don't toggle if clicking on action buttons
      if (e.target.closest(".store-actions")) return;
      storeCard.classList.toggle("collapsed");
      storeCard.classList.toggle("expanded");
    });

    // Toggle/delete/edit-name button listeners
    document
      .getElementById(`category-${store.id}`)
      ?.addEventListener("click", () => toggleStoreCategory(store.id, store.store_category));
    document
      .getElementById(`toggle-${store.id}`)
      ?.addEventListener("click", () => toggleStore(store.id));
    document
      .getElementById(`edit-conn-${store.id}`)
      ?.addEventListener("click", () => openEditStoreModal(store));
    document
      .getElementById(`delete-${store.id}`)
      ?.addEventListener("click", () => deleteStore(store.id));
    document
      .getElementById(`edit-name-${store.id}`)
      ?.addEventListener("click", (e) => {
        e.stopPropagation();
        startRenameStore(store.id, store.name);
      });
  });
}

function createStoreCard(store, index) {
  const connection = store.mssql_connection || store.shopify_connection;
  const isMssql = store.store_type === "mssql";

  return `
        <div class="store-card collapsed" data-store-id="${store.id}">
            <div class="store-card-header">
                <div class="store-info">
                    <div class="store-header-clickable">
                        <span class="row-number">${index}.</span>
                        <span class="expand-icon">▶</span>
                        <h4 id="store-name-${store.id}">${store.name}</h4>
                        <button class="btn-edit-name" id="edit-name-${store.id}" title="Rename store">&#9998;</button>
                        <span class="store-type-badge ${store.store_type}">${store.store_type.toUpperCase()}</span>
                        <span class="store-category-badge ${store.store_category || 'retail'}">${(store.store_category || 'retail').toUpperCase()}</span>
                    </div>
                </div>
                <div class="store-actions">
                    <button class="btn btn-small btn-secondary" id="category-${store.id}" title="Toggle wholesale/retail">
                        ${(store.store_category || 'retail') === 'retail' ? 'Set Wholesale' : 'Set Retail'}
                    </button>
                    <button class="btn btn-small btn-secondary" id="toggle-${store.id}">
                        ${store.is_active ? "Disable" : "Enable"}
                    </button>
                    <button class="btn btn-small btn-secondary" id="edit-conn-${store.id}">Edit</button>
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

async function toggleStoreCategory(storeId, currentCategory) {
  const newCategory = (currentCategory || 'retail') === 'retail' ? 'wholesale' : 'retail';
  await apiRequest(`/stores/${storeId}/category`, {
    method: "PATCH",
    body: JSON.stringify({ store_category: newCategory }),
  });
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

function startRenameStore(storeId, currentName) {
  const h4 = document.getElementById(`store-name-${storeId}`);
  const editBtn = document.getElementById(`edit-name-${storeId}`);
  if (!h4) return;

  editBtn.style.display = "none";

  const input = document.createElement("input");
  input.type = "text";
  input.value = currentName;
  input.className = "inline-rename-input";
  h4.replaceWith(input);
  input.focus();
  input.select();

  const commit = async () => {
    const newName = input.value.trim();
    if (newName && newName !== currentName) {
      await renameStore(storeId, newName);
    } else {
      await loadStores();
    }
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      input.blur();
    } else if (e.key === "Escape") {
      input.value = currentName;
      input.blur();
    }
  });

  input.addEventListener("blur", commit, { once: true });
}

async function renameStore(storeId, newName) {
  await apiRequest(`/stores/${storeId}/name`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: newName }),
  });
  await loadStores();
  await loadDashboard();
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

// Prevent backdrop close on price-update-modal during updates
document.getElementById("price-update-modal")?.addEventListener("click", (e) => {
  if (priceUpdatesState.isUpdating && e.target.id === "price-update-modal") {
    e.stopImmediatePropagation();
  }
}, true);

// Store edit-mode state (null = create mode)
let mssqlEditId = null;
let shopifyEditId = null;

// Swap modal title/submit-button/secret-field between create and edit modes
function setStoreModalMode(type, isEdit) {
  if (type === "mssql") {
    document.querySelector("#mssql-modal .modal-header h3").textContent = isEdit
      ? "Edit MSSQL Database"
      : "Add MSSQL Database";
    document.querySelector("#mssql-form button[type=submit]").textContent =
      isEdit ? "Save Changes" : "Add Database";
    const pw = document.getElementById("mssql-password");
    pw.required = !isEdit;
    pw.placeholder = isEdit ? "Leave blank to keep current" : "••••••••";
  } else {
    document.querySelector("#shopify-modal .modal-header h3").textContent = isEdit
      ? "Edit Shopify Store"
      : "Add Shopify Store";
    document.querySelector("#shopify-form button[type=submit]").textContent =
      isEdit ? "Save Changes" : "Add Store";
    const key = document.getElementById("shopify-api-key");
    key.required = !isEdit;
    key.placeholder = isEdit ? "Leave blank to keep current" : "shpat_...";
  }
}

function openEditStoreModal(store) {
  if (store.store_type === "mssql") {
    const c = store.mssql_connection;
    mssqlEditId = store.id;
    document.getElementById("mssql-name").value = store.name;
    document.getElementById("mssql-category").value =
      store.store_category || "retail";
    document.getElementById("mssql-host").value = c.host;
    document.getElementById("mssql-port").value = c.port;
    document.getElementById("mssql-database").value = c.database_name;
    document.getElementById("mssql-username").value = c.username;
    document.getElementById("mssql-password").value = "";
    setStoreModalMode("mssql", true);
    document.getElementById("mssql-test-status").className = "test-status";
    document.getElementById("mssql-test-status").textContent = "";
    openModal("mssql-modal");
  } else {
    const c = store.shopify_connection;
    shopifyEditId = store.id;
    document.getElementById("shopify-name").value = store.name;
    document.getElementById("shopify-category").value =
      store.store_category || "retail";
    document.getElementById("shopify-domain").value = c.shop_domain;
    document.getElementById("shopify-api-key").value = "";
    document.getElementById("shopify-version").value = c.api_version;
    const skuCheckbox = document.querySelector(
      "#shopify-form input[name=update_sku_with_barcode]",
    );
    if (skuCheckbox) skuCheckbox.checked = !!c.update_sku_with_barcode;
    setStoreModalMode("shopify", true);
    document.getElementById("shopify-test-status").className = "test-status";
    document.getElementById("shopify-test-status").textContent = "";
    openModal("shopify-modal");
  }
}

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
  mssqlEditId = null;
  document.getElementById("mssql-form").reset();
  setStoreModalMode("mssql", false);
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
    store_category: formData.get("store_category"),
    connection: {
      host: formData.get("host"),
      port: parseInt(formData.get("port")),
      database_name: formData.get("database_name"),
      username: formData.get("username"),
      password: formData.get("password"),
    },
  };

  if (mssqlEditId != null) {
    // omit password when blank so backend keeps the current one
    if (!data.connection.password) delete data.connection.password;
    await apiRequest(`/stores/${mssqlEditId}/mssql`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  } else {
    await apiRequest("/stores/mssql", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  closeModal("mssql-modal");
  e.target.reset();
  mssqlEditId = null;
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
  shopifyEditId = null;
  document.getElementById("shopify-form").reset();
  setStoreModalMode("shopify", false);
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
      store_category: formData.get("store_category"),
      connection: {
        shop_domain: formData.get("shop_domain"),
        admin_api_key: formData.get("admin_api_key"),
        api_version: formData.get("api_version"),
        update_sku_with_barcode:
          formData.get("update_sku_with_barcode") === "on",
      },
    };

    if (shopifyEditId != null) {
      // omit api key when blank so backend keeps the current one
      if (!data.connection.admin_api_key) delete data.connection.admin_api_key;
      await apiRequest(`/stores/${shopifyEditId}/shopify`, {
        method: "PUT",
        body: JSON.stringify(data),
      });
    } else {
      await apiRequest("/stores/shopify", {
        method: "POST",
        body: JSON.stringify(data),
      });
    }

    closeModal("shopify-modal");
    e.target.reset();
    shopifyEditId = null;
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

// Theme Toggle (Nord <-> Author's Light)
document.getElementById("themeToggle").addEventListener("click", () => {
  const current = localStorage.getItem("selectedTheme") || "author-light";
  const next = current === "author-light" ? "nord" : "author-light";
  setTheme(next);
});

// Default Landing Page Preference
function setDefaultLandingPage(pageName) {
  localStorage.setItem("defaultLandingPage", pageName);
}

function getDefaultLandingPage() {
  const saved = localStorage.getItem("defaultLandingPage") || "dashboard";
  const removed = ["store-comparison", "delivery-b"];
  if (removed.includes(saved)) {
    localStorage.setItem("defaultLandingPage", "dashboard");
    return "dashboard";
  }
  return saved;
}

// Landing page dropdown change handler
document
  .getElementById("default-landing-page")
  ?.addEventListener("change", (e) => {
    setDefaultLandingPage(e.target.value);
  });

// Exclusions store filter handler
document
  .getElementById("exclusions-store-filter")
  ?.addEventListener("change", (e) => {
    const storeId = e.target.value ? parseInt(e.target.value) : null;
    loadExclusions(storeId);
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

  // Autofocus on new UPC input after search completes
  setTimeout(() => {
    const newUpcInput = document.getElementById("new-upc-input");
    if (newUpcInput) newUpcInput.focus();
  }, 100);
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

document
  .getElementById("update-all-btn")
  ?.addEventListener("click", async () => {
    const newUPC = document.getElementById("new-upc-input").value.trim();
    const oldUPC = currentSearchResults.upc;
    const updateBtn = document.getElementById("update-all-btn");

    // Basic validation checks
    if (!newUPC) {
      alert("Please enter a new UPC");
      return;
    }

    if (currentSearchResults.matches.length === 0) {
      alert("No search results to update");
      return;
    }

    // Check if same UPC (hard block)
    if (newUPC === oldUPC) {
      document.getElementById("same-upc-value").textContent = oldUPC;
      openModal("same-upc-modal");
      return;
    }

    // Proceed with confirmation dialog and update
    const message = `Update ${currentSearchResults.total_found} item${currentSearchResults.total_found !== 1 ? "s" : ""} from UPC "${oldUPC}" to "${newUPC}"?\n\nNote: Stores with duplicate UPCs will be skipped automatically.`;
    if (confirm(message)) {
      updateUPC(oldUPC, newUPC, currentSearchResults.matches);
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
          if (data.status === "validating_store") {
            const item = createProgressItem(
              `${data.store_name} (validating...)`,
              "active",
            );
            storeItems.set(data.store_name, item);
            progressItems.appendChild(item);
            // Auto-scroll to bottom like a terminal
            progressContainer.scrollTop = progressContainer.scrollHeight;
          } else if (data.status === "skipped_store") {
            const existingItem = storeItems.get(data.store_name);
            if (existingItem) {
              const icon = existingItem.querySelector("span");
              icon.innerHTML = "⚠";
              icon.style.animation = "";
              existingItem.style.color = "var(--warning)";

              const textSpan = existingItem.querySelector("span:last-child");
              textSpan.textContent = `${data.store_name} • Skipped (duplicate found)`;
            }
          } else if (data.status === "updating_store") {
            const existingItem = storeItems.get(data.store_name);
            if (existingItem) {
              const textSpan = existingItem.querySelector("span:last-child");
              textSpan.textContent = `${data.store_name} (updating...)`;
            } else {
              const item = createProgressItem(
                `${data.store_name} (updating...)`,
                "active",
              );
              storeItems.set(data.store_name, item);
              progressItems.appendChild(item);
              progressContainer.scrollTop = progressContainer.scrollHeight;
            }
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
    if (result.skipped) {
      // Store was skipped due to duplicate
      statusTd.innerHTML =
        '<span style="color: var(--warning); font-weight: 500;">⚠ Skipped - Duplicate UPC found</span>';
      statusTd.style.fontSize = "0.875rem";
    } else if (result.success) {
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

// Generic [data-page] click delegation. Covers tool cards on the dashboard,
// dashboard KPI tiles, activity rows, health-card links, and any future
// surface that wants to navigate by adding a data-page attribute. Sidebar
// .nav-item buttons have their own listener and are skipped here.
document.addEventListener("click", (e) => {
  const trigger = e.target.closest("[data-page]");
  if (!trigger) return;
  if (trigger.classList.contains("nav-item")) return;
  const page = trigger.dataset.page;
  if (!page) return;
  e.preventDefault();
  navigateTo(page);
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

  // Reset cross-database UI
  document.getElementById("audit-cross-db-checkbox").checked = false;
  document.getElementById("audit-target-db-group").style.display = "none";

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

async function loadTargetStoreDropdown(excludeStoreId) {
  const select = document.getElementById("audit-target-store-select");

  // Reset dropdown
  select.innerHTML = '<option value="">-- Select target database --</option>';

  try {
    const stores = await apiRequest("/stores");
    const mssqlStores = stores.filter(
      (s) => s.store_type === "mssql" && s.is_active && s.id !== excludeStoreId,
    );

    if (mssqlStores.length === 0) {
      select.innerHTML =
        '<option value="">No other SQL stores available</option>';
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
    console.error("Error loading target stores:", error);
  }
}

// Store selection change handler
document
  .getElementById("audit-store-select")
  ?.addEventListener("change", (e) => {
    const runBtn = document.getElementById("run-audit-btn");
    const crossDbCheckbox = document.getElementById("audit-cross-db-checkbox");
    const targetStoreSelect = document.getElementById(
      "audit-target-store-select",
    );

    // Enable run button if store is selected and (cross-db is unchecked OR target is selected)
    const isValid =
      e.target.value && (!crossDbCheckbox.checked || targetStoreSelect.value);
    runBtn.disabled = !isValid;

    // Reload target dropdown to exclude selected source store
    if (crossDbCheckbox.checked) {
      loadTargetStoreDropdown(parseInt(e.target.value));
    }
  });

// Cross-database checkbox handler
document
  .getElementById("audit-cross-db-checkbox")
  ?.addEventListener("change", (e) => {
    const targetDbGroup = document.getElementById("audit-target-db-group");
    const storeSelect = document.getElementById("audit-store-select");
    const runBtn = document.getElementById("run-audit-btn");

    if (e.target.checked) {
      // Show target dropdown
      targetDbGroup.style.display = "block";

      // Load target stores (excluding source store)
      if (storeSelect.value) {
        loadTargetStoreDropdown(parseInt(storeSelect.value));
      }

      // Disable run button until target is selected
      runBtn.disabled = true;
    } else {
      // Hide target dropdown
      targetDbGroup.style.display = "none";

      // Re-enable run button if source store is selected
      runBtn.disabled = !storeSelect.value;
    }
  });

// Target store selection change handler
document
  .getElementById("audit-target-store-select")
  ?.addEventListener("change", (e) => {
    const runBtn = document.getElementById("run-audit-btn");
    const storeSelect = document.getElementById("audit-store-select");
    const crossDbCheckbox = document.getElementById("audit-cross-db-checkbox");

    // Enable run button if both source and target are selected
    if (crossDbCheckbox.checked) {
      runBtn.disabled = !storeSelect.value || !e.target.value;
    }
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

// Date button handlers
document
  .getElementById("audit-date-last-month")
  ?.addEventListener("click", () => {
    const now = new Date();
    const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const lastDayOfLastMonth = new Date(now.getFullYear(), now.getMonth(), 0);

    document.getElementById("audit-date-from").value =
      formatDateForInput(lastMonth);
    document.getElementById("audit-date-to").value =
      formatDateForInput(lastDayOfLastMonth);
  });

document
  .getElementById("audit-date-this-month")
  ?.addEventListener("click", () => {
    const now = new Date();
    const firstDayOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    const lastDayOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0);

    document.getElementById("audit-date-from").value =
      formatDateForInput(firstDayOfMonth);
    document.getElementById("audit-date-to").value =
      formatDateForInput(lastDayOfMonth);
  });

document.getElementById("audit-date-clear")?.addEventListener("click", () => {
  document.getElementById("audit-date-from").value = "";
  document.getElementById("audit-date-to").value = "";
});

// Helper function to format date as YYYY-MM-DD for HTML date inputs
function formatDateForInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function runAudit(storeId) {
  // Store current audit store ID for exclusion feature
  currentAuditStoreId = storeId;

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

  // Capture cross-database options
  const crossDbCheckbox = document.getElementById("audit-cross-db-checkbox");
  const targetStoreSelect = document.getElementById(
    "audit-target-store-select",
  );
  const targetStoreId =
    crossDbCheckbox.checked && targetStoreSelect.value
      ? parseInt(targetStoreSelect.value)
      : null;

  // Show loading state
  loadingEl.style.display = "block";
  progressContainer.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";
  progressItems.innerHTML = "";
  runBtn.disabled = true;

  try {
    // Build request body with optional date filters and target store
    const requestBody = { store_id: storeId };
    if (dateFrom) requestBody.date_from = dateFrom;
    if (dateTo) requestBody.date_to = dateTo;
    if (targetStoreId) requestBody.target_store_id = targetStoreId;

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
            // Pass cross-database mode flag to display function
            displayAuditResults(data, targetStoreId !== null);
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
  isCrossDatabase: false,
};

function displayAuditResults(data, isCrossDatabase = false) {
  const resultsEl = document.getElementById("audit-results");
  const tableBody = document.getElementById("audit-results-table-body");
  const orphanedCountEl = document.getElementById("audit-orphaned-count");
  const tablesCountEl = document.getElementById("audit-tables-count");
  const filterTextEl = document.getElementById("audit-filter-text");
  const reconciliationActions = document.getElementById(
    "reconciliation-actions",
  );

  // Store audit results globally for reconciliation
  currentAuditResults = {
    store_id: data.store_id,
    orphaned_records: data.orphaned_records,
    isCrossDatabase: isCrossDatabase,
  };

  // Update counts
  orphanedCountEl.textContent = data.total_orphaned;
  tablesCountEl.textContent = data.tables_checked;

  // Update filter text based on mode
  if (isCrossDatabase) {
    filterTextEl.textContent =
      "UPCs found in source but missing in target database across";
  } else {
    filterTextEl.textContent = "orphaned UPCs found across";
  }

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

    // Actions
    const actionsTd = document.createElement("td");
    actionsTd.style.textAlign = "center";
    const excludeBtn = document.createElement("button");
    excludeBtn.className = "btn-icon";
    excludeBtn.title = "Exclude this UPC from future audits";
    excludeBtn.innerHTML = "🚫";
    excludeBtn.style.cursor = "pointer";
    excludeBtn.style.fontSize = "1.125rem";
    excludeBtn.style.padding = "0.25rem 0.5rem";
    excludeBtn.style.background = "transparent";
    excludeBtn.style.border = "1px solid var(--border-color)";
    excludeBtn.style.borderRadius = "var(--radius-sm)";
    excludeBtn.style.transition = "all 0.2s";
    excludeBtn.onclick = async () => {
      if (
        !confirm(
          `Exclude UPC ${record.upc} from future audits?\n\nThis will hide this UPC from all future orphaned UPC audit results for this store.`,
        )
      ) {
        return;
      }

      try {
        const response = await fetch(`${API_BASE}/exclusions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            store_id: currentAuditStoreId,
            upc: record.upc,
            notes: `Excluded from ${record.table_name}`,
          }),
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || "Failed to exclude UPC");
        }

        // Fade out and remove the row
        row.style.transition = "opacity 0.3s";
        row.style.opacity = "0";
        setTimeout(() => {
          row.remove();
          // Update counts
          const remainingRows = tableBody.querySelectorAll("tr").length;
          const orphanedCountEl = document.getElementById(
            "audit-orphaned-count",
          );
          if (orphanedCountEl) {
            orphanedCountEl.textContent = remainingRows;
          }
          // Renumber visible rows
          tableBody.querySelectorAll("tr").forEach((r, idx) => {
            const rowNumCell = r.querySelector("td:nth-child(2)");
            if (rowNumCell) {
              rowNumCell.textContent = idx + 1;
            }
          });
        }, 300);

        showToast(`✓ UPC ${record.upc} excluded successfully`, "success");
      } catch (error) {
        console.error("Error excluding UPC:", error);
        showToast(`✗ Failed to exclude UPC: ${error.message}`, "error");
      }
    };
    excludeBtn.onmouseover = () => {
      excludeBtn.style.background = "var(--bg-tertiary)";
      excludeBtn.style.borderColor = "var(--accent-primary)";
    };
    excludeBtn.onmouseout = () => {
      excludeBtn.style.background = "transparent";
      excludeBtn.style.borderColor = "var(--border-color)";
    };
    actionsTd.appendChild(excludeBtn);
    row.appendChild(actionsTd);

    tableBody.appendChild(row);
  });

  // Show results
  resultsEl.style.display = "block";

  // Show/hide reconciliation actions based on audit mode
  // Reconciliation only works for same-database audits
  if (isCrossDatabase) {
    reconciliationActions.style.display = "none";
  } else {
    reconciliationActions.style.display = "flex";
    // Reset checkboxes and buttons
    document.getElementById("select-all-orphans").checked = false;
    updateReconciliationButtons();
  }
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
  const isCrossDb = currentAuditResults.isCrossDatabase;

  if (!filterTableName) {
    // No filter - show all
    orphanedCountEl.textContent = totalOrphaned;
    if (isCrossDb) {
      filterTextEl.textContent =
        " UPCs found in source but missing in target database across";
    } else {
      filterTextEl.textContent = " orphaned UPCs found across";
    }
    tablesCountEl.style.display = "inline";
  } else {
    // Filtered - show count and filter status
    orphanedCountEl.textContent = visibleCount;
    if (isCrossDb) {
      filterTextEl.textContent = ` of ${totalOrphaned} UPCs found in source but missing in target database (filtered by ${formatTableName(filterTableName)})`;
    } else {
      filterTextEl.textContent = ` of ${totalOrphaned} orphaned UPCs (filtered by ${formatTableName(filterTableName)})`;
    }
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

function exportAuditToCSV() {
  if (
    !currentAuditResults.orphaned_records ||
    currentAuditResults.orphaned_records.length === 0
  ) {
    return;
  }

  const header = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Styles>
  <Style ss:ID="header">
   <Font ss:Bold="1"/>
  </Style>
  <Style ss:ID="text">
   <NumberFormat ss:Format="@"/>
  </Style>
 </Styles>
 <Worksheet ss:Name="Orphaned UPCs">
  <Table>
   <Row>
    <Cell ss:StyleID="header"><Data ss:Type="String">Table Name</Data></Cell>
    <Cell ss:StyleID="header"><Data ss:Type="String">Record ID</Data></Cell>
    <Cell ss:StyleID="header"><Data ss:Type="String">Orphaned UPC</Data></Cell>
    <Cell ss:StyleID="header"><Data ss:Type="String">Product Description</Data></Cell>
   </Row>`;

  const rows = currentAuditResults.orphaned_records
    .map((record) => {
      const escapeXml = (str) => {
        if (!str) return "";
        return String(str)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&apos;");
      };

      return `   <Row>
    <Cell><Data ss:Type="String">${escapeXml(record.table_name)}</Data></Cell>
    <Cell><Data ss:Type="Number">${record.primary_key}</Data></Cell>
    <Cell ss:StyleID="text"><Data ss:Type="String">${escapeXml(record.upc)}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(record.description || "")}</Data></Cell>
   </Row>`;
    })
    .join("\n");

  const footer = `
  </Table>
 </Worksheet>
</Workbook>`;

  const excelContent = header + "\n" + rows + footer;
  const blob = new Blob([excelContent], { type: "application/vnd.ms-excel" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;

  const storeSelect = document.getElementById("audit-store-select");
  const storeName =
    storeSelect.options[storeSelect.selectedIndex]?.text || "unknown";
  const dateStr = new Date().toISOString().split("T")[0];
  const mode = currentAuditResults.isCrossDatabase
    ? "cross-database"
    : "orphaned";

  a.download = `${mode}-upcs-${storeName}-${dateStr}.xls`;
  a.click();
  URL.revokeObjectURL(url);
}

// Export audit results button handler
document
  .getElementById("export-audit-btn")
  ?.addEventListener("click", exportAuditToCSV);

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

// ============================================================================
// Item Tracker Functions
// ============================================================================

// Global state for Item Tracker
let itemTrackerState = {
  config: null,
  events: [],
  filteredEvents: [],
  isSearching: false,
  sortColumn: "event_date",
  sortDirection: "desc",
  descriptionSearchTimeout: null,
  autocompleteSelectedIndex: -1,
  autocompleteResults: [],
  configExpanded: false,
};

async function navigateToItemTrackerWithUpc(upc, days = null, fromDate = null, toDate = null) {
  // Show Item Tracker page and highlight nav item
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.remove("active");
  });
  const trackerNav = document.querySelector('[data-page="item-tracker"]');
  if (trackerNav) trackerNav.classList.add("active");

  document.querySelectorAll(".page").forEach((p) => {
    p.style.display = "none";
  });
  const trackerPage = document.getElementById("item-tracker-page");
  if (trackerPage) trackerPage.style.display = "block";

  await loadItemTrackerPage();

  if (fromDate || toDate) {
    if (fromDate) {
      document.getElementById("item-tracker-date-from").value = fromDate;
    }
    if (toDate) {
      document.getElementById("item-tracker-date-to").value = toDate;
    }
  } else if (days && days > 0) {
    const today = new Date();
    const from = new Date();
    from.setDate(today.getDate() - days);
    document.getElementById("item-tracker-date-from").value = formatDateForInput(from);
    document.getElementById("item-tracker-date-to").value = formatDateForInput(today);
  }

  const searchSection = document.getElementById("item-tracker-search-section");
  if (searchSection && searchSection.style.display !== "none") {
    document.getElementById("item-tracker-upc-input").value = upc;
    window.history.replaceState({}, "", window.location.pathname);
    searchItemTracker();
  } else {
    window.history.replaceState({}, "", window.location.pathname);
    showToast("Please configure Item Tracker databases first", "error");
  }
}

async function loadItemTrackerPage() {
  const configSection = document.getElementById("item-tracker-config-section");
  const searchSection = document.getElementById("item-tracker-search-section");

  // Load MSSQL stores for dropdowns
  try {
    const stores = await apiRequest("/stores");
    const mssqlStores = stores.filter((s) => s.store_type === "mssql");

    // Populate S2S store dropdown
    const s2sDropdown = document.getElementById("item-tracker-s2s-store");
    s2sDropdown.innerHTML = '<option value="">Select S2S database...</option>';
    mssqlStores.forEach((store) => {
      const option = document.createElement("option");
      option.value = store.id;
      option.textContent = store.name;
      s2sDropdown.appendChild(option);
    });

    // Populate sales stores checkboxes
    const salesStoresContainer = document.getElementById(
      "item-tracker-sales-stores",
    );
    salesStoresContainer.innerHTML = "";
    mssqlStores.forEach((store) => {
      const label = document.createElement("label");
      label.style.display = "flex";
      label.style.alignItems = "center";
      label.style.gap = "0.5rem";
      label.style.cursor = "pointer";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = store.id;
      checkbox.id = `sales-store-${store.id}`;
      checkbox.style.width = "auto";
      checkbox.style.margin = "0";

      const span = document.createElement("span");
      span.textContent = store.name;

      label.appendChild(checkbox);
      label.appendChild(span);
      salesStoresContainer.appendChild(label);
    });

    // Populate inventory store dropdown
    const inventoryDropdown = document.getElementById(
      "item-tracker-inventory-store",
    );
    inventoryDropdown.innerHTML =
      '<option value="">None - Skip inventory recounts</option>';
    mssqlStores.forEach((store) => {
      const option = document.createElement("option");
      option.value = store.id;
      option.textContent = store.name;
      inventoryDropdown.appendChild(option);
    });

    // Load existing config
    const config = await apiRequest("/item-tracker/config");
    itemTrackerState.config = config;

    if (config.s2s_store_id) {
      // Config exists - show search section
      s2sDropdown.value = config.s2s_store_id;

      // Check sales store checkboxes
      config.sales_store_ids.forEach((storeId) => {
        const checkbox = document.getElementById(`sales-store-${storeId}`);
        if (checkbox) checkbox.checked = true;
      });

      // Set inventory store dropdown
      if (config.inventory_store_id) {
        inventoryDropdown.value = config.inventory_store_id;
      }

      updateConfigSummary(config);
      configSection.style.display = "none";
      searchSection.style.display = "block";

      // Focus on description input
      setTimeout(() => {
        const descInput = document.getElementById("item-tracker-desc-input");
        if (descInput) descInput.focus();
      }, 100);
    } else {
      // No config - show config section
      configSection.style.display = "block";
      searchSection.style.display = "none";
    }
  } catch (error) {
    console.error("Error loading Item Tracker page:", error);
    showToast(`Failed to load Item Tracker: ${error.message}`, "error");
  }
}

function updateConfigSummary(config) {
  document.getElementById("config-s2s-name").textContent =
    config.s2s_store_name || "-";
  document.getElementById("config-sales-names").textContent =
    config.sales_store_names && config.sales_store_names.length > 0
      ? config.sales_store_names.join(", ")
      : "None selected";
  document.getElementById("config-inventory-name").textContent =
    config.inventory_store_name || "Not configured";
}

async function saveItemTrackerConfig() {
  const s2sStoreId = document.getElementById("item-tracker-s2s-store").value;

  if (!s2sStoreId) {
    showToast("Please select an S2S database", "error");
    return;
  }

  // Get selected sales stores
  const salesStoreIds = [];
  document
    .querySelectorAll(
      '#item-tracker-sales-stores input[type="checkbox"]:checked',
    )
    .forEach((checkbox) => {
      salesStoreIds.push(parseInt(checkbox.value));
    });

  // Get inventory store (optional)
  const inventoryStoreId = document.getElementById(
    "item-tracker-inventory-store",
  ).value;

  try {
    const config = await apiRequest("/item-tracker/config", {
      method: "POST",
      body: JSON.stringify({
        s2s_store_id: parseInt(s2sStoreId),
        sales_store_ids: salesStoreIds,
        inventory_store_id: inventoryStoreId
          ? parseInt(inventoryStoreId)
          : null,
      }),
    });

    itemTrackerState.config = config;
    updateConfigSummary(config);

    // Hide config section, show search section
    document.getElementById("item-tracker-config-section").style.display =
      "none";
    document.getElementById("item-tracker-search-section").style.display =
      "block";

    showToast("Configuration saved successfully", "success");

    // Focus on UPC input
    setTimeout(() => {
      const upcInput = document.getElementById("item-tracker-upc-input");
      if (upcInput) upcInput.focus();
    }, 100);
  } catch (error) {
    console.error("Error saving Item Tracker config:", error);
    showToast(`Failed to save configuration: ${error.message}`, "error");
  }
}

function showItemTrackerConfigSection() {
  document.getElementById("item-tracker-config-section").style.display =
    "block";
  document.getElementById("item-tracker-search-section").style.display = "none";
}

async function searchItemTracker() {
  if (itemTrackerState.isSearching) return;

  const upc = document.getElementById("item-tracker-upc-input").value.trim();
  if (!upc) {
    showToast("Please enter a UPC to search", "error");
    return;
  }

  const url = new URL(window.location);
  url.searchParams.set("tracker", upc);
  window.history.replaceState({}, "", url);

  const dateFrom =
    document.getElementById("item-tracker-date-from").value || null;
  const dateTo = document.getElementById("item-tracker-date-to").value || null;

  // Reset state
  itemTrackerState.isSearching = true;
  itemTrackerState.events = [];
  itemTrackerState.filteredEvents = [];

  // UI state
  const searchBtn = document.getElementById("item-tracker-search-btn");
  const loadingEl = document.getElementById("item-tracker-loading");
  const emptyEl = document.getElementById("item-tracker-empty");
  const resultsEl = document.getElementById("item-tracker-results");
  const progressEl = document.getElementById("item-tracker-progress");
  const progressItems = document.getElementById("item-tracker-progress-items");

  searchBtn.disabled = true;
  loadingEl.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";
  progressEl.style.display = "block";
  progressItems.innerHTML = "";

  try {
    const showVoided =
      document.getElementById("item-tracker-show-voided")?.checked || false;

    const requestBody = { upc, show_voided: showVoided };
    if (dateFrom) requestBody.date_from = dateFrom;
    if (dateTo) requestBody.date_to = dateTo;

    const response = await fetch(`${API_BASE}/item-tracker/search/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          const eventType = line.substring(7);
          continue;
        }
        if (line.startsWith("data: ")) {
          const data = JSON.parse(line.substring(6));
          handleItemTrackerEvent(data, progressItems);
        }
      }
    }
  } catch (error) {
    console.error("Error searching Item Tracker:", error);
    showToast(`Search failed: ${error.message}`, "error");
  } finally {
    itemTrackerState.isSearching = false;
    searchBtn.disabled = false;
    loadingEl.style.display = "none";
    progressEl.style.display = "none";
  }
}

function handleItemTrackerEvent(data, progressItems) {
  if (data.status) {
    // Progress event
    const progressItem = document.createElement("div");
    progressItem.style.fontSize = "0.875rem";
    progressItem.style.color = "var(--text-secondary)";

    if (data.status === "searching") {
      progressItem.textContent = data.message;
    } else if (data.status === "found_item") {
      progressItem.style.color = "var(--success)";
      progressItem.textContent = `✓ ${data.message}`;
    } else if (data.status === "not_found") {
      progressItem.style.color = "var(--text-tertiary)";
      progressItem.textContent = data.message;
    } else if (data.status === "completed") {
      progressItem.style.color = "var(--success)";
      progressItem.textContent = `✓ ${data.message}`;
    } else if (data.status === "store_complete") {
      progressItem.textContent = `✓ ${data.store_name}: ${data.count} ${data.event_type.replace("_", " ")}s found`;
    }

    progressItems.appendChild(progressItem);
    progressItems.scrollTop = progressItems.scrollHeight;
  } else if (data.events !== undefined) {
    // Complete event
    displayItemTrackerResults(data);
  } else if (data.message) {
    // Error event
    showToast(`Error: ${data.message}`, "error");
  }
}

function computeNetQuantity(events) {
  return events.reduce((sum, event) => {
    if (event.quantity == null) return sum;
    if (event.event_type === "inventory_recount") return sum + event.quantity;
    if (
      event.event_type === "purchase" ||
      event.event_type === "customer_return"
    )
      return sum + Math.abs(event.quantity);
    return sum - Math.abs(event.quantity);
  }, 0);
}

function displayItemTrackerResults(data) {
  const emptyEl = document.getElementById("item-tracker-empty");
  const resultsEl = document.getElementById("item-tracker-results");
  const infoCard = document.getElementById("item-tracker-info-card");

  itemTrackerState.events = data.events || [];
  itemTrackerState.filteredEvents = [...itemTrackerState.events];

  if (data.total_events === 0 && !data.item_info) {
    emptyEl.style.display = "block";
    resultsEl.style.display = "none";
    return;
  }

  resultsEl.style.display = "block";

  // Display item info if available
  if (data.item_info) {
    infoCard.style.display = "block";
    document.getElementById("item-info-upc").textContent =
      data.item_info.product_upc || "-";
    document.getElementById("item-info-description").textContent =
      data.item_info.product_description || "-";
    document.getElementById("item-info-qty").textContent =
      data.item_info.quant_on_hand !== null
        ? data.item_info.quant_on_hand.toLocaleString()
        : "-";
    // Sync description input field with search result
    document.getElementById("item-tracker-desc-input").value =
      data.item_info.product_description || "";
  } else {
    infoCard.style.display = "none";
    // Clear description input if no item found
    document.getElementById("item-tracker-desc-input").value = "";
  }

  // Display event type summary badges
  const summaryEl = document.getElementById("item-tracker-summary");
  summaryEl.innerHTML = "";

  // Calculate total quantities per event type
  const qtyTotals = {};
  data.events.forEach((event) => {
    if (!qtyTotals[event.event_type]) qtyTotals[event.event_type] = 0;
    qtyTotals[event.event_type] += event.quantity || 0;
  });

  const eventTypes = [
    { key: "purchase", label: "Purchases", color: "#22c55e" },
    { key: "sale", label: "Sales", color: "#3b82f6" },
    { key: "customer_return", label: "Cust. Returns", color: "#f59e0b" },
    { key: "vendor_return", label: "Vendor Returns", color: "#ef4444" },
    { key: "inventory_recount", label: "Inv. Recounts", color: "#a855f7" },
    { key: "in_progress", label: "In Progress", color: "#06b6d4" },
  ];

  eventTypes.forEach((type) => {
    const count = data.event_counts[type.key] || 0;
    if (count > 0) {
      const totalQty = qtyTotals[type.key] || 0;
      const badge = document.createElement("span");
      badge.style.padding = "0.375rem 0.75rem";
      badge.style.borderRadius = "var(--radius-sm)";
      badge.style.fontSize = "0.75rem";
      badge.style.fontWeight = "500";
      badge.style.background = type.color + "20";
      badge.style.color = type.color;
      badge.style.border = `1px solid ${type.color}40`;
      badge.style.display = "inline-flex";
      badge.style.alignItems = "center";
      badge.style.gap = "0.5rem";
      badge.innerHTML =
        type.key === "inventory_recount"
          ? `${type.label}: ${count}`
          : `${type.label}: ${count} <span style="opacity: 0.6;">·</span> <span style="opacity: 0.7;">${totalQty.toLocaleString()}</span>`;
      summaryEl.appendChild(badge);
    }
  });

  // Update counts
  document.getElementById("item-tracker-event-count").textContent =
    data.total_events;
  document.getElementById("item-tracker-store-count").textContent =
    data.stores_searched;

  // Reset filter
  document.getElementById("item-tracker-filter").value = "";

  // Render table
  renderItemTrackerTable(itemTrackerState.events);
}

function renderItemTrackerTable(events) {
  const tableBody = document.getElementById("item-tracker-table-body");
  tableBody.innerHTML = "";

  const eventTypeColors = {
    purchase: { bg: "#22c55e20", color: "#22c55e", label: "Purchase" },
    sale: { bg: "#3b82f620", color: "#3b82f6", label: "Sale" },
    customer_return: {
      bg: "#f59e0b20",
      color: "#f59e0b",
      label: "Cust. Return",
    },
    vendor_return: {
      bg: "#ef444420",
      color: "#ef4444",
      label: "Vendor Return",
    },
    inventory_recount: {
      bg: "#a855f720",
      color: "#a855f7",
      label: "Inv. Recount",
    },
    in_progress: {
      bg: "#06b6d420",
      color: "#06b6d4",
      label: "In Progress",
    },
  };

  events.forEach((event, index) => {
    const row = document.createElement("tr");
    const typeInfo = eventTypeColors[event.event_type] || {
      bg: "transparent",
      color: "inherit",
      label: event.event_type,
    };

    // Format date
    let dateStr = "-";
    if (event.event_date) {
      const date = new Date(event.event_date);
      dateStr =
        date.toLocaleDateString() +
        " " +
        date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }

    // Format quantity with +/- sign based on balance impact
    let qty = "-";
    if (event.quantity !== null && event.quantity !== undefined) {
      const absQty = Math.abs(event.quantity).toLocaleString();
      if (event.event_type === "inventory_recount") {
        // DiffQty already has correct sign from backend
        qty = event.quantity >= 0 ? `+${absQty}` : `-${absQty}`;
      } else if (
        event.event_type === "purchase" ||
        event.event_type === "customer_return"
      ) {
        // These add to inventory
        qty = `+${absQty}`;
      } else {
        // sale, vendor_return - these remove from inventory
        qty = `-${absQty}`;
      }
    }

    // Format document number with voided badge if applicable
    const docNumber = event.document_number || "-";
    const voidedBadge = event.is_voided
      ? `<span style="margin-left: 0.375rem; padding: 0.125rem 0.375rem; border-radius: var(--radius-sm); font-size: 0.625rem; font-weight: 600; background: #dc262620; color: #f87171; border: 1px solid #dc262640; vertical-align: middle;">VOID</span>`
      : "";

    // Format running balance (no inline variance for recounts - difference is in Qty column)
    let balanceStr = "-";
    if (event.running_balance != null) {
      balanceStr = event.running_balance.toLocaleString();
    }

    const isRecount = event.event_type === "inventory_recount";

    row.innerHTML = `
      <td style="color: var(--text-tertiary)">${index + 1}</td>
      <td style="font-size: 0.8125rem; white-space: nowrap">${dateStr}</td>
      <td>
        <span style="padding: 0.25rem 0.5rem; border-radius: var(--radius-sm); font-size: 0.75rem; font-weight: 500; background: ${typeInfo.bg}; color: ${typeInfo.color}; white-space: nowrap;">
          ${typeInfo.label}
        </span>
      </td>
      <td style="font-weight: 500">${isRecount ? "-" : event.store_name || "-"}</td>
      <td style="font-family: monospace; font-size: 0.8125rem; white-space: nowrap">${isRecount ? "-" : docNumber}${isRecount ? "" : voidedBadge}</td>
      <td style="text-align: center">${qty}</td>
      <td style="text-align: center; white-space: nowrap">${balanceStr}</td>
      <td style="max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" title="${escapeHtml(event.business_name || "")}">${escapeHtml(event.business_name || "-")}</td>
      <td style="text-align: center">
        ${
          event.event_type === "inventory_recount" || !event.business_name
            ? "-"
            : `<button class="exclude-trigger" data-name="${escapeHtml(event.business_name)}" data-type="${event.event_type}"
                 style="cursor: pointer; padding: 0.25rem 0.5rem; background: transparent; border: 1px solid var(--border-color); border-radius: var(--radius-sm); color: var(--text-tertiary); transition: all 0.15s; display: inline-flex; align-items: center;">
                 <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style="opacity: 0.7;">
                   <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                 </svg>
               </button>`
        }
      </td>
    `;

    tableBody.appendChild(row);
  });

  // Add event listeners for exclude triggers
  tableBody.querySelectorAll(".exclude-trigger").forEach((trigger) => {
    const businessName = trigger.dataset.name;
    const eventType = trigger.dataset.type;

    // Hover effects for trigger
    trigger.addEventListener("mouseover", () => {
      trigger.style.borderColor = "var(--text-tertiary)";
      trigger.style.color = "var(--text-primary)";
    });
    trigger.addEventListener("mouseout", () => {
      trigger.style.borderColor = "var(--border-color)";
      trigger.style.color = "var(--text-tertiary)";
    });

    // Show menu on click
    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      closeExcludeMenu();

      const rect = trigger.getBoundingClientRect();
      const menu = document.createElement("div");
      menu.id = "exclude-menu-popup";
      menu.style.cssText = `
        position: fixed;
        right: ${window.innerWidth - rect.right}px;
        top: ${rect.bottom + 4}px;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-sm);
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 9999;
        min-width: 120px;
        overflow: hidden;
      `;

      const options =
        eventType === "sale"
          ? [
              { value: "all", label: "Exclude All" },
              { value: "voided", label: "Voided Only" },
              { value: "nonvoided", label: "Non-voided Only" },
            ]
          : [{ value: "all", label: "Exclude All" }];

      options.forEach((opt) => {
        const btn = document.createElement("button");
        btn.textContent = opt.label;
        btn.style.cssText = `
          width: 100%;
          padding: 0.5rem 0.75rem;
          background: transparent;
          border: none;
          color: var(--text-primary);
          font-size: 0.75rem;
          text-align: left;
          cursor: pointer;
          transition: background 0.15s;
        `;
        btn.addEventListener("mouseover", () => {
          btn.style.background = "var(--bg-tertiary)";
        });
        btn.addEventListener("mouseout", () => {
          btn.style.background = "transparent";
        });
        btn.addEventListener("click", async () => {
          let voidStatus = null;
          let scopeText = "all";
          if (opt.value === "voided") {
            voidStatus = 1;
            scopeText = "voided only";
          } else if (opt.value === "nonvoided") {
            voidStatus = 0;
            scopeText = "non-voided only";
          }

          closeExcludeMenu();

          if (
            !confirm(
              `Exclude "${businessName}" (${scopeText})?\n\nThis will hide matching events from search results.`,
            )
          ) {
            return;
          }

          try {
            await apiRequest("/item-tracker/exclusions", {
              method: "POST",
              body: JSON.stringify({
                business_name: businessName,
                void_status: voidStatus,
              }),
            });

            showToast(
              `✓ "${businessName}" excluded (${scopeText})`,
              "success",
            );
            searchItemTracker();
          } catch (error) {
            console.error("Error excluding business name:", error);
            if (error.message && error.message.includes("already excluded")) {
              showToast(
                `Already excluded: ${businessName} (${scopeText})`,
                "warning",
              );
            } else {
              showToast(`✗ Failed to exclude: ${error.message}`, "error");
            }
          }
        });
        menu.appendChild(btn);
      });

      document.body.appendChild(menu);
    });
  });

  // Net quantity total
  const table = document.getElementById("item-tracker-table");
  const net = computeNetQuantity(events);
  let netColor = "var(--text-secondary)";
  let netText = "0";
  if (net > 0) {
    netColor = "var(--success, #22c55e)";
    netText = `+${net.toLocaleString()}`;
  } else if (net < 0) {
    netColor = "var(--error, #ef4444)";
    netText = net.toLocaleString();
  }

  // Top: positioned to align with QTY column
  const topEl = document.getElementById("item-tracker-net-qty-top");
  topEl.style.display = events.length > 0 ? "inline" : "none";
  topEl.style.color = netColor;
  topEl.textContent = netText;
  const qtyHeader = table.querySelector('th[data-sort="quantity"]');
  if (qtyHeader) {
    const tableRect = table.closest("div").getBoundingClientRect();
    const thRect = qtyHeader.getBoundingClientRect();
    topEl.style.left = (thRect.left - tableRect.left) + "px";
    topEl.style.width = thRect.width + "px";
  }

  // Bottom: tfoot row
  let tfoot = table.querySelector("tfoot");
  if (tfoot) tfoot.remove();
  tfoot = document.createElement("tfoot");
  tfoot.innerHTML = `<tr><td colspan="5" style="border-top: 2px solid var(--border-color);"></td><td style="text-align: center; font-weight: 700; font-family: monospace; font-size: 0.875rem; color: ${netColor}; border-top: 2px solid var(--border-color);">${netText}</td><td colspan="3" style="border-top: 2px solid var(--border-color);"></td></tr>`;
  table.appendChild(tfoot);
}

function closeExcludeMenu() {
  const existing = document.getElementById("exclude-menu-popup");
  if (existing) existing.remove();
}

// Close menu when clicking outside
document.addEventListener("click", closeExcludeMenu);

function filterItemTrackerEvents() {
  const filterValue = document.getElementById("item-tracker-filter").value;

  if (!filterValue) {
    itemTrackerState.filteredEvents = [...itemTrackerState.events];
  } else {
    itemTrackerState.filteredEvents = itemTrackerState.events.filter(
      (event) => event.event_type === filterValue,
    );
  }

  // Apply current sort
  sortItemTrackerEvents(
    itemTrackerState.sortColumn,
    itemTrackerState.sortDirection,
    false,
  );
}

function sortItemTrackerEvents(column, direction = null, toggle = true) {
  // If same column clicked, toggle direction; otherwise use specified or default desc
  if (toggle && column === itemTrackerState.sortColumn) {
    itemTrackerState.sortDirection =
      itemTrackerState.sortDirection === "asc" ? "desc" : "asc";
  } else if (direction) {
    itemTrackerState.sortDirection = direction;
  } else if (column !== itemTrackerState.sortColumn) {
    itemTrackerState.sortDirection = "desc";
  }

  itemTrackerState.sortColumn = column;

  // Sort the filtered events
  itemTrackerState.filteredEvents.sort((a, b) => {
    let valA = a[column];
    let valB = b[column];

    // Handle null/undefined values
    if (valA === null || valA === undefined) valA = "";
    if (valB === null || valB === undefined) valB = "";

    // Handle date comparison
    if (column === "event_date") {
      valA = valA ? new Date(valA).getTime() : 0;
      valB = valB ? new Date(valB).getTime() : 0;
    }

    // Handle numeric comparison
    if (column === "quantity") {
      valA = typeof valA === "number" ? valA : 0;
      valB = typeof valB === "number" ? valB : 0;
    }

    // String comparison for other columns
    if (typeof valA === "string") {
      valA = valA.toLowerCase();
      valB = valB.toLowerCase();
    }

    let result = 0;
    if (valA < valB) result = -1;
    else if (valA > valB) result = 1;

    return itemTrackerState.sortDirection === "asc" ? result : -result;
  });

  // Update sort indicators in the table header
  updateSortIndicators();

  // Re-render table
  renderItemTrackerTable(itemTrackerState.filteredEvents);
  document.getElementById("item-tracker-event-count").textContent =
    itemTrackerState.filteredEvents.length;
}

function updateSortIndicators() {
  const table = document.getElementById("item-tracker-table");
  if (!table) return;

  const headers = table.querySelectorAll("th.sortable");
  headers.forEach((header) => {
    const indicator = header.querySelector(".sort-indicator");
    if (!indicator) return;

    const column = header.dataset.sort;
    if (column === itemTrackerState.sortColumn) {
      indicator.textContent =
        itemTrackerState.sortDirection === "asc" ? "▲" : "▼";
      indicator.style.opacity = "1";
    } else {
      indicator.textContent = "";
      indicator.style.opacity = "0.3";
    }
  });
}

function exportItemTrackerCSV() {
  const events = itemTrackerState.filteredEvents;
  if (events.length === 0) {
    showToast("No data to export", "error");
    return;
  }

  // CSV headers
  const headers = [
    "#",
    "Date",
    "Type",
    "Store",
    "Document #",
    "Qty",
    "TRACK QTY",
    "Extended Amount",
    "Customer/Supplier",
  ];

  // Convert events to CSV rows
  const rows = events.map((event, index) => {
    let dateStr = "";
    if (event.event_date) {
      const date = new Date(event.event_date);
      dateStr = date.toLocaleDateString() + " " + date.toLocaleTimeString();
    }

    // Format balance for CSV (no inline variance - difference is in Qty column for recounts)
    let balanceStr = "";
    if (event.running_balance != null) {
      balanceStr = event.running_balance;
    }

    // Format quantity with +/- sign based on balance impact
    let qtyStr = "";
    if (event.quantity !== null && event.quantity !== undefined) {
      const absQty = Math.abs(event.quantity);
      if (event.event_type === "inventory_recount") {
        qtyStr = event.quantity >= 0 ? `+${absQty}` : `-${absQty}`;
      } else if (
        event.event_type === "purchase" ||
        event.event_type === "customer_return"
      ) {
        qtyStr = `+${absQty}`;
      } else {
        qtyStr = `-${absQty}`;
      }
    }

    return [
      index + 1,
      dateStr,
      event.event_type,
      event.store_name || "",
      event.document_number || "",
      qtyStr,
      balanceStr,
      event.extended_amount !== null ? event.extended_amount : "",
      event.business_name || "",
    ];
  });

  // Build CSV content
  const csvContent = [
    headers.join(","),
    ...rows.map((row) =>
      row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","),
    ),
  ].join("\n");

  // Create and download file
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;

  const upc = document.getElementById("item-tracker-upc-input").value.trim();
  const timestamp = new Date().toISOString().slice(0, 10);
  link.download = `item-tracker-${upc}-${timestamp}.csv`;

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);

  showToast(`Exported ${events.length} events to CSV`, "success");
}

// Description autocomplete functions
function handleDescriptionInput(e) {
  const query = e.target.value.trim();
  clearTimeout(itemTrackerState.descriptionSearchTimeout);

  if (query.length < 2) {
    hideDescriptionDropdown();
    return;
  }

  itemTrackerState.descriptionSearchTimeout = setTimeout(() => {
    fetchDescriptionSuggestions(query);
  }, 300);
}

async function fetchDescriptionSuggestions(query) {
  const dropdown = document.getElementById("item-tracker-desc-dropdown");

  dropdown.innerHTML = '<div class="autocomplete-loading">Searching...</div>';
  dropdown.classList.add("show");

  try {
    const response = await fetch(
      `${API_BASE}/item-tracker/description/autocomplete`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      },
    );

    if (!response.ok) {
      throw new Error("Failed to fetch suggestions");
    }

    const data = await response.json();
    showDescriptionDropdown(data.results);
  } catch (error) {
    console.error("Autocomplete error:", error);
    dropdown.innerHTML =
      '<div class="autocomplete-empty">Error fetching suggestions</div>';
  }
}

function showDescriptionDropdown(results) {
  const dropdown = document.getElementById("item-tracker-desc-dropdown");

  itemTrackerState.autocompleteResults = results;
  itemTrackerState.autocompleteSelectedIndex = -1;

  if (results.length === 0) {
    dropdown.innerHTML =
      '<div class="autocomplete-empty">No products found</div>';
    dropdown.classList.add("show");
    return;
  }

  dropdown.innerHTML = results
    .map(
      (result, index) => `
    <div class="autocomplete-item" data-index="${index}" data-upc="${result.product_upc}" data-desc="${result.product_description}">
      <div class="autocomplete-item-description">${escapeHtml(result.product_description)}</div>
      <div class="autocomplete-item-upc">UPC: ${result.product_upc || "N/A"} · Qty: ${result.quant_on_hand?.toLocaleString() ?? 0}</div>
    </div>
  `,
    )
    .join("");

  dropdown.classList.add("show");

  dropdown.querySelectorAll(".autocomplete-item").forEach((item) => {
    item.addEventListener("click", () => {
      selectDescriptionResult(item.dataset.upc, item.dataset.desc);
    });
  });
}

function updateAutocompleteSelection() {
  const dropdown = document.getElementById("item-tracker-desc-dropdown");
  const items = dropdown.querySelectorAll(".autocomplete-item");

  items.forEach((item, index) => {
    if (index === itemTrackerState.autocompleteSelectedIndex) {
      item.classList.add("selected");
      item.scrollIntoView({ block: "nearest" });
    } else {
      item.classList.remove("selected");
    }
  });
}

function handleAutocompleteKeydown(e) {
  const dropdown = document.getElementById("item-tracker-desc-dropdown");
  if (!dropdown.classList.contains("show")) return;

  const results = itemTrackerState.autocompleteResults;
  if (results.length === 0) return;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    itemTrackerState.autocompleteSelectedIndex = Math.min(
      itemTrackerState.autocompleteSelectedIndex + 1,
      results.length - 1,
    );
    updateAutocompleteSelection();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    itemTrackerState.autocompleteSelectedIndex = Math.max(
      itemTrackerState.autocompleteSelectedIndex - 1,
      0,
    );
    updateAutocompleteSelection();
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (itemTrackerState.autocompleteSelectedIndex >= 0) {
      const selected = results[itemTrackerState.autocompleteSelectedIndex];
      selectDescriptionResult(
        selected.product_upc,
        selected.product_description,
      );
    } else {
      hideDescriptionDropdown();
      const upcInput = document.getElementById("item-tracker-upc-input");
      if (upcInput.value.trim()) {
        searchItemTracker();
      }
    }
  } else if (e.key === "Escape") {
    hideDescriptionDropdown();
  }
}

function toggleItemTrackerConfig() {
  itemTrackerState.configExpanded = !itemTrackerState.configExpanded;
  const details = document.getElementById("item-tracker-config-details");
  const toggle = document.getElementById("item-tracker-config-toggle");

  if (itemTrackerState.configExpanded) {
    details.style.display = "block";
    toggle.style.transform = "rotate(90deg)";
  } else {
    details.style.display = "none";
    toggle.style.transform = "rotate(0deg)";
  }
}

function hideDescriptionDropdown() {
  const dropdown = document.getElementById("item-tracker-desc-dropdown");
  if (dropdown) {
    dropdown.classList.remove("show");
    dropdown.innerHTML = "";
  }
}

function selectDescriptionResult(upc, description) {
  document.getElementById("item-tracker-upc-input").value = upc || "";
  document.getElementById("item-tracker-desc-input").value = description || "";
  hideDescriptionDropdown();

  if (upc) {
    searchItemTracker();
  }
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function getStoreBaseName(storeName) {
  return storeName.replace(/\s+(BackOffice|Shopify)$/i, "").trim();
}

function buildStoreFilterChips(containerEl, stores, { localStorageKey, onToggle }) {
  containerEl.innerHTML = "";

  const grid = document.createElement("div");
  grid.className = "store-filter-grid";

  const controlsRow = document.createElement("div");
  controlsRow.className = "store-filter-controls";

  const selectAllBtn = document.createElement("span");
  selectAllBtn.className = "store-filter-chip store-filter-control";
  selectAllBtn.textContent = "\u2611 All";
  selectAllBtn.title = "Select all stores";
  selectAllBtn.addEventListener("click", () => {
    containerEl.querySelectorAll(".store-filter-chip:not(.store-filter-control)").forEach((c) => {
      c.classList.add("active");
      c.classList.remove("not-found");
    });
    onToggle();
  });
  controlsRow.appendChild(selectAllBtn);

  const deselectAllBtn = document.createElement("span");
  deselectAllBtn.className = "store-filter-chip store-filter-control";
  deselectAllBtn.textContent = "\u2610 None";
  deselectAllBtn.title = "Deselect all stores";
  deselectAllBtn.addEventListener("click", () => {
    containerEl.querySelectorAll(".store-filter-chip:not(.store-filter-control)").forEach((c) => {
      c.classList.remove("active");
      c.classList.add("not-found");
    });
    onToggle();
  });
  controlsRow.appendChild(deselectAllBtn);

  grid.appendChild(controlsRow);

  const shopifyStores = stores.filter((s) => s.type === "shopify");
  const mssqlStores = stores.filter((s) => s.type === "mssql");

  const shopifyNames = new Set(shopifyStores.map((s) => getStoreBaseName(s.name)));
  const mssqlNames = new Set(mssqlStores.map((s) => getStoreBaseName(s.name)));

  const sortFn = (pairedNames) => (a, b) => {
    const aBase = getStoreBaseName(a.name);
    const bBase = getStoreBaseName(b.name);
    const aPaired = pairedNames.has(aBase);
    const bPaired = pairedNames.has(bBase);
    if (aPaired !== bPaired) return aPaired ? -1 : 1;
    return aBase.localeCompare(bBase);
  };

  const pairedNames = new Set([...shopifyNames].filter((n) => mssqlNames.has(n)));
  shopifyStores.sort(sortFn(pairedNames));
  mssqlStores.sort(sortFn(pairedNames));

  const savedStores = (() => {
    try {
      const raw = localStorage.getItem(localStorageKey);
      return raw ? new Set(JSON.parse(raw)) : null;
    } catch {
      return null;
    }
  })();

  function buildRow(label, cssClass, storeList) {
    if (storeList.length === 0) return;

    const row = document.createElement("div");
    row.className = "store-filter-row";

    const rowLabel = document.createElement("span");
    rowLabel.className = "store-filter-row-label " + cssClass;
    rowLabel.textContent = label;
    rowLabel.title = "Toggle all " + label + " stores";
    rowLabel.addEventListener("click", () => {
      const chips = row.querySelectorAll(".store-filter-chip:not(.store-filter-control)");
      const allActive = Array.from(chips).every((c) => c.classList.contains("active"));
      chips.forEach((c) => {
        if (allActive) {
          c.classList.remove("active");
          c.classList.add("not-found");
        } else {
          c.classList.add("active");
          c.classList.remove("not-found");
        }
      });
      onToggle();
    });
    row.appendChild(rowLabel);

    const chipsContainer = document.createElement("div");
    chipsContainer.className = "store-filter-row-chips";

    storeList.forEach((store) => {
      const isActive = savedStores ? savedStores.has(String(store.id)) : store.hasRows;
      const chip = document.createElement("span");
      chip.className = "store-filter-chip" + (isActive ? " active" : " not-found");
      chip.dataset.storeId = store.id;
      const baseName = getStoreBaseName(store.name);
      chip.textContent = store.rowCount > 0 ? `${baseName} (${store.rowCount})` : baseName;
      chip.title = store.name;
      chip.addEventListener("click", () => {
        chip.classList.toggle("active");
        chip.classList.toggle("not-found", !chip.classList.contains("active"));
        onToggle();
      });
      chipsContainer.appendChild(chip);
    });

    row.appendChild(chipsContainer);
    grid.appendChild(row);
  }

  buildRow("SHOPIFY", "shopify", shopifyStores);
  buildRow("BACKOFFICE", "mssql", mssqlStores);

  containerEl.appendChild(grid);

  if (savedStores) onToggle();
}

// Event listeners for Item Tracker
document
  .getElementById("save-item-tracker-config-btn")
  ?.addEventListener("click", saveItemTrackerConfig);
document
  .getElementById("edit-item-tracker-config-btn")
  ?.addEventListener("click", showItemTrackerConfigSection);
document
  .getElementById("item-tracker-search-btn")
  ?.addEventListener("click", searchItemTracker);
document
  .getElementById("item-tracker-filter")
  ?.addEventListener("change", filterItemTrackerEvents);
document
  .getElementById("item-tracker-show-voided")
  ?.addEventListener("change", () => {
    // Re-run search if there's a UPC entered
    const upc = document.getElementById("item-tracker-upc-input")?.value.trim();
    if (upc) {
      searchItemTracker();
    }
  });
document
  .getElementById("export-item-tracker-btn")
  ?.addEventListener("click", exportItemTrackerCSV);

// Enter key handler for Item Tracker UPC input
document
  .getElementById("item-tracker-upc-input")
  ?.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      searchItemTracker();
    }
  });

// Description input handlers
document
  .getElementById("item-tracker-desc-input")
  ?.addEventListener("input", handleDescriptionInput);
document
  .getElementById("item-tracker-desc-input")
  ?.addEventListener("keydown", handleAutocompleteKeydown);

// Hide dropdown when clicking outside
document.addEventListener("click", (e) => {
  const descInput = document.getElementById("item-tracker-desc-input");
  const dropdown = document.getElementById("item-tracker-desc-dropdown");
  if (
    descInput &&
    dropdown &&
    !descInput.contains(e.target) &&
    !dropdown.contains(e.target)
  ) {
    hideDescriptionDropdown();
  }
});

// Config summary toggle
document
  .getElementById("item-tracker-config-header")
  ?.addEventListener("click", (e) => {
    if (!e.target.closest("#edit-item-tracker-config-btn")) {
      toggleItemTrackerConfig();
    }
  });

// Sort column click handlers for Item Tracker table
document
  .getElementById("item-tracker-table")
  ?.querySelectorAll("th.sortable")
  .forEach((header) => {
    header.addEventListener("click", () => {
      const column = header.dataset.sort;
      if (column) {
        sortItemTrackerEvents(column);
      }
    });
  });

// ==================== Price Updates ====================

let priceUpdatesState = {
  config: null,
  prices: [],
  siblingPrices: [],
  mirrors: [],
  isSearching: false,
  isUpdating: false,
  searchAbortController: null,
  descriptionSearchTimeout: null,
  autocompleteSelectedIndex: -1,
  autocompleteResults: [],
  configExpanded: false,
  primaryCost: null,
  primaryDeliveryB: null,
  stores: [],
  historyFilterTimeout: null,
  recallData: null,
  fsDescSearchTimeout: null,
  fsAutocompleteResults: [],
  fsAutocompleteSelectedIndex: -1,
};

async function loadPriceUpdatesPage() {
  const configSection = document.getElementById("price-updates-config-section");
  const searchSection = document.getElementById("price-updates-search-section");

  try {
    const [stores, mirrorsData] = await Promise.all([
      apiRequest("/stores"),
      apiRequest("/store-mirrors"),
    ]);
    const allStores = stores.filter((s) => s.is_active);
    priceUpdatesState.stores = allStores;
    const mssqlStores = allStores.filter((s) => s.store_type === "mssql");
    const mirrors = mirrorsData.mirrors || [];
    priceUpdatesState.mirrors = mirrors;

    const mirrorStoreIds = new Set(mirrors.map((m) => m.mirror_store_id));
    const mirrorSourceMap = {};
    mirrors.forEach((m) => {
      mirrorSourceMap[m.mirror_store_id] = m.source_store_name;
    });

    // Populate primary store dropdown (MSSQL only)
    const primaryDropdown = document.getElementById(
      "price-updates-primary-store",
    );
    primaryDropdown.innerHTML =
      '<option value="">Select primary store...</option>';
    mssqlStores.forEach((store) => {
      const option = document.createElement("option");
      option.value = store.id;
      option.textContent = store.name;
      primaryDropdown.appendChild(option);
    });

    // Populate store checkboxes (all stores)
    const checkboxContainer = document.getElementById(
      "price-updates-store-checkboxes",
    );
    checkboxContainer.innerHTML = "";
    allStores.forEach((store) => {
      const isMirror = mirrorStoreIds.has(store.id);
      const label = document.createElement("label");
      label.style.display = "flex";
      label.style.alignItems = "center";
      label.style.gap = "0.5rem";
      label.style.cursor = isMirror ? "default" : "pointer";
      if (isMirror) label.style.opacity = "0.5";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = store.id;
      checkbox.id = `price-store-${store.id}`;
      checkbox.dataset.storeName = store.name;
      checkbox.dataset.storeType = store.store_type;
      checkbox.dataset.isMirror = isMirror ? "true" : "false";
      checkbox.style.width = "auto";
      checkbox.style.margin = "0";

      if (isMirror) {
        checkbox.disabled = true;
        checkbox.dataset.mirrorSource = mirrorSourceMap[store.id];
      }

      const span = document.createElement("span");
      const typeLabel = store.store_type === "mssql" ? "BACKOFFICE" : store.store_type.toUpperCase();
      if (isMirror) {
        span.innerHTML = `${escapeHtml(store.name)} <span style="font-size:0.75rem;color:var(--text-tertiary);font-style:italic">(mirrors ${escapeHtml(mirrorSourceMap[store.id])})</span>`;
      } else {
        span.textContent = `${store.name} (${typeLabel})`;
      }

      label.appendChild(checkbox);
      label.appendChild(span);
      checkboxContainer.appendChild(label);
    });

    // Auto-check/uncheck mirror stores when source changes
    checkboxContainer.addEventListener("change", (e) => {
      if (e.target.type !== "checkbox" || e.target.dataset.isMirror === "true") return;
      const sourceId = parseInt(e.target.value);
      mirrors.forEach((m) => {
        if (m.source_store_id === sourceId) {
          const mirrorCb = document.getElementById(`price-store-${m.mirror_store_id}`);
          if (mirrorCb) mirrorCb.checked = e.target.checked;
        }
      });
    });

    // Load config from localStorage
    const savedConfig = localStorage.getItem("priceUpdatesConfig");
    if (savedConfig) {
      const config = JSON.parse(savedConfig);
      priceUpdatesState.config = config;

      // Verify primary store still exists
      const primaryExists = mssqlStores.some(
        (s) => s.id === config.primaryStoreId,
      );
      if (primaryExists && config.storeIds && config.storeIds.length > 0) {
        primaryDropdown.value = config.primaryStoreId;

        config.storeIds.forEach((id) => {
          const cb = document.getElementById(`price-store-${id}`);
          if (cb && !cb.disabled) cb.checked = true;
        });

        // Auto-check mirrors of checked sources
        mirrors.forEach((m) => {
          const sourceCb = document.getElementById(`price-store-${m.source_store_id}`);
          const mirrorCb = document.getElementById(`price-store-${m.mirror_store_id}`);
          if (sourceCb && sourceCb.checked && mirrorCb) mirrorCb.checked = true;
        });

        updatePriceUpdatesConfigSummary(config);
        configSection.style.display = "none";
        searchSection.style.display = "block";
        document.getElementById("price-updates-view-toggle").style.display = "block";

        setTimeout(() => {
          const descInput = document.getElementById("price-updates-desc-input");
          if (descInput) descInput.focus();
        }, 100);
        return;
      }
    }

    // No valid config — show config section
    configSection.style.display = "block";
    searchSection.style.display = "none";
    document.getElementById("price-updates-view-toggle").style.display = "block";
  } catch (error) {
    console.error("Error loading Price Updates page:", error);
    showToast(`Failed to load Price Updates: ${error.message}`, "error");
  }
}

function updatePriceUpdatesConfigSummary(config) {
  document.getElementById("price-updates-primary-name").textContent =
    config.primaryStoreName || "-";
  let storeText = config.storeNames && config.storeNames.length > 0
    ? config.storeNames.join(", ")
    : "None selected";
  if (config.mirrorStoreNames && config.mirrorStoreNames.length > 0) {
    storeText += " + " + config.mirrorStoreNames.join(", ");
  }
  document.getElementById("price-updates-store-names").textContent = storeText;
}

function savePriceUpdatesConfig() {
  const primaryStoreId = document.getElementById(
    "price-updates-primary-store",
  ).value;

  if (!primaryStoreId) {
    showToast("Please select a primary store", "error");
    return;
  }

  const storeIds = [];
  const storeNames = [];
  const mirrorStoreIds = [];
  const mirrorStoreNames = [];
  document
    .querySelectorAll(
      '#price-updates-store-checkboxes input[type="checkbox"]:checked',
    )
    .forEach((cb) => {
      if (cb.dataset.isMirror === "true") {
        mirrorStoreIds.push(parseInt(cb.value));
        mirrorStoreNames.push(`${cb.dataset.storeName} (mirrors ${cb.dataset.mirrorSource})`);
      } else {
        storeIds.push(parseInt(cb.value));
        storeNames.push(cb.dataset.storeName);
      }
    });

  if (storeIds.length === 0) {
    showToast("Please select at least one store to update", "error");
    return;
  }

  const primaryOption = document.querySelector(
    `#price-updates-primary-store option[value="${primaryStoreId}"]`,
  );
  const config = {
    primaryStoreId: parseInt(primaryStoreId),
    primaryStoreName: primaryOption ? primaryOption.textContent : "-",
    storeIds,
    storeNames,
    mirrorStoreIds,
    mirrorStoreNames,
  };

  localStorage.setItem("priceUpdatesConfig", JSON.stringify(config));
  priceUpdatesState.config = config;
  updatePriceUpdatesConfigSummary(config);

  document.getElementById("price-updates-config-section").style.display = "none";
  document.getElementById("price-updates-search-section").style.display = "block";
  document.getElementById("price-history-section").style.display = "none";
  document.getElementById("price-updates-view-toggle").style.display = "block";
  document.getElementById("price-updates-main-view-btn").classList.add("active");
  document.getElementById("price-updates-history-view-btn").classList.remove("active");
  priceHistoryState.visible = false;

  showToast("Configuration saved", "success");

  setTimeout(() => {
    const descInput = document.getElementById("price-updates-desc-input");
    if (descInput) descInput.focus();
  }, 100);
}

function showPriceUpdatesConfigSection() {
  exitPriceFullscreen();
  document.getElementById("price-updates-config-section").style.display = "block";
  document.getElementById("price-updates-search-section").style.display = "none";
  document.getElementById("price-history-section").style.display = "none";
  document.getElementById("price-updates-main-view-btn").classList.add("active");
  document.getElementById("price-updates-history-view-btn").classList.remove("active");
  priceHistoryState.visible = false;
}

function togglePriceUpdatesConfig() {
  priceUpdatesState.configExpanded = !priceUpdatesState.configExpanded;
  const details = document.getElementById("price-updates-config-details");
  const toggle = document.getElementById("price-updates-config-toggle");

  if (priceUpdatesState.configExpanded) {
    details.style.display = "block";
    toggle.style.transform = "rotate(90deg)";
  } else {
    details.style.display = "none";
    toggle.style.transform = "";
  }
}

async function searchPriceUpdates(overrideUpc, overrideIncludeSiblings) {
  if (priceUpdatesState.searchAbortController) {
    priceUpdatesState.searchAbortController.abort();
    priceUpdatesState.searchAbortController = null;
  }

  const upc = overrideUpc !== undefined
    ? overrideUpc
    : document.getElementById("price-updates-upc-input").value.trim();
  if (!upc) {
    showToast("Please enter a UPC to search", "error");
    return;
  }

  const config = priceUpdatesState.config;
  if (!config || !config.storeIds || config.storeIds.length === 0) {
    showToast("No stores configured", "error");
    return;
  }

  priceUpdatesState.isSearching = true;
  const controller = new AbortController();
  priceUpdatesState.searchAbortController = controller;
  priceUpdatesState.prices = [];

  const searchBtn = document.getElementById("price-updates-search-btn");
  const fsSearchBtn = document.getElementById("price-fs-search-btn");
  const resultsEl = document.getElementById("price-updates-results");
  const progressEl = document.getElementById("price-updates-progress");
  const progressItems = document.getElementById("price-updates-progress-items");

  searchBtn.disabled = true;
  if (fsSearchBtn) fsSearchBtn.disabled = true;
  resultsEl.style.display = "none";
  closeModal("price-update-modal");
  progressItems.innerHTML = "";
  progressEl.style.display = "block";

  let lastProgressItem = null;

  try {
    const response = await fetch(
      `${API_BASE}/price-updates/fetch-prices/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upc,
          store_ids: config.storeIds,
          include_sibling_barcodes: overrideIncludeSiblings !== undefined
            ? overrideIncludeSiblings
            : (document.getElementById("price-updates-include-siblings")?.checked || false)
        }),
        signal: controller.signal,
      },
    );

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event: ")) continue;
        if (line.startsWith("data: ")) {
          const data = JSON.parse(line.substring(6));

          if (data.status === "searching" && data.message) {
            const itemEl = document.createElement("div");
            itemEl.className = "progress-store-item";
            itemEl.innerHTML = `<div class="progress-spinner"></div><span>${escapeHtml(data.message)}</span>`;
            progressItems.appendChild(itemEl);
            progressItems.scrollTop = progressItems.scrollHeight;
            lastProgressItem = itemEl;
          } else if (data.status === "found" || data.status === "not_found") {
            if (lastProgressItem) {
              const spinner = lastProgressItem.querySelector(".progress-spinner");
              if (spinner) spinner.outerHTML = '<span class="progress-icon success">\u2713</span>';
              if (data.message) lastProgressItem.querySelector("span:last-child").textContent = data.message;
            }
          } else if (data.status === "error" && data.message) {
            if (lastProgressItem) {
              const spinner = lastProgressItem.querySelector(".progress-spinner");
              if (spinner) spinner.outerHTML = '<span class="progress-icon error">\u2717</span>';
              lastProgressItem.querySelector("span:last-child").textContent = data.message;
            }
          }

          if (data.prices) {
            priceUpdatesState.prices = data.prices;
            priceUpdatesState.siblingPrices = data.sibling_prices || [];
            displayPriceResults(upc, data.prices, priceUpdatesState.siblingPrices);
          }
        }
      }
    }
  } catch (error) {
    if (error.name === "AbortError") return;
    console.error("Error searching prices:", error);
    showToast(`Search failed: ${error.message}`, "error");
  } finally {
    if (priceUpdatesState.searchAbortController === controller) {
      priceUpdatesState.searchAbortController = null;
      priceUpdatesState.isSearching = false;
      searchBtn.disabled = false;
      if (fsSearchBtn) fsSearchBtn.disabled = false;
      // Resolve any remaining spinners
      progressItems.querySelectorAll(".progress-spinner").forEach((s) => {
        s.outerHTML = '<span class="progress-icon success">\u2713</span>';
      });
      setTimeout(() => { progressEl.style.display = "none"; }, 800);
    }
  }
}

function displayPriceResults(upc, prices, siblingPrices) {
  const resultsEl = document.getElementById("price-updates-results");
  resultsEl.style.display = "block";

  const desc =
    prices.find((p) => p.product_found && p.product_description)
      ?.product_description || "-";

  document.getElementById("price-info-upc").textContent = upc;
  document.getElementById("price-info-description").textContent = desc;

  const stickyUpc = document.getElementById("price-sticky-upc");
  const stickyDesc = document.getElementById("price-sticky-desc");
  if (stickyUpc) stickyUpc.textContent = upc;
  if (stickyDesc) stickyDesc.textContent = desc;

  // Flash product info to confirm search complete
  const stickyBarInfo = document.getElementById("price-sticky-bar-info");
  if (stickyBarInfo) {
    stickyBarInfo.classList.remove("search-complete-flash");
    void stickyBarInfo.offsetWidth;
    stickyBarInfo.classList.add("search-complete-flash");
  }

  enterPriceFullscreen();

  const tbody = document.getElementById("price-updates-tbody");
  tbody.innerHTML = "";

  const primaryStoreId = priceUpdatesState.config?.primaryStoreId;
  let primaryCost = null;
  const primaryEntry = prices.find((p) => p.store_id === primaryStoreId);
  if (primaryEntry) {
    if (primaryEntry.store_type === "mssql" && primaryEntry.product_found) {
      primaryCost = primaryEntry.unit_cost != null ? parseFloat(primaryEntry.unit_cost) : null;
    } else if (primaryEntry.store_type === "shopify" && primaryEntry.variants) {
      const searchedVariant = primaryEntry.variants.find((v) => v.is_searched);
      if (searchedVariant) primaryCost = searchedVariant.cost != null ? parseFloat(searchedVariant.cost) : null;
    }
  }
  priceUpdatesState.primaryCost = primaryCost;
  let primaryDeliveryB = null;
  if (primaryEntry && primaryEntry.store_type === "mssql" && primaryEntry.product_found) {
    primaryDeliveryB = primaryEntry.unit_delivery_b != null ? parseFloat(primaryEntry.unit_delivery_b) : null;
  }
  priceUpdatesState.primaryDeliveryB = primaryDeliveryB;

  const storeCategoryMap = {};
  (priceUpdatesState.stores || []).forEach(s => { storeCategoryMap[s.id] = s.store_category || "retail"; });

  function formatMarkup(price, cost) {
    if (price == null || cost == null || cost === 0) return { text: "-", color: "" };
    const val = ((price - cost) / cost) * 100;
    const color = val > 0 ? "var(--success)" : val < 0 ? "var(--danger)" : "";
    return { text: val.toFixed(1) + "%", color };
  }

  function formatCostMarkup(storeCost, pCost, storeId) {
    if (storeId === primaryStoreId) return { text: "-", color: "" };
    if (storeCost == null || pCost == null || pCost === 0) return { text: "-", color: "" };
    const val = ((storeCost - pCost) / pCost) * 100;
    const color = val > 0 ? "var(--danger)" : val < 0 ? "var(--success)" : "";
    return { text: val.toFixed(1) + "%", color };
  }

  function markupTd(m) {
    return `<td style="${m.color ? "color:" + m.color : ""}">${m.text}</td>`;
  }

  function currentValueSpan(val) {
    if (val === "-") return "";
    return `<span class="current-value">$${val}</span>`;
  }

  // Build store-grouped data structure
  const storeOrder = [];
  const storeData = {};

  prices.forEach((p) => {
    if (!storeData[p.store_id]) {
      storeData[p.store_id] = {
        storeName: p.store_name,
        storeType: p.store_type,
        found: p.product_found,
        mainRows: [],
        siblingRows: [],
      };
      storeOrder.push(p.store_id);
    }
    if (p.product_found) {
      storeData[p.store_id].mainRows.push(p);
    }
  });

  if (siblingPrices) {
    siblingPrices.forEach((sp) => {
      if (!storeData[sp.store_id]) {
        storeData[sp.store_id] = {
          storeName: sp.store_name,
          storeType: "mssql",
          found: sp.product_found,
          mainRows: [],
          siblingRows: [],
        };
        storeOrder.push(sp.store_id);
      }
      if (sp.product_found) {
        storeData[sp.store_id].siblingRows.push(sp);
      }
    });
  }

  // Ensure primary store appears first
  const primaryId = priceUpdatesState.config?.primaryStoreId;
  if (primaryId) {
    const idx = storeOrder.indexOf(primaryId);
    if (idx > 0) {
      storeOrder.splice(idx, 1);
      storeOrder.unshift(primaryId);
    }
  }

  // Render per store
  storeOrder.forEach((storeId) => {
    const sd = storeData[storeId];
    if (sd.mainRows.length === 0 && sd.siblingRows.length === 0) return;

    const sid = parseInt(storeId);
    const storeColor = getStoreColor(sid);
    const storeBg = getStoreBgColor(sid);
    const storeBgStrong = getStoreBgColor(sid, "strong");

    const headerTr = document.createElement("tr");
    headerTr.classList.add("store-header-row");
    headerTr.dataset.storeId = storeId;
    headerTr.style.setProperty("--store-border-color", storeColor);
    const headerTd = document.createElement("td");
    headerTd.colSpan = 7;
    headerTd.style.color = storeColor;
    headerTd.style.background = storeBgStrong;
    headerTd.textContent = sd.storeName;
    headerTr.appendChild(headerTd);
    tbody.appendChild(headerTr);

    // Main rows
    sd.mainRows.forEach((p) => {
      if (p.store_type === "mssql") {
        const tr = document.createElement("tr");
        tr.style.backgroundColor = storeBg;
        tr.style.setProperty("--store-border-color", storeColor);
        tr.dataset.storeId = p.store_id;
        tr.dataset.storeType = "mssql";
        tr.dataset.storeCategory = storeCategoryMap[p.store_id] || "retail";
        tr.dataset.barcode = upc;

        const currentPrice = p.unit_price != null ? parseFloat(p.unit_price).toFixed(2) : "-";
        const currentCost = p.unit_cost != null ? parseFloat(p.unit_cost).toFixed(2) : "-";
        const currentDeliveryB = p.unit_delivery_b != null ? parseFloat(p.unit_delivery_b).toFixed(2) : "-";
        const currentListPrice = p.unit_list_price != null ? parseFloat(p.unit_list_price).toFixed(2) : "-";
        tr.dataset.currentPrice = currentPrice;
        tr.dataset.currentCost = currentCost;
        tr.dataset.currentDeliveryB = currentDeliveryB;
        tr.dataset.currentListPrice = currentListPrice;
        const mssqlDesc = p.product_description ? escapeHtml(p.product_description) : "-";
        const mPrice = p.unit_price != null ? parseFloat(p.unit_price) : null;
        const mCost = p.unit_cost != null ? parseFloat(p.unit_cost) : null;
        const mMarkup = formatMarkup(mPrice, mCost);
        const mCostMarkup = formatCostMarkup(mCost, primaryCost, p.store_id);
        const isPrimary = p.store_id === primaryStoreId;
        const deliveryBCell = isPrimary
          ? `<td>${currentValueSpan(currentDeliveryB)}<input type="number" class="dark-input price-input new-delivery-b" step="0.01" min="0" placeholder="${currentDeliveryB}"></td>`
          : `<td style="color: var(--text-tertiary)">-</td>`;
        const listPriceCell = isPrimary
          ? `<td>${currentValueSpan(currentListPrice)}<input type="number" class="dark-input price-input new-list-price" step="0.01" min="0" placeholder="${currentListPrice}"></td>`
          : `<td style="color: var(--text-tertiary)">-</td>`;
        tr.innerHTML = `
          <td style="font-size: 0.875rem; color: var(--text-primary)">${mssqlDesc} [${escapeHtml(upc)}]</td>
          <td>${currentValueSpan(currentPrice)}<input type="number" class="dark-input price-input new-price" step="0.01" min="0" placeholder="${currentPrice}"></td>
          <td>${currentValueSpan(currentCost)}<input type="number" class="dark-input price-input new-cost" step="0.01" min="0" placeholder="${currentCost}"></td>
          ${deliveryBCell}
          ${listPriceCell}
          ${markupTd(mMarkup)}
          ${markupTd(mCostMarkup)}
          <td class="price-exclude-cell"><button type="button" class="price-exclude-btn" title="Exclude from update"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></td>
        `;
        tbody.appendChild(tr);
      } else if (p.store_type === "shopify") {
        p.variants.forEach((v) => {
          const tr = document.createElement("tr");
          tr.classList.add("variant-subrow");
          tr.style.backgroundColor = storeBg;
          tr.style.setProperty("--store-border-color", storeColor);
          tr.dataset.storeId = p.store_id;
          tr.dataset.storeType = "shopify";
          tr.dataset.storeCategory = storeCategoryMap[p.store_id] || "retail";
          tr.dataset.variantId = v.variant_id;
          tr.dataset.productId = v.product_id;
          tr.dataset.barcode = v.barcode || "";
          tr.dataset.productTitle = v.product_title || "";
          tr.dataset.variantTitle = v.variant_title || "";

          const vPrice = v.price != null ? parseFloat(v.price).toFixed(2) : "-";
          const vCost = v.cost != null ? parseFloat(v.cost).toFixed(2) : "-";
          tr.dataset.currentPrice = vPrice;
          tr.dataset.currentCost = vCost;
          tr.dataset.currentDeliveryB = "-";
          tr.dataset.currentListPrice = "-";
          const isDefaultVariant = !v.variant_title || v.variant_title === "Default Title";
          const variantLabel = escapeHtml(isDefaultVariant ? (v.product_title || "Default") : (v.product_title ? `${v.product_title} / ${v.variant_title}` : v.variant_title));
          const barcodeLabel = v.barcode ? ` [${escapeHtml(v.barcode)}]` : "";
          const vPriceNum = v.price != null ? parseFloat(v.price) : null;
          const vCostNum = v.cost != null ? parseFloat(v.cost) : null;
          const vMarkup = formatMarkup(vPriceNum, vCostNum);
          const vCostMarkup = formatCostMarkup(vCostNum, primaryCost, p.store_id);
          tr.innerHTML = `
            <td style="font-size: 0.875rem; color: var(--text-primary)">${variantLabel}${barcodeLabel}</td>
            <td>${currentValueSpan(vPrice)}<input type="number" class="dark-input price-input new-price" step="0.01" min="0" placeholder="${vPrice}"></td>
            <td>${currentValueSpan(vCost)}<input type="number" class="dark-input price-input new-cost" step="0.01" min="0" placeholder="${vCost}"></td>
            <td style="color: var(--text-tertiary)">-</td>
            <td style="color: var(--text-tertiary)">-</td>
            ${markupTd(vMarkup)}
            ${markupTd(vCostMarkup)}
            <td class="price-exclude-cell"><button type="button" class="price-exclude-btn" title="Exclude from update"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></td>
          `;
          tbody.appendChild(tr);
        });
      }
    });

    // Sibling rows
    sd.siblingRows.forEach((sp) => {
      const tr = document.createElement("tr");
      tr.style.backgroundColor = storeBg;
      tr.style.setProperty("--store-border-color", storeColor);
      tr.dataset.storeId = sp.store_id;
      tr.dataset.storeType = "mssql";
      tr.dataset.storeCategory = storeCategoryMap[sp.store_id] || "retail";
      tr.dataset.barcode = sp.sibling_barcode;

      const currentPrice = sp.unit_price != null ? parseFloat(sp.unit_price).toFixed(2) : "-";
      const currentCost = sp.unit_cost != null ? parseFloat(sp.unit_cost).toFixed(2) : "-";
      const currentDeliveryB = sp.unit_delivery_b != null ? parseFloat(sp.unit_delivery_b).toFixed(2) : "-";
      const currentListPrice = sp.unit_list_price != null ? parseFloat(sp.unit_list_price).toFixed(2) : "-";
      tr.dataset.currentPrice = currentPrice;
      tr.dataset.currentCost = currentCost;
      tr.dataset.currentDeliveryB = currentDeliveryB;
      tr.dataset.currentListPrice = currentListPrice;
      const spPrice = sp.unit_price != null ? parseFloat(sp.unit_price) : null;
      const spCost = sp.unit_cost != null ? parseFloat(sp.unit_cost) : null;
      const spMarkup = formatMarkup(spPrice, spCost);
      const spCostMarkup = formatCostMarkup(spCost, primaryCost, sp.store_id);
      const siblingLabel = `${escapeHtml(sp.product_description || sp.sibling_variant_title || "-")} [${escapeHtml(sp.sibling_barcode)}]`;
      const isPrimarySibling = sp.store_id === primaryStoreId;
      const siblingDeliveryBCell = isPrimarySibling
        ? `<td>${currentValueSpan(currentDeliveryB)}<input type="number" class="dark-input price-input new-delivery-b" step="0.01" min="0" placeholder="${currentDeliveryB}"></td>`
        : `<td style="color: var(--text-tertiary)">-</td>`;
      const siblingListPriceCell = isPrimarySibling
        ? `<td>${currentValueSpan(currentListPrice)}<input type="number" class="dark-input price-input new-list-price" step="0.01" min="0" placeholder="${currentListPrice}"></td>`
        : `<td style="color: var(--text-tertiary)">-</td>`;

      tr.innerHTML = `
        <td style="color: var(--text-secondary); font-size: 0.875rem">${siblingLabel}</td>
        <td>${currentValueSpan(currentPrice)}<input type="number" class="dark-input price-input new-price" step="0.01" min="0" placeholder="${currentPrice}"></td>
        <td>${currentValueSpan(currentCost)}<input type="number" class="dark-input price-input new-cost" step="0.01" min="0" placeholder="${currentCost}"></td>
        ${siblingDeliveryBCell}
        ${siblingListPriceCell}
        ${markupTd(spMarkup)}
        ${markupTd(spCostMarkup)}
        <td class="price-exclude-cell"><button type="button" class="price-exclude-btn" title="Exclude from update"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></td>
      `;
      tbody.appendChild(tr);
    });
  });

  // Build store filter chips
  const filtersEl = document.getElementById("price-store-filters");
  const chipStores = storeOrder.map((id) => {
    const sd = storeData[id];
    let rowCount = sd.siblingRows.length;
    sd.mainRows.forEach((p) => {
      rowCount += p.store_type === "shopify" && p.variants ? p.variants.length : 1;
    });
    return {
      id: String(id),
      name: sd.storeName,
      type: sd.storeType,
      hasRows: sd.mainRows.length > 0 || sd.siblingRows.length > 0,
      rowCount,
    };
  });
  buildStoreFilterChips(filtersEl, chipStores, {
    localStorageKey: "priceActiveStores",
    onToggle: () => { applyStoreFilters(); updateDeliveryBColumnVisibility(); updatePriceFilterZoneSummary(); updateFillAllCount(); },
  });
  updatePriceFilterZoneSummary();
  updateDeliveryBColumnVisibility();
  initPriceFilterZoneCollapse();

  // Restore fill-all last-value labels from localStorage
  const savedFillPrice = localStorage.getItem("priceFillAllPrice");
  const savedFillCost = localStorage.getItem("priceFillAllCost");
  const savedFillDeliveryB = localStorage.getItem("priceFillAllDeliveryB");
  const lastPriceEl = document.getElementById("price-fill-last-price");
  const lastCostEl = document.getElementById("price-fill-last-cost");
  const lastDeliveryBEl = document.getElementById("price-fill-last-delivery-b");
  if (lastPriceEl) lastPriceEl.textContent = savedFillPrice ? `Last: $${savedFillPrice}` : "";
  if (lastCostEl) lastCostEl.textContent = savedFillCost ? `Last: $${savedFillCost}` : "";
  if (lastDeliveryBEl) lastDeliveryBEl.textContent = savedFillDeliveryB ? `Last: $${savedFillDeliveryB}` : "";
  const savedFillListPrice = localStorage.getItem("priceFillAllListPrice");
  const lastListPriceEl = document.getElementById("price-fill-last-list-price");
  if (lastListPriceEl) lastListPriceEl.textContent = savedFillListPrice ? `Last: $${savedFillListPrice}` : "";
  updateFillAllCount();

  // Auto-focus: after update re-search, focus description for next item; otherwise first price input
  setTimeout(() => {
    if (priceUpdatesState._focusDescAfterSearch) {
      priceUpdatesState._focusDescAfterSearch = false;
      const descInput = document.getElementById("price-updates-desc-input");
      if (descInput) descInput.focus();
    } else {
      const costFill = document.getElementById("price-fill-all-cost");
      if (costFill) costFill.focus();
    }
  }, 100);

  if (priceUpdatesState.recallData) {
    setTimeout(() => applyRecallData(), 150);
  }
}

function applyStoreFilters() {
  const activeIds = new Set();
  document.querySelectorAll("#price-store-filters .store-filter-chip.active").forEach((chip) => {
    activeIds.add(chip.dataset.storeId);
  });
  localStorage.setItem("priceActiveStores", JSON.stringify([...activeIds]));

  const tbody = document.getElementById("price-updates-tbody");
  const rows = Array.from(tbody.children);

  rows.forEach((tr) => {
    if (tr.classList.contains("store-header-row")) return;
    if (tr.dataset.storeId) {
      tr.style.display = activeIds.has(tr.dataset.storeId) ? "" : "none";
    }
  });

  // Hide store headers when all their child rows are hidden
  rows.forEach((tr, i) => {
    if (!tr.classList.contains("store-header-row")) return;
    let anyVisible = false;
    for (let j = i + 1; j < rows.length; j++) {
      if (rows[j].classList.contains("store-header-row")) break;
      if (rows[j].style.display !== "none") {
        anyVisible = true;
        break;
      }
    }
    tr.style.display = anyVisible ? "" : "none";
  });
}

function updateDeliveryBColumnVisibility() {
  const primaryStoreId = priceUpdatesState.config?.primaryStoreId;
  if (!primaryStoreId) return;

  const primaryChip = document.querySelector(`#price-store-filters .store-filter-chip[data-store-id="${primaryStoreId}"]`);
  const isActive = primaryChip && primaryChip.classList.contains("active");
  const display = isActive ? "" : "none";

  const th = document.getElementById("price-delivery-b-th");
  if (th) th.style.display = display;
  const listPriceTh = document.getElementById("price-list-price-th");
  if (listPriceTh) listPriceTh.style.display = display;

  const fillGroup = document.getElementById("price-delivery-b-fill-group");
  if (fillGroup) fillGroup.style.display = display;
  const listPriceFillGroup = document.getElementById("price-list-price-fill-group");
  if (listPriceFillGroup) listPriceFillGroup.style.display = display;

  document.querySelectorAll("#price-updates-tbody tr").forEach((tr) => {
    const cells = tr.children;
    if (cells.length >= 4) cells[3].style.display = display;
    if (cells.length >= 5) cells[4].style.display = display;
  });
}

function resetPriceUpdates() {
  priceUpdatesState.recallData = null;
  exitPriceFullscreen();

  // Reset fullscreen history tab state
  const historyPanel = document.getElementById("price-fs-history-panel");
  if (historyPanel) historyPanel.classList.remove("price-fs-visible");
  const pricesTab = document.getElementById("price-fs-tab-prices");
  if (pricesTab) pricesTab.classList.add("active");
  const historyTab = document.getElementById("price-fs-tab-history");
  if (historyTab) historyTab.classList.remove("active");
  const stickyBarInfo = document.getElementById("price-sticky-bar-info");
  if (stickyBarInfo) stickyBarInfo.classList.remove("price-fs-hidden");
  document.querySelectorAll(".price-fs-hidden").forEach((el) => el.classList.remove("price-fs-hidden"));
  priceFsHistoryState.active = false;
  priceFsHistoryState.currentPage = 0;
  priceFsHistoryState.preserveState = false;
  priceFsHistoryState.expandedBatches.clear();
  priceHistoryState.preserveState = false;
  priceHistoryState.expandedBatches.clear();

  document.getElementById("price-updates-upc-input").value = "";
  document.getElementById("price-updates-desc-input").value = "";
  document.getElementById("price-updates-results").style.display = "none";
  document.getElementById("price-updates-progress").style.display = "none";
  document.getElementById("price-updates-tbody").innerHTML = "";
  document.getElementById("price-store-filters").innerHTML = "";
  document.getElementById("price-fill-all-price").value = "";
  document.getElementById("price-fill-all-cost").value = "";
  document.getElementById("price-fill-all-delivery-b").value = "";
  document.getElementById("price-fill-all-list-price").value = "";
  closeModal("price-update-modal");
  hidePriceDescriptionDropdown();
  hideFsDescriptionDropdown();
  const fsUpcInput = document.getElementById("price-fs-upc-input");
  const fsDescInput = document.getElementById("price-fs-desc-input");
  if (fsUpcInput) fsUpcInput.value = "";
  if (fsDescInput) fsDescInput.value = "";
  priceUpdatesState.prices = [];
  priceUpdatesState.siblingPrices = [];
  priceUpdatesState.primaryCost = null;
  priceUpdatesState.primaryDeliveryB = null;
  priceUpdatesState.isSearching = false;
  priceUpdatesState.isUpdating = false;
  priceUpdatesState.searchAbortController = null;
  const descInput = document.getElementById("price-updates-desc-input");
  if (descInput) descInput.focus();
}

function enterPriceFullscreen() {
  const results = document.getElementById("price-updates-results");
  if (results) results.classList.add("results-fullscreen");
  document.body.classList.add("no-scroll");

  // Sync original inputs to fullscreen search
  const fsUpc = document.getElementById("price-fs-upc-input");
  const fsSiblings = document.getElementById("price-fs-include-siblings");
  if (fsUpc) fsUpc.value = document.getElementById("price-updates-upc-input").value;
  if (fsSiblings) fsSiblings.checked = document.getElementById("price-updates-include-siblings")?.checked || false;
}

function exitPriceFullscreen() {
  const results = document.getElementById("price-updates-results");
  if (results) results.classList.remove("results-fullscreen");
  document.body.classList.remove("no-scroll");
}

function confirmExitPriceFullscreen() {
  const results = document.getElementById("price-updates-results");
  if (!results || !results.classList.contains("results-fullscreen")) return;

  if (document.getElementById("price-exit-confirm-overlay")) return;

  const overlay = document.createElement("div");
  overlay.id = "price-exit-confirm-overlay";
  overlay.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);animation:fadeIn 0.15s ease";

  const dialog = document.createElement("div");
  dialog.style.cssText = "background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:var(--radius-lg);padding:1.5rem;max-width:360px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4);animation:slideUp 0.15s ease";
  dialog.innerHTML = `
    <p style="margin:0 0 0.25rem;font-size:0.9375rem;font-weight:600;color:var(--text-primary)">Exit price updates?</p>
    <p style="margin:0 0 1.25rem;font-size:0.8125rem;color:var(--text-secondary);line-height:1.5">Unsaved changes will be lost.</p>
    <div style="display:flex;gap:0.5rem;justify-content:flex-end">
      <button id="price-exit-stay-btn" class="btn btn-secondary" style="font-size:0.8125rem;padding:0.4375rem 1rem">Cancel</button>
      <button id="price-exit-leave-btn" class="btn" style="font-size:0.8125rem;padding:0.4375rem 1rem;background:var(--danger);color:#fff;border:none;border-radius:var(--radius-md);cursor:pointer">Exit</button>
    </div>
  `;
  overlay.appendChild(dialog);
  document.body.appendChild(overlay);

  const dismiss = () => overlay.remove();

  document.getElementById("price-exit-stay-btn").addEventListener("click", dismiss);
  document.getElementById("price-exit-leave-btn").addEventListener("click", () => {
    dismiss();
    resetPriceUpdates();
  });
  overlay.addEventListener("click", (e) => { if (e.target === overlay) dismiss(); });
  overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") dismiss(); });
  document.getElementById("price-exit-stay-btn").focus();
}

function fillAllPrices() {
  const newPrice = document.getElementById("price-fill-all-price").value;
  const newCost = document.getElementById("price-fill-all-cost").value;
  const newDeliveryB = document.getElementById("price-fill-all-delivery-b").value;
  const newListPrice = document.getElementById("price-fill-all-list-price").value;

  if (newPrice) {
    localStorage.setItem("priceFillAllPrice", newPrice);
    const lbl = document.getElementById("price-fill-last-price");
    if (lbl) lbl.textContent = `Last: $${newPrice}`;
  }
  if (newCost) {
    localStorage.setItem("priceFillAllCost", newCost);
    const lbl = document.getElementById("price-fill-last-cost");
    if (lbl) lbl.textContent = `Last: $${newCost}`;
  }
  if (newDeliveryB) {
    localStorage.setItem("priceFillAllDeliveryB", newDeliveryB);
    const lbl = document.getElementById("price-fill-last-delivery-b");
    if (lbl) lbl.textContent = `Last: $${newDeliveryB}`;
  }
  if (newListPrice) {
    localStorage.setItem("priceFillAllListPrice", newListPrice);
    const lbl = document.getElementById("price-fill-last-list-price");
    if (lbl) lbl.textContent = `Last: $${newListPrice}`;
  }

  const rowSelector = '#price-updates-tbody tr:not(.store-header-row):not([style*="display: none"]):not(.price-excluded)';

  const primaryStoreId = priceUpdatesState.config?.primaryStoreId;

  // Determine effective Delivery B for non-primary cost calculation
  let effectiveDeliveryB = null;
  if (newDeliveryB !== "") {
    effectiveDeliveryB = parseFloat(newDeliveryB);
  } else if (newCost !== "" && primaryStoreId) {
    const primaryRow = document.querySelector(
      `${rowSelector}[data-store-id="${primaryStoreId}"]`
    );
    if (primaryRow) {
      const curCost = parseFloat(primaryRow.dataset.currentCost);
      const curDeliveryB = parseFloat(primaryRow.dataset.currentDeliveryB);
      if (curCost > 0 && curDeliveryB > 0) {
        effectiveDeliveryB = roundUpTo5Cents(parseFloat(newCost) * (curDeliveryB / curCost));
      }
    }
  } else {
    effectiveDeliveryB = priceUpdatesState.primaryDeliveryB;
  }

  let filledCount = 0;
  document
    .querySelectorAll(rowSelector)
    .forEach((tr) => {
      let filled = false;
      let rowCost = null;
      const isPrimary = String(tr.dataset.storeId) === String(primaryStoreId);

      if (isPrimary) {
        if (newCost !== "") {
          rowCost = newCost;
        }
      } else {
        if (effectiveDeliveryB && effectiveDeliveryB > 0) {
          const category = tr.dataset.storeCategory;
          if (category === "wholesale") {
            rowCost = effectiveDeliveryB.toFixed(2);
          } else {
            rowCost = roundUpTo5Cents(effectiveDeliveryB * 1.02).toFixed(2);
          }
        } else if (newCost !== "") {
          rowCost = newCost;
        }
      }

      if (rowCost !== null) {
        const costInput = tr.querySelector(".new-cost");
        if (costInput) { costInput.value = rowCost; filled = true; }
      }

      if (newPrice !== "") {
        const priceInput = tr.querySelector(".new-price");
        if (priceInput) {
          priceInput.value = newPrice;
          priceInput.dataset.autoCalculated = "";
          priceInput.classList.remove("auto-calculated");
          filled = true;
        }
      } else if (rowCost !== null) {
        autoCalculateFromCost(tr, rowCost);
      }

      if (newDeliveryB !== "") {
        const deliveryBInput = tr.querySelector(".new-delivery-b");
        if (deliveryBInput) {
          deliveryBInput.value = newDeliveryB;
          deliveryBInput.dataset.autoCalculated = "";
          deliveryBInput.classList.remove("auto-calculated");
          filled = true;
        }
      }

      if (newListPrice !== "") {
        const listPriceInput = tr.querySelector(".new-list-price");
        if (listPriceInput) {
          listPriceInput.value = newListPrice;
          filled = true;
        }
      }

      if (filled) {
        tr.dataset.filled = "true";
        tr.classList.add("filled-row");
        recalculateRowMarkup(tr);
        filledCount++;
      }
    });

  // Flash feedback on Fill All button
  const fillBtn = document.getElementById("price-fill-all-btn");
  if (fillBtn && filledCount > 0) {
    fillBtn.classList.remove("fill-all-flash");
    void fillBtn.offsetWidth;
    fillBtn.innerHTML = `Filled ${filledCount}`;
    fillBtn.classList.add("fill-all-flash");
    setTimeout(() => {
      fillBtn.classList.remove("fill-all-flash");
      updateFillAllCount();
    }, 1500);
  }
}

function clearAllPrices() {
  document.getElementById("price-fill-all-price").value = "";
  document.getElementById("price-fill-all-cost").value = "";
  document.getElementById("price-fill-all-delivery-b").value = "";
  document.getElementById("price-fill-all-list-price").value = "";

  document
    .querySelectorAll("#price-updates-tbody tr:not(.store-header-row)")
    .forEach((tr) => {
      tr.querySelectorAll(".price-input").forEach((inp) => {
        inp.value = "";
        inp.dataset.autoCalculated = "";
        inp.classList.remove("auto-calculated");
      });
      tr.dataset.filled = "";
      tr.classList.remove("filled-row");
      recalculateRowMarkup(tr);
    });
}

// Count visible, non-excluded rows for Fill All badge
function getVisibleRowCount() {
  return document.querySelectorAll(
    '#price-updates-tbody tr:not(.store-header-row):not([style*="display: none"]):not(.price-excluded)'
  ).length;
}

function updateFillAllCount() {
  const count = getVisibleRowCount();
  const scopeEl = document.getElementById("price-fill-all-scope");
  if (scopeEl) scopeEl.textContent = count > 0 ? ` (${count} rows)` : "";
  const fillBtn = document.getElementById("price-fill-all-btn");
  if (fillBtn && !fillBtn.classList.contains("fill-all-flash")) {
    fillBtn.innerHTML = count > 0
      ? `Fill All<span class="fill-all-count" id="price-fill-all-count"> (${count})</span>`
      : `Fill All<span class="fill-all-count" id="price-fill-all-count"></span>`;
  }
}

// Collapsible store filter zone
function updatePriceFilterZoneSummary() {
  const summaryEl = document.getElementById("price-filter-zone-summary");
  const badgesEl = document.getElementById("price-filter-zone-badges");
  if (!summaryEl) return;

  const allChips = document.querySelectorAll("#price-store-filters .store-filter-chip:not(.store-filter-control)");
  const activeChips = document.querySelectorAll("#price-store-filters .store-filter-chip.active:not(.store-filter-control)");
  const total = allChips.length;
  const active = activeChips.length;
  summaryEl.textContent = `Stores: ${active} of ${total} selected`;

  if (badgesEl) {
    let shopifyCount = 0, mssqlCount = 0;
    activeChips.forEach((c) => {
      const row = c.closest(".store-filter-row");
      if (row) {
        const label = row.querySelector(".store-filter-row-label");
        if (label && label.classList.contains("shopify")) shopifyCount++;
        else if (label && label.classList.contains("mssql")) mssqlCount++;
      }
    });
    badgesEl.innerHTML = "";
    if (shopifyCount > 0) {
      const badge = document.createElement("span");
      badge.className = "price-filter-zone-badge shopify";
      badge.textContent = `SHOPIFY: ${shopifyCount}`;
      badge.title = "Toggle all Shopify stores";
      badge.addEventListener("click", (e) => {
        e.stopPropagation();
        const shopifyLabel = document.querySelector("#price-store-filters .store-filter-row-label.shopify");
        if (shopifyLabel) shopifyLabel.click();
      });
      badgesEl.appendChild(badge);
    }
    if (mssqlCount > 0) {
      const badge = document.createElement("span");
      badge.className = "price-filter-zone-badge mssql";
      badge.textContent = `BACKOFFICE: ${mssqlCount}`;
      badge.title = "Toggle all BackOffice stores";
      badge.addEventListener("click", (e) => {
        e.stopPropagation();
        const mssqlLabel = document.querySelector("#price-store-filters .store-filter-row-label.mssql");
        if (mssqlLabel) mssqlLabel.click();
      });
      badgesEl.appendChild(badge);
    }
  }
}

document
  .getElementById("price-filter-zone-header")
  ?.addEventListener("click", () => {
    const body = document.getElementById("price-filter-zone-body");
    const toggle = document.getElementById("price-filter-zone-toggle");
    if (!body || !toggle) return;

    const isCollapsed = body.classList.contains("collapsed");
    if (isCollapsed) {
      body.classList.remove("collapsed");
      toggle.classList.add("expanded");
      localStorage.setItem("priceFilterZoneCollapsed", "false");
    } else {
      body.classList.add("collapsed");
      toggle.classList.remove("expanded");
      localStorage.setItem("priceFilterZoneCollapsed", "true");
    }
  });

function initPriceFilterZoneCollapse() {
  const body = document.getElementById("price-filter-zone-body");
  const toggle = document.getElementById("price-filter-zone-toggle");
  if (!body || !toggle) return;

  const collapsed = localStorage.getItem("priceFilterZoneCollapsed") === "true";
  if (collapsed) {
    body.classList.add("collapsed");
    toggle.classList.remove("expanded");
  } else {
    body.classList.remove("collapsed");
    toggle.classList.add("expanded");
  }
}

function collectPriceUpdates() {
  const updates = [];
  const rows = document.querySelectorAll("#price-updates-tbody tr");

  rows.forEach((tr) => {
    if (tr.classList.contains("store-header-row")) return;
    if (tr.style.display === "none") return;
    if (tr.classList.contains("price-excluded")) return;

    const storeId = parseInt(tr.dataset.storeId);
    const storeType = tr.dataset.storeType;
    const priceInput = tr.querySelector(".new-price");
    const costInput = tr.querySelector(".new-cost");
    const deliveryBInput = tr.querySelector(".new-delivery-b");
    const listPriceInput = tr.querySelector(".new-list-price");

    const newPrice = priceInput?.value ? parseFloat(priceInput.value) : null;
    const newCost = costInput?.value ? parseFloat(costInput.value) : null;
    const newDeliveryB = deliveryBInput?.value ? parseFloat(deliveryBInput.value) : null;
    const newListPrice = listPriceInput?.value ? parseFloat(listPriceInput.value) : null;

    if (newPrice === null && newCost === null && newDeliveryB === null && newListPrice === null) return;

    const oldPrice = priceInput?.placeholder && priceInput.placeholder !== "-"
      ? parseFloat(priceInput.placeholder) : null;
    const oldCost = costInput?.placeholder && costInput.placeholder !== "-"
      ? parseFloat(costInput.placeholder) : null;
    const oldDeliveryB = deliveryBInput?.placeholder && deliveryBInput.placeholder !== "-"
      ? parseFloat(deliveryBInput.placeholder) : null;
    const oldListPrice = listPriceInput?.placeholder && listPriceInput.placeholder !== "-"
      ? parseFloat(listPriceInput.placeholder) : null;
    const productDesc = tr.querySelector("td:first-child")?.textContent?.trim() || null;

    if (storeType === "mssql") {
      updates.push({
        store_id: storeId,
        store_type: "mssql",
        upc: tr.dataset.barcode || null,
        new_price: newPrice,
        new_cost: newCost,
        new_delivery_b: newDeliveryB,
        new_list_price: newListPrice,
        old_price: oldPrice,
        old_cost: oldCost,
        old_delivery_b: oldDeliveryB,
        old_list_price: oldListPrice,
        product_description: productDesc,
        _store_name: tr.closest("tbody")?.querySelector(`.store-header-row[data-store-id="${storeId}"] td`)?.textContent || `Store ${storeId}`,
      });
    } else if (storeType === "shopify") {
      let shopifyUpdate = updates.find(
        (u) => u.store_id === storeId && u.store_type === "shopify",
      );
      if (!shopifyUpdate) {
        shopifyUpdate = {
          store_id: storeId,
          store_type: "shopify",
          variant_updates: [],
          _store_name: tr.closest("tbody")?.querySelector(`.store-header-row[data-store-id="${storeId}"] td`)?.textContent || `Store ${storeId}`,
        };
        updates.push(shopifyUpdate);
      }

      shopifyUpdate.variant_updates.push({
        variant_id: tr.dataset.variantId,
        product_id: tr.dataset.productId,
        new_price: newPrice,
        new_cost: newCost,
        old_price: oldPrice,
        old_cost: oldCost,
        variant_title: tr.dataset.variantTitle || null,
        product_title: tr.dataset.productTitle || null,
        barcode: tr.dataset.barcode || null,
      });
    }
  });

  return updates;
}

function showUpdateConfirmation() {
  if (priceUpdatesState.isUpdating) return;

  const updates = collectPriceUpdates();
  if (updates.length === 0) {
    showToast("No price changes to update", "error");
    return;
  }

  const summaryEl = document.getElementById("price-update-modal-summary");

  // Group updates by store name
  const storeGroups = new Map();
  updates.forEach((u) => {
    const storeName = escapeHtml(u._store_name);
    if (!storeGroups.has(storeName)) storeGroups.set(storeName, []);
    const group = storeGroups.get(storeName);

    if (u.store_type === "mssql") {
      const parts = [];
      if (u.new_price != null) {
        const old = u.old_price != null ? `$${u.old_price.toFixed(2)}` : "-";
        parts.push(`Price ${old} \u2192 $${u.new_price.toFixed(2)}`);
      }
      if (u.new_cost != null) {
        const old = u.old_cost != null ? `$${u.old_cost.toFixed(2)}` : "-";
        parts.push(`Cost ${old} \u2192 $${u.new_cost.toFixed(2)}`);
      }
      if (u.new_delivery_b != null) {
        const old = u.old_delivery_b != null ? `$${u.old_delivery_b.toFixed(2)}` : "-";
        parts.push(`Delivery B ${old} \u2192 $${u.new_delivery_b.toFixed(2)}`);
      }
      if (u.new_list_price != null) {
        const old = u.old_list_price != null ? `$${u.old_list_price.toFixed(2)}` : "-";
        parts.push(`List Price ${old} \u2192 $${u.new_list_price.toFixed(2)}`);
      }
      const desc = u.product_description ? escapeHtml(u.product_description) : null;
      group.push({ desc, changes: parts.join(", ") });
    } else if (u.store_type === "shopify") {
      u.variant_updates.forEach((v) => {
        const parts = [];
        if (v.new_price != null) {
          const old = v.old_price != null ? `$${v.old_price.toFixed(2)}` : "-";
          parts.push(`Price ${old} \u2192 $${v.new_price.toFixed(2)}`);
        }
        if (v.new_cost != null) {
          const old = v.old_cost != null ? `$${v.old_cost.toFixed(2)}` : "-";
          parts.push(`Cost ${old} \u2192 $${v.new_cost.toFixed(2)}`);
        }
        let desc = v.product_title ? escapeHtml(v.product_title) : null;
        if (v.variant_title && v.variant_title !== "Default Title") {
          desc = desc ? `${desc} / ${escapeHtml(v.variant_title)}` : escapeHtml(v.variant_title);
        }
        group.push({ desc, changes: parts.join(", ") });
      });
    }
  });

  // Build mirror entries from configured mirrors
  const mirrors = priceUpdatesState.mirrors || [];
  const sourceStoreNames = new Set(storeGroups.keys());
  const mirrorGroups = new Map();
  mirrors.forEach((m) => {
    const escapedSource = escapeHtml(m.source_store_name);
    if (sourceStoreNames.has(escapedSource)) {
      const mirrorName = escapeHtml(m.mirror_store_name);
      const sourceItems = storeGroups.get(escapedSource);
      if (sourceItems) {
        const cloned = sourceItems.map((item) => ({
          desc: item.desc,
          changes: item.changes.replace(/Delivery B [^,]+,?\s*/g, "").replace(/List Price [^,]+,?\s*/g, "").replace(/,\s*$/, ""),
        })).filter((item) => item.changes);
        if (cloned.length > 0) {
          mirrorGroups.set(mirrorName, { items: cloned, sourceName: m.source_store_name });
        }
      }
    }
  });

  let html = "";
  storeGroups.forEach((items, storeName) => {
    html += `<div style="margin-bottom: 0.75rem;">`;
    html += `<div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">${storeName}</div>`;
    items.forEach((item) => {
      html += `<div style="padding-left: 0.75rem; margin-bottom: 0.25rem;">`;
      if (item.desc) html += `<div style="color: var(--text-tertiary); font-size: 0.75rem;">${item.desc}</div>`;
      html += `<div>${item.changes}</div>`;
      html += `</div>`;
    });
    html += `</div>`;
  });

  mirrorGroups.forEach(({ items, sourceName }, mirrorName) => {
    html += `<div style="margin-bottom: 0.75rem; opacity: 0.75;">`;
    html += `<div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">${mirrorName} <span style="font-size: 0.75rem; font-weight: 400; font-style: italic; color: var(--text-tertiary);">(mirrored from ${escapeHtml(sourceName)})</span></div>`;
    items.forEach((item) => {
      html += `<div style="padding-left: 0.75rem; margin-bottom: 0.25rem;">`;
      if (item.desc) html += `<div style="color: var(--text-tertiary); font-size: 0.75rem;">${item.desc}</div>`;
      html += `<div>${item.changes}</div>`;
      html += `</div>`;
    });
    html += `</div>`;
  });

  summaryEl.innerHTML = html;
  document.getElementById("price-update-modal-title").textContent = "Review Changes";
  document.getElementById("price-update-modal-summary").style.display = "";
  document.getElementById("price-update-modal-progress").style.display = "none";
  document.getElementById("price-update-modal-result").style.display = "none";
  document.getElementById("price-update-modal-cancel-btn").style.display = "";
  document.getElementById("price-update-modal-confirm-btn").style.display = "";
  document.getElementById("price-update-modal-close-btn").style.display = "none";
  document.getElementById("price-update-modal-x").style.display = "";
  openModal("price-update-modal");
}

function hideUpdateConfirmation() {
  closeModal("price-update-modal");
}

async function executeUpdate() {
  if (priceUpdatesState.isUpdating) return;

  const upc = document.getElementById("price-updates-upc-input").value.trim();
  if (!upc) return;

  const updates = collectPriceUpdates();
  if (updates.length === 0) return;

  const cleanUpdates = updates.map((u) => {
    const { _store_name, ...rest } = u;
    return rest;
  });

  priceUpdatesState.isUpdating = true;
  const updateBtn = document.getElementById("price-updates-update-btn");
  const progressEl = document.getElementById("price-update-modal-progress");
  const progressItems = document.getElementById("price-update-modal-progress-items");
  const resultEl = document.getElementById("price-update-modal-result");

  updateBtn.disabled = true;

  // Transition modal to updating state
  document.getElementById("price-update-modal-summary").style.display = "none";
  progressItems.innerHTML = "";
  progressEl.style.display = "";
  resultEl.style.display = "none";
  document.getElementById("price-update-modal-cancel-btn").style.display = "none";
  document.getElementById("price-update-modal-confirm-btn").style.display = "none";
  document.getElementById("price-update-modal-close-btn").style.display = "none";
  document.getElementById("price-update-modal-x").style.display = "none";
  document.getElementById("price-update-modal-title").textContent = "Updating...";

  let lastUpdateItem = null;

  try {
    const response = await fetch(`${API_BASE}/price-updates/update/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upc, updates: cleanUpdates }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event: ")) continue;
        if (line.startsWith("data: ")) {
          const data = JSON.parse(line.substring(6));

          if ((data.status === "updating" || data.status === "mirroring") && data.message) {
            const itemEl = document.createElement("div");
            itemEl.className = "progress-store-item";
            itemEl.innerHTML = `<div class="progress-spinner"></div><span>${escapeHtml(data.message)}</span>`;
            progressItems.appendChild(itemEl);
            lastUpdateItem = itemEl;
          } else if (data.status === "updated") {
            if (lastUpdateItem) {
              const spinner = lastUpdateItem.querySelector(".progress-spinner");
              if (spinner) spinner.outerHTML = '<span class="progress-icon success">\u2713</span>';
              if (data.message) lastUpdateItem.querySelector("span:last-child").textContent = data.message;
            }
          } else if (data.status === "error") {
            if (lastUpdateItem) {
              const spinner = lastUpdateItem.querySelector(".progress-spinner");
              if (spinner) spinner.outerHTML = '<span class="progress-icon error">\u2717</span>';
              if (data.message) lastUpdateItem.querySelector("span:last-child").textContent = data.message;
            }
          }

          if (data.results) {
            const succeeded = data.results.filter((r) => r.success).length;
            const failed = data.results.filter((r) => !r.success).length;

            resultEl.textContent = `Update complete: ${succeeded} succeeded, ${failed} failed`;
            resultEl.style.display = "";
            if (failed > 0) {
              resultEl.style.background = "color-mix(in srgb, var(--danger) 15%, transparent)";
              resultEl.style.color = "var(--danger)";
            } else {
              resultEl.style.background = "color-mix(in srgb, var(--success) 15%, transparent)";
              resultEl.style.color = "var(--success)";
            }

            const primaryStoreId = priceUpdatesState.config?.primaryStoreId;
            const updTbody = document.getElementById("price-updates-tbody");

            data.results.forEach((result) => {
              if (!result.success) return;
              const sid = String(result.store_id);
              const rows = updTbody.querySelectorAll(`tr[data-store-id="${sid}"]:not(.store-header-row)`);

              rows.forEach((tr) => {
                const priceInput = tr.querySelector(".new-price");
                const costInput = tr.querySelector(".new-cost");
                const deliveryBInput = tr.querySelector(".new-delivery-b");
                const listPriceInput = tr.querySelector(".new-list-price");
                let costUpdated = false;

                [
                  { input: priceInput, dataKey: "currentPrice" },
                  { input: costInput, dataKey: "currentCost" },
                  { input: deliveryBInput, dataKey: "currentDeliveryB" },
                  { input: listPriceInput, dataKey: "currentListPrice" },
                ].forEach(({ input, dataKey }) => {
                  if (!input || !input.value) return;
                  const newVal = parseFloat(input.value).toFixed(2);
                  input.placeholder = newVal;
                  tr.dataset[dataKey] = newVal;
                  const td = input.closest("td");
                  let span = td.querySelector(".current-value");
                  if (span) {
                    span.textContent = `$${newVal}`;
                  } else {
                    span = document.createElement("span");
                    span.className = "current-value";
                    span.textContent = `$${newVal}`;
                    td.insertBefore(span, input);
                  }
                  input.value = "";
                  if (dataKey === "currentCost") costUpdated = true;
                });

                if (costUpdated && parseInt(sid) === primaryStoreId) {
                  const newCostVal = parseFloat(tr.dataset.currentCost);
                  if (!isNaN(newCostVal)) priceUpdatesState.primaryCost = newCostVal;
                }

                const tds = tr.querySelectorAll("td");
                const effPrice = tr.dataset.currentPrice !== "-" ? parseFloat(tr.dataset.currentPrice) : null;
                const effCost = tr.dataset.currentCost !== "-" ? parseFloat(tr.dataset.currentCost) : null;

                if (tds[4]) {
                  if (effPrice != null && effCost != null && effCost !== 0) {
                    const markup = ((effPrice - effCost) / effCost) * 100;
                    tds[4].textContent = markup.toFixed(1) + "%";
                    tds[4].style.color = markup > 0 ? "var(--success)" : markup < 0 ? "var(--danger)" : "";
                  } else {
                    tds[4].textContent = "-";
                    tds[4].style.color = "";
                  }
                }

                if (tds[5]) {
                  const pCost = priceUpdatesState.primaryCost;
                  if (parseInt(sid) === primaryStoreId || effCost == null || pCost == null || pCost === 0) {
                    tds[5].textContent = "-";
                    tds[5].style.color = "";
                  } else {
                    const costMarkup = ((effCost - pCost) / pCost) * 100;
                    tds[5].textContent = costMarkup.toFixed(1) + "%";
                    tds[5].style.color = costMarkup > 0 ? "var(--danger)" : costMarkup < 0 ? "var(--success)" : "";
                  }
                }
              });
            });

            setTimeout(() => {
              const descInput = document.getElementById("price-fs-desc-input");
              if (descInput) descInput.focus();
            }, 100);
          }
        }
      }
    }
  } catch (error) {
    console.error("Error updating prices:", error);
    resultEl.textContent = `Update failed: ${error.message}`;
    resultEl.style.display = "";
    resultEl.style.background = "color-mix(in srgb, var(--danger) 15%, transparent)";
    resultEl.style.color = "var(--danger)";
  } finally {
    priceUpdatesState.isUpdating = false;
    updateBtn.disabled = false;
    progressItems.querySelectorAll(".progress-spinner").forEach((s) => {
      s.outerHTML = '<span class="progress-icon success">\u2713</span>';
    });
    document.getElementById("price-update-modal-title").textContent = "Update Complete";
    document.getElementById("price-update-modal-close-btn").style.display = "";
    document.getElementById("price-update-modal-x").style.display = "";
  }
}

// Price Updates description autocomplete
function handlePriceDescriptionInput(e) {
  const query = e.target.value.trim();
  clearTimeout(priceUpdatesState.descriptionSearchTimeout);

  if (query.length < 2) {
    hidePriceDescriptionDropdown();
    return;
  }

  priceUpdatesState.descriptionSearchTimeout = setTimeout(() => {
    fetchPriceDescriptionSuggestions(query);
  }, 300);
}

async function fetchPriceDescriptionSuggestions(query) {
  const dropdown = document.getElementById("price-updates-desc-dropdown");
  const config = priceUpdatesState.config;

  if (!config || !config.primaryStoreId) return;

  dropdown.innerHTML = '<div class="autocomplete-loading">Searching...</div>';
  dropdown.classList.add("show");

  try {
    const response = await fetch(
      `${API_BASE}/price-updates/description/autocomplete?store_id=${config.primaryStoreId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      },
    );

    if (!response.ok) throw new Error("Failed to fetch suggestions");

    const data = await response.json();
    showPriceDescriptionDropdown(data.results);
  } catch (error) {
    console.error("Price autocomplete error:", error);
    dropdown.innerHTML =
      '<div class="autocomplete-empty">Error fetching suggestions</div>';
  }
}

function showPriceDescriptionDropdown(results) {
  const dropdown = document.getElementById("price-updates-desc-dropdown");
  priceUpdatesState.autocompleteResults = results;
  priceUpdatesState.autocompleteSelectedIndex = -1;

  if (results.length === 0) {
    dropdown.innerHTML =
      '<div class="autocomplete-empty">No products found</div>';
    dropdown.classList.add("show");
    return;
  }

  dropdown.innerHTML = results
    .map(
      (result, index) => `
    <div class="autocomplete-item" data-index="${index}" data-upc="${result.product_upc}" data-desc="${result.product_description}">
      <div class="autocomplete-item-description">${escapeHtml(result.product_description)}</div>
      <div class="autocomplete-item-upc">UPC: ${result.product_upc || "N/A"} \u00b7 Qty: ${result.quant_on_hand?.toLocaleString() ?? 0}</div>
    </div>
  `,
    )
    .join("");

  dropdown.classList.add("show");

  dropdown.querySelectorAll(".autocomplete-item").forEach((item) => {
    item.addEventListener("click", () => {
      selectPriceDescriptionResult(item.dataset.upc, item.dataset.desc);
    });
  });
}

function hidePriceDescriptionDropdown() {
  const dropdown = document.getElementById("price-updates-desc-dropdown");
  if (dropdown) {
    dropdown.classList.remove("show");
    dropdown.innerHTML = "";
  }
}

function selectPriceDescriptionResult(upc, description) {
  document.getElementById("price-updates-upc-input").value = upc || "";
  document.getElementById("price-updates-desc-input").value = description || "";
  hidePriceDescriptionDropdown();

  if (upc) {
    searchPriceUpdates();
  }
}

function updatePriceAutocompleteSelection() {
  const dropdown = document.getElementById("price-updates-desc-dropdown");
  const items = dropdown.querySelectorAll(".autocomplete-item");

  items.forEach((item, index) => {
    if (index === priceUpdatesState.autocompleteSelectedIndex) {
      item.classList.add("selected");
      item.scrollIntoView({ block: "nearest" });
    } else {
      item.classList.remove("selected");
    }
  });
}

function handlePriceAutocompleteKeydown(e) {
  const results = priceUpdatesState.autocompleteResults;
  if (!results || results.length === 0) return;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    priceUpdatesState.autocompleteSelectedIndex = Math.min(
      priceUpdatesState.autocompleteSelectedIndex + 1,
      results.length - 1,
    );
    updatePriceAutocompleteSelection();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    priceUpdatesState.autocompleteSelectedIndex = Math.max(
      priceUpdatesState.autocompleteSelectedIndex - 1,
      0,
    );
    updatePriceAutocompleteSelection();
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (priceUpdatesState.autocompleteSelectedIndex >= 0) {
      const selected =
        results[priceUpdatesState.autocompleteSelectedIndex];
      selectPriceDescriptionResult(
        selected.product_upc,
        selected.product_description,
      );
    } else {
      searchPriceUpdates();
    }
  } else if (e.key === "Escape") {
    hidePriceDescriptionDropdown();
  }
}

// Fullscreen compact search
function searchFromFullscreen() {
  if (priceUpdatesState.isUpdating) return;

  const upc = document.getElementById("price-fs-upc-input").value.trim();
  if (!upc) {
    showToast("Please enter a UPC to search", "error");
    return;
  }

  const includeSiblings = document.getElementById("price-fs-include-siblings")?.checked || false;

  // Sync to original inputs
  document.getElementById("price-updates-upc-input").value = upc;
  document.getElementById("price-updates-include-siblings").checked = includeSiblings;

  // Clear table and show loading
  const tbody = document.getElementById("price-updates-tbody");
  if (tbody) tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:2rem;color:var(--text-tertiary)">Searching...</td></tr>';

  hideFsDescriptionDropdown();
  searchPriceUpdates(upc, includeSiblings);
}

function handleFsDescriptionInput(e) {
  const query = e.target.value.trim();
  clearTimeout(priceUpdatesState.fsDescSearchTimeout);

  if (query.length < 2) {
    hideFsDescriptionDropdown();
    return;
  }

  priceUpdatesState.fsDescSearchTimeout = setTimeout(() => {
    fetchFsDescriptionSuggestions(query);
  }, 300);
}

async function fetchFsDescriptionSuggestions(query) {
  const dropdown = document.getElementById("price-fs-desc-dropdown");
  const config = priceUpdatesState.config;

  if (!config || !config.primaryStoreId) return;

  dropdown.innerHTML = '<div class="autocomplete-loading">Searching...</div>';
  dropdown.classList.add("show");

  try {
    const response = await fetch(
      `${API_BASE}/price-updates/description/autocomplete?store_id=${config.primaryStoreId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      },
    );

    if (!response.ok) throw new Error("Failed to fetch suggestions");

    const data = await response.json();
    showFsDescriptionDropdown(data.results);
  } catch (error) {
    console.error("FS autocomplete error:", error);
    dropdown.innerHTML = '<div class="autocomplete-empty">Error fetching suggestions</div>';
  }
}

function showFsDescriptionDropdown(results) {
  const dropdown = document.getElementById("price-fs-desc-dropdown");
  priceUpdatesState.fsAutocompleteResults = results;
  priceUpdatesState.fsAutocompleteSelectedIndex = -1;

  if (results.length === 0) {
    dropdown.innerHTML = '<div class="autocomplete-empty">No products found</div>';
    dropdown.classList.add("show");
    return;
  }

  dropdown.innerHTML = results
    .map(
      (result, index) => `
    <div class="autocomplete-item" data-index="${index}" data-upc="${result.product_upc}" data-desc="${result.product_description}">
      <div class="autocomplete-item-description">${escapeHtml(result.product_description)}</div>
      <div class="autocomplete-item-upc">UPC: ${result.product_upc || "N/A"} \u00b7 Qty: ${result.quant_on_hand?.toLocaleString() ?? 0}</div>
    </div>
  `,
    )
    .join("");

  dropdown.classList.add("show");

  dropdown.querySelectorAll(".autocomplete-item").forEach((item) => {
    item.addEventListener("click", () => {
      selectFsDescriptionResult(item.dataset.upc, item.dataset.desc);
    });
  });
}

function hideFsDescriptionDropdown() {
  const dropdown = document.getElementById("price-fs-desc-dropdown");
  if (dropdown) {
    dropdown.classList.remove("show");
    dropdown.innerHTML = "";
  }
}

function selectFsDescriptionResult(upc, description) {
  document.getElementById("price-fs-upc-input").value = upc || "";
  document.getElementById("price-fs-desc-input").value = description || "";
  hideFsDescriptionDropdown();

  if (upc) {
    // Sync to original inputs
    document.getElementById("price-updates-upc-input").value = upc;
    document.getElementById("price-updates-desc-input").value = description || "";
    const includeSiblings = document.getElementById("price-fs-include-siblings")?.checked || false;
    document.getElementById("price-updates-include-siblings").checked = includeSiblings;

    const tbody = document.getElementById("price-updates-tbody");
    if (tbody) tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:2rem;color:var(--text-tertiary)">Searching...</td></tr>';

    searchPriceUpdates(upc, includeSiblings);
  }
}

function updateFsAutocompleteSelection() {
  const dropdown = document.getElementById("price-fs-desc-dropdown");
  const items = dropdown.querySelectorAll(".autocomplete-item");

  items.forEach((item, index) => {
    if (index === priceUpdatesState.fsAutocompleteSelectedIndex) {
      item.classList.add("selected");
      item.scrollIntoView({ block: "nearest" });
    } else {
      item.classList.remove("selected");
    }
  });
}

function handleFsAutocompleteKeydown(e) {
  const results = priceUpdatesState.fsAutocompleteResults;
  if (!results || results.length === 0) return;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    priceUpdatesState.fsAutocompleteSelectedIndex = Math.min(
      priceUpdatesState.fsAutocompleteSelectedIndex + 1,
      results.length - 1,
    );
    updateFsAutocompleteSelection();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    priceUpdatesState.fsAutocompleteSelectedIndex = Math.max(
      priceUpdatesState.fsAutocompleteSelectedIndex - 1,
      0,
    );
    updateFsAutocompleteSelection();
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (priceUpdatesState.fsAutocompleteSelectedIndex >= 0) {
      const selected = results[priceUpdatesState.fsAutocompleteSelectedIndex];
      selectFsDescriptionResult(selected.product_upc, selected.product_description);
    } else {
      searchFromFullscreen();
    }
  } else if (e.key === "Escape") {
    hideFsDescriptionDropdown();
  }
}

// Price Updates event listeners
document
  .getElementById("save-price-updates-config-btn")
  ?.addEventListener("click", savePriceUpdatesConfig);
document
  .getElementById("price-updates-select-all-btn")
  ?.addEventListener("click", () => {
    document.querySelectorAll('#price-updates-store-checkboxes input[type="checkbox"]').forEach((cb) => { cb.checked = true; });
  });
document
  .getElementById("price-updates-deselect-all-btn")
  ?.addEventListener("click", () => {
    document.querySelectorAll('#price-updates-store-checkboxes input[type="checkbox"]').forEach((cb) => {
      if (!cb.disabled) cb.checked = false;
      else cb.checked = false;
    });
  });
document
  .getElementById("edit-price-updates-config-btn")
  ?.addEventListener("click", showPriceUpdatesConfigSection);
document
  .getElementById("price-updates-search-btn")
  ?.addEventListener("click", searchPriceUpdates);
document
  .getElementById("price-updates-reset-btn")
  ?.addEventListener("click", () => {
    const results = document.getElementById("price-updates-results");
    if (results && results.classList.contains("results-fullscreen")) {
      confirmExitPriceFullscreen();
    } else {
      resetPriceUpdates();
    }
  });
document
  .getElementById("price-sticky-expand-btn")
  ?.addEventListener("click", () => {
    confirmExitPriceFullscreen();
  });
document
  .getElementById("price-updates-upc-input")
  ?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchPriceUpdates();
  });
document
  .getElementById("price-fill-all-btn")
  ?.addEventListener("click", fillAllPrices);
document
  .getElementById("price-clear-all-btn")
  ?.addEventListener("click", clearAllPrices);
document
  .getElementById("price-updates-update-btn")
  ?.addEventListener("click", showUpdateConfirmation);
document
  .getElementById("price-update-modal-confirm-btn")
  ?.addEventListener("click", executeUpdate);
document
  .getElementById("price-update-modal-cancel-btn")
  ?.addEventListener("click", hideUpdateConfirmation);
document
  .getElementById("price-update-modal-close-btn")
  ?.addEventListener("click", hideUpdateConfirmation);
document
  .getElementById("price-updates-desc-input")
  ?.addEventListener("input", handlePriceDescriptionInput);
document
  .getElementById("price-updates-desc-input")
  ?.addEventListener("keydown", handlePriceAutocompleteKeydown);
document
  .getElementById("price-fs-search-btn")
  ?.addEventListener("click", searchFromFullscreen);
document
  .getElementById("price-fs-upc-input")
  ?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchFromFullscreen();
  });
document
  .getElementById("price-fs-desc-input")
  ?.addEventListener("input", handleFsDescriptionInput);
document
  .getElementById("price-fs-desc-input")
  ?.addEventListener("keydown", handleFsAutocompleteKeydown);

// Clear buttons for fullscreen search inputs
document.querySelectorAll(".price-fs-input-clear").forEach((btn) => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const targetId = btn.dataset.target;
    const input = document.getElementById(targetId);
    if (input) {
      input.value = "";
      input.focus();
      input.dispatchEvent(new Event("input"));
    }
  });
});

// Keyboard shortcuts for fullscreen mode
document.addEventListener("keydown", (e) => {
  const results = document.getElementById("price-updates-results");
  if (!results || !results.classList.contains("results-fullscreen")) return;

  // Don't intercept when typing in inputs (except for specific combos)
  const inInput = document.activeElement && (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA" || document.activeElement.tagName === "SELECT");

  // Escape - exit fullscreen
  if (e.key === "Escape" && !document.getElementById("price-exit-confirm-overlay")) {
    e.preventDefault();
    confirmExitPriceFullscreen();
    return;
  }

  // "/" - focus UPC search
  if (e.key === "/" && !inInput) {
    e.preventDefault();
    const upcInput = document.getElementById("price-fs-upc-input");
    if (upcInput) upcInput.focus();
    return;
  }

  // Ctrl+A - select all stores
  if (e.ctrlKey && !e.shiftKey && e.key === "a" && !inInput) {
    e.preventDefault();
    const allBtn = document.querySelector("#price-store-filters .store-filter-chip.store-filter-control");
    if (allBtn) allBtn.click();
    return;
  }

  // Ctrl+Shift+A - deselect all stores
  if (e.ctrlKey && e.shiftKey && (e.key === "A" || e.key === "a")) {
    e.preventDefault();
    const noneBtn = document.querySelectorAll("#price-store-filters .store-filter-chip.store-filter-control")[1];
    if (noneBtn) noneBtn.click();
    return;
  }

  // Ctrl+F - focus price fill input
  if (e.ctrlKey && !e.shiftKey && e.key === "f") {
    e.preventDefault();
    const priceInput = document.getElementById("price-fill-all-price");
    if (priceInput) priceInput.focus();
    return;
  }

  // Ctrl+Enter - fill all
  if (e.ctrlKey && e.key === "Enter") {
    e.preventDefault();
    fillAllPrices();
    return;
  }
});

function roundPriceTo5or9(value) {
  const cents = Math.round(value * 100);
  const lastDigit = cents % 10;
  if (lastDigit <= 5) {
    return (cents + (5 - lastDigit)) / 100;
  }
  return (cents + (9 - lastDigit)) / 100;
}

function roundUpTo5Cents(value) {
  return Math.ceil(value * 20) / 20;
}

function autoCalculateFromCost(tr, newCostValue) {
  const curCost = parseFloat(tr.dataset.currentCost);
  const curPrice = parseFloat(tr.dataset.currentPrice);
  const curDeliveryB = parseFloat(tr.dataset.currentDeliveryB);
  const newCost = parseFloat(newCostValue);

  if (!newCost || isNaN(newCost) || !curCost || isNaN(curCost) || curCost === 0) return;

  if (curPrice && !isNaN(curPrice)) {
    const markupRatio = (curPrice - curCost) / curCost;
    const rawPrice = newCost * (1 + markupRatio);
    const newPrice = roundPriceTo5or9(rawPrice);
    const priceInput = tr.querySelector(".new-price");
    if (priceInput) {
      priceInput.value = newPrice.toFixed(2);
      priceInput.dataset.autoCalculated = "true";
      priceInput.classList.add("auto-calculated");
    }
  }

  const deliveryBInput = tr.querySelector(".new-delivery-b");
  if (deliveryBInput && curDeliveryB && !isNaN(curDeliveryB) && curDeliveryB > 0) {
    const deliveryBRatio = curDeliveryB / curCost;
    const rawDeliveryB = newCost * deliveryBRatio;
    const newDeliveryB = roundUpTo5Cents(rawDeliveryB);
    deliveryBInput.value = newDeliveryB.toFixed(2);
    deliveryBInput.dataset.autoCalculated = "true";
    deliveryBInput.classList.add("auto-calculated");
  }
}

// Real-time markup recalculation (Improvement 1)
function recalculateRowMarkup(tr) {
  const priceInput = tr.querySelector(".new-price");
  const costInput = tr.querySelector(".new-cost");
  if (!priceInput || !costInput) return;

  const price = priceInput.value ? parseFloat(priceInput.value) :
    (priceInput.placeholder && priceInput.placeholder !== "-" ? parseFloat(priceInput.placeholder) : null);
  const cost = costInput.value ? parseFloat(costInput.value) :
    (costInput.placeholder && costInput.placeholder !== "-" ? parseFloat(costInput.placeholder) : null);

  const tds = tr.querySelectorAll("td");
  const hasTyped = priceInput.value || costInput.value;

  // Markup (6th td, index 5)
  if (price != null && cost != null && cost !== 0) {
    const val = ((price - cost) / cost) * 100;
    const color = val > 0 ? "var(--success)" : val < 0 ? "var(--danger)" : "";
    tds[5].textContent = val.toFixed(1) + "%";
    tds[5].style.color = hasTyped ? (color || "var(--accent-primary)") : color;
  } else {
    tds[5].textContent = "-";
    tds[5].style.color = "";
  }

  // Cost markup (7th td, index 6)
  const pCost = priceUpdatesState.primaryCost;
  const storeId = parseInt(tr.dataset.storeId);
  const primaryStoreId = priceUpdatesState.config?.primaryStoreId;
  if (storeId === primaryStoreId) {
    tds[6].textContent = "-";
    tds[6].style.color = "";
  } else if (cost != null && pCost != null && pCost !== 0) {
    const val = ((cost - pCost) / pCost) * 100;
    const color = val > 0 ? "var(--danger)" : val < 0 ? "var(--success)" : "";
    tds[6].textContent = val.toFixed(1) + "%";
    tds[6].style.color = hasTyped ? (color || "var(--accent-primary)") : color;
  } else {
    tds[6].textContent = "-";
    tds[6].style.color = "";
  }
}

const xIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
const plusIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h18"/><path d="M12 3v18"/></svg>';

function excludePriceRow(tr) {
  if (tr.classList.contains("price-excluded")) return;
  tr.classList.add("price-excluded");
  tr.querySelectorAll(".price-input").forEach((inp) => { inp.value = ""; inp.disabled = true; });
  tr.classList.remove("filled-row");
  tr.dataset.filled = "";
  const btn = tr.querySelector(".price-exclude-btn");
  if (btn) { btn.innerHTML = plusIcon; btn.title = "Restore row"; }
  recalculateRowMarkup(tr);
}

function restorePriceRow(tr) {
  if (!tr.classList.contains("price-excluded")) return;
  tr.classList.remove("price-excluded");
  tr.querySelectorAll(".price-input").forEach((inp) => { inp.disabled = false; });
  const btn = tr.querySelector(".price-exclude-btn");
  if (btn) { btn.innerHTML = xIcon; btn.title = "Exclude from update"; }
  recalculateRowMarkup(tr);
}

let activeExcludePopover = null;

function dismissExcludePopover() {
  if (activeExcludePopover) {
    activeExcludePopover.remove();
    activeExcludePopover = null;
  }
}

function getMatchingBarcodeRows(barcode) {
  if (!barcode) return [];
  return Array.from(document.querySelectorAll(`#price-updates-tbody tr:not(.store-header-row)[data-barcode="${CSS.escape(barcode)}"]`));
}

function showExcludePopover(btn, tr) {
  dismissExcludePopover();
  const isExcluded = tr.classList.contains("price-excluded");
  const barcode = tr.dataset.barcode || "";
  const matchingRows = getMatchingBarcodeRows(barcode);
  const matchCount = matchingRows.length;

  const popover = document.createElement("div");
  popover.className = "price-exclude-popover";

  const singleBtn = document.createElement("button");
  singleBtn.className = "price-exclude-popover-item";
  singleBtn.textContent = isExcluded ? "Restore this item" : "Exclude this item";
  singleBtn.addEventListener("click", () => {
    if (isExcluded) restorePriceRow(tr); else excludePriceRow(tr);
    updateFillAllCount();
    dismissExcludePopover();
  });
  popover.appendChild(singleBtn);

  if (barcode && matchCount > 1) {
    const allBtn = document.createElement("button");
    allBtn.className = "price-exclude-popover-item";
    const label = isExcluded ? "Restore in all stores" : "Exclude in all stores";
    allBtn.innerHTML = `${label} <span class="popover-count">(${matchCount})</span>`;
    allBtn.addEventListener("click", () => {
      matchingRows.forEach((r) => { if (isExcluded) restorePriceRow(r); else excludePriceRow(r); });
      updateFillAllCount();
      dismissExcludePopover();
    });
    popover.appendChild(allBtn);
  }

  document.body.appendChild(popover);
  activeExcludePopover = popover;

  const rect = btn.getBoundingClientRect();
  const popRect = popover.getBoundingClientRect();
  let top = rect.top - popRect.height - 4;
  let left = rect.right - popRect.width;
  if (top < 4) top = rect.bottom + 4;
  if (left < 4) left = 4;
  if (left + popRect.width > window.innerWidth - 4) left = window.innerWidth - popRect.width - 4;
  popover.style.top = top + "px";
  popover.style.left = left + "px";
}

document.getElementById("price-updates-tbody")?.addEventListener("click", (e) => {
  const btn = e.target.closest(".price-exclude-btn");
  if (!btn) return;
  e.stopPropagation();
  const tr = btn.closest("tr");
  if (!tr) return;
  showExcludePopover(btn, tr);
});

document.getElementById("price-updates-tbody")?.addEventListener("input", (e) => {
  if (!e.target.matches(".new-price, .new-cost, .new-delivery-b")) return;
  const tr = e.target.closest("tr");
  if (!tr) return;

  tr.dataset.filled = "";
  tr.classList.remove("filled-row");

  if (e.target.matches(".new-cost")) {
    if (e.target.value) {
      autoCalculateFromCost(tr, e.target.value);
    } else {
      const priceInput = tr.querySelector(".new-price");
      if (priceInput && priceInput.dataset.autoCalculated === "true") {
        priceInput.value = "";
        priceInput.dataset.autoCalculated = "";
        priceInput.classList.remove("auto-calculated");
      }
      const deliveryBInput = tr.querySelector(".new-delivery-b");
      if (deliveryBInput && deliveryBInput.dataset.autoCalculated === "true") {
        deliveryBInput.value = "";
        deliveryBInput.dataset.autoCalculated = "";
        deliveryBInput.classList.remove("auto-calculated");
      }
    }
  } else if (e.target.matches(".new-price") || e.target.matches(".new-delivery-b")) {
    e.target.dataset.autoCalculated = "";
    e.target.classList.remove("auto-calculated");
  }

  recalculateRowMarkup(tr);
});

// Keyboard shortcut: Ctrl+Enter / Cmd+Enter to trigger update
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    const page = document.getElementById("price-updates-page");
    const results = document.getElementById("price-updates-results");
    if (page && page.style.display !== "none" && results && results.style.display !== "none") {
      e.preventDefault();
      const modal = document.getElementById("price-update-modal");
      if (modal && modal.classList.contains("active")) {
        executeUpdate();
      } else {
        showUpdateConfirmation();
      }
    }
  }
});

// ESC key: dismiss exclude popover, close price update modal, or handle fullscreen tabs
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && activeExcludePopover) {
    dismissExcludePopover();
    return;
  }
  if (e.key === "Escape") {
    const priceModal = document.getElementById("price-update-modal");
    if (priceModal && priceModal.classList.contains("active")) {
      if (!priceUpdatesState.isUpdating) {
        e.preventDefault();
        hideUpdateConfirmation();
      }
      return;
    }
    if (document.getElementById("price-exit-confirm-overlay")) return;
    const results = document.getElementById("price-updates-results");
    if (results && results.classList.contains("results-fullscreen")) {
      e.preventDefault();
      if (priceFsHistoryState.active) {
        switchFullscreenTab("prices");
      } else {
        confirmExitPriceFullscreen();
      }
    }
  }
});

// Hide price description dropdown and exclude popover when clicking outside
document.addEventListener("click", (e) => {
  if (activeExcludePopover && !activeExcludePopover.contains(e.target) && !e.target.closest(".price-exclude-btn")) {
    dismissExcludePopover();
  }

  const descInput = document.getElementById("price-updates-desc-input");
  const dropdown = document.getElementById("price-updates-desc-dropdown");
  if (
    descInput &&
    dropdown &&
    !descInput.contains(e.target) &&
    !dropdown.contains(e.target)
  ) {
    hidePriceDescriptionDropdown();
  }

  const fsDescInput = document.getElementById("price-fs-desc-input");
  const fsDropdown = document.getElementById("price-fs-desc-dropdown");
  if (
    fsDescInput &&
    fsDropdown &&
    !fsDescInput.contains(e.target) &&
    !fsDropdown.contains(e.target)
  ) {
    hideFsDescriptionDropdown();
  }
});

// Dismiss exclude popover on scroll (fixed positioning detaches from button)
window.addEventListener("scroll", dismissExcludePopover, { capture: true });

// Price Updates config summary toggle
document
  .getElementById("price-updates-config-header")
  ?.addEventListener("click", (e) => {
    if (!e.target.closest("#edit-price-updates-config-btn")) {
      togglePriceUpdatesConfig();
    }
  });

// ==========================================
// Price Update History
// ==========================================

let priceHistoryState = {
  currentPage: 0,
  pageSize: parseInt(localStorage.getItem("priceHistoryPageSize")) || 25,
  totalRecords: 0,
  filters: {
    store_ids: null,
    upc_search: null,
    description_search: null,
    start_date: null,
    end_date: null,
  },
  visible: false,
  expandedBatches: new Set(),
};

// Set saved page size on the select
const phPageSizeEl = document.getElementById("price-history-page-size");
if (phPageSizeEl) phPageSizeEl.value = priceHistoryState.pageSize;

function togglePriceHistory(showHistory) {
  exitPriceFullscreen();
  priceHistoryState.visible = showHistory;
  const historySection = document.getElementById("price-history-section");
  const searchSection = document.getElementById("price-updates-search-section");
  const configSection = document.getElementById("price-updates-config-section");
  const mainBtn = document.getElementById("price-updates-main-view-btn");
  const histBtn = document.getElementById("price-updates-history-view-btn");

  if (showHistory) {
    historySection.style.display = "block";
    searchSection.style.display = "none";
    configSection.style.display = "none";
    mainBtn.classList.remove("active");
    histBtn.classList.add("active");
    loadPriceHistory();
  } else {
    historySection.style.display = "none";
    if (priceUpdatesState.config) {
      searchSection.style.display = "block";
    } else {
      configSection.style.display = "block";
    }
    mainBtn.classList.add("active");
    histBtn.classList.remove("active");
  }
}

async function loadPriceHistory() {
  if (priceHistoryState.preserveState) {
    priceHistoryState.preserveState = false;
    const resultsEl = document.getElementById("price-history-results");
    if (resultsEl) resultsEl.style.display = "block";
    return;
  }

  const loadingEl = document.getElementById("price-history-loading");
  const emptyEl = document.getElementById("price-history-empty");
  const resultsEl = document.getElementById("price-history-results");

  loadingEl.style.display = "block";
  emptyEl.style.display = "none";
  resultsEl.style.display = "none";

  try {
    const params = new URLSearchParams();
    params.append("limit", priceHistoryState.pageSize);
    params.append("offset", priceHistoryState.currentPage * priceHistoryState.pageSize);

    if (priceHistoryState.filters.store_ids) {
      params.append("store_ids", priceHistoryState.filters.store_ids);
    }
    if (priceHistoryState.filters.upc_search) {
      params.append("upc_search", priceHistoryState.filters.upc_search);
    }
    if (priceHistoryState.filters.description_search) {
      params.append("description_search", priceHistoryState.filters.description_search);
    }
    if (priceHistoryState.filters.start_date) {
      params.append("start_date", priceHistoryState.filters.start_date);
    }
    if (priceHistoryState.filters.end_date) {
      params.append("end_date", priceHistoryState.filters.end_date);
    }

    const data = await apiRequest(`/price-updates/history?${params.toString()}`);
    priceHistoryState.totalRecords = data.total;

    loadingEl.style.display = "none";

    if (data.batches.length === 0) {
      emptyEl.style.display = "block";
    } else {
      resultsEl.style.display = "block";
      displayPriceHistory(data.batches, data.total);
    }
  } catch (error) {
    loadingEl.style.display = "none";
    showToast(`Error loading price history: ${error.message}`, "error");
  }
}

async function loadPriceHistoryStores() {
  if (priceHistoryState.preserveState) return;

  try {
    const stores = await apiRequest("/stores");
    const config = priceUpdatesState.config;
    const configuredIds =
      config && config.storeIds
        ? new Set(config.storeIds.map(String))
        : null;
    const filtered = configuredIds
      ? stores.filter((s) => configuredIds.has(String(s.id)))
      : stores;
    const filtersEl = document.getElementById("price-history-store-filters");
    const chipStores = filtered.map((s) => ({
      id: String(s.id),
      name: s.name,
      type: s.store_type,
      hasRows: true,
    }));
    buildStoreFilterChips(filtersEl, chipStores, {
      localStorageKey: "priceActiveStores",
      onToggle: saveHistoryStoreSelections,
    });
  } catch (e) {
    // Silently fail
  }
}

function saveHistoryStoreSelections() {
  const activeIds = [];
  document.querySelectorAll("#price-history-store-filters .store-filter-chip.active").forEach((chip) => {
    if (chip.dataset.storeId) activeIds.push(chip.dataset.storeId);
  });
  localStorage.setItem("priceActiveStores", JSON.stringify(activeIds));
  if (priceHistoryState.visible) applyPriceHistoryFilters();
}

async function applyPriceHistoryFilters() {
  const activeStoreIds = [];
  document.querySelectorAll("#price-history-store-filters .store-filter-chip.active").forEach((chip) => {
    if (chip.dataset.storeId) activeStoreIds.push(chip.dataset.storeId);
  });
  const totalChips = document.querySelectorAll("#price-history-store-filters .store-filter-chip:not(.store-filter-control)").length;
  const upcSearch = document.getElementById("price-history-upc-filter").value;
  const descSearch = document.getElementById("price-history-desc-filter").value;
  const startDate = document.getElementById("price-history-start-date").value;
  const endDate = document.getElementById("price-history-end-date").value;

  priceHistoryState.filters = {
    store_ids: activeStoreIds.length > 0 && activeStoreIds.length < totalChips ? activeStoreIds.join(",") : null,
    upc_search: upcSearch || null,
    description_search: descSearch || null,
    start_date: startDate ? `${startDate}T00:00:00` : null,
    end_date: endDate ? `${endDate}T23:59:59` : null,
  };
  priceHistoryState.currentPage = 0;
  await loadPriceHistory();
}

function getActiveStoreIdsFromContainer(containerSelector) {
  const chips = document.querySelectorAll(`${containerSelector} .store-filter-chip:not(.store-filter-control)`);
  if (chips.length === 0) return null;
  const activeChips = document.querySelectorAll(`${containerSelector} .store-filter-chip.active`);
  if (activeChips.length === chips.length) return null;
  const ids = new Set();
  activeChips.forEach((chip) => {
    if (chip.dataset.storeId) ids.add(String(chip.dataset.storeId));
  });
  return ids;
}

function getActiveHistoryStoreIds() {
  return getActiveStoreIdsFromContainer("#price-history-store-filters");
}

const STORE_PALETTE_DARK = [
  "#4fc3f7", // sky blue
  "#ff8a65", // coral
  "#81c784", // green
  "#ce93d8", // lavender
  "#fff176", // yellow
  "#f48fb1", // pink
  "#4dd0e1", // teal
  "#a1887f", // taupe
  "#aed581", // lime
  "#ffb74d", // amber
  "#9fa8da", // periwinkle
  "#80cbc4", // mint
];

const STORE_PALETTE_LIGHT = [
  "#0277bd", // blue
  "#c62828", // red
  "#2e7d32", // green
  "#6a1b9a", // purple
  "#e65100", // orange
  "#00695c", // teal
  "#ad1457", // pink
  "#827717", // olive
  "#4527a0", // deep purple
  "#00838f", // cyan
  "#4e342e", // brown
  "#1565c0", // steel blue
];

function getStoreColor(storeId) {
  const isLight = document.body.getAttribute("data-theme") === "author-light";
  const palette = isLight ? STORE_PALETTE_LIGHT : STORE_PALETTE_DARK;
  const idx = ((storeId - 1) % palette.length + palette.length) % palette.length;
  return palette[idx];
}

function getStoreBgColor(storeId, intensity = "normal") {
  const hex = getStoreColor(storeId);
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const isLight = document.body.getAttribute("data-theme") === "author-light";
  const alpha = intensity === "strong" ? (isLight ? 0.12 : 0.1) : (isLight ? 0.07 : 0.05);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function displayPriceHistory(batches, total, targetConfig = null) {
  const cfg = targetConfig || {
    tbodyId: "price-history-table-body",
    totalCountId: "price-history-total-count",
    storeFilterSelector: "#price-history-store-filters",
    state: priceHistoryState,
    expandedBatches: priceHistoryState.expandedBatches,
  };

  const totalCountEl = cfg.totalCountId ? document.getElementById(cfg.totalCountId) : null;
  if (totalCountEl) totalCountEl.textContent = total;

  const tbody = document.getElementById(cfg.tbodyId);
  tbody.innerHTML = "";

  const activeStoreIdsFn = () => getActiveStoreIdsFromContainer(cfg.storeFilterSelector);

  batches.forEach((batch, index) => {
    const recordNumber = cfg.state.currentPage * cfg.state.pageSize + index + 1;

    const batchRow = document.createElement("tr");
    batchRow.style.cursor = "pointer";
    batchRow.style.backgroundColor = "var(--bg-secondary)";
    batchRow.dataset.batchId = batch.batch_id;

    // # cell with chevron
    const numCell = document.createElement("td");
    numCell.style.color = "var(--text-tertiary)";
    numCell.style.fontSize = "0.875rem";
    const chevron = document.createElement("span");
    chevron.className = "ph-chevron";
    numCell.appendChild(chevron);
    numCell.appendChild(document.createTextNode(recordNumber.toString()));
    batchRow.appendChild(numCell);

    // Timestamp — short date with full datetime tooltip
    const timestampCell = document.createElement("td");
    const date = new Date(batch.created_at);
    timestampCell.textContent = date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    timestampCell.title = date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    timestampCell.style.fontSize = "0.875rem";
    batchRow.appendChild(timestampCell);

    // UPC
    const upcCell = document.createElement("td");
    upcCell.style.fontFamily = "monospace";
    upcCell.style.fontSize = "0.875rem";
    upcCell.textContent = batch.upc;
    batchRow.appendChild(upcCell);

    // Product
    const productCell = document.createElement("td");
    productCell.style.fontSize = "0.875rem";
    productCell.style.color = "var(--text-primary)";
    productCell.textContent = batch.product_description || "-";
    batchRow.appendChild(productCell);

    // Filter entries by active store chips for summary calculations
    const activeStoreIds = activeStoreIdsFn();
    const filteredEntries = activeStoreIds
      ? batch.entries.filter((e) => activeStoreIds.has(String(e.store_id)))
      : batch.entries;

    // Change — net price direction badge (filtered by active stores)
    const changeCell = document.createElement("td");
    const priceChanges = filteredEntries
      .filter((e) => e.new_price != null && e.old_price != null)
      .map((e) => parseFloat(e.new_price) - parseFloat(e.old_price));
    if (priceChanges.length > 0) {
      const allPositive = priceChanges.every((c) => c > 0);
      const allNegative = priceChanges.every((c) => c < 0);
      const avgChange = priceChanges.reduce((a, b) => a + b, 0) / priceChanges.length;
      const badge = document.createElement("span");
      badge.className = "price-change-badge";
      if (allPositive) {
        badge.classList.add("increase");
        badge.textContent = `\u2191 +$${Math.abs(avgChange).toFixed(2)}`;
      } else if (allNegative) {
        badge.classList.add("decrease");
        badge.textContent = `\u2193 -$${Math.abs(avgChange).toFixed(2)}`;
      } else {
        badge.classList.add("mixed");
        badge.textContent = "\u2014";
      }
      changeCell.appendChild(badge);
    } else {
      changeCell.style.color = "var(--text-tertiary)";
      changeCell.textContent = "\u2014";
    }
    batchRow.appendChild(changeCell);

    // Updated — total rows_affected across filtered entries
    const updatedCell = document.createElement("td");
    const totalRowsAffected = filteredEntries.reduce((sum, e) => sum + (e.rows_affected || 0), 0);
    updatedCell.textContent = totalRowsAffected;
    updatedCell.style.fontWeight = "600";
    updatedCell.style.fontSize = "0.875rem";
    const filteredStoreCount = filteredEntries.length;
    updatedCell.title = `${totalRowsAffected} product${totalRowsAffected !== 1 ? "s" : ""} updated across ${filteredStoreCount} store${filteredStoreCount !== 1 ? "s" : ""}`;
    batchRow.appendChild(updatedCell);

    // Recall button
    const recallCell = document.createElement("td");
    recallCell.style.textAlign = "center";
    const recallBtn = document.createElement("button");
    recallBtn.type = "button";
    recallBtn.className = "ph-recall-btn";
    recallBtn.title = "Recall this update";
    recallBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>';
    recallBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      recallBatch(batch, cfg.storeFilterSelector);
    });
    recallCell.appendChild(recallBtn);
    batchRow.appendChild(recallCell);

    // Status — icon only with tooltip
    const statusCell = document.createElement("td");
    statusCell.style.textAlign = "center";
    const statusIcon = document.createElement("span");
    statusIcon.className = "ph-status-icon";
    if (batch.failed_stores === 0) {
      statusIcon.classList.add("success");
      statusIcon.textContent = "\u2713";
      statusIcon.title = `${batch.successful_stores}/${batch.total_stores} succeeded`;
    } else if (batch.successful_stores === 0) {
      statusIcon.classList.add("error");
      statusIcon.textContent = "\u2717";
      statusIcon.title = `0/${batch.total_stores} succeeded, ${batch.failed_stores} failed`;
    } else {
      statusIcon.classList.add("partial");
      statusIcon.textContent = "\u2713";
      statusIcon.title = `${batch.successful_stores}/${batch.total_stores} succeeded, ${batch.failed_stores} failed`;
    }
    statusCell.appendChild(statusIcon);
    batchRow.appendChild(statusCell);

    // Expand/collapse
    let isExpanded = cfg.expandedBatches?.has(batch.batch_id) || false;
    if (isExpanded) chevron.classList.add("expanded");
    batchRow.addEventListener("click", () => {
      isExpanded = !isExpanded;
      if (isExpanded) {
        cfg.expandedBatches?.add(batch.batch_id);
      } else {
        cfg.expandedBatches?.delete(batch.batch_id);
      }
      chevron.classList.toggle("expanded", isExpanded);
      const detailRows = tbody.querySelectorAll(`[data-batch-detail="${batch.batch_id}"]`);
      const storeIds = activeStoreIdsFn();
      detailRows.forEach((row) => {
        if (!isExpanded) {
          row.style.display = "none";
        } else {
          row.style.display = storeIds ? (storeIds.has(row.dataset.storeId) ? "" : "none") : "";
        }
      });
    });

    // Store filter visibility
    if (activeStoreIds) {
      const hasMatchingStore = batch.entries.some((entry) =>
        activeStoreIds.has(String(entry.store_id))
      );
      if (!hasMatchingStore) {
        batchRow.style.display = "none";
      }
    }

    tbody.appendChild(batchRow);

    // Detail rows
    batch.entries.forEach((entry) => {
      const detailRow = document.createElement("tr");
      if (isExpanded) {
        const storeIds = activeStoreIdsFn();
        detailRow.style.display = storeIds ? (storeIds.has(String(entry.store_id)) ? "" : "none") : "";
      } else {
        detailRow.style.display = "none";
      }
      detailRow.style.backgroundColor = "var(--bg-tertiary)";
      detailRow.dataset.batchDetail = batch.batch_id;
      detailRow.dataset.storeId = entry.store_id;

      // Price/cost changes spanning # + Timestamp columns
      const changeCell = document.createElement("td");
      changeCell.colSpan = 2;
      changeCell.style.fontSize = "0.8125rem";
      changeCell.style.overflow = "hidden";
      changeCell.style.textOverflow = "ellipsis";
      changeCell.style.whiteSpace = "nowrap";
      changeCell.style.maxWidth = "0";
      const changeParts = [];
      if (entry.new_price != null) {
        const oldP = entry.old_price != null ? `$${parseFloat(entry.old_price).toFixed(2)}` : "-";
        const newP = `$${parseFloat(entry.new_price).toFixed(2)}`;
        changeParts.push(
          `<span class="ph-change-label">Price:</span>` +
          `<span class="ph-change-old">${oldP}</span>` +
          `<span class="ph-change-arrow">\u2192</span>` +
          `<span class="ph-change-new">${newP}</span>`
        );
      }
      if (entry.new_cost != null) {
        const oldC = entry.old_cost != null ? `$${parseFloat(entry.old_cost).toFixed(2)}` : "-";
        const newC = `$${parseFloat(entry.new_cost).toFixed(2)}`;
        changeParts.push(
          `<span class="ph-change-label">Cost:</span>` +
          `<span class="ph-change-old">${oldC}</span>` +
          `<span class="ph-change-arrow">\u2192</span>` +
          `<span class="ph-change-new">${newC}</span>`
        );
      }
      if (entry.new_delivery_b != null) {
        const oldD = entry.old_delivery_b != null ? `$${parseFloat(entry.old_delivery_b).toFixed(2)}` : "-";
        const newD = `$${parseFloat(entry.new_delivery_b).toFixed(2)}`;
        changeParts.push(
          `<span class="ph-change-label">Delivery B:</span>` +
          `<span class="ph-change-old">${oldD}</span>` +
          `<span class="ph-change-arrow">\u2192</span>` +
          `<span class="ph-change-new">${newD}</span>`
        );
      }
      if (entry.new_list_price != null) {
        const oldL = entry.old_list_price != null ? `$${parseFloat(entry.old_list_price).toFixed(2)}` : "-";
        const newL = `$${parseFloat(entry.new_list_price).toFixed(2)}`;
        changeParts.push(
          `<span class="ph-change-label">List Price:</span>` +
          `<span class="ph-change-old">${oldL}</span>` +
          `<span class="ph-change-arrow">\u2192</span>` +
          `<span class="ph-change-new">${newL}</span>`
        );
      }
      changeCell.innerHTML = changeParts.length > 0
        ? changeParts.join('<span style="margin: 0 0.5rem; color: var(--text-tertiary)">|</span>')
        : "-";
      detailRow.appendChild(changeCell);

      // Barcode (under UPC column)
      const upcCell = document.createElement("td");
      upcCell.style.fontFamily = "monospace";
      upcCell.style.fontSize = "0.8125rem";
      upcCell.style.color = "var(--text-secondary)";
      upcCell.textContent = entry.variant_barcode || entry.upc || "";
      detailRow.appendChild(upcCell);

      // Store name + product description + variant (under Product column)
      const descCell = document.createElement("td");
      descCell.style.fontSize = "0.875rem";
      descCell.style.color = "var(--text-primary)";
      const storeSpan = document.createElement("span");
      storeSpan.style.color = getStoreColor(entry.store_id);
      storeSpan.style.fontWeight = "600";
      storeSpan.textContent = entry.store_name;
      descCell.appendChild(storeSpan);
      if (entry.is_mirror) {
        const mirrorBadge = document.createElement("span");
        mirrorBadge.style.fontSize = "0.625rem";
        mirrorBadge.style.marginLeft = "0.375rem";
        mirrorBadge.style.padding = "0.125rem 0.375rem";
        mirrorBadge.style.borderRadius = "var(--radius-sm)";
        mirrorBadge.style.background = "color-mix(in srgb, var(--accent-primary) 15%, transparent)";
        mirrorBadge.style.color = "var(--accent-primary)";
        mirrorBadge.style.fontWeight = "500";
        mirrorBadge.textContent = "mirrored";
        if (entry.mirror_source_store_name) {
          mirrorBadge.title = `Mirrored from ${entry.mirror_source_store_name}`;
        }
        descCell.appendChild(mirrorBadge);
      }
      if (entry.product_description) {
        descCell.appendChild(document.createTextNode(" \u2014 " + entry.product_description));
        const variantTitle = entry.variant_title;
        if (variantTitle && variantTitle.toLowerCase() !== "default title") {
          const variantSpan = document.createElement("span");
          variantSpan.style.color = "var(--text-tertiary)";
          variantSpan.style.fontSize = "0.75rem";
          variantSpan.style.marginLeft = "0.375rem";
          variantSpan.textContent = `(${variantTitle})`;
          descCell.appendChild(variantSpan);
        }
      }
      detailRow.appendChild(descCell);

      // Detail change cell (under Change column)
      const detailChangeCell = document.createElement("td");
      if (entry.new_price != null && entry.old_price != null) {
        const diff = parseFloat(entry.new_price) - parseFloat(entry.old_price);
        const detailBadge = document.createElement("span");
        detailBadge.className = "price-change-badge";
        if (diff > 0) {
          detailBadge.classList.add("increase");
          detailBadge.textContent = `+$${diff.toFixed(2)}`;
        } else if (diff < 0) {
          detailBadge.classList.add("decrease");
          detailBadge.textContent = `-$${Math.abs(diff).toFixed(2)}`;
        } else {
          detailBadge.classList.add("mixed");
          detailBadge.textContent = "$0.00";
        }
        detailChangeCell.appendChild(detailBadge);
      }
      detailRow.appendChild(detailChangeCell);

      // Rows affected (under Updated column)
      const rowsCell = document.createElement("td");
      rowsCell.style.fontSize = "0.8125rem";
      rowsCell.textContent = entry.success ? (entry.rows_affected || 0) : "-";
      detailRow.appendChild(rowsCell);

      // Empty recall column placeholder
      detailRow.appendChild(document.createElement("td"));

      // Status icon (under Status column)
      const detailStatusCell = document.createElement("td");
      detailStatusCell.style.textAlign = "center";
      const detailIcon = document.createElement("span");
      detailIcon.className = "ph-status-icon";
      if (entry.success) {
        detailIcon.classList.add("success");
        detailIcon.textContent = "\u2713";
        detailIcon.title = `${entry.rows_affected || 0} row${(entry.rows_affected || 0) !== 1 ? "s" : ""} affected`;
      } else {
        detailIcon.classList.add("error");
        detailIcon.textContent = "\u2717";
        detailIcon.title = entry.error_message || "Failed";
      }
      detailStatusCell.appendChild(detailIcon);
      detailRow.appendChild(detailStatusCell);

      tbody.appendChild(detailRow);
    });
  });

  updatePriceHistoryPagination(total, targetConfig);
}

function updatePriceHistoryPagination(total, targetConfig = null) {
  const cfg = targetConfig || {
    state: priceHistoryState,
    pageInfoId: "price-history-page-info",
    prevBtnId: "price-history-prev-btn",
    nextBtnId: "price-history-next-btn",
  };
  const pageInfoId = cfg.pageInfoId || "price-history-page-info";
  const prevBtnId = cfg.prevBtnId || "price-history-prev-btn";
  const nextBtnId = cfg.nextBtnId || "price-history-next-btn";
  const state = cfg.state || priceHistoryState;

  const totalPages = Math.ceil(total / state.pageSize);
  const currentPage = state.currentPage + 1;

  document.getElementById(pageInfoId).textContent =
    `Page ${currentPage} of ${totalPages || 1}`;

  document.getElementById(prevBtnId).disabled = state.currentPage === 0;
  document.getElementById(nextBtnId).disabled = currentPage >= totalPages;
}

function recallBatch(batch, storeFilterSelector) {
  const config = priceUpdatesState.config;
  if (!config || !config.storeIds || config.storeIds.length === 0) {
    showToast("Configure stores before recalling", "error");
    return;
  }
  if (priceUpdatesState.isSearching || priceUpdatesState.isUpdating) return;

  const historyActiveIds = getActiveStoreIdsFromContainer(storeFilterSelector);
  const configStoreSet = new Set(config.storeIds.map(String));
  const batchStoreIds = new Set(batch.entries.map((e) => String(e.store_id)));

  const filteredIds = [...batchStoreIds].filter((id) => {
    if (!configStoreSet.has(id)) return false;
    if (historyActiveIds && !historyActiveIds.has(id)) return false;
    return true;
  });

  if (filteredIds.length === 0) {
    showToast("No matching stores between history and configured stores", "error");
    return;
  }

  priceUpdatesState.recallData = {
    upc: batch.upc,
    entries: batch.entries,
    storeIds: filteredIds,
  };

  const isFullscreen = priceFsHistoryState.active;
  if (isFullscreen) {
    priceFsHistoryState.preserveState = true;
    switchFullscreenTab("prices");
  } else {
    priceHistoryState.preserveState = true;
    togglePriceHistory(false);
  }

  document.getElementById("price-updates-upc-input").value = batch.upc;

  const distinctBarcodes = new Set(
    batch.entries.map((e) => e.variant_barcode || e.upc).filter(Boolean)
  );
  const hasSiblings = distinctBarcodes.size > 1;
  if (hasSiblings) {
    const siblingsCheckbox = document.getElementById("price-updates-include-siblings");
    if (siblingsCheckbox) siblingsCheckbox.checked = true;
  }

  localStorage.setItem("priceActiveStores", JSON.stringify(filteredIds));

  const savedStoreIds = config.storeIds;
  config.storeIds = filteredIds.map(Number);
  searchPriceUpdates().finally(() => {
    config.storeIds = savedStoreIds;
  });
}

function applyRecallData() {
  if (!priceUpdatesState.recallData) return;
  const { entries } = priceUpdatesState.recallData;
  const rows = document.querySelectorAll("#price-updates-tbody tr:not(.store-header-row)");

  entries.forEach((entry) => {
    let matchedRow = null;
    const entryBarcode = entry.variant_barcode || entry.upc || "";
    rows.forEach((tr) => {
      if (matchedRow) return;
      if (String(tr.dataset.storeId) !== String(entry.store_id)) return;
      if (entry.variant_id && tr.dataset.variantId) {
        if (String(tr.dataset.variantId) === String(entry.variant_id)) matchedRow = tr;
      } else if (tr.dataset.barcode && entryBarcode) {
        if (tr.dataset.barcode === entryBarcode) matchedRow = tr;
      }
    });
    if (!matchedRow) return;

    const priceInput = matchedRow.querySelector(".new-price");
    const costInput = matchedRow.querySelector(".new-cost");
    const deliveryBInput = matchedRow.querySelector(".new-delivery-b");
    const listPriceInput = matchedRow.querySelector(".new-list-price");

    if (priceInput && entry.new_price != null) priceInput.value = parseFloat(entry.new_price).toFixed(2);
    if (costInput && entry.new_cost != null) costInput.value = parseFloat(entry.new_cost).toFixed(2);
    if (deliveryBInput && entry.new_delivery_b != null) deliveryBInput.value = parseFloat(entry.new_delivery_b).toFixed(2);
    if (listPriceInput && entry.new_list_price != null) listPriceInput.value = parseFloat(entry.new_list_price).toFixed(2);

    matchedRow.classList.add("filled-row");
    recalculateRowMarkup(matchedRow);
  });

  priceUpdatesState.recallData = null;
}

// Price History event listeners
document
  .getElementById("price-updates-main-view-btn")
  ?.addEventListener("click", () => togglePriceHistory(false));
document
  .getElementById("price-updates-history-view-btn")
  ?.addEventListener("click", () => {
    loadPriceHistoryStores();
    togglePriceHistory(true);
  });

// Auto-apply filters with debounce for text inputs
function debouncedHistoryFilter() {
  clearTimeout(priceUpdatesState.historyFilterTimeout);
  priceUpdatesState.historyFilterTimeout = setTimeout(() => {
    if (priceHistoryState.visible) applyPriceHistoryFilters();
  }, 400);
}

document
  .getElementById("price-history-upc-filter")
  ?.addEventListener("input", debouncedHistoryFilter);
document
  .getElementById("price-history-desc-filter")
  ?.addEventListener("input", debouncedHistoryFilter);
document
  .getElementById("price-history-start-date")
  ?.addEventListener("change", () => {
    if (priceHistoryState.visible) applyPriceHistoryFilters();
  });
document
  .getElementById("price-history-end-date")
  ?.addEventListener("change", () => {
    if (priceHistoryState.visible) applyPriceHistoryFilters();
  });

document
  .getElementById("clear-price-history-filters-btn")
  ?.addEventListener("click", async () => {
    document.querySelectorAll("#price-history-store-filters .store-filter-chip:not(.store-filter-control)").forEach((c) => {
      c.classList.add("active");
      c.classList.remove("not-found");
    });
    localStorage.setItem("priceActiveStores", JSON.stringify([]));
    document.getElementById("price-history-upc-filter").value = "";
    document.getElementById("price-history-desc-filter").value = "";
    document.getElementById("price-history-start-date").value = "";
    document.getElementById("price-history-end-date").value = "";
    await applyPriceHistoryFilters();
  });

document
  .getElementById("price-history-prev-btn")
  ?.addEventListener("click", async () => {
    if (priceHistoryState.currentPage > 0) {
      priceHistoryState.currentPage--;
      await loadPriceHistory();
    }
  });

document
  .getElementById("price-history-next-btn")
  ?.addEventListener("click", async () => {
    const totalPages = Math.ceil(priceHistoryState.totalRecords / priceHistoryState.pageSize);
    if (priceHistoryState.currentPage < totalPages - 1) {
      priceHistoryState.currentPage++;
      await loadPriceHistory();
    }
  });

document
  .getElementById("price-history-page-size")
  ?.addEventListener("change", async (e) => {
    priceHistoryState.pageSize = parseInt(e.target.value, 10);
    localStorage.setItem("priceHistoryPageSize", priceHistoryState.pageSize);
    priceHistoryState.currentPage = 0;
    await loadPriceHistory();
  });

// ==========================================
// Fullscreen History Tab
// ==========================================

let priceFsHistoryState = {
  currentPage: 0,
  pageSize: parseInt(localStorage.getItem("priceFsHistoryPageSize")) || 25,
  totalRecords: 0,
  filters: { store_ids: null },
  active: false,
  expandedBatches: new Set(),
};

const fsHistPageSizeEl = document.getElementById("price-fs-history-page-size");
if (fsHistPageSizeEl) fsHistPageSizeEl.value = priceFsHistoryState.pageSize;

const FS_HISTORY_CONFIG = {
  tbodyId: "price-fs-history-tbody",
  totalCountId: null,
  storeFilterSelector: "#price-fs-history-store-filters",
  state: priceFsHistoryState,
  pageInfoId: "price-fs-history-page-info",
  prevBtnId: "price-fs-history-prev-btn",
  nextBtnId: "price-fs-history-next-btn",
  expandedBatches: priceFsHistoryState.expandedBatches,
};

function switchFullscreenTab(tab) {
  const pricesTab = document.getElementById("price-fs-tab-prices");
  const historyTab = document.getElementById("price-fs-tab-history");
  const historyPanel = document.getElementById("price-fs-history-panel");
  const stickyBarInfo = document.getElementById("price-sticky-bar-info");
  const fsSearch = document.getElementById("price-fs-search");

  const priceElements = document.querySelectorAll(
    ".fill-all-row, .price-table-scroll, .price-update-btn-row, #price-filter-zone"
  );

  if (tab === "history") {
    priceFsHistoryState.active = true;
    priceElements.forEach((el) => el.classList.add("price-fs-hidden"));
    if (stickyBarInfo) stickyBarInfo.classList.add("price-fs-hidden");
    if (fsSearch) fsSearch.classList.add("price-fs-hidden");
    if (historyPanel) historyPanel.classList.add("price-fs-visible");
    if (pricesTab) pricesTab.classList.remove("active");
    if (historyTab) historyTab.classList.add("active");
    loadFullscreenHistoryStores();
    loadFullscreenHistory();
  } else {
    priceFsHistoryState.active = false;
    priceElements.forEach((el) => el.classList.remove("price-fs-hidden"));
    if (stickyBarInfo) stickyBarInfo.classList.remove("price-fs-hidden");
    if (fsSearch) fsSearch.classList.remove("price-fs-hidden");
    if (historyPanel) historyPanel.classList.remove("price-fs-visible");
    if (pricesTab) pricesTab.classList.add("active");
    if (historyTab) historyTab.classList.remove("active");
  }
}

async function loadFullscreenHistory() {
  if (priceFsHistoryState.preserveState) {
    priceFsHistoryState.preserveState = false;
    return;
  }

  const tbody = document.getElementById("price-fs-history-tbody");
  if (tbody) tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--text-tertiary)">Loading...</td></tr>';

  try {
    const params = new URLSearchParams();
    params.append("limit", priceFsHistoryState.pageSize);
    params.append("offset", priceFsHistoryState.currentPage * priceFsHistoryState.pageSize);

    if (priceFsHistoryState.filters.store_ids) {
      params.append("store_ids", priceFsHistoryState.filters.store_ids);
    }

    const data = await apiRequest(`/price-updates/history?${params.toString()}`);
    priceFsHistoryState.totalRecords = data.total;

    if (data.batches.length === 0) {
      if (tbody) tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--text-tertiary)">No history found</td></tr>';
      updatePriceHistoryPagination(0, FS_HISTORY_CONFIG);
    } else {
      displayPriceHistory(data.batches, data.total, FS_HISTORY_CONFIG);
    }
  } catch (error) {
    if (tbody) tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--danger)">Error loading history</td></tr>';
    showToast(`Error loading history: ${error.message}`, "error");
  }
}

async function loadFullscreenHistoryStores() {
  if (priceFsHistoryState.preserveState) return;

  try {
    const stores = await apiRequest("/stores");
    const filtersEl = document.getElementById("price-fs-history-store-filters");
    const chipStores = stores.map((s) => ({
      id: String(s.id),
      name: s.name,
      type: s.store_type,
      hasRows: true,
    }));
    buildStoreFilterChips(filtersEl, chipStores, {
      localStorageKey: "priceFsActiveStores",
      onToggle: saveFsHistoryStoreSelections,
    });
  } catch (e) {
    // Silently fail
  }
}

function saveFsHistoryStoreSelections() {
  const activeIds = [];
  document.querySelectorAll("#price-fs-history-store-filters .store-filter-chip.active").forEach((chip) => {
    if (chip.dataset.storeId) activeIds.push(chip.dataset.storeId);
  });
  localStorage.setItem("priceFsActiveStores", JSON.stringify(activeIds));
  applyFsHistoryFilters();
}

async function applyFsHistoryFilters() {
  const activeStoreIds = [];
  document.querySelectorAll("#price-fs-history-store-filters .store-filter-chip.active").forEach((chip) => {
    if (chip.dataset.storeId) activeStoreIds.push(chip.dataset.storeId);
  });
  const totalChips = document.querySelectorAll("#price-fs-history-store-filters .store-filter-chip:not(.store-filter-control)").length;

  priceFsHistoryState.filters = {
    store_ids: activeStoreIds.length > 0 && activeStoreIds.length < totalChips ? activeStoreIds.join(",") : null,
  };
  priceFsHistoryState.currentPage = 0;
  await loadFullscreenHistory();
}

// Fullscreen tab event listeners
document
  .getElementById("price-fs-tab-prices")
  ?.addEventListener("click", () => switchFullscreenTab("prices"));
document
  .getElementById("price-fs-tab-history")
  ?.addEventListener("click", () => switchFullscreenTab("history"));

document
  .getElementById("price-fs-history-prev-btn")
  ?.addEventListener("click", async () => {
    if (priceFsHistoryState.currentPage > 0) {
      priceFsHistoryState.currentPage--;
      await loadFullscreenHistory();
    }
  });

document
  .getElementById("price-fs-history-next-btn")
  ?.addEventListener("click", async () => {
    const totalPages = Math.ceil(priceFsHistoryState.totalRecords / priceFsHistoryState.pageSize);
    if (priceFsHistoryState.currentPage < totalPages - 1) {
      priceFsHistoryState.currentPage++;
      await loadFullscreenHistory();
    }
  });

document
  .getElementById("price-fs-history-page-size")
  ?.addEventListener("change", async (e) => {
    priceFsHistoryState.pageSize = parseInt(e.target.value, 10);
    localStorage.setItem("priceFsHistoryPageSize", priceFsHistoryState.pageSize);
    priceFsHistoryState.currentPage = 0;
    await loadFullscreenHistory();
  });

// ===== Shopify Sales =====

let shopifySalesResults = null;

async function loadShopifySalesPage() {
  const container = document.getElementById("shopify-sales-store-checkboxes");
  const fetchBtn = document.getElementById("shopify-sales-fetch-btn");
  container.innerHTML = "";
  fetchBtn.disabled = true;
  document.getElementById("shopify-sales-progress").style.display = "none";
  document.getElementById("shopify-sales-results").style.display = "none";
  document.getElementById("shopify-sales-empty").style.display = "none";

  try {
    const stores = await apiRequest("/stores");
    const shopifyStores = stores.filter(
      (s) => s.store_type === "shopify" && s.is_active,
    );

    if (shopifyStores.length === 0) {
      container.innerHTML =
        '<span style="color: var(--text-tertiary); font-size: 0.8125rem;">No active Shopify stores configured</span>';
      return;
    }

    shopifyStores.forEach((store) => {
      const label = document.createElement("label");
      label.style.display = "flex";
      label.style.alignItems = "center";
      label.style.gap = "0.5rem";
      label.style.cursor = "pointer";
      label.style.whiteSpace = "nowrap";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = store.id;
      checkbox.className = "shopify-sales-store-cb";
      checkbox.style.width = "auto";
      checkbox.style.margin = "0";

      const span = document.createElement("span");
      span.textContent = store.name;

      label.appendChild(checkbox);
      label.appendChild(span);
      container.appendChild(label);
    });

    updateShopifySalesFetchBtn();
  } catch (error) {
    console.error("Error loading Shopify stores:", error);
  }
}

function updateShopifySalesFetchBtn() {
  const checked = document.querySelectorAll(
    ".shopify-sales-store-cb:checked",
  ).length;
  const startDate = document.getElementById("shopify-sales-start-date").value;
  const endDate = document.getElementById("shopify-sales-end-date").value;
  document.getElementById("shopify-sales-fetch-btn").disabled =
    checked === 0 || !startDate || !endDate;
}

document
  .getElementById("shopify-sales-store-checkboxes")
  ?.addEventListener("change", updateShopifySalesFetchBtn);

document
  .getElementById("shopify-sales-start-date")
  ?.addEventListener("change", updateShopifySalesFetchBtn);

document
  .getElementById("shopify-sales-end-date")
  ?.addEventListener("change", updateShopifySalesFetchBtn);

document.getElementById("shopify-sales-select-all")?.addEventListener("click", () => {
  document.querySelectorAll(".shopify-sales-store-cb").forEach((cb) => (cb.checked = true));
  updateShopifySalesFetchBtn();
});

document.getElementById("shopify-sales-deselect-all")?.addEventListener("click", () => {
  document.querySelectorAll(".shopify-sales-store-cb").forEach((cb) => (cb.checked = false));
  updateShopifySalesFetchBtn();
});

document.querySelectorAll("[data-range]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const range = btn.dataset.range;
    const today = new Date();
    let start, end;

    if (range === "this-month") {
      start = new Date(today.getFullYear(), today.getMonth(), 1);
      end = today;
    } else if (range === "last-month") {
      start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      end = new Date(today.getFullYear(), today.getMonth(), 0);
    } else {
      const days = parseInt(range, 10);
      start = new Date(today);
      start.setDate(today.getDate() - days);
      end = today;
    }

    document.getElementById("shopify-sales-start-date").value = start
      .toISOString()
      .split("T")[0];
    document.getElementById("shopify-sales-end-date").value = end
      .toISOString()
      .split("T")[0];
    updateShopifySalesFetchBtn();
  });
});

document.getElementById("shopify-sales-fetch-btn")?.addEventListener("click", fetchShopifySales);

async function fetchShopifySales() {
  const fetchBtn = document.getElementById("shopify-sales-fetch-btn");
  const progressEl = document.getElementById("shopify-sales-progress");
  const progressBar = document.getElementById("shopify-sales-progress-bar");
  const progressStatus = document.getElementById("shopify-sales-progress-status");
  const progressItems = document.getElementById("shopify-sales-progress-items");
  const resultsEl = document.getElementById("shopify-sales-results");
  const emptyEl = document.getElementById("shopify-sales-empty");

  const storeIds = Array.from(
    document.querySelectorAll(".shopify-sales-store-cb:checked"),
  ).map((cb) => parseInt(cb.value, 10));
  const startDate = document.getElementById("shopify-sales-start-date").value;
  const endDate = document.getElementById("shopify-sales-end-date").value;

  if (storeIds.length === 0 || !startDate || !endDate) return;

  fetchBtn.disabled = true;
  fetchBtn.textContent = "Fetching...";
  progressEl.style.display = "block";
  progressBar.style.width = "0%";
  progressStatus.textContent = "Connecting to stores...";
  progressItems.innerHTML = "";
  resultsEl.style.display = "none";
  emptyEl.style.display = "none";
  shopifySalesResults = null;

  const storeItemMap = new Map();

  try {
    const response = await fetch(`${API_BASE}/shopify-sales/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        store_ids: storeIds,
        start_date: startDate,
        end_date: endDate,
      }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const messages = buffer.split("\n\n");
      buffer = messages.pop();

      for (const msg of messages) {
        if (!msg.trim()) continue;

        const eventMatch = msg.match(/event: (\w+)\ndata: (.+)/s);
        if (!eventMatch) continue;

        const [, eventType, dataStr] = eventMatch;
        const data = JSON.parse(dataStr);

        if (eventType === "progress") {
          if (data.status === "started") {
            progressStatus.textContent = `Fetching orders from ${data.total_stores} store(s)...`;
          } else if (data.status === "searching_store") {
            const item = document.createElement("div");
            item.style.cssText = "display: flex; align-items: center; gap: 0.5rem;";
            item.innerHTML = `<span style="color: var(--accent-primary); animation: pulse 1.5s ease-in-out infinite;">&#9679;</span> <span>${escapeHtml(data.store_name)} — fetching orders...</span>`;
            storeItemMap.set(data.store_name, item);
            progressItems.appendChild(item);
          } else if (data.status === "completed_store") {
            const pct = Math.round((data.completed / data.total_stores) * 100);
            progressBar.style.width = `${pct}%`;
            progressStatus.textContent = `${data.completed} of ${data.total_stores} store(s) complete...`;

            const existing = storeItemMap.get(data.store_name);
            if (existing) {
              existing.style.cssText = "display: flex; align-items: center; gap: 0.5rem;";
              existing.innerHTML = `<span style="color: var(--success);">&#10003;</span> <span>${escapeHtml(data.store_name)} &mdash; ${data.orders_found} orders, ${data.line_items} line items</span>`;
            }
          } else if (data.status === "error_store") {
            const pct = Math.round((data.completed / data.total_stores) * 100);
            progressBar.style.width = `${pct}%`;
            progressStatus.textContent = `${data.completed} of ${data.total_stores} store(s) complete...`;

            const existing = storeItemMap.get(data.store_name);
            if (existing) {
              existing.style.cssText = "display: flex; align-items: center; gap: 0.5rem;";
              existing.innerHTML = `<span style="color: var(--danger);">&#10007;</span> <span>${escapeHtml(data.store_name)} &mdash; ${escapeHtml(data.message)}</span>`;
            }
          } else if (data.status === "aggregating") {
            progressBar.style.width = "100%";
            progressStatus.textContent = "Aggregating results...";
          }
        } else if (eventType === "complete") {
          progressStatus.textContent = "Done!";
          shopifySalesResults = data;
          displayShopifySalesResults(data);
        } else if (eventType === "error") {
          progressStatus.textContent = "Error";
          const item = document.createElement("div");
          item.style.color = "var(--danger)";
          item.textContent = data.message || "Unknown error";
          progressItems.appendChild(item);
        }
      }
    }
  } catch (error) {
    console.error("Shopify sales fetch error:", error);
    progressStatus.textContent = "Error";
    const item = document.createElement("div");
    item.style.color = "var(--danger)";
    item.textContent = `Error: ${error.message}`;
    progressItems.appendChild(item);
  } finally {
    fetchBtn.disabled = false;
    fetchBtn.textContent = "Fetch Sales";
  }
}

let shopifySalesSortColumn = "total_revenue";
let shopifySalesSortDirection = "desc";

const shopifySalesNumericColumns = new Set(["cost", "avg_price", "total_quantity", "total_revenue"]);

function sortShopifySalesResults(results) {
  const col = shopifySalesSortColumn;
  const dir = shopifySalesSortDirection === "asc" ? 1 : -1;
  const isNumeric = shopifySalesNumericColumns.has(col);

  return [...results].sort((a, b) => {
    let av = a[col];
    let bv = b[col];
    if (isNumeric) {
      av = av != null ? parseFloat(av) : -Infinity;
      bv = bv != null ? parseFloat(bv) : -Infinity;
      return (av - bv) * dir;
    }
    av = (av || "").toLowerCase();
    bv = (bv || "").toLowerCase();
    return av < bv ? -dir : av > bv ? dir : 0;
  });
}

function updateShopifySalesSortIndicators() {
  const table = document.getElementById("shopify-sales-table");
  if (!table) return;
  table.querySelectorAll("th[data-sort]").forEach((th) => {
    const indicator = th.querySelector(".sort-indicator");
    if (!indicator) return;
    if (th.dataset.sort === shopifySalesSortColumn) {
      indicator.textContent = shopifySalesSortDirection === "asc" ? "▲" : "▼";
      indicator.style.opacity = "1";
    } else {
      indicator.textContent = "";
      indicator.style.opacity = "0.3";
    }
  });
}

document.getElementById("shopify-sales-table")?.addEventListener("click", (e) => {
  const th = e.target.closest("th[data-sort]");
  if (!th) return;
  const col = th.dataset.sort;
  if (shopifySalesSortColumn === col) {
    shopifySalesSortDirection = shopifySalesSortDirection === "asc" ? "desc" : "asc";
  } else {
    shopifySalesSortColumn = col;
    shopifySalesSortDirection = shopifySalesNumericColumns.has(col) ? "desc" : "asc";
  }
  if (shopifySalesResults) displayShopifySalesResults(shopifySalesResults);
});

function displayShopifySalesResults(data) {
  const resultsEl = document.getElementById("shopify-sales-results");
  const emptyEl = document.getElementById("shopify-sales-empty");
  const tbody = document.getElementById("shopify-sales-tbody");
  const tfoot = document.getElementById("shopify-sales-tfoot");
  const summaryEl = document.getElementById("shopify-sales-summary");

  const results = data.results || [];
  const summary = data.summary || {};

  if (results.length === 0) {
    emptyEl.style.display = "block";
    resultsEl.style.display = "none";
    return;
  }

  const shippingVal = parseFloat(summary.total_shipping || 0);
  const shippingPart = shippingVal > 0 ? ` · $${shippingVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} shipping` : "";
  let summaryHtml = `<div>${summary.total_items} products · ${summary.total_quantity?.toLocaleString()} units sold · $${parseFloat(summary.total_revenue || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} total revenue${shippingPart} · ${summary.stores_searched} store(s) · ${summary.date_range?.start} to ${summary.date_range?.end}</div>`;

  const excludedProducts = summary.excluded_products || [];
  if (excludedProducts.length > 0) {
    const exclRev = parseFloat(summary.excluded_total_revenue || 0);
    const exclQty = summary.excluded_total_quantity || 0;
    let exclRows = excludedProducts.map(p => `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:0.8125rem;"><span>${escapeHtml(p.product_title)}</span><span>${p.quantity.toLocaleString()} units · $${parseFloat(p.revenue).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span></div>`).join("");
    summaryHtml += `<div style="margin-top:6px;padding:6px 10px;border-left:3px solid var(--warning, #f9ab00);background:var(--bg-tertiary, rgba(255,255,255,0.04));border-radius:4px;font-size:0.85rem;">Excluded: ${excludedProducts.length} product(s) · ${exclQty.toLocaleString()} units · $${exclRev.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} revenue <a href="#" id="toggle-excluded-details" style="margin-left:8px;font-size:0.8rem;">[show]</a><div id="excluded-details" style="display:none;margin-top:4px;padding-top:4px;border-top:1px solid var(--border-color, rgba(255,255,255,0.1));">${exclRows}</div></div>`;
  }

  summaryEl.innerHTML = summaryHtml;

  const toggleLink = document.getElementById("toggle-excluded-details");
  if (toggleLink) {
    toggleLink.addEventListener("click", (e) => {
      e.preventDefault();
      const details = document.getElementById("excluded-details");
      if (details.style.display === "none") {
        details.style.display = "block";
        toggleLink.textContent = "[hide]";
      } else {
        details.style.display = "none";
        toggleLink.textContent = "[show]";
      }
    });
  }

  const sorted = sortShopifySalesResults(results);

  tbody.innerHTML = "";
  sorted.forEach((r) => {
    const tr = document.createElement("tr");
    const productDisplay = r.variant_title ? `${r.product_title} - ${r.variant_title}` : r.product_title;
    tr.innerHTML = `
      <td>${escapeHtml(productDisplay)}</td>
      <td style="font-family: monospace; font-size: 0.8125rem;">${escapeHtml(r.barcode || "")}</td>
      <td style="font-size: 0.8125rem;">${escapeHtml(r.sku || "")}</td>
      <td style="text-align: right;">${r.cost != null ? "$" + parseFloat(r.cost).toFixed(2) : "\u2014"}</td>
      <td style="text-align: right;">$${parseFloat(r.avg_price).toFixed(2)}</td>
      <td style="text-align: right;">${r.total_quantity.toLocaleString()}</td>
      <td style="text-align: right;">$${parseFloat(r.total_revenue).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
    `;
    tbody.appendChild(tr);
  });

  const totalQty = results.reduce((s, r) => s + r.total_quantity, 0);
  const totalRev = results.reduce((s, r) => s + parseFloat(r.total_revenue), 0);
  const avgAll = totalQty > 0 ? (totalRev / totalQty).toFixed(2) : "0.00";
  document.getElementById("shopify-sales-total-avg").textContent = `$${avgAll}`;
  document.getElementById("shopify-sales-total-qty").textContent = totalQty.toLocaleString();
  document.getElementById("shopify-sales-total-rev").textContent = `$${totalRev.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  tfoot.style.display = "";

  updateShopifySalesSortIndicators();
  resultsEl.style.display = "block";
}

document.getElementById("shopify-sales-export-btn")?.addEventListener("click", exportShopifySalesToExcel);

function exportShopifySalesToExcel() {
  if (!shopifySalesResults || !shopifySalesResults.results || shopifySalesResults.results.length === 0) return;

  const headers = ["Product", "UPC", "SKU", "Cost", "Avg Price", "Qty", "Revenue"];
  const dataRows = shopifySalesResults.results.map((r) => [
    r.variant_title ? `${r.product_title} - ${r.variant_title}` : (r.product_title || ""),
    r.barcode || "",
    r.sku || "",
    r.cost != null ? parseFloat(r.cost) : null,
    parseFloat(r.avg_price),
    r.total_quantity,
    parseFloat(r.total_revenue),
  ]);

  const totalQty = shopifySalesResults.results.reduce((s, r) => s + r.total_quantity, 0);
  const totalRev = shopifySalesResults.results.reduce((s, r) => s + parseFloat(r.total_revenue), 0);
  const totalsRow = ["", "", "", "Totals", "", totalQty, totalRev];

  const extraRows = [];
  const summary = shopifySalesResults.summary || {};
  const shippingTotal = parseFloat(summary.total_shipping || 0);
  if (shippingTotal > 0) {
    extraRows.push(["", "", "", "Shipping Collected", "", "", shippingTotal]);
  }
  const excludedProducts = summary.excluded_products || [];
  if (excludedProducts.length > 0) {
    const exclRev = parseFloat(summary.excluded_total_revenue || 0);
    const exclQty = summary.excluded_total_quantity || 0;
    extraRows.push(["", "", "", "Excluded Products", "", exclQty, exclRev]);
    excludedProducts.forEach((p) => {
      extraRows.push([p.product_title, "", "", "", "", p.quantity, parseFloat(p.revenue)]);
    });
  }

  const wsData = [headers, ...dataRows, totalsRow, ...extraRows];
  const ws = XLSX.utils.aoa_to_sheet(wsData);

  const colWidths = [55, 16, 16, 10, 12, 10, 14];
  ws["!cols"] = colWidths.map((w) => ({ wch: w }));

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Shopify Sales");

  const startDate = document.getElementById("shopify-sales-start-date").value;
  const endDate = document.getElementById("shopify-sales-end-date").value;
  XLSX.writeFile(wb, `shopify-sales-${startDate}-to-${endDate}.xlsx`);
}

// ===== End Shopify Sales =====

// ===== Sales Report =====

const SALES_COLUMNS = [
  { key: "upc",            label: "UPC",         soldOnly: false, baseWidth: 10, align: "left",  thStyle: "",                    tdStyle: "font-family: monospace; font-size: 0.8125rem",                                                                      hasFilter: true },
  { key: "description",    label: "Description", soldOnly: false, baseWidth: 25, align: "left",  thStyle: "",                    tdStyle: "font-size: 0.8125rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap",                               hasFilter: true },
  { key: "subcategory",    label: "Subcategory", soldOnly: false, baseWidth: 12, align: "left",  thStyle: "",                    tdStyle: "font-size: 0.8125rem; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap", hasFilter: true },
  { key: "bin_location",   label: "Bin",         soldOnly: false, baseWidth: 8,  align: "left",  thStyle: "",                    tdStyle: "font-size: 0.8125rem",                                                                                              hasFilter: false },
  { key: "reorder_level",  label: "Reorder",     soldOnly: false, baseWidth: 6,  align: "right", thStyle: "text-align: right;",  tdStyle: "text-align: right; font-size: 0.8125rem",                                                                           hasFilter: true },
  { key: "quant_on_hand",  label: "On Hand",     soldOnly: false, baseWidth: 7,  align: "right", thStyle: "text-align: right;",  tdStyle: "text-align: right; font-size: 0.8125rem",                                                                           hasFilter: false },
  { key: "total_sold",     label: "Sold",        soldOnly: true,  baseWidth: 6,  align: "right", thStyle: "text-align: right;",  tdStyle: "text-align: right; font-size: 0.8125rem",                                                                           hasFilter: false },
  { key: "total_returned", label: "Returns",     soldOnly: true,  baseWidth: 6,  align: "right", thStyle: "text-align: right;",  tdStyle: "text-align: right; font-size: 0.8125rem; color: var(--warning)",                                                    hasFilter: false },
  { key: "net_sold",       label: "Net Sold",    soldOnly: true,  baseWidth: 7,  align: "right", thStyle: "text-align: right;",  tdStyle: "text-align: right; font-size: 0.8125rem; font-weight: 600",                                                         hasFilter: false },
];

function getVisibleColumns(isSold) {
  const cols = SALES_COLUMNS.filter(col => {
    if (col.soldOnly && !isSold) return false;
    return !salesState.hiddenColumns.includes(col.key);
  });
  const totalBase = cols.reduce((s, c) => s + c.baseWidth, 0);
  const target = 98;
  cols.forEach(col => {
    col.width = ((col.baseWidth / totalBase) * target).toFixed(1) + "%";
  });
  return cols;
}

function buildColumnTogglePills() {
  const container = document.getElementById("sales-column-pills");
  if (!container) return;
  container.innerHTML = "";
  SALES_COLUMNS.forEach(col => {
    const isVisible = !salesState.hiddenColumns.includes(col.key);
    const label = document.createElement("label");
    label.style.cssText = `display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; cursor: pointer; padding: 0.2rem 0.5rem; border-radius: 1rem; border: 1px solid var(--border-color); background: ${isVisible ? "var(--bg-tertiary, rgba(255,255,255,0.08))" : "transparent"}; white-space: nowrap; opacity: ${isVisible ? "1" : "0.5"}; transition: opacity 0.15s, background 0.15s;`;
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = isVisible;
    cb.style.cssText = "margin: 0; cursor: pointer;";
    cb.onchange = () => toggleSalesColumn(col.key);
    label.appendChild(cb);
    label.appendChild(document.createTextNode(col.label));
    container.appendChild(label);
  });
}

function toggleSalesColumn(key) {
  const idx = salesState.hiddenColumns.indexOf(key);
  if (idx >= 0) {
    salesState.hiddenColumns.splice(idx, 1);
  } else {
    const visibleCount = SALES_COLUMNS.filter(c => !salesState.hiddenColumns.includes(c.key)).length;
    if (visibleCount <= 1) {
      showToast("At least one column must remain visible", "warning");
      buildColumnTogglePills();
      return;
    }
    salesState.hiddenColumns.push(key);
  }
  localStorage.setItem("sales_hidden_columns", JSON.stringify(salesState.hiddenColumns));
  buildColumnTogglePills();
  const filterRow = document.getElementById("sales-table-filters");
  if (filterRow) filterRow.dataset.viewKey = "";
  renderSalesTable();
}

function resetSalesColumns() {
  salesState.hiddenColumns = [];
  localStorage.removeItem("sales_hidden_columns");
  buildColumnTogglePills();
  const filterRow = document.getElementById("sales-table-filters");
  if (filterRow) filterRow.dataset.viewKey = "";
  renderSalesTable();
}

let salesState = {
  isLoading: false,
  allProducts: [],
  filteredProducts: [],
  viewMode: "sold",
  sortColumn: "net_sold",
  sortDirection: "desc",
  currentPage: 0,
  pageSize: parseInt(localStorage.getItem("sales_page_size") || "100"),
  summary: null,
  stores: [],
  config: null,
  configExpanded: false,
  allMssqlStores: [],
  allShopifyStores: [],
  subcategories: [],
  selectedSubcategories: [],
  excludedSubcategories: [],
  exclSearchTimeout: null,
  upcFilter: "",
  descFilter: "",
  selectedReorderLevels: [],
  binsFilter: "",
  hiddenColumns: JSON.parse(localStorage.getItem("sales_hidden_columns") || "[]"),
};

async function loadSalesPage() {
  document.getElementById("sales-config-bar").style.display = "none";
  document.getElementById("sales-config-setup").style.display = "none";
  document.getElementById("sales-controls").style.display = "none";
  document.getElementById("sales-results").style.display = "none";
  document.getElementById("sales-progress").style.display = "none";
  document.getElementById("sales-empty").style.display = "none";

  try {
    const [config, allStores] = await Promise.all([
      apiRequest("/sales/config"),
      apiRequest("/stores"),
    ]);

    salesState.allMssqlStores = allStores.filter((s) => s.store_type === "mssql" && s.is_active);
    salesState.allShopifyStores = allStores.filter((s) => s.store_type === "shopify" && s.is_active);

    if (!config || !config.s2s_store_id) {
      populateSalesConfigForm(null);
      buildColumnTogglePills();
      document.getElementById("sales-config-setup").style.display = "block";
      document.getElementById("sales-config-cancel-btn").style.display = "none";
      return;
    }

    salesState.config = config;
    salesState.excludedSubcategories = config.excluded_subcategories || [];
    updateSalesConfigBar(config);
    document.getElementById("sales-config-bar").style.display = "block";
    document.getElementById("sales-controls").style.display = "block";

    const savedFrom = localStorage.getItem("sales_date_from");
    const savedTo = localStorage.getItem("sales_date_to");
    if (savedFrom && savedTo) {
      document.getElementById("sales-date-from").value = savedFrom;
      document.getElementById("sales-date-to").value = savedTo;
    } else if (!document.getElementById("sales-date-from").value) {
      setSalesDatePreset("30d");
    }
  } catch (e) {
    populateSalesConfigForm(null);
    buildColumnTogglePills();
    document.getElementById("sales-config-setup").style.display = "block";
  }
}

function updateSalesConfigBar(config) {
  const s2sName = config.s2s_store_name || "Unknown";
  const mssqlNames = (config.mssql_store_names || []).join(", ") || "None";
  const shopifyNames = (config.shopify_store_names || []).join(", ") || "None";

  document.getElementById("sales-config-label").innerHTML =
    `Database Config: <strong style="color: var(--text-primary)">${s2sName}</strong>`;
  document.getElementById("sales-config-mssql-info").innerHTML =
    `MSSQL Sales Stores: <strong style="color: var(--text-primary)">${mssqlNames}</strong>`;
  document.getElementById("sales-config-shopify-info").innerHTML =
    `Shopify Stores: <strong style="color: var(--text-primary)">${shopifyNames}</strong>`;
  buildColumnTogglePills();
}

function toggleSalesConfig() {
  salesState.configExpanded = !salesState.configExpanded;
  const details = document.getElementById("sales-config-details");
  const toggle = document.getElementById("sales-config-toggle");
  if (salesState.configExpanded) {
    details.style.display = "block";
    toggle.style.transform = "rotate(90deg)";
  } else {
    details.style.display = "none";
    toggle.style.transform = "rotate(0deg)";
  }
}

function populateSalesConfigForm(config) {
  const s2sSelect = document.getElementById("sales-s2s-select");
  s2sSelect.innerHTML = '<option value="">Select primary database...</option>';
  salesState.allMssqlStores.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name;
    if (config && config.s2s_store_id === s.id) opt.selected = true;
    s2sSelect.appendChild(opt);
  });

  const mssqlContainer = document.getElementById("sales-mssql-checkboxes");
  mssqlContainer.innerHTML = "";
  const selectedMssql = config ? (config.mssql_store_ids || []) : [];
  salesState.allMssqlStores.forEach((s) => {
    const label = document.createElement("label");
    label.style.cssText = "display: inline-flex; align-items: center; gap: 0.375rem; font-size: 0.8125rem; cursor: pointer; padding: 0.25rem 0.625rem; border-radius: 1rem; border: 1px solid var(--border-color); background: var(--bg-tertiary); white-space: nowrap;";
    const checked = selectedMssql.includes(s.id) ? "checked" : "";
    label.innerHTML = `<input type="checkbox" class="sales-cfg-mssql-cb" value="${s.id}" ${checked}> ${s.name}`;
    mssqlContainer.appendChild(label);
  });

  const shopifyContainer = document.getElementById("sales-shopify-checkboxes");
  shopifyContainer.innerHTML = "";
  const selectedShopify = config ? (config.shopify_store_ids || []) : [];
  const shopifyGroup = document.getElementById("sales-shopify-config-group");
  if (salesState.allShopifyStores.length > 0) {
    shopifyGroup.style.display = "block";
    salesState.allShopifyStores.forEach((s) => {
      const label = document.createElement("label");
      label.style.cssText = "display: inline-flex; align-items: center; gap: 0.375rem; font-size: 0.8125rem; cursor: pointer; padding: 0.25rem 0.625rem; border-radius: 1rem; border: 1px solid var(--border-color); background: var(--bg-tertiary); white-space: nowrap;";
      const checked = selectedShopify.includes(s.id) ? "checked" : "";
      label.innerHTML = `<input type="checkbox" class="sales-cfg-shopify-cb" value="${s.id}" ${checked}> ${s.name}`;
      shopifyContainer.appendChild(label);
    });
  } else {
    shopifyGroup.style.display = "none";
  }
}

function openSalesConfigEdit() {
  populateSalesConfigForm(salesState.config);
  buildColumnTogglePills();
  document.getElementById("sales-config-setup").style.display = "block";
  document.getElementById("sales-config-cancel-btn").style.display = "inline-flex";
}

function cancelSalesConfigEdit() {
  document.getElementById("sales-config-setup").style.display = "none";
}

async function saveSalesConfig() {
  const s2sId = parseInt(document.getElementById("sales-s2s-select").value);
  if (!s2sId) {
    showToast("Please select a primary database", "warning");
    return;
  }

  const mssqlIds = Array.from(document.querySelectorAll(".sales-cfg-mssql-cb:checked")).map((cb) => parseInt(cb.value));
  const shopifyIds = Array.from(document.querySelectorAll(".sales-cfg-shopify-cb:checked")).map((cb) => parseInt(cb.value));

  try {
    const config = await apiRequest("/sales/config", {
      method: "POST",
      body: JSON.stringify({ s2s_store_id: s2sId, mssql_store_ids: mssqlIds, shopify_store_ids: shopifyIds }),
    });

    salesState.config = config;
    salesState.excludedSubcategories = config.excluded_subcategories || [];
    updateSalesConfigBar(config);
    document.getElementById("sales-config-setup").style.display = "none";
    document.getElementById("sales-config-bar").style.display = "block";
    document.getElementById("sales-controls").style.display = "block";

    if (!document.getElementById("sales-date-from").value) {
      setSalesDatePreset("30d");
    }

    showToast("Sales configuration saved", "success");
  } catch (e) {
    showToast(e.message || "Failed to save configuration", "error");
  }
}

function setSalesDatePreset(preset) {
  const now = new Date();
  let from, to;

  switch (preset) {
    case "7d":
      from = new Date(now);
      from.setDate(from.getDate() - 7);
      to = now;
      break;
    case "30d":
      from = new Date(now);
      from.setDate(from.getDate() - 30);
      to = now;
      break;
    case "thisMonth":
      from = new Date(now.getFullYear(), now.getMonth(), 1);
      to = now;
      break;
    case "lastMonth":
      from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      to = new Date(now.getFullYear(), now.getMonth(), 0);
      break;
    case "thisYear":
      from = new Date(now.getFullYear(), 0, 1);
      to = now;
      break;
    case "lastYear":
      from = new Date(now.getFullYear() - 1, 0, 1);
      to = new Date(now.getFullYear() - 1, 11, 31);
      break;
  }

  const fromStr = from.toISOString().split("T")[0];
  const toStr = to.toISOString().split("T")[0];
  document.getElementById("sales-date-from").value = fromStr;
  document.getElementById("sales-date-to").value = toStr;
  localStorage.setItem("sales_date_from", fromStr);
  localStorage.setItem("sales_date_to", toStr);
}

async function fetchSalesReport() {
  if (salesState.isLoading) return;

  const config = salesState.config;
  if (!config || !config.s2s_store_id) {
    showToast("Please configure databases first", "warning");
    return;
  }

  const mssqlStoreIds = config.mssql_store_ids || [];
  const shopifyStoreIds = config.shopify_store_ids || [];
  const dateFrom = document.getElementById("sales-date-from").value || null;
  const dateTo = document.getElementById("sales-date-to").value || null;

  if (mssqlStoreIds.length === 0 && shopifyStoreIds.length === 0) {
    showToast("Please configure at least one sales store", "warning");
    return;
  }

  salesState.isLoading = true;
  const btn = document.getElementById("sales-generate-btn");
  btn.disabled = true;
  btn.textContent = "Generating...";

  document.getElementById("sales-results").style.display = "none";
  document.getElementById("sales-empty").style.display = "none";
  document.getElementById("sales-progress").style.display = "block";
  const progressList = document.getElementById("sales-progress-list");
  progressList.innerHTML = "";

  try {
    const response = await fetch(`${API_BASE}/sales/report/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mssql_store_ids: mssqlStoreIds,
        shopify_store_ids: shopifyStoreIds,
        date_from: dateFrom,
        date_to: dateTo,
      }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.substring(6));
            handleSalesProgress(data, progressList);
          } catch (e) {
            // skip malformed
          }
        }
      }
    }
  } catch (e) {
    addSalesProgressItem(progressList, `Error: ${e.message}`, "var(--danger)");
  } finally {
    salesState.isLoading = false;
    btn.disabled = false;
    btn.textContent = "Generate Report";
  }
}

function handleSalesProgress(data, progressList) {
  if (data.message && !data.status) {
    addSalesProgressItem(progressList, data.message, "var(--danger)");
    return;
  }

  switch (data.status) {
    case "fetching_products":
      addSalesProgressItem(progressList, "Fetching active products from primary database...", "var(--text-secondary)");
      break;
    case "products_fetched":
      addSalesProgressItem(progressList, `Found ${data.count.toLocaleString()} active products`, "var(--success)");
      break;
    case "searching_store":
      addSalesProgressItem(progressList, `Searching ${data.store_name} (${data.store_type})...`, "var(--text-secondary)");
      break;
    case "completed_store":
      addSalesProgressItem(progressList, `${data.store_name}: ${data.products_found.toLocaleString()} products with sales (${data.completed}/${data.total_stores})`, "var(--success)");
      break;
    case "error_store":
      addSalesProgressItem(progressList, `${data.store_name}: ${data.message}`, "var(--danger)");
      break;
    case "merging":
      addSalesProgressItem(progressList, "Merging results...", "var(--text-secondary)");
      break;
  }

  if (data.products) {
    document.getElementById("sales-progress").style.display = "none";
    if (data.products.length === 0) {
      document.getElementById("sales-empty").style.display = "block";
    } else {
      displaySalesResults(data);
    }
  }
}

function addSalesProgressItem(container, text, color) {
  const li = document.createElement("li");
  li.style.cssText = `padding: 0.25rem 0; color: ${color};`;
  li.textContent = text;
  container.appendChild(li);
}

function displaySalesResults(data) {
  salesState.allProducts = data.products;
  salesState.summary = data.summary;
  salesState.stores = data.stores || [];
  salesState.allSubcategories = data.subcategories || [];
  salesState.subcategories = data.subcategories || [];
  salesState.selectedSubcategories = [];

  const summary = data.summary;
  document.querySelector('.sales-toggle-btn[data-view="sold"]').textContent = `Sold (${summary.sold_count.toLocaleString()})`;
  document.querySelector('.sales-toggle-btn[data-view="not-sold"]').textContent = `Not Sold (${summary.not_sold_count.toLocaleString()})`;
  document.querySelector('.sales-toggle-btn[data-view="all"]').textContent = `All (${summary.total_products.toLocaleString()})`;

  const savedView = localStorage.getItem("sales_view_mode");
  salesState.viewMode = savedView || "all";
  salesState.sortColumn = salesState.viewMode === "sold" ? "net_sold" : "description";
  salesState.sortDirection = salesState.viewMode === "sold" ? "desc" : "asc";
  salesState.currentPage = 0;

  document.querySelectorAll(".sales-toggle-btn").forEach((b) => b.classList.remove("active"));
  document.querySelector(`.sales-toggle-btn[data-view="${salesState.viewMode}"]`).classList.add("active");

  salesState.upcFilter = localStorage.getItem("sales_filter_upc") || "";
  salesState.descFilter = localStorage.getItem("sales_filter_desc") || "";

  const savedReorder = JSON.parse(localStorage.getItem("sales_filter_reorder") || "[]");
  if (savedReorder.length > 0) {
    salesState.selectedReorderLevels = savedReorder;
  }

  const savedSubcats = JSON.parse(localStorage.getItem("sales_filter_subcategories") || "[]");
  if (savedSubcats.length > 0 && savedSubcats.length < (data.subcategories || []).length) {
    salesState.selectedSubcategories = savedSubcats.filter((s) => (data.subcategories || []).includes(s));
  }

  applySalesFilters();

  const instockEl = document.getElementById("sales-filter-instock");
  const binsEl = document.getElementById("sales-filter-bins");
  if (instockEl) instockEl.checked = localStorage.getItem("sales_filter_instock") === "1";
  const savedBins = localStorage.getItem("sales_filter_bins") || "";
  salesState.binsFilter = savedBins;
  if (binsEl) binsEl.value = savedBins;

  applySalesFilters();
  document.getElementById("sales-results").style.display = "block";
}

function toggleSalesView(mode) {
  salesState.viewMode = mode;
  salesState.currentPage = 0;
  localStorage.setItem("sales_view_mode", mode);

  if (mode === "sold" || mode === "all") {
    salesState.sortColumn = "net_sold";
    salesState.sortDirection = "desc";
  } else {
    salesState.sortColumn = "description";
    salesState.sortDirection = "asc";
  }

  document.querySelectorAll(".sales-toggle-btn").forEach((b) => b.classList.remove("active"));
  document.querySelector(`.sales-toggle-btn[data-view="${mode}"]`).classList.add("active");

  applySalesFilters();
}

function applySalesFilters() {
  const upcEl = document.getElementById("sales-filter-upc");
  const descEl = document.getElementById("sales-filter-desc");
  const upcFilter = upcEl ? upcEl.value.toLowerCase().trim() : (salesState.upcFilter || "");
  const descFilter = descEl ? descEl.value.toLowerCase().trim() : (salesState.descFilter || "");
  const subcatFilters = salesState.selectedSubcategories || [];
  const reorderFilters = salesState.selectedReorderLevels || [];
  const instockEl = document.getElementById("sales-filter-instock");
  const binsEl = document.getElementById("sales-filter-bins");
  const instockOnly = instockEl ? instockEl.checked : false;
  const binsFilter = binsEl ? binsEl.value : (salesState.binsFilter || "");

  salesState.upcFilter = upcFilter;
  salesState.descFilter = descFilter;
  salesState.binsFilter = binsFilter;

  localStorage.setItem("sales_filter_upc", upcFilter);
  localStorage.setItem("sales_filter_desc", descFilter);
  localStorage.setItem("sales_filter_reorder", JSON.stringify(reorderFilters));
  localStorage.setItem("sales_filter_subcategories", JSON.stringify(subcatFilters));
  localStorage.setItem("sales_filter_instock", instockOnly ? "1" : "0");
  localStorage.setItem("sales_filter_bins", binsFilter);

  const allReorderLevels = [...new Set(salesState.allProducts.map(p => p.reorder_level || 0))];
  const reorderActive = reorderFilters.length > 0 && reorderFilters.length < allReorderLevels.length;

  const matchesFilters = (p) => {
    if (upcFilter && !p.upc.toLowerCase().includes(upcFilter)) return false;
    if (descFilter && !p.description.toLowerCase().includes(descFilter)) return false;
    if (subcatFilters.length > 0 && !subcatFilters.includes(p.subcategory || "")) return false;
    if (reorderActive && !reorderFilters.includes(p.reorder_level || 0)) return false;
    return true;
  };

  let filtered = salesState.allProducts.filter((p) => {
    if (salesState.viewMode === "sold" && p.net_sold <= 0) return false;
    if (salesState.viewMode === "not-sold" && p.net_sold > 0) return false;
    if (instockOnly && p.quant_on_hand <= 0) return false;
    if (binsFilter === "no-bins" && p.bin_location) return false;
    if (binsFilter === "bins-only" && !p.bin_location) return false;
    return matchesFilters(p);
  });

  salesState.filteredProducts = filtered;
  sortSalesProducts();
  salesState.currentPage = 0;

  const soldCount = salesState.allProducts.filter((p) => {
    if (p.net_sold <= 0) return false;
    return matchesFilters(p);
  }).length;
  const notSoldCount = salesState.allProducts.filter((p) => {
    if (p.net_sold > 0) return false;
    return matchesFilters(p);
  }).length;
  document.querySelector('.sales-toggle-btn[data-view="sold"]').textContent = `Sold (${soldCount.toLocaleString()})`;
  document.querySelector('.sales-toggle-btn[data-view="not-sold"]').textContent = `Not Sold (${notSoldCount.toLocaleString()})`;
  document.querySelector('.sales-toggle-btn[data-view="all"]').textContent = `All (${(soldCount + notSoldCount).toLocaleString()})`;

  renderSalesTable();
}

function clearSalesFilters() {
  salesState.upcFilter = "";
  salesState.descFilter = "";
  salesState.binsFilter = "";
  const upcEl = document.getElementById("sales-filter-upc");
  const descEl = document.getElementById("sales-filter-desc");
  if (upcEl) upcEl.value = "";
  if (descEl) descEl.value = "";
  salesState.selectedSubcategories = [...(salesState.subcategories || [])];
  document.querySelectorAll(".sales-subcat-cb").forEach((cb) => (cb.checked = true));
  updateSubcatLabel();
  const reorderLevels = [...new Set(salesState.allProducts.map(p => p.reorder_level || 0))].sort((a, b) => a - b);
  salesState.selectedReorderLevels = [...reorderLevels];
  document.querySelectorAll(".sales-reorder-cb").forEach((cb) => (cb.checked = true));
  updateReorderLabel();
  const instockEl = document.getElementById("sales-filter-instock");
  const binsEl = document.getElementById("sales-filter-bins");
  if (instockEl) instockEl.checked = false;
  if (binsEl) binsEl.value = "";
  localStorage.removeItem("sales_filter_upc");
  localStorage.removeItem("sales_filter_desc");
  localStorage.removeItem("sales_filter_reorder");
  localStorage.removeItem("sales_filter_subcategories");
  localStorage.removeItem("sales_filter_instock");
  localStorage.removeItem("sales_filter_bins");
  localStorage.removeItem("sales_filter_nobins");
  applySalesFilters();
}

function sortSalesProducts() {
  const col = salesState.sortColumn;
  const dir = salesState.sortDirection === "asc" ? 1 : -1;

  salesState.filteredProducts.sort((a, b) => {
    let va = a[col];
    let vb = b[col];
    if (typeof va === "string" || typeof vb === "string") {
      return (va || "").localeCompare(vb || "") * dir;
    }
    return ((va || 0) - (vb || 0)) * dir;
  });
}

function handleSalesSort(column) {
  if (salesState.sortColumn === column) {
    salesState.sortDirection = salesState.sortDirection === "asc" ? "desc" : "asc";
  } else {
    salesState.sortColumn = column;
    salesState.sortDirection = column === "description" || column === "upc" ? "asc" : "desc";
  }
  sortSalesProducts();
  salesState.currentPage = 0;
  renderSalesTable();
}

function renderSalesTable() {
  const isSold = salesState.viewMode === "sold" || salesState.viewMode === "all";
  const thead = document.getElementById("sales-table-head");
  const filterRow = document.getElementById("sales-table-filters");
  const tbody = document.getElementById("sales-table-body");
  const tfoot = document.getElementById("sales-table-foot");
  const visibleCols = getVisibleColumns(isSold);

  const sortIcon = (col) => {
    if (salesState.sortColumn !== col) return "";
    return salesState.sortDirection === "asc" ? " ▲" : " ▼";
  };
  const sortStyle = 'cursor: pointer; user-select: none;';

  let headHtml = `<th style="width: 20px; text-align: center">#</th>`;
  visibleCols.forEach(col => {
    const widthStyle = col.width ? `width: ${col.width};` : "";
    headHtml += `<th style="${widthStyle} ${col.thStyle} ${sortStyle}" onclick="handleSalesSort('${col.key}')">${col.label}${sortIcon(col.key)}</th>`;
  });
  thead.innerHTML = headHtml;

  // Build filter row — only rebuild when view mode or visible columns change
  const filterCacheKey = `${isSold ? "sold" : "not-sold"}|${salesState.hiddenColumns.join(",")}`;
  if (filterRow.dataset.viewKey !== filterCacheKey) {
    filterRow.dataset.viewKey = filterCacheKey;

    const subcatTrigger = `<div id="sales-subcat-trigger" onclick="toggleSubcatDropdown()" class="dark-input" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; padding: 0.2rem 0.4rem; user-select: none;">
      <span id="sales-subcat-label" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">All</span>
      <span style="font-size: 0.5rem; color: var(--text-tertiary);">▼</span>
    </div>
    <div id="sales-subcat-dropdown" style="display: none; position: fixed; z-index: 100; max-height: 500px; overflow-y: auto; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-md); box-shadow: var(--shadow-md); min-width: 280px;"></div>`;

    const reorderTrigger = `<div id="sales-reorder-trigger" onclick="toggleReorderDropdown()" class="dark-input" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; padding: 0.2rem 0.4rem; user-select: none;">
      <span id="sales-reorder-label" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">All</span>
      <span style="font-size: 0.5rem; color: var(--text-tertiary);">▼</span>
    </div>
    <div id="sales-reorder-dropdown" style="display: none; position: fixed; z-index: 100; max-height: 500px; overflow-y: auto; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-md); box-shadow: var(--shadow-md); min-width: 180px;"></div>`;

    let filterHtml = `<td style="width: 20px;"></td>`;
    visibleCols.forEach(col => {
      const w = col.width ? `width: ${col.width};` : "";
      if (col.key === "upc") {
        filterHtml += `<td style="${w}"><input type="text" id="sales-filter-upc" class="dark-input" placeholder="Filter..." oninput="applySalesFilters()"></td>`;
      } else if (col.key === "description") {
        filterHtml += `<td style="${w}"><input type="text" id="sales-filter-desc" class="dark-input" placeholder="Filter..." oninput="applySalesFilters()"></td>`;
      } else if (col.key === "subcategory") {
        filterHtml += `<td style="${w}">${subcatTrigger}</td>`;
      } else if (col.key === "reorder_level") {
        filterHtml += `<td style="${w}">${reorderTrigger}</td>`;
      } else if (col.key === "bin_location") {
        filterHtml += `<td style="${w}"><select id="sales-filter-bins" class="dark-input" onchange="applySalesFilters()" style="font-size: 0.75rem; padding: 0.2rem 0.3rem;"><option value="">All</option><option value="no-bins">No Bins</option><option value="bins-only">Bins Only</option></select></td>`;
      } else if (col.key === "quant_on_hand") {
        filterHtml += `<td style="${w}"><label style="display: flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; cursor: pointer; white-space: nowrap;"><input type="checkbox" id="sales-filter-instock" onchange="applySalesFilters()"> In Stock</label></td>`;
      } else {
        filterHtml += `<td style="${w}"></td>`;
      }
    });
    filterRow.innerHTML = filterHtml;

    // Restore filter input values from state
    const upcEl = document.getElementById("sales-filter-upc");
    const descEl = document.getElementById("sales-filter-desc");
    if (upcEl) upcEl.value = salesState.upcFilter || "";
    if (descEl) descEl.value = salesState.descFilter || "";

    // Rebuild subcategory dropdown, preserving any saved selections
    const savedSubcats = salesState.selectedSubcategories ? [...salesState.selectedSubcategories] : [];
    buildSubcatDropdown(salesState.allSubcategories || salesState.subcategories || []);
    if (savedSubcats.length > 0 && savedSubcats.length < (salesState.subcategories || []).length) {
      salesState.selectedSubcategories = savedSubcats.filter(s => (salesState.subcategories || []).includes(s));
      document.querySelectorAll(".sales-subcat-cb").forEach(cb => {
        cb.checked = salesState.selectedSubcategories.includes(cb.value);
      });
    }
    updateSubcatLabel();

    // Build reorder dropdown, preserving any saved selections
    const reorderLevels = [...new Set(salesState.allProducts.map(p => p.reorder_level || 0))].sort((a, b) => a - b);
    const savedReorders = salesState.selectedReorderLevels.length > 0 ? [...salesState.selectedReorderLevels] : [];
    buildReorderDropdown(reorderLevels);
    if (savedReorders.length > 0 && savedReorders.length < reorderLevels.length) {
      salesState.selectedReorderLevels = savedReorders.filter(v => reorderLevels.includes(v));
      document.querySelectorAll(".sales-reorder-cb").forEach(cb => {
        cb.checked = salesState.selectedReorderLevels.includes(Number(cb.value));
      });
    }
    updateReorderLabel();

    // Restore bins dropdown
    const binsEl = document.getElementById("sales-filter-bins");
    if (binsEl) binsEl.value = salesState.binsFilter || "";
  } else {
    // Update reorder dropdown options without full rebuild (dataset may have changed)
    const reorderLevels = [...new Set(salesState.allProducts.map(p => p.reorder_level || 0))].sort((a, b) => a - b);
    const currentSelected = salesState.selectedReorderLevels;
    buildReorderDropdown(reorderLevels);
    if (currentSelected.length > 0 && currentSelected.length < reorderLevels.length) {
      salesState.selectedReorderLevels = currentSelected.filter(v => reorderLevels.includes(v));
      document.querySelectorAll(".sales-reorder-cb").forEach(cb => {
        cb.checked = salesState.selectedReorderLevels.includes(Number(cb.value));
      });
    }
    updateReorderLabel();
  }

  const start = salesState.currentPage * salesState.pageSize;
  const end = Math.min(start + salesState.pageSize, salesState.filteredProducts.length);
  const pageData = salesState.filteredProducts.slice(start, end);

  tbody.innerHTML = "";
  pageData.forEach((p, i) => {
    const row = document.createElement("tr");
    let cellsHtml = `<td style="text-align: center; color: var(--text-tertiary); font-size: 0.75rem">${start + i + 1}</td>`;
    visibleCols.forEach(col => {
      const raw = col.key === "subcategory" ? (p.subcategory || "") :
                  col.key === "bin_location" ? (p.bin_location || "") :
                  col.key === "reorder_level" ? (p.reorder_level || 0) :
                  p[col.key];
      const display = typeof raw === "number" ? raw.toLocaleString() : raw;
      const titleAttr = (col.key === "description" || col.key === "subcategory" || col.key === "bin_location") ? ` title="${raw}"` : "";
      cellsHtml += `<td style="${col.tdStyle}"${titleAttr}>${display}</td>`;
    });
    row.innerHTML = cellsHtml;
    tbody.appendChild(row);
  });

  tfoot.innerHTML = "";
  if (isSold && pageData.length > 0) {
    const totalSold = salesState.filteredProducts.reduce((s, p) => s + p.total_sold, 0);
    const totalReturned = salesState.filteredProducts.reduce((s, p) => s + p.total_returned, 0);
    const totalNet = salesState.filteredProducts.reduce((s, p) => s + p.net_sold, 0);
    const totalsMap = { total_sold: totalSold, total_returned: totalReturned, net_sold: totalNet };
    const hasDesc = visibleCols.some(c => c.key === "description");

    let footHtml = `<td></td>`;
    let labelPlaced = false;
    visibleCols.forEach((col, idx) => {
      if (col.key === "description") {
        footHtml += `<td style="font-size: 0.8125rem">Totals</td>`;
        labelPlaced = true;
      } else if (!labelPlaced && !hasDesc && idx === 0) {
        footHtml += `<td style="font-size: 0.8125rem">Totals</td>`;
        labelPlaced = true;
      } else if (totalsMap[col.key] !== undefined) {
        const colorStyle = col.key === "total_returned" ? " color: var(--warning);" : "";
        footHtml += `<td style="text-align: right; font-size: 0.8125rem;${colorStyle}">${totalsMap[col.key].toLocaleString()}</td>`;
      } else {
        footHtml += `<td></td>`;
      }
    });
    tfoot.innerHTML = `<tr style="font-weight: 700; border-top: 2px solid var(--border-color);">${footHtml}</tr>`;
  }

  const total = salesState.filteredProducts.length;
  const totalPages = Math.max(1, Math.ceil(total / salesState.pageSize));
  document.getElementById("sales-total-records").textContent = `${total.toLocaleString()} records`;
  document.getElementById("sales-page-info").textContent = `Page ${salesState.currentPage + 1} of ${totalPages}`;
  document.getElementById("sales-prev-page").disabled = salesState.currentPage === 0;
  document.getElementById("sales-next-page").disabled = salesState.currentPage >= totalPages - 1;
  const viewLabel = salesState.viewMode === "sold" ? "products sold" : salesState.viewMode === "not-sold" ? "products not sold" : "products";
  document.getElementById("sales-results-count").textContent = `Showing ${start + 1}-${end} of ${total.toLocaleString()} ${viewLabel}`;
  document.getElementById("sales-page-size").value = salesState.pageSize;
}

function changeSalesPage(delta) {
  const totalPages = Math.ceil(salesState.filteredProducts.length / salesState.pageSize);
  const newPage = salesState.currentPage + delta;
  if (newPage >= 0 && newPage < totalPages) {
    salesState.currentPage = newPage;
    renderSalesTable();
  }
}

function changeSalesPageSize() {
  salesState.pageSize = parseInt(document.getElementById("sales-page-size").value);
  salesState.currentPage = 0;
  localStorage.setItem("sales_page_size", salesState.pageSize);
  renderSalesTable();
}

function exportSalesReport() {
  if (!salesState.filteredProducts || salesState.filteredProducts.length === 0) return;

  const isSold = salesState.viewMode === "sold" || salesState.viewMode === "all";
  const visibleCols = getVisibleColumns(isSold);
  const headers = visibleCols.map(col => col.label);

  const dataRows = salesState.filteredProducts.map((p) =>
    visibleCols.map(col => {
      if (col.key === "subcategory") return p.subcategory || "";
      if (col.key === "bin_location") return p.bin_location || "";
      if (col.key === "reorder_level") return p.reorder_level || 0;
      return p[col.key];
    })
  );

  if (isSold) {
    const totalSold = salesState.filteredProducts.reduce((s, p) => s + p.total_sold, 0);
    const totalReturned = salesState.filteredProducts.reduce((s, p) => s + p.total_returned, 0);
    const totalNet = salesState.filteredProducts.reduce((s, p) => s + p.net_sold, 0);
    const totalsMap = { total_sold: totalSold, total_returned: totalReturned, net_sold: totalNet };
    const totalsRow = visibleCols.map(col => {
      if (col.key === "description") return "Totals";
      if (totalsMap[col.key] !== undefined) return totalsMap[col.key];
      return "";
    });
    dataRows.push(totalsRow);
  }

  const wsData = [headers, ...dataRows];
  const ws = XLSX.utils.aoa_to_sheet(wsData);
  ws["!cols"] = headers.map(() => ({ wch: 18 }));

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, isSold ? "Products Sold" : "Products Not Sold");

  const dateStr = new Date().toISOString().split("T")[0];
  XLSX.writeFile(wb, `sales-report-${salesState.viewMode}-${dateStr}.xlsx`);
}

function selectSellingSubcategories() {
  const sellingSubcats = new Set();
  salesState.allProducts.forEach((p) => {
    if (p.net_sold > 0 && p.subcategory) sellingSubcats.add(p.subcategory);
  });
  salesState.selectedSubcategories = [...sellingSubcats];
  document.querySelectorAll(".sales-subcat-cb").forEach((cb) => {
    cb.checked = sellingSubcats.has(cb.value);
  });
  updateSubcatLabel();
  applySalesFilters();
}

function buildSubcatDropdown(subcategories) {
  const container = document.getElementById("sales-subcat-dropdown");
  container.innerHTML = "";

  const excludedSubcats = salesState.excludedSubcategories || [];
  const visibleSubcats = subcategories.filter((sc) => !excludedSubcats.includes(sc));
  salesState.subcategories = visibleSubcats;

  const controls = document.createElement("div");
  controls.style.cssText = "display: flex; justify-content: space-between; align-items: center; padding: 0.375rem 0.75rem; border-bottom: 2px solid var(--border-color); gap: 0.25rem;";
  controls.innerHTML = `
    <div style="display: flex; gap: 0.375rem;">
      <button type="button" class="btn btn-secondary" onclick="salesSubcatCheckAll(true)" style="font-size: 0.625rem; padding: 0.15rem 0.4rem;">All</button>
      <button type="button" class="btn btn-secondary" onclick="salesSubcatCheckAll(false)" style="font-size: 0.625rem; padding: 0.15rem 0.4rem;">None</button>
    </div>
    <button type="button" class="btn btn-secondary" onclick="openSubcatExclusions()" style="font-size: 0.625rem; padding: 0.15rem 0.4rem;" title="Hide subcategories from this list">Manage</button>
  `;
  container.appendChild(controls);

  visibleSubcats.forEach((sc) => {
    const label = document.createElement("label");
    label.style.cssText = "display: flex; align-items: center; gap: 0.5rem; padding: 0.375rem 0.75rem; cursor: pointer; font-size: 0.8125rem; border-bottom: 1px solid var(--border-color);";
    label.innerHTML = `<input type="checkbox" class="sales-subcat-cb" value="${sc}" checked onchange="onSubcatChange()"> ${sc}`;
    container.appendChild(label);
  });
  salesState.selectedSubcategories = [...visibleSubcats];
}

function salesSubcatCheckAll(checked) {
  document.querySelectorAll(".sales-subcat-cb").forEach((cb) => (cb.checked = checked));
  onSubcatChange();
}

function openSubcatExclusions() {
  const dd = document.getElementById("sales-subcat-dropdown");
  dd.style.display = "none";

  const allSubcats = salesState.allSubcategories || salesState.subcategories || [];
  const excluded = salesState.excludedSubcategories || [];

  let html = '<div style="max-height: 300px; overflow-y: auto;">';
  allSubcats.forEach((sc) => {
    const isExcluded = excluded.includes(sc);
    html += `<label style="display: flex; align-items: center; gap: 0.5rem; padding: 0.375rem 0.75rem; cursor: pointer; font-size: 0.8125rem; border-bottom: 1px solid var(--border-color);">
      <input type="checkbox" class="sales-subcat-manage-cb" value="${sc}" ${isExcluded ? "" : "checked"}> ${sc}
    </label>`;
  });
  html += '</div>';
  html += '<div style="padding: 0.5rem 0.75rem; border-top: 2px solid var(--border-color); display: flex; justify-content: flex-end; gap: 0.375rem;">';
  html += '<button type="button" class="btn btn-secondary" onclick="cancelSubcatExclusions()" style="font-size: 0.6875rem; padding: 0.25rem 0.5rem;">Cancel</button>';
  html += '<button type="button" class="btn btn-primary" onclick="saveSubcatExclusions()" style="font-size: 0.6875rem; padding: 0.25rem 0.5rem;">Save</button>';
  html += '</div>';

  const panel = document.getElementById("sales-subcat-dropdown");
  panel.setAttribute("data-mode", "manage");
  panel.innerHTML = html;
  const trigger = document.getElementById("sales-subcat-trigger");
  const rect = trigger.getBoundingClientRect();
  panel.style.top = (rect.bottom + 2) + "px";
  panel.style.left = rect.left + "px";
  panel.style.display = "block";
}

function cancelSubcatExclusions() {
  const panel = document.getElementById("sales-subcat-dropdown");
  panel.removeAttribute("data-mode");
  buildSubcatDropdown(salesState.allSubcategories || salesState.subcategories || []);
  panel.style.display = "none";
  updateSubcatLabel();
}

async function saveSubcatExclusions() {
  const included = Array.from(document.querySelectorAll(".sales-subcat-manage-cb:checked")).map((cb) => cb.value);
  const allSubcats = salesState.allSubcategories || salesState.subcategories || [];
  const excluded = allSubcats.filter((sc) => !included.includes(sc));

  try {
    await apiRequest("/sales/config/excluded-subcategories", {
      method: "PUT",
      body: JSON.stringify({ excluded_subcategories: excluded }),
    });
    salesState.excludedSubcategories = excluded;
  } catch (e) {
    showToast(e.message || "Failed to save", "error");
    return;
  }

  const panel = document.getElementById("sales-subcat-dropdown");
  panel.removeAttribute("data-mode");
  buildSubcatDropdown(allSubcats);
  panel.style.display = "none";
  updateSubcatLabel();
  applySalesFilters();
  showToast(`${excluded.length} subcategories hidden`, "success");
}

function toggleSubcatDropdown() {
  const dd = document.getElementById("sales-subcat-dropdown");
  if (dd.style.display === "none") {
    const trigger = document.getElementById("sales-subcat-trigger");
    const rect = trigger.getBoundingClientRect();
    dd.style.position = "fixed";
    dd.style.top = (rect.bottom + 2) + "px";
    dd.style.left = rect.left + "px";
    dd.style.display = "block";
  } else {
    dd.style.display = "none";
  }
}

function onSubcatChange() {
  salesState.selectedSubcategories = Array.from(document.querySelectorAll(".sales-subcat-cb:checked")).map((cb) => cb.value);
  updateSubcatLabel();
  applySalesFilters();
}

function updateSubcatLabel() {
  const sel = salesState.selectedSubcategories || [];
  const total = salesState.subcategories ? salesState.subcategories.length : 0;
  const label = document.getElementById("sales-subcat-label");
  if (sel.length === 0 || sel.length === total) {
    label.textContent = "All";
  } else {
    const unchecked = total - sel.length;
    label.textContent = `${unchecked} excluded`;
  }
}

function buildReorderDropdown(levels) {
  const container = document.getElementById("sales-reorder-dropdown");
  if (!container) return;
  container.innerHTML = "";

  const controls = document.createElement("div");
  controls.style.cssText = "display: flex; justify-content: space-between; align-items: center; padding: 0.375rem 0.75rem; border-bottom: 2px solid var(--border-color); gap: 0.25rem;";
  controls.innerHTML = `
    <div style="display: flex; gap: 0.375rem;">
      <button type="button" class="btn btn-secondary" onclick="reorderCheckAll(true)" style="font-size: 0.625rem; padding: 0.15rem 0.4rem;">All</button>
      <button type="button" class="btn btn-secondary" onclick="reorderCheckAll(false)" style="font-size: 0.625rem; padding: 0.15rem 0.4rem;">None</button>
    </div>
  `;
  container.appendChild(controls);

  levels.forEach((lvl) => {
    const label = document.createElement("label");
    label.style.cssText = "display: flex; align-items: center; gap: 0.5rem; padding: 0.375rem 0.75rem; cursor: pointer; font-size: 0.8125rem; border-bottom: 1px solid var(--border-color);";
    label.innerHTML = `<input type="checkbox" class="sales-reorder-cb" value="${lvl}" checked onchange="onReorderChange()"> ${lvl}`;
    container.appendChild(label);
  });
  salesState.selectedReorderLevels = [...levels];
}

function reorderCheckAll(checked) {
  document.querySelectorAll(".sales-reorder-cb").forEach((cb) => (cb.checked = checked));
  onReorderChange();
}

function toggleReorderDropdown() {
  const dd = document.getElementById("sales-reorder-dropdown");
  if (dd.style.display === "none") {
    const trigger = document.getElementById("sales-reorder-trigger");
    const rect = trigger.getBoundingClientRect();
    dd.style.position = "fixed";
    dd.style.top = (rect.bottom + 2) + "px";
    dd.style.left = rect.left + "px";
    dd.style.display = "block";
  } else {
    dd.style.display = "none";
  }
}

function onReorderChange() {
  salesState.selectedReorderLevels = Array.from(document.querySelectorAll(".sales-reorder-cb:checked")).map((cb) => Number(cb.value));
  updateReorderLabel();
  applySalesFilters();
}

function updateReorderLabel() {
  const sel = salesState.selectedReorderLevels || [];
  const allLevels = [...new Set(salesState.allProducts.map(p => p.reorder_level || 0))];
  const total = allLevels.length;
  const label = document.getElementById("sales-reorder-label");
  if (!label) return;
  if (sel.length === 0 || sel.length === total) {
    label.textContent = "All";
  } else {
    const unchecked = total - sel.length;
    label.textContent = `${unchecked} excluded`;
  }
}

document.addEventListener("click", (e) => {
  const trigger = document.getElementById("sales-subcat-trigger");
  const dropdown = document.getElementById("sales-subcat-dropdown");
  if (trigger && dropdown && !trigger.contains(e.target) && !dropdown.contains(e.target) && !dropdown.getAttribute("data-mode")) {
    dropdown.style.display = "none";
  }
  const reorderTrigger = document.getElementById("sales-reorder-trigger");
  const reorderDropdown = document.getElementById("sales-reorder-dropdown");
  if (reorderTrigger && reorderDropdown && !reorderTrigger.contains(e.target) && !reorderDropdown.contains(e.target)) {
    reorderDropdown.style.display = "none";
  }
  const acContainer = document.getElementById("sales-excl-autocomplete");
  const acInput = document.getElementById("sales-excl-name");
  if (acContainer && acInput && !acContainer.contains(e.target) && e.target !== acInput) {
    acContainer.style.display = "none";
  }
});

function searchSalesBusinessNames() {
  clearTimeout(salesState.exclSearchTimeout);
  const query = document.getElementById("sales-excl-name").value.trim();
  const container = document.getElementById("sales-excl-autocomplete");
  if (query.length < 2) { container.style.display = "none"; return; }

  salesState.exclSearchTimeout = setTimeout(async () => {
    try {
      const data = await apiRequest(`/sales/business-names?query=${encodeURIComponent(query)}`);
      if (!data.results || data.results.length === 0) { container.style.display = "none"; return; }
      container.innerHTML = "";
      data.results.forEach((name) => {
        const div = document.createElement("div");
        div.style.cssText = "padding: 0.375rem 0.75rem; cursor: pointer; font-size: 0.8125rem; border-bottom: 1px solid var(--border-color);";
        div.textContent = name;
        div.onmouseenter = () => { div.style.background = "var(--bg-hover)"; };
        div.onmouseleave = () => { div.style.background = ""; };
        div.onclick = () => {
          document.getElementById("sales-excl-name").value = name;
          container.style.display = "none";
        };
        container.appendChild(div);
      });
      container.style.display = "block";
    } catch (e) {
      container.style.display = "none";
    }
  }, 300);
}

function toggleSalesExclusions() {
  const panel = document.getElementById("sales-exclusions-panel");
  if (panel.style.display === "none") {
    panel.style.display = "block";
    loadSalesExclusions();
  } else {
    panel.style.display = "none";
  }
}

async function loadSalesExclusions() {
  try {
    const data = await apiRequest("/sales/exclusions");
    const container = document.getElementById("sales-exclusions-list");
    if (!data.exclusions || data.exclusions.length === 0) {
      container.innerHTML = '<p style="color: var(--text-tertiary); margin: 0;">No exclusions configured.</p>';
      return;
    }
    let html = '<table class="data-table" style="font-size: 0.8125rem;"><thead><tr><th>Business Name</th><th style="width: 100px;">Scope</th><th style="width: 60px;"></th></tr></thead><tbody>';
    data.exclusions.forEach((e) => {
      const scope = e.void_status === null ? "All" : (e.void_status === 0 ? "Non-voided" : "Voided");
      const scopeColor = e.void_status === null ? "var(--text-tertiary)" : (e.void_status === 0 ? "var(--success)" : "var(--warning)");
      html += `<tr>
        <td>${e.business_name}</td>
        <td style="color: ${scopeColor}">${scope}</td>
        <td style="text-align: center;"><button class="btn btn-secondary" style="font-size: 0.6875rem; padding: 0.15rem 0.4rem;" onclick="deleteSalesExclusion(${e.id})">Remove</button></td>
      </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  } catch (e) {
    document.getElementById("sales-exclusions-list").innerHTML = '<p style="color: var(--danger);">Failed to load exclusions.</p>';
  }
}

async function addSalesExclusion() {
  const name = document.getElementById("sales-excl-name").value.trim();
  if (!name) { showToast("Enter a business name", "warning"); return; }
  const scopeVal = document.getElementById("sales-excl-scope").value;
  const voidStatus = scopeVal === "" ? null : parseInt(scopeVal);

  try {
    await apiRequest("/sales/exclusions", {
      method: "POST",
      body: JSON.stringify({ business_name: name, void_status: voidStatus }),
    });
    document.getElementById("sales-excl-name").value = "";
    loadSalesExclusions();
    showToast("Exclusion added", "success");
  } catch (e) {
    showToast(e.message || "Failed to add exclusion", "error");
  }
}

async function deleteSalesExclusion(id) {
  try {
    await apiRequest(`/sales/exclusions/${id}`, { method: "DELETE" });
    loadSalesExclusions();
    showToast("Exclusion removed", "success");
  } catch (e) {
    showToast(e.message || "Failed to remove", "error");
  }
}

// ===== End Sales Report =====

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  const savedTheme = localStorage.getItem("selectedTheme") || "author-light";
  setTheme(savedTheme);

  initSettingsTabs();

  const params = new URLSearchParams(window.location.search);
  const trackerUpc = params.get("tracker");
  const trackerDays = params.get("days");
  const trackerFrom = params.get("from");
  const trackerTo = params.get("to");

  if (trackerUpc) {
    navigateToItemTrackerWithUpc(trackerUpc, trackerDays ? parseInt(trackerDays, 10) : null, trackerFrom, trackerTo);
  } else {
    const defaultPage = getDefaultLandingPage();
    navigateTo(defaultPage);
  }
});

// ===== Quotations In Progress =====

const QIP_ADMIN_STORE_KEY = "admin_store_id";

const qipState = {
  initialized: false,
  loading: false,
  filters: {
    scan_filter: "all", // "all" | "in" | "out" | "none"
    source_dbs: [],
    packers: [],
    checkers: [],
    search: "",
    sort_by: "start_date",
    sort_order: "desc",
    limit: 500,
  },
  // Tracks total available options per multiselect, so the badge can
  // compare "checked count vs total" and we can default to "all checked"
  // on first populate.
  multiselectMeta: {
    source_dbs: { initialized: false, total: 0 },
    packers: { initialized: false, total: 0 },
    checkers: { initialized: false, total: 0 },
  },
  results: [],
  selectedQuotation: null,
  productCache: new Map(),

  // Right pane mode
  viewMode: "empty",          // "empty" | "summary" | "quotation"
  searchProducts: [],         // matched product rows for the active search
  searchProductsCount: 0,
  searchActiveQuery: "",      // term currently driving summary + highlights

  // Sort applied to the products table (both quotation view and summary).
  // column: null | "description" | "qty"; order: "asc" | "desc"
  productSort: { column: null, order: "asc" },
};

let qipSearchDebounce = null;

async function loadAdminStoreSetting() {
  const select = document.getElementById("qip-admin-store");
  if (!select) return;

  try {
    const stores = await apiRequest("/stores");
    const mssqlStores = stores.filter(
      (s) => s.store_type === "mssql" && s.is_active,
    );
    select.innerHTML = '<option value="">— None —</option>';
    mssqlStores.forEach((store) => {
      const opt = document.createElement("option");
      opt.value = store.id;
      opt.textContent = store.name;
      select.appendChild(opt);
    });

    const resp = await fetch(`${API_BASE}/settings/${QIP_ADMIN_STORE_KEY}`);
    if (resp.ok) {
      const setting = await resp.json();
      if (setting.value) select.value = setting.value;
    }
  } catch {}
}

async function saveAdminStoreSetting() {
  const select = document.getElementById("qip-admin-store");
  if (!select) return;
  const value = select.value;

  try {
    const patchResp = await fetch(`${API_BASE}/settings/${QIP_ADMIN_STORE_KEY}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
    if (!patchResp.ok) {
      await apiRequest("/settings", {
        method: "POST",
        body: JSON.stringify({
          key: QIP_ADMIN_STORE_KEY,
          value,
          description: "MSSQL store hosting the centralized DB_ADMIN database (QuotationsInProgress / QuotationsStatus).",
        }),
      });
    }
    showToast("✓ Admin store saved", "success");
  } catch (error) {
    showToast(`✗ Failed to save: ${error.message}`, "error");
  }
}

document
  .getElementById("qip-admin-store-save")
  ?.addEventListener("click", saveAdminStoreSetting);

function loadQuotationsInProgressPage() {
  if (!qipState.initialized) {
    initQuotationsInProgressPage();
    qipState.initialized = true;
  }
  fetchQuotationsInProgress();
}

function initQuotationsInProgressPage() {
  // ----- Segmented scan-status control (single-select) -----
  const segContainer = document.getElementById("qip-scan-segmented");
  segContainer.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-scan]");
    if (!btn) return;
    qipState.filters.scan_filter = btn.dataset.scan;
    qipUpdateSegmented();
    fetchQuotationsInProgress();
  });

  // ----- Search (debounced) -----
  const search = document.getElementById("qip-search");
  search.addEventListener("input", (e) => {
    qipState.filters.search = e.target.value;
    if (qipSearchDebounce) clearTimeout(qipSearchDebounce);
    qipSearchDebounce = setTimeout(qipHandleSearchChange, 300);
  });

  // ----- Summary button -----
  document
    .getElementById("qip-summary-btn")
    .addEventListener("click", () => {
      if (!qipState.searchActiveQuery) return;
      qipState.viewMode = "summary";
      qipUpdateSummaryButton();
      qipRenderRightPane();
    });

  // ----- Multi-select popovers -----
  document.querySelectorAll(".qip-multiselect").forEach((ms) => {
    const trigger = ms.querySelector(".qip-ms-trigger");
    trigger.setAttribute("aria-expanded", "false");
    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const popover = ms.querySelector(".qip-ms-popover");
      const isOpen = popover.classList.contains("open");
      // Close any other open popovers
      document.querySelectorAll(".qip-ms-popover.open").forEach((p) => {
        p.classList.remove("open");
        p.parentElement.querySelector(".qip-ms-trigger").setAttribute("aria-expanded", "false");
      });
      if (!isOpen) {
        popover.classList.add("open");
        trigger.setAttribute("aria-expanded", "true");
      }
    });
  });

  // Click outside to close popovers
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".qip-multiselect")) {
      document.querySelectorAll(".qip-ms-popover.open").forEach((p) => {
        p.classList.remove("open");
        p.parentElement.querySelector(".qip-ms-trigger").setAttribute("aria-expanded", "false");
      });
    }
  });

  // ----- Sort -----
  document.getElementById("qip-sort-by").addEventListener("change", (e) => {
    qipState.filters.sort_by = e.target.value;
    fetchQuotationsInProgress();
  });

  const sortDir = document.getElementById("qip-sort-dir");
  sortDir.addEventListener("click", () => {
    const next = qipState.filters.sort_order === "desc" ? "asc" : "desc";
    qipState.filters.sort_order = next;
    sortDir.dataset.order = next;
    fetchQuotationsInProgress();
  });

  // ----- Refresh / Clear -----
  document
    .getElementById("qip-refresh-btn")
    .addEventListener("click", () => fetchQuotationsInProgress(true));

  document.getElementById("qip-clear-btn").addEventListener("click", () => {
    document.getElementById("qip-search").value = "";
    qipState.filters = {
      scan_filter: "all",
      source_dbs: [],
      packers: [],
      checkers: [],
      search: "",
      sort_by: qipState.filters.sort_by,
      sort_order: qipState.filters.sort_order,
      limit: 500,
    };
    // Re-default multiselects to "all checked" on next populate.
    Object.keys(qipState.multiselectMeta).forEach((k) => {
      qipState.multiselectMeta[k].initialized = false;
    });
    // Clear the active search summary state too.
    qipState.searchActiveQuery = "";
    qipState.searchProducts = [];
    qipState.searchProductsCount = 0;
    if (qipState.viewMode === "summary") {
      qipState.viewMode = qipState.selectedQuotation ? "quotation" : "empty";
    }
    qipUpdateSegmented();
    qipUpdateSummaryButton();
    fetchQuotationsInProgress();
  });

  // Settings page-link inside the unconfigured banner
  document
    .querySelector('#qip-not-configured a[data-page="settings"]')
    ?.addEventListener("click", (e) => {
      e.preventDefault();
      navigateTo("settings");
    });

  // Delegate clicks on sortable column headers anywhere in the right
  // detail pane -- works for both the per-quotation products table
  // (whose thead lives in the HTML) and the dynamic summary table
  // (whose thead is recreated by renderSearchSummary).
  const detailPane = document.querySelector(".qip-detail");
  if (detailPane) {
    detailPane.addEventListener("click", (e) => {
      const th = e.target.closest("th.qip-sortable");
      if (!th) return;
      const col = th.dataset.sort;
      if (!col) return;
      const cur = qipState.productSort;
      let next;
      if (cur.column !== col) {
        next = { column: col, order: "asc" };
      } else if (cur.order === "asc") {
        next = { column: col, order: "desc" };
      } else {
        next = { column: null, order: "asc" }; // third click clears
      }
      qipState.productSort = next;
      qipRefreshProductsTable();
    });
  }

  qipUpdateSegmented();
}

function qipUpdateSegmented() {
  const seg = document.getElementById("qip-scan-segmented");
  if (!seg) return;
  seg.querySelectorAll("button[data-scan]").forEach((b) => {
    b.classList.toggle(
      "active",
      b.dataset.scan === qipState.filters.scan_filter,
    );
  });
}

function populateMultiselect(key, values) {
  const container = document.querySelector(`.qip-multiselect[data-key="${key}"]`);
  if (!container) return;
  const popover = container.querySelector(".qip-ms-popover");

  const meta = qipState.multiselectMeta[key];
  meta.total = values.length;

  if (!meta.initialized) {
    // First time we see options for this filter -> default to all checked.
    qipState.filters[key] = [...values];
    meta.initialized = true;
  } else {
    // Drop any prior selections that no longer exist in the data.
    qipState.filters[key] = (qipState.filters[key] || []).filter((v) =>
      values.includes(v),
    );
  }

  const selectedSet = new Set(qipState.filters[key]);

  popover.innerHTML = "";
  if (!values || values.length === 0) {
    const empty = document.createElement("div");
    empty.className = "qip-ms-empty";
    empty.textContent = "No options available";
    popover.appendChild(empty);
  } else {
    values.forEach((v) => {
      const item = document.createElement("div");
      item.className = "qip-ms-item" + (selectedSet.has(v) ? " selected" : "");
      item.dataset.value = v;
      item.innerHTML = `
        <span class="qip-ms-check"></span>
        <span class="qip-ms-item-label"></span>
      `;
      item.querySelector(".qip-ms-item-label").textContent = v;
      item.addEventListener("click", () => {
        const idx = qipState.filters[key].indexOf(v);
        if (idx === -1) qipState.filters[key].push(v);
        else qipState.filters[key].splice(idx, 1);
        item.classList.toggle("selected");
        qipUpdateMultiselectTrigger(key);
        fetchQuotationsInProgress();
      });
      popover.appendChild(item);
    });
  }

  qipUpdateMultiselectTrigger(key);
}

function qipUpdateMultiselectTrigger(key) {
  const container = document.querySelector(`.qip-multiselect[data-key="${key}"]`);
  if (!container) return;
  const trigger = container.querySelector(".qip-ms-trigger");
  const countEl = trigger.querySelector(".qip-ms-count");
  const meta = qipState.multiselectMeta[key];
  const checked = (qipState.filters[key] || []).length;
  const total = meta ? meta.total : 0;

  if (total === 0) {
    countEl.hidden = true;
    trigger.classList.remove("has-selection");
    return;
  }

  countEl.textContent = String(checked);
  countEl.hidden = false;
  // Highlight the trigger only when the user has actually filtered
  // (i.e. some options are unchecked).
  trigger.classList.toggle("has-selection", checked < total);
}

function qipUpdateMultiselectsTriggers() {
  ["source_dbs", "packers", "checkers"].forEach((k) => {
    qipUpdateMultiselectTrigger(k);
    // Sync visual selection of items inside the popover
    const container = document.querySelector(`.qip-multiselect[data-key="${k}"]`);
    if (!container) return;
    container.querySelectorAll(".qip-ms-item").forEach((item) => {
      const sel = (qipState.filters[k] || []).includes(item.dataset.value);
      item.classList.toggle("selected", sel);
    });
  });
}

async function fetchQuotationsInProgress(forceClearCache = false) {
  const errorEl = document.getElementById("qip-error");
  const loadingEl = document.getElementById("qip-loading");
  const resultsEl = document.getElementById("qip-results");
  const controlsEl = document.getElementById("qip-controls");
  const notConfigEl = document.getElementById("qip-not-configured");

  errorEl.style.display = "none";
  loadingEl.style.display = "inline-flex";
  qipState.loading = true;

  if (forceClearCache) qipState.productCache.clear();

  try {
    // When every option of a multiselect is checked, treat it as "no
    // filter on this dimension" -- send an empty array. Otherwise the
    // backend's IN (...) clause would silently exclude rows whose value
    // is NULL (e.g. unscanned quotations have no packer / checker row).
    const payload = { ...qipState.filters };
    ["source_dbs", "packers", "checkers"].forEach((k) => {
      const meta = qipState.multiselectMeta[k];
      if (
        meta &&
        meta.initialized &&
        meta.total > 0 &&
        (qipState.filters[k] || []).length === meta.total
      ) {
        payload[k] = [];
      }
    });

    const resp = await fetch(`${API_BASE}/quotations/in-progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (resp.status === 400) {
      const err = await resp.json();
      controlsEl.style.display = "none";
      resultsEl.style.display = "none";
      notConfigEl.style.display = "flex";
      const body = notConfigEl.querySelector(".qip-banner-body");
      if (body) {
        body.innerHTML =
          `<strong>Admin database not configured.</strong> ${escapeHtml(err.detail || "")} `
          + `Open <a href="#" data-page="settings" class="qip-banner-link">Settings</a> to set it.`;
        body.querySelector('a[data-page="settings"]').addEventListener("click", (e) => {
          e.preventDefault();
          navigateTo("settings");
        });
      }
      return;
    }

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${resp.status})`);
    }

    const data = await resp.json();
    qipState.results = data.quotations || [];

    notConfigEl.style.display = "none";
    controlsEl.style.display = "flex";
    resultsEl.style.display = "grid";

    populateMultiselect("source_dbs", data.filter_options.source_dbs || []);
    populateMultiselect("packers", data.filter_options.packers || []);
    populateMultiselect("checkers", data.filter_options.checkers || []);

    qipUpdateHeaderMeta(qipState.results);
    renderQuotationsList(qipState.results);

    // Drop the selection if it no longer appears in the narrowed list.
    if (
      qipState.selectedQuotation &&
      !qipState.results.some(
        (q) => q.quotation_number === qipState.selectedQuotation,
      )
    ) {
      qipState.selectedQuotation = null;
      if (qipState.viewMode === "quotation") {
        qipState.viewMode = qipState.searchActiveQuery ? "summary" : "empty";
      }
    } else {
      highlightSelectedCard();
    }

    qipRenderRightPane({ forceClearCache });
  } catch (error) {
    errorEl.style.display = "block";
    errorEl.textContent = `Error: ${error.message}`;
    controlsEl.style.display = "flex";
    resultsEl.style.display = "none";
  } finally {
    loadingEl.style.display = "none";
    qipState.loading = false;
  }
}

function qipUpdateHeaderMeta(quotations) {
  const total = quotations.length;
  let pending = 0;
  let complete = 0;
  quotations.forEach((q) => {
    const hasIn = !!(q.dop2 && String(q.dop2).trim());
    const hasOut = !!(q.dop3 && String(q.dop3).trim());
    if (hasIn && hasOut) complete++;
    else pending++;
  });
  document.getElementById("qip-meta-total").textContent = total.toLocaleString();
  document.getElementById("qip-meta-pending").textContent = pending.toLocaleString();
  document.getElementById("qip-meta-complete").textContent = complete.toLocaleString();
}

function renderQuotationsList(quotations) {
  const body = document.getElementById("qip-list-body");
  document.getElementById("qip-count").textContent = quotations.length.toLocaleString();

  if (quotations.length === 0) {
    body.innerHTML = '<div class="qip-empty">No quotations match these filters.</div>';
    return;
  }

  body.innerHTML = "";
  const indexWidth = String(quotations.length).length;
  quotations.forEach((q, idx) => {
    const card = document.createElement("div");
    card.className = "qip-card";
    card.dataset.quotationNumber = q.quotation_number || "";
    if (q.quotation_number === qipState.selectedQuotation) {
      card.classList.add("selected");
    }

    const hasIn = !!(q.dop2 && String(q.dop2).trim());
    const hasOut = !!(q.dop3 && String(q.dop3).trim());
    const inTime = hasIn ? qipFormatTime(String(q.dop2)) : "";
    const outTime = hasOut ? qipFormatTime(String(q.dop3)) : "";

    const businessText = q.business_name || "—";
    const startedAbs = q.start_date ? qipFormatDateTime(q.start_date) : "";
    const indexLabel = String(idx + 1).padStart(indexWidth, "0");
    const status = qipStatusFor(hasIn, hasOut);
    const statusChipHtml = qipRenderStatusChip(status, inTime, outTime);

    const metaTitle = `${businessText}${q.packer ? ` (${q.packer})` : ""}${startedAbs ? ` — started ${startedAbs}` : ""}`;

    card.innerHTML = `
      <div class="qip-card-head">
        <span class="qip-card-index">${escapeHtml(indexLabel)}</span>
        <span class="qip-card-num">${escapeHtml(q.quotation_number || "—")}</span>
        ${statusChipHtml}
      </div>
      <div class="qip-card-foot" title="${escapeHtml(metaTitle)}">
        <span class="qip-card-business">
          ${escapeHtml(businessText)}${q.packer ? ` <span class="qip-card-packer">· ${escapeHtml(q.packer)}</span>` : ""}
        </span>
        <span class="qip-card-foot-right">
          <span class="qip-card-meta-stats">
            <strong>${q.product_count}</strong>&nbsp;<span class="qip-card-meta-unit">items</span>
            <span class="qip-card-meta-sep">·</span>
            <strong>${(q.total_qty || 0).toLocaleString()}</strong>&nbsp;<span class="qip-card-meta-unit">qty</span>
          </span>
          ${q.source_db ? `<span class="qip-card-tag">${escapeHtml(q.source_db)}</span>` : ""}
        </span>
      </div>
    `;

    card.addEventListener("click", () => selectQuotation(q.quotation_number));
    body.appendChild(card);
  });
}

function highlightSelectedCard() {
  document.querySelectorAll("#qip-list-body .qip-card").forEach((c) => {
    c.classList.toggle(
      "selected",
      c.dataset.quotationNumber === qipState.selectedQuotation,
    );
  });
}

async function selectQuotation(quotationNumber, forceFetch = false) {
  if (!quotationNumber) return;
  qipState.selectedQuotation = quotationNumber;
  qipState.viewMode = "quotation";
  highlightSelectedCard();
  qipUpdateSummaryButton();

  qipShowQuotationViewShell();
  const headerEl = document.getElementById("qip-detail-header");
  const tbody = document
    .getElementById("qip-products-table")
    .querySelector("tbody");

  headerEl.innerHTML = `
    <div class="qip-hero">
      <div class="qip-hero-left">
        <div class="qip-hero-eyebrow">Loading…</div>
        <h2>${escapeHtml(quotationNumber)}</h2>
      </div>
    </div>
  `;
  tbody.innerHTML = "";

  let payload = qipState.productCache.get(quotationNumber);
  if (!payload || forceFetch) {
    try {
      const resp = await fetch(
        `${API_BASE}/quotations/in-progress/${encodeURIComponent(quotationNumber)}/products`,
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Request failed (${resp.status})`);
      }
      payload = await resp.json();
      qipState.productCache.set(quotationNumber, payload);
    } catch (error) {
      headerEl.innerHTML = `<div class="qip-error">Error: ${escapeHtml(error.message)}</div>`;
      return;
    }
  }

  // Bail if user navigated away or cleared while we were fetching.
  if (qipState.selectedQuotation !== quotationNumber) return;

  renderQuotationDetailHeader(payload.header, quotationNumber);
  renderQuotationProducts(payload.products, qipState.searchActiveQuery);
}

const QIP_CHECK_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
const QIP_DASH_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="12" x2="18" y2="12"/></svg>';

function renderQuotationDetailHeader(header, quotationNumber) {
  const headerEl = document.getElementById("qip-detail-header");

  if (!header) {
    headerEl.innerHTML = `
      <div class="qip-hero">
        <div class="qip-hero-left">
          <div class="qip-hero-eyebrow">No status record</div>
          <h2>${escapeHtml(quotationNumber)}</h2>
          <div class="qip-hero-business">No matching record in QuotationsStatus.</div>
        </div>
      </div>
    `;
    return;
  }

  const hasIn = !!(header.dop2 && String(header.dop2).trim());
  const hasOut = !!(header.dop3 && String(header.dop3).trim());
  const inTime = hasIn ? String(header.dop2) : "—";
  const outTime = hasOut ? String(header.dop3) : "—";
  let lineClass = "";
  if (hasIn && hasOut) lineClass = "complete";

  headerEl.innerHTML = `
    <div class="qip-hero">
      <div class="qip-hero-left">
        <div class="qip-hero-eyebrow">
          <span>Quotation</span>
          ${header.source_db ? `<span class="qip-hero-tag">${escapeHtml(header.source_db)}</span>` : ""}
          ${header.status ? `<span class="qip-hero-tag">${escapeHtml(header.status)}</span>` : ""}
        </div>
        <h2>${escapeHtml(quotationNumber)}</h2>
        <div class="qip-hero-business">
          ${escapeHtml(header.business_name || "—")}
          ${header.packer ? ` <span class="qip-hero-sep">·</span> Packer <strong>${escapeHtml(header.packer)}</strong>` : ""}
        </div>
      </div>
      <div class="qip-timeline" aria-label="Scan timeline">
        <div class="qip-timeline-step in ${hasIn ? "complete" : ""}">
          <div class="qip-timeline-icon">${hasIn ? QIP_CHECK_SVG : QIP_DASH_SVG}</div>
          <div class="qip-timeline-text">
            <span class="qip-timeline-label">Scan-in</span>
            <span class="qip-timeline-time">${escapeHtml(inTime)}</span>
          </div>
        </div>
        <div class="qip-timeline-line ${lineClass}"></div>
        <div class="qip-timeline-step out ${hasOut ? "complete" : ""}">
          <div class="qip-timeline-icon">${hasOut ? QIP_CHECK_SVG : QIP_DASH_SVG}</div>
          <div class="qip-timeline-text">
            <span class="qip-timeline-label">Scan-out</span>
            <span class="qip-timeline-time">${escapeHtml(outTime)}</span>
          </div>
        </div>
      </div>
    </div>
  `;
}

const QIP_PRICE_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function qipFormatPrice(value) {
  if (value == null || isNaN(value)) return "—";
  return QIP_PRICE_FORMATTER.format(value);
}

function qipLineTotal(row) {
  // Grouped summary rows carry an aggregated line_total; per-quotation
  // rows derive theirs on the fly from price * qty. Returns -Infinity
  // for unpriced rows so sorting parks them on whichever end matches
  // "missing last".
  if (row.line_total != null) return row.line_total;
  if (row.price == null) return -Infinity;
  return row.price * (row.qty || 0);
}

function qipSortProducts(products) {
  const { column, order } = qipState.productSort;
  if (!column) return products;
  const dir = order === "desc" ? -1 : 1;
  const sorted = [...products];
  sorted.sort((a, b) => {
    if (column === "qty") {
      return ((a.qty || 0) - (b.qty || 0)) * dir;
    }
    if (column === "price") {
      // Treat null prices as -Infinity so they sink to the bottom on
      // descending and to the top on ascending (consistent with the
      // common "missing values last when you care most" expectation).
      const ap = a.price == null ? -Infinity : a.price;
      const bp = b.price == null ? -Infinity : b.price;
      return (ap - bp) * dir;
    }
    if (column === "line_total") {
      // Per-quotation rows compute line_total inline (price * qty);
      // grouped summary rows already carry it pre-computed.
      const al = qipLineTotal(a);
      const bl = qipLineTotal(b);
      return (al - bl) * dir;
    }
    const ad = (a.product_description || "").toLowerCase();
    const bd = (b.product_description || "").toLowerCase();
    if (ad < bd) return -1 * dir;
    if (ad > bd) return 1 * dir;
    return 0;
  });
  return sorted;
}

function qipUpdateSortIndicators(thead) {
  if (!thead) return;
  const { column, order } = qipState.productSort;
  thead.querySelectorAll("th.qip-sortable").forEach((th) => {
    th.classList.remove("qip-sort-asc", "qip-sort-desc");
    if (column && th.dataset.sort === column) {
      th.classList.add(order === "desc" ? "qip-sort-desc" : "qip-sort-asc");
    }
  });
}

function qipRefreshProductsTable() {
  if (qipState.viewMode === "summary") {
    renderSearchSummary();
  } else if (
    qipState.viewMode === "quotation" &&
    qipState.selectedQuotation
  ) {
    const cached = qipState.productCache.get(qipState.selectedQuotation);
    if (cached && cached.products) {
      renderQuotationProducts(cached.products, qipState.searchActiveQuery);
    }
  }
}

function renderQuotationProducts(products, matchTerm) {
  const table = document.getElementById("qip-products-table");
  const tbody = table.querySelector("tbody");
  const thead = table.querySelector("thead");
  const countEl = document.getElementById("qip-products-count");

  qipUpdateSortIndicators(thead);

  if (!products || products.length === 0) {
    countEl.textContent = "0";
    tbody.innerHTML = `<tr><td colspan="4"><div class="qip-products-empty">No products on this quotation.</div></td></tr>`;
    return;
  }

  const sortedProducts = qipSortProducts(products);
  const term = (matchTerm || "").trim().toLowerCase();
  let matchCount = 0;
  let lineTotalSum = 0;

  tbody.innerHTML = "";
  sortedProducts.forEach((p) => {
    const tr = document.createElement("tr");

    const isMatch =
      term &&
      (((p.product_upc || "").toLowerCase().includes(term)) ||
        ((p.product_sku || "").toLowerCase().includes(term)) ||
        ((p.product_description || "").toLowerCase().includes(term)));
    if (isMatch) {
      tr.classList.add("qip-product-match");
      matchCount++;
    }

    const rowTotal = p.price != null ? p.price * (p.qty || 0) : null;
    if (rowTotal != null) {
      lineTotalSum += rowTotal;
    }

    tr.innerHTML = `
      <td class="qip-product-desc">${escapeHtml(p.product_description || "—")}</td>
      <td class="qip-num">${(p.qty || 0).toLocaleString()}</td>
      <td class="qip-num">${qipFormatPrice(p.price)}</td>
      <td class="qip-num"><strong>${qipFormatPrice(rowTotal)}</strong></td>
    `;
    tbody.appendChild(tr);
  });

  let countText = `${products.length} ${products.length === 1 ? "item" : "items"}`;
  if (term && matchCount > 0) {
    countText += ` · ${matchCount} match${matchCount === 1 ? "" : "es"}`;
  }
  if (lineTotalSum > 0) {
    countText += ` · ${qipFormatPrice(lineTotalSum)} total`;
  }
  countEl.textContent = countText;
}

function qipStatusFor(hasIn, hasOut) {
  if (hasIn && hasOut) return "complete";
  if (hasIn) return "picking";
  if (hasOut) return "complete"; // edge case: out without in — treat as complete
  return "pending";
}

const QIP_STATUS_ICON = {
  pending:
    '<svg class="qip-status-icon" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>',
  picking:
    '<svg class="qip-status-icon" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>',
  complete:
    '<svg class="qip-status-icon" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.25" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
};

function qipRenderStatusChip(status, inTime, outTime) {
  const labels = {
    pending: "Pending",
    picking: "Picking",
    complete: "Complete",
  };
  const label = labels[status];
  let timeHtml = "";
  if (status === "picking" && inTime) {
    timeHtml = `<span class="qip-status-time">${escapeHtml(inTime)}</span>`;
  } else if (status === "complete" && (inTime || outTime)) {
    timeHtml = `<span class="qip-status-time">${escapeHtml(inTime || "—")}<span class="qip-status-time-sep">→</span>${escapeHtml(outTime || "—")}</span>`;
  }
  return `<span class="qip-status-chip ${status}">${QIP_STATUS_ICON[status]}<span class="qip-status-label">${label}</span>${timeHtml}</span>`;
}

function qipShowQuotationViewShell() {
  // Hide summary, show the original quotation hero + products section.
  const summaryEl = document.getElementById("qip-search-summary");
  if (summaryEl) summaryEl.style.display = "none";
  document.getElementById("qip-detail-empty").style.display = "none";
  document.getElementById("qip-detail-content").style.display = "block";
}

function qipShowEmptyShell() {
  const summaryEl = document.getElementById("qip-search-summary");
  if (summaryEl) summaryEl.style.display = "none";
  document.getElementById("qip-detail-empty").style.display = "flex";
  document.getElementById("qip-detail-content").style.display = "none";
}

function qipShowSummaryShell() {
  document.getElementById("qip-detail-empty").style.display = "none";
  document.getElementById("qip-detail-content").style.display = "none";
  let summaryEl = document.getElementById("qip-search-summary");
  if (!summaryEl) {
    const detailPane = document.querySelector(".qip-detail");
    summaryEl = document.createElement("div");
    summaryEl.id = "qip-search-summary";
    detailPane.appendChild(summaryEl);
  }
  summaryEl.style.display = "block";
  return summaryEl;
}

function qipRenderRightPane({ forceClearCache = false } = {}) {
  if (qipState.viewMode === "summary") {
    renderSearchSummary();
  } else if (qipState.viewMode === "quotation" && qipState.selectedQuotation) {
    selectQuotation(qipState.selectedQuotation, forceClearCache);
  } else {
    qipState.viewMode = "empty";
    qipShowEmptyShell();
  }
  qipUpdateSummaryButton();
}

async function qipHandleSearchChange() {
  const term = (qipState.filters.search || "").trim();

  if (!term) {
    // Cleared: drop summary state, snap right pane back to selection or empty.
    qipState.searchActiveQuery = "";
    qipState.searchProducts = [];
    qipState.searchProductsCount = 0;
    if (qipState.viewMode === "summary") {
      qipState.viewMode = qipState.selectedQuotation ? "quotation" : "empty";
    }
    qipUpdateSummaryButton();
    fetchQuotationsInProgress();
    return;
  }

  // Active search: switch right pane to summary mode and fire both fetches.
  qipState.searchActiveQuery = term;
  qipState.viewMode = "summary";
  qipUpdateSummaryButton();

  // Fire both in parallel; each calls qipRenderRightPane (via the fetch
  // chain) so the summary materializes as soon as products arrive.
  fetchQuotationsInProgress();
  fetchSearchProducts();
}

async function fetchSearchProducts() {
  const errorEl = document.getElementById("qip-error");
  errorEl.style.display = "none";

  // Snapshot the query that triggered this fetch so a stale response
  // can't overwrite state after the user has cleared / typed something
  // newer.
  const expectedQuery = qipState.searchActiveQuery;

  try {
    // Mirror the same "all-checked = no filter" payload transform used
    // by fetchQuotationsInProgress so summary results stay consistent
    // with the narrowed list.
    const payload = { ...qipState.filters };
    ["source_dbs", "packers", "checkers"].forEach((k) => {
      const meta = qipState.multiselectMeta[k];
      if (
        meta &&
        meta.initialized &&
        meta.total > 0 &&
        (qipState.filters[k] || []).length === meta.total
      ) {
        payload[k] = [];
      }
    });

    const resp = await fetch(`${API_BASE}/quotations/in-progress/search-products`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${resp.status})`);
    }
    const data = await resp.json();

    // Drop the response if the user has moved on.
    if (qipState.searchActiveQuery !== expectedQuery) return;

    qipState.searchProducts = data.products || [];
    qipState.searchProductsCount = data.products ? data.products.length : 0;

    // The list-quotations request narrows the left pane separately;
    // we only re-render the right pane here.
    if (qipState.viewMode === "summary") {
      renderSearchSummary();
    }
    qipUpdateSummaryButton();
  } catch (error) {
    if (qipState.searchActiveQuery !== expectedQuery) return;
    errorEl.style.display = "block";
    errorEl.textContent = `Search error: ${error.message}`;
  }
}

function renderSearchSummary() {
  const root = qipShowSummaryShell();
  const products = qipState.searchProducts || [];
  const term = qipState.searchActiveQuery || "";

  if (products.length === 0) {
    root.innerHTML = `
      <header class="qip-search-summary-head">
        <div class="qip-search-summary-title">
          <span class="qip-search-summary-eyebrow">Search</span>
          <strong>${escapeHtml(term)}</strong>
        </div>
        <div class="qip-search-summary-count">
          <strong>0</strong>&nbsp;<span class="qip-card-meta-unit">products</span>
        </div>
      </header>
      <div class="qip-products-empty" style="padding: 2rem 1rem;">
        No products matched <strong>${escapeHtml(term)}</strong>.<br/>
        Quotations whose number, business, or account matches may still appear in the list — click one to view its products.
      </div>
    `;
    return;
  }

  // Group rows by ProductUPC (fall back to description when UPC is blank
  // so unrelated null-UPC products don't all collapse into one row).
  // Per-group fields: summed qty, the unit price (same UPC -> same price
  // by definition), the running line total (sum price*qty), and the set
  // of quotations the group spans.
  const grouped = new Map();
  for (const p of products) {
    const upc = (p.product_upc || "").trim();
    const key = upc
      ? `upc:${upc}`
      : `desc:${(p.product_description || "").trim()}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        product_upc: upc || null,
        product_description: p.product_description || "",
        qty: 0,
        price: null,
        line_total: 0,
        quotations: new Set(),
      });
    }
    const g = grouped.get(key);
    g.qty += p.qty || 0;
    if (p.price != null) {
      // Latest non-null price wins -- same UPC should map to the same
      // price since the lookup is by UPC, but be defensive.
      g.price = p.price;
      g.line_total += p.price * (p.qty || 0);
    }
    if (p.quotation_number) g.quotations.add(p.quotation_number);
  }

  let rowsData = [...grouped.values()].sort((a, b) =>
    (a.product_description || "").localeCompare(b.product_description || ""),
  );
  rowsData = qipSortProducts(rowsData);

  const totalQuotations = new Set(
    products.map((p) => p.quotation_number).filter(Boolean),
  ).size;
  const grandTotal = rowsData.reduce((acc, r) => acc + (r.line_total || 0), 0);

  const rows = rowsData
    .map((r) => {
      return `
        <tr class="qip-summary-row">
          <td class="qip-product-desc">${escapeHtml(r.product_description || "—")}</td>
          <td class="qip-num"><strong>${r.qty.toLocaleString()}</strong></td>
          <td class="qip-num">${qipFormatPrice(r.price)}</td>
          <td class="qip-num"><strong>${qipFormatPrice(r.line_total > 0 ? r.line_total : null)}</strong></td>
        </tr>
      `;
    })
    .join("");

  const totalChip = grandTotal > 0
    ? `<span class="qip-card-meta-sep">·</span>
       <strong>${qipFormatPrice(grandTotal)}</strong>&nbsp;<span class="qip-card-meta-unit">total</span>`
    : "";

  root.innerHTML = `
    <header class="qip-search-summary-head">
      <div class="qip-search-summary-title">
        <span class="qip-search-summary-eyebrow">Search</span>
        <strong>${escapeHtml(term)}</strong>
      </div>
      <div class="qip-search-summary-count">
        <strong>${rowsData.length}</strong>&nbsp;<span class="qip-card-meta-unit">${rowsData.length === 1 ? "product" : "products"}</span>
        <span class="qip-card-meta-sep">·</span>
        <strong>${totalQuotations}</strong>&nbsp;<span class="qip-card-meta-unit">${totalQuotations === 1 ? "quotation" : "quotations"}</span>
        ${totalChip}
      </div>
    </header>
    <table class="qip-products-table qip-summary-table">
      <thead>
        <tr>
          <th class="qip-sortable" data-sort="description">
            <span>Description</span>
            <span class="qip-sort-arrow"></span>
          </th>
          <th class="qip-num qip-sortable" data-sort="qty">
            <span>Qty</span>
            <span class="qip-sort-arrow"></span>
          </th>
          <th class="qip-num qip-sortable" data-sort="price">
            <span>Price</span>
            <span class="qip-sort-arrow"></span>
          </th>
          <th class="qip-num qip-sortable" data-sort="line_total">
            <span>Total</span>
            <span class="qip-sort-arrow"></span>
          </th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  qipUpdateSortIndicators(root.querySelector("thead"));
}

function qipUpdateSummaryButton() {
  const btn = document.getElementById("qip-summary-btn");
  const countEl = document.getElementById("qip-summary-btn-count");
  if (!btn) return;

  const hasSearch = !!(qipState.searchActiveQuery || "").trim();
  if (!hasSearch) {
    btn.hidden = true;
    btn.setAttribute("aria-pressed", "false");
    if (countEl) {
      countEl.hidden = true;
      countEl.textContent = "";
    }
    return;
  }
  btn.hidden = false;
  btn.setAttribute(
    "aria-pressed",
    qipState.viewMode === "summary" ? "true" : "false",
  );
  if (qipState.searchProductsCount > 0) {
    countEl.textContent = String(qipState.searchProductsCount);
    countEl.hidden = false;
  } else {
    countEl.textContent = "";
    countEl.hidden = true;
  }
}

function qipFormatDateTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

function qipFormatTime(value) {
  // QuotationsStatus Dop2/Dop3 are raw strings like "MM/DD/YYYY HH:MM AM/PM"
  // — show the time portion to keep the card compact.
  if (!value) return "";
  const m = String(value).match(/(\d{1,2}:\d{2}\s*[AP]M)/i);
  if (m) return m[1].toUpperCase().replace(/\s+/g, " ");
  const d = new Date(value);
  if (!isNaN(d.getTime())) {
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  return String(value);
}

function qipRelativeTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "";
  const seconds = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

// ============================================================================
// Shopify Analytics
// ============================================================================

const shopifyAnalyticsState = {
  initialized: false,
  loading: false,
  shopifyStores: [],
  rows: [],
  summary: null,
  sortColumn: "subsequent_count",
  sortOrder: "desc",
  abortController: null,
  filter: { status: "all", minCount: 0 },
  returnedThreshold: 1,
  staggerBudget: 0,
};

const SA_NUMERIC_COLUMNS = new Set([
  "first_order_amount",
  "subsequent_count",
  "subsequent_amount",
]);

// Faster than escapeHtml() (which builds a DOM node) — meaningful on
// streaming renders that touch thousands of cells per pass.
const SA_ESCAPE_MAP = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
function saEscape(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => SA_ESCAPE_MAP[c]);
}

// Render coalescer: customer events arrive faster than we can usefully
// repaint a 10k-row table. Trailing-edge throttle keeps the main thread
// responsive; forced render flushes pending work (used on `complete`).
let saRenderTimer = null;
let saRenderPending = false;
const SA_RENDER_THROTTLE_MS = 200;

function requestSaRender(force) {
  if (force) {
    if (saRenderTimer) clearTimeout(saRenderTimer);
    saRenderTimer = null;
    saRenderPending = false;
    renderShopifyAnalyticsTable();
    return;
  }
  if (saRenderPending) return;
  saRenderPending = true;
  saRenderTimer = setTimeout(() => {
    saRenderTimer = null;
    saRenderPending = false;
    renderShopifyAnalyticsTable();
  }, SA_RENDER_THROTTLE_MS);
}

function cancelSaRender() {
  if (saRenderTimer) clearTimeout(saRenderTimer);
  saRenderTimer = null;
  saRenderPending = false;
}

async function loadShopifyAnalyticsPage() {
  if (shopifyAnalyticsState.initialized) {
    return;
  }
  shopifyAnalyticsState.initialized = true;

  try {
    const stores = await apiRequest("/stores");
    shopifyAnalyticsState.shopifyStores = (stores || []).filter(
      (s) => s.store_type === "shopify" && s.is_active,
    );
  } catch (e) {
    shopifyAnalyticsState.shopifyStores = [];
  }

  const select = document.getElementById("sa-store");
  if (select) {
    select.innerHTML = "";
    if (shopifyAnalyticsState.shopifyStores.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(no active Shopify stores)";
      select.appendChild(opt);
      select.disabled = true;
    } else {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Select a store...";
      select.appendChild(placeholder);
      for (const s of shopifyAnalyticsState.shopifyStores) {
        const opt = document.createElement("option");
        opt.value = String(s.id);
        opt.textContent = s.name;
        select.appendChild(opt);
      }
    }
  }

  // Tag input: auto-fill from selected store's saved tag; track dirty state.
  const tagInput = document.getElementById("sa-tag");
  const tagSaveBtn = document.getElementById("sa-tag-save-btn");
  const tagStatus = document.getElementById("sa-tag-status");

  const refreshTagFromStore = () => {
    const storeId = parseInt(select?.value, 10);
    if (!storeId) {
      tagInput.value = "";
      tagInput.disabled = true;
      tagSaveBtn.disabled = true;
      if (tagStatus) tagStatus.textContent = "";
      return;
    }
    const s = shopifyAnalyticsState.shopifyStores.find((x) => x.id === storeId);
    const saved = (s && s.shopify_connection && s.shopify_connection.first_order_tag) || "First order";
    tagInput.value = saved;
    tagInput.disabled = false;
    tagInput.dataset.saved = saved;
    tagSaveBtn.disabled = true;
    if (tagStatus) tagStatus.textContent = "";
  };

  tagInput?.addEventListener("input", () => {
    const dirty = tagInput.value.trim() !== (tagInput.dataset.saved || "");
    tagSaveBtn.disabled = !dirty || !tagInput.value.trim();
    if (tagStatus) tagStatus.textContent = dirty ? "unsaved" : "";
  });

  tagSaveBtn?.addEventListener("click", async () => {
    const storeId = parseInt(select.value, 10);
    const newTag = tagInput.value.trim();
    if (!storeId || !newTag) return;
    tagSaveBtn.disabled = true;
    tagSaveBtn.textContent = "Saving...";
    try {
      const res = await fetch(
        `${API_BASE}/shopify-analytics/stores/${storeId}/tag`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ first_order_tag: newTag }),
        },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      tagInput.dataset.saved = newTag;
      const s = shopifyAnalyticsState.shopifyStores.find((x) => x.id === storeId);
      if (s) {
        s.shopify_connection = s.shopify_connection || {};
        s.shopify_connection.first_order_tag = newTag;
      }
      if (tagStatus) tagStatus.textContent = "saved";
      tagSaveBtn.disabled = true;
    } catch (e) {
      if (tagStatus) tagStatus.textContent = `error: ${e.message || e}`;
      tagSaveBtn.disabled = false;
    } finally {
      tagSaveBtn.textContent = "Save for this store";
    }
  });

  // Default date range: last 30 days
  const startInput = document.getElementById("sa-start-date");
  const endInput = document.getElementById("sa-end-date");
  if (startInput && !startInput.value) {
    const today = new Date();
    const start = new Date(today);
    start.setDate(today.getDate() - 30);
    startInput.value = start.toISOString().slice(0, 10);
    endInput.value = today.toISOString().slice(0, 10);
  }

  // Date range presets
  document.querySelectorAll("[data-sa-range]").forEach((btn) => {
    btn.addEventListener("click", () => saApplyDatePreset(btn.dataset.saRange));
  });

  // Enable/disable Run button on input change
  const updateRunBtn = () => {
    const runBtn = document.getElementById("sa-run-btn");
    if (!runBtn) return;
    const storeId = document.getElementById("sa-store").value;
    const startVal = startInput.value;
    const endVal = endInput.value;
    runBtn.disabled = !(storeId && startVal && endVal && startVal <= endVal);
  };

  document.getElementById("sa-store")?.addEventListener("change", () => {
    refreshTagFromStore();
    updateRunBtn();
  });
  startInput?.addEventListener("change", updateRunBtn);
  endInput?.addEventListener("change", updateRunBtn);
  refreshTagFromStore();
  updateRunBtn();

  document
    .getElementById("sa-run-btn")
    ?.addEventListener("click", runFirstCustomerReturnsReport);
  document
    .getElementById("sa-cancel-btn")
    ?.addEventListener("click", () => {
      if (shopifyAnalyticsState.abortController) {
        shopifyAnalyticsState.abortController.abort();
      }
    });

  // Sortable headers
  const table = document.getElementById("sa-table");
  table?.addEventListener("click", (e) => {
    const th = e.target.closest("th.qip-sortable");
    if (!th) return;
    const col = th.dataset.sort;
    if (!col) return;
    if (shopifyAnalyticsState.sortColumn === col) {
      if (shopifyAnalyticsState.sortOrder === "asc") {
        shopifyAnalyticsState.sortOrder = "desc";
      } else if (shopifyAnalyticsState.sortOrder === "desc") {
        shopifyAnalyticsState.sortColumn = null;
        shopifyAnalyticsState.sortOrder = "asc";
      } else {
        shopifyAnalyticsState.sortOrder = "asc";
      }
    } else {
      shopifyAnalyticsState.sortColumn = col;
      shopifyAnalyticsState.sortOrder = "asc";
    }
    saApplySortHeaders();
    renderShopifyAnalyticsTable();
  });

  saApplySortHeaders();

  // === Filter bar wiring (status chips + min-count input/presets + reset) ===
  document
    .querySelectorAll('#sa-filter-bar [data-sa-status]')
    .forEach((b) => {
      b.addEventListener("click", () => {
        document
          .querySelectorAll('#sa-filter-bar [data-sa-status]')
          .forEach((x) => {
            const on = x === b;
            x.classList.toggle("active", on);
            x.setAttribute("aria-checked", on ? "true" : "false");
          });
        shopifyAnalyticsState.filter.status = b.dataset.saStatus;
        renderShopifyAnalyticsTable();
      });
    });

  const minInput = document.getElementById("sa-min-count");
  const setMin = (n) => {
    const v = Math.max(0, parseInt(n, 10) || 0);
    shopifyAnalyticsState.filter.minCount = v;
    if (minInput) minInput.value = String(v);
    document
      .querySelectorAll('#sa-filter-bar [data-sa-min]')
      .forEach((x) => {
        x.classList.toggle("active", parseInt(x.dataset.saMin, 10) === v);
      });
    renderShopifyAnalyticsTable();
  };
  minInput?.addEventListener("input", () => setMin(minInput.value));
  document
    .querySelectorAll('#sa-filter-bar [data-sa-min]')
    .forEach((b) => {
      b.addEventListener("click", () => setMin(b.dataset.saMin));
    });

  document.getElementById("sa-reset-filters")?.addEventListener("click", () => {
    document
      .querySelector('#sa-filter-bar [data-sa-status="all"]')
      ?.click();
    setMin(0);
  });

  // === Returned KPI threshold toggle (>=1 / >=2 / >=3) ===
  document.querySelectorAll('[data-sa-threshold]').forEach((b) => {
    b.addEventListener("click", () => {
      const t = parseInt(b.dataset.saThreshold, 10) || 1;
      shopifyAnalyticsState.returnedThreshold = t;
      document.querySelectorAll('[data-sa-threshold]').forEach((x) => {
        const on = parseInt(x.dataset.saThreshold, 10) === t;
        x.classList.toggle("active", on);
        x.setAttribute("aria-pressed", on ? "true" : "false");
      });
      // Recompute KPIs without re-rendering the (potentially huge) table.
      renderSaKpis([...shopifyAnalyticsState.rows]);
    });
  });
}

function saApplySortHeaders() {
  const ths = document
    .getElementById("sa-table")
    ?.querySelectorAll("th.qip-sortable");
  if (!ths) return;
  ths.forEach((th) => {
    th.classList.remove("qip-sort-asc", "qip-sort-desc");
    if (th.dataset.sort === shopifyAnalyticsState.sortColumn) {
      th.classList.add(
        shopifyAnalyticsState.sortOrder === "asc"
          ? "qip-sort-asc"
          : "qip-sort-desc",
      );
    }
  });
}

function saApplyDatePreset(range) {
  const startInput = document.getElementById("sa-start-date");
  const endInput = document.getElementById("sa-end-date");
  if (!startInput || !endInput) return;
  const today = new Date();
  let start, end;
  if (range === "7" || range === "30" || range === "90") {
    end = today;
    start = new Date(today);
    start.setDate(today.getDate() - parseInt(range, 10));
  } else if (range === "6m" || range === "12m") {
    end = today;
    start = new Date(today);
    start.setMonth(today.getMonth() - (range === "6m" ? 6 : 12));
  } else if (range === "this-month") {
    start = new Date(today.getFullYear(), today.getMonth(), 1);
    end = today;
  } else if (range === "last-month") {
    start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    end = new Date(today.getFullYear(), today.getMonth(), 0);
  } else if (range === "ytd" || range === "this-year") {
    start = new Date(today.getFullYear(), 0, 1);
    end = today;
  } else if (range === "last-year") {
    start = new Date(today.getFullYear() - 1, 0, 1);
    end = new Date(today.getFullYear() - 1, 11, 31);
  } else {
    return;
  }
  startInput.value = start.toISOString().slice(0, 10);
  endInput.value = end.toISOString().slice(0, 10);
  startInput.dispatchEvent(new Event("change"));
  endInput.dispatchEvent(new Event("change"));
}

async function runFirstCustomerReturnsReport() {
  if (shopifyAnalyticsState.loading) return;

  const storeId = parseInt(document.getElementById("sa-store").value, 10);
  const startDate = document.getElementById("sa-start-date").value;
  const endDate = document.getElementById("sa-end-date").value;
  const tag = (document.getElementById("sa-tag")?.value || "").trim();
  if (!storeId || !startDate || !endDate) return;

  const runBtn = document.getElementById("sa-run-btn");
  const cancelBtn = document.getElementById("sa-cancel-btn");
  const progressEl = document.getElementById("sa-progress");
  const progressBar = document.getElementById("sa-progress-bar");
  const progressStatus = document.getElementById("sa-progress-status");
  const resultsEl = document.getElementById("sa-results");
  const emptyEl = document.getElementById("sa-empty");
  const tbody = document.getElementById("sa-tbody");
  const tfoot = document.getElementById("sa-tfoot");

  shopifyAnalyticsState.loading = true;
  shopifyAnalyticsState.rows = [];
  shopifyAnalyticsState.summary = null;
  shopifyAnalyticsState.abortController = new AbortController();
  shopifyAnalyticsState.staggerBudget = 1; // one render burst gets the fade

  runBtn.disabled = true;
  runBtn.textContent = "Running...";
  cancelBtn.style.display = "inline-flex";
  progressEl.style.display = "block";
  progressBar.style.width = "0%";
  progressBar.style.background = "var(--accent-primary)";
  progressStatus.textContent = "Connecting to Shopify...";
  resultsEl.style.display = "none";
  emptyEl.style.display = "none";
  document.getElementById("sa-kpi-strip")?.setAttribute("hidden", "");
  document.getElementById("sa-filter-bar")?.setAttribute("hidden", "");
  if (tbody) tbody.innerHTML = "";
  if (tfoot) tfoot.style.display = "none";

  try {
    const response = await fetch(
      `${API_BASE}/shopify-analytics/first-customer-returns/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          store_id: storeId,
          start_date: startDate,
          end_date: endDate,
          tag: tag || undefined,
        }),
        signal: shopifyAnalyticsState.abortController.signal,
      },
    );

    if (!response.ok || !response.body) {
      const text = await response.text().catch(() => "");
      throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const messages = buffer.split("\n\n");
      buffer = messages.pop();

      for (const msg of messages) {
        if (!msg.trim()) continue;
        if (msg.startsWith(":")) continue; // heartbeat comment

        const eventMatch = msg.match(/event: (\w+)\ndata: (.+)/s);
        if (!eventMatch) continue;
        const [, eventType, dataStr] = eventMatch;
        let data;
        try {
          data = JSON.parse(dataStr);
        } catch {
          continue;
        }

        if (eventType === "progress") {
          if (data.phase === "started") {
            progressStatus.textContent = `Fetching tagged orders for ${data.store_name || "store"}...`;
          } else if (data.phase === "tagged_orders_complete") {
            progressStatus.textContent = `${data.first_time_customers} first-time customer(s) found — looking up subsequent orders...`;
            progressBar.style.width = "20%";
          } else if (data.phase === "customer_error") {
            progressStatus.textContent = `Customer ${data.completed} of ${data.total} (error: ${data.message})`;
          }
        } else if (eventType === "customer") {
          if (data.row) {
            shopifyAnalyticsState.rows.push(data.row);
          }
          const completed = data.completed || shopifyAnalyticsState.rows.length;
          const total = data.total || completed;
          const pct = 20 + Math.round((completed / Math.max(total, 1)) * 75);
          progressBar.style.width = `${Math.min(pct, 95)}%`;
          progressStatus.textContent = `Processed ${completed} of ${total} customer(s)...`;
          requestSaRender();
          resultsEl.style.display = "block";
          document.getElementById("sa-kpi-strip")?.removeAttribute("hidden");
          document.getElementById("sa-filter-bar")?.removeAttribute("hidden");
        } else if (eventType === "complete") {
          progressBar.style.width = "100%";
          progressStatus.textContent = "Done";
          shopifyAnalyticsState.summary = data.summary || null;
          if (Array.isArray(data.rows) && data.rows.length > 0) {
            shopifyAnalyticsState.rows = data.rows;
          }
          if (shopifyAnalyticsState.rows.length === 0) {
            cancelSaRender();
            resultsEl.style.display = "none";
            emptyEl.style.display = "block";
            document.getElementById("sa-kpi-strip")?.setAttribute("hidden", "");
            document.getElementById("sa-filter-bar")?.setAttribute("hidden", "");
          } else {
            resultsEl.style.display = "block";
            document.getElementById("sa-kpi-strip")?.removeAttribute("hidden");
            document.getElementById("sa-filter-bar")?.removeAttribute("hidden");
            requestSaRender(true);
          }
        } else if (eventType === "error") {
          progressStatus.textContent = `Error: ${data.message || "unknown"}`;
          progressBar.style.background = "var(--danger)";
        }
      }
    }
  } catch (e) {
    if (e.name === "AbortError") {
      progressStatus.textContent = "Cancelled";
    } else {
      progressStatus.textContent = `Error: ${e.message || e}`;
      console.error("Shopify Analytics error:", e);
    }
  } finally {
    shopifyAnalyticsState.loading = false;
    shopifyAnalyticsState.abortController = null;
    cancelSaRender();
    // Final flush in case streaming was cut short by an error or abort
    if (shopifyAnalyticsState.rows.length > 0) {
      renderShopifyAnalyticsTable();
    }
    runBtn.disabled = false;
    runBtn.textContent = "Run Report";
    cancelBtn.style.display = "none";
  }
}

function applyShopifyAnalyticsFilters(rows) {
  const { status, minCount } = shopifyAnalyticsState.filter;
  return rows.filter((r) => {
    const c = r.subsequent_count || 0;
    if (status === "returned" && c < 1) return false;
    if (status === "not_returned" && c !== 0) return false;
    if (minCount > 0 && c < minCount) return false;
    return true;
  });
}

function renderSaKpis(rows) {
  const strip = document.getElementById("sa-kpi-strip");
  if (!strip) return;
  if (rows.length === 0) {
    strip.hidden = true;
    return;
  }
  strip.hidden = false;

  const total = rows.length;
  const threshold = shopifyAnalyticsState.returnedThreshold || 1;
  const returners = rows.filter((r) => (r.subsequent_count || 0) >= 1);
  const meetingThreshold = rows.filter(
    (r) => (r.subsequent_count || 0) >= threshold,
  );
  const subseqOrders = returners.reduce(
    (s, r) => s + (r.subsequent_count || 0),
    0,
  );
  const subseqRev = rows.reduce(
    (s, r) => s + (parseFloat(r.subsequent_amount) || 0),
    0,
  );
  const pct = total ? (meetingThreshold.length / total) * 100 : 0;
  const avg = returners.length ? subseqOrders / returners.length : 0;
  const ccy =
    (rows.find((r) => r.subsequent_currency) || {}).subsequent_currency || "";

  document.getElementById("sa-kpi-total").textContent = total.toLocaleString();
  document.getElementById("sa-kpi-returned").textContent =
    meetingThreshold.length.toLocaleString();
  document.getElementById("sa-kpi-returned-pct").textContent = `${pct.toFixed(1)}%`;
  const subEl = document.getElementById("sa-kpi-returned-sub");
  if (subEl) {
    subEl.textContent = `placed ≥${threshold} successful order${threshold === 1 ? "" : "s"}`;
  }
  document.getElementById("sa-kpi-avg").textContent = avg.toFixed(2);
  document.getElementById("sa-kpi-avg-sub").textContent = returners.length
    ? `among ${returners.length.toLocaleString()} returners`
    : "no returners yet";
  document.getElementById("sa-kpi-rev").textContent =
    subseqRev.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  document.getElementById("sa-kpi-rev-sub").textContent = ccy || "";
}

function renderSaRowCount(visible, total) {
  const el = document.getElementById("sa-row-count");
  if (!el) return;
  el.textContent =
    visible === total
      ? `${total.toLocaleString()} customer${total === 1 ? "" : "s"}`
      : `showing ${visible.toLocaleString()} of ${total.toLocaleString()}`;
  const reset = document.getElementById("sa-reset-filters");
  if (reset) {
    const f = shopifyAnalyticsState.filter;
    reset.hidden = f.status === "all" && f.minCount === 0;
  }
}

function renderShopifyAnalyticsTable() {
  const tbody = document.getElementById("sa-tbody");
  const tfoot = document.getElementById("sa-tfoot");
  if (!tbody) return;

  const rows = [...shopifyAnalyticsState.rows];
  const col = shopifyAnalyticsState.sortColumn;
  const dir = shopifyAnalyticsState.sortOrder === "asc" ? 1 : -1;

  if (col) {
    const numeric = SA_NUMERIC_COLUMNS.has(col);
    rows.sort((a, b) => {
      const av = a[col];
      const bv = b[col];
      if (numeric) {
        const an = parseFloat(av) || 0;
        const bn = parseFloat(bv) || 0;
        return (an - bn) * dir;
      }
      const as = (av || "").toString().toLowerCase();
      const bs = (bv || "").toString().toLowerCase();
      if (as < bs) return -1 * dir;
      if (as > bs) return 1 * dir;
      return 0;
    });
  }

  // KPIs describe the whole cohort, not the active filter view.
  renderSaKpis(rows);

  const visible = applyShopifyAnalyticsFilters(rows);
  renderSaRowCount(visible.length, rows.length);

  // Bar scales to the visible page max so subsets stay readable.
  const maxCount = Math.max(1, ...visible.map((r) => r.subsequent_count || 0));
  const useStagger = shopifyAnalyticsState.staggerBudget > 0;

  tbody.innerHTML = visible
    .map((r, idx) => {
      const c = r.subsequent_count || 0;
      const pct = Math.min(100, Math.round((c / maxCount) * 100));
      const stagger =
        useStagger && idx < 30
          ? ` class="sa-row-fade" style="animation-delay:${idx * 12}ms"`
          : "";
      return `
        <tr${stagger}>
          <td>${saEscape(r.customer_name)}</td>
          <td>${saEscape(r.customer_email)}</td>
          <td>${saEscape(r.first_order_name)}</td>
          <td>${saEscape(r.first_order_date)}</td>
          <td class="sa-num">${saEscape(r.first_order_amount || "0.00")} ${saEscape(r.first_order_currency)}</td>
          <td class="sa-num">
            <span class="sa-count-cell">
              <span class="sa-count-bar" style="--sa-bar:${pct}%"></span>
              <span class="sa-count-num">${c.toLocaleString()}</span>
            </span>
          </td>
          <td class="sa-num">${saEscape(r.subsequent_amount || "0.00")} ${saEscape(r.subsequent_currency)}</td>
        </tr>
      `;
    })
    .join("");

  // Decrement the stagger budget by one render burst, so it fades away.
  if (useStagger) {
    shopifyAnalyticsState.staggerBudget = Math.max(
      0,
      shopifyAnalyticsState.staggerBudget - 1,
    );
  }

  // Footer totals reflect the visible (filtered) set.
  const totalCount = visible.reduce((s, r) => s + (r.subsequent_count || 0), 0);
  const totalAmount = visible.reduce(
    (s, r) => s + (parseFloat(r.subsequent_amount) || 0),
    0,
  );
  const currency =
    (visible.find((r) => r.subsequent_currency) || {}).subsequent_currency || "";
  const totalCountEl = document.getElementById("sa-total-count");
  const totalAmountEl = document.getElementById("sa-total-amount");
  if (totalCountEl) totalCountEl.textContent = totalCount.toLocaleString();
  if (totalAmountEl)
    totalAmountEl.textContent = `${totalAmount.toFixed(2)} ${currency}`.trim();
  if (tfoot) tfoot.style.display = visible.length > 0 ? "" : "none";
}

// ===== Inventory Time =====

const INVENTORY_TIMEOUT_KEY = "inventory_recount_timeout_minutes";
const INVENTORY_ISOLATED_KEY = "isolated_product_recount_minutes";

const inventoryTimeState = {
  initialized: false,
  users: [],
};

function loadInventoryTimePage() {
  if (!inventoryTimeState.initialized) {
    initInventoryTimePage();
    inventoryTimeState.initialized = true;
  }
  loadInventoryTimeUsers();
}

function initInventoryTimePage() {
  invtimeApplyDatePreset("7");

  document
    .getElementById("invtime-calculate-btn")
    ?.addEventListener("click", fetchInventoryTime);

  document
    .getElementById("invtime-controls")
    ?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-range]");
      if (btn) invtimeApplyDatePreset(btn.dataset.range);
    });
}

function invtimeApplyDatePreset(range) {
  const startInput = document.getElementById("invtime-start-date");
  const endInput = document.getElementById("invtime-end-date");
  if (!startInput || !endInput) return;
  const today = new Date();
  let start, end;
  if (range === "7" || range === "30") {
    end = today;
    start = new Date(today);
    start.setDate(today.getDate() - parseInt(range, 10));
  } else if (range === "this-month") {
    start = new Date(today.getFullYear(), today.getMonth(), 1);
    end = today;
  } else if (range === "last-month") {
    start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    end = new Date(today.getFullYear(), today.getMonth(), 0);
  } else {
    return;
  }
  startInput.value = start.toISOString().slice(0, 10);
  endInput.value = end.toISOString().slice(0, 10);
}

async function loadInventoryTimeUsers() {
  const select = document.getElementById("invtime-user");
  const notConfigured = document.getElementById("invtime-not-configured");
  const controls = document.getElementById("invtime-controls");
  if (!select) return;

  try {
    const data = await apiRequest("/inventory-time/users");
    if (!data.configured) {
      if (notConfigured) notConfigured.style.display = "block";
      if (controls) controls.style.display = "none";
      return;
    }
    if (notConfigured) notConfigured.style.display = "none";
    if (controls) controls.style.display = "block";

    inventoryTimeState.users = data.users || [];
    const previous = select.value;
    select.innerHTML = '<option value="">— Select a user —</option>';
    inventoryTimeState.users.forEach((u) => {
      const opt = document.createElement("option");
      opt.value = u;
      opt.textContent = u;
      select.appendChild(opt);
    });
    if (previous && inventoryTimeState.users.includes(previous)) {
      select.value = previous;
    }
  } catch (error) {
    showToast(`✗ Failed to load users: ${error.message}`, "error");
  }
}

async function fetchInventoryTime() {
  const username = document.getElementById("invtime-user")?.value || "";
  const dateFrom = document.getElementById("invtime-start-date")?.value || "";
  const dateTo = document.getElementById("invtime-end-date")?.value || "";

  const loadingEl = document.getElementById("invtime-loading");
  const errorEl = document.getElementById("invtime-error");
  const summaryEl = document.getElementById("invtime-summary");
  const resultsEl = document.getElementById("invtime-results");
  const emptyEl = document.getElementById("invtime-empty");

  errorEl.style.display = "none";
  if (!username) {
    errorEl.textContent = "Please select a user.";
    errorEl.style.display = "block";
    return;
  }
  if (!dateFrom || !dateTo) {
    errorEl.textContent = "Please select a date range.";
    errorEl.style.display = "block";
    return;
  }

  loadingEl.style.display = "block";
  summaryEl.style.display = "none";
  resultsEl.style.display = "none";
  emptyEl.style.display = "none";

  try {
    const data = await apiRequest("/inventory-time", {
      method: "POST",
      body: JSON.stringify({
        username,
        date_from: dateFrom,
        date_to: dateTo,
      }),
    });
    if (!data.configured) {
      errorEl.textContent =
        "The DB_ADMIN store is not configured. Set it under Settings → Roles & Mirrors.";
      errorEl.style.display = "block";
      return;
    }
    renderInventoryTime(data);
  } catch (error) {
    errorEl.textContent = `Failed to calculate: ${error.message}`;
    errorEl.style.display = "block";
  } finally {
    loadingEl.style.display = "none";
  }
}

function renderInventoryTime(data) {
  const summaryEl = document.getElementById("invtime-summary");
  const resultsEl = document.getElementById("invtime-results");
  const emptyEl = document.getElementById("invtime-empty");
  const tbody = document.getElementById("invtime-tbody");

  document.getElementById("invtime-total").textContent = formatDuration(
    data.total_seconds,
  );
  document.getElementById("invtime-session-count").textContent =
    data.session_count.toLocaleString();
  document.getElementById("invtime-item-count").textContent =
    data.item_count.toLocaleString();
  document.getElementById("invtime-settings-info").textContent =
    `${data.timeout_minutes} min / ${data.isolated_minutes} min`;
  summaryEl.style.display = "block";

  const sessions = data.sessions || [];
  if (sessions.length === 0) {
    resultsEl.style.display = "none";
    emptyEl.style.display = "block";
    return;
  }
  emptyEl.style.display = "none";

  tbody.innerHTML = "";
  sessions.forEach((s, index) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td style="color: var(--text-tertiary)">${index + 1}</td>
      <td>${escapeHtml(formatDateTime(s.start))}</td>
      <td>${escapeHtml(formatDateTime(s.end))}</td>
      <td style="text-align: right">${s.item_count.toLocaleString()}</td>
      <td style="text-align: right">${escapeHtml(formatDuration(s.seconds))}</td>
    `;
    tbody.appendChild(row);
  });
  resultsEl.style.display = "block";
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return (
    d.toLocaleDateString() +
    " " +
    d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
}

function formatDuration(seconds) {
  const total = Math.round(seconds || 0);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

async function loadInventoryTimeSettings() {
  const timeoutInput = document.getElementById("inventory-timeout-minutes");
  const isolatedInput = document.getElementById("inventory-isolated-minutes");

  if (timeoutInput) {
    try {
      const resp = await fetch(`${API_BASE}/settings/${INVENTORY_TIMEOUT_KEY}`);
      timeoutInput.value = resp.ok ? (await resp.json()).value || "10" : "10";
    } catch {
      timeoutInput.value = "10";
    }
  }
  if (isolatedInput) {
    try {
      const resp = await fetch(`${API_BASE}/settings/${INVENTORY_ISOLATED_KEY}`);
      isolatedInput.value = resp.ok ? (await resp.json()).value || "1" : "1";
    } catch {
      isolatedInput.value = "1";
    }
  }
}

async function saveSetting(key, value, description) {
  const patchResp = await fetch(`${API_BASE}/settings/${key}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!patchResp.ok) {
    await apiRequest("/settings", {
      method: "POST",
      body: JSON.stringify({ key, value, description }),
    });
  }
}

async function saveInventoryTimeSettings() {
  const timeout = document.getElementById("inventory-timeout-minutes")?.value;
  const isolated = document.getElementById("inventory-isolated-minutes")?.value;

  try {
    await saveSetting(
      INVENTORY_TIMEOUT_KEY,
      timeout,
      "Inventory Time: break-timeout in minutes (gap larger than this starts a new session).",
    );
    await saveSetting(
      INVENTORY_ISOLATED_KEY,
      isolated,
      "Inventory Time: minutes credited for an isolated single-item recount session.",
    );
    showToast("✓ Inventory Time settings saved", "success");
  } catch (error) {
    showToast(`✗ Failed to save: ${error.message}`, "error");
  }
}

document
  .getElementById("inventory-time-settings-save")
  ?.addEventListener("click", saveInventoryTimeSettings);
