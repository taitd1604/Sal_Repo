const currency = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0,
});

const VIEW_SCOPES = {
  all: {
    label: "Tổng",
    caption: "Toàn bộ ca đã ghi nhận",
  },
  open_mic: {
    label: "Open mic",
    caption: "Các buổi open mic",
    predicate: (row) => eventTypeMatches(row.event_type, ["open mic", "openmic"]),
  },
  live_show: {
    label: "Đêm nhạc",
    caption: "Các đêm nhạc",
    predicate: (row) => eventTypeMatches(row.event_type, ["dem nhac", "demnhac"]),
  },
};

const state = {
  rows: [],
  chart: null,
  filters: {
    eventType: "all",
    scope: getInitialScope(),
    month: getInitialMonth(),
  },
};

async function init() {
  setupScopeFilter();
  setupEventFilter();
  setupMonthFilter();
  try {
    const rows = await loadCsv("./data/shifts_public.csv");
    state.rows = rows;
    if (!rows.length) {
      updateMonthOptions([]);
      updateEventFilterOptions([]);
      renderEmptyState();
      return;
    }
    updateMonthOptions(rows);
    updateEventFilterOptions(getScopeAndMonthRows());
    refreshDashboard();
  } catch (error) {
    console.error(error);
    document.getElementById("shift-rows").innerHTML =
      `<tr><td colspan="6">Không thể tải dữ liệu: ${error.message}</td></tr>`;
  }
}

async function loadCsv(path) {
  const response = await fetch(`${path}?t=${Date.now()}`);
  if (!response.ok) {
    throw new Error("Không tìm thấy file dữ liệu");
  }
  const text = await response.text();
  const parsed = Papa.parse(text, { header: true });
  return parsed.data
    .filter((row) => row.date)
    .map((row) => ({
      ...row,
      ot_minutes: Number(row.ot_minutes || 0),
      ot_pay: Number(row.ot_pay || 0),
      total_pay: Number(row.total_pay || 0),
    }));
}

function updateSummary(rows) {
  if (!rows.length) {
    document.getElementById("total-shifts").textContent = "0";
    document.getElementById("total-ot").textContent = "0";
    document.getElementById("total-ot-pay").textContent = "0";
    document.getElementById("total-pay").textContent = "0";
    const stamp = document.getElementById("last-updated");
    if (stamp) {
      stamp.textContent = "Chưa có dữ liệu cho chế độ này";
    }
    return;
  }
  const totalShifts = rows.length;
  const totalOt = rows.reduce((sum, row) => sum + row.ot_minutes, 0);
  const totalOtPay = rows.reduce((sum, row) => sum + row.ot_pay, 0);
  const totalPay = rows.reduce((sum, row) => sum + row.total_pay, 0);
  document.getElementById("total-shifts").textContent = totalShifts;
  document.getElementById("total-ot").textContent = totalOt;
  document.getElementById("total-ot-pay").textContent = currency.format(totalOtPay);
  document.getElementById("total-pay").textContent = currency.format(totalPay);
  const lastDate = rows.reduce((max, row) => (row.date > max ? row.date : max), rows[0].date);
  const stamp = document.getElementById("last-updated");
  if (stamp) {
    stamp.textContent = `Cập nhật đến ${lastDate}`;
  }
}

function setupEventFilter() {
  const select = document.getElementById("public-event-filter");
  if (!select) {
    return;
  }
  select.addEventListener("change", (event) => {
    state.filters.eventType = event.target.value;
    renderTable(getFilteredRows());
  });
}

function setupMonthFilter() {
  const select = document.getElementById("public-month-filter");
  if (!select) {
    return;
  }
  select.addEventListener("change", (event) => {
    state.filters.month = event.target.value;
    syncFiltersToQuery();
    if (!state.rows.length) {
      return;
    }
    updateEventFilterOptions(getScopeAndMonthRows());
    refreshDashboard();
  });
}

function updateEventFilterOptions(rows) {
  const select = document.getElementById("public-event-filter");
  if (!select) {
    state.filters.eventType = "all";
    return;
  }
  const types = Array.from(
    new Set(
      rows
        .map((row) => row.event_type)
        .filter((value) => value && value.trim().length > 0)
    )
  ).sort();
  const options = ['<option value="all">Tất cả loại</option>'].concat(
    types.map((type) => `<option value="${type}">${type}</option>`)
  );
  select.innerHTML = options.join("");
  if (state.filters.eventType !== "all" && !types.includes(state.filters.eventType)) {
    state.filters.eventType = "all";
  }
  select.value = state.filters.eventType;
}

function updateMonthOptions(rows) {
  const select = document.getElementById("public-month-filter");
  if (!select) {
    return;
  }
  const months = Array.from(
    new Set(
      rows
        .map((row) => (row.date ? row.date.slice(0, 7) : null))
        .filter((value) => value)
    )
  ).sort((a, b) => (a > b ? -1 : 1));
  const options = ['<option value="all">Tất cả tháng</option>'].concat(
    months.map((month) => `<option value="${month}">${formatMonthLabel(month)}</option>`)
  );
  select.innerHTML = options.join("");
  if (state.filters.month !== "all" && !months.includes(state.filters.month)) {
    state.filters.month = "all";
  }
  select.value = state.filters.month;
}

