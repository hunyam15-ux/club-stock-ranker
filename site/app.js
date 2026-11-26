/* 매수 레이더 — 정적 SPA (해시 라우팅)
   데이터: data/latest.json (전 종목 요약), data/stock/{code}.json (종목 상세 + 1년 일봉) */
(() => {
  "use strict";
  const $app = document.getElementById("app");
  const $status = document.getElementById("status");
  let DATA = null;
  const detailCache = {};
  const state = { sort: "rank", dir: 1, sector: "", market: "", grades: new Set(), mcap: "", q: "", club: false, shown: 50 };
  const TOP_N = 10;

  // ------------------------------------------------------------ 포맷
  const NA = '<span class="na">N/A</span>';
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const won = (v) => (isNum(v) ? Math.round(v).toLocaleString("ko-KR") + "원" : NA);
  const n0 = (v) => (isNum(v) ? Math.round(v).toLocaleString("ko-KR") : NA);
  const x1 = (v, suf = "배") => (isNum(v) ? v.toFixed(1) + suf : NA);
  const perf = (v) => (isNum(v) && v <= 0 ? '<span class="muted">적자</span>' : x1(v));
  const p1 = (v) => (isNum(v) ? v.toFixed(1) + "%" : NA);
  const sgn = (v, d = 1) => {
    if (!isNum(v)) return NA;
    if (Math.abs(v) < 0.5 * Math.pow(10, -d)) v = 0;
    const cls = v > 0 ? "up" : v < 0 ? "down" : "";
    return `<span class="${cls}">${v > 0 ? "+" : ""}${v.toFixed(d)}%</span>`;
  };
  const eok = (v) => {
    if (!isNum(v)) return NA;
    if (Math.abs(v) >= 10000) return (v / 10000).toFixed(v >= 100000 ? 0 : 1) + "조";
    return Math.round(v).toLocaleString("ko-KR") + "억";
  };
  const gradeBadge = (s) => `<span class="g g-${s.score.grade}">${s.score.grade_emoji} ${esc(s.score.grade_label)}</span>`;
  const gradeShort = { green: "🟢 개꿀", yellow: "🟡 분할매수", white: "⚪ 관망", red: "🔴 비싸다" };
  const bar = (v) => `<span class="bar"><i style="width:${isNum(v) ? Math.max(0, Math.min(100, v)) : 0}%"></i></span>`;
  const tlabel = (src) => ({ "컨센서스": "컨센서스 목표가", "보수적 목표가": "보수적 목표가", "내재가치": "내재가치", "모델 적정가": "모델 적정가", "모임": "모임 목표가" }[src] || "목표가");
  const alphaChips = (s) => {
    const a = s.alpha || {}, out = [];
    out.push(a.quality_ok ? `<span class="ac ok">✓ 퀄리티 통과</span>` : `<span class="ac no">✕ 퀄리티 미달</span>`);
    if (isNum(a.surprise)) out.push(`<span class="ac ${a.surprise >= 0 ? "ok" : "no"}">어닝 ${a.surprise >= 0 ? "서프라이즈" : "쇼크"} ${a.surprise > 0 ? "+" : ""}${a.surprise.toFixed(1)}%</span>`);
    else if (isNum(a.q_op_yoy)) out.push(`<span class="ac ${a.q_op_yoy >= 0 ? "ok" : "no"}">${esc(a.last_q || "")} 영업익 YoY ${a.q_op_yoy > 0 ? "+" : ""}${a.q_op_yoy.toFixed(0)}%</span>`);
    if (a.orders) out.push(`<span class="ac ok">수주 공시 ${a.orders}건${isNum(a.orders_pct) && a.orders_pct ? ` · 매출 ${a.orders_pct.toFixed(0)}%` : ""}</span>`);
    if (isNum(a.revision)) out.push(`<span class="ac ${a.revision >= 0 ? "ok" : "no"}">컨센서스 ${a.revision >= 0 ? "↑" : "↓"} ${Math.abs(a.revision).toFixed(1)}%</span>`);
    if (isNum(s.mos_pct)) out.push(`<span class="ac ${s.mos_pct >= 0 ? "ok" : "no"}">안전마진 ${s.mos_pct > 0 ? "+" : ""}${s.mos_pct.toFixed(0)}%</span>`);
    if (a.low_vol) out.push(`<span class="ac ok">저변동성</span>`);
    if (a.knife) out.push(`<span class="ac no">하락 추세</span>`);
    if (s.bucket) out.push(`<span class="ac bk">${esc(s.bucket)} ${(s.weight_pct || 0).toFixed(1)}%</span>`);
    return `<div class="achips">${out.join("")}</div>`;
  };
  const li = (arr, empty) => (arr && arr.length ? `<ul class="blist">${arr.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : `<p class="muted small">${empty}</p>`);
  const clubTag = (s) => (s.club ? `<span class="tag club">모임 발표</span>` : "");

  // ------------------------------------------------------------ 데이터
  async function load() {
    try {
      const r = await fetch("data/latest.json", { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      DATA = await r.json();
    } catch (e) {
      $status.innerHTML = "";
      $app.innerHTML = `<div class="card sec" style="margin-top:16px"><h2>아직 수집된 데이터가 없습니다</h2>
        <p class="muted">GitHub 저장소의 <b>Actions → 데이터 갱신 및 배포 → Run workflow</b>를 실행하면 데이터가 채워집니다.</p></div>`;
      return false;
    }
    return true;
  }
  async function detail(code) {
    if (detailCache[code]) return detailCache[code];
    const r = await fetch(`data/stock/${code}.json`, { cache: "no-store" });
    if (!r.ok) throw new Error("no detail");
    return (detailCache[code] = await r.json());
  }

  // ------------------------------------------------------------ 상단 요약
  function renderStatus() {
    const m = DATA.meta, c = m.cash || {}, gc = m.grade_counts || {}, u = m.universe || {}, IS = m.index_series || {};
    let warn = "";
    if (m.demo) warn += `<div class="banner err">⚠️ 화면 확인용 <b>데모 데이터</b>입니다. 실제 시세가 아닙니다.</div>`;
    if (!m.dart_enabled) warn += `<div class="banner">DART API 키가 없어 희석 물량·대주주 지분은 N/A로 표시됩니다.</div>`;
    const idxCard = (sym, label) => {
      const x = IS[sym] || {}, rows = x.rows || [], last = rows.length ? rows[rows.length - 1] : null;
      const y1 = rows.length ? (last[1] / rows[0][1] - 1) * 100 : null;
      return `<div class="hcard idx"><div class="hk">${label}</div>
        <div class="hv"><b class="cu" data-to="${last ? last[1] : ""}" data-dec="2">${last ? last[1].toLocaleString("ko-KR", { minimumFractionDigits: 2 }) : "N/A"}</b>
          ${sgn(x.change_pct, 2)}</div>
        <div class="hs">1년 ${sgn(y1, 1)} · <span style="color:#ffc342">60일선</span> · <span style="color:#a78bfa">120일선</span></div>
        <div class="ich" data-sym="${sym}"></div></div>`;
    };
    const cp = isNum(c.cash_pct) ? c.cash_pct : 0;
    const P = DATA.stocks.filter((s) => s.weight_pct > 0);
    const core = P.filter((s) => s.bucket === "코어").reduce((a, s) => a + s.weight_pct, 0);
    const sat = P.filter((s) => s.bucket === "새틀라이트").reduce((a, s) => a + s.weight_pct, 0);
    const dn = Viz.donut([{ label: "코어", value: core, color: "#3182f6" }, { label: "새틀라이트", value: sat, color: "#a78bfa" },
      { label: "현금", value: Math.max(0, 100 - core - sat), color: "#4e5968" }], 128, 16,
      `<text x="64" y="62" text-anchor="middle" font-size="24" font-weight="800" fill="#f2f3f5">${cp.toFixed(0)}%</text><text x="64" y="80" text-anchor="middle" font-size="11" fill="#7d818b">권장 현금</text>`);
    const tot = ["green", "yellow", "white", "red"].reduce((a, g) => a + (gc[g] || 0), 0) || 1;
    const gcol = { green: "#2fca73", yellow: "#ffc342", white: "#6b7280", red: "#ff6b6b" };
    $status.innerHTML = `${portfolioTop()}<div class="hgrid">
      ${idxCard("KOSPI", "코스피")}${idxCard("KOSDAQ", "코스닥")}
      <div class="hcard"><div class="hk">매수 등급 분포 <span class="tmuted">· 눌러서 필터</span></div>
        <div class="hv"><b class="cu" data-to="${u.analyzed || 0}">${n0(u.analyzed)}</b><span class="unit">종목 분석</span></div>
        <div class="gstack">${["green", "yellow", "white", "red"].map((g) => `<a href="#/" data-grade="${g}" style="flex:${Math.max(gc[g] || 0, tot * 0.02)};background:${gcol[g]}" data-tip="${gradeShort[g]} ${gc[g] || 0}종목 (${(((gc[g] || 0) / tot) * 100).toFixed(0)}%)"></a>`).join("")}</div>
        <div class="glegend">${["green", "yellow", "white", "red"].map((g) => `<a href="#/" data-grade="${g}"><i style="background:${gcol[g]}"></i>${gradeShort[g].split(" ")[1]} <b>${gc[g] || 0}</b></a>`).join("")}</div>
        <div class="hs">${esc(String(m.generated_at || "").replace(" KST", ""))} 갱신 · 코스피·코스닥 ${n0(u.listed)}개 중</div></div>
    </div>
    <div class="hcard macro2">${macroHtml(m)}</div>${warn}`;
    Viz.bindRing($status);
    $status.querySelectorAll(".ich").forEach((el) => Viz.indexChart(el, (IS[el.dataset.sym] || {}).rows, { height: window.innerWidth < 720 ? 70 : 96 }));
    $status.querySelectorAll(".cu").forEach((el) => { const v = parseFloat(el.dataset.to); if (isFinite(v)) Viz.countUp(el, v, { dec: +(el.dataset.dec || 0) }); });
    $status.querySelectorAll("[data-grade]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault(); state.grades = new Set([a.dataset.grade]); state.jumpAll = true;
      if (location.hash === "#/" || location.hash === "") route(); else location.hash = "#/";
    }));
  }

  const SEC_PAL = ["#3182f6", "#22b8cf", "#8b7cf6", "#4dabf7", "#3fd0a4", "#b197fc", "#5c7cfa", "#66d9e8"];
  const NONSTOCK = { etf: "#63e6be", short_bond: "#ffc342", gov_bond: "#ff922b", cash: "#5a6070" };
  function lighten(hex, t) {
    const n = hex.match(/\w\w/g).map((h) => parseInt(h, 16));
    return "#" + n.map((x) => Math.round(x + (255 - x) * t).toString(16).padStart(2, "0")).join("");
  }

  function portfolioTop() {
    const m = DATA.meta, port = m.portfolio || {}, alloc = port.allocation || [];
    if (!alloc.length) return "";
    const byCode = Object.fromEntries(DATA.stocks.map((s) => [s.code, s]));
    // 섹터별 묶음 (구버전 데이터면 종목에서 직접 계산)
    let secs = port.sectors;
    if (!secs) {
      const mp = {};
      DATA.stocks.filter((s) => s.weight_pct > 0).forEach((s) => {
        const d = (mp[s.sector] = mp[s.sector] || { sector: s.sector, pct: 0, stocks: [] });
        d.pct += s.weight_pct; d.stocks.push({ code: s.code, name: s.name, pct: s.weight_pct, bucket: s.bucket });
      });
      secs = Object.values(mp).sort((a, b) => b.pct - a.pct);
      if (port.index_etf_pct > 0) secs.push({ sector: "지수 ETF(코스피200)", pct: port.index_etf_pct, stocks: [], etf: true });
    }
    const secCol = {};
    let ci = 0;
    secs.forEach((d) => { secCol[d.sector] = d.etf ? NONSTOCK.etf : SEC_PAL[ci++ % SEC_PAL.length]; });
    const eq = secs.reduce((a, d) => a + d.pct, 0);
    const non = alloc.filter((a) => ["short_bond", "gov_bond", "cash"].includes(a.key));
    const nonTot = non.reduce((a, x) => a + x.pct, 0);

    // ① 전체 자산: 주식(섹터별) + 주식 외
    const p1 = secs.map((d, i) => ({ key: "s" + i, label: d.sector, value: d.pct, color: secCol[d.sector],
      tip: `<b>${esc(d.sector)}</b> ${d.pct.toFixed(1)}%${d.stocks.length ? "<br>" + d.stocks.map((x) => `${esc(x.name)} ${x.pct.toFixed(1)}%`).join(" · ") : ""}` }))
      .concat(non.map((a) => ({ key: a.key, label: a.label, value: a.pct, color: NONSTOCK[a.key], tip: `<b>${esc(a.label)}</b> ${a.pct.toFixed(1)}%<br>${esc(a.note)}` })));
    const stockKeys = secs.map((_, i) => "s" + i);
    const ring1 = Viz.ring(p1, { center: { value: eq.toFixed(0) + "%", label: "주식 비중" }, bracket: { keys: stockKeys, color: "#3182f6" } });
    const leg1 = `<div class="lgrp"><div class="lgh"><span class="lgdot" style="background:#3182f6"></span>주식 <b>${eq.toFixed(1)}%</b><em>${secs.filter((d) => !d.etf).length}개 섹터</em></div>
        ${secs.map((d, i) => `<div class="lrow" data-k="s${i}"><i style="background:${secCol[d.sector]}"></i><span>${esc(d.sector)}<em>${d.stocks.map((x) => esc(x.name)).join(", ")}</em></span><b>${d.pct.toFixed(1)}%</b></div>`).join("")}</div>
      <div class="lgrp"><div class="lgh"><span class="lgdot" style="background:#8b8f98"></span>주식 외 <b>${nonTot.toFixed(1)}%</b><em>현금 비중 ${m.cash?.cash_pct ?? "-"}%를 나눠 둠</em></div>
        ${non.map((a) => `<div class="lrow" data-k="${a.key}" data-tip="${esc(a.note)}"><i style="background:${NONSTOCK[a.key]}"></i><span>${esc(a.label)}</span><b>${a.pct.toFixed(1)}%</b></div>`).join("")}</div>`;

    // ② 주식 몫 안의 종목 (섹터 색을 이어받음)
    const P = [];
    secs.forEach((d) => d.stocks.forEach((x, j) => P.push({ ...x, sector: d.sector, color: j ? lighten(secCol[d.sector], 0.35 * j) : secCol[d.sector] })));
    const p2 = P.map((x) => {
      const s = byCode[x.code] || {};
      return { key: "c" + x.code, label: x.name, value: x.pct, color: x.color, href: `#/stock/${x.code}`,
        tip: `<b>${esc(x.name)}</b> ${x.pct.toFixed(1)}% · ${esc(x.sector)}<br>${esc(s.weight_why || "")}` };
    });
    if (port.index_etf_pct > 0) p2.push({ key: "etf2", label: "지수 ETF", value: port.index_etf_pct, color: NONSTOCK.etf, tip: "비중 상한·섹터 상한으로 남은 주식 몫" });
    const ring2 = Viz.ring(p2, { center: { value: P.length + "종목", label: `주식 ${eq.toFixed(0)}% 안에서` }, bracket: { keys: [], color: "#3182f6" } });
    const leg2 = `<div class="lgrp">${P.map((x) => {
      const s = byCode[x.code] || {}, sc = s.score || {};
      return `<a class="lrow stock" data-k="c${esc(x.code)}" href="#/stock/${esc(x.code)}" data-tip="${esc(s.weight_why || "")}"><i style="background:${x.color}"></i>
        <span><b class="nm2">${esc(x.name)}</b><em>${esc(x.sector)} · ${esc(x.bucket || "")}${s.is_holdco ? " · 지주사" : ""} · ${gradeShort[sc.grade] || ""} ${isNum(sc.total) ? sc.total.toFixed(0) + "점" : ""}</em></span><b>${x.pct.toFixed(1)}%</b></a>`;
    }).join("")}
      ${port.index_etf_pct > 0 ? `<div class="lrow" data-k="etf2"><i style="background:${NONSTOCK.etf}"></i><span>지수 ETF (코스피200)<em>상한으로 남은 주식 몫</em></span><b>${port.index_etf_pct.toFixed(1)}%</b></div>` : ""}
      ${!P.length ? '<p class="muted small">현재 매수 등급 종목이 없어 주식 몫은 지수 ETF로 채웁니다.</p>' : ""}</div>`;

    return `<div class="ptop">
      <div class="ptop-h"><div><h2>오늘의 포트폴리오</h2><div class="hs">총자산 100% 기준 · ${esc(String(m.generated_at || "").replace(" KST", ""))}</div></div>
        <a class="pbtn" href="#/rules">배분 원칙 →</a></div>
      <div class="pgrid">
        <div class="pcol" data-ring><div class="pt">전체 자산 배분 <span class="tmuted">파란 테두리 = 주식</span></div>
          <div class="prow2">${ring1}<div class="plegend">${leg1}</div></div></div>
        <div class="pcol" data-ring><div class="pt"><span class="lgdot" style="background:#3182f6"></span>주식 ${eq.toFixed(0)}%는 이렇게 <span class="tmuted">섹터 색 · 눌러서 상세</span></div>
          <div class="prow2">${ring2}<div class="plegend">${leg2}</div></div></div>
      </div>${selectionHtml(port)}</div>`;
  }

  function selectionHtml(port) {
    const log = port.log || [], R = port.rules || {};
    if (!log.length) return "";
    const nIn = log.filter((e) => e.status === "in").length;
    const kinds = {};
    log.filter((e) => e.status === "out").forEach((e) => {
      const k = /그룹/.test(e.why) ? "그룹 중복" : /섹터/.test(e.why) ? "섹터 쏠림" : /정원/.test(e.why) ? "정원 마감" : "퀄리티";
      kinds[k] = (kinds[k] || 0) + 1;
    });
    const steps = [
      ["1", "전 종목 채점", "업사이드·가치·성장·알파·가격위험"],
      ["2", "🟢·🟡만 후보", "점수 높은 순으로 훑기"],
      ["3", "코어 / 새틀라이트", `시총 ${((R.core_min_mcap_eok || 20000) / 10000).toFixed(0)}조↑ 퀄리티 통과 ${R.core_size || 4}개 · 중소형 ${R.satellite_size || 2}개`],
      ["4", "분산 규칙", `같은 그룹 1개 · 섹터 ${R.max_per_sector || 2}종목·주식 몫 ${R.max_sector_pct || 40}%까지`],
      ["5", "비중", "점수 × (1+안전마진) ÷ 변동성, 종목 상한"],
    ];
    const row = (e) => `<a class="sl ${e.status}" href="#/stock/${esc(e.code)}">
          <span class="sl-t">${e.status === "in" ? "편입" : "제외"}</span>
          <span class="sl-n"><b>${esc(e.name)}</b><em>${esc(e.sector)} · ${esc(e.bucket)}${e.holdco ? " · 지주사" : ""}</em></span>
          <span class="sl-s">${isNum(e.total) ? e.total.toFixed(1) : "-"}점</span>
          <span class="sl-w">${e.status === "in" ? `<b>${(e.weight_pct || 0).toFixed(1)}%</b>` : esc(e.why)}</span></a>`;
    return `<details class="sel" open><summary><span class="pt" style="margin:0">어떻게 골랐나</span>
        <span class="tmuted">후보 ${log.length}개 심사 · 편입 ${nIn} · ${Object.entries(kinds).map(([k, v]) => `${k} ${v}`).join(" · ")}</span></summary>
      <div class="ssteps">${steps.map(([n, t, d]) => `<div class="sst"><span class="sn">${n}</span><div><b>${t}</b><em>${esc(d)}</em></div></div>`).join("")}</div>
      <div class="slog">${log.filter((e, i) => i < 12 || e.status === "in").map(row).join("")}</div>
      ${log.length > 12 ? `<details class="smore"><summary>나머지 제외 후보 ${log.filter((e, i) => i >= 12 && e.status !== "in").length}개 보기</summary>
        <div class="slog">${log.filter((e, i) => i >= 12 && e.status !== "in").map(row).join("")}</div></details>` : ""}
      <p class="tiny muted" style="margin:10px 2px 0">점수는 사람이 고른 테마·업황 판단이 아니라 수집된 숫자로만 계산합니다. 업황 전망(예: 반도체 사이클)은 반영돼 있지 않으니 최종 판단은 직접 해 주세요.</p></details>`;
  }

  function macroHtml(m) {
    const mc = m.macro || {}, c = m.cash || {}, mk = m.market || {}, cm = (DATA.meta.config.cash || {}).macro || {};
    const item = (k, lab, warnAt) => {
      const x = mc[k] || {};
      if (!isNum(x.value)) return `<div class="mg"><div class="mgh"><span>${lab}</span><b class="na">N/A</b></div></div>`;
      const ch = isNum(x.chg_1m) ? `<span class="${x.chg_1m > 0 ? "up" : x.chg_1m < 0 ? "down" : ""}">${x.chg_1m > 0 ? "+" : ""}${x.chg_1m.toFixed(2)}%p</span>` : "";
      const hot = isNum(warnAt) && x.value >= warnAt;
      return `<div class="mg ${hot ? "hot" : ""}"><div class="mgh"><span>${lab}</span><b>${x.value.toFixed(2)}%</b>${ch}</div>
        ${Viz.rangeBar(x.low_1y, x.high_1y, x.value, { loLabel: "1년 저 " + (x.low_1y ?? 0).toFixed(2), hiLabel: "고 " + (x.high_1y ?? 0).toFixed(2), cls: hot ? "hot" : "",
          marks: isNum(warnAt) ? [{ v: warnAt, color: "#ff6b6b", label: "경고선 " + warnAt + "%" }] : [] })}</div>`;
    };
    const steps = (c.steps || []).map((s) => `<span class="stp" data-tip="${esc(s.label)}">${esc(s.label.split(":")[0].split("(")[0].trim())} <b class="${s.adj > 0 ? "up" : s.adj < 0 ? "down" : ""}">${s.adj > 0 ? "+" : ""}${s.adj}</b></span>`).join("");
    return `<div class="mhead"><span class="mt">불안요소 체크</span><span class="tmuted">현금 비중 계산</span><div class="steps">${steps}<span class="stp eq">= <b>${c.cash_pct}%</b></span></div></div>
      <div class="mgrid">${item("hy_spread", "하이일드 스프레드", cm.hy_spread_high)}${item("us10y", "미국 10년물", cm.us10y_high)}${item("kr10y", "한국 10년물(월)")}
        <div class="mg"><div class="mgh"><span>코스피 12개월</span><b class="${(mk.ret_12m || 0) >= 0 ? "up" : "down"}">${isNum(mk.ret_12m) ? (mk.ret_12m > 0 ? "+" : "") + mk.ret_12m.toFixed(1) + "%" : "N/A"}</b></div>
          <div class="tmuted" style="font-size:12px;margin-top:8px">${isNum(mk.ret_12m) && mk.ret_12m < 0 ? "절대모멘텀 음수 → 현금 확대" : "절대모멘텀 양수"}</div></div></div>`;
  }

  const COMP_LABELS = [["upside", "업사이드"], ["value", "가치"], ["growth", "성장"], ["alpha", "알파"], ["price_risk", "가격·위험"]];
  function compBars(s) {
    const c = s.comps || {};
    return `<div class="cbars">${COMP_LABELS.map(([k, l]) => {
      const v = c[k];
      const col = v == null ? "#3a3d46" : v >= 70 ? "#2fca73" : v >= 50 ? "#3182f6" : v >= 35 ? "#ffc342" : "#ff6b6b";
      return `<div class="cb" data-tip="${l} ${v ?? "N/A"}점"><span>${l}</span><div><i style="width:${v ?? 0}%;background:${col}"></i></div></div>`;
    }).join("")}</div>`;
  }

  // ------------------------------------------------------------ TOP 픽 카드
  function pickCard(s) {
    const sc = s.score, t = s.thesis || {}, pl = s.plan || {};
    return `<article class="pick" data-code="${esc(s.code)}">
      <header class="pick-h">
        <div class="pick-title"><span class="rkb">${s.rank}</span>
          <div><h3>${esc(s.name)} ${clubTag(s)}</h3><div class="tiny muted">${esc(s.code)} · ${esc(s.market || "")}</div></div></div>
        <div class="pick-price"><b>${won(s.price)}</b><span class="tiny">${sgn(s.change_pct, 2)}</span>${Viz.sparkline(s.spark, 96, 28)}</div>
      </header>
      <div class="pick-verdict">${gradeBadge(s)}<span class="score-big">${isNum(sc.total) ? sc.total.toFixed(0) : "N/A"}<small>점</small></span>
        <span class="tiny muted">${esc(sc.reason)}</span></div>
      ${alphaChips(s)}
      ${compBars(s)}
      <div class="boxes">
        <section class="box">
          <div class="box-t">🏢 어떤 회사?</div>
          <div class="chips-s"><span class="tag">${esc(s.sector)}</span><span class="tag">시총 ${eok(s.mcap_eok)}</span>${s.club_sector ? `<span class="tag">모임 섹터: ${esc(s.club_sector)}</span>` : ""}</div>
          <p class="desc">${s.summary && s.summary.length ? esc(s.summary.join(" ")) : '<span class="muted">회사 소개 정보 없음</span>'}</p>
        </section>
        <section class="box good">
          <div class="box-t">💡 왜 사야 하나</div>${li((t.ideas || []).slice(0, 4), "뚜렷한 매수 근거가 데이터상 부족합니다.")}
        </section>
        <section class="box bad">
          <div class="box-t">⚠️ 리스크</div>${li((t.risks || []).slice(0, 3), "데이터상 큰 리스크 신호 없음 (공시·뉴스는 직접 확인)")}
        </section>
        <section class="box">
          <div class="box-t">🎯 목표가 · 매매</div>
          <div class="tp"><div><span class="k">${esc(tlabel(s.target_source))}</span><b>${won(s.target)}</b><span>${sgn(sc.upside_pct, 0)}</span></div>
            <div><span class="k">1차 매수</span><b>${won(pl.entry1)}</b></div>
            <div><span class="k">손절</span><b class="down">${won(pl.stop)}</b></div>
            <div><span class="k">권장 비중</span><b>${(s.weight_pct || 0).toFixed(1)}%</b></div></div>
          <p class="tiny muted" style="margin:8px 0 0">${esc((t.target_basis || [])[0] || "")}</p>
        </section>
      </div>
      <a class="more" href="#/stock/${esc(s.code)}">차트 · 실적 · 매매 전략 자세히 보기 →</a>
    </article>`;
  }

  // ------------------------------------------------------------ 메인
  const MCAP = [["", "시총 전체"], ["0-3000", "3천억 미만"], ["3000-10000", "3천억~1조"], ["10000-50000", "1조~5조"], ["50000-1e12", "5조 이상"]];
  const COLS = [["rank", "순위", "l"], ["name", "종목", "l"], ["grade", "등급", "l"], ["total", "총점"], ["price", "현재가"], ["ret_3m", "3개월"],
    ["upside", "업사이드"], ["per", "PER"], ["pbr", "PBR"], ["fwd_per", "Fwd PER"], ["mcap", "시총"], ["reason", "판단 근거", "l"]];
  const gOrder = { green: 0, yellow: 1, white: 2, red: 3 };
  const sortVal = {
    rank: (s) => s.rank, name: (s) => s.name, grade: (s) => gOrder[s.score.grade] * 1000 - (s.score.total ?? 0),
    total: (s) => s.score.total, price: (s) => s.price, upside: (s) => s.score.upside_pct, per: (s) => s.per,
    pbr: (s) => s.pbr, fwd_per: (s) => s.fwd_per, mcap: (s) => s.mcap_eok, reason: (s) => s.score.reason, ret_3m: (s) => s.ret_3m,
  };

  function filtered() {
    let L = DATA.stocks.slice();
    if (state.sector) L = L.filter((s) => s.sector === state.sector);
    if (state.market) L = L.filter((s) => s.market === state.market);
    if (state.club) L = L.filter((s) => s.club);
    if (state.grades.size) L = L.filter((s) => state.grades.has(s.score.grade));
    if (state.mcap) {
      const [a, b] = state.mcap.split("-").map(Number);
      L = L.filter((s) => isNum(s.mcap_eok) && s.mcap_eok >= a && s.mcap_eok < b);
    }
    if (state.q) {
      const q = state.q.toLowerCase();
      L = L.filter((s) => (s.name + s.code + s.sector).toLowerCase().includes(q));
    }
    const f = sortVal[state.sort];
    L.sort((x, y) => {
      const a = f(x), b = f(y);
      const an = a === null || a === undefined, bn = b === null || b === undefined;
      if (an && bn) return x.rank - y.rank;
      if (an) return 1;
      if (bn) return -1;
      return (typeof a === "string" ? a.localeCompare(b, "ko") : a - b) * state.dir;
    });
    return L;
  }

  function renderRank() {
    const sectors = [...new Set(DATA.stocks.map((s) => s.sector))].sort((a, b) => a.localeCompare(b, "ko"));
    const picks = DATA.stocks.filter((s) => s.score.grade === "green" || s.score.grade === "yellow").slice(0, TOP_N);
    const clubN = DATA.stocks.filter((s) => s.club).length;
    $app.innerHTML = `
      <div class="sec-h"><h2>오늘의 TOP ${picks.length} 픽</h2><span class="muted small">총점 상위 🟢·🟡 종목 · 카드를 누르면 상세</span></div>
      <div class="picks">${picks.map(pickCard).join("") || '<p class="muted">현재 매수 등급 종목이 없습니다.</p>'}</div>

      <div class="sec-h" id="all"><h2>전체 순위</h2><span class="muted small" id="count"></span></div>
      <div class="filters">
        <input id="q" type="search" placeholder="종목명·코드·업종 검색" value="${esc(state.q)}">
        <select id="sector"><option value="">업종 전체</option>${sectors.map((s) => `<option ${s === state.sector ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <select id="market"><option value="">시장 전체</option>${["코스피", "코스닥"].map((m) => `<option ${m === state.market ? "selected" : ""}>${m}</option>`).join("")}</select>
        <select id="mcap">${MCAP.map(([v, l]) => `<option value="${v}" ${v === state.mcap ? "selected" : ""}>${l}</option>`).join("")}</select>
        <div class="chips">${["green", "yellow", "white", "red"].map((g) => `<button class="chip ${state.grades.has(g) ? "on" : ""}" data-g="${g}">${gradeShort[g]}</button>`).join("")}
          <button class="chip ${state.club ? "on" : ""}" id="clubchip">모임 발표 ${clubN}</button></div>
      </div>
      <div class="card"><div class="tbl-wrap"><table class="rank"><thead><tr>
        ${COLS.map(([k, l, a]) => `<th class="${a || ""}" data-k="${k}">${l} <span class="arr">${state.sort === k ? (state.dir > 0 ? "▲" : "▼") : ""}</span></th>`).join("")}
      </tr></thead><tbody id="tb"></tbody></table></div><div class="mlist" id="ml"></div></div>
      <div class="morebar"><button class="chip" id="showmore">50개 더 보기</button></div>
      <p class="tiny muted">목표가(보수적) = min(컨센서스 × ${DATA.meta.config.target.consensus_haircut}, 내재가치 = 예상 EPS × ${1 - DATA.meta.config.target.intrinsic_eps_haircut} × 업종 중앙 PER).
        업사이드 = (목표가 − 현재가) ÷ 현재가. 자세한 기준은 '매매 원칙' 탭.</p>`;
    $app.querySelectorAll(".pick").forEach((el) => el.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      location.hash = `#/stock/${el.dataset.code}`;
    }));
    const draw = () => {
      const L = filtered();
      const V = L.slice(0, state.shown);
      document.getElementById("count").textContent = `${L.length}종목 중 ${V.length}개 표시`;
      document.getElementById("tb").innerHTML = V.map(rowHtml).join("") || `<tr><td colspan="12" class="l muted">조건에 맞는 종목이 없습니다.</td></tr>`;
      document.getElementById("ml").innerHTML = V.map(cardHtml).join("") || `<p class="sec muted">조건에 맞는 종목이 없습니다.</p>`;
      document.getElementById("showmore").style.display = L.length > V.length ? "" : "none";
    };
    const reset = () => { state.shown = 50; draw(); };
    draw();
    $app.querySelector("#q").addEventListener("input", (e) => { state.q = e.target.value.trim(); reset(); });
    $app.querySelector("#sector").addEventListener("change", (e) => { state.sector = e.target.value; reset(); });
    $app.querySelector("#market").addEventListener("change", (e) => { state.market = e.target.value; reset(); });
    $app.querySelector("#mcap").addEventListener("change", (e) => { state.mcap = e.target.value; reset(); });
    $app.querySelector("#clubchip").addEventListener("click", (e) => { state.club = !state.club; e.target.classList.toggle("on"); reset(); });
    $app.querySelector("#showmore").addEventListener("click", () => { state.shown += 50; draw(); });
    $app.querySelectorAll(".chip[data-g]").forEach((b) => b.addEventListener("click", () => {
      const g = b.dataset.g; state.grades.has(g) ? state.grades.delete(g) : state.grades.add(g);
      b.classList.toggle("on"); reset();
    }));
    $app.querySelectorAll("th").forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.k;
      if (state.sort === k) state.dir *= -1;
      else { state.sort = k; state.dir = ["total", "upside", "mcap"].includes(k) ? -1 : 1; }
      const y = window.scrollY; renderRank(); window.scrollTo(0, y);
    }));
    $app.querySelector("#tb").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-code]"); if (tr) location.hash = `#/stock/${tr.dataset.code}`;
    });
    if (state.jumpAll) { state.jumpAll = false; document.getElementById("all").scrollIntoView(); }
  }

  function portfolioHtml() {
    const P = DATA.stocks.filter((s) => s.weight_pct > 0);
    if (!P.length) return "";
    const c = DATA.meta.cash || {};
    const grp = (b) => P.filter((s) => s.bucket === b);
    const sum = (L) => L.reduce((a, s) => a + s.weight_pct, 0);
    const tbl = (L) => L.map((s) => `<a class="prow" href="#/stock/${esc(s.code)}"><span><b>${esc(s.name)}</b> <span class="tiny muted">${esc(s.sector)}</span></span>
      <span class="tiny">${gradeShort[s.score.grade]}</span><span class="pw"><i style="width:${Math.min(100, s.weight_pct / 12 * 100)}%"></i></span><b class="num">${s.weight_pct.toFixed(1)}%</b></a>`).join("");
    return `<div class="sec-h"><h2>권장 포트폴리오</h2><span class="muted small">코어 & 새틀라이트 · 가치 가중 · 현금 ${c.cash_pct}%</span></div>
      <div class="grid2 port">
        <div class="card sec"><h2>🛡️ 코어 <span class="muted">시총 1조↑ · 퀄리티 통과 · ${sum(grp("코어")).toFixed(0)}%</span></h2>${tbl(grp("코어")) || '<p class="muted small">해당 없음</p>'}</div>
        <div class="card sec"><h2>🚀 새틀라이트 <span class="muted">중소형 알파 · ${sum(grp("새틀라이트")).toFixed(0)}%</span></h2>${tbl(grp("새틀라이트")) || '<p class="muted small">해당 없음</p>'}</div>
      </div>`;
  }

  function rowHtml(s) {
    const sc = s.score;
    return `<tr data-code="${esc(s.code)}">
      <td class="l rk ${s.rank <= 3 ? "rk1" : ""}">${s.rank}</td>
      <td class="l nm">${esc(s.name)} ${clubTag(s)}<small>${esc(s.code)} · ${esc(s.sector)}</small></td>
      <td class="l">${gradeBadge(s)}</td>
      <td><span class="score"><b>${isNum(sc.total) ? sc.total.toFixed(0) : "N/A"}</b>${bar(sc.total)}</span></td>
      <td>${won(s.price)}<div class="tiny">${sgn(s.change_pct, 2)}</div></td>
      <td class="sp">${Viz.sparkline(s.spark, 72, 24)}<div class="tiny">${sgn(s.ret_3m, 0)}</div></td>
      <td>${sgn(sc.upside_pct, 0)}<div class="tiny muted">${esc(s.target_source || "")}</div></td>
      <td>${perf(s.per)}</td><td>${x1(s.pbr, "")}</td><td>${perf(s.fwd_per)}</td><td>${eok(s.mcap_eok)}</td>
      <td class="reason">${esc(sc.reason)}</td></tr>`;
  }

  function cardHtml(s) {
    const sc = s.score;
    return `<a class="mcard" href="#/stock/${esc(s.code)}">
      <div class="mrow"><div class="mname"><span class="rk ${s.rank <= 3 ? "rk1" : ""}">${s.rank}</span>
          <div><b>${esc(s.name)}</b><span class="tiny">${esc(s.sector)} · ${esc(s.code)}</span></div></div>
        <div class="mprice">${Viz.sparkline(s.spark, 56, 22, { area: false })}<div><b>${won(s.price)}</b><span class="tiny">${sgn(s.change_pct, 2)}</span></div></div></div>
      <div class="mstats">${gradeBadge(s)}${clubTag(s)}<span>총점 <b>${isNum(sc.total) ? sc.total.toFixed(0) : "N/A"}</b></span>
        <span>업사이드 ${sgn(sc.upside_pct, 0)}</span><span>PER <b>${perf(s.per)}</b></span></div>
      <div class="reason">${esc(sc.reason)}</div></a>`;
  }

  // ------------------------------------------------------------ 상세
  async function renderStock(code) {
    $app.innerHTML = `<p class="loading">불러오는 중…</p>`;
    let s;
    try { s = await detail(code); } catch (e) {
      $app.innerHTML = `<p class="loading">종목 데이터를 찾을 수 없습니다. <a href="#/">순위로</a></p>`; return;
    }
    const sc = s.score, c = sc.components, est = s.est || {}, pl = s.plan, t = s.thesis || {};
    const yr = est.year;
    const comp = (k, l) => {
      const v = c[k]?.score;
      return `<div class="comp"><span>${l} <span class="tiny muted">×${c[k]?.weight ?? 0}</span></span>${bar(v)}<b class="num">${isNum(v) ? v.toFixed(0) : "N/A"}</b></div>`;
    };
    const pd = sc.penalty_detail || {};
    const dart = s.dart || {}, dil = dart.dilution, fin = dart.financials || {};
    const yrow = (label, key, unit) => {
      const cell = (o) => (o && isNum(o[key]) ? (unit === "won" ? n0(o[key]) : eok(o[key])) : NA);
      return `<tr><td>${label}</td><td>${cell(est.prev)}</td><td>${cell(est.cur)}</td>
        <td>${sgn(est[key + "_g_cur"], 0)}</td><td>${cell(est.next)}</td><td>${sgn(est[key + "_g_next"], 0)}</td></tr>`;
    };
    const tag = (o) => (o && Object.keys(o).length ? (o.estimate ? '<span class="pill">E</span>' : '<span class="pill">확정</span>') : "");
    const sh = s.sheet || {};

    $app.innerHTML = `
      <a class="back" href="#/">← 매수 순위</a>
      <div class="card">
        <div class="dhead">
          <div><h1>${esc(s.name)} ${clubTag(s)}</h1>
            <div class="meta">${esc(s.code)} · ${esc(s.market || "")} · ${esc(s.sector)} · ${s.rank}위</div></div>
          <div class="dprice"><div class="p">${won(s.price)}</div>
            <div>${sgn(s.change_pct, 2)} <span class="tiny muted">${esc(String(s.price_time || "").replace("T", " ").slice(0, 16))}</span></div></div>
        </div>
        <div class="verdict">${gradeBadge(s)}<span class="tot">${isNum(sc.total) ? sc.total.toFixed(1) : "N/A"}점</span>${(sc.flags || []).map((f) => `<span class="ac no">${esc(f)}</span>`).join("")}<span class="why">${esc(sc.reason)}</span></div>
      </div>
      ${priceMapHtml(s)}
      <div class="card sec" style="margin-top:12px"><h2>🧭 종목 선정 프로세스</h2>
        <div class="proc">${(s.process || []).map((p) => `<div class="pstep ${p.ok ? "ok" : "no"}"><div class="pn">${p.ok ? "✓" : "✕"} ${esc(p.name)}</div><div class="tiny">${esc(p.note || "")}</div></div>`).join("")}</div>
      </div>

      <div class="boxes big">
        <section class="box"><div class="box-t">🏢 어떤 회사?</div>
          <div class="chips-s"><span class="tag">${esc(s.sector)}</span><span class="tag">${esc(s.market || "")}</span><span class="tag">시총 ${eok(s.mcap_eok)}</span></div>
          ${s.summary && s.summary.length ? `<ul class="blist">${s.summary.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : '<p class="muted small">회사 소개 정보 없음</p>'}</section>
        <section class="box good"><div class="box-t">💡 왜 사야 하나 <span class="muted tiny">투자아이디어</span></div>${li(t.ideas, "뚜렷한 매수 근거가 데이터상 부족합니다.")}</section>
        <section class="box bad"><div class="box-t">⚠️ 리스크 <span class="muted tiny">Risk</span></div>${li(t.risks, "데이터상 큰 리스크 신호 없음 (공시·뉴스는 직접 확인)")}</section>
        <section class="box"><div class="box-t">🎯 목표가 근거</div>
          <div class="tp"><div><span class="k">${esc(tlabel(s.target_source))}</span><b>${won(s.target)}</b><span>${sgn(sc.upside_pct, 1)}</span></div></div>
          ${li(t.target_basis, "목표가 산출 불가")}</section>
        <section class="box"><div class="box-t">🔍 체크포인트 <span class="muted tiny">주가희석요소 · 경영진</span></div>${li(t.checks, "")}
          ${s.orders?.items?.length ? `<div class="memo-t" style="margin-top:10px">최근 수주 공시 (단일판매·공급계약)</div><table class="mini"><thead><tr><th>공시일</th><th>매출 대비</th><th>계약금액</th></tr></thead><tbody>
            ${s.orders.items.map((o) => `<tr><td><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${esc(o.rcept_no)}" target="_blank" rel="noopener">${esc(o.date)}</a></td><td>${p1(o.pct_of_sales)}</td><td>${isNum(o.amount_won) ? eok(o.amount_won / 1e8) : NA}</td></tr>`).join("")}</tbody></table>` : ""}
          ${dil?.events?.length ? `<table class="mini" style="margin-top:8px"><thead><tr><th>공시일</th><th>종류</th><th>주식총수 대비</th></tr></thead><tbody>
            ${dil.events.slice(0, 6).map((e) => `<tr><td><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${esc(e.rcept_no)}" target="_blank" rel="noopener">${esc(e.date)}</a></td><td>${esc(e.type)}</td><td>${p1(e.pct_of_shares)}</td></tr>`).join("")}</tbody></table>` : ""}</section>
        <section class="box"><div class="box-t">📊 점수 구성 <span class="muted tiny">충족률 ${(sc.coverage * 100).toFixed(0)}% · 감점 −${sc.penalty}</span></div>
          <div class="scoreviz"><div class="gwrap">${Viz.gauge(sc.total, 150, { green: "#2fca73", yellow: "#ffc342", white: "#9aa1ad", red: "#ff6b6b" }[sc.grade])}<div class="tiny muted">가중평균 ${sc.base ?? "N/A"} − 감점 ${sc.penalty}</div></div>
            ${Viz.radar([["upside", "업사이드"], ["value", "가치"], ["growth", "성장"], ["alpha", "알파"], ["price_risk", "가격·위험"]].map(([k, l]) => ({ label: l, value: c[k]?.score == null ? null : Math.round(c[k].score) })), 210)}</div>
          <div class="tiny muted">감점: 희석 ${pd.dilution ?? "N/A"} · 부채 ${pd.debt ?? "N/A"} · 메모 ${pd.memo ?? 0} · 퀄리티 ${pd.quality ?? 0} · 추세 ${pd.knife ?? 0}</div></section>
      </div>

      <div class="card sec" style="margin-top:12px"><h2>주요 지표</h2>
        <div class="kv">
          <div><div class="k">PER (Trailing)</div><div class="v">${perf(s.per)}</div><div class="x">업종 ${x1(s.bench?.per)} · ${esc(s.bench?.per_src || "")}</div></div>
          <div><div class="k">PBR</div><div class="v">${x1(s.pbr, "배")}</div><div class="x">업종 ${x1(s.bench?.pbr)} · ${esc(s.bench?.pbr_src || "")}</div></div>
          <div><div class="k">Forward PER</div><div class="v">${perf(s.fwd_per)}</div><div class="x">${esc(s.fwd_basis || "")}</div></div>
          <div><div class="k">ROE</div><div class="v">${p1(s.roe)}</div><div class="x">최근 연간</div></div>
          <div><div class="k">배당수익률</div><div class="v">${p1(s.div_yield)}</div></div>
          <div><div class="k">52주 고가 / 저가</div><div class="v">${n0(s.high52)} / ${n0(s.low52)}</div><div class="x">범위 내 위치 ${isNum(s.range_pos) ? (s.range_pos * 100).toFixed(0) + "%" : "N/A"}</div></div>
          <div><div class="k">수익률 1M · 3M</div><div class="v small">${sgn(s.ret_1m)} · ${sgn(s.ret_3m)}</div><div class="x">6M ${sgn(s.ret_6m)} · 12M ${sgn(s.ret_12m)}</div></div>
          <div><div class="k">부채비율</div><div class="v">${p1(s.debt_ratio)}</div><div class="x">${esc(s.debt_basis || "")}${s.is_financial ? " · 금융업은 감점 제외" : ""}</div></div>
          <div><div class="k">변동성(60일)</div><div class="v">${p1(s.vol_annual)}</div></div>
          <div><div class="k">컨센서스 변화</div><div class="v">${sgn(s.revision_pct)}</div><div class="x">${esc(s.revision_basis || "과거 스냅샷 누적 중")}</div></div>
          <div><div class="k">최대주주 지분</div><div class="v">${p1(dart.holder?.pct)}</div><div class="x">${esc(dart.holder?.basis || (dart.enabled ? "상위 종목만 조회" : ""))}</div></div>
          <div><div class="k">컨센서스 목표가</div><div class="v">${won(s.target_cons)}</div><div class="x">${s.target_cons ? esc(s.cons_date || "") : "커버리지 없음"}</div></div>
        </div>
      </div>

      <div class="card sec" style="margin-top:12px"><h2>52주 차트 <span class="muted">일봉 · 상승 빨강 / 하락 파랑</span></h2>
        <div class="chart-box" id="chart"></div>
        <div class="legend"><span><i style="border-color:#2fca73;border-top-style:dashed"></i>목표가</span><span><i style="border-color:#d1d6db"></i>분할매수가</span>
          <span><i style="border-color:#8fb8ff;border-top-style:dashed"></i>손절가</span><span><i style="border-color:#6b7280;border-top-style:dotted"></i>52주 고·저</span></div>
      </div>

      ${sensHtml(s)}
      ${quarterHtml(s)}
      <div class="card sec" style="margin-top:12px"><h2>실적 · 컨센서스 <span class="muted">억원, EPS 원 · 네이버 증권</span></h2>
        <table class="mini"><thead><tr><th></th><th>${yr - 1} ${tag(est.prev)}</th><th>${yr} ${tag(est.cur)}</th><th>성장률</th><th>${yr + 1} ${tag(est.next)}</th><th>성장률</th></tr></thead>
          <tbody>${yrow("매출액", "revenue")}${yrow("영업이익", "op_income")}${yrow("EPS", "eps", "won")}</tbody></table>
        ${fin.annual ? `<p class="tiny muted" style="margin:8px 0 0">DART 확정 (${fin.annual.year} 사업보고서, ${esc(fin.annual.fs)}): 매출 ${eok(fin.annual.revenue)} · 영업이익 ${eok(fin.annual.op_income)} · 순이익 ${eok(fin.annual.net_income)}</p>` : ""}
      </div>

      <div class="card sec" style="margin-top:12px"><h2>매매 전략 <span class="muted">권장 비중 ${(s.weight_pct || 0).toFixed(1)}% · 최대 ${DATA.meta.config.strategy.max_weight_pct}%</span></h2>
        ${pl ? planHtml(s, pl) : '<p class="muted">시세 데이터가 없어 전략을 산출하지 못했습니다.</p>'}
      </div>

      ${s.club ? `<div class="card sec" style="margin-top:12px"><h2>모임 발표 기록</h2>
        <table class="mini"><thead><tr><th>발표일</th><th>발표자</th><th>발표일 주가</th><th>목표가</th><th>이후 수익률</th></tr></thead><tbody>
          ${(s.pitches || []).map((p) => `<tr><td>${esc(p.date || "N/A")}</td><td>${esc(p.presenter || "N/A")}</td><td>${won(p.price_at_pitch)}</td>
            <td>${p.target ? won(p.target) : esc(p.target_raw || "N/A")}</td><td>${sgn(p.return_since, 1)}</td></tr>`).join("")}</tbody></table>
        <div class="grid2" style="margin-top:12px">
          <div><div class="memo-t">투자아이디어</div><pre class="memo">${esc(sh.idea || "—")}</pre>
            <div class="memo-t">목표가 근거</div><pre class="memo">${esc(sh.basis || "—")}</pre></div>
          <div><div class="memo-t">Risk</div><pre class="memo">${esc(sh.risk || "—")}</pre>
            <div class="memo-t">비고 · 희석요소 및 경영진 Check</div><pre class="memo">${esc(sh.note || "—")}</pre></div>
        </div></div>` : ""}
      ${s.errors?.length ? `<p class="errs">수집 실패 항목: ${esc(s.errors.join(" / "))}</p>` : ""}`;
    if (s.chart) drawChart(document.getElementById("chart"), s.chart, s);
    else document.getElementById("chart").innerHTML = `<p class="muted small">차트 데이터 N/A</p>`;
  }

  function priceMapHtml(s) {
    const pl = s.plan || {}, ent = pl.entries || [];
    const pts = [
      { v: s.low52, label: "52주 저가", color: "#6b7280" }, { v: pl.stop, label: "손절가", color: "#8fb8ff" },
      ...ent.map((e) => ({ v: e.price, label: `${e.step}차 매수`, color: "#d1d6db" })),
      { v: s.price, label: "현재가", color: "#ffffff", main: true }, { v: s.intrinsic, label: "내재가치", color: "#a78bfa" },
      { v: s.target, label: "보수적 목표가", color: "#2fca73" }, { v: s.target_cons, label: "컨센서스", color: "#5fdc97" },
      { v: s.high52, label: "52주 고가", color: "#6b7280" }].filter((p) => isNum(p.v));
    if (pts.length < 3) return "";
    const lo = Math.min(...pts.map((p) => p.v)) * 0.97, hi = Math.max(...pts.map((p) => p.v)) * 1.03;
    const X = (v) => ((v - lo) / (hi - lo)) * 100;
    const up = s.score.upside_pct;
    return `<div class="card sec" style="margin-top:12px"><h2>🎯 가격 지도 <span class="muted">현재가 → 목표가까지 ${sgn(up, 1)} · 손절까지 ${sgn(isNum(pl.stop) ? (pl.stop / s.price - 1) * 100 : null, 1)}</span></h2>
      <div class="pmap"><div class="pline"></div>
        ${isNum(s.target) ? `<div class="pzone up" style="left:${X(Math.min(s.price, s.target))}%;width:${Math.abs(X(s.target) - X(s.price))}%"></div>` : ""}
        ${isNum(pl.stop) ? `<div class="pzone dn" style="left:${X(pl.stop)}%;width:${X(s.price) - X(pl.stop)}%"></div>` : ""}
        ${(() => {
          // 라벨 겹침 방지: 위·아래 여러 줄 중 빈 자리에 배치
          const lanes = { hi: [-1e9, -1e9, -1e9], lo: [-1e9, -1e9, -1e9] }, gap = window.innerWidth < 720 ? 22 : 11;
          return pts.slice().sort((a, b) => a.v - b.v).map((p) => {
            const x = X(p.v);
            let side = null, row = 0;
            outer: for (const r of [0, 1, 2]) for (const sd of p.main ? ["lo", "hi"] : ["hi", "lo"]) if (x - lanes[sd][r] >= gap) { side = sd; row = r; break outer; }
            if (!side) {  // 빈 자리가 없으면 가장 덜 겹치는 줄
              let best = 1e9;
              for (const r of [0, 1, 2]) for (const sd of ["hi", "lo"]) if (lanes[sd][r] < best) { best = lanes[sd][r]; side = sd; row = r; }
            }
            lanes[side][row] = x;
            return `<div class="pp ${p.main ? "main" : ""} ${side}" style="left:${x}%;--row:${row}" data-tip="${p.label} ${Math.round(p.v).toLocaleString("ko-KR")}원 (${p.v >= s.price ? "+" : ""}${((p.v / s.price - 1) * 100).toFixed(1)}%)">
              <i style="background:${p.color}"></i><span>${p.label}<b>${Math.round(p.v).toLocaleString("ko-KR")}</b></span></div>`;
          }).join("");
        })()}
      </div></div>`;
  }

  function sensHtml(s) {
    const t = s.sensitivity;
    if (!t) return "";
    const cell = (u) => {
      const a = Math.min(1, Math.abs(u) / 80);
      const bg = u >= 0 ? `rgba(240,68,82,${0.1 + a * 0.45})` : `rgba(49,130,246,${0.1 + a * 0.45})`;
      return `style="background:${bg}"`;
    };
    return `<div class="card sec" style="margin-top:12px"><h2>📐 밸류에이션 민감도 <span class="muted">목표가 = ${esc(t.basis || "예상")} EPS × (1 − 감익) × PER · 현재가 ${won(t.price)}</span></h2>
      <table class="mini sens"><thead><tr><th>EPS 감익 \\ PER</th>${t.pers.map((p) => `<th>${p.toFixed(1)}배</th>`).join("")}</tr></thead><tbody>
      ${t.rows.map((r) => `<tr><td>${r.eps_cut}%</td>${r.values.map((v, i) => `<td ${cell(r.upside[i])}>${n0(v)}<div class="tiny">${r.upside[i] > 0 ? "+" : ""}${r.upside[i].toFixed(0)}%</div></td>`).join("")}</tr>`).join("")}
      </tbody></table><p class="tiny muted" style="margin:8px 0 0">PER 열은 업종 중앙 PER의 ${DATA.meta.config.target.sensitivity_per_mults.map((m) => m + "배").join("·")} · 빨강=현재가 대비 상승, 파랑=하락</p></div>`;
  }

  function quarterHtml(s) {
    const Q = s.quarters || {};
    const ks = Object.keys(Q).sort();
    if (!ks.length) return "";
    return `<div class="card sec" style="margin-top:12px"><h2>분기 실적 <span class="muted">억원 · E=컨센서스${isNum(s.surprise_pct) ? ` · ${esc(s.surprise_q)} 서프라이즈 ${s.surprise_pct > 0 ? "+" : ""}${s.surprise_pct.toFixed(1)}%` : " · 서프라이즈는 발표 전 컨센서스가 저장된 분기부터 계산"}</span></h2>
      <table class="mini"><thead><tr><th></th>${ks.map((k) => `<th>${esc(k)}${Q[k].estimate ? ' <span class="pill">E</span>' : ""}</th>`).join("")}</tr></thead><tbody>
      <tr><td>매출액</td>${ks.map((k) => `<td>${eok(Q[k].revenue)}</td>`).join("")}</tr>
      <tr><td>영업이익</td>${ks.map((k) => `<td>${eok(Q[k].op_income)}</td>`).join("")}</tr></tbody></table>
      <p class="tiny muted" style="margin:8px 0 0">최근 분기 영업이익 YoY ${sgn(s.q_op_yoy, 0)} · QoQ ${sgn(s.q_op_qoq, 0)}</p></div>`;
  }

  function planHtml(s, pl) {
    const st = DATA.meta.config.strategy;
    const fr = (f) => Math.round(f * 100) + "%";
    const rel = (p) => (isNum(p) && isNum(s.price) ? sgn((p / s.price - 1) * 100, 1) : "");
    const notBuy = s.score.grade === "red" || s.score.grade === "white";
    return `${notBuy ? `<div class="banner" style="margin:0 0 10px">현재 등급(${gradeShort[s.score.grade]})에서는 신규 매수를 권하지 않습니다. 아래 가격은 등급이 오를 때 참고용입니다.</div>` : ""}
      <div class="plan-steps">${pl.entries.map((e) => `<div class="step"><div class="k">${e.step}차 매수 · ${fr(e.fraction)}</div>
        <div class="v">${won(e.price)}</div><div class="x">${esc(e.basis)} ${rel(e.price)}</div></div>`).join("")}</div>
      <table class="mini" style="margin-top:12px"><tbody>
        <tr><td>평균 진입가(예상)</td><td>${won(pl.avg_entry)}</td><td class="muted small">3회 모두 체결 시</td></tr>
        <tr><td><b>손절</b></td><td class="down"><b>${won(pl.stop)}</b> ${rel(pl.stop)}</td><td class="muted small">${esc(pl.stop_basis)} · 또는 투자 논리 훼손 시 즉시</td></tr>
        <tr><td><b>1차 익절</b></td><td class="up"><b>${won(pl.tp1)}</b> ${rel(pl.tp1)}</td><td class="muted small">${pl.tp1 ? `목표가까지 상승여력의 ${Math.round(st.take_profit_1_progress * 100)}% 도달 → 보유분 ${Math.round(st.take_profit_1_fraction * 100)}% 매도` : esc(pl.note || "")}</td></tr>
        <tr><td><b>2차 익절</b></td><td class="up"><b>${won(pl.tp2)}</b> ${rel(pl.tp2)}</td><td class="muted small">목표가 도달 → 잔량 대부분 매도, 일부는 추적 손절로 보유</td></tr>
        <tr><td>추적 손절</td><td>고점 대비 ${pl.trailing_pct}%</td><td class="muted small">1차 익절 이후 종가 기준 최고가에서 적용</td></tr>
      </tbody></table>`;
  }

  // ------------------------------------------------------------ 차트(SVG 캔들)
  function drawChart(box, rows, s) {
    if (!rows || !rows.length) { box.innerHTML = '<p class="muted small">차트 데이터 N/A</p>'; return; }
    const W = Math.max(340, Math.round(box.clientWidth || 900)), H = W < 600 ? 250 : 330;
    const padL = 6, padR = 58, padT = 12, padB = 26;
    const lines = [];
    if (isNum(s.target)) lines.push([s.target, "#2fca73", "6 4", "목표"]);
    if (s.plan) {
      s.plan.entries.forEach((e) => lines.push([e.price, "#d1d6db", "", `${e.step}차`]));
      lines.push([s.plan.stop, "#8fb8ff", "6 4", "손절"]);
    }
    const hi = Math.max(...rows.map((r) => r[2])), lo = Math.min(...rows.map((r) => r[3]));
    lines.push([hi, "#6b7280", "2 3", "52주 고"], [lo, "#6b7280", "2 3", "52주 저"]);
    const all = [hi, lo, ...lines.map((l) => l[0]).filter(isNum)];
    let ymax = Math.max(...all), ymin = Math.min(...all);
    const pad = (ymax - ymin) * 0.05; ymax += pad; ymin -= pad;
    const n = rows.length, cw = (W - padL - padR) / n;
    const X = (i) => padL + cw * (i + 0.5);
    const VH = Math.round(H * 0.16);
    const Y = (v) => padT + (H - padT - padB - VH - 4) * (1 - (v - ymin) / (ymax - ymin));
    let g = "";
    // 거래량 막대(하단)
    const vmax = Math.max(...rows.map((r) => r[5] || 0)) || 1;
    rows.forEach((r, i) => {
      const vh = ((r[5] || 0) / vmax) * VH, up = r[4] >= r[1];
      g += `<rect x="${X(i) - Math.max(1, cw * 0.62) / 2}" y="${H - padB - vh}" width="${Math.max(1, cw * 0.62)}" height="${vh}" fill="${up ? "#f04452" : "#3182f6"}" opacity=".35"/>`;
    });
    // 격자
    for (let k = 0; k <= 4; k++) {
      const v = ymin + ((ymax - ymin) * k) / 4, y = Y(v);
      g += `<line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" stroke="#25252c"/><text x="${W - padR + 6}" y="${y + 4}" font-size="11" fill="#7d818b">${Math.round(v).toLocaleString("ko-KR")}</text>`;
    }
    // 월 라벨
    let lastM = "";
    rows.forEach((r, i) => {
      const m = r[0].slice(0, 7);
      if (m !== lastM && i > 3 && (W >= 600 || +m.slice(5) % 2 === 1)) g += `<text x="${X(i)}" y="${H - 8}" font-size="11" fill="#7d818b" text-anchor="middle">${m.slice(2).replace("-", ".")}</text>`;
      lastM = m;
    });
    // 캔들
    rows.forEach((r, i) => {
      const [, o, h, l, c] = r, up = c >= o, col = up ? "#f04452" : "#3182f6";
      const x = X(i), bw = Math.max(1, cw * 0.62);
      g += `<line x1="${x}" x2="${x}" y1="${Y(h)}" y2="${Y(l)}" stroke="${col}" stroke-width="1"/>`;
      const y1 = Y(Math.max(o, c)), y2 = Y(Math.min(o, c));
      g += `<rect x="${x - bw / 2}" y="${y1}" width="${bw}" height="${Math.max(1, y2 - y1)}" fill="${col}"/>`;
    });
    // 기준선
    // 기준선 + 라벨(겹치지 않게 세로로 밀어냄)
    const labs = [];
    lines.forEach(([v, col, dash, lab]) => {
      if (!isNum(v)) return;
      const y = Y(v);
      g += `<line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="1.2" ${dash ? `stroke-dasharray="${dash}"` : ""} opacity=".85"/>`;
      labs.push({ y: y - 3, col, t: `${lab} ${Math.round(v).toLocaleString("ko-KR")}` });
    });
    labs.sort((a, b) => a.y - b.y);
    if (labs.length) labs[0].y = Math.max(labs[0].y, padT + 9);
    for (let k = 1; k < labs.length; k++) if (labs[k].y < labs[k - 1].y + 12) labs[k].y = labs[k - 1].y + 12;
    const over = labs.length ? labs[labs.length - 1].y - (H - padB - VH - 6) : 0;
    if (over > 0) labs.forEach((l) => (l.y -= over));
    labs.forEach((l) => { g += `<text x="${padL + 4}" y="${l.y}" font-size="10.5" fill="${l.col}" paint-order="stroke" stroke="#1c1c21" stroke-width="3">${l.t}</text>`; });
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="52주 일봉 차트">${g}<line id="xh" y1="${padT}" y2="${H - padB}" stroke="#d1d6db" stroke-width=".6" opacity="0"/></svg><div class="tip" id="tip"></div>`;
    const svg = box.querySelector("svg"), tip = box.querySelector("#tip"), xh = box.querySelector("#xh");
    const move = (ev) => {
      const pt = ev.touches ? ev.touches[0] : ev;
      const rc = svg.getBoundingClientRect();
      const sx = ((pt.clientX - rc.left) / rc.width) * W;
      const i = Math.max(0, Math.min(n - 1, Math.floor((sx - padL) / cw)));
      const r = rows[i];
      xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i)); xh.setAttribute("opacity", ".5");
      const prev = i > 0 ? rows[i - 1][4] : r[1];
      const ch = (r[4] / prev - 1) * 100;
      tip.innerHTML = `${r[0]}<br>시 ${Math.round(r[1]).toLocaleString()} 고 ${Math.round(r[2]).toLocaleString()}<br>저 ${Math.round(r[3]).toLocaleString()} 종 <b>${Math.round(r[4]).toLocaleString()}</b> (${ch >= 0 ? "+" : ""}${ch.toFixed(2)}%)<br>거래량 ${Math.round(r[5] || 0).toLocaleString()}`;
      tip.style.display = "block";
      const left = ((X(i) / W) * rc.width);
      tip.style.left = Math.min(rc.width - tip.offsetWidth - 4, Math.max(4, left + 10)) + "px";
      tip.style.top = "6px";
    };
    svg.addEventListener("mousemove", move);
    svg.addEventListener("touchmove", move, { passive: true });
    svg.addEventListener("mouseleave", () => { tip.style.display = "none"; xh.setAttribute("opacity", "0"); });
  }


  // ------------------------------------------------------------ 마켓맵
  const MAP = { market: "코스피", period: "change_pct", color: "change", sel: null };
  const PERIODS = [["change_pct", "1일", 3], ["ret_1w", "1주", 7], ["ret_1m", "1개월", 12], ["ret_3m", "3개월", 25], ["ret_6m", "6개월", 40], ["ret_12m", "1년", 60]];

  function renderMap() {
    const seg = (arr, cur, key) => arr.map(([v, l]) => `<button class="sg ${cur === v ? "on" : ""}" data-${key}="${v}">${l}</button>`).join("");
    $app.innerHTML = `<div class="sec-h"><h2>마켓맵</h2><span class="muted small">크기 = 시가총액 · 색 = ${MAP.color === "change" ? "등락률" : "매수 점수"} · 분석 대상 ${n0(DATA.stocks.length)}종목</span></div>
      <div class="mapbar">
        <div class="segs big">${seg([["코스피", "코스피"], ["코스닥", "코스닥"], ["전체", "전체"]], MAP.market, "mk")}</div>
        <div class="segs">${seg(PERIODS.map(([k, l]) => [k, l]), MAP.period, "pd")}</div>
        <div class="segs">${seg([["change", "등락률"], ["score", "매수 점수"]], MAP.color, "cl")}</div>
      </div>
      <div class="mapwrap"><div class="tmap" id="tmap"></div></div>
      <div class="maplegend" id="mlegend"></div>
      <div class="grid2" style="margin-top:14px">
        <div class="card sec"><h2>업종별 등락 <span class="muted" id="sbt"></span></h2><div id="secbars"></div></div>
        <div class="card sec"><h2>시장 체온 <span class="muted">상승·하락 종목 수 · 등급 분포</span></h2><div id="breadth"></div></div>
      </div>`;
    $app.querySelectorAll("[data-mk]").forEach((b) => b.addEventListener("click", () => { MAP.market = b.dataset.mk; renderMap(); }));
    $app.querySelectorAll("[data-pd]").forEach((b) => b.addEventListener("click", () => { MAP.period = b.dataset.pd; renderMap(); }));
    $app.querySelectorAll("[data-cl]").forEach((b) => b.addEventListener("click", () => { MAP.color = b.dataset.cl; renderMap(); }));
    drawMap();
  }

  function mapStocks() {
    return DATA.stocks.filter((s) => (MAP.market === "전체" || s.market === MAP.market) && isNum(s.mcap_eok) && s.mcap_eok > 0);
  }

  function drawMap() {
    const box = document.getElementById("tmap");
    if (!box) return;
    const L = mapStocks(), pd = PERIODS.find((p) => p[0] === MAP.period), range = pd[2];
    const W = box.clientWidth, mobile = W < 700, H = mobile ? Math.round(W * 1.5) : Math.min(720, Math.round(W * 0.58));
    box.style.height = H + "px";
    const val = (s) => s[MAP.period];
    const colorOf = (s) => (MAP.color === "change" ? Viz.changeColor(val(s), range) : Viz.scoreColor(s.score.total));
    const groups = {};
    L.forEach((s) => (groups[s.sector] = groups[s.sector] || []).push(s));
    const secs = Object.entries(groups).map(([name, arr]) => ({ name, arr: arr.sort((a, b) => b.mcap_eok - a.mcap_eok), value: arr.reduce((a, s) => a + s.mcap_eok, 0) }))
      .sort((a, b) => b.value - a.value);
    const rects = Viz.squarify(secs, 0, 0, W, H);
    let html = "";
    rects.forEach(({ item: sec, x, y, w, h }) => {
      const head = w > 54 && h > 46 ? 17 : 0;
      html += `<div class="tsec" style="left:${x}px;top:${y}px;width:${w}px;height:${h}px" data-sec="${esc(sec.name)}">${head ? `<div class="tsh">${esc(sec.name)}</div>` : ""}</div>`;
      Viz.squarify(sec.arr.map((s) => ({ ...s, value: s.mcap_eok })), x + 1, y + head + 1, w - 2, h - head - 2).forEach(({ item: s, x: tx, y: ty, w: tw, h: th }) => {
        const area = tw * th, fs = Math.max(9, Math.min(34, Math.sqrt(area) / 5.2));
        const showName = tw > 34 && th > 20, showPct = th > fs * 2.3 && tw > 30;
        const v = MAP.color === "change" ? val(s) : s.score.total;
        const lab = MAP.color === "change" ? (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}%` : "–") : (isNum(v) ? `${v.toFixed(0)}점` : "–");
        html += `<a class="tile ${MAP.sel === s.code ? "sel" : ""}" href="#/stock/${esc(s.code)}" data-code="${esc(s.code)}"
          style="left:${tx}px;top:${ty}px;width:${Math.max(0, tw - 1)}px;height:${Math.max(0, th - 1)}px;background:${colorOf(s)}">
          ${showName ? `<span class="tn" style="font-size:${fs}px">${esc(s.name)}</span>` : ""}${showPct ? `<span class="tp" style="font-size:${Math.max(9, fs * 0.72)}px">${lab}</span>` : ""}</a>`;
      });
    });
    box.innerHTML = html;
    const by = Object.fromEntries(L.map((s) => [s.code, s]));
    const tipHtml = (s) => {
      const v = val(s), sc = s.score;
      return `<div class="tt-h"><b>${esc(s.name)}</b><span class="tmuted">${esc(s.sector)} · ${esc(s.code)}</span></div>
        <div class="tt-p"><b>${won(s.price)}</b> ${sgn(s.change_pct, 2)}</div>
        ${Viz.sparkline(s.spark, 200, 44)}
        <div class="tt-g"><span>${pd[1]} ${sgn(v, 2)}</span><span>시총 ${eok(s.mcap_eok)}</span></div>
        <div class="tt-g"><span class="g g-${sc.grade}">${sc.grade_emoji} ${esc(sc.grade_label)}</span><span>총점 <b>${isNum(sc.total) ? sc.total.toFixed(0) : "N/A"}</b> · 업사이드 ${sgn(sc.upside_pct, 0)}</span></div>
        <div class="tmuted tt-r">${esc(sc.reason)}</div><div class="tmuted tt-c">${matchMedia("(hover: none)").matches ? "한 번 더 누르면 상세" : "클릭하면 상세"}</div>`;
    };
    box.onmousemove = (e) => {
      const t = e.target.closest(".tile");
      box.querySelectorAll(".tile.hov").forEach((x) => x !== t && x.classList.remove("hov"));
      box.querySelectorAll(".tsec.hov").forEach((x) => x.classList.remove("hov"));
      if (!t) { Viz.Tip.hide(); box.classList.remove("dim"); return; }
      t.classList.add("hov"); box.classList.add("dim");
      const sec = [...box.querySelectorAll(".tsec")].find((el) => el.dataset.sec === by[t.dataset.code].sector);
      if (sec) sec.classList.add("hov");
      Viz.Tip.show(e.clientX, e.clientY, tipHtml(by[t.dataset.code]));
    };
    box.onmouseleave = () => { Viz.Tip.hide(); box.classList.remove("dim"); box.querySelectorAll(".hov").forEach((x) => x.classList.remove("hov")); };
    box.onclick = (e) => {
      const t = e.target.closest(".tile");
      if (!t) return;
      if (matchMedia("(hover: none)").matches && MAP.sel !== t.dataset.code) {
        e.preventDefault(); MAP.sel = t.dataset.code;
        box.querySelectorAll(".tile.sel").forEach((x) => x.classList.remove("sel")); t.classList.add("sel");
        const r = t.getBoundingClientRect(); Viz.Tip.show(r.left + r.width / 2, r.top + r.height / 2, tipHtml(by[t.dataset.code]));
      }
    };
    // 범례
    const steps = [-1, -0.66, -0.33, 0, 0.33, 0.66, 1];
    document.getElementById("mlegend").innerHTML = MAP.color === "change"
      ? steps.map((k) => `<span style="background:${Viz.changeColor(k * range, range)}">${k === 0 ? "0%" : (k > 0 ? "+" : "") + (k * range).toFixed(range < 10 ? 1 : 0) + "%"}</span>`).join("")
      : [20, 35, 45, 55, 65, 75, 90].map((v) => `<span style="background:${Viz.scoreColor(v)}">${v}점</span>`).join("");
    // 업종별 등락 (시총 가중)
    const sa = secs.map((sc) => {
      const vs = sc.arr.filter((s) => isNum(val(s)));
      const wsum = vs.reduce((a, s) => a + s.mcap_eok, 0);
      return { name: sc.name, n: sc.arr.length, v: wsum ? vs.reduce((a, s) => a + val(s) * s.mcap_eok, 0) / wsum : null };
    }).filter((x) => isNum(x.v)).sort((a, b) => b.v - a.v);
    const mx = Math.max(1, ...sa.map((x) => Math.abs(x.v)));
    const show = sa.length > 16 ? [...sa.slice(0, 8), null, ...sa.slice(-8)] : sa;
    document.getElementById("sbt").textContent = `${pd[1]} · 시총 가중 · 상위·하위 8개`;
    document.getElementById("secbars").innerHTML = show.map((x) => x === null ? `<div class="sbsep">⋯</div>` :
      `<div class="sbr" data-tip="${esc(x.name)} ${x.n}종목 · ${x.v > 0 ? "+" : ""}${x.v.toFixed(2)}%"><span class="sbn">${esc(x.name)}</span>
        <div class="sbt"><div class="sbh neg">${x.v < 0 ? `<i style="width:${(-x.v / mx) * 100}%"></i>` : ""}</div><div class="sbh pos">${x.v > 0 ? `<i style="width:${(x.v / mx) * 100}%"></i>` : ""}</div></div>
        <b class="${x.v > 0 ? "up" : x.v < 0 ? "down" : ""}">${x.v > 0 ? "+" : ""}${x.v.toFixed(1)}%</b></div>`).join("");
    // 시장 체온
    const upN = L.filter((s) => val(s) > 0).length, dnN = L.filter((s) => val(s) < 0).length, flat = L.length - upN - dnN;
    const gc = { green: 0, yellow: 0, white: 0, red: 0 };
    L.forEach((s) => gc[s.score.grade]++);
    const gcol = { green: "#2fca73", yellow: "#ffc342", white: "#6b7280", red: "#ff6b6b" };
    document.getElementById("breadth").innerHTML = `
      <div class="bth"><span class="up">상승 <b>${upN}</b></span><span class="muted">보합 ${flat}</span><span class="down">하락 <b>${dnN}</b></span></div>
      <div class="gstack big"><i style="flex:${upN || 0.01};background:${Viz.UP}" data-tip="상승 ${upN}"></i><i style="flex:${flat || 0.01};background:#4e5968" data-tip="보합 ${flat}"></i><i style="flex:${dnN || 0.01};background:${Viz.DOWN}" data-tip="하락 ${dnN}"></i></div>
      <div class="bth" style="margin-top:18px"><span>매수 등급 (${esc(MAP.market)})</span></div>
      <div class="gstack big">${Object.keys(gc).map((g) => `<i style="flex:${gc[g] || 0.01};background:${gcol[g]}" data-tip="${gradeShort[g]} ${gc[g]}"></i>`).join("")}</div>
      <div class="glegend">${Object.keys(gc).map((g) => `<span><i style="background:${gcol[g]}"></i>${gradeShort[g].split(" ")[1]} <b>${gc[g]}</b></span>`).join("")}</div>
      <div class="hs" style="margin-top:14px">${pd[1]} 기준 ${upN > dnN ? "상승 종목이 더 많습니다" : upN < dnN ? "하락 종목이 더 많습니다" : "상승·하락이 비슷합니다"} (상승 비율 ${L.length ? ((upN / L.length) * 100).toFixed(0) : 0}%).</div>`;
  }
  let _rz;
  window.addEventListener("resize", () => { clearTimeout(_rz); _rz = setTimeout(() => { if ((location.hash || "").startsWith("#/map")) drawMap(); }, 150); });

  // ------------------------------------------------------------ 업종
  function renderSectors() {
    const secs = Object.entries(DATA.sectors).sort((a, b) => b[1].n - a[1].n || a[0].localeCompare(b[0], "ko"));
    const bySec = {};
    DATA.stocks.forEach((s) => (bySec[s.sector] = bySec[s.sector] || []).push(s));
    $app.innerHTML = `<h1 class="page">업종 뷰</h1>
      <p class="small muted" style="margin:4px 0 0">네이버 업종 분류 기준. PER·PBR 중앙값(평균)은 양수인 종목만으로 계산하며, 각 종목의 밸류에이션 비교 기준이 됩니다.</p>
      <div class="secgrid">${secs.map(([name, st]) => {
        const L = (bySec[name] || []).sort((a, b) => a.rank - b.rank);
        const g = L.filter((s) => s.score.grade === "green").length;
        return `<div class="card"><h3>${esc(name)} <span class="tiny muted">${st.n}종목 · 🟢 ${g}</span></h3>
          <div class="kv"><div><div class="k">PER 중앙값 (평균)</div><div class="v">${x1(st.per_median)} <span class="tiny muted">(${x1(st.per_mean)})</span></div></div>
            <div><div class="k">PBR 중앙값 (평균)</div><div class="v">${x1(st.pbr_median, "배")} <span class="tiny muted">(${x1(st.pbr_mean, "배")})</span></div></div></div>
          ${L.slice(0, 5).map((s) => `<a class="mrow" href="#/stock/${esc(s.code)}"><span><b>${esc(s.name)}</b> <span class="tiny muted">${s.rank}위</span></span>
            <span>${gradeShort[s.score.grade]} · 업사이드 ${sgn(s.score.upside_pct, 0)}</span></a>`).join("")}
          ${L.length > 5 ? `<a class="mrow more-s" href="#/" data-sector="${esc(name)}"><span class="muted">전체 ${L.length}종목 보기 →</span><span></span></a>` : ""}
        </div>`;
      }).join("")}</div>`;
    $app.querySelectorAll("[data-sector]").forEach((a) => a.addEventListener("click", () => {
      state.sector = a.dataset.sector; state.jumpAll = true;
    }));
  }

  // ------------------------------------------------------------ 매매 원칙
  function renderRules() {
    const C = DATA.meta.config, st = C.strategy, cs = C.cash, gr = C.grades, w = C.weights, rk = C.risk, tg = C.target, q = C.quality, al = C.alpha;
    const u = DATA.meta.universe || {}, f = u.filters || {}, csat = st.core_satellite;
    const steps = st.entry_steps_pct.map((p, i) => `${i + 1}차 ${p === 0 ? "현재가" : `현재가 ${p}%`} (${Math.round(st.entry_split[i] * 100)}%)`).join(" → ");
    $app.innerHTML = `<div class="rules"><h1 class="page" style="margin-bottom:12px">투자 전략 · 매매 원칙</h1>
      <div class="card"><h2>🧭 종목 선정 프로세스</h2><ol class="olist">
        <li><b>유니버스</b> — 코스피·코스닥 ${n0(u.listed)}개 중 시총 ${n0(f.min_mcap_eok)}억↑ · 거래대금 ${n0((f.min_trade_value_mil || 0) / 100)}억↑ 보통주 ${n0(u.analyzed)}개 (+모임 발표 종목)</li>
        <li><b>퀄리티 체크</b>(가치 함정 회피) — 적자, ROE &lt; ${q.min_roe}%, 부채비율 &gt; ${q.max_debt_ratio}%(금융 제외), 잠재 희석 ≥ ${q.max_dilution_pct}% — 걸린 항목당 <b>−${q.penalty_per_fail}점</b>(최대 −${q.penalty_max})</li>
        <li><b>가치</b> — 보수적 내재가치(예상 EPS × (1−${tg.intrinsic_eps_haircut * 100}%) × 업종 중앙 PER) 대비 <b>안전마진</b>, 업종 대비 PER·PBR, Forward PER</li>
        <li><b>알파</b> — ① 실적 서프라이즈(분기 영업이익 vs 발표 직전 컨센서스) ② 신규 수주(최근 ${al.orders_months}개월 단일판매·공급계약 공시, 매출 대비 %) ③ 컨센서스 EPS 상향</li>
        <li><b>성장</b> — 예상 EPS·영업이익 성장률 (PER이 높더라도 이익 성장이 나오는 종목)</li>
        <li><b>가격·위험</b> — 52주 위치, 3개월 수익률, <b>저변동성</b>(책의 저변동성 투자). 3개월 ${C.falling_knife.ret_3m_pct}% 이하 + 200일선 아래 + 컨센서스 상향 없음 = 하락 추세 <b>−${C.falling_knife.penalty_points}점</b> (싸면 여전히 상위 가능)</li>
        <li><b>리스크 감점</b> — 희석·부채·모임 메모 키워드 (최대 ${rk.max_total}점)</li>
        <li><b>순위는 순수 총점순</b> · 등급 정원 🟢 ${gr.max_green}개, 🟡 ${gr.max_yellow}개 (현재가 ≥ 보수적 목표가면 🔴 표시)</li></ol></div>
      <div class="card"><h2>🎯 보수적 목표가</h2><ul>
        <li>목표가 = <b>min(컨센서스 × ${tg.consensus_haircut}, 보수적 내재가치)</b> — 증권사 낙관 편향과 이익 추정 오차를 모두 할인</li>
        <li>컨센서스가 없으면 내재가치만 사용(현재가 +${tg.model_max_upside_pct}% 상한)</li>
        <li>업사이드 0% 이하 → 🔴, +${C.upside.best_pct}% 이상이어야 만점 · 데이터가 없는 항목은 ${C.missing_component_score}점(보수적)으로 계산</li>
        <li>종목 상세의 <b>밸류에이션 민감도</b> 표: EPS ${tg.sensitivity_eps_cuts.join("·")}% × PER(업종의 ${tg.sensitivity_per_mults.join("·")}배)</li></ul></div>
      <div class="card"><h2>📚 전략적 가치투자에서 가져온 전략</h2><ul>
        <li><b>가치투자</b> — 내재가치보다 싸면 사고 비싸면 판다: 안전마진·업종 대비 할인이 점수의 중심(가치 ${w.value} + 업사이드 ${w.upside})</li>
        <li><b>저변동성</b> — 같은 조건이면 변동성이 낮은 종목을 우대(가격·위험 항목의 ${Math.round(C.price_risk.sub_weights.low_volatility * 100)}%)</li>
        <li><b>성장투자</b> — 이익이 늘어나는 기업(성장 ${w.growth})과 실적·수주 알파(${w.alpha})</li>
        <li><b>가치 가중</b> — 비중 ∝ 총점 × (1 + 안전마진) ÷ 변동성, 한 종목 최대 ${st.max_weight_pct}%</li>
        <li><b>코어 & 새틀라이트</b> — 코어 최대 ${csat.core_size}종목(시총 ${n0(csat.core_min_mcap_eok / 10000)}조↑·퀄리티 통과)에 주식 몫의 ${Math.round(csat.core_ratio * 100)}%, 한 종목 최대 ${st.max_weight_pct}% · 새틀라이트(중소형) 최대 ${csat.satellite_size}종목에 ${Math.round((1 - csat.core_ratio) * 100)}%, 한 종목 최대 ${csat.satellite_max_weight_pct}% — 단 🟢·총점 ${csat.boost_score}점↑ '진짜 개꿀'이면 ${Math.round(csat.boost_ratio * 100)}%·종목당 ${csat.boost_max_weight_pct}%까지 · 상한으로 남는 주식 몫은 지수 ETF</li>
        <li><b>정률투자</b> — 기본 주식 ${100 - cs.base_pct} : 현금 ${cs.base_pct}, 권장 비중에서 ±${cs.rebalance_band_pct}%p 벗어나면 리밸런싱</li>
        <li><b>주식 외 자산(현금 몫)은 놀리지 않기</b> — 분할매수 2·3차 대기 자금은 CMA·파킹통장(바로 인출), 나머지는 단기채·금리형 ETF(KOFR·CD금리, 매일 이자) ${Math.round(cs.parking.base_split.short_bond * 100)}% · 국채 ETF ${Math.round(cs.parking.base_split.gov_bond * 100)}% · 현금성 ${Math.round(cs.parking.base_split.cash * 100)}% (한국 10년물 ${cs.parking.duration_kr10y}%↑이면 국채 비중 확대)</li>
        <li><b>절대모멘텀</b> — 코스피 12개월 수익률이 마이너스면 현금 +${cs.abs_momentum_adj}%p</li></ul></div>
      <div class="card"><h2>⚠️ 불안요소(매크로) 체크</h2><ul>
        <li>하이일드 스프레드 ≥ ${cs.macro.hy_spread_high}% → 현금 +${cs.macro.hy_spread_high_adj}%p, 1개월 +${cs.macro.hy_spread_jump}%p 이상 확대 → +${cs.macro.hy_spread_jump_adj}%p</li>
        <li>미국 10년물 ≥ ${cs.macro.us10y_high}% → +${cs.macro.us10y_high_adj}%p (높은 할인율은 성장 기대의 주가 반영을 제약)</li>
        <li>코스피 ${cs.ma_short}·${cs.ma_long}일선: 모두 위 ${cs.trend_adj.above_both}%p / 혼조 ${cs.trend_adj.mixed}%p / 모두 아래 +${cs.trend_adj.below_both}%p</li>
        <li>직접 확인: 자회사 IPO·블록딜 오버행, 레버리지 ETF 쏠림·개인 본전 심리, 장비사·IDM 컨퍼런스콜(CAPEX)</li>
        <li>현재 권장 현금 <b>${DATA.meta.cash.cash_pct}%</b> — ${(DATA.meta.cash.steps || []).map((x) => esc(x.label) + " " + (x.adj > 0 ? "+" : "") + x.adj).join(" · ")}</li></ul></div>
      <div class="card"><h2>📈 매매 원칙</h2><ul>
        <li>진입: ${steps} (내려갈수록 많이) · 2·3차는 ±${st.support_snap_pct}% 안의 ${st.support_lookbacks.join("·")}일 저점(지지선)에 맞춤</li>
        <li>손절: 평균 진입가 ${st.stop_loss_pct}% 또는 지지선 ${st.stop_below_support_pct}% 이탈 중 먼저 닿는 가격 · 투자 논리 훼손 시 즉시</li>
        <li>익절: 목표가까지 상승여력의 ${Math.round(st.take_profit_1_progress * 100)}% → ${Math.round(st.take_profit_1_fraction * 100)}% 매도, 목표가 도달 → 잔량 대부분, 이후 고점 대비 ${st.trailing_stop_pct}% 추적 손절</li>
        <li>등급: 🟢 ${gr.green}점↑ 분할매수 실행 · 🟡 ${gr.yellow}점↑ 절반 비중 · ⚪ ${gr.white}점↑ 보류 · 🔴 매수 금지</li>
        <li>점수는 기계적 참고 지표입니다. 최종 판단과 책임은 각자에게 있습니다.</li></ul></div>
    </div>`;
  }

  // ------------------------------------------------------------ 라우터
  function setNav(k) {
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === k));
  }
  function route() {
    const h = location.hash || "#/";
    $status.style.display = h === "#/" || h === "#" || h === "" ? "" : "none";
    Viz.Tip.hide();
    const m = h.match(/^#\/stock\/([0-9A-Z]{6})/);
    if (!state.jumpAll) window.scrollTo(0, 0);
    if (m) { setNav("rank"); renderStock(m[1]); return; }
    if (h.startsWith("#/sectors")) { setNav("sectors"); renderSectors(); return; }
    if (h.startsWith("#/map")) { setNav("map"); renderMap(); return; }
    if (h.startsWith("#/rules")) { setNav("rules"); renderRules(); return; }
    setNav("rank");
    renderRank();
  }

  load().then((ok) => {
    if (!ok) return;
    renderStatus();
    window.addEventListener("hashchange", route);
    route();
  });
})();
