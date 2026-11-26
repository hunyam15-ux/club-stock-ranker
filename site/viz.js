/* 시각화 도구 모음 (외부 라이브러리 없이 SVG/DOM) — window.Viz */
(() => {
  "use strict";
  const UP = "#f04452", DOWN = "#3182f6", FLAT = "#4e5968";
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const fmt = (v) => Math.round(v).toLocaleString("ko-KR");

  // ------------------------------------------------------------ 색상
  function mix(a, b, t) {
    const pa = a.match(/\w\w/g).map((h) => parseInt(h, 16)), pb = b.match(/\w\w/g).map((h) => parseInt(h, 16));
    return "#" + pa.map((x, i) => Math.round(x + (pb[i] - x) * t).toString(16).padStart(2, "0")).join("");
  }
  /** 등락률 → 색 (국내 관례: 상승 빨강, 하락 파랑). range: 이 값에서 최대 진하기 */
  function changeColor(v, range) {
    if (!isNum(v)) return "#2c2f36";
    const t = Math.min(1, Math.abs(v) / range);
    if (Math.abs(v) < range * 0.02) return "#3a3d46";
    return v > 0 ? mix("4a3238", "f0284a", Math.pow(t, 0.75)) : mix("2f3a52", "1f6fff", Math.pow(t, 0.75));
  }
  /** 점수(0~100) → 색 (낮음 회색 → 높음 초록) */
  function scoreColor(v) {
    if (!isNum(v)) return "#2c2f36";
    if (v < 45) return mix("3a2c30", "5a2f36", Math.max(0, (45 - v) / 45));
    return mix("2d3a33", "13b864", Math.min(1, (v - 45) / 45));
  }

  // ------------------------------------------------------------ 스파크라인
  function sparkline(vals, w = 80, h = 26, opts = {}) {
    if (!vals || vals.length < 2) return `<svg class="spark" width="${w}" height="${h}"></svg>`;
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const X = (i) => (i / (vals.length - 1)) * (w - 2) + 1, Y = (v) => h - 2 - ((v - lo) / span) * (h - 4);
    const col = vals[vals.length - 1] >= vals[0] ? UP : DOWN;
    const d = vals.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    const id = "g" + Math.random().toString(36).slice(2, 8);
    const area = opts.area === false ? "" : `<path d="${d}L${X(vals.length - 1)},${h}L${X(0)},${h}Z" fill="url(#${id})"/>`;
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity=".35"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
      ${area}<path d="${d}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${X(vals.length - 1)}" cy="${Y(vals[vals.length - 1])}" r="2" fill="${col}"/></svg>`;
  }

  // ------------------------------------------------------------ 지수 면적 차트 (+이동평균, 호버)
  function indexChart(box, rows, opts = {}) {
    if (!rows || rows.length < 2) { box.innerHTML = ""; return; }
    const W = Math.max(260, box.clientWidth || 320), H = opts.height || 120, pt = 8, pb = 18;
    const vals = rows.map((r) => r[1]);
    const all = rows.flatMap((r) => [r[1], r[2], r[3]]).filter(isNum);
    const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
    const X = (i) => (i / (rows.length - 1)) * (W - 4) + 2, Y = (v) => pt + (1 - (v - lo) / span) * (H - pt - pb);
    const col = vals[vals.length - 1] >= vals[0] ? UP : DOWN;
    const path = (k) => rows.map((r, i) => (isNum(r[k]) ? `${i && isNum(rows[i - 1][k]) ? "L" : "M"}${X(i).toFixed(1)},${Y(r[k]).toFixed(1)}` : "")).join("");
    const d = path(1);
    const id = "ia" + Math.random().toString(36).slice(2, 8);
    let ticks = "", last = "";
    rows.forEach((r, i) => {
      const m = r[0].slice(0, 7);
      if (m !== last && i > 5 && +m.slice(5) % 3 === 1) ticks += `<text x="${X(i)}" y="${H - 4}" fill="#6b7280" font-size="10" text-anchor="middle">${m.slice(2).replace("-", ".")}</text>`;
      last = m;
    });
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" class="ichart"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity=".28"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
      <path d="${d}L${X(rows.length - 1)},${H - pb}L${X(0)},${H - pb}Z" fill="url(#${id})"/>
      <path d="${path(2)}" fill="none" stroke="#ffc342" stroke-width="1" opacity=".7" stroke-dasharray="3 3"/>
      <path d="${path(3)}" fill="none" stroke="#a78bfa" stroke-width="1" opacity=".7" stroke-dasharray="3 3"/>
      <path d="${d}" fill="none" stroke="${col}" stroke-width="1.8"/>${ticks}
      <line class="xh" y1="${pt}" y2="${H - pb}" stroke="#d1d6db" stroke-width=".6" opacity="0"/><circle class="dot" r="3.5" fill="${col}" stroke="#101013" stroke-width="2" opacity="0"/></svg>`;
    const svg = box.querySelector("svg"), xh = svg.querySelector(".xh"), dot = svg.querySelector(".dot");
    const move = (ev) => {
      const p = ev.touches ? ev.touches[0] : ev, rc = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(rows.length - 1, Math.round(((p.clientX - rc.left) / rc.width) * W / (W - 4) * (rows.length - 1))));
      const r = rows[i];
      xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i)); xh.setAttribute("opacity", ".5");
      dot.setAttribute("cx", X(i)); dot.setAttribute("cy", Y(r[1])); dot.setAttribute("opacity", "1");
      const ch = (r[1] / rows[0][1] - 1) * 100;
      Tip.show(p.clientX, p.clientY, `<b>${r[0]}</b><br>${fmt(r[1])} <span style="color:${ch >= 0 ? UP : DOWN}">${ch >= 0 ? "+" : ""}${ch.toFixed(1)}%</span> <span class="tmuted">(1년 전 대비)</span>`
        + (isNum(r[2]) ? `<br><span style="color:#ffc342">60일선</span> ${fmt(r[2])}` : "") + (isNum(r[3]) ? ` · <span style="color:#a78bfa">120일선</span> ${fmt(r[3])}` : ""));
    };
    const leave = () => { xh.setAttribute("opacity", "0"); dot.setAttribute("opacity", "0"); Tip.hide(); };
    svg.addEventListener("mousemove", move); svg.addEventListener("touchmove", move, { passive: true });
    svg.addEventListener("mouseleave", leave); svg.addEventListener("touchend", leave);
  }

  // ------------------------------------------------------------ 도넛
  function donut(parts, size = 120, thick = 14, center = "") {
    const r = size / 2 - thick / 2, c = 2 * Math.PI * r;
    const tot = parts.reduce((a, p) => a + p.value, 0) || 1;
    let off = 0;
    const segs = parts.map((p) => {
      const len = (p.value / tot) * c;
      const s = `<circle class="dseg" r="${r}" cx="${size / 2}" cy="${size / 2}" fill="none" stroke="${p.color}" stroke-width="${thick}"
        stroke-dasharray="${Math.max(0, len - 2)} ${c}" stroke-dashoffset="${-off}" data-tip="${p.label} ${p.value.toFixed(1)}%"/>`;
      off += len;
      return s;
    }).join("");
    return `<svg class="donut" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><g transform="rotate(-90 ${size / 2} ${size / 2})">
      <circle r="${r}" cx="${size / 2}" cy="${size / 2}" fill="none" stroke="#26262d" stroke-width="${thick}"/>${segs}</g>${center}</svg>`;
  }

  // ------------------------------------------------------------ 파이 차트 (호버 시 조각이 튀어나옴)
  function pie(parts, size = 200, opts = {}) {
    const tot = parts.reduce((a, p) => a + Math.max(0, p.value), 0) || 1;
    const cx = size / 2, cy = size / 2, r = size / 2 - 8, hole = opts.hole || 0;
    let a0 = -Math.PI / 2, out = "";
    parts.filter((p) => p.value > 0).forEach((p, i) => {
      const frac = p.value / tot, a1 = a0 + frac * 2 * Math.PI, mid = (a0 + a1) / 2;
      const P = (a, rr) => [cx + rr * Math.cos(a), cy + rr * Math.sin(a)];
      const large = a1 - a0 > Math.PI ? 1 : 0;
      let d;
      if (frac >= 0.9999) d = `M${cx - r},${cy}A${r},${r} 0 1 1 ${cx + r},${cy}A${r},${r} 0 1 1 ${cx - r},${cy}Z`;
      else {
        const [x0, y0] = P(a0, r), [x1, y1] = P(a1, r);
        if (hole) {
          const [h0x, h0y] = P(a0, hole), [h1x, h1y] = P(a1, hole);
          d = `M${x0},${y0}A${r},${r} 0 ${large} 1 ${x1},${y1}L${h1x},${h1y}A${hole},${hole} 0 ${large} 0 ${h0x},${h0y}Z`;
        } else d = `M${cx},${cy}L${x0},${y0}A${r},${r} 0 ${large} 1 ${x1},${y1}Z`;
      }
      const dx = Math.cos(mid) * 7, dy = Math.sin(mid) * 7;
      const [lx, ly] = P(mid, hole ? (r + hole) / 2 : r * 0.62);
      out += `<g class="pslice" style="--dx:${dx}px;--dy:${dy}px;animation-delay:${i * 60}ms" data-tip="${p.tip || p.label + " " + p.value.toFixed(1) + "%"}" ${p.href ? `data-href="${p.href}"` : ""}>
        <path d="${d}" fill="${p.color}" stroke="#1c1c21" stroke-width="2"/>
        ${frac >= 0.06 ? `<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="middle" font-size="${size < 180 ? 11 : 12.5}" font-weight="800" fill="#fff" pointer-events="none">${p.value.toFixed(0)}%</text>` : ""}</g>`;
      a0 = a1;
    });
    return `<svg class="pie" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${out}${opts.center || ""}</svg>`;
  }

  // ------------------------------------------------------------ 범위 막대 (1년 저점~고점 중 현재 위치)
  function rangeBar(lo, hi, v, opts = {}) {
    if (![lo, hi, v].every(isNum) || hi <= lo) return `<div class="rbar na"></div>`;
    const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
    const marks = (opts.marks || []).filter((m) => isNum(m.v)).map((m) => {
      const mt = Math.max(0, Math.min(1, (m.v - lo) / (hi - lo)));
      return `<i class="rmark" style="left:${mt * 100}%;background:${m.color}" data-tip="${m.label}"></i>`;
    }).join("");
    return `<div class="rbar ${opts.cls || ""}"><div class="rtrack"><i class="rfill" style="width:${t * 100}%"></i>${marks}<i class="rdot" style="left:${t * 100}%"></i></div>
      <div class="rlab"><span>${opts.loLabel ?? lo}</span><span>${opts.hiLabel ?? hi}</span></div></div>`;
  }

  // ------------------------------------------------------------ 레이더 (점수 구성)
  function radar(items, size = 220) {
    const n = items.length, cx = size / 2, cy = size / 2 + 4, R = size / 2 - 34;
    const pt = (i, v) => {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / n, rr = (R * (v ?? 0)) / 100;
      return [cx + rr * Math.cos(a), cy + rr * Math.sin(a)];
    };
    let grid = "";
    [25, 50, 75, 100].forEach((g) => {
      grid += `<polygon points="${items.map((_, i) => pt(i, g).join(",")).join(" ")}" fill="none" stroke="#2e2e37" stroke-width="1"/>`;
    });
    items.forEach((_, i) => { const [x, y] = pt(i, 100); grid += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#2e2e37"/>`; });
    const poly = items.map((it, i) => pt(i, it.value ?? 0).join(",")).join(" ");
    const labels = items.map((it, i) => {
      const [x, y] = pt(i, 128);
      return `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle" font-size="11.5" fill="#b0b3ba">${it.label}</text>
        <text x="${x}" y="${y + 13}" text-anchor="middle" font-size="11" font-weight="700" fill="${it.value == null ? "#7d818b" : "#f2f3f5"}">${it.value == null ? "N/A" : it.value}</text>`;
    }).join("");
    const dots = items.map((it, i) => { const [x, y] = pt(i, it.value ?? 0); return `<circle cx="${x}" cy="${y}" r="3" fill="#3182f6"/>`; }).join("");
    return `<svg class="radar" viewBox="0 0 ${size} ${size + 8}" width="100%" style="max-width:${size + 40}px">${grid}
      <polygon class="rpoly" points="${poly}" fill="rgba(49,130,246,.28)" stroke="#3182f6" stroke-width="2"/>${dots}${labels}</svg>`;
  }

  // ------------------------------------------------------------ 반원 게이지 (총점)
  function gauge(v, size = 150, color = "#3182f6") {
    const r = size / 2 - 12, cx = size / 2, cy = size / 2 + 4, len = Math.PI * r;
    const t = isNum(v) ? Math.max(0, Math.min(1, v / 100)) : 0;
    return `<svg class="gauge" width="${size}" height="${size / 2 + 22}" viewBox="0 0 ${size} ${size / 2 + 22}">
      <path d="M${cx - r},${cy} A${r},${r} 0 0 1 ${cx + r},${cy}" fill="none" stroke="#26262d" stroke-width="12" stroke-linecap="round"/>
      <path class="gfill" d="M${cx - r},${cy} A${r},${r} 0 0 1 ${cx + r},${cy}" fill="none" stroke="${color}" stroke-width="12" stroke-linecap="round"
        stroke-dasharray="${len}" stroke-dashoffset="${len * (1 - t)}" style="--len:${len}"/>
      <text x="${cx}" y="${cy - 6}" text-anchor="middle" font-size="30" font-weight="800" fill="#f2f3f5">${isNum(v) ? Math.round(v) : "–"}</text>
      <text x="${cx}" y="${cy + 14}" text-anchor="middle" font-size="11" fill="#7d818b">/ 100점</text></svg>`;
  }

  // ------------------------------------------------------------ 스쿼리파이드 트리맵
  function squarify(items, x, y, w, h) {
    // items: [{value, ...}] 내림차순 → [{item, x, y, w, h}]
    const out = [];
    const total = items.reduce((a, it) => a + it.value, 0);
    if (!total || w <= 0 || h <= 0) return out;
    const scale = (w * h) / total;
    let rest = items.map((it) => ({ it, a: it.value * scale }));
    let rx = x, ry = y, rw = w, rh = h;
    const worst = (row, side) => {
      const s = row.reduce((a, r) => a + r.a, 0), mx = Math.max(...row.map((r) => r.a)), mn = Math.min(...row.map((r) => r.a));
      return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
    };
    while (rest.length) {
      const side = Math.min(rw, rh);
      let row = [rest[0]], i = 1;
      while (i < rest.length && worst([...row, rest[i]], side) <= worst(row, side)) { row.push(rest[i]); i++; }
      const s = row.reduce((a, r) => a + r.a, 0);
      if (rw >= rh) {
        const cw = s / rh; let cy = ry;
        row.forEach((r) => { const ch = r.a / cw; out.push({ item: r.it, x: rx, y: cy, w: cw, h: ch }); cy += ch; });
        rx += cw; rw -= cw;
      } else {
        const ch = s / rw; let cx = rx;
        row.forEach((r) => { const cw = r.a / ch; out.push({ item: r.it, x: cx, y: ry, w: cw, h: ch }); cx += cw; });
        ry += ch; rh -= ch;
      }
      rest = rest.slice(row.length);
    }
    return out;
  }

  // ------------------------------------------------------------ 공용 툴팁
  const Tip = {
    el: null,
    init() {
      if (this.el) return;
      this.el = document.createElement("div");
      this.el.className = "vtip";
      document.body.appendChild(this.el);
      document.addEventListener("mouseover", (e) => {
        const t = e.target.closest("[data-tip]");
        if (t) this.show(e.clientX, e.clientY, t.getAttribute("data-tip"));
      });
      document.addEventListener("mousemove", (e) => {
        const t = e.target.closest("[data-tip]");
        if (t) this.move(e.clientX, e.clientY);
      });
      document.addEventListener("mouseout", (e) => { if (e.target.closest("[data-tip]")) this.hide(); });
      window.addEventListener("scroll", () => this.hide(), { passive: true });
    },
    show(x, y, html) { this.init(); this.el.innerHTML = html; this.el.style.display = "block"; this.move(x, y); },
    move(x, y) {
      if (!this.el) return;
      const r = this.el.getBoundingClientRect(), vw = window.innerWidth, vh = window.innerHeight;
      let lx = x + 14, ly = y + 14;
      if (lx + r.width > vw - 8) lx = x - r.width - 14;
      if (ly + r.height > vh - 8) ly = y - r.height - 14;
      this.el.style.left = Math.max(6, lx) + "px"; this.el.style.top = Math.max(6, ly) + "px";
    },
    hide() { if (this.el) this.el.style.display = "none"; },
  };

  // ------------------------------------------------------------ 숫자 카운트업
  function countUp(el, to, opts = {}) {
    if (!el || !isNum(to)) return;
    const dur = opts.dur || 700, dec = opts.dec || 0, suf = opts.suf || "", start = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = (to * e).toLocaleString("ko-KR", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + suf;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  window.Viz = { pie, changeColor, scoreColor, sparkline, indexChart, donut, rangeBar, radar, gauge, squarify, Tip, countUp, UP, DOWN, FLAT };
})();
