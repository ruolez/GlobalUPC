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
  } else if (page === "shopify-sales") {
    loadShopifySalesPage();
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
  await loadExclusions();
  await loadStoreMirrors();
  await loadItemTrackerExclusions();
  await loadShopifySalesSettings();

  // Set dropdown value to saved preference
  const savedLandingPage = getDefaultLandingPage();
  const dropdown = document.getElementById("default-landing-page");
  if (dropdown) {
    dropdown.value = savedLandingPage;
  }
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

    // Toggle/delete button listeners
    document
      .getElementById(`toggle-${store.id}`)
      ?.addEventListener("click", () => toggleStore(store.id));
    document
      .getElementById(`delete-${store.id}`)
      ?.addEventListener("click", () => deleteStore(store.id));
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
                        <h4>${store.name}</h4>
                        <span class="store-type-badge ${store.store_type}">${store.store_type.toUpperCase()}</span>
                    </div>
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

async function navigateToItemTrackerWithUpc(upc, days = null) {
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

  if (days && days > 0) {
    const today = new Date();
    const fromDate = new Date();
    fromDate.setDate(today.getDate() - days);
    document.getElementById("item-tracker-date-from").value = formatDateForInput(fromDate);
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
        tr.dataset.barcode = upc;

        const currentPrice = p.unit_price != null ? parseFloat(p.unit_price).toFixed(2) : "-";
        const currentCost = p.unit_cost != null ? parseFloat(p.unit_cost).toFixed(2) : "-";
        const currentDeliveryB = p.unit_delivery_b != null ? parseFloat(p.unit_delivery_b).toFixed(2) : "-";
        tr.dataset.currentPrice = currentPrice;
        tr.dataset.currentCost = currentCost;
        tr.dataset.currentDeliveryB = currentDeliveryB;
        const mssqlDesc = p.product_description ? escapeHtml(p.product_description) : "-";
        const mPrice = p.unit_price != null ? parseFloat(p.unit_price) : null;
        const mCost = p.unit_cost != null ? parseFloat(p.unit_cost) : null;
        const mMarkup = formatMarkup(mPrice, mCost);
        const mCostMarkup = formatCostMarkup(mCost, primaryCost, p.store_id);
        const isPrimary = p.store_id === primaryStoreId;
        const deliveryBCell = isPrimary
          ? `<td>${currentValueSpan(currentDeliveryB)}<input type="number" class="dark-input price-input new-delivery-b" step="0.01" min="0" placeholder="${currentDeliveryB}"></td>`
          : `<td style="color: var(--text-tertiary)">-</td>`;
        tr.innerHTML = `
          <td style="font-size: 0.875rem; color: var(--text-primary)">${mssqlDesc} [${escapeHtml(upc)}]</td>
          <td>${currentValueSpan(currentPrice)}<input type="number" class="dark-input price-input new-price" step="0.01" min="0" placeholder="${currentPrice}"></td>
          <td>${currentValueSpan(currentCost)}<input type="number" class="dark-input price-input new-cost" step="0.01" min="0" placeholder="${currentCost}"></td>
          ${deliveryBCell}
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
      tr.dataset.barcode = sp.sibling_barcode;

      const currentPrice = sp.unit_price != null ? parseFloat(sp.unit_price).toFixed(2) : "-";
      const currentCost = sp.unit_cost != null ? parseFloat(sp.unit_cost).toFixed(2) : "-";
      const currentDeliveryB = sp.unit_delivery_b != null ? parseFloat(sp.unit_delivery_b).toFixed(2) : "-";
      tr.dataset.currentPrice = currentPrice;
      tr.dataset.currentCost = currentCost;
      tr.dataset.currentDeliveryB = currentDeliveryB;
      const spPrice = sp.unit_price != null ? parseFloat(sp.unit_price) : null;
      const spCost = sp.unit_cost != null ? parseFloat(sp.unit_cost) : null;
      const spMarkup = formatMarkup(spPrice, spCost);
      const spCostMarkup = formatCostMarkup(spCost, primaryCost, sp.store_id);
      const siblingLabel = `${escapeHtml(sp.product_description || sp.sibling_variant_title || "-")} [${escapeHtml(sp.sibling_barcode)}]`;
      const isPrimarySibling = sp.store_id === primaryStoreId;
      const siblingDeliveryBCell = isPrimarySibling
        ? `<td>${currentValueSpan(currentDeliveryB)}<input type="number" class="dark-input price-input new-delivery-b" step="0.01" min="0" placeholder="${currentDeliveryB}"></td>`
        : `<td style="color: var(--text-tertiary)">-</td>`;

      tr.innerHTML = `
        <td style="color: var(--text-secondary); font-size: 0.875rem">${siblingLabel}</td>
        <td>${currentValueSpan(currentPrice)}<input type="number" class="dark-input price-input new-price" step="0.01" min="0" placeholder="${currentPrice}"></td>
        <td>${currentValueSpan(currentCost)}<input type="number" class="dark-input price-input new-cost" step="0.01" min="0" placeholder="${currentCost}"></td>
        ${siblingDeliveryBCell}
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

  const fillGroup = document.getElementById("price-delivery-b-fill-group");
  if (fillGroup) fillGroup.style.display = display;

  document.querySelectorAll("#price-updates-tbody tr").forEach((tr) => {
    const cells = tr.children;
    if (cells.length >= 4) cells[3].style.display = display;
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

  const rowSelector = '#price-updates-tbody tr:not(.store-header-row):not([style*="display: none"]):not(.price-excluded)';

  const primaryStoreId = priceUpdatesState.config?.primaryStoreId;
  const primaryCost = priceUpdatesState.primaryCost;
  let applyCostMarkup = false;
  if (newCost !== "" && primaryStoreId && primaryCost && primaryCost > 0) {
    applyCostMarkup = !!document.querySelector(
      `${rowSelector}[data-store-id="${primaryStoreId}"]`
    );
  }

  let filledCount = 0;
  document
    .querySelectorAll(rowSelector)
    .forEach((tr) => {
      let filled = false;
      let rowCost = newCost;

      if (newCost !== "") {
        if (applyCostMarkup && String(tr.dataset.storeId) !== String(primaryStoreId)) {
          const currentRowCost = parseFloat(tr.dataset.currentCost);
          if (currentRowCost && !isNaN(currentRowCost) && currentRowCost > 0) {
            rowCost = roundUpTo5Cents(parseFloat(newCost) * (currentRowCost / primaryCost)).toFixed(2);
          }
        }
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
      } else if (newCost !== "") {
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

    const newPrice = priceInput?.value ? parseFloat(priceInput.value) : null;
    const newCost = costInput?.value ? parseFloat(costInput.value) : null;
    const newDeliveryB = deliveryBInput?.value ? parseFloat(deliveryBInput.value) : null;

    if (newPrice === null && newCost === null && newDeliveryB === null) return;

    const oldPrice = priceInput?.placeholder && priceInput.placeholder !== "-"
      ? parseFloat(priceInput.placeholder) : null;
    const oldCost = costInput?.placeholder && costInput.placeholder !== "-"
      ? parseFloat(costInput.placeholder) : null;
    const oldDeliveryB = deliveryBInput?.placeholder && deliveryBInput.placeholder !== "-"
      ? parseFloat(deliveryBInput.placeholder) : null;
    const productDesc = tr.querySelector("td:first-child")?.textContent?.trim() || null;

    if (storeType === "mssql") {
      updates.push({
        store_id: storeId,
        store_type: "mssql",
        upc: tr.dataset.barcode || null,
        new_price: newPrice,
        new_cost: newCost,
        new_delivery_b: newDeliveryB,
        old_price: oldPrice,
        old_cost: oldCost,
        old_delivery_b: oldDeliveryB,
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
          changes: item.changes.replace(/Delivery B [^,]+,?\s*/g, "").replace(/,\s*$/, ""),
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
                let costUpdated = false;

                [
                  { input: priceInput, dataKey: "currentPrice" },
                  { input: costInput, dataKey: "currentCost" },
                  { input: deliveryBInput, dataKey: "currentDeliveryB" },
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

  // Markup (5th td, index 4)
  if (price != null && cost != null && cost !== 0) {
    const val = ((price - cost) / cost) * 100;
    const color = val > 0 ? "var(--success)" : val < 0 ? "var(--danger)" : "";
    tds[4].textContent = val.toFixed(1) + "%";
    tds[4].style.color = hasTyped ? (color || "var(--accent-primary)") : color;
  } else {
    tds[4].textContent = "-";
    tds[4].style.color = "";
  }

  // Cost markup (6th td, index 5)
  const pCost = priceUpdatesState.primaryCost;
  const storeId = parseInt(tr.dataset.storeId);
  const primaryStoreId = priceUpdatesState.config?.primaryStoreId;
  if (storeId === primaryStoreId) {
    tds[5].textContent = "-";
    tds[5].style.color = "";
  } else if (cost != null && pCost != null && pCost !== 0) {
    const val = ((cost - pCost) / pCost) * 100;
    const color = val > 0 ? "var(--danger)" : val < 0 ? "var(--success)" : "";
    tds[5].textContent = val.toFixed(1) + "%";
    tds[5].style.color = hasTyped ? (color || "var(--accent-primary)") : color;
  } else {
    tds[5].textContent = "-";
    tds[5].style.color = "";
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

    if (priceInput && entry.new_price != null) priceInput.value = parseFloat(entry.new_price).toFixed(2);
    if (costInput && entry.new_cost != null) costInput.value = parseFloat(entry.new_cost).toFixed(2);
    if (deliveryBInput && entry.new_delivery_b != null) deliveryBInput.value = parseFloat(entry.new_delivery_b).toFixed(2);

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

  summaryEl.textContent = `${summary.total_items} products \u00b7 ${summary.total_quantity?.toLocaleString()} units sold \u00b7 $${parseFloat(summary.total_revenue || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} total revenue \u00b7 ${summary.stores_searched} store(s) \u00b7 ${summary.date_range?.start} to ${summary.date_range?.end}`;

  const sorted = sortShopifySalesResults(results);

  tbody.innerHTML = "";
  sorted.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(r.store_name)}</td>
      <td>${escapeHtml(r.product_title)}</td>
      <td>${escapeHtml(r.variant_title || "")}</td>
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

  const headers = ["Store", "Product", "Variant", "UPC", "SKU", "Cost", "Avg Price", "Qty", "Revenue"];
  const dataRows = shopifySalesResults.results.map((r) => [
    r.store_name || "",
    r.product_title || "",
    r.variant_title || "",
    r.barcode || "",
    r.sku || "",
    r.cost != null ? parseFloat(r.cost) : null,
    parseFloat(r.avg_price),
    r.total_quantity,
    parseFloat(r.total_revenue),
  ]);

  const totalQty = shopifySalesResults.results.reduce((s, r) => s + r.total_quantity, 0);
  const totalRev = shopifySalesResults.results.reduce((s, r) => s + parseFloat(r.total_revenue), 0);
  const totalsRow = ["", "", "", "", "", "Totals", "", totalQty, totalRev];

  const wsData = [headers, ...dataRows, totalsRow];
  const ws = XLSX.utils.aoa_to_sheet(wsData);

  const colWidths = [18, 40, 20, 16, 16, 10, 12, 10, 14];
  ws["!cols"] = colWidths.map((w) => ({ wch: w }));

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Shopify Sales");

  const startDate = document.getElementById("shopify-sales-start-date").value;
  const endDate = document.getElementById("shopify-sales-end-date").value;
  XLSX.writeFile(wb, `shopify-sales-${startDate}-to-${endDate}.xlsx`);
}

// ===== End Shopify Sales =====

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  const savedTheme = localStorage.getItem("selectedTheme") || "author-light";
  setTheme(savedTheme);

  const params = new URLSearchParams(window.location.search);
  const trackerUpc = params.get("tracker");
  const trackerDays = params.get("days");

  if (trackerUpc) {
    navigateToItemTrackerWithUpc(trackerUpc, trackerDays ? parseInt(trackerDays, 10) : null);
  } else {
    const defaultPage = getDefaultLandingPage();
    navigateTo(defaultPage);
  }
});
