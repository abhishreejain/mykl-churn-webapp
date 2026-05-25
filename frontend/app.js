const apiBase = resolveApiBase();

const input = document.getElementById("workbookInput");
const chooseBtn = document.getElementById("chooseFileBtn");
const generateBtn = document.getElementById("generateBtn");
const selectedFileText = document.getElementById("selectedFileText");
const statusFileName = document.getElementById("statusFileName");
const statusJobId = document.getElementById("statusJobId");
const statusMessage = document.getElementById("statusMessage");
const statusTitle = document.getElementById("statusTitle");
const statusCard = document.querySelector(".status-card");
const preRunWorkspace = document.getElementById("preRunWorkspace");
const postRunWorkspace = document.getElementById("postRunWorkspace");
const downloadBtn = document.getElementById("downloadBtn");
const downloadHint = document.getElementById("downloadHint");

const redCountEl = document.getElementById("redCount");
const orangeCountEl = document.getElementById("orangeCount");
const greenCountEl = document.getElementById("greenCount");
const otherCountEl = document.getElementById("otherCount");
const totalCountEl = document.getElementById("totalCount");
const redMeterEl = document.getElementById("redMeter");
const orangeMeterEl = document.getElementById("orangeMeter");
const greenMeterEl = document.getElementById("greenMeter");
const activeFilterTextEl = document.getElementById("activeFilterText");
const stateFilterSelect = document.getElementById("stateFilterSelect");
const riskButtons = document.getElementById("riskButtons");
const potentialButtons = document.getElementById("potentialButtons");
const influencerRows = document.getElementById("influencerRows");
const influencerListHint = document.getElementById("influencerListHint");

const state = {
  selectedFile: null,
  jobId: null,
  dashboard: null,
  filterState: "ALL",
  filterRisk: "ALL",
  filterPotentialLevel: "ALL",
  downloadReady: false,
};

const STATUS_CLASS_NAMES = ["info", "processing", "success", "warn", "error"];

if (chooseBtn && input) {
  chooseBtn.addEventListener("click", () => input.click());
}

if (input) {
  input.addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0] ? event.target.files[0] : null;
    state.selectedFile = file;
    state.jobId = null;
    state.downloadReady = false;
    statusJobId.textContent = "None";
    hideDownload();
    resetDashboardView();

    if (!file) {
      selectedFileText.textContent = "None";
      statusFileName.textContent = "None";
      setStatus("Current status", "Choose an Excel file and click Generate when you are ready.", "info");
      return;
    }

    selectedFileText.textContent = file.name;
    statusFileName.textContent = file.name;
    if (!isValidWorkbook(file.name)) {
      setStatus("Current status", "Invalid file type. Please select a .xlsx or .xls workbook.", "error");
      return;
    }
    setStatus("Current status", "Workbook selected. Click Generate to run churn and potential processing.", "info");
  });
}

if (generateBtn) {
  generateBtn.addEventListener("click", async () => {
    if (!state.selectedFile) {
      setStatus("Current status", "Please select a workbook before generating.", "error");
      return;
    }
    if (!isValidWorkbook(state.selectedFile.name)) {
      setStatus("Current status", "Cannot proceed. Selected file type is not supported.", "error");
      return;
    }

    disableRunUi(true);
    hideDownload();
    resetDashboardView();

    try {
      await assertBackendReachable();
      setStatus("Current status", "Uploading workbook...", "processing");
      const uploadPayload = await uploadWorkbook(state.selectedFile);
      const jobId = (uploadPayload.job_id || uploadPayload.jobId || "").trim();
      if (!jobId) {
        throw new Error("Upload completed but no job ID was returned.");
      }
      state.jobId = jobId;
      statusJobId.textContent = jobId;

      setStatus("Current status", "Workbook uploaded. Running churn scoring and potential enrichment...", "processing");
      const processPayload = await processWorkbook(jobId);
      const processStatus = String(processPayload.status || "").toLowerCase();
      const completed = processPayload.ok === true && (processStatus === "completed" || processStatus === "success");

      if (!completed) {
        const warningMessage =
          processPayload.message ||
          "Processing did not complete fully. Please review the status message and backend logs.";
        setStatus("Run status", warningMessage, "warn");
        return;
      }

      setStatus("Current status", "Processing complete. Loading dashboard data...", "processing");
      const dashboardPayload = await fetchDashboard(jobId);
      state.dashboard = dashboardPayload;
      primeFiltersFromDashboard(dashboardPayload);
      renderDashboard(dashboardPayload);

      showDashboardWorkspace();
      showDownload(jobId);
      setStatus("Generation complete", "Dashboard is ready. You can filter records and download the final output.", "success");
    } catch (error) {
      const message = friendlyErrorMessage(error);
      setStatus("Current status", message, "error");
    } finally {
      disableRunUi(false);
    }
  });
}

