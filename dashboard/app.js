const currency = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0,
});

const state = {
  rows: [],
  chart: null,
};

async function init() {
  try {
    const rows = await loadCsv("./data/shifts.csv");
    if (!rows.length) {
      renderEmptyState();
      return;
    }
    state.rows = rows;
    updateSummary(rows);
    renderTable(rows);
    renderChart(rows, document.getElementById("chart-mode").value);
    document
      .getElementById("chart-mode")
      .addEventListener("change", (event) => {
        renderChart(state.rows, event.target.value);
      });
  } catch (error) {
    console.error(error);
    const body = document.getElementById("shift-rows");
    body.innerHTML = `<tr><td colspan="7">Không thể tải dữ liệu: ${error.message}</td></tr>`;
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
      base_pay: parseFloat(row.base_pay || 0),
      ot_minutes: Number(row.ot_minutes || 0),
      ot_pay: parseFloat(row.ot_pay || 0),
      total_pay: parseFloat(row.total_pay || 0),
    }));
}

function updateSummary(rows) {
  const totalPay = rows.reduce((sum, row) => sum + (row.total_pay || 0), 0);
  const totalOt = rows.reduce((sum, row) => sum + (row.ot_minutes || 0), 0);
  const selfCount = rows.filter((row) => (row.performed_by || "").includes("Tự")).length;
  const outsourced = rows.length - selfCount;
  document.getElementById("total-pay").textContent = currency.format(totalPay);
  document.getElementById("total-ot").textContent = totalOt;
  document.getElementById("total-shifts").textContent = rows.length;
  document.getElementById("self-vs-outsourced").textContent = `${selfCount}/${outsourced}`;
  const lastDate = rows.reduce(
    (max, row) => (row.date > max ? row.date : max),
    rows[0].date
  );
  document.getElementById("last-updated").textContent = `Cập nhật đến ${lastDate}`;
}

function renderTable(rows) {
  const body = document.getElementById("shift-rows");
  const latest = [...rows].sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, 20);
  body.innerHTML = latest
    .map(
      (row) => `
      <tr>
        <td>${row.date}</td>
        <td>${row.venue}</td>
        <td>${row.event_type}</td>
        <td>${row.performed_by}</td>
        <td>${row.actual_end_time || row.scheduled_end_time}</td>
        <td>${row.ot_minutes} ph</td>
        <td>${currency.format(row.total_pay)}</td>
      </tr>`
    )
    .join("");
}

function renderChart(rows, metric = "total_pay") {
  const monthly = {};
  rows.forEach((row) => {
    const month = row.date.slice(0, 7);
    monthly[month] = (monthly[month] || 0) + (row[metric] || 0);
  });
  const labels = Object.keys(monthly).sort();
  const data = labels.map((label) => Math.round(monthly[label]));
  const datasetLabel = metric === "total_pay" ? "Tổng lương" : "Lương OT";
  const config = {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: datasetLabel,
          data,
          backgroundColor: metric === "total_pay" ? "#6366f1" : "#f97316",
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

  if (state.chart) {
    state.chart.destroy();
  }
  const ctx = document.getElementById("monthlyChart").getContext("2d");
  state.chart = new Chart(ctx, config);
}

function renderEmptyState() {
  document.getElementById("total-pay").textContent = "0";
  document.getElementById("total-ot").textContent = "0";
  document.getElementById("total-shifts").textContent = "0";
  document.getElementById("self-vs-outsourced").textContent = "0/0";
  document.getElementById("last-updated").textContent = "";
  document.getElementById("shift-rows").innerHTML =
    '<tr><td colspan="7">Chưa có dữ liệu, hãy log ca đầu tiên nhé!</td></tr>';
}

init();
