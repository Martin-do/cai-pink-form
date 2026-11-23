(function () {
  function fmt(n) {
    return n.toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function num(el) {
    if (!el) return 0;
    const v = parseFloat(String(el.value || "0").replace(/,/g, ""));
    return isNaN(v) || v < 0 ? 0 : v;
  }

  // Stepper / tabs
  const stepBtns = document.querySelectorAll("[data-tab]");
  const panels = document.querySelectorAll(".tab-panel");
  const tabInput = document.getElementById("active-tab-input");
  function showTab(name) {
    stepBtns.forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    panels.forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
    if (tabInput) tabInput.value = name;
  }
  stepBtns.forEach((b) =>
    b.addEventListener("click", () => {
      showTab(b.dataset.tab);
      history.replaceState(null, "", "#" + b.dataset.tab);
    })
  );
  document.querySelectorAll("[data-step-goto]").forEach((b) =>
    b.addEventListener("click", () => {
      const target = b.dataset.stepGoto;
      showTab(target);
      history.replaceState(null, "", "#" + target);
      window.scrollTo({ top: 0, behavior: "smooth" });
    })
  );
  if (location.hash) {
    const h = location.hash.slice(1);
    if (document.getElementById("tab-" + h)) showTab(h);
  }

  // Instant line-item search filter inside Income / Expenditure tables
  document.querySelectorAll("[data-sheet-filter]").forEach((inp) => {
    const table = document.querySelector(inp.dataset.sheetFilter);
    if (!table) return;
    inp.addEventListener("input", () => {
      const q = inp.value.trim().toLowerCase();
      table.querySelectorAll("tbody tr[data-line-label]").forEach((row) => {
        const match = !q || row.dataset.lineLabel.toLowerCase().includes(q);
        row.style.display = match ? "" : "none";
      });
      table.querySelectorAll("tbody tr.group-row").forEach((grp) => {
        grp.style.display = q ? "none" : "";
      });
    });
  });

  // Live totals
  const form = document.getElementById("return-form");
  if (!form) return;
  const levyRate = parseFloat(form.dataset.levyRate || "0.25");

  function recalc() {
    let totalInc = 0;
    let totalLevy = 0;
    document.querySelectorAll("tr[data-inc-line]").forEach((row) => {
      let rowTotal = 0;
      row.querySelectorAll("input.money").forEach((inp) => (rowTotal += num(inp)));
      const cell = row.querySelector("[data-row-total]");
      if (cell) cell.textContent = fmt(rowTotal);
      totalInc += rowTotal;
      if (row.dataset.levyable === "1") totalLevy += rowTotal;
    });

    let totalExp = 0;
    document.querySelectorAll("tr[data-exp-line]").forEach((row) => {
      let rowTotal = 0;
      row.querySelectorAll("input.money").forEach((inp) => (rowTotal += num(inp)));
      const cell = row.querySelector("[data-row-total]");
      if (cell) cell.textContent = fmt(rowTotal);
      totalExp += rowTotal;
    });

    const openEl = document.getElementById("opening-balance-input");
    const openBal = openEl
      ? parseFloat(String(openEl.value || "0").replace(/,/g, "")) || 0
      : parseFloat(form.dataset.opening || "0");
    const closing = openBal + totalInc - totalExp;
    const levyDue = totalLevy * levyRate;

    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = fmt(val);
    };
    set("sum-income", totalInc);
    set("sum-income-2", totalInc);
    set("sum-expense", totalExp);
    set("sum-expense-2", totalExp);
    set("sum-surplus", totalInc - totalExp);
    set("sum-closing", closing);
    set("sum-levyable", totalLevy);
    set("sum-levy", levyDue);
    set("bar-income", totalInc);
    set("bar-expense", totalExp);
    set("bar-levy", levyDue);
  }

  form.addEventListener("input", (e) => {
    if (e.target.matches("input.money, #opening-balance-input")) recalc();
  });
})();
