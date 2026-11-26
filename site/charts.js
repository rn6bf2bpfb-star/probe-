/* Trading Center – eigene, abhängigkeitsfreie Charts (Canvas/SVG). */
(function () {
  "use strict";
  const C = {
    up: "#22c55e", down: "#ef4444", grid: "#1b232d", axis: "#6b7684", text: "#9aa5b2",
    sma20: "#4c9aff", sma50: "#f5a623", sma200: "#a78bfa", line: "#f5a623", vol: "rgba(127,139,153,.35)",
  };
  const nf = (d) => new Intl.NumberFormat("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
  function fmtNum(v, d) { return v == null || !isFinite(v) ? "–" : nf(d).format(v); }
  function autoDec(v) { const a = Math.abs(v); return a >= 1000 ? 0 : a >= 10 ? 2 : a >= 1 ? 2 : 4; }

  function niceTicks(min, max, n) {
    if (!(max > min)) { max = min + 1; }
    const span = max - min, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const norm = step0 / mag, step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const out = []; for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(v);
    return out;
  }

  function setup(container, height) {
    container.innerHTML = "";
    container.classList.add("chart");
    const cv = document.createElement("canvas");
    const tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true;
    container.appendChild(cv); container.appendChild(tip);
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const w = container.clientWidth || 600, h = height;
    cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + "px";
    const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
    return { cv, ctx, tip, w, h };
  }

  function onHover(st, handler) {
    const move = (e) => {
      const r = st.cv.getBoundingClientRect();
      const p = e.touches ? e.touches[0] : e;
      handler(p.clientX - r.left, p.clientY - r.top);
    };
    st.cv.addEventListener("mousemove", move);
    st.cv.addEventListener("touchstart", move, { passive: true });
    st.cv.addEventListener("touchmove", move, { passive: true });
    st.cv.addEventListener("mouseleave", () => handler(null));
  }

  function placeTip(st, x, y, html) {
    st.tip.innerHTML = html; st.tip.hidden = false;
    const tw = st.tip.offsetWidth, th = st.tip.offsetHeight;
    let left = x + 12; if (left + tw > st.w) left = x - tw - 12; if (left < 0) left = 0;
    let top = y - th - 8; if (top < 0) top = y + 14;
    st.tip.style.left = left + "px"; st.tip.style.top = top + "px";
  }

  /* Kurschart mit Kerzen oder Linie, Gleitenden Durchschnitten, Volumen und Marken */
  function price(container, hist, opt) {
    opt = Object.assign({ bars: 250, mode: "candle", overlays: ["sma20", "sma50", "sma200"], levels: [], height: 330, currency: "" }, opt || {});
    const n = hist.t.length, start = Math.max(0, n - opt.bars);
    const idx = []; for (let i = start; i < n; i++) if (hist.c[i] != null) idx.push(i);
    const st = setup(container, opt.height);
    if (idx.length < 2) { st.ctx.fillStyle = C.text; st.ctx.fillText("Keine Kursdaten verfügbar", 10, 20); return; }
    const padL = 6, padR = 58, padT = 10, volH = Math.round(opt.height * 0.16), padB = 22;
    const plotH = opt.height - padT - padB - volH - 6;
    let lo = Infinity, hi = -Infinity, vmax = 0;
    idx.forEach((i) => {
      const l = opt.mode === "candle" ? hist.l[i] : hist.c[i], h = opt.mode === "candle" ? hist.h[i] : hist.c[i];
      if (l != null) lo = Math.min(lo, l); if (h != null) hi = Math.max(hi, h);
      opt.overlays.forEach((k) => { const v = hist[k] && hist[k][i]; if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
      if (hist.v[i]) vmax = Math.max(vmax, hist.v[i]);
    });
    opt.levels.forEach((L) => { if (L.y > lo * 0.85 && L.y < hi * 1.15) { lo = Math.min(lo, L.y); hi = Math.max(hi, L.y); } });
    const pad = (hi - lo) * 0.05 || 1; lo -= pad; hi += pad;
    const W = st.w - padL - padR, step = W / idx.length;
    const X = (k) => padL + step * (k + 0.5), Y = (v) => padT + (hi - v) / (hi - lo) * plotH;
    const ctx = st.ctx;
    const draw = (hover) => {
      ctx.clearRect(0, 0, st.w, st.h);
      ctx.font = "10.5px ui-monospace, Menlo, monospace"; ctx.textBaseline = "middle";
      niceTicks(lo, hi, 5).forEach((v) => {
        const y = Y(v); ctx.strokeStyle = C.grid; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(st.w - padR, y); ctx.stroke();
        ctx.fillStyle = C.axis; ctx.textAlign = "left"; ctx.fillText(fmtNum(v, autoDec(v)), st.w - padR + 6, y);
      });
      // Zeitachse: Monatsanfänge
      ctx.textAlign = "center"; ctx.fillStyle = C.axis; let lastM = "";
      idx.forEach((i, k) => { const m = hist.t[i].slice(0, 7); if (m !== lastM && k > 2) { const x = X(k); ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke(); if (k < idx.length - 3) ctx.fillText(monthName(m), x, opt.height - 8); } lastM = m; });
      // Volumen
      const vy0 = padT + plotH + 6 + volH;
      idx.forEach((i, k) => { const v = hist.v[i]; if (!v || !vmax) return; const hgt = v / vmax * volH; ctx.fillStyle = hist.c[i] >= hist.o[i] ? "rgba(34,197,94,.33)" : "rgba(239,68,68,.33)"; ctx.fillRect(X(k) - Math.max(1, step * 0.35), vy0 - hgt, Math.max(1, step * 0.7), hgt); });
      // Marken
      opt.levels.forEach((L) => { const y = Y(L.y); if (y < padT || y > padT + plotH) return; ctx.setLineDash([4, 4]); ctx.strokeStyle = L.color; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(st.w - padR, y); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = L.color; ctx.textAlign = "left"; ctx.fillText(L.label, padL + 4, y - 7); });
      // Kurs
      if (opt.mode === "candle") {
        idx.forEach((i, k) => {
          const o = hist.o[i], c = hist.c[i], h = hist.h[i], l = hist.l[i]; if ([o, c, h, l].some((v) => v == null)) return;
          const col = c >= o ? C.up : C.down, x = X(k); ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(x, Y(h)); ctx.lineTo(x, Y(l)); ctx.stroke();
          const bw = Math.max(1, step * 0.62), y1 = Y(Math.max(o, c)), y2 = Y(Math.min(o, c));
          ctx.fillRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
        });
      } else {
        ctx.strokeStyle = C.line; ctx.lineWidth = 1.6; ctx.beginPath();
        idx.forEach((i, k) => { const y = Y(hist.c[i]); k ? ctx.lineTo(X(k), y) : ctx.moveTo(X(k), y); }); ctx.stroke();
      }
      opt.overlays.forEach((key) => {
        const arr = hist[key]; if (!arr) return; ctx.strokeStyle = C[key] || "#888"; ctx.lineWidth = 1.2; ctx.beginPath(); let on = false;
        idx.forEach((i, k) => { const v = arr[i]; if (v == null) { on = false; return; } const y = Y(v); on ? ctx.lineTo(X(k), y) : ctx.moveTo(X(k), y); on = true; }); ctx.stroke();
      });
      // Letzter Kurs
      const li = idx[idx.length - 1], ly = Y(hist.c[li]);
      ctx.fillStyle = C.line; ctx.fillRect(st.w - padR + 1, ly - 8, padR - 2, 16); ctx.fillStyle = "#111"; ctx.textAlign = "left";
      ctx.fillText(fmtNum(hist.c[li], autoDec(hist.c[li])), st.w - padR + 5, ly);
      if (hover != null) {
        const k = Math.max(0, Math.min(idx.length - 1, Math.floor((hover - padL) / step))), i = idx[k], x = X(k);
        ctx.strokeStyle = "rgba(255,255,255,.25)"; ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH + volH + 6); ctx.stroke();
        const d = autoDec(hist.c[i]);
        let html = `<div>${hist.t[i].split("-").reverse().join(".")}</div>`;
        if (opt.mode === "candle") html += `<div>E ${fmtNum(hist.o[i], d)} H ${fmtNum(hist.h[i], d)}</div><div>T ${fmtNum(hist.l[i], d)} S <b>${fmtNum(hist.c[i], d)}</b></div>`;
        else html += `<div>Schluss <b>${fmtNum(hist.c[i], d)}</b></div>`;
        opt.overlays.forEach((key) => { if (hist[key] && hist[key][i] != null) html += `<div style="color:${C[key]}">${key.toUpperCase().replace("SMA", "SMA ")} ${fmtNum(hist[key][i], d)}</div>`; });
        if (hist.v[i]) html += `<div class="muted">Vol ${fmtNum(hist.v[i], 0)}</div>`;
        placeTip(st, x, Y(hist.c[i]), html);
      } else st.tip.hidden = true;
    };
    draw(null);
    onHover(st, (x) => draw(x));
  }

  /* Liniendiagramm mit mehreren Reihen */
  function line(container, series, opt) {
    opt = Object.assign({ height: 220, fmt: (v) => fmtNum(v, 2), pct: false, zeroLine: false, fill: false }, opt || {});
    const st = setup(container, opt.height), ctx = st.ctx;
    const all = series.flatMap((s) => s.values.map((p) => p.v)).filter((v) => v != null && isFinite(v));
    const times = Array.from(new Set(series.flatMap((s) => s.values.map((p) => p.t)))).sort();
    if (all.length < 2 || times.length < 2) { ctx.fillStyle = C.text; ctx.font = "12px sans-serif"; ctx.fillText(opt.empty || "Noch nicht genug Daten für ein Diagramm", 10, 24); return; }
    let lo = Math.min(...all), hi = Math.max(...all); if (opt.zeroLine) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1; lo -= pad; hi += pad;
    const padL = 6, padR = 62, padT = 8, padB = 20, W = st.w - padL - padR, H = opt.height - padT - padB;
    const tIndex = new Map(times.map((t, i) => [t, i]));
    const X = (t) => padL + tIndex.get(t) / (times.length - 1) * W, Y = (v) => padT + (hi - v) / (hi - lo) * H;
    const draw = (hover) => {
      ctx.clearRect(0, 0, st.w, st.h); ctx.font = "10.5px ui-monospace, Menlo, monospace"; ctx.textBaseline = "middle";
      niceTicks(lo, hi, 4).forEach((v) => { const y = Y(v); ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(st.w - padR, y); ctx.stroke(); ctx.fillStyle = C.axis; ctx.textAlign = "left"; ctx.fillText(opt.fmt(v), st.w - padR + 6, y); });
      if (opt.zeroLine) { ctx.strokeStyle = "#3a4654"; ctx.beginPath(); ctx.moveTo(padL, Y(0)); ctx.lineTo(st.w - padR, Y(0)); ctx.stroke(); }
      ctx.fillStyle = C.axis; ctx.textAlign = "left"; ctx.fillText(shortDate(times[0]), padL, opt.height - 7); ctx.textAlign = "right"; ctx.fillText(shortDate(times[times.length - 1]), st.w - padR, opt.height - 7);
      series.forEach((s) => {
        ctx.strokeStyle = s.color; ctx.lineWidth = s.width || 1.7; ctx.setLineDash(s.dash || []); ctx.beginPath(); let on = false;
        s.values.forEach((p) => { if (p.v == null) { on = false; return; } const x = X(p.t), y = Y(p.v); on ? ctx.lineTo(x, y) : ctx.moveTo(x, y); on = true; }); ctx.stroke(); ctx.setLineDash([]);
        if (opt.fill && s === series[0]) { ctx.lineTo(X(s.values[s.values.length - 1].t), Y(Math.max(lo, opt.zeroLine ? 0 : lo))); ctx.lineTo(X(s.values[0].t), Y(Math.max(lo, opt.zeroLine ? 0 : lo))); ctx.closePath(); ctx.fillStyle = s.fillColor || "rgba(245,166,35,.08)"; ctx.fill(); }
      });
      if (hover != null) {
        const k = Math.max(0, Math.min(times.length - 1, Math.round((hover - padL) / W * (times.length - 1)))), t = times[k], x = X(t);
        ctx.strokeStyle = "rgba(255,255,255,.25)"; ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + H); ctx.stroke();
        let html = `<div>${longDate(t)}</div>`;
        series.forEach((s) => { const p = s.values.find((q) => q.t === t); if (p && p.v != null) html += `<div style="color:${s.color}">${s.name}: <b>${opt.fmt(p.v)}</b></div>`; });
        placeTip(st, x, padT + 20, html);
      } else st.tip.hidden = true;
    };
    draw(null); onHover(st, (x) => draw(x));
  }

  function spark(values, up) {
    const v = (values || []).filter((x) => x != null);
    if (v.length < 2) return '<svg viewBox="0 0 100 30"></svg>';
    const lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
    const pts = v.map((x, i) => `${(i / (v.length - 1) * 100).toFixed(2)},${(28 - (x - lo) / r * 26).toFixed(2)}`).join(" ");
    const col = up == null ? (v[v.length - 1] >= v[0] ? C.up : C.down) : up ? C.up : C.down;
    return `<svg viewBox="0 0 100 30" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.4" vector-effect="non-scaling-stroke"/></svg>`;
  }

  function gauge(score, label) {
    const s = score == null ? null : Math.max(0, Math.min(100, score));
    const arc = (a0, a1, col) => { const p = (a) => [100 + 80 * Math.cos(Math.PI * (1 - a)), 100 - 80 * Math.sin(Math.PI * (1 - a))]; const [x0, y0] = p(a0), [x1, y1] = p(a1); return `<path d="M${x0},${y0} A80,80 0 0 1 ${x1},${y1}" stroke="${col}" stroke-width="14" fill="none"/>`; };
    let segs = arc(0, 0.25, "#b91c1c") + arc(0.25, 0.45, "#ef4444") + arc(0.45, 0.55, "#64748b") + arc(0.55, 0.75, "#22c55e") + arc(0.75, 1, "#15803d");
    let needle = "";
    if (s != null) { const a = Math.PI * (1 - s / 100), x = 100 + 66 * Math.cos(a), y = 100 - 66 * Math.sin(a); needle = `<line x1="100" y1="100" x2="${x}" y2="${y}" stroke="#d9dfe7" stroke-width="3" stroke-linecap="round"/><circle cx="100" cy="100" r="6" fill="#d9dfe7"/>`; }
    return `<svg viewBox="0 0 200 128">${segs}${needle}<text x="100" y="125" text-anchor="middle" fill="#d9dfe7" font-family="ui-monospace,monospace" font-size="22" font-weight="700">${s == null ? "–" : s}</text></svg><div class="small muted">${label || ""}</div>`;
  }

  function donut(parts) {
    const tot = parts.reduce((a, p) => a + p.v, 0) || 1; let a = 0; const cols = ["#f5a623", "#4c9aff", "#22c55e", "#a78bfa", "#22d3ee", "#ef4444", "#eab308", "#ec4899", "#14b8a6", "#64748b"];
    const segs = parts.map((p, i) => { const f = p.v / tot, a0 = a, a1 = a + f; a = a1; if (f >= 0.999) return `<circle cx="60" cy="60" r="44" stroke="${cols[i % cols.length]}" stroke-width="20" fill="none"/>`; const P = (t) => [60 + 44 * Math.sin(2 * Math.PI * t), 60 - 44 * Math.cos(2 * Math.PI * t)]; const [x0, y0] = P(a0), [x1, y1] = P(a1); return `<path d="M${x0},${y0} A44,44 0 ${f > 0.5 ? 1 : 0} 1 ${x1},${y1}" stroke="${cols[i % cols.length]}" stroke-width="20" fill="none"/>`; }).join("");
    return { svg: `<svg viewBox="0 0 120 120" style="width:120px;height:120px">${segs}</svg>`, colors: cols };
  }

  const MON = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
  function monthName(ym) { const [y, m] = ym.split("-"); return m === "01" ? y : MON[+m - 1]; }
  function shortDate(t) { const d = String(t).slice(0, 10).split("-"); return `${d[2]}.${d[1]}.${d[0].slice(2)}`; }
  function longDate(t) { const s = String(t); return s.length > 10 ? new Date(s).toLocaleString("de-DE", { timeZone: "Europe/Berlin", dateStyle: "short", timeStyle: "short" }) : shortDate(s); }

  window.TC_CHART = { price, line, spark, gauge, donut, colors: C };
})();
