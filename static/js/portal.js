(function () {
  // 1. Automatic loading spinners on all form submissions
  document.addEventListener("submit", function (e) {
    const form = e.target;
    if (!form || form.dataset.noSpinner === "1") return;
    const btn = e.submitter || form.querySelector('button[type="submit"], input[type="submit"]');
    if (!btn || btn.classList.contains("is-loading")) return;

    if (!btn.dataset.origHtml && btn.tagName === "BUTTON") {
      btn.dataset.origHtml = btn.innerHTML;
    }

    if (btn.name && !form.querySelector('input[type="hidden"][data-submit-clone="1"]')) {
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = btn.name;
      hidden.value = btn.value;
      hidden.dataset.submitClone = "1";
      form.appendChild(hidden);
    }

    btn.classList.add("is-loading");
    const label = btn.dataset.loadingText || btn.textContent.trim() || "Working...";
    if (btn.tagName === "BUTTON") {
      btn.innerHTML = '<span class="btn-spinner" aria-hidden="true"></span><span>' + label + "</span>";
    }
    btn.disabled = true;
  });

  // Loading spinner for heavy navigation / export links opted in via data-loading-link
  document.addEventListener("click", function (e) {
    const link = e.target.closest("a[data-loading-link]");
    if (!link || link.classList.contains("is-loading")) return;
    if (!link.dataset.origHtml) link.dataset.origHtml = link.innerHTML;
    link.classList.add("is-loading");
    const label = link.dataset.loadingText || link.textContent.trim();
    link.innerHTML = '<span class="btn-spinner" aria-hidden="true"></span><span>' + label + "</span>";
  });

  // Reset spinner states if user hits browser Back button (bfcache restore)
  window.addEventListener("pageshow", function () {
    document.querySelectorAll(".is-loading").forEach(function (el) {
      el.classList.remove("is-loading");
      el.disabled = false;
      if (el.dataset.origHtml) el.innerHTML = el.dataset.origHtml;
    });
    document.querySelectorAll('input[type="hidden"][data-submit-clone="1"]').forEach(function (h) {
      h.remove();
    });
  });

  // 2. Mobile sidebar drawer
  const menuBtn = document.querySelector("[data-sidebar-toggle]");
  const backdrop = document.querySelector("[data-sidebar-backdrop]");
  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
  }
  if (menuBtn) {
    menuBtn.addEventListener("click", function () {
      document.body.classList.toggle("sidebar-open");
    });
  }
  if (backdrop) backdrop.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeSidebar();
  });

  // 3. Password visibility toggle
  document.querySelectorAll("[data-pw-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const inp = btn.parentElement.querySelector("input");
      if (!inp) return;
      const show = inp.type === "password";
      inp.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
    });
  });

  // 4. Instant client-side table filtering (data-table-search="#table-id")
  document.querySelectorAll("[data-table-search]").forEach(function (inp) {
    const target = document.querySelector(inp.dataset.tableSearch);
    if (!target) return;
    inp.addEventListener("input", function () {
      const q = inp.value.trim().toLowerCase();
      target.querySelectorAll("tbody tr[data-searchable]").forEach(function (row) {
        const text = (row.dataset.searchable || row.textContent).toLowerCase();
        row.style.display = !q || text.includes(q) ? "" : "none";
      });
    });
  });

  // 5. Floating toast dismissal + gentle auto-fade for success/info toasts
  document.querySelectorAll("[data-toast-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const toast = btn.closest(".toast");
      if (toast) toast.remove();
    });
  });
  document.querySelectorAll(".toast.success, .toast.info").forEach(function (toast) {
    setTimeout(function () {
      toast.style.transition = "opacity .35s ease, transform .35s ease";
      toast.style.opacity = "0";
      toast.style.transform = "translateY(-6px)";
      setTimeout(function () { toast.remove(); }, 360);
    }, 6000);
  });

  // 6. Auth background slideshow (auto-activates when 2+ slides are present)
  document.querySelectorAll("[data-auth-slideshow]").forEach(function (wrap) {
    const slides = wrap.querySelectorAll(".auth-slide");
    if (slides.length < 2) return;
    let idx = 0;
    setInterval(function () {
      slides[idx].classList.remove("active");
      idx = (idx + 1) % slides.length;
      slides[idx].classList.add("active");
    }, 8000);
  });
})();
