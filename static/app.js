(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ---------- formatting ----------
  const fmtMoney = (x, quote = "USDT") => {
    if (x === 0) return `0 ${quote}`;
    const ax = Math.abs(x);
    if (ax >= 1) return `${x.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${quote}`;
    return `${x.toPrecision(4)} ${quote}`;
  };
  const fmtNum = (x) => {
    if (x === 0) return "0";
    const ax = Math.abs(x);
    if (ax >= 1000) return x.toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (ax >= 1) return x.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return x.toPrecision(4);
  };
  const fmtPct = (x) => `${x.toLocaleString(undefined, { maximumFractionDigits: 3 })}%`;
  const fmtX = (roi) => `${(roi + 1).toLocaleString(undefined, { maximumFractionDigits: 2 })}×`;

  // ---------- chart defaults ----------
  Chart.defaults.color = "#8a97ab";
  Chart.defaults.font.family = "Inter, sans-serif";
  Chart.defaults.borderColor = "#1a2230";
  const ACCENT = "#2dd4a7";
  const ACCENT2 = "#4f8cff";
  const WARN = "#f7c948";

  let roiChart, ownChart, settleChart, mcChart;

  const gridCfg = { grid: { color: "#1a2230" }, ticks: { font: { size: 11 } } };

  // ---------- gather inputs ----------
  function getPayload() {
    const curve = $("curve").value;
    return {
      num_outcomes: parseInt($("num_outcomes").value, 10),
      early_pct: parseFloat($("early_pct").value),
      full_mcap: parseFloat($("full_mcap").value),
      house_seed: parseFloat($("house_seed").value),
      curve,
      coefficient: parseFloat($("coefficient").value),
      exponent: parseFloat($("exponent").value),
      slope: parseFloat($("slope").value),
      base: parseFloat($("base").value),
      buy_fee: parseFloat($("buy_fee").value) / 100,
      sell_fee: parseFloat($("sell_fee").value) / 100,
      multiples: $("multiples").value,
    };
  }

  function showError(msg) {
    const b = $("error_banner");
    b.textContent = msg;
    b.classList.remove("hidden");
  }
  function clearError() {
    $("error_banner").classList.add("hidden");
  }

  // ---------- run simulation ----------
  async function runSimulation() {
    clearError();
    const btn = $("run_btn");
    btn.disabled = true;
    btn.textContent = "Running…";
    try {
      const res = await fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(getPayload()),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Simulation failed.");
        return;
      }
      render(data);
    } catch (err) {
      showError("Network error: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run simulation";
    }
  }

  function render(d) {
    const q = d.quote;

    $("stat_total_spend").textContent = fmtMoney(d.total_spend, q);
    $("stat_spend_each").textContent = `${fmtMoney(d.spend_per_outcome, q)} × ${d.num_outcomes} outcomes`;
    $("stat_entry_price").textContent = fmtNum(d.entry_price);
    $("stat_tokens").textContent = fmtNum(d.tokens_per_outcome);
    $("stat_supply_sub").textContent = `${d.early_pct}% of ${fmtNum(d.total_supply)}`;
    $("stat_entry_mcap").textContent = fmtMoney(d.entry_market_cap, q);

    const badge = $("mode_badge");
    if (d.is_production) {
      badge.className = "badge production";
      badge.textContent = "✓ 42 confirmed production curve & 0.2% fees — ROI is exact & scale-free";
    } else {
      badge.className = "badge custom";
      badge.textContent = "⚠ Custom parameters — not 42's production calibration";
    }

    const labels = d.stages.map((s) => `${fmtNum(s.multiple)}×`);

    renderRoiChart(labels, d.stages);
    renderOwnChart(labels, d.stages);
    renderSettleChart(labels, d.stages);
    renderTable(d.stages, q);
  }

  function lineDataset(label, data, color, fill = false) {
    return {
      label,
      data,
      borderColor: color,
      backgroundColor: fill ? color + "22" : color,
      borderWidth: 2.5,
      tension: 0.3,
      pointRadius: 3,
      pointHoverRadius: 5,
      pointBackgroundColor: color,
      fill,
    };
  }

  function renderRoiChart(labels, stages) {
    const ctx = $("roiChart");
    if (roiChart) roiChart.destroy();
    roiChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          lineDataset("Spot ROI (×)", stages.map((s) => s.spot_roi + 1), ACCENT2),
          lineDataset("Redeem ROI (×)", stages.map((s) => s.redeem_roi + 1), ACCENT),
          lineDataset("Settlement-win ROI (×)", stages.map((s) => s.settle_roi + 1), WARN),
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { usePointStyle: true, boxWidth: 8, padding: 16 } },
          tooltip: {
            callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)}×` },
          },
        },
        scales: {
          x: { ...gridCfg, title: { display: true, text: "Market-cap multiple of entry" } },
          y: { ...gridCfg, title: { display: true, text: "Return (×)" }, beginAtZero: true },
        },
      },
    });
  }

  function renderOwnChart(labels, stages) {
    const ctx = $("ownChart");
    if (ownChart) ownChart.destroy();
    ownChart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [lineDataset("Ownership %", stages.map((s) => s.ownership_pct), ACCENT, true)] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => `Ownership: ${c.parsed.y.toFixed(3)}%` } },
        },
        scales: {
          x: { ...gridCfg },
          y: { ...gridCfg, title: { display: true, text: "% of outcome supply" }, beginAtZero: true },
        },
      },
    });
  }

  function renderSettleChart(labels, stages) {
    const ctx = $("settleChart");
    if (settleChart) settleChart.destroy();
    settleChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Win ROI (×)",
            data: stages.map((s) => s.settle_roi + 1),
            backgroundColor: WARN + "cc",
            borderColor: WARN,
            borderWidth: 1,
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => `Win ROI: ${c.parsed.y.toFixed(2)}×` } },
        },
        scales: {
          x: { ...gridCfg },
          y: { ...gridCfg, title: { display: true, text: "Payout / spend (×)" }, beginAtZero: true },
        },
      },
    });
  }

  function renderTable(stages, q) {
    const tbody = $("detail_table").querySelector("tbody");
    tbody.innerHTML = "";
    for (const s of stages) {
      const tr = document.createElement("tr");
      const roiCell = (roi) => {
        const cls = roi >= 0 ? "pos" : "neg";
        return `<td class="${cls}">${fmtX(roi)}</td>`;
      };
      tr.innerHTML =
        `<td>${fmtNum(s.multiple)}×</td>` +
        `<td>${fmtNum(s.market_cap)}</td>` +
        `<td>${fmtNum(s.price)}</td>` +
        `<td>${fmtPct(s.ownership_pct)}</td>` +
        roiCell(s.spot_roi) +
        roiCell(s.redeem_roi) +
        roiCell(s.settle_roi);
      tbody.appendChild(tr);
    }
  }

  // ---------- monte carlo ----------
  async function runMonteCarlo() {
    clearError();
    const btn = $("mc_btn");
    btn.disabled = true;
    btn.textContent = "Running…";
    try {
      const payload = getPayload();
      payload.mc_trials = parseInt($("mc_trials").value, 10);
      payload.winner_prior = $("winner_prior").value;
      const res = await fetch("/api/montecarlo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Monte Carlo failed.");
        return;
      }
      renderMc(data);
    } catch (err) {
      showError("Network error: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run Monte Carlo";
    }
  }

  function renderMc(d) {
    $("mc_placeholder").classList.add("hidden");
    $("mc_results").classList.remove("hidden");

    const prob = d.prob_profit * 100;
    const probEl = $("mc_prob");
    probEl.textContent = `${prob.toFixed(1)}%`;
    probEl.style.color = prob >= 50 ? ACCENT : WARN;
    $("mc_median").textContent = `${d.median_settle.toFixed(2)}×`;
    $("mc_mean").textContent = `${d.mean_settle.toFixed(2)}×`;
    $("mc_range").textContent = `${d.p05_settle.toFixed(2)}× – ${d.p95_settle.toFixed(2)}×`;

    const edges = d.histogram.edges;
    const counts = d.histogram.counts;
    const labels = counts.map((_, i) => `${edges[i].toFixed(2)}×`);

    const ctx = $("mcChart");
    if (mcChart) mcChart.destroy();
    mcChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Trials",
            data: counts,
            backgroundColor: counts.map((_, i) => (edges[i] >= 1 ? ACCENT + "cc" : "#ff6b6bcc")),
            borderWidth: 0,
            barPercentage: 1.0,
            categoryPercentage: 1.0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => `Return ≈ ${items[0].label}`,
              label: (c) => `${c.parsed.y.toLocaleString()} trials`,
            },
          },
        },
        scales: {
          x: {
            ...gridCfg,
            title: { display: true, text: "Settlement return (payout / spend)" },
            ticks: { maxTicksLimit: 12, font: { size: 10 } },
          },
          y: { ...gridCfg, title: { display: true, text: "Number of trials" }, beginAtZero: true },
        },
      },
    });
  }

  // ---------- UI wiring ----------
  function wire() {
    $("num_outcomes").addEventListener("input", (e) => {
      $("num_outcomes_out").textContent = e.target.value;
    });

    $("advanced_toggle").addEventListener("click", () => {
      $("advanced").classList.toggle("open");
    });

    $("curve").addEventListener("change", (e) => {
      const affine = e.target.value === "affine";
      $("affine_params").classList.toggle("hidden", !affine);
      $("power_params").classList.toggle("hidden", affine);
    });

    $("controls").addEventListener("submit", (e) => {
      e.preventDefault();
      runSimulation();
    });

    $("mc_btn").addEventListener("click", runMonteCarlo);

    // run once on load
    runSimulation();
  }

  document.addEventListener("DOMContentLoaded", wire);
})();
