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

const CHART_LABELS = {
  total_pay: "Tổng lương",
  net_income: "Thu ròng",
  ot_pay: "Lương OT",
};

const CHART_COLORS = {
  total_pay: "#6366f1",
  net_income: "#0f766e",
  ot_pay: "#f97316",
};

const state = {
  rows: [],
  chart: null,
  filters: {
    eventType: "all",
    scope: getInitialScope(),
    month: getInitialMonth(),
  },
  chartInterval: "month",
};

async function init() {
  setupScopeFilter();
  setupEventFilter();
  setupMonthFilter();
  setupChartControls();
  try {
    const rows = await loadCsv("./data/shifts.csv");
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
    const body = document.getElementById("shift-rows");
    body.innerHTML = `<tr><td colspan="9">Không thể tải dữ liệu: ${error.message}</td></tr>`;
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
    .map((row) => {
      const basePay = Number(row.base_pay || 0);
      const otMinutes = Number(row.ot_minutes || 0);
      const otPay = Number(row.ot_pay || 0);
      const totalPay = Number(row.total_pay || 0);
      const workerPayment = Number(row.worker_payment || 0);
      const netIncome = row.net_income ? Number(row.net_income) : totalPay - workerPayment;
      return {
        ...row,
        base_pay: basePay,
        ot_minutes: otMinutes,
        ot_pay: otPay,
        total_pay: totalPay,
        worker_payment: workerPayment,
        net_income: netIncome,
      };
    });
}

function updateSummary(rows) {
  if (!rows.length) {
    document.getElementById("total-pay").textContent = "0";
    document.getElementById("net-income").textContent = "0";
    document.getElementById("total-worker-pay").textContent = "0";
    document.getElementById("total-ot").textContent = "0";
    document.getElementById("total-shifts").textContent = "0";
    document.getElementById("self-vs-outsourced").textContent = "0/0";
    document.getElementById("last-updated").textContent = "Chưa có dữ liệu cho chế độ này";
    return;
  }
  const totalPay = rows.reduce((sum, row) => sum + (row.total_pay || 0), 0);
  const totalOt = rows.reduce((sum, row) => sum + (row.ot_minutes || 0), 0);
  const totalWorker = rows.reduce((sum, row) => sum + (row.worker_payment || 0), 0);
  const totalNet = rows.reduce((sum, row) => sum + (row.net_income || 0), 0);
  const selfCount = rows.filter((row) => (row.performed_by || "").includes("Tự")).length;
  const outsourced = rows.length - selfCount;
  document.getElementById("total-pay").textContent = currency.format(totalPay);
  document.getElementById("net-income").textContent = currency.format(totalNet);
  document.getElementById("total-worker-pay").textContent = currency.format(totalWorker);
  document.getElementById("total-ot").textContent = totalOt;
  document.getElementById("total-shifts").textContent = rows.length;
  document.getElementById("self-vs-outsourced").textContent = `${selfCount}/${outsourced}`;
  const lastDate = rows.reduce(
    (max, row) => (row.date > max ? row.date : max),
    rows[0].date
  );
  document.getElementById("last-updated").textContent = `Cập nhật đến ${lastDate}`;
}

function setupEventFilter() {
  const select = document.getElementById("event-filter");
  if (!select) {
    state.filters.eventType = "all";
    return;
  }
  select.addEventListener("change", (event) => {
    state.filters.eventType = event.target.value;
    renderTable(getFilteredRows());
  });
}

function setupMonthFilter() {
  const select = document.getElementById("month-filter");
  if (!select) return;
  select.addEventListener("change", (event) => {
    state.filters.month = event.target.value;
    syncFiltersToQuery();
    if (!state.rows.length) return;
    updateEventFilterOptions(getScopeAndMonthRows());
    refreshDashboard();
  });
}

function setupChartControls() {
  const modeSelect = document.getElementById("chart-mode");
  if (modeSelect) {
    modeSelect.addEventListener("change", () => {
      if (!state.rows.length) {
        return;
      }
      renderChart(getScopeAndMonthRows());
    });
  }
  const intervalSelect = document.getElementById("chart-interval");
  if (intervalSelect) {
    intervalSelect.addEventListener("change", (event) => {
      state.chartInterval = event.target.value;
      if (!state.rows.length) {
        updateChartCaption(
          state.chartInterval === "day" ? "Theo ngày" : "Theo tháng"
        );
        return;
      }
      renderChart(getScopeAndMonthRows());
    });
  }
}

function updateEventFilterOptions(rows) {
  const select = document.getElementById("event-filter");
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
  const select = document.getElementById("month-filter");
  if (!select) return;
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
      '<tr><td colspan="9">Không có ca nào khớp với bộ lọc hiện tại.</td></tr>';
    return;
  }
  const latest = [...rows].sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, 20);
  body.innerHTML = latest
    .map(
      (row) => `
      <tr>
        <td>${formatDateLabel(row.date)}</td>
        <td>${row.venue}</td>
        <td>${row.event_type}</td>
        <td>${row.performed_by}</td>
        <td>${row.actual_end_time || row.scheduled_end_time}</td>
        <td>${row.ot_minutes} ph</td>
        <td>${currency.format(row.worker_payment || 0)}</td>
        <td>${currency.format(row.total_pay)}</td>
        <td>${currency.format(row.net_income || 0)}</td>
      </tr>`
    )
    .join("");
}

