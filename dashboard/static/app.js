// Gilded Ace dashboard: chart rendering, theme, filters and table sorting.
(() => {
  "use strict";

  // ---------- theme ----------
  // Figures are authored with light-mode hex values; in dark mode each one is swapped for
  // its dark step (reference palette). Keep in sync with dashboard/charts.py.
  const DARK = {
    "#2a78d6": "#3987e5", "#eb6834": "#d95926", "#1baf7a": "#199e70", "#eda100": "#c98500",
    "#e87ba4": "#d55181", "#6250d6": "#9085e9", "#e34948": "#e66767",
    // card-stock chrome (dashboard/charts.py) -> night panels
    "#1f1d19": "#ece6d6", "#555049": "#cfc8b8", "#e4e0d6": "#2b3933", "#c9c3b6": "#3c4b44",
    "#f8f6f0": "#16231e",
    // sequential blue re-stepped so "more" reads brighter on the dark surface
    "#cde2fb": "#1c2b40", "#9ec5f4": "#184f95", "#1c5cab": "#6da7ec", "#0d366b": "#cde2fb",
  };
  const DARK_RE = new RegExp(Object.keys(DARK).join("|"), "gi");
  const THEMES = ["auto", "light", "dark"];
  const media = matchMedia("(prefers-color-scheme: dark)");

  const storedTheme = () => { try { return localStorage.getItem("theme") || "auto"; } catch (e) { return "auto"; } };
  const isDark = () => {
    const t = document.documentElement.dataset.theme;
    return t ? t === "dark" : media.matches;
  };
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function themed(raw) {
    const fig = JSON.parse(isDark() ? raw.replace(DARK_RE, (m) => DARK[m.toLowerCase()]) : raw);
    const L = fig.layout || {};
    L.hoverlabel = Object.assign({}, L.hoverlabel, {
      bgcolor: cssVar("--surface-2"), bordercolor: cssVar("--border-strong"),
      font: Object.assign({}, (L.hoverlabel || {}).font, { color: cssVar("--text-primary") }),
    });
    L.paper_bgcolor = "rgba(0,0,0,0)";
    L.plot_bgcolor = "rgba(0,0,0,0)";
    fig.layout = L;
    return fig;
  }

  const CONFIG = { responsive: true, displayModeBar: false };

  function renderAll() {
    document.querySelectorAll(".plot[data-fig]").forEach((el) => {
      const src = document.getElementById(el.dataset.fig);
      if (!src) return;
      const fig = themed(src.textContent);
      // Span labels (events) collide on narrow charts; the hover tooltip still names them.
      if (el.clientWidth < 640 && fig.layout.annotations) {
        fig.layout.annotations = fig.layout.annotations.filter((a) => a.name !== "span-label");
      }
      Plotly.react(el, fig.data, fig.layout, CONFIG);
    });
  }

  function applyTheme(t) {
    if (t === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
    try { localStorage.setItem("theme", t === "auto" ? "" : t); } catch (e) {}
    const label = document.getElementById("theme-label");
    if (label) label.textContent = t[0].toUpperCase() + t.slice(1);
    renderAll();
  }

  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const next = THEMES[(THEMES.indexOf(storedTheme() || "auto") + 1) % THEMES.length];
      applyTheme(next);
    });
  }
  media.addEventListener("change", () => { if (!document.documentElement.dataset.theme) renderAll(); });

  // ---------- filters: submit on change, keep bank list consistent with zone ----------
  const form = document.getElementById("filters");
  if (form) {
    const zone = document.getElementById("zone-select");
    const bank = document.getElementById("bank-select");
    const syncBanks = () => {
      [...bank.options].forEach((o) => {
        if (!o.value) return;
        o.hidden = !!zone.value && o.dataset.zone !== zone.value;
      });
    };
    if (zone && bank) {
      syncBanks();
      zone.addEventListener("change", () => { bank.value = ""; });
      bank.addEventListener("change", () => {
        const opt = bank.selectedOptions[0];
        if (opt && opt.dataset.zone) zone.value = opt.dataset.zone;
      });
    }
    form.addEventListener("change", () => {
      // Drop empty / default params so URLs stay short and shareable.
      [...form.elements].forEach((el) => {
        if (!el.name) return;
        const isDefault = (el.name === "start" && el.value === el.min) || (el.name === "end" && el.value === el.max);
        el.disabled = !el.value || isDefault;
      });
      form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  }

  // ---------- sortable tables ----------
  document.querySelectorAll("table.sortable").forEach((table) => {
    const heads = [...table.tHead.rows[0].cells];
    heads.forEach((th, i) => {
      const btn = th.querySelector("button");
      if (!btn) return;
      btn.addEventListener("click", () => {
        const dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
        heads.forEach((h) => h.removeAttribute("aria-sort"));
        th.setAttribute("aria-sort", dir);
        const numeric = th.classList.contains("num");
        const sign = dir === "ascending" ? 1 : -1;
        const body = table.tBodies[0];
        const rows = [...body.rows];
        rows.sort((a, b) => {
          const x = a.cells[i].dataset.sort, y = b.cells[i].dataset.sort;
          if (x === "" || y === "") return (x === "") - (y === "");   // blanks always last
          return sign * (numeric ? parseFloat(x) - parseFloat(y) : x.localeCompare(y, undefined, { numeric: true }));
        });
        body.append(...rows);
      });
    });
  });

  const label = document.getElementById("theme-label");
  if (label) { const t = storedTheme(); label.textContent = t[0].toUpperCase() + t.slice(1); }
  renderAll();
})();
