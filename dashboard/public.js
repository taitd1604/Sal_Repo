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
    const rows = await loadCsv("./data/shifts_public.csv");
    if (!rows.length) {
      renderEmptyState();
      return;
    }
    state.rows = rows;
    updateSummary(rows);
    renderTable(rows);
    renderChart(rows);
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
  const totalShifts = rows.length;
  const totalOt = rows.reduce((sum, row) => sum + row.ot_minutes, 0);
  const totalOtPay = rows.reduce((sum, row) => sum + row.ot_pay, 0);
  const totalPay = rows.reduce((sum, row) => sum + row.total_pay, 0);
  document.getElementById("total-shifts").textContent = totalShifts;
  document.getElementById("total-ot").textContent = totalOt;
  document.getElementById("total-ot-pay").textContent = currency.format(totalOtPay);
  document.getElementById("total-pay").textContent = currency.format(totalPay);
  const lastDate = rows.reduce((max, row) => (row.date > max ? row.date : max), rows[0].date);
  document.getElementById("last-updated").textContent = `Cập nhật đến ${lastDate}`;
}

function renderTable(rows) {
  const body = document.getElementById("shift-rows");
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
  const byMonth = {};
  rows.forEach((row) => {
    const month = row.date.slice(0, 7);
    byMonth[month] = (byMonth[month] || 0) + row.ot_minutes;
  });
  const labels = Object.keys(byMonth).sort();
  const data = labels.map((label) => byMonth[label]);
  const config = {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "OT (phút)",
          data,
          backgroundColor: "#ff5d73",
          borderWidth: 2,
          borderColor: "#111",
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
  document.getElementById("last-updated").textContent = "--";
  document.getElementById("shift-rows").innerHTML =
    '<tr><td colspan="6">Chưa có dữ liệu để hiển thị</td></tr>';
  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }
}

init();