if (stateFilterSelect) {
  stateFilterSelect.addEventListener("change", (event) => {
    state.filterState = String(event.target.value || "ALL");
    renderFilteredInfluencerRows();
  });
}

if (riskButtons) {
  riskButtons.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-filter-type='risk']");
    if (!btn) return;
    state.filterRisk = String(btn.dataset.filterValue || "ALL");
    markActiveButton(riskButtons, state.filterRisk);
    renderFilteredInfluencerRows();
  });
}

if (potentialButtons) {
  potentialButtons.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-filter-type='potential']");
    if (!btn) return;
    state.filterPotentialLevel = String(btn.dataset.filterValue || "ALL");
    markActiveButton(potentialButtons, state.filterPotentialLevel);
    renderFilteredInfluencerRows();
  });
}

function isValidWorkbook(name) {
  const lowered = String(name || "").toLowerCase();
  return lowered.endsWith(".xlsx") || lowered.endsWith(".xls");
}

async function uploadWorkbook(file) {
  const formData = new FormData();
  formData.append("file", file, file.name);
  const response = await fetch(`${apiBase}/api/upload`, {
    method: "POST",
    body: formData,
  });
  const payload = await parseJsonResponse(response);
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || "Upload failed. Please check input format and try again.");
  }
  return payload;
}

