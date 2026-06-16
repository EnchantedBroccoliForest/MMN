(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  // ---------- formatting ----------
  const fmtMoney = (x, q = "USDT") => {
    if (x == null) return "—";
    if (x === 0) return `0 ${q}`;
    const ax = Math.abs(x);
    if (ax >= 1)
      return `${x.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${q}`;
    return `${x.toPrecision(4)} ${q}`;
  };
  const fmtNum = (x) => {
    if (x == null) return "—";
    if (x === 0) return "0";
    const ax = Math.abs(x);
    if (ax >= 1000)
      return x.toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (ax >= 1)
      return x.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return x.toPrecision(4);
  };
  const fmtPct = (x) =>
    x == null
      ? "—"
      : `${x.toLocaleString(undefined, { maximumFractionDigits: 3 })}%`;
  const fmtX = (roi) =>
    roi == null
      ? "—"
      : `${(roi + 1).toLocaleString(undefined, { maximumFractionDigits: 2 })}×`;
  const roiClass = (roi) => (roi != null && roi >= 0 ? "pos" : "neg");

  // ---------- chart defaults ----------
  Chart.defaults.color = "#93a0b3";
  Chart.defaults.font.family = "Inter, sans-serif";
  Chart.defaults.borderColor = "#212b3a";
  const ACCENT = "#2dd4a7",
    CYAN = "#38bdf8",
    WARN = "#f7c948",
    NEG = "#f87171";
  // redeem band: orange (best) -> red (worst); settlement: green
  const ORANGE = "#fb923c",
    RED = "#ef4444",
    GREEN = "#34d399";
  const grid = { grid: { color: "#18202c" }, ticks: { font: { size: 11 } } };
  const charts = {};
  const mountChart = (id, cfg) => {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart($(id), cfg);
  };

  // ---------- inputs ----------
  function payload() {
    // protocol fee is charged per trade (one-way) -> same on buy and sell
    const feeEach = parseFloat($("fee").value) / 100;
    return {
      num_outcomes: parseInt($("num_outcomes").value, 10),
      early_pct: parseFloat($("early_pct").value),
      full_mcap: parseFloat($("full_mcap").value),
      house_seed: parseFloat($("house_seed").value),
      coefficient: parseFloat($("coefficient").value),
      exponent: parseFloat($("exponent").value),
      buy_fee: feeEach,
      sell_fee: feeEach,
      redeem_tax: parseFloat($("redeem_tax").value) / 100,
      multiples: multiples,
    };
  }

  // ---------- editable market-cap multiples (chips) ----------
  const MAX_MULTIPLES = 24;
  let multiples = [1, 2, 5, 10, 25, 50, 100, 500, 1000];
  function renderChips() {
    const box = $("multiples_chips");
    const input = $("multiples_input");
    [...box.querySelectorAll(".chip")].forEach((c) => c.remove());
    multiples.forEach((m, i) => {
      const chip = el("span", "chip");
      chip.appendChild(el("span", "chip-val", fmtNum(m)));
      const x = el("button", "chip-x", "✕");
      x.type = "button";
      x.setAttribute("aria-label", "remove " + fmtNum(m) + "×");
      // mousedown (not click) so removal beats the input's blur-commit and we keep focus
      x.addEventListener("mousedown", (e) => {
        e.preventDefault();
        multiples.splice(i, 1);
        renderChips();
        input.focus();
      });
      chip.appendChild(x);
      box.insertBefore(chip, input);
    });
  }
  // add one or many (comma/space/newline-separated) values; returns true if any added
  function addMultiples(raw) {
    let added = false;
    for (const tok of String(raw).split(/[\s,]+/)) {
      const v = parseFloat(tok.trim());
      if (!isFinite(v) || v < 1 || multiples.length >= MAX_MULTIPLES) continue;
      if (!multiples.includes(v)) {
        multiples.push(v);
        added = true;
      }
    }
    if (added) multiples.sort((a, b) => a - b);
    return added;
  }
  function wireMultiples() {
    const input = $("multiples_input");
    const commit = () => {
      if (addMultiples(input.value)) input.value = "";
      renderChips();
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === "," || e.key === " ") {
        e.preventDefault();
        commit();
      } else if (
        e.key === "Backspace" &&
        input.value === "" &&
        multiples.length
      ) {
        multiples.pop();
        renderChips();
      }
    });
    input.addEventListener("paste", (e) => {
      e.preventDefault();
      if (
        addMultiples((e.clipboardData || window.clipboardData).getData("text"))
      )
        input.value = "";
      renderChips();
    });
    input.addEventListener("blur", commit);
    renderChips();
  }
  // toast notifications (top-center, auto-dismiss). Replaces the inline error banner.
  const dismissToast = (t) => {
    if (t.classList.contains("out")) return;
    t.classList.add("out");
    t.addEventListener("animationend", () => t.remove(), { once: true });
  };
  function toast(msg, ms = 6000) {
    const box = $("toasts");
    // dedupe: if the same message is already showing, don't stack another
    if (
      [...box.children].some(
        (t) => t.dataset.msg === msg && !t.classList.contains("out"),
      )
    )
      return;
    const t = el("div", "toast");
    t.dataset.msg = msg;
    t.appendChild(el("span", null, msg));
    const close = el("button", null, "✕");
    close.type = "button";
    close.setAttribute("aria-label", "dismiss");
    close.addEventListener("click", () => dismissToast(t));
    t.appendChild(close);
    box.appendChild(t);
    // cap the stack: keep the 3 newest
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => dismissToast(t), ms);
  }
  // Escape dismisses the most recent toast
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const box = $("toasts");
    if (box && box.lastElementChild) dismissToast(box.lastElementChild);
  });
  const showError = (m) => toast(m);
  // validate the numeric inputs before posting; null => an empty/NaN field
  function validPayload() {
    const p = payload();
    const nums = [
      p.num_outcomes,
      p.early_pct,
      p.full_mcap,
      p.house_seed,
      p.coefficient,
      p.exponent,
      p.buy_fee,
      p.sell_fee,
      p.redeem_tax,
    ];
    if (nums.some((x) => !Number.isFinite(x))) {
      showError("Please enter a valid number in every field.");
      return null;
    }
    return p;
  }

  // ---------- simulation ----------
  async function runSimulation() {
    const p = validPayload();
    if (!p) return;
    const btn = $("run_btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>Running…';
    try {
      const res = await fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(p),
      });
      const d = await res.json();
      if (!res.ok) {
        showError(d.error || "Simulation failed.");
        return;
      }
      render(d);
    } catch (err) {
      showError("Network error: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run simulation";
    }
  }

  function render(d) {
    const q = d.quote;
    const n = d.num_outcomes;
    // two-side KPI cards: total (aggregate over N outcomes) | per outcome
    $("inv_total").textContent = fmtNum(d.total_spend);
    $("inv_each").textContent = fmtNum(d.spend_per_outcome);
    $("tok_total").textContent = fmtNum(d.tokens_per_outcome * n);
    $("tok_each").textContent = fmtNum(d.tokens_per_outcome);
    $("res_total").textContent = fmtNum(d.entry_reserve * n);
    $("res_each").textContent = fmtNum(d.entry_reserve);
    $("mc_total").textContent = fmtNum(d.entry_market_cap * n);
    $("mc_each").textContent = fmtNum(d.entry_market_cap);

    const labels = d.stages.map((s) => `${fmtNum(s.multiple)}×`);
    const line = (label, data, color, fill) => ({
      label,
      data,
      borderColor: color,
      backgroundColor: fill ? color + "22" : color,
      borderWidth: 2.5,
      tension: 0.3,
      pointRadius: 3,
      pointHoverRadius: 5,
      fill: !!fill,
    });

    mountChart("roiChart", {
      type: "line",
      data: {
        labels,
        datasets: [
          // redeem-ROI band: orange (best) edge fills down to the red (worst) edge
          {
            label: "Redeem · best",
            data: d.stages.map((s) => s.redeem_roi_band_hi + 1),
            borderColor: ORANGE,
            backgroundColor: ORANGE + "22",
            borderWidth: 2.5,
            pointRadius: 0,
            tension: 0.3,
            fill: 1,
          },
          {
            label: "Redeem · worst",
            data: d.stages.map((s) => s.redeem_roi_band_lo + 1),
            borderColor: RED,
            backgroundColor: RED + "22",
            borderDash: [5, 4],
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            fill: false,
          },
          {
            label: "Settlement (if win)",
            data: d.stages.map((s) => s.settle_roi + 1),
            borderColor: GREEN,
            backgroundColor: GREEN,
            borderWidth: 2.5,
            pointRadius: 3,
            pointHoverRadius: 5,
            tension: 0.3,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { usePointStyle: true, boxWidth: 8, padding: 16 } },
          tooltip: {
            callbacks: {
              label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)}×`,
            },
          },
        },
        scales: {
          x: {
            ...grid,
            title: { display: true, text: "reserve multiple of entry" },
          },
          y: {
            ...grid,
            beginAtZero: true,
            title: { display: true, text: "return (×)" },
          },
        },
      },
    });
    mountChart("ownChart", {
      type: "line",
      data: {
        labels,
        datasets: [
          line(
            "Ownership %",
            d.stages.map((s) => s.ownership_pct),
            CYAN,
            true,
          ),
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${c.parsed.y.toFixed(3)}%` } },
        },
        scales: {
          x: { ...grid },
          y: {
            ...grid,
            beginAtZero: true,
            title: { display: true, text: "% of supply" },
          },
        },
      },
    });
    mountChart("settleChart", {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Win ROI (×)",
            data: d.stages.map((s) => s.settle_roi + 1),
            backgroundColor: GREEN + "cc",
            borderColor: GREEN,
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
          tooltip: { callbacks: { label: (c) => `${c.parsed.y.toFixed(2)}×` } },
        },
        scales: {
          x: { ...grid },
          y: {
            ...grid,
            beginAtZero: true,
            title: { display: true, text: "payout / spend (×)" },
          },
        },
      },
    });

    const tb = $("detail_table").querySelector("tbody");
    tb.innerHTML = "";
    for (const s of d.stages) {
      const tr = el("tr");
      tr.appendChild(el("td", null, `${fmtNum(s.multiple)}×`));
      tr.appendChild(el("td", null, fmtNum(s.reserve)));
      tr.appendChild(el("td", null, fmtNum(s.market_cap))); // price × supply (spot)
      tr.appendChild(el("td", null, fmtPct(s.ownership_pct)));
      // req inflow = additional pot needed to reach this stage from entry (1×):
      // (reserve − entry reserve) × N outcomes. First row (1×) is +0.
      const reqInflow = (s.reserve - d.entry_reserve) * n;
      tr.appendChild(
        el(
          "td",
          null,
          `+${fmtNum(Math.abs(reqInflow) < 1e-6 ? 0 : reqInflow)}`,
        ),
      );
      const r1 = el("td");
      r1.appendChild(el("span", roiClass(s.redeem_roi), fmtX(s.redeem_roi)));
      tr.appendChild(r1);
      const r2 = el("td");
      r2.appendChild(el("span", roiClass(s.settle_roi), fmtX(s.settle_roi)));
      tr.appendChild(r2);
      tb.appendChild(tr);
    }
  }

  // ---------- monte carlo ----------
  async function runMonteCarlo() {
    const p = validPayload();
    if (!p) return;
    const btn = $("mc_btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>Running…';
    try {
      p.mc_trials = parseInt($("mc_trials").value, 10);
      p.winner_prior = $("winner_prior").value;
      const res = await fetch("/api/montecarlo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(p),
      });
      const d = await res.json();
      if (!res.ok) {
        showError(d.error || "Monte Carlo failed.");
        return;
      }
      renderMc(d);
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
    $("mc_range").textContent =
      `${d.p05_settle.toFixed(2)}–${d.p95_settle.toFixed(2)}×`;

    const { edges, counts } = d.histogram;
    const labels = counts.map((_, i) => `${edges[i].toFixed(2)}×`);
    mountChart("mcChart", {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Trials",
            data: counts,
            backgroundColor: counts.map((_, i) =>
              edges[i] >= 1 ? ACCENT + "cc" : NEG + "cc",
            ),
            borderWidth: 0,
            barPercentage: 1,
            categoryPercentage: 1,
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
              title: (it) => `return ≈ ${it[0].label}`,
              label: (c) => `${c.parsed.y.toLocaleString()} trials`,
            },
          },
        },
        scales: {
          x: {
            ...grid,
            title: {
              display: true,
              text: "settlement return (payout / spend)",
            },
            ticks: { maxTicksLimit: 12, font: { size: 10 } },
          },
          y: {
            ...grid,
            beginAtZero: true,
            title: { display: true, text: "trials" },
          },
        },
      },
    });
  }

  // ---------- wiring ----------
  function wire() {
    $("controls").addEventListener("submit", (e) => {
      e.preventDefault();
      runSimulation();
    });
    $("mc_btn").addEventListener("click", runMonteCarlo);
    wireMultiples();
  }

  document.addEventListener("DOMContentLoaded", () => {
    wire();
    runSimulation();
  });
})();
