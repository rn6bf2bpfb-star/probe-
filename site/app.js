/* Trading Center – Frontend. Liest ausschließlich die vom Backend erzeugten JSON-Dateien (data/*.json).
   Es gibt hier keine API-Schlüssel und keine erfundenen Werte: Fehlt ein Wert, steht „–“ bzw. „nicht verfügbar“. */
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const app = $("#app");
  const cache = {};
  const LS = {
    get(k, d) { try { const v = localStorage.getItem("tc." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("tc." + k, JSON.stringify(v)); return true; } catch (e) { return false; } },
  };

  // ------------------------------------------------------------ Formate
  const NF = {};
  const nf = (d) => NF[d] || (NF[d] = new Intl.NumberFormat("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const ok = (v) => v != null && isFinite(v);
  const num = (v, d = 2) => ok(v) ? nf(d).format(v) : "–";
  const sgn = (v, d = 2) => ok(v) ? (v > 0 ? "+" : "") + nf(d).format(v) : "–";
  const pct = (v, d = 1, signed = true) => ok(v) ? (signed && v > 0 ? "+" : "") + nf(d).format(v * 100) + " %" : "–";
  const eur = (v, d = 2) => ok(v) ? nf(d).format(v) + " €" : "–";
  const big = (v) => !ok(v) ? "–" : Math.abs(v) >= 1e12 ? num(v / 1e12, 2) + " Bio." : Math.abs(v) >= 1e9 ? num(v / 1e9, 1) + " Mrd." : Math.abs(v) >= 1e6 ? num(v / 1e6, 0) + " Mio." : num(v, 0);
  const dec = (v) => !ok(v) ? 2 : Math.abs(v) >= 1000 ? 2 : Math.abs(v) >= 1 ? 2 : 4;
  const cls = (v) => !ok(v) || v === 0 ? "" : v > 0 ? "up" : "down";
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ccy = (c) => c === "GBp" ? "GBp" : c || "";
  function px(q) { return q && ok(q.price) ? `${num(q.price, dec(q.price))} ${ccy(q.currency)}` : "nicht verfügbar"; }
  function when(iso, withDate = true) {
    if (!iso) return "–";
    const s = String(iso);
    if (/T00:00:00Z$/.test(s) || s.length === 10) return new Date(s.slice(0, 10) + "T12:00:00Z").toLocaleDateString("de-DE", { timeZone: "Europe/Berlin" });
    const d = new Date(s);
    return withDate ? d.toLocaleString("de-DE", { timeZone: "Europe/Berlin", day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : d.toLocaleTimeString("de-DE", { timeZone: "Europe/Berlin", hour: "2-digit", minute: "2-digit" });
  }
  function ago(iso) {
    if (!iso) return "–";
    const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 1) return "gerade eben"; if (m < 60) return `vor ${m} Min.`; const h = Math.round(m / 60); if (h < 48) return `vor ${h} Std.`; return `vor ${Math.round(h / 24)} Tagen`;
  }
  function qual(q) {
    const k = q && q.quality || "nicht verfügbar";
    const c = { "verzögert": "warn", "nahezu Echtzeit": "ok", "Schlusskurs": "info", "veraltet": "bad", "nicht verfügbar": "bad", "DEMO": "info" }[k] || "";
    return `<span class="pill ${c}" title="${esc((q && q.source) || "")}${q && q.time ? " · " + esc(when(q.time)) : ""}">${esc(k)}</span>`;
  }
  function tag(t) {
    if (!t) return "";
    const c = /DRITTE|ANALYST/.test(t) ? "third" : /MODELL|KI/.test(t) ? "model" : "fact";
    return `<span class="tag ${c}">${esc(t)}</span>`;
  }
  const rating = (r) => `<span class="rating r-${esc(String(r).replace(" ", "-"))}">${esc(r)}</span>`;
  const H = { short: "Trading", long: "Investment" };

  // ------------------------------------------------------------- Daten
  let routeSeq = 0;
  const STALE = new Error("stale");
  async function load(name, force) {
    const seq = routeSeq;
    if (!force && cache[name]) return cache[name];
    const r = await fetch(`data/${name}.json?ts=${Math.floor(Date.now() / 60000)}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    const j = await r.json();
    cache[name] = j;
    if (seq !== routeSeq) throw STALE; // Nutzer hat inzwischen die Seite gewechselt
    return j;
  }
  const safeName = (s) => s.replace(/[^A-Za-z0-9\-_.]/g, "_");

  // ------------------------------------------------------- Navigation
  const NAV = [
    ["", "◧", "Dashboard"], ["signale", "◆", "Signale"], ["depot", "▤", "Depot"], ["alerts", "◉", "Alerts"],
    ["screener", "⌕", "Screener"], ["berichte", "☰", "Berichte"], ["kalender", "▦", "Kalender"], ["risiko", "⚖", "Risiko"],
    ["bilanz", "✓", "Trefferquote"], ["einstellungen", "⚙", "Einstellungen"],
  ];
  const BOTTOM = ["", "signale", "depot", "alerts", "mehr"];
  function renderNav(route) {
    const unread = unreadAlerts();
    $("#sidenav").innerHTML = NAV.map(([r, i, l]) => `<a href="#/${r}" class="${route === r ? "active" : ""}"><span class="ico">${i}</span>${l}${r === "alerts" && unread ? ` <span class="badge">${unread}</span>` : ""}</a>`).join("");
    $("#bottomnav").innerHTML = BOTTOM.map((r) => {
      const n = r === "mehr" ? ["⋯", "Mehr"] : NAV.find((x) => x[0] === r).slice(1);
      const active = route === r || (r === "mehr" && !BOTTOM.includes(route) && route !== "aktie");
      return `<a href="#/${r}" class="${active ? "active" : ""}"><span class="ico">${n[0]}</span>${n[1]}${r === "alerts" && unread ? `<span class="badge">${unread}</span>` : ""}</a>`;
    }).join("");
  }
  function unreadAlerts() {
    const a = cache.alerts; if (!a) return 0;
    const seen = LS.get("alertsSeen", null);
    return a.alerts.filter((x) => x.priority !== "LOW" && (!seen || x.created > seen)).length;
  }

  async function header() {
    try {
      const m = await load("meta");
      const age = (Date.now() - new Date(m.time).getTime()) / 60000;
      const pills = [];
      pills.push(`<span class="pill ${age < 90 ? "ok" : age < 24 * 60 ? "warn" : "bad"}" title="Letzter Lauf des Backends">Stand ${esc(when(m.time))}</span>`);
      if (m.demo) pills.push(`<span class="pill info">DEMO</span>`);
      $("#status").innerHTML = pills.join("");
      const b = [];
      if (m.demo) b.push(`<div class="banner demo">DEMO-MODUS: Alle Kurse, Kennzahlen und Signale sind synthetisch erzeugt und dienen nur zum Testen der Oberfläche.</div>`);
      const local = new Date().toLocaleString("en-US", { timeZone: "Europe/Berlin", weekday: "short", hour: "numeric", hour12: false });
      const weekday = !/Sat|Sun/.test(local);
      if (!m.demo && age > 150 && weekday) b.push(`<div class="banner stale">Letzte Aktualisierung ${esc(ago(m.time))}. Die Überwachung läuft gerade nicht planmäßig – angezeigt wird der letzte verfügbare Datenstand.</div>`);
      $("#banner").innerHTML = b.join("");
    } catch (e) {
      $("#status").innerHTML = `<span class="pill bad">keine Daten</span>`;
      $("#banner").innerHTML = `<div class="banner err">Es liegen noch keine Daten vor (${esc(e.message)}). Das Backend muss mindestens einmal gelaufen sein – siehe Einstellungen → Einrichtung.</div>`;
    }
  }

  async function route() {
    const h = location.hash.replace(/^#\/?/, "");
    const [r, ...rest] = h.split("/");
    const name = r || "";
    const seq = ++routeSeq;
    window.onresize = null;
    renderNav(name === "aktie" ? "signale" : name);
    closeSheet();
    app.innerHTML = `<div class="loading">Lade …</div>`;
    const pages = { "": dashboard, signale: signalsPage, aktie: stockPage, depot: depotPage, screener: screenerPage, berichte: reportsPage, kalender: calendarPage, risiko: riskPage, alerts: alertsPage, bilanz: trackPage, einstellungen: settingsPage, mehr: morePage };
    try {
      await (pages[name] || notFound)(rest.map(decodeURIComponent));
    } catch (e) {
      if (e === STALE || seq !== routeSeq) return;
      console.error(e);
      app.innerHTML = `<div class="card"><h2>Daten nicht verfügbar</h2><p class="muted">${esc(e.message)}</p><p class="small muted">Wenn das System neu ist: Einmal den Workflow in GitHub Actions starten (Einstellungen → Einrichtung).</p></div>`;
    }
    renderNav(name === "aktie" ? "signale" : name);
    window.scrollTo(0, 0);
  }
  function notFound() { app.innerHTML = `<div class="empty">Seite nicht gefunden. <a href="#/">Zum Dashboard</a></div>`; }

  // ----------------------------------------------------------- Dashboard
  async function dashboard() {
    const [mk, sg, dp, al, cal] = await Promise.all([load("market"), load("signals"), load("depot"), load("alerts"), load("calendar")]);
    const env = mk.environment, s = mk.sentiment, v = dp.valuation;
    const envCls = { positiv: "ok", neutral: "warn", negativ: "bad" }[env.verdict];
    const top = sg.signals.filter((x) => x.rating !== "HOLD").sort((a, b) => Math.abs(b.score - 50) - Math.abs(a.score - 50)).slice(0, 6);
    const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Berlin" });
    const evs = cal.events.filter((e) => e.date >= today).slice(0, 6);
    app.innerHTML = `
      <div class="page-head"><div><h1>Dashboard</h1><p>Marktumfeld, Stimmung, Signale und dein Planspiel-Depot auf einen Blick.</p></div></div>
      <div class="grid g3">
        <div class="card">
          <div class="card-head"><h3>Marktumfeld</h3>${tag(env.tag)}</div>
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px"><span class="pill ${envCls}" style="font-size:14px;padding:4px 12px">${esc(env.verdict.toUpperCase())}</span></div>
          <p style="margin:0 0 8px">${esc(env.explanation)}</p>
          <ul class="points small">${env.reasons.map((r) => `<li class="${r.dir === "+" ? "p" : r.dir === "-" ? "n" : ""}">${esc(r.text)}</li>`).join("")}</ul>
        </div>
        <div class="card">
          <div class="card-head"><h3>Angst & Gier</h3>${tag(s.tag)}</div>
          <div class="gauge">${TC_CHART.gauge(s.score, esc(s.label || "nicht verfügbar"))}</div>
          ${s.components.map((c) => `<div class="hbar"><span class="small muted">${esc(c.label.split(" (")[0])}</span><span class="b"><i style="width:${c.score}%"></i></span><span class="num small r">${c.score}</span></div>`).join("")}
          <details><summary>Methode</summary><p class="small muted">${esc(s.method)}</p>${s.components.map((c) => `<div class="small"><b>${esc(c.label)}:</b> ${esc(c.detail)}</div>`).join("")}</details>
        </div>
        <div class="card">
          <div class="card-head"><h3>Planspiel-Depot</h3><a class="small" href="#/depot">öffnen →</a></div>
          <div class="kpi" style="border:0;padding:0;background:none"><div class="l">Depotwert</div><div class="v">${eur(v.total_eur)}</div>
          <div class="s ${cls(v.pnl_eur)}">${sgn(v.pnl_eur)} € (${pct(v.pnl_pct, 2)}) seit Start</div><div class="s ${cls(v.day_eur)}">heute ${sgn(v.day_eur)} €</div></div>
          <dl class="kv" style="margin-top:10px"><dt>Cash</dt><dd>${eur(v.cash_eur)}</dd><dt>Investiert</dt><dd>${eur(v.invested_eur)}</dd><dt>Positionen</dt><dd>${v.positions.length}</dd>
          <dt>Benchmark (${esc(dp.benchmark.symbol)})</dt><dd class="${cls(dp.benchmark.since_start)}">${pct(dp.benchmark.since_start, 2)}</dd></dl>
        </div>
      </div>
      <div class="section"><div class="card-head"><h2>Marktübersicht</h2><span class="meta">Börsenkurse i. d. R. 15–20 Min. verzögert · Quelle je Kachel</span></div>
        <div class="tiles">${mk.overview.map(tile).join("")}</div></div>
      <div class="grid g2 section">
        <div class="card"><div class="card-head"><h3>Zinsen, Inflation & Volatilität</h3><span class="meta">mit Quelle</span></div>${macroBlock(mk)}</div>
        <div class="card"><div class="card-head"><h3>Neueste Alerts</h3><a class="small" href="#/alerts">alle →</a></div>
          <div class="list">${al.alerts.slice(0, 5).map(alertMini).join("") || `<div class="empty">Noch keine Meldungen.</div>`}</div></div>
      </div>
      <div class="section"><div class="card-head"><h2>Stärkste Signale</h2><a class="small" href="#/signale">alle Signale →</a></div>
        <div class="grid g3">${top.map(sigCard).join("") || `<div class="empty">Aktuell keine bestätigten Kauf- oder Verkaufssignale.</div>`}</div></div>
      <div class="grid g2 section">
        <div class="card"><div class="card-head"><h3>KI-Tagesauswahl nach Branchen</h3>${tag("EIGENE MODELLINTERPRETATION")}</div>${picksBlock(sg.picks.slice(0, 5))}</div>
        <div class="card"><div class="card-head"><h3>Nächste Termine</h3><a class="small" href="#/kalender">Kalender →</a></div>
          <div class="list">${evs.map((e) => `<div class="li"><span class="num small muted" style="width:72px">${esc(when(e.date))}</span><div class="grow"><div class="t">${esc(e.title)}</div><div class="d">${esc(e.category_de)}${e.in_depot ? " · im Depot" : ""}</div></div></div>`).join("") || `<div class="empty">Keine Termine.</div>`}</div></div>
      </div>
      ${mk.news && mk.news.length ? `<div class="card section"><div class="card-head"><h3>Marktnachrichten</h3>${tag("BESTÄTIGTE NACHRICHT")}</div><div class="list">${mk.news.slice(0, 8).map(newsItem).join("")}</div></div>` : ""}`;
  }
  function tile(i) {
    if (!i.available) return `<div class="tile"><div class="name">${esc(i.name)}</div><div class="px muted">nicht verfügbar</div><div class="foot"><span>${esc(i.symbol)}</span>${qual(i.quote)}</div></div>`;
    const tr = { aufwärts: "▲ aufwärts", abwärts: "▼ abwärts", seitwärts: "► seitwärts" }[i.trend] || i.trend;
    return `<div class="tile" title="${esc(i.note || "")}">
      <div class="name"><span>${esc(i.name)}</span><span class="${i.trend === "aufwärts" ? "up" : i.trend === "abwärts" ? "down" : "muted"}">${esc(tr)}</span></div>
      <div class="px">${num(i.quote.price, dec(i.quote.price))} <span class="small muted">${esc(ccy(i.quote.currency))}</span></div>
      <div class="chg"><span class="${cls(i.day_pct)}">T ${pct(i.day_pct, 2)}</span><span class="${cls(i.week_pct)}">W ${pct(i.week_pct)}</span><span class="${cls(i.month_pct)}">M ${pct(i.month_pct)}</span></div>
      ${TC_CHART.spark(i.spark)}
      <div class="foot"><span>${esc(when(i.quote.time))}</span>${qual(i.quote)}</div></div>`;
  }
  function macroBlock(mk) {
    const rows = [];
    const m = mk.macro || {};
    Object.values(m).forEach((x) => rows.push(`<dt>${esc(x.label)}</dt><dd>${num(x.value, 2)} % <span class="dim tiny">(${esc(x.date)}${x.prev != null ? `, vorher ${num(x.prev, 2)} %` : ""})</span></dd>`));
    Object.values(mk.sentiment.rates || {}).forEach((x) => rows.push(`<dt>${esc(x.label)}</dt><dd>${num(x.value, 2)} % <span class="dim tiny">${x.month_ago != null ? `(vor 1 M ${num(x.month_ago, 2)} %)` : ""}</span></dd>`));
    const vx = mk.sentiment.vix;
    if (vx) rows.push(`<dt>VIX (Volatilität S&P 500)</dt><dd>${num(vx.value, 1)} <span class="dim tiny">(${esc(vx.level)})</span></dd>`);
    const srcs = Array.from(new Set(Object.values(m).map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.source)}</a>`))).join(", ");
    return rows.length ? `<dl class="kv">${rows.join("")}</dl><p class="tiny muted" style="margin-top:8px">Quellen: ${srcs || "–"}${srcs ? ", " : ""}Yahoo Finance (Renditen, VIX). Fehlende Werte: Einstellungen → Status.</p>` : `<div class="empty">Keine Makrodaten verfügbar.</div>`;
  }
  function picksBlock(picks) {
    if (!picks.length) return `<div class="empty">Heute keine Branche mit bestätigtem Kaufszenario.</div>`;
    return `<div class="list">${picks.map((p) => `<div class="li click" onclick="location.hash='#/aktie/${encodeURIComponent(p.symbol)}'"><div class="grow"><div class="t">${esc(p.name)} <span class="tk mono small muted">${esc(p.symbol)}</span></div>
      <div class="d">${esc(p.sector)} · ${H[p.horizon]} · Unsicherheit ${esc(p.uncertainty)}</div><ul class="points small">${p.why.map((w) => `<li class="p">${esc(w)}</li>`).join("")}${p.against.slice(0, 1).map((w) => `<li class="n">${esc(w)}</li>`).join("")}</ul></div>${rating(p.rating)}</div>`).join("")}</div>`;
  }
  function sigCard(x) {
    const col = x.score >= 50 ? "var(--up)" : "var(--down)";
    return `<div class="sig" onclick="location.hash='#/aktie/${encodeURIComponent(x.symbol)}'">
      <div class="top"><div><div class="nm">${esc(x.name)}</div><div class="tk">${esc(x.symbol)} · ${H[x.horizon]}</div></div>${rating(x.rating)}</div>
      <div class="row"><span>Kurs <b>${px(x.quote)}</b></span><span>Score <b>${x.score}</b></span><span>Unsicherheit <b>${esc(x.uncertainty.level)}</b></span>${x.levels && x.levels.crv != null ? `<span>CRV <b>${num(x.levels.crv, 2)}</b></span>` : ""}</div>
      <div class="scorebar"><i style="width:${x.score}%;background:${col}"></i></div>
      <div class="why">${esc(x.reason)}</div>
      <div class="row tiny"><span>${qual(x.quote)}</span><span>Analyse ${esc(when(x.time))}</span></div></div>`;
  }
  function alertMini(a) {
    return `<div class="li"><span class="pill ${a.priority === "HIGH" ? "bad" : a.priority === "MEDIUM" ? "warn" : "info"}">${a.priority}</span><div class="grow"><div class="t">${esc(a.title)}</div><div class="d">${esc(a.headline)}</div><div class="tiny dim">${esc(ago(a.created))}</div></div></div>`;
  }
  function newsItem(n) {
    return `<div class="li"><div class="grow"><div class="t">${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>` : esc(n.title)}</div>
      <div class="d">${esc(n.publisher || "Quelle unbekannt")} · ${esc(when(n.published))}${n.categories ? " · " + esc(n.categories.join(", ")) : ""}${n.tone ? ` · <span class="${n.tone === "positiv" ? "up" : n.tone === "negativ" ? "down" : ""}" title="${esc(n.tone_method || "")}">${esc(n.tone)}</span>` : ""}</div></div></div>`;
  }

  // ------------------------------------------------------------- Signale
  async function signalsPage() {
    const sg = await load("signals");
    const st = LS.get("sigFilter", { h: "short", r: "action", q: "" });
    const draw = () => {
      LS.set("sigFilter", st);
      let list = sg.signals.filter((x) => x.horizon === st.h);
      if (st.r === "action") list = list.filter((x) => x.rating !== "HOLD");
      else if (st.r !== "all") list = list.filter((x) => x.rating.includes(st.r));
      if (st.q) { const q = st.q.toLowerCase(); list = list.filter((x) => (x.name + x.symbol).toLowerCase().includes(q)); }
      list.sort((a, b) => st.r === "SELL" ? a.score - b.score : b.score - a.score);
      $("#siglist").innerHTML = list.map(sigCard).join("") || `<div class="empty">Keine Signale für diesen Filter.</div>`;
      document.querySelectorAll("[data-h]").forEach((b) => b.classList.toggle("on", b.dataset.h === st.h));
      document.querySelectorAll("[data-r]").forEach((b) => b.classList.toggle("on", b.dataset.r === st.r));
    };
    const counts = (h) => ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"].map((r) => `${r}: ${sg.signals.filter((x) => x.horizon === h && x.rating === r).length}`).join(" · ");
    app.innerHTML = `<div class="page-head"><div><h1>KI-Aktienanalyst – Signale</h1><p>Analyse ${esc(when(sg.time))}. Kein Signal beruht auf einem einzelnen Indikator. Einstufungen sind analytische Orientierung für das Planspiel, keine Anlageberatung.</p></div></div>
      <div class="toolbar"><div class="seg"><button data-h="short">Trading (kurzfristig)</button><button data-h="long">Investment (langfristig)</button></div>
      <div class="seg"><button data-r="action">Kauf & Verkauf</button><button data-r="BUY">Kauf</button><button data-r="SELL">Verkauf</button><button data-r="all">Alle</button></div>
      <input id="sigq" placeholder="Name oder Kürzel" value="${esc(st.q)}"></div>
      <p class="tiny muted" id="sigcounts"></p><div class="grid g3" id="siglist"></div>`;
    app.querySelectorAll("[data-h]").forEach((b) => b.onclick = () => { st.h = b.dataset.h; $("#sigcounts").textContent = counts(st.h); draw(); });
    app.querySelectorAll("[data-r]").forEach((b) => b.onclick = () => { st.r = b.dataset.r; draw(); });
    $("#sigq").oninput = (e) => { st.q = e.target.value; draw(); };
    $("#sigcounts").textContent = counts(st.h);
    draw();
  }

  // ------------------------------------------------------- Einzelanalyse
  async function stockPage([sym]) {
    if (!sym) return notFound();
    const [d, meta] = await Promise.all([load("stocks/" + safeName(sym)), load("meta")]);
    const q = d.quote, t = d.tech, f = d.fundamentals || {};
    const day = q.price && q.prev_close ? q.price / q.prev_close - 1 : null;
    const chartSt = LS.get("chart", { bars: 250, mode: "candle" });
    const tabs = LS.get("stockTab", "short");
    app.innerHTML = `
      <div class="page-head"><div><h1>${esc(d.name)} <span class="mono muted small">${esc(d.symbol)}</span></h1>
        <p>${esc(f.sector || "")}${f.industry ? " · " + esc(f.industry) : ""}${f.country ? " · " + esc(f.country) : ""}</p></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn buy" id="bBuy">Virtuell kaufen</button>${d.in_depot ? `<button class="btn sell" id="bSell">Virtuell verkaufen</button>` : ""}
        <button class="btn" id="bWatch">${d.on_watchlist ? "Von Watchlist entfernen" : "Auf Watchlist"}</button><button class="btn" id="bAlert">Kursmarke</button></div></div>
      <div class="kpis">
        <div class="kpi"><div class="l">Letzter Kurs</div><div class="v">${px(q)}</div><div class="s">${qual(q)} <span class="tiny dim">${esc(when(q.time))}</span></div></div>
        <div class="kpi"><div class="l">Tag</div><div class="v ${cls(day)}">${pct(day, 2)}</div><div class="s muted">Vortag ${num(q.prev_close, dec(q.prev_close))}</div></div>
        <div class="kpi"><div class="l">1 Monat / 1 Jahr</div><div class="v"><span class="${cls(t.perf_1m)}">${pct(t.perf_1m)}</span></div><div class="s ${cls(t.perf_1y)}">${pct(t.perf_1y)} 1 J</div></div>
        <div class="kpi"><div class="l">Marktkap. / Trend</div><div class="v">${big(f.market_cap)}</div><div class="s">${esc(t.trend || "–")}</div></div>
      </div>
      <div class="card section">
        <div class="toolbar" style="margin-bottom:6px"><div class="seg" id="rng">${[[63, "3M"], [126, "6M"], [250, "1J"], [400, "Max"]].map(([b, l]) => `<button data-b="${b}" class="${chartSt.bars == b ? "on" : ""}">${l}</button>`).join("")}</div>
        <div class="seg" id="mode"><button data-m="candle" class="${chartSt.mode === "candle" ? "on" : ""}">Kerzen</button><button data-m="line" class="${chartSt.mode === "line" ? "on" : ""}">Linie</button></div><span class="tiny muted">Tageskurse · ${esc(d.source)}</span></div>
        <div id="chart"></div>
        <div class="legend"><span><i style="background:${TC_CHART.colors.sma20}"></i>SMA 20</span><span><i style="background:${TC_CHART.colors.sma50}"></i>SMA 50</span><span><i style="background:${TC_CHART.colors.sma200}"></i>SMA 200</span><span><i style="background:#22d3ee"></i>Unterstützung</span><span><i style="background:#ef4444"></i>Widerstand / Verlustbereich</span></div>
      </div>
      <div class="section"><div class="seg" id="htab"><button data-t="short" class="${tabs === "short" ? "on" : ""}">Trading (kurzfristig)</button><button data-t="long" class="${tabs === "long" ? "on" : ""}">Investment (langfristig)</button></div></div>
      <div id="sigdetail" class="section"></div>
      <div class="grid g2 section">
        <div class="card"><div class="card-head"><h3>Technische Kennzahlen</h3>${tag("BESTÄTIGTE DATEN")}</div>${techTable(t)}</div>
        <div class="card"><div class="card-head"><h3>Fundamentaldaten</h3><span class="meta">${esc(f._source || "–")} · ${esc(when(f._fetched))}</span></div>${fundTable(f)}</div>
      </div>
      <div class="grid g2 section">
        <div class="card"><div class="card-head"><h3>Nachrichten</h3>${tag("BESTÄTIGTE NACHRICHT")}</div><div class="list">${(d.signals.short.news.items || []).map(newsItem).join("") || `<div class="empty">Keine Meldungen der letzten 7 Tage in den abgerufenen Quellen.</div>`}</div></div>
        <div class="card"><div class="card-head"><h3>Termine & Analysten</h3></div>${eventsBlock(d.events)}${d.summary ? `<details><summary>Geschäftsmodell (Unternehmensangabe via Yahoo)</summary><p class="small">${esc(d.summary)}…</p></details>` : ""}</div>
      </div>`;
    const drawChart = () => {
      if (!$("#chart")) return;
      const s = d.signals[LS.get("stockTab", "short")], L = [];
      (t.sr && t.sr.supports || []).slice(0, 2).forEach((z) => L.push({ y: z.level, color: "#22d3ee", label: "U " + num(z.level, dec(z.level)) }));
      (t.sr && t.sr.resistances || []).slice(0, 2).forEach((z) => L.push({ y: z.level, color: "#ef4444", label: "W " + num(z.level, dec(z.level)) }));
      if (s.levels && s.levels.risk_level) L.push({ y: s.levels.risk_level, color: "#f87171", label: "Verlustbereich" });
      TC_CHART.price($("#chart"), d.history, { bars: chartSt.bars, mode: chartSt.mode, levels: L, height: window.innerWidth < 700 ? 280 : 360 });
    };
    const drawSig = () => { $("#sigdetail").innerHTML = signalDetail(d.signals[LS.get("stockTab", "short")]); };
    app.querySelectorAll("#rng button").forEach((b) => b.onclick = () => { chartSt.bars = +b.dataset.b; LS.set("chart", chartSt); app.querySelectorAll("#rng button").forEach((x) => x.classList.toggle("on", x === b)); drawChart(); });
    app.querySelectorAll("#mode button").forEach((b) => b.onclick = () => { chartSt.mode = b.dataset.m; LS.set("chart", chartSt); app.querySelectorAll("#mode button").forEach((x) => x.classList.toggle("on", x === b)); drawChart(); });
    app.querySelectorAll("#htab button").forEach((b) => b.onclick = () => { LS.set("stockTab", b.dataset.t); app.querySelectorAll("#htab button").forEach((x) => x.classList.toggle("on", x === b)); drawSig(); drawChart(); });
    $("#bBuy").onclick = () => orderSheet({ side: "BUY", symbol: d.symbol, quote: q, name: d.name, sig: d.signals[LS.get("stockTab", "short")] });
    if ($("#bSell")) $("#bSell").onclick = () => orderSheet({ side: "SELL", symbol: d.symbol, quote: q, name: d.name });
    $("#bWatch").onclick = () => sendCommand({ type: d.on_watchlist ? "watch_remove" : "watch_add", symbol: d.symbol });
    $("#bAlert").onclick = () => priceAlertSheet(d.symbol, q);
    drawSig(); drawChart();
    window.onresize = debounce(drawChart, 200);
  }

  function signalDetail(s) {
    const L = s.levels || {};
    const lv = (l, v) => `<div><div class="l">${l}</div><div class="v">${ok(v) ? num(v, dec(v)) : "–"}</div></div>`;
    const pts = (arr) => arr.map((p) => `<li class="${p.dir > 0 ? "p" : p.dir < 0 ? "n" : ""}">${esc(p.text)} ${tag(p.tag)}</li>`).join("");
    return `<div class="card">
      <div class="card-head"><div><h2>${esc(s.horizon_label)}</h2><div class="tiny muted">1. ${esc(s.name)} (${esc(s.symbol)}) · 2. Kurs ${px(s.quote)} ${qual(s.quote)} · 3. Analyse ${esc(when(s.time))}</div></div>${rating(s.rating)}</div>
      <div class="note">${esc(s.rating_text)} – Score ${s.score} ± ${s.score_band} (0 = sehr negativ, 100 = sehr positiv). ${tag(s.tag)}</div>
      ${s.rating_note ? `<div class="note warn">${esc(s.rating_note)}</div>` : ""}
      <h3 style="margin-top:12px">4. Begründung</h3><p>${esc(s.reason)}</p>
      <div class="grid g2">
        <div><h3>5. Fundamentale Bewertung · ${s.fundamental.score}/100 <span class="dim">(Abdeckung ${pct(s.fundamental.coverage, 0, false)})</span></h3><ul class="points small">${pts(s.fundamental.points)}</ul></div>
        <div><h3>6. Technische Bewertung · ${s.technical.score}/100</h3><ul class="points small">${pts(s.technical.points)}</ul></div>
      </div>
      <h3 style="margin-top:12px">7. Relevante Nachrichten · ${s.news.score}/100</h3><ul class="points small">${pts(s.news.points) || "<li>Keine verwertbaren Nachrichten.</li>"}</ul>
      <h3 style="margin-top:12px">8.–9. Szenarien & Verlustbereich</h3>
      <div class="levels">${lv("Bear-Szenario", L.scenario_bear)}${lv("Basis-Szenario", L.scenario_base)}${lv("Bull-Szenario", L.scenario_bull)}${lv("Verlustbereich", L.risk_level)}</div>
      <p class="tiny muted">${esc(L.method || "")} ${esc(L.risk_text || "")}${L.crv != null ? ` · Chance-Risiko-Verhältnis bis Basis: ${num(L.crv, 2)}` : ""}</p>
      <h3 style="margin-top:12px">10. Unsicherheit: ${esc(s.uncertainty.level)} (${s.uncertainty.score}/100)</h3><p class="small muted">${esc(s.uncertainty.reasons.join(", ") || "keine besonderen Unsicherheitsfaktoren")}</p>
      <div class="grid g2"><div><h3>11. Signal wird ungültig, wenn …</h3><ul class="points small">${s.invalidation.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div><h3>Gegenargumente</h3><ul class="points small">${s.counterarguments.map((x) => `<li class="n">${esc(x)}</li>`).join("")}</ul></div></div>
      <p class="tiny dim" style="margin-top:10px">${esc(s.disclaimer)}</p></div>`;
  }
  function techTable(t) {
    const r = [["SMA 20 / 50", `${num(t.sma20)} / ${num(t.sma50)}`], ["SMA 100 / 200", `${num(t.sma100)} / ${num(t.sma200)}`], ["Kreuzung (20 T.)", t.cross_20d === "golden_cross" ? "Golden Cross" : t.cross_20d === "death_cross" ? "Death Cross" : "–"],
      ["RSI (14)", num(t.rsi, 1)], ["MACD / Signal", `${num(t.macd, 3)} / ${num(t.macd_signal, 3)}`], ["Bollinger-Position", t.boll_pos != null ? pct(t.boll_pos, 0, false) : "–"],
      ["ATR (14)", `${num(t.atr)} (${pct(t.atr_pct, 1, false)})`], ["ADX (Trendstärke)", num(t.adx, 1)], ["Volumen rel. (20 T.)", t.rvol != null ? num(t.rvol, 2) + "×" : "–"],
      ["Ø-Volumen 20 T.", big(t.avg_volume_20)], ["Volatilität 60 T. p. a.", pct(t.vol_60, 1, false)], ["52-W-Hoch / -Tief", `${num(t.high_52w)} / ${num(t.low_52w)}`],
      ["Abstand 52-W-Hoch", pct(t.dist_52w_high)], ["Rel. Stärke 1 M / 6 M", `${pct(t.rel_strength_1m)} / ${pct(t.rel_strength_6m)}`],
      ["Trendkanal 60 T.", t.channel ? `${num(t.channel.lower)} – ${num(t.channel.upper)} (R² ${num(t.channel.r2, 2)})` : "–"],
      ["Unterstützungen", (t.sr && t.sr.supports || []).map((z) => num(z.level)).join(" · ") || "–"], ["Widerstände", (t.sr && t.sr.resistances || []).map((z) => num(z.level)).join(" · ") || "–"]];
    return `<dl class="kv">${r.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
  }
  function fundTable(f) {
    const hist = (h) => h && h.length ? h.slice(0, 4).map((x) => `${x.date.slice(0, 4)}: ${big(x.value)}`).join(" · ") : "–";
    const r = [["KGV / erw. KGV", `${num(f.pe, 1)} / ${num(f.forward_pe, 1)}`], ["KBV", num(f.pb, 2)], ["PEG", num(f.peg, 2)], ["EPS", num(f.eps, 2)],
      ["Umsatzwachstum J/J", pct(f.revenue_growth)], ["Gewinnwachstum J/J", pct(f.earnings_growth)], ["Operative Marge", pct(f.operating_margin, 1, false)], ["Nettomarge", pct(f.profit_margin, 1, false)],
      ["Eigenkapitalrendite", pct(f.roe, 1, false)], ["Eigenkapitalquote", pct(f.equity_ratio, 0, false)], ["Verschuldungsgrad", num(f.debt_to_equity, 2)],
      ["Free Cashflow", big(f.free_cashflow)], ["Operativer Cashflow", big(f.operating_cashflow)], ["Dividendenrendite", pct(f.dividend_yield, 2, false)], ["Ausschüttungsquote", pct(f.payout_ratio, 0, false)],
      ["Beta", num(f.beta, 2)], ["Umsatz (Jahre)", hist(f.revenue_history)], ["Gewinn (Jahre)", hist(f.net_income_history)]];
    const an = f.analyst_count ? `<p class="small" style="margin-top:8px">${tag("ANALYSTENEINSCHÄTZUNG (Dritte)")} ${f.analyst_count} Analysten, Kursziel Ø ${num(f.analyst_target_mean)} (Spanne ${num(f.analyst_target_low)}–${num(f.analyst_target_high)}), Empfehlung ${esc(f.recommendation_key || "–")} (${num(f.recommendation_mean, 1)} auf Skala 1 = Kauf bis 5 = Verkauf)</p>` : "";
    return `<dl class="kv">${r.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>${an}${f._stale ? `<p class="note warn">Aus älterem Cache – aktueller Abruf fehlgeschlagen.</p>` : ""}<p class="tiny dim">Werte in Berichtswährung des Unternehmens. Fehlende Werte liefert die Quelle nicht.</p>`;
  }
  function eventsBlock(e) {
    const c = e.calendar || {}, out = [];
    if (c.earnings_date) out.push(`<dt>Nächste Quartalszahlen</dt><dd>${esc(when(c.earnings_date.slice(0, 10)))}</dd>`);
    if (c.ex_dividend_date) out.push(`<dt>Ex-Dividende</dt><dd>${esc(when(c.ex_dividend_date.slice(0, 10)))}</dd>`);
    const er = (e.earnings || []).filter((x) => x.eps_reported != null).slice(0, 4).map((x) => `<tr><td>${esc(when(x.date.slice(0, 10)))}</td><td class="r num">${num(x.eps_estimate)}</td><td class="r num">${num(x.eps_reported)}</td><td class="r num ${cls(x.surprise_pct)}">${x.surprise_pct != null ? sgn(x.surprise_pct, 1) + " %" : "–"}</td></tr>`).join("");
    const up = (e.upgrades || []).slice(0, 6).map((u) => `<tr><td>${esc(when(u.date))}</td><td>${esc(u.firm)}</td><td>${esc(u.from || "–")} → ${esc(u.to || "–")}</td></tr>`).join("");
    return `<dl class="kv">${out.join("") || "<dt>Termine</dt><dd>nicht verfügbar</dd>"}</dl>
      ${er ? `<h3 style="margin-top:12px">Gewinnüberraschungen</h3><div class="table-wrap"><table><tr><th>Datum</th><th class="r">EPS erw.</th><th class="r">EPS ist</th><th class="r">Überr.</th></tr>${er}</table></div>` : ""}
      ${up ? `<h3 style="margin-top:12px">Analysten-Änderungen ${tag("Dritte")}</h3><div class="table-wrap"><table><tr><th>Datum</th><th>Haus</th><th>Einstufung</th></tr>${up}</table></div>` : ""}`;
  }

  // ---------------------------------------------------------------- Depot
  async function depotPage() {
    const [dp, meta] = await Promise.all([load("depot"), load("meta")]);
    const v = dp.valuation, m = dp.metrics || {}, tr = dp.trades || {};
    const open = dp.orders.filter((o) => o.status === "offen");
    const done = dp.orders.filter((o) => o.status !== "offen").slice(-30).reverse();
    const pending = LS.get("pending", []).filter((p) => Date.now() - p.t < 30 * 60000);
    app.innerHTML = `
      <div class="page-head"><div><h1>Virtuelles Depot</h1><p>Planspiel mit ${eur(dp.valuation.start_capital, 0)} Startkapital seit ${esc(when(dp.created))}. Keine echten Transaktionen.</p></div>
        <div style="display:flex;gap:8px"><button class="btn buy" id="newOrder">Neue Order</button></div></div>
      ${pending.length ? `<div class="note warn">${pending.length} Befehl(e) gesendet, werden beim nächsten Lauf verarbeitet (meist 2–5 Min.): ${pending.map((p) => esc(p.label)).join(", ")}</div>` : ""}
      <div class="kpis">
        <div class="kpi"><div class="l">Depotwert</div><div class="v">${eur(v.total_eur)}</div><div class="s ${cls(v.pnl_eur)}">${sgn(v.pnl_eur)} € · ${pct(v.pnl_pct, 2)}</div></div>
        <div class="kpi"><div class="l">Cash</div><div class="v">${eur(v.cash_eur)}</div><div class="s muted">${pct(v.cash_eur / v.total_eur, 0, false)} des Depots</div></div>
        <div class="kpi"><div class="l">Realisiert / Unrealisiert</div><div class="v ${cls(v.realized_eur)}">${sgn(v.realized_eur)} €</div><div class="s ${cls(v.unrealized_eur)}">${sgn(v.unrealized_eur)} € offen</div></div>
        <div class="kpi"><div class="l">Kosten / Steuern</div><div class="v">${eur(v.fees_eur)}</div><div class="s muted">Steuern ${eur(v.taxes_eur)}</div></div>
      </div>
      <div class="card section"><div class="card-head"><h3>Wertentwicklung</h3><span class="meta">Benchmark ${esc(dp.benchmark.symbol)} seit Start: <span class="${cls(dp.benchmark.since_start)}">${pct(dp.benchmark.since_start, 2)}</span></span></div><div id="eq"></div></div>
      <div class="card section"><div class="card-head"><h3>Positionen</h3><span class="meta">Bewertung in EUR zum letzten verfügbaren Kurs</span></div>
        ${v.positions.length ? `<div class="table-wrap"><table><tr><th>Wert</th><th class="r">Stück</th><th class="r hide-sm">Ø Einstand</th><th class="r">Kurs</th><th class="r">Wert €</th><th class="r">G/V</th><th class="r hide-sm">Anteil</th><th></th></tr>
        ${v.positions.map((p) => `<tr class="click" onclick="location.hash='#/aktie/${encodeURIComponent(p.symbol)}'"><td class="wrap"><b>${esc(p.name)}</b><div class="tiny muted mono">${esc(p.symbol)} · ${esc(p.strategy || "")}</div></td>
        <td class="r num">${num(p.qty, p.qty % 1 ? 4 : 0)}</td><td class="r num hide-sm">${num(p.avg_price_local, dec(p.avg_price_local))} ${esc(ccy(p.currency))}<div class="tiny dim">${eur(p.avg_cost_eur)} inkl. Geb.</div></td>
        <td class="r num">${num(p.quote.price, dec(p.quote.price))}<div>${qual(p.quote)}</div></td><td class="r num">${eur(p.value_eur)}${p.value_note ? `<div class="tiny down">${esc(p.value_note)}</div>` : ""}</td>
        <td class="r num ${cls(p.unrealized_eur)}">${sgn(p.unrealized_eur)} €<div>${pct(p.unrealized_pct)}</div></td><td class="r num hide-sm">${pct(p.weight, 1, false)}</td>
        <td><button class="btn small sell" data-sell="${esc(p.symbol)}">Verkaufen</button></td></tr>`).join("")}</table></div>` : `<div class="empty">Noch keine Positionen. Über „Neue Order“ oder in einer Einzelanalyse virtuell kaufen.</div>`}
      </div>
      <div class="card section"><div class="card-head"><h3>Offene Orders</h3></div>
        ${open.length ? `<div class="table-wrap"><table><tr><th>Erteilt</th><th>Wert</th><th>Art</th><th class="r">Menge</th><th class="r">Limit/Stop</th><th>Hinweis</th><th></th></tr>${open.map((o) => `<tr><td>${esc(when(o.created_at))}</td><td class="mono">${esc(o.symbol)}</td><td>${o.side === "BUY" ? '<span class="up">Kauf</span>' : '<span class="down">Verkauf</span>'} ${esc(o.type)}</td><td class="r num">${o.qty ? num(o.qty, o.qty % 1 ? 4 : 0) : eur(o.amount_eur)}</td><td class="r num">${num(o.limit || o.stop)}</td><td class="small">${esc(o.note || o.strategy || "")}</td><td><button class="btn small" data-cancel="${esc(o.id)}">Storno</button></td></tr>`).join("")}</table></div>` : `<div class="empty">Keine offenen Orders.</div>`}
        <p class="tiny muted">Market-Orders werden zum Eröffnungskurs des ersten Kursbalkens nach Verarbeitung ausgeführt, Limit/Stop sobald ein späterer Balken die Marke erreicht. Prüfung bei jedem Lauf (werktags stündlich).</p>
      </div>
      <div class="grid g2 section">
        <div class="card"><div class="card-head"><h3>Performance-Auswertung</h3></div>
          <dl class="kv"><dt>Max. Drawdown</dt><dd class="down">${pct(m.max_drawdown)}</dd><dt>Aktueller Drawdown</dt><dd>${pct(m.current_drawdown)}</dd><dt>Längste Verlustphase</dt><dd>${m.longest_underwater_days != null ? m.longest_underwater_days + " Tage" : "–"}</dd>
          <dt>Volatilität p. a.</dt><dd>${pct(m.volatility, 1, false)}</dd><dt>Sharpe Ratio</dt><dd>${num(m.sharpe, 2)}</dd><dt>Abgeschlossene Trades</dt><dd>${tr.trades_closed || 0}</dd>
          <dt>Trefferquote</dt><dd>${pct(tr.win_rate, 0, false)}</dd><dt>Ø Gewinn / Ø Verlust</dt><dd>${eur(tr.avg_win)} / ${eur(tr.avg_loss)}</dd><dt>Profit Factor</dt><dd>${num(tr.profit_factor, 2)}</dd>
          <dt>Längste Verlustserie</dt><dd>${tr.max_losing_streak != null ? tr.max_losing_streak : "–"}</dd><dt>Ausführungen 7 Tage</dt><dd>${tr.trades_last_7d || 0}</dd></dl>
          ${m.sharpe_note ? `<p class="tiny dim">${esc(m.sharpe_note)}</p>` : ""}${m.note ? `<p class="tiny dim">${esc(m.note)}</p>` : ""}</div>
        <div class="card"><div class="card-head"><h3>Welche Strategie funktioniert?</h3></div>
          ${(tr.by_strategy || []).length ? `<div class="table-wrap"><table><tr><th>Strategie</th><th class="r">Trades</th><th class="r">Treffer</th><th class="r">Ergebnis</th><th class="r">Kosten</th></tr>${tr.by_strategy.map((b) => `<tr><td>${esc(b.strategy)}</td><td class="r num">${b.n}</td><td class="r num">${pct(b.win_rate, 0, false)}</td><td class="r num ${cls(b.realized_eur)}">${sgn(b.realized_eur)} €</td><td class="r num">${eur(b.fees_eur)}</td></tr>`).join("")}</table></div>` : `<div class="empty">Noch keine abgeschlossenen Trades. Vergib bei jeder Order einen Strategienamen – hier siehst du dann, was funktioniert.</div>`}
          <p class="tiny muted">Ergebnis = realisierter Gewinn/Verlust vor Steuern, nach Gebühren.</p></div>
      </div>
      <div class="card section"><div class="card-head"><h3>Transaktionshistorie</h3></div>
        ${dp.transactions.length ? `<div class="table-wrap"><table><tr><th>Zeit</th><th>Wert</th><th>Art</th><th class="r">Stück</th><th class="r">Kurs</th><th class="r">Betrag €</th><th class="r">Gebühr</th><th class="r">G/V €</th><th class="r">Steuer</th></tr>${dp.transactions.slice().reverse().map((t) => `<tr><td>${esc(when(t.time))}</td><td class="mono">${esc(t.symbol)}</td><td>${t.side === "BUY" ? '<span class="up">Kauf</span>' : '<span class="down">Verkauf</span>'} ${esc(t.type)}</td><td class="r num">${num(t.qty, t.qty % 1 ? 4 : 0)}</td><td class="r num">${num(t.price, dec(t.price))} ${esc(ccy(t.currency))}</td><td class="r num">${eur(t.gross_eur)}</td><td class="r num">${eur(t.fees_eur)}</td><td class="r num ${cls(t.realized_eur)}">${t.realized_eur != null ? sgn(t.realized_eur) : ""}</td><td class="r num">${t.tax_eur ? eur(t.tax_eur) : ""}</td></tr>`).join("")}</table></div>` : `<div class="empty">Noch keine Transaktionen.</div>`}
      </div>
      <div class="card section"><div class="card-head"><h3>Erledigte Orders</h3></div>${done.length ? `<div class="list">${done.map((o) => `<div class="li"><span class="pill ${o.status === "ausgeführt" ? "ok" : o.status === "abgelehnt" ? "bad" : ""}">${esc(o.status)}</span><div class="grow"><div class="t mono small">${esc(o.side)} ${esc(o.type)} ${esc(o.symbol)}</div><div class="d">${esc(o.reason || (o.fill ? `${num(o.fill.qty, 4)} zu ${num(o.fill.price, dec(o.fill.price))} am ${when(o.fill.time)}` : ""))}</div></div></div>`).join("")}</div>` : `<div class="empty">–</div>`}</div>
      <div class="card section"><div class="card-head"><h3>Simulationsannahmen</h3><span class="meta">änderbar in config/settings.yaml</span></div>${assumptions(dp.assumptions, v.tax_state)}
        <div style="margin-top:10px"><button class="btn small" id="reset">Depot zurücksetzen</button></div></div>`;
    const eq = dp.equity.map((p) => ({ t: p.time, v: p.value }));
    TC_CHART.line($("#eq"), [{ name: "Depotwert", values: eq, color: "#f5a623" }], { height: 220, fmt: (x) => num(x, 0) + " €", fill: true, empty: "Die Kurve entsteht ab dem zweiten Lauf." });
    $("#newOrder").onclick = () => orderSheet({ side: "BUY" });
    app.querySelectorAll("[data-sell]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); const p = v.positions.find((x) => x.symbol === b.dataset.sell); orderSheet({ side: "SELL", symbol: p.symbol, quote: p.quote, name: p.name, qty: p.qty }); });
    app.querySelectorAll("[data-cancel]").forEach((b) => b.onclick = () => sendCommand({ type: "cancel", order_id: b.dataset.cancel }, `Storno ${b.dataset.cancel}`));
    $("#reset").onclick = () => { if (confirm("Depot wirklich auf das Startkapital zurücksetzen? Positionen, Orders und Historie des Planspiels werden archiviert.")) sendCommand({ type: "reset" }, "Depot-Reset"); };
  }
  function assumptions(a, tax) {
    if (!a) return "–";
    const t = a.taxes || {};
    return `<dl class="kv"><dt>Gebühr je Order</dt><dd>${eur(a.fee_fixed)} + ${num(a.fee_percent, 2)} %</dd><dt>Währungsaufschlag</dt><dd>${num(a.fx_fee_percent, 2)} %</dd><dt>Slippage</dt><dd>${num(a.slippage_bps, 0)} Basispunkte</dd>
      <dt>Steuern simuliert</dt><dd>${t.enabled ? `ja: ${num(t.rate * 100, 0)} % + Soli${t.church ? " + KiSt" : ""}, Freibetrag ${eur(t.allowance, 0)}` : "nein"}</dd>
      ${tax ? `<dt>Freibetrag genutzt ${tax.year}</dt><dd>${eur(tax.allowance_used)}</dd><dt>Verlusttopf Aktien / sonstige</dt><dd>${eur(tax.loss_pot_stocks)} / ${eur(tax.loss_pot_other)}</dd>` : ""}</dl>
      <p class="tiny dim">Vereinfachte Steuersimulation (keine Steuerberatung): Aktienverluste nur mit Aktiengewinnen verrechenbar, Teilfreistellung ${pct(t.etf_partial_exemption, 0, false)} für Aktien-ETFs, keine Vorabpauschale.</p>`;
  }

  // --------------------------------------------------------- Ordermaske
  async function orderSheet(o) {
    const [dp, sc, meta] = await Promise.all([load("depot"), load("screener"), load("meta")]);
    const total = dp.valuation.total_eur, cash = dp.valuation.cash_eur;
    const sym0 = o.symbol || "";
    const opts = sc.rows.map((r) => `<option value="${esc(r.symbol)}">${esc(r.name)}</option>`).join("");
    openSheet(`<div class="card-head"><h2>Virtuelle Order</h2><button class="icon-btn" data-close>✕</button></div>
      <div class="note">Planspiel: Es wird nichts an einer echten Börse ausgeführt. ${o.sig ? `Aktuelles Signal: ${rating(o.sig.rating)}` : ""}</div>
      <form class="form" id="of">
        <div class="seg"><button type="button" data-side="BUY">Kauf</button><button type="button" data-side="SELL">Verkauf</button></div>
        <label class="f">Wert (Yahoo-Kürzel)<input name="symbol" list="syms" value="${esc(sym0)}" required autocapitalize="characters" placeholder="z. B. SAP.DE, NVDA"><datalist id="syms">${opts}</datalist></label>
        <div class="row2"><label class="f">Menge in<select name="unit"><option value="qty">Stück</option><option value="eur">Euro</option></select></label><label class="f">Menge<input name="amount" inputmode="decimal" required value="${o.qty ? String(o.qty).replace(".", ",") : ""}"></label></div>
        <div class="row2"><label class="f">Ordertyp<select name="type"><option value="MARKET">Market</option><option value="LIMIT">Limit</option><option value="STOP">Stop</option></select></label><label class="f" id="lvlwrap" hidden><span id="lvllbl">Limit</span><input name="level" inputmode="decimal"></label></div>
        <div class="row2" id="bracket"><label class="f">Stop-Loss (optional)<input name="sl" inputmode="decimal" value="${o.sig && o.sig.levels && o.sig.levels.risk_level && o.side === "BUY" ? num(o.sig.levels.risk_level, 2).replace(/\./g, "") : ""}"></label><label class="f">Take-Profit (optional)<input name="tp" inputmode="decimal" value="${o.sig && o.sig.levels && o.sig.levels.scenario_base && o.side === "BUY" ? num(o.sig.levels.scenario_base, 2).replace(/\./g, "") : ""}"></label></div>
        <label class="f">Strategie (für die Auswertung)<input name="strategy" list="strats" value="${o.sig ? (o.sig.horizon === "short" ? "Signal kurzfristig" : "Signal langfristig") : "manuell"}"><datalist id="strats"><option>Signal kurzfristig</option><option>Signal langfristig</option><option>Momentum</option><option>Rücksetzer kaufen</option><option>Ausbruch</option><option>Dividende</option><option>ETF-Sparplan</option><option>manuell</option></datalist></label>
        <label class="f">Notiz / These<input name="note" maxlength="200" placeholder="Warum dieser Trade?"></label>
        <div id="preview" class="note"></div>
        <button class="btn primary" type="submit">Order senden</button>
      </form>`);
    const f = $("#of");
    let side = o.side || "BUY";
    const setSide = (s) => { side = s; document.querySelectorAll("[data-side]").forEach((b) => b.classList.toggle("on", b.dataset.side === s)); $("#bracket").hidden = s !== "BUY"; prev(); };
    document.querySelectorAll("[data-side]").forEach((b) => b.onclick = () => setSide(b.dataset.side));
    const P = (x) => { const v = parseFloat(String(x || "").replace(/\./g, "").replace(",", ".")); return isFinite(v) ? v : null; };
    const prev = () => {
      const sym = f.symbol.value.trim().toUpperCase(), row = sc.rows.find((r) => r.symbol === sym);
      const typ = f.type.value; $("#lvlwrap").hidden = typ === "MARKET"; $("#lvllbl").textContent = typ === "LIMIT" ? "Limit" : "Stop-Kurs";
      if (!row) { $("#preview").innerHTML = sym ? `${esc(sym)} ist nicht im beobachteten Universum. Die Order wird angenommen, wenn das Backend einen Kurs abrufen kann.` : "Wert wählen."; return; }
      const price = typ === "MARKET" ? row.price : P(f.level.value) || row.price, amt = P(f.amount.value);
      const fxr = row.currency === "EUR" ? 1 : null;
      let h = `Letzter Kurs ${num(row.price, dec(row.price))} ${esc(ccy(row.currency))} (${esc(row.quality)}, ${esc(when(row.time))}).`;
      if (amt && fxr) {
        const qty = f.unit.value === "qty" ? amt : amt / price, val = qty * price;
        h += ` Ca. ${num(qty, qty % 1 ? 3 : 0)} Stück ≈ ${eur(val)} zzgl. Gebühren (${pct(val / total, 1, false)} des Depots, Cash ${eur(cash)}).`;
        const sl = P(f.sl.value), tp = P(f.tp.value);
        if (side === "BUY" && sl && sl < price) { const risk = (price - sl) * qty; h += ` Risiko bis Stop ${eur(risk)} = ${pct(risk / total, 2, false)} des Depots.`; if (risk / total > 0.02) h += ` <span class="down">Über 2 %-Regel.</span>`; if (tp && tp > price) h += ` CRV ${num((tp - price) / (price - sl), 2)}.`; }
        if (val / total > 0.2 && side === "BUY") h += ` <span class="down">Position über 20 % des Depots.</span>`;
      } else if (amt) h += ` Umrechnung in EUR erfolgt bei Ausführung mit dem dann aktuellen Wechselkurs.`;
      $("#preview").innerHTML = h;
    };
    f.oninput = prev; setSide(side);
    f.onsubmit = (e) => {
      e.preventDefault();
      const sym = f.symbol.value.trim().toUpperCase(), amt = P(f.amount.value), typ = f.type.value, lvl = P(f.level.value);
      if (!sym || !amt || amt <= 0) return toast("Wert und Menge angeben.");
      if (typ !== "MARKET" && !lvl) return toast("Limit bzw. Stop-Kurs angeben.");
      const cmd = { type: "order", side, symbol: sym, order_type: typ, strategy: f.strategy.value || "manuell", note: f.note.value };
      if (f.unit.value === "qty") cmd.qty = amt; else cmd.amount_eur = amt;
      if (typ === "LIMIT") cmd.limit = lvl; if (typ === "STOP") cmd.stop = lvl;
      if (side === "BUY") { const sl = P(f.sl.value), tp = P(f.tp.value); if (sl) cmd.sl = sl; if (tp) cmd.tp = tp; }
      cmd.created_at = new Date().toISOString().slice(0, 19) + "Z";
      sendCommand(cmd, `${side === "BUY" ? "Kauf" : "Verkauf"} ${sym}`);
    };
  }
  function priceAlertSheet(sym, q) {
    openSheet(`<div class="card-head"><h2>Kursmarke für ${esc(sym)}</h2><button class="icon-btn" data-close>✕</button></div>
      <p class="small muted">Letzter Kurs ${px(q)}. Geprüft wird bei jedem Lauf; die Meldung kommt einmalig.</p>
      <form class="form" id="pf"><div class="row2"><label class="f">Richtung<select name="dir"><option value="above">Kurs ≥ Marke</option><option value="below">Kurs ≤ Marke</option></select></label><label class="f">Marke<input name="lvl" inputmode="decimal" required></label></div>
      <label class="f">Notiz<input name="note" placeholder="z. B. Ausbruch prüfen"></label><button class="btn primary">Anlegen</button></form>`);
    $("#pf").onsubmit = (e) => { e.preventDefault(); const f = e.target; sendCommand({ type: "price_alert_add", symbol: sym, direction: f.dir.value, level: String(f.lvl.value).replace(/\./g, "").replace(",", "."), note: f.note.value }, `Kursmarke ${sym}`); };
  }

  // --------------------------------------------------- Befehle an GitHub
  function conn(meta) {
    const c = LS.get("conn", {});
    return { repo: c.repo || (meta && meta.repo) || "", token: c.token || "", ref: c.ref || "main" };
  }
  async function sendCommand(cmd, label) {
    const meta = cache.meta || await load("meta").catch(() => ({}));
    const c = conn(meta);
    const json = JSON.stringify(cmd);
    if (!c.repo || !c.token) {
      openSheet(`<div class="card-head"><h2>Befehl senden</h2><button class="icon-btn" data-close>✕</button></div>
        <p class="small">Für den Versand direkt aus der Website hinterlegst du einmalig einen GitHub-Token unter <a href="#/einstellungen">Einstellungen</a>. Alternativ ohne Token:</p>
        <ol class="small"><li>In der GitHub-App bzw. im Browser <b>Actions → Trading Center → Run workflow</b> öffnen${c.repo ? ` (<a target="_blank" rel="noopener" href="https://github.com/${esc(c.repo)}/actions/workflows/trading-center.yml">direkt öffnen</a>)` : ""}.</li><li>Folgenden Text ins Feld <b>command</b> einfügen und starten:</li></ol>
        <textarea rows="4" readonly id="cmdtxt" class="mono small">${esc(json)}</textarea><button class="btn" id="cpy" style="margin-top:8px">Kopieren</button>`);
      $("#cpy").onclick = () => { $("#cmdtxt").select(); try { navigator.clipboard.writeText(json); toast("Kopiert"); } catch (e) { document.execCommand("copy"); } };
      return;
    }
    try {
      const r = await fetch(`https://api.github.com/repos/${c.repo}/actions/workflows/trading-center.yml/dispatches`, {
        method: "POST", headers: { Authorization: `Bearer ${c.token}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
        body: JSON.stringify({ ref: c.ref, inputs: { command: json } }),
      });
      if (r.status === 204) {
        const p = LS.get("pending", []); p.push({ t: Date.now(), label: label || cmd.type }); LS.set("pending", p.slice(-20));
        closeSheet(); toast("Gesendet. Verarbeitung im nächsten Lauf (meist 2–5 Minuten), danach Seite neu laden.");
      } else {
        const t = await r.text(); toast(`GitHub hat abgelehnt (HTTP ${r.status}). Token-Rechte prüfen. ${t.slice(0, 120)}`, 8000);
      }
    } catch (e) { toast("Senden fehlgeschlagen: " + e.message, 8000); }
  }

  // ------------------------------------------------------------- Screener
  async function screenerPage() {
    const [sc, sg] = await Promise.all([load("screener"), load("signals")]);
    const st = LS.get("scr", { q: "", sector: "", kind: "", sort: "short_score", dir: -1, mcap: "", pe: "", div: "", rsiMin: "", rsiMax: "", rg: "", eg: "", trend: "", vol: "", rvol: "", perf: "" });
    const sectors = Array.from(new Set(sc.rows.map((r) => r.sector).filter(Boolean))).sort();
    const cols = [["name", "Name"], ["price", "Kurs"], ["day_pct", "Tag"], ["perf_1m", "1 M"], ["perf_6m", "6 M"], ["market_cap_eur", "Mkap €"], ["pe", "KGV"], ["revenue_growth", "Umsatz +"], ["earnings_growth", "Gewinn +"], ["dividend_yield", "Div."], ["rsi", "RSI"], ["rvol", "Vol rel."], ["volatility", "Vola"], ["adx", "ADX"], ["short_score", "Trading"], ["long_score", "Invest"]];
    app.innerHTML = `<div class="page-head"><div><h1>Aktien-Screener</h1><p>${sc.rows.length} Werte aus dem Beobachtungsuniversum · Stand ${esc(when(sc.time))}. Werte erweitern: config/universe.yaml.</p></div></div>
      <div class="card"><div class="card-head"><h3>KI-Tagesauswahl: interessanteste Werte je Branche</h3>${tag("EIGENE MODELLINTERPRETATION")}</div>${picksBlock(sg.picks)}<p class="tiny muted">Je Branche der Wert mit dem höchsten bestätigten Kauf-Score (kurz- oder langfristig). Begründung und Gegenargument stehen dabei; Details per Klick.</p></div>
      <div class="card section"><form class="form" id="sf" onsubmit="return false">
        <div class="toolbar" style="margin:0"><input name="q" placeholder="Suche" value="${esc(st.q)}"><select name="sector"><option value="">Alle Branchen</option>${sectors.map((s) => `<option ${st.sector === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <select name="kind"><option value="">Aktien & ETFs</option><option value="stock" ${st.kind === "stock" ? "selected" : ""}>Nur Aktien</option><option value="etf" ${st.kind === "etf" ? "selected" : ""}>Nur ETFs</option></select>
        <select name="trend"><option value="">Jeder Trend</option>${["aufwärts", "seitwärts", "abwärts"].map((t) => `<option ${st.trend === t ? "selected" : ""}>${t}</option>`).join("")}</select></div>
        <details ${Object.entries(st).some(([k, v]) => v && !["q", "sector", "kind", "sort", "dir", "trend"].includes(k)) ? "open" : ""}><summary>Weitere Filter</summary><div class="grid g4" style="margin-top:8px">
          ${fil("mcap", "Mkap min. (Mrd. €)", st)}${fil("pe", "KGV max.", st)}${fil("div", "Dividende min. (%)", st)}${fil("rg", "Umsatzwachstum min. (%)", st)}${fil("eg", "Gewinnwachstum min. (%)", st)}
          ${fil("rsiMin", "RSI min.", st)}${fil("rsiMax", "RSI max.", st)}${fil("rvol", "Volumen rel. min.", st)}${fil("vol", "Volatilität max. (%)", st)}${fil("perf", "Perf. 1 M min. (%)", st)}${fil("adx", "Trendstärke ADX min.", st)}</div></details></form>
        <p class="tiny muted" id="cnt"></p><div class="table-wrap"><table id="st"></table></div></div>`;
    const P = (x) => { const v = parseFloat(String(x).replace(",", ".")); return isFinite(v) ? v : null; };
    const draw = () => {
      LS.set("scr", st);
      let rows = sc.rows.filter((r) => {
        if (st.q && !(r.name + r.symbol).toLowerCase().includes(st.q.toLowerCase())) return false;
        if (st.sector && r.sector !== st.sector) return false; if (st.kind && r.kind !== st.kind) return false; if (st.trend && r.trend !== st.trend) return false;
        const t = (val, lim, f) => lim === null || (val != null && f(val, lim));
        return t(r.market_cap_eur, P(st.mcap) != null ? P(st.mcap) * 1e9 : null, (a, b) => a >= b) && t(r.pe, P(st.pe), (a, b) => a > 0 && a <= b) && t(r.dividend_yield, P(st.div) != null ? P(st.div) / 100 : null, (a, b) => a >= b)
          && t(r.revenue_growth, P(st.rg) != null ? P(st.rg) / 100 : null, (a, b) => a >= b) && t(r.earnings_growth, P(st.eg) != null ? P(st.eg) / 100 : null, (a, b) => a >= b)
          && t(r.rsi, P(st.rsiMin), (a, b) => a >= b) && t(r.rsi, P(st.rsiMax), (a, b) => a <= b) && t(r.rvol, P(st.rvol), (a, b) => a >= b)
          && t(r.volatility, P(st.vol) != null ? P(st.vol) / 100 : null, (a, b) => a <= b) && t(r.perf_1m, P(st.perf) != null ? P(st.perf) / 100 : null, (a, b) => a >= b) && t(r.adx, P(st.adx), (a, b) => a >= b);
      });
      rows.sort((a, b) => { const x = a[st.sort], y = b[st.sort]; if (x == null) return 1; if (y == null) return -1; return (typeof x === "string" ? x.localeCompare(y) : x - y) * st.dir; });
      $("#cnt").textContent = `${rows.length} Treffer · Spaltenkopf antippen zum Sortieren · fehlende Werte (–) liefert die Quelle nicht`;
      $("#st").innerHTML = `<tr>${cols.map(([k, l]) => `<th class="sortable ${k === "name" ? "" : "r"}" data-k="${k}">${l}${st.sort === k ? (st.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr>` + rows.map((r) => `<tr class="click" data-s="${esc(r.symbol)}">
        <td class="wrap" style="min-width:150px"><b>${esc(r.name)}</b><div class="tiny muted mono">${esc(r.symbol)} · ${esc(r.sector || "–")}</div></td><td class="r num">${num(r.price, dec(r.price))}<div class="tiny dim">${esc(ccy(r.currency))}</div></td>
        <td class="r num ${cls(r.day_pct)}">${pct(r.day_pct)}</td><td class="r num ${cls(r.perf_1m)}">${pct(r.perf_1m)}</td><td class="r num ${cls(r.perf_6m)}">${pct(r.perf_6m)}</td><td class="r num">${big(r.market_cap_eur)}</td>
        <td class="r num">${num(r.pe, 1)}</td><td class="r num ${cls(r.revenue_growth)}">${pct(r.revenue_growth)}</td><td class="r num ${cls(r.earnings_growth)}">${pct(r.earnings_growth)}</td><td class="r num">${pct(r.dividend_yield, 1, false)}</td>
        <td class="r num">${num(r.rsi, 0)}</td><td class="r num">${num(r.rvol, 1)}</td><td class="r num">${pct(r.volatility, 0, false)}</td><td class="r num">${num(r.adx, 0)}</td>
        <td class="r">${rating(r.short_rating)}<div class="tiny dim num">${r.short_score}</div></td><td class="r">${rating(r.long_rating)}<div class="tiny dim num">${r.long_score}</div></td></tr>`).join("");
      app.querySelectorAll("th[data-k]").forEach((th) => th.onclick = () => { if (st.sort === th.dataset.k) st.dir *= -1; else { st.sort = th.dataset.k; st.dir = th.dataset.k === "name" ? 1 : -1; } draw(); });
      app.querySelectorAll("tr[data-s]").forEach((tr) => tr.onclick = () => location.hash = "#/aktie/" + encodeURIComponent(tr.dataset.s));
    };
    $("#sf").oninput = (e) => { st[e.target.name] = e.target.value; draw(); };
    draw();
  }
  const fil = (k, l, st) => `<label class="f">${l}<input name="${k}" inputmode="decimal" value="${esc(st[k] || "")}"></label>`;

  // ------------------------------------------------------------- Berichte
  async function reportsPage([file]) {
    const idx = await load("reports_index");
    if (!idx.reports.length) { app.innerHTML = `<div class="page-head"><h1>Börsenberichte</h1></div><div class="empty">Noch kein Bericht. Morgens (ca. 7–8 Uhr), stündlich untertags und abends (ca. 22–23 Uhr) entsteht je ein Bericht.</div>`; return; }
    const cur = file ? idx.reports.find((r) => r.file === decodeURIComponent(file)) || idx.reports[0] : idx.reports[0];
    const rep = await load(cur.file.replace(/\.json$/, ""));
    const K = { morning: "Morgen", intraday: "Zwischenstand", evening: "Abend" };
    app.innerHTML = `<div class="page-head"><div><h1>${esc(rep.title)} – ${esc(when(rep.date))}</h1><p>Erstellt ${esc(when(rep.time))} · Umfeld: <b>${esc(rep.environment.verdict)}</b>${rep.demo ? " · DEMO-Daten" : ""}</p></div>
      <select id="rsel" style="width:auto">${idx.reports.map((r) => `<option value="${esc(r.file)}" ${r.file === cur.file ? "selected" : ""}>${esc(when(r.date))} · ${K[r.kind] || r.kind}</option>`).join("")}</select></div>
      ${rep.commentary ? `<div class="card"><div class="card-head"><h3>Kommentar</h3>${tag(rep.commentary.tag)}</div><p style="white-space:pre-wrap;margin:0">${esc(rep.commentary.text)}</p></div>` : ""}
      <div class="grid g2 section">${rep.sections.map((s) => `<div class="card"><div class="card-head"><h3>${esc(s.title)}</h3>${tag(s.tag)}</div><ul class="points">${s.items.map((it) => typeof it === "string" ? `<li>${esc(it)}</li>` : `<li>${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.text)}</a>` : esc(it.text)}${it.source ? ` <span class="tiny dim">(${esc(it.source)})</span>` : ""}</li>`).join("")}</ul></div>`).join("")}</div>
      <p class="tiny dim">Berichte werden regelbasiert aus den abgerufenen Daten erzeugt${rep.commentary ? "; der Kommentar stammt von einem KI-Modell, das nur diese Daten erhalten hat" : ""}. Keine Anlageberatung.</p>`;
    $("#rsel").onchange = (e) => location.hash = "#/berichte/" + encodeURIComponent(e.target.value);
  }

  // ------------------------------------------------------------- Kalender
  async function calendarPage() {
    const cal = await load("calendar");
    let f = LS.get("calf", "all");
    const draw = () => {
      LS.set("calf", f);
      const ev = cal.events.filter((e) => f === "all" || (f === "macro" ? ["fed", "ecb", "inflation", "labor", "gdp"].includes(e.category) : f === "mine" ? e.in_depot || e.on_watchlist : e.category === f));
      const by = {}; ev.forEach((e) => (by[e.date] = by[e.date] || []).push(e));
      $("#cal").innerHTML = Object.keys(by).sort().map((d) => `<div class="card" style="margin-bottom:10px"><div class="card-head"><h3>${new Date(d + "T12:00:00Z").toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</h3></div>
        <div class="list">${by[d].map((e) => `<div class="li"><span class="pill ${["fed", "ecb"].includes(e.category) ? "warn" : e.category === "earnings" ? "info" : ""}">${esc(e.category_de)}</span><div class="grow"><div class="t">${e.symbol ? `<a href="#/aktie/${encodeURIComponent(e.symbol)}">${esc(e.title)}</a>` : esc(e.title)}${e.in_depot ? ' <span class="pill ok">im Depot</span>' : ""}${e.on_watchlist ? ' <span class="pill">Watchlist</span>' : ""}</div>
        <div class="d">${esc(e.why)}</div><div class="tiny dim">Quelle: ${/^https?:/.test(e.source) ? `<a href="${esc(e.source)}" target="_blank" rel="noopener">${esc(e.source.replace(/^https?:\/\//, "").split("/")[0])}</a>` : esc(e.source)}${e.confirmed === false ? " · Termin vorläufig" : ""}</div></div></div>`).join("")}</div></div>`).join("") || `<div class="empty">Keine Termine für diesen Filter.</div>`;
      app.querySelectorAll("[data-c]").forEach((b) => b.classList.toggle("on", b.dataset.c === f));
    };
    app.innerHTML = `<div class="page-head"><div><h1>Wirtschaftskalender</h1><p>${esc(when(cal.from))} bis ${esc(when(cal.to))} · Jeder Termin mit Quelle und Einordnung.</p></div></div>
      <div class="toolbar"><div class="seg">${[["all", "Alle"], ["macro", "Notenbanken & Konjunktur"], ["earnings", "Quartalszahlen"], ["dividend", "Dividenden"], ["mine", "Depot & Watchlist"]].map(([k, l]) => `<button data-c="${k}">${l}</button>`).join("")}</div></div>
      ${cal.gaps.map((g) => `<div class="note">${esc(g)}</div>`).join("")}<div id="cal"></div>`;
    app.querySelectorAll("[data-c]").forEach((b) => b.onclick = () => { f = b.dataset.c; draw(); });
    draw();
  }

  // --------------------------------------------------------------- Risiko
  async function riskPage() {
    const [rk, dp, sc] = await Promise.all([load("risk"), load("depot"), load("screener")]);
    const d = rk.diversification, rs = rk.risk_score, v = dp.valuation;
    const don = TC_CHART.donut(d.sectors.map((s) => ({ v: s.weight })).concat(d.cash_weight > 0 ? [{ v: d.cash_weight }] : []));
    const labels = d.sectors.map((s) => s.name).concat(d.cash_weight > 0 ? ["Cash"] : []), weights = d.sectors.map((s) => s.weight).concat(d.cash_weight > 0 ? [d.cash_weight] : []);
    app.innerHTML = `<div class="page-head"><div><h1>Risikomanagement</h1><p>Nicht nur der Gewinn zählt, sondern das Risiko, das dafür eingegangen wurde.</p></div></div>
      <div class="kpis"><div class="kpi"><div class="l">Eingegangenes Risiko</div><div class="v">${rs.score}/100</div><div class="s">${esc(rs.level)}</div></div>
        <div class="kpi"><div class="l">Gewichtete Volatilität</div><div class="v">${pct(rs.weighted_volatility, 1, false)}</div><div class="s muted">p. a.</div></div>
        <div class="kpi"><div class="l">Rendite je Risiko</div><div class="v">${num(rs.return_per_risk, 2)}</div><div class="s muted">Gesamtrendite / Volatilität</div></div>
        <div class="kpi"><div class="l">Max. Drawdown</div><div class="v down">${pct(rk.metrics.max_drawdown)}</div><div class="s muted">aktuell ${pct(rk.metrics.current_drawdown)}</div></div></div>
      <div class="card section"><div class="card-head"><h3>Warnungen</h3>${tag("EIGENE MODELLINTERPRETATION")}</div>
        <div class="list">${rk.warnings.map((w) => `<div class="li"><span class="pill ${w.level === "HIGH" ? "bad" : w.level === "MEDIUM" ? "warn" : "info"}">${w.level}</span><div class="grow">${esc(w.text)}</div></div>`).join("") || `<div class="empty">Keine Risikowarnungen.</div>`}</div></div>
      <div class="grid g2 section">
        <div class="card"><div class="card-head"><h3>Positionsgrößen-Rechner</h3></div>
          <form class="form" id="pc" onsubmit="return false">
            <label class="f">Wert (optional, für ATR-Stop)<input name="sym" list="psyms" placeholder="z. B. SAP.DE"><datalist id="psyms">${sc.rows.map((r) => `<option value="${esc(r.symbol)}">${esc(r.name)}</option>`).join("")}</datalist></label>
            <div class="row2"><label class="f">Depotwert €<input name="cap" inputmode="decimal" value="${num(v.total_eur, 2)}"></label><label class="f">Risiko je Trade %<input name="risk" inputmode="decimal" value="1"></label></div>
            <div class="row2"><label class="f">Einstieg<input name="entry" inputmode="decimal"></label><label class="f">Stop-Loss<input name="stop" inputmode="decimal"></label></div>
            <div class="row2"><label class="f">Kursziel (Take-Profit)<input name="tp" inputmode="decimal"></label><label class="f">Gebühren je Order €<input name="fee" inputmode="decimal" value="${num(dp.assumptions ? dp.assumptions.fee_fixed : 1, 2)}"></label></div>
          </form><div id="pcout" class="note"></div></div>
        <div class="card"><div class="card-head"><h3>Diversifikation</h3><span class="meta">effektiv ${num(d.effective_positions, 1)} Positionen</span></div>
          ${weights.length ? `<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">${don.svg}<div style="flex:1;min-width:160px">${labels.map((l, i) => `<div class="hbar" style="grid-template-columns:14px 1fr 52px"><i style="width:10px;height:10px;border-radius:2px;background:${don.colors[i % don.colors.length]}"></i><span class="small">${esc(l)}</span><span class="num small r">${pct(weights[i], 0, false)}</span></div>`).join("")}</div></div>` : `<div class="empty">Depot ist komplett in Cash.</div>`}
          <h3 style="margin-top:12px">Länder</h3>${d.countries.map((c) => `<div class="hbar"><span class="small">${esc(c.name)}</span><span class="b"><i style="width:${c.weight * 100}%"></i></span><span class="num small r">${pct(c.weight, 0, false)}</span></div>`).join("") || '<div class="small muted">–</div>'}
          <p class="tiny muted">Konzentrationsmaß (HHI) ${num(d.hhi, 3)} · Grenzen: Position ${pct(cache.meta && cache.meta.settings ? cache.meta.settings.risk.max_position_weight : 0.2, 0, false)}, Sektor ${pct(cache.meta && cache.meta.settings ? cache.meta.settings.risk.max_sector_weight : 0.4, 0, false)}</p></div>
      </div>
      <div class="grid g2 section">
        <div class="card"><div class="card-head"><h3>Drawdown-Analyse</h3></div><div id="dd"></div><p class="tiny muted">Abstand des Depotwerts zum bisherigen Höchststand. Längste Verlustphase: ${rk.metrics.longest_underwater_days != null ? rk.metrics.longest_underwater_days + " Tage" : "–"}.</p></div>
        <div class="card"><div class="card-head"><h3>Korrelationen im Depot</h3><span class="meta">${esc(rk.correlations.window || "")}</span></div>
          ${rk.correlations.pairs.length ? `<div class="table-wrap"><table><tr><th>Paar</th><th class="r">Korrelation</th></tr>${rk.correlations.pairs.map((p) => `<tr><td class="mono small">${esc(p.a)} / ${esc(p.b)}</td><td class="r num ${p.corr > 0.8 ? "down" : ""}">${num(p.corr, 2)}</td></tr>`).join("")}</table></div><p class="tiny muted">Über 0,8: Positionen bewegen sich fast gleich – kaum Streuungseffekt.</p>` : `<div class="empty">Ab zwei Positionen verfügbar.</div>`}</div>
      </div>`;
    const ddv = (rk.metrics.drawdown_series || []).map((p) => ({ t: p.date, v: p.dd * 100 }));
    TC_CHART.line($("#dd"), [{ name: "Drawdown", values: ddv, color: "#ef4444" }], { height: 180, fmt: (x) => num(x, 1) + " %", zeroLine: true, fill: true, empty: "Drawdown-Verlauf entsteht mit der Depothistorie." });
    const f = $("#pc"), P = (x) => { const s = String(x || "").trim(); const v = parseFloat(s.includes(",") ? s.replace(/\./g, "").replace(",", ".") : s); return isFinite(v) ? v : null; };
    const calc = () => {
      const row = sc.rows.find((r) => r.symbol === f.sym.value.trim().toUpperCase());
      let h = "";
      if (row && !f.entry.value) { f.entry.value = num(row.price, 2); }
      const cap = P(f.cap.value), risk = P(f.risk.value) / 100, entry = P(f.entry.value), stop = P(f.stop.value), tp = P(f.tp.value), fee = P(f.fee.value) || 0;
      if (row) h += `Letzter Kurs ${num(row.price, dec(row.price))} ${esc(ccy(row.currency))}, Volatilität ${pct(row.volatility, 0, false)} p. a. `;
      if (cap && risk && entry && stop && stop < entry) {
        const perShare = entry - stop, maxLoss = cap * risk, shares = Math.floor((maxLoss - 2 * fee) / perShare), val = shares * entry;
        h += `<br><b>${shares > 0 ? shares : 0} Stück</b> ≈ ${eur(val)} (${pct(val / cap, 1, false)} des Depots). Max. Verlust bis Stop inkl. Gebühren ≈ ${eur(shares * perShare + 2 * fee)} = ${pct(risk, 1, false)}.`;
        if (val > cap) h += ` <span class="down">Position größer als das Depot – Stop zu eng oder Risiko zu hoch.</span>`;
        else if (val / cap > 0.2) h += ` <span class="down">Über 20 % Gewicht – Klumpenrisiko.</span>`;
        if (tp && tp > entry) { const crv = (tp - entry) / perShare; h += `<br>Chance-Risiko-Verhältnis <b>${num(crv, 2)}</b> · möglicher Gewinn ${eur(shares * (tp - entry) - 2 * fee)}. ${crv < 1.5 ? '<span class="down">CRV unter 1,5 – Trefferquote muss hoch sein.</span>' : '<span class="up">CRV ausreichend.</span>'} Benötigte Trefferquote für Break-even ≈ ${pct(1 / (1 + crv), 0, false)}.`; }
        h += `<br><span class="tiny dim">Stop-Loss-Simulation: Bei Kurslücken wird schlechter als der Stop ausgeführt – das Risiko ist dann größer.</span>`;
      } else h += `<br>Einstieg und Stop (unter dem Einstieg) eingeben.`;
      $("#pcout").innerHTML = h;
    };
    f.oninput = calc; calc();
  }

  // --------------------------------------------------------------- Alerts
  async function alertsPage() {
    const al = await load("alerts");
    const st = LS.get("alf", "MEDIUM");
    const seenBefore = LS.get("alertsSeen", null);
    LS.set("alertsSeen", al.alerts.length ? al.alerts[0].created : new Date().toISOString());
    const draw = (f) => {
      LS.set("alf", f);
      const list = al.alerts.filter((a) => f === "ALL" || (f === "MEDIUM" ? a.priority !== "LOW" : a.priority === f) || (f === "SIG" && a.is_signal));
      $("#al").innerHTML = list.map((a) => `<div class="card alert-card ${a.priority}" style="margin-bottom:10px">
        <div class="card-head"><div><span class="pill ${a.priority === "HIGH" ? "bad" : a.priority === "MEDIUM" ? "warn" : "info"}">${a.priority}</span> <b>${esc(a.title)}</b>${!seenBefore || a.created > seenBefore ? ' <span class="pill ok">neu</span>' : ""}</div><span class="meta">${esc(when(a.created))}</span></div>
        <div class="tiny ${a.is_signal ? "" : "muted"}" style="margin-bottom:6px">${esc(a.type_label)}</div>
        ${a.signal_label ? `<div><b>Signal:</b> ${esc(a.signal_label)}</div>` : ""}
        <div><b>Ereignis:</b> ${esc(a.headline)}</div>
        <div><b>Aktueller Kurs:</b> ${a.quote ? `${px(a.quote)} ${qual(a.quote)} <span class="tiny dim">${esc(when(a.quote.time))}</span>` : "–"}</div>
        <div style="margin-top:6px"><b>Grund:</b> ${esc(a.reason)}</div><div><b>Risiko:</b> ${esc(a.risk)}</div><div><b>Was ist zu tun?</b> ${esc(a.todo)}</div>
        <div class="tiny dim" style="margin-top:6px">Quelle: ${esc(a.source)} · Stand der Information ${esc(when(a.info_time))} · ${tag(a.tag)} · zugestellt: ${esc((a.delivered || []).join(", "))}
        ${a.link ? ` · <a href="${esc(a.link)}" target="_blank" rel="noopener">Originalquelle</a>` : ""}${a.symbol && !/^(MARKT|DEPOT)$/.test(a.symbol) ? ` · <a href="#/aktie/${encodeURIComponent(a.symbol)}">Analyse</a>` : ""}</div></div>`).join("") || `<div class="empty">Keine Meldungen für diesen Filter.</div>`;
      app.querySelectorAll("[data-f]").forEach((b) => b.classList.toggle("on", b.dataset.f === f));
    };
    app.innerHTML = `<div class="page-head"><div><h1>Benachrichtigungen</h1><p>Letzte Prüfung ${esc(when(al.time))}. Push/Telegram/E-Mail erhalten Meldungen ab Priorität MEDIUM. Benachrichtigungen sind keine Kaufempfehlungen.</p></div></div>
      <div class="toolbar"><div class="seg">${[["MEDIUM", "Wichtig"], ["HIGH", "HIGH"], ["SIG", "Signale"], ["ALL", "Alle"]].map(([k, l]) => `<button data-f="${k}">${l}</button>`).join("")}</div></div><div id="al"></div>`;
    app.querySelectorAll("[data-f]").forEach((b) => b.onclick = () => draw(b.dataset.f));
    draw(st);
  }

  // ------------------------------------------------------- Trefferquote
  async function trackPage() {
    const tr = await load("track");
    const s = tr.stats;
    const R = { "STRONG BUY": 0, BUY: 1, SELL: 2, "STRONG SELL": 3, ALLE: 4 };
    const rows = s.rows.slice().sort((a, b) => a.horizon.localeCompare(b.horizon) || R[a.rating] - R[b.rating] || a.days - b.days);
    app.innerHTML = `<div class="page-head"><div><h1>Trefferquote der Signale</h1><p>Jede Änderung einer Einstufung wird gespeichert und nach festen Fristen ausgewertet – auch Fehlschläge.</p></div></div>
      <div class="kpis"><div class="kpi"><div class="l">Gespeicherte Signale</div><div class="v">${s.total}</div></div><div class="kpi"><div class="l">Noch offen</div><div class="v">${s.open}</div></div>
        <div class="kpi"><div class="l">Verlustbereich erreicht</div><div class="v down">${s.stop_hits}</div></div><div class="kpi"><div class="l">Basisziel erreicht</div><div class="v up">${s.target_hits}</div></div></div>
      <div class="card section"><div class="card-head"><h3>Statistik</h3></div>
        ${rows.length ? `<div class="table-wrap"><table><tr><th>Horizont</th><th>Einstufung</th><th class="r">nach Tagen</th><th class="r">Anzahl</th><th class="r">Trefferquote</th><th class="r">Ø netto</th><th class="r">Median</th><th class="r">bestes / schlechtestes</th><th class="r">Ø vs. Index</th></tr>
        ${rows.map((r) => `<tr><td>${H[r.horizon]}</td><td>${r.rating === "ALLE" ? "<b>alle</b>" : rating(r.rating)}</td><td class="r num">${r.days}</td><td class="r num">${r.n}</td><td class="r num ${r.hit_rate >= 0.5 ? "up" : "down"}">${pct(r.hit_rate, 0, false)}</td><td class="r num ${cls(r.avg_net)}">${pct(r.avg_net, 2)}</td><td class="r num">${pct(r.median_net, 2)}</td><td class="r num">${pct(r.best, 1)} / ${pct(r.worst, 1)}</td><td class="r num ${cls(r.avg_excess)}">${pct(r.avg_excess, 2)}</td></tr>`).join("")}</table></div>` : `<div class="empty">Noch keine ausgewerteten Signale. Die erste Auswertung erfolgt 5 Handelstage nach dem ersten Kauf- oder Verkaufssignal.</div>`}
        <p class="tiny muted">${esc(s.method)}</p><p class="note warn">${esc(s.note)}</p></div>
      <div class="card section"><div class="card-head"><h3>Fehlgeschlagene Signale – zum Lernen</h3></div>
        ${s.failures.length ? `<div class="table-wrap"><table><tr><th>Wert</th><th>Signal</th><th>Datum</th><th class="r">Tage</th><th class="r">Ergebnis netto</th><th>Verlustbereich</th></tr>${s.failures.map((f) => `<tr class="click" onclick="location.hash='#/aktie/${encodeURIComponent(f.symbol)}'"><td class="mono">${esc(f.symbol)}</td><td>${rating(f.rating)} ${H[f.horizon]}</td><td>${esc(when(f.time))}</td><td class="r num">${f.days}</td><td class="r num down">${pct(f.return_net_directional, 2)}</td><td>${f.stop_hit ? "erreicht " + esc(when(f.stop_hit)) : "–"}</td></tr>`).join("")}</table></div>` : `<div class="empty">Bisher keine Fehlschläge ausgewertet.</div>`}</div>
      <div class="card section"><div class="card-head"><h3>Signal-Historie</h3></div><div class="table-wrap"><table><tr><th>Zeit</th><th>Wert</th><th>Horizont</th><th>Wechsel</th><th class="r">Kurs</th><th>Status</th></tr>
        ${tr.history.slice(0, 150).map((h) => `<tr><td>${esc(when(h.time))}</td><td class="mono">${esc(h.symbol)}</td><td>${H[h.horizon]}</td><td>${h.prev_rating ? esc(h.prev_rating) + " → " : ""}${rating(h.rating)}</td><td class="r num">${num(h.price, dec(h.price))}</td><td class="small">${esc(h.status)}${Object.entries(h.evaluations).map(([d, e]) => ` · ${d} T: <span class="${e.hit ? "up" : "down"}">${pct(e.return_net_directional, 1)}</span>`).join("")}</td></tr>`).join("")}</table></div></div>`;
  }

  // -------------------------------------------------------- Einstellungen
  async function settingsPage() {
    const meta = await load("meta");
    const c = conn(meta);
    const ch = meta.channels || {};
    app.innerHTML = `<div class="page-head"><div><h1>Einstellungen & Status</h1><p>Letzter Lauf ${esc(when(meta.time))} (${esc(ago(meta.time))}) · Bericht: ${esc(meta.report_kind)}</p></div></div>
      <div class="grid g2">
        <div class="card"><div class="card-head"><h3>Verbindung zu GitHub (für Orders aus der Website)</h3></div>
          <form class="form" id="cf"><label class="f">Repository (besitzer/name)<input name="repo" value="${esc(c.repo)}" placeholder="deinname/trading-center"></label>
          <label class="f">Fine-grained Personal Access Token<input name="token" type="password" value="${esc(c.token)}" placeholder="github_pat_…" autocomplete="off"></label>
          <label class="f">Branch<input name="ref" value="${esc(c.ref)}"></label><button class="btn primary">Speichern</button></form>
          <p class="tiny muted">Der Token wird nur in diesem Browser gespeichert (localStorage), nie auf der Website veröffentlicht. Rechte: nur dieses Repository, <b>Actions: Read and write</b>. Ohne Token kannst du Befehle in der GitHub-App per „Run workflow“ starten.</p></div>
        <div class="card"><div class="card-head"><h3>Status der Datenquellen</h3></div>
          <dl class="kv"><dt>Quellen</dt><dd style="white-space:normal">${esc(meta.sources.join(", "))}</dd><dt>KI-Kommentar</dt><dd>${meta.llm ? "aktiv" : "aus (kein ANTHROPIC_API_KEY)"}</dd>
          <dt>Telegram</dt><dd>${ch.telegram ? "eingerichtet" : "–"}</dd><dt>Push (ntfy)</dt><dd>${ch.push ? "eingerichtet" : "–"}</dd><dt>E-Mail</dt><dd>${ch.email ? "eingerichtet" : "–"}</dd>
          <dt>Versand zuletzt</dt><dd style="white-space:normal">${esc(Object.entries(meta.delivery || {}).map(([k, v]) => `${k}: ${v}`).join(" · ") || "–")}</dd></dl>
          <details ${meta.gaps.length ? "" : ""}><summary>Datenlücken im letzten Lauf (${meta.gaps.length})</summary><div class="table-wrap"><table>${meta.gaps.slice(0, 80).map((g) => `<tr><td class="mono small">${esc(g.symbol)}</td><td class="small">${esc(g.what)}</td><td class="small wrap muted">${esc(g.reason)}</td></tr>`).join("")}</table></div></details></div>
      </div>
      <div class="grid g2 section">
        <div class="card"><div class="card-head"><h3>Watchlist</h3></div><div class="list">${(meta.watchlist || []).map((w) => `<div class="li"><a class="grow mono" href="#/aktie/${encodeURIComponent(w)}">${esc(w)}</a><button class="btn small" data-unwatch="${esc(w)}">Entfernen</button></div>`).join("") || '<div class="empty">leer</div>'}</div>
          <form class="toolbar" id="wf" style="margin-top:10px"><input name="s" placeholder="Kürzel, z. B. AIR.DE" autocapitalize="characters"><button class="btn">Hinzufügen</button></form></div>
        <div class="card"><div class="card-head"><h3>Kursmarken</h3></div><div class="list">${(meta.price_alerts || []).map((a) => `<div class="li"><div class="grow"><span class="mono">${esc(a.ticker)}</span> ${a.direction === "above" ? "≥" : "≤"} <b class="num">${num(a.level, dec(a.level))}</b> <span class="small muted">${esc(a.note || "")}</span>${a.active ? "" : ` <span class="pill ok">ausgelöst ${esc(when(a.triggered))}</span>`}</div><button class="btn small" data-rmpa="${esc(a.id)}">Löschen</button></div>`).join("") || '<div class="empty">Keine Kursmarken. Anlegen in der Einzelanalyse.</div>'}</div></div>
      </div>
      <div class="card section"><div class="card-head"><h3>Letzte Befehle</h3></div><div class="list">${(meta.command_log || []).slice().reverse().map((r) => `<div class="li"><span class="pill ${r.ok ? "ok" : "bad"}">${r.ok ? "ok" : "Fehler"}</span><div class="grow"><div class="small">${esc(r.message || "")}</div><div class="tiny dim mono">${esc(when(r.time))} · ${esc(JSON.stringify(r.command).slice(0, 140))}</div></div></div>`).join("") || '<div class="empty">Noch keine Befehle.</div>'}</div></div>
      <div class="card section"><div class="card-head"><h3>Wichtige Hinweise</h3></div><ul class="points small">
        <li>Börsen-Planspiel mit virtuellem Kapital. Es werden keine echten Kauf- oder Verkaufsaufträge ausgeführt.</li>
        <li>Kurse von Yahoo Finance sind in der Regel 15–20 Minuten verzögert; jede Anzeige trägt Quelle und Zeitstempel. Echtzeit wird nie behauptet.</li>
        <li>Die Website zeigt nur, was das Backend tatsächlich berechnet hat. Läuft es nicht, siehst du den letzten Stand und einen Hinweis oben.</li>
        <li>Signale und Berichte sind analytische Orientierung, keine Anlageberatung.</li></ul></div>`;
    $("#cf").onsubmit = (e) => { e.preventDefault(); const f = e.target; const saved = LS.set("conn", { repo: f.repo.value.trim(), token: f.token.value.trim(), ref: f.ref.value.trim() || "main" }); toast(saved ? "Gespeichert (nur in diesem Browser)." : "Speichern nicht möglich – der Browser blockiert lokalen Speicher."); };
    $("#wf").onsubmit = (e) => { e.preventDefault(); const s = e.target.s.value.trim().toUpperCase(); if (s) sendCommand({ type: "watch_add", symbol: s }, `Watchlist + ${s}`); };
    app.querySelectorAll("[data-unwatch]").forEach((b) => b.onclick = () => sendCommand({ type: "watch_remove", symbol: b.dataset.unwatch }, `Watchlist − ${b.dataset.unwatch}`));
    app.querySelectorAll("[data-rmpa]").forEach((b) => b.onclick = () => sendCommand({ type: "price_alert_remove", id: b.dataset.rmpa }, "Kursmarke löschen"));
  }

  function morePage() {
    app.innerHTML = `<div class="page-head"><h1>Mehr</h1></div><div class="more-grid">${NAV.filter(([r]) => !BOTTOM.includes(r)).map(([r, i, l]) => `<a href="#/${r}"><span class="ico">${i}</span>${l}</a>`).join("")}</div>`;
  }

  // ------------------------------------------------------- UI-Helfer
  function openSheet(html) {
    const sh = $("#sheet"); sh.innerHTML = html; sh.hidden = false; $("#sheet-backdrop").hidden = false;
    sh.querySelectorAll("[data-close]").forEach((b) => b.onclick = closeSheet);
  }
  function closeSheet() { $("#sheet").hidden = true; $("#sheet-backdrop").hidden = true; }
  $("#sheet-backdrop").onclick = closeSheet;
  let toastT;
  function toast(msg, ms = 4500) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), ms); }
  function debounce(fn, ms) { let t; return () => { clearTimeout(t); t = setTimeout(fn, ms); }; }

  async function refresh() { Object.keys(cache).forEach((k) => delete cache[k]); await header(); await load("alerts").catch(() => null); route(); }
  $("#refresh").onclick = refresh;
  window.addEventListener("hashchange", route);
  // Daten ändern sich nur mit jedem Backend-Lauf; alle 5 Minuten still prüfen
  setInterval(async () => {
    try { const r = await fetch(`data/meta.json?ts=${Date.now()}`, { cache: "no-store" }); const m = await r.json(); if (cache.meta && m.time !== cache.meta.time) { toast("Neue Daten verfügbar – wird aktualisiert."); refresh(); } } catch (e) { /* offline */ }
  }, 5 * 60000);
  (async () => { await header(); await load("alerts").catch(() => null); route(); })();
})();