async function processWorkbook(jobId) {
  const response = await fetch(`${apiBase}/api/process/${encodeURIComponent(jobId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const payload = await parseJsonResponse(response);
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || "Processing failed at backend stage.");
  }
  return payload;
}

async function fetchDashboard(jobId) {
  const response = await fetch(`${apiBase}/api/dashboard/${encodeURIComponent(jobId)}`);
  const payload = await parseJsonResponse(response);
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || "Dashboard data is not available yet.");
  }
  return payload;
}

async function parseJsonResponse(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  return payload || {};
}

function renderDashboard(dashboardPayload) {
  buildStateFilter(dashboardPayload.state_list || []);
  buildRiskButtons(dashboardPayload.risk_list || []);
  buildPotentialButtons(dashboardPayload.potential_level_list || []);
  renderFilteredInfluencerRows();
}

function primeFiltersFromDashboard(dashboardPayload) {
  const states = dashboardPayload.state_list || [];
  const risks = dashboardPayload.risk_list || [];
  const levels = dashboardPayload.potential_level_list || [];

  state.filterState = states.length > 0 ? "ALL" : "ALL";
  state.filterRisk = risks.length > 0 ? "ALL" : "ALL";
  state.filterPotentialLevel = levels.length > 0 ? "ALL" : "ALL";
}

function buildStateFilter(states) {
  stateFilterSelect.innerHTML = "";
  const allOption = document.createElement("option");
  allOption.value = "ALL";
  allOption.textContent = "All States";
  stateFilterSelect.appendChild(allOption);

  states.forEach((entry) => {
    const value = String(entry || "").trim();
    if (!value) return;
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    stateFilterSelect.appendChild(option);
  });
  stateFilterSelect.value = state.filterState;
}

function buildRiskButtons(risks) {
  riskButtons.innerHTML = "";
  riskButtons.appendChild(createFilterButton("risk", "ALL", "All Risks", state.filterRisk === "ALL"));

  risks.forEach((entry) => {
    const value = String(entry || "").trim();
    if (!value) return;
    riskButtons.appendChild(createFilterButton("risk", value, value, state.filterRisk === value));
  });
}

function buildPotentialButtons(levels) {
  potentialButtons.innerHTML = "";
  potentialButtons.appendChild(
    createFilterButton("potential", "ALL", "All Potential Levels", state.filterPotentialLevel === "ALL")
  );

  levels.forEach((entry) => {
    const value = String(entry || "").trim();
    if (!value) return;
    potentialButtons.appendChild(createFilterButton("potential", value, value, state.filterPotentialLevel === value));
  });
}

function createFilterButton(type, value, label, active) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `pill-btn${active ? " active" : ""}`;
  button.dataset.filterType = type;
  button.dataset.filterValue = value;
  button.textContent = label;
  return button;
}

function markActiveButton(container, value) {
  container.querySelectorAll("button[data-filter-value]").forEach((button) => {
    const isActive = String(button.dataset.filterValue || "") === String(value);
    button.classList.toggle("active", isActive);
  });
}

function renderFilteredInfluencerRows() {
  if (!state.dashboard) return;
  const records = Array.isArray(state.dashboard.influencer_records) ? state.dashboard.influencer_records : [];
  updateSummaryCardsByState(records);
  const filtered = records.filter((record) => matchesFilters(record));

  influencerRows.innerHTML = "";
  if (filtered.length === 0) {
    influencerListHint.textContent = "No influencers found for the selected filters.";
  } else {
    influencerListHint.textContent = `${filtered.length} influencer(s) in current selection.`;
  }

  filtered.forEach((record) => {
    const row = document.createElement("tr");
    appendCell(row, safeText(record.customer_name));
    appendCell(row, safeText(record.customer_mobile_number));
    appendCell(row, safeText(record.risk));
    appendCell(row, safeText(record.potential_level));
    appendCell(row, safeText(record.priority_bucket));
    appendCell(row, formatNumber(record.churn_probability, 4));
    appendCell(row, formatNumber(record.potential, 0));
    influencerRows.appendChild(row);
  });

  activeFilterTextEl.textContent = `${prettyFilterValue(state.filterState, "All States")} | ${prettyFilterValue(
    state.filterRisk,
    "All Risks"
  )} | ${prettyFilterValue(state.filterPotentialLevel, "All Potential Levels")}`;
}

function updateSummaryCardsByState(records) {
  const stateScoped = records.filter((record) => {
    if (state.filterState === "ALL") return true;
    return normalizeValue(record.state) === normalizeValue(state.filterState);
  });

  const counts = { RED: 0, ORANGE: 0, GREEN: 0, OTHER: 0 };
  stateScoped.forEach((record) => {
    const bucket = normalizeValue(record.priority_bucket);
    if (bucket === "RED") counts.RED += 1;
    else if (bucket === "ORANGE") counts.ORANGE += 1;
    else if (bucket === "GREEN") counts.GREEN += 1;
    else counts.OTHER += 1;
  });

  const totalCount = counts.RED + counts.ORANGE + counts.GREEN + counts.OTHER;
  redCountEl.textContent = String(counts.RED);
  orangeCountEl.textContent = String(counts.ORANGE);
  greenCountEl.textContent = String(counts.GREEN);
  otherCountEl.textContent = String(counts.OTHER);
  totalCountEl.textContent = String(totalCount);

  setMeterWidth(redMeterEl, counts.RED, totalCount);
  setMeterWidth(orangeMeterEl, counts.ORANGE, totalCount);
  setMeterWidth(greenMeterEl, counts.GREEN, totalCount);
}

function matchesFilters(record) {
  const stateOk = state.filterState === "ALL" || normalizeValue(record.state) === normalizeValue(state.filterState);
  const riskOk = state.filterRisk === "ALL" || normalizeValue(record.risk) === normalizeValue(state.filterRisk);
  const potentialOk =
    state.filterPotentialLevel === "ALL" ||
    normalizeValue(record.potential_level) === normalizeValue(state.filterPotentialLevel);
  return stateOk && riskOk && potentialOk;
}

function setMeterWidth(element, numerator, denominator) {
  if (!element) return;
  if (!denominator || denominator <= 0) {
    element.style.width = "0%";
    return;
  }
  const pct = Math.max(0, Math.min(100, (Number(numerator) / Number(denominator)) * 100));
  element.style.width = `${pct.toFixed(1)}%`;
}

function showDashboardWorkspace() {
  preRunWorkspace.classList.add("hidden");
  postRunWorkspace.classList.remove("hidden");
}

function resetDashboardView() {
  state.dashboard = null;
  preRunWorkspace.classList.remove("hidden");
  postRunWorkspace.classList.add("hidden");
}

function setStatus(title, message, kind) {
  statusTitle.textContent = title;
  statusMessage.textContent = message;
  STATUS_CLASS_NAMES.forEach((token) => statusCard.classList.remove(token));
  statusCard.classList.add(kind || "info");
}

function disableRunUi(disabled) {
  chooseBtn.disabled = disabled;
  generateBtn.disabled = disabled;
  input.disabled = disabled;
  if (disabled) {
    generateBtn.textContent = "Running...";
  } else {
    generateBtn.textContent = "Generate Dashboard";
  }
}

function showDownload(jobId) {
  state.downloadReady = true;
  downloadHint.textContent = "Final enriched output is ready.";
  downloadBtn.classList.remove("hidden");
  downloadBtn.disabled = false;
  downloadBtn.onclick = () => {
    window.location.href = `${apiBase}/api/download/${encodeURIComponent(jobId)}/final`;
  };
}

function hideDownload() {
  state.downloadReady = false;
  downloadHint.textContent = "Download button will appear after a successful run.";
  downloadBtn.classList.add("hidden");
  downloadBtn.disabled = true;
  downloadBtn.onclick = null;
}

function friendlyErrorMessage(error) {
  const message = error && error.message ? String(error.message) : "Unexpected error while running workflow.";
  if (message.toLowerCase().includes("failed to fetch")) {
    return `Could not reach backend API at ${apiBase || window.location.origin}. Start backend server and try again.`;
  }
  return message || "Unexpected error while running workflow.";
}

function resolveApiBase() {
  const queryApiBase = new URLSearchParams(window.location.search).get("apiBase");
  if (queryApiBase && queryApiBase.trim()) {
    return queryApiBase.trim().replace(/\/+$/, "");
  }
  if (window.MYKL_API_BASE && String(window.MYKL_API_BASE).trim()) {
    return String(window.MYKL_API_BASE).trim().replace(/\/+$/, "");
  }
  if (window.location.protocol === "file:") {
    return "https://mykl-churn-webapp.onrender.com";
  }
  if (
    (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost") &&
    window.location.port !== "8000"
  ) {
    return "https://mykl-churn-webapp.onrender.com";
  }
  return "";
}

async function assertBackendReachable() {
  const healthUrl = `${apiBase}/api/health`;
  try {
    const response = await fetch(healthUrl, { method: "GET" });
    if (!response.ok) {
      throw new Error(`Backend health check failed with HTTP ${response.status}.`);
    }
  } catch (error) {
    throw new Error(`Could not reach backend API at ${apiBase}. Start backend server and try again.`);
  }
}

function safeText(value) {
  if (value === null || value === undefined) return "";
  return String(value);
}

function normalizeValue(value) {
  return String(value || "")
    .trim()
    .toUpperCase();
}

function toSafeInt(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.trunc(parsed));
}

function formatNumber(value, precision) {
  if (value === null || value === undefined || value === "") return "";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "";
  return parsed.toFixed(precision);
}

function prettyFilterValue(value, fallback) {
  if (!value || value === "ALL") return fallback;
  return value;
}

function appendCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  row.appendChild(cell);
}