function renderChart(rows) {
  const metric = getSelectedChartMetric();
  if (!rows.length) {
    destroyChart();
    updateChartCaption(state.chartInterval === "day" ? "Theo ngày (không có dữ liệu)" : "Theo tháng (không có dữ liệu)");
    return;
  }
  if (state.chartInterval === "day") {
    renderDailyChart(rows, metric);
  } else {
    renderMonthlyChart(rows, metric);
  }
}

function renderMonthlyChart(rows, metric) {
  const monthly = {};
  rows.forEach((row) => {
    const month = row.date.slice(0, 7);
    monthly[month] = (monthly[month] || 0) + (row[metric] || 0);
  });
  const labels = Object.keys(monthly).sort();
  const data = labels.map((label) => Math.round(monthly[label]));
  const datasetLabel = CHART_LABELS[metric] || CHART_LABELS.total_pay;
  const color = CHART_COLORS[metric] || CHART_COLORS.total_pay;
  const config = {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: datasetLabel,
          data,
          backgroundColor: color,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            callback: (value) => currency.format(value),
          },
        },
      },
    },
  };
  updateChartCaption("Theo tháng");
  drawChart(config);
}

function renderDailyChart(rows, metric) {
  const { month, rows: monthRows } = getDailyChartRows(rows);
  if (!month || !monthRows.length) {
    destroyChart();
    updateChartCaption("Theo ngày (không có dữ liệu)");
    return;
  }
  const daily = {};
  monthRows.forEach((row) => {
    const dayKey = row.date;
    daily[dayKey] = (daily[dayKey] || 0) + (row[metric] || 0);
  });
  const labels = Object.keys(daily).sort();
  const data = labels.map((label) => Math.round(daily[label]));
  const datasetLabel = `${CHART_LABELS[metric] || CHART_LABELS.total_pay} / ngày`;
  const color = CHART_COLORS[metric] || CHART_COLORS.total_pay;
  const fillColor = color.length === 7 ? `${color}33` : color;
  const config = {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: datasetLabel,
          data,
          borderColor: color,
          backgroundColor: fillColor,
          borderWidth: 3,
          tension: 0.25,
          pointRadius: 4,
          pointBackgroundColor: color,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            callback: (value) => currency.format(value),
          },
        },
      },
      plugins: {
        legend: {
          display: false,
        },
      },
    },
  };
  updateChartCaption(`Theo ngày (${formatMonthLabel(month)})`);
  drawChart(config);
}

function drawChart(config) {
  if (state.chart) {
    state.chart.destroy();
  }
  const canvas = document.getElementById("monthlyChart");
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  state.chart = new Chart(ctx, config);
}

function destroyChart() {
  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }
}

function getDailyChartRows(rows) {
  const months = Array.from(
    new Set(
      rows
        .map((row) => (row.date ? row.date.slice(0, 7) : null))
        .filter((value) => value)
    )
  ).sort((a, b) => (a > b ? -1 : 1));
  if (!months.length) {
    return { month: null, rows: [] };
  }
  let selectedMonth = state.filters.month;
  if (selectedMonth === "all" || !months.includes(selectedMonth)) {
    selectedMonth = months[0];
  }
  const monthRows = rows.filter(
    (row) => row.date && row.date.slice(0, 7) === selectedMonth
  );
  return { month: selectedMonth, rows: monthRows };
}

function updateChartCaption(text) {
  const caption = document.getElementById("chart-caption");
  if (caption) {
    caption.textContent = text;
  }
}

function getSelectedChartMetric() {
  const select = document.getElementById("chart-mode");
  if (!select) {
    return "total_pay";
  }
  return select.value || "total_pay";
}

function renderEmptyState() {
  document.getElementById("total-pay").textContent = "0";
  document.getElementById("net-income").textContent = "0";
  document.getElementById("total-worker-pay").textContent = "0";
  document.getElementById("total-ot").textContent = "0";
  document.getElementById("total-shifts").textContent = "0";
  document.getElementById("self-vs-outsourced").textContent = "0/0";
  document.getElementById("last-updated").textContent = "";
  document.getElementById("shift-rows").innerHTML =
    '<tr><td colspan="9">Chưa có dữ liệu, hãy log ca đầu tiên nhé!</td></tr>';
  destroyChart();
  updateChartCaption("Theo tháng");
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

function formatDateLabel(value) {
  if (!value || !value.includes("-")) {
    return value || "";
  }
  const [year, month, day] = value.split("-");
  if (!day) {
    return value;
  }
  return `${day}/${month}/${year}`;
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