function getFilteredRows() {
  const scoped = getScopeAndMonthRows();
  if (state.filters.eventType === "all") {
    return scoped;
  }
  return scoped.filter((row) => row.event_type === state.filters.eventType);
}

function renderTable(rows) {
  const body = document.getElementById("shift-rows");
  if (!rows.length) {
    body.innerHTML =
      '<tr><td colspan="6">Không có ca nào khớp với bộ lọc hiện tại.</td></tr>';
    return;
  }
  const sorted = [...rows].sort((a, b) => new Date(b.date) - new Date(a.date));
  body.innerHTML = sorted
    .map(
      (row) => `
      <tr>
        <td>${row.date}</td>
        <td>${row.event_type}</td>
        <td>${row.actual_end_time}</td>
        <td>${row.ot_minutes}</td>
        <td>${currency.format(row.ot_pay)}</td>
        <td>${currency.format(row.total_pay)}</td>
      </tr>`
    )
    .join("");
}

function renderChart(rows) {
  const byDay = {};
  rows.forEach((row) => {
    const dayKey = row.date;
    byDay[dayKey] = (byDay[dayKey] || 0) + row.ot_minutes;
  });
  const labels = Object.keys(byDay).sort();
  const data = labels.map((label) => byDay[label]);
  const config = {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "OT (phút)",
          data,
          borderColor: "#ff5d73",
          backgroundColor: "rgba(255, 93, 115, 0.15)",
          borderWidth: 3,
          tension: 0.25,
          pointRadius: 4,
          pointBackgroundColor: "#ff5d73",
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: {
          beginAtZero: true,
        },
      },
      plugins: {
        legend: {
          display: false,
        },
      },
    },
  };

  if (state.chart) {
    state.chart.destroy();
  }
  const ctx = document.getElementById("otChart").getContext("2d");
  state.chart = new Chart(ctx, config);
}

function renderEmptyState() {
  document.getElementById("total-shifts").textContent = "0";
  document.getElementById("total-ot").textContent = "0";
  document.getElementById("total-ot-pay").textContent = "0";
  document.getElementById("total-pay").textContent = "0";
  const stamp = document.getElementById("last-updated");
  if (stamp) {
    stamp.textContent = "--";
  }
  document.getElementById("shift-rows").innerHTML =
    '<tr><td colspan="6">Chưa có dữ liệu để hiển thị</td></tr>';
  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }
}

function getInitialScope() {
  const params = new URLSearchParams(window.location.search);
  const scope = params.get("view");
  if (scope && VIEW_SCOPES[scope]) {
    return scope;
  }
  return "all";
}

function eventTypeMatches(value, keywords) {
  const normalized = normalizeText(value).replace(/\s+/g, "");
  return keywords.some((keyword) =>
    normalized.includes(normalizeText(keyword).replace(/\s+/g, ""))
  );
}

function normalizeText(value) {
  return (value || "")
    .toString()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/đ/g, "d");
}

function setupScopeFilter() {
  document.querySelectorAll(".filter-tab[data-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      applyScope(button.dataset.scope);
    });
  });
  updateScopeButtons();
}

function applyScope(scope) {
  if (!VIEW_SCOPES[scope] || state.filters.scope === scope) {
    return;
  }
  state.filters.scope = scope;
  state.filters.eventType = "all";
  syncFiltersToQuery();
  updateScopeButtons();
  if (!state.rows.length) {
    return;
  }
  updateEventFilterOptions(getScopeAndMonthRows());
  refreshDashboard();
}

function updateScopeButtons() {
  document.querySelectorAll(".filter-tab[data-scope]").forEach((button) => {
    const isActive = button.dataset.scope === state.filters.scope;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function refreshDashboard() {
  const scopedRows = getScopeAndMonthRows();
  updateSummary(scopedRows);
  renderChart(scopedRows);
  renderTable(getFilteredRows());
}

function getScopedRows() {
  const config = VIEW_SCOPES[state.filters.scope];
  if (!config || !config.predicate) {
    return state.rows;
  }
  return state.rows.filter((row) => config.predicate(row));
}

function getScopeAndMonthRows() {
  return applyMonthFilter(getScopedRows());
}

function applyMonthFilter(rows) {
  if (state.filters.month === "all") {
    return rows;
  }
  return rows.filter((row) => row.date && row.date.slice(0, 7) === state.filters.month);
}

function syncFiltersToQuery() {
  const url = new URL(window.location.href);
  if (state.filters.scope === "all") {
    url.searchParams.delete("view");
  } else {
    url.searchParams.set("view", state.filters.scope);
  }
  if (state.filters.month === "all") {
    url.searchParams.delete("month");
  } else {
    url.searchParams.set("month", state.filters.month);
  }
  window.history.replaceState({}, "", url);
}

function formatMonthLabel(value) {
  if (!value || !value.includes("-")) {
    return value || "";
  }
  const [year, month] = value.split("-");
  return `Tháng ${month}/${year}`;
}

function getInitialMonth() {
  const params = new URLSearchParams(window.location.search);
  const month = params.get("month");
  if (month && /^\d{4}-\d{2}$/.test(month)) {
    return month;
  }
  return "all";
}

init();
