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
  const tlabel = (src) => ({ "컨센서스": "컨센서스 목표가", "모델 적정가": "모델 적정가", "모임": "모임 목표가" }[src] || "목표가");
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
    const m = DATA.meta, c = m.cash || {}, gc = m.grade_counts || {}, mk = m.market, u = m.universe || {};
    const trendCls = c.trend_state === "above_both" ? "up" : c.trend_state === "below_both" ? "down" : "";
    let warn = "";
    if (m.demo) warn += `<div class="banner err">⚠️ 화면 확인용 <b>데모 데이터</b>입니다. 실제 시세가 아닙니다.</div>`;
    if (!m.dart_enabled) warn += `<div class="banner">DART API 키가 없어 희석 물량·대주주 지분은 N/A로 표시됩니다.</div>`;
    const cp = isNum(c.cash_pct) ? c.cash_pct : null;
    $status.innerHTML = `<div class="hero">
      <div><div class="k">권장 현금 비중</div><div class="v">${cp !== null ? cp.toFixed(0) + "%" : "N/A"}</div>
        <div class="cashbar"><i style="width:${cp ?? 0}%"></i></div>
        <div class="s">주식 ${cp !== null ? (100 - cp).toFixed(0) : "-"}% (상위 ${c.portfolio_size ?? "-"}종목) · 현금 ${cp !== null ? cp.toFixed(0) : "-"}%</div></div>
      <div><div class="k">코스피</div><div class="v">${mk ? n0(mk.last) : "N/A"}</div>
        <div class="s ${trendCls}">${esc((c.trend_desc || "").replace("코스피 ", ""))}</div></div>
      <div><div class="k">분석 종목</div><div class="v">${n0(u.analyzed)}<span class="unit">개</span></div>
        <div class="s">코스피·코스닥 ${n0(u.listed)}개 중 · ${esc(String(m.generated_at || "").replace(" KST", ""))} 갱신</div></div>
      <div><div class="k">등급 분포</div><div class="gcounts">
        ${["green", "yellow", "white", "red"].map((g) => `<span class="g g-${g}">${gradeShort[g]} ${gc[g] ?? 0}</span>`).join("")}</div></div>
    </div>${warn}`;
  }

  // ------------------------------------------------------------ TOP 픽 카드
  function pickCard(s) {
    const sc = s.score, t = s.thesis || {}, pl = s.plan || {};
    return `<article class="pick" data-code="${esc(s.code)}">
      <header class="pick-h">
        <div class="pick-title"><span class="rkb">${s.rank}</span>
          <div><h3>${esc(s.name)} ${clubTag(s)}</h3><div class="tiny muted">${esc(s.code)} · ${esc(s.market || "")}</div></div></div>
        <div class="pick-price"><b>${won(s.price)}</b><span class="tiny">${sgn(s.change_pct, 2)}</span></div>
      </header>
      <div class="pick-verdict">${gradeBadge(s)}<span class="score-big">${isNum(sc.total) ? sc.total.toFixed(0) : "N/A"}<small>점</small></span>
        <span class="tiny muted">${esc(sc.reason)}</span></div>
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
  const COLS = [["rank", "순위", "l"], ["name", "종목", "l"], ["grade", "등급", "l"], ["total", "총점"], ["price", "현재가"],
    ["upside", "업사이드"], ["per", "PER"], ["pbr", "PBR"], ["fwd_per", "Fwd PER"], ["mcap", "시총"], ["reason", "판단 근거", "l"]];
  const gOrder = { green: 0, yellow: 1, white: 2, red: 3 };
  const sortVal = {
    rank: (s) => s.rank, name: (s) => s.name, grade: (s) => gOrder[s.score.grade] * 1000 - (s.score.total ?? 0),
    total: (s) => s.score.total, price: (s) => s.price, upside: (s) => s.score.upside_pct, per: (s) => s.per,
    pbr: (s) => s.pbr, fwd_per: (s) => s.fwd_per, mcap: (s) => s.mcap_eok, reason: (s) => s.score.reason,
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
      <div class="sec-h"><h2>오늘의 TOP ${picks.length} 픽</h2><span class="muted small">점수 상위 🟢·🟡 종목 · 카드를 누르면 상세</span></div>
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
      <p class="tiny muted">목표가 = 증권사 컨센서스 → 없으면 모델 적정가(업종 중앙 PER × 예상 EPS × ${DATA.meta.config.target.model_haircut}) → 모임 목표가 순.
        업사이드 = (목표가 − 현재가) ÷ 현재가.</p>`;
    $app.querySelectorAll(".pick").forEach((el) => el.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      location.hash = `#/stock/${el.dataset.code}`;
    }));
    const draw = () => {
      const L = filtered();
      const V = L.slice(0, state.shown);
      document.getElementById("count").textContent = `${L.length}종목 중 ${V.length}개 표시`;
      document.getElementById("tb").innerHTML = V.map(rowHtml).join("") || `<tr><td colspan="11" class="l muted">조건에 맞는 종목이 없습니다.</td></tr>`;
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

  function rowHtml(s) {
    const sc = s.score;
    return `<tr data-code="${esc(s.code)}">
      <td class="l rk ${s.rank <= 3 ? "rk1" : ""}">${s.rank}</td>
      <td class="l nm">${esc(s.name)} ${clubTag(s)}<small>${esc(s.code)} · ${esc(s.sector)}</small></td>
      <td class="l">${gradeBadge(s)}</td>
      <td><span class="score"><b>${isNum(sc.total) ? sc.total.toFixed(0) : "N/A"}</b>${bar(sc.total)}</span></td>
      <td>${won(s.price)}<div class="tiny">${sgn(s.change_pct, 2)}</div></td>
      <td>${sgn(sc.upside_pct, 0)}<div class="tiny muted">${esc(s.target_source || "")}</div></td>
      <td>${perf(s.per)}</td><td>${x1(s.pbr, "")}</td><td>${perf(s.fwd_per)}</td><td>${eok(s.mcap_eok)}</td>
      <td class="reason">${esc(sc.reason)}</td></tr>`;
  }

  function cardHtml(s) {
    const sc = s.score;
    return `<a class="mcard" href="#/stock/${esc(s.code)}">
      <div class="mrow"><div class="mname"><span class="rk ${s.rank <= 3 ? "rk1" : ""}">${s.rank}</span>
          <div><b>${esc(s.name)}</b><span class="tiny">${esc(s.sector)} · ${esc(s.code)}</span></div></div>
        <div class="mprice"><b>${won(s.price)}</b><span class="tiny">${sgn(s.change_pct, 2)}</span></div></div>
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
        <div class="verdict">${gradeBadge(s)}<span class="tot">${isNum(sc.total) ? sc.total.toFixed(1) : "N/A"}점</span><span class="why">${esc(sc.reason)}</span></div>
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
          ${dil?.events?.length ? `<table class="mini" style="margin-top:8px"><thead><tr><th>공시일</th><th>종류</th><th>주식총수 대비</th></tr></thead><tbody>
            ${dil.events.slice(0, 6).map((e) => `<tr><td><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${esc(e.rcept_no)}" target="_blank" rel="noopener">${esc(e.date)}</a></td><td>${esc(e.type)}</td><td>${p1(e.pct_of_shares)}</td></tr>`).join("")}</tbody></table>` : ""}</section>
        <section class="box"><div class="box-t">📊 점수 구성 <span class="muted tiny">충족률 ${(sc.coverage * 100).toFixed(0)}%</span></div>
          ${comp("upside", "업사이드")}${comp("valuation", "밸류에이션")}${comp("momentum", "실적 모멘텀")}${comp("price_position", "가격 위치")}
          <div class="comp"><span>리스크 감점</span><span class="tiny muted">희석 ${pd.dilution ?? "N/A"} · 부채 ${pd.debt ?? "N/A"} · 메모 ${pd.memo ?? 0}</span><b class="num down">−${sc.penalty}</b></div></section>
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
          <div><div class="k">컨센서스 목표가</div><div class="v">${won(s.target_cons)}</div><div class="x">${esc(s.cons_date || "커버리지 없음")}</div></div>
        </div>
      </div>

      <div class="card sec" style="margin-top:12px"><h2>52주 차트 <span class="muted">일봉 · 상승 빨강 / 하락 파랑</span></h2>
        <div class="chart-box" id="chart"></div>
        <div class="legend"><span><i style="border-color:#2fca73;border-top-style:dashed"></i>목표가</span><span><i style="border-color:#d1d6db"></i>분할매수가</span>
          <span><i style="border-color:#8fb8ff;border-top-style:dashed"></i>손절가</span><span><i style="border-color:#6b7280;border-top-style:dotted"></i>52주 고·저</span></div>
      </div>

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
    const Y = (v) => padT + (H - padT - padB) * (1 - (v - ymin) / (ymax - ymin));
    let g = "";
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
    const over = labs.length ? labs[labs.length - 1].y - (H - padB - 2) : 0;
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
      tip.innerHTML = `${r[0]}<br>시 ${Math.round(r[1]).toLocaleString()} 고 ${Math.round(r[2]).toLocaleString()}<br>저 ${Math.round(r[3]).toLocaleString()} 종 <b>${Math.round(r[4]).toLocaleString()}</b> (${ch >= 0 ? "+" : ""}${ch.toFixed(2)}%)`;
      tip.style.display = "block";
      const left = ((X(i) / W) * rc.width);
      tip.style.left = Math.min(rc.width - tip.offsetWidth - 4, Math.max(4, left + 10)) + "px";
      tip.style.top = "6px";
    };
    svg.addEventListener("mousemove", move);
    svg.addEventListener("touchmove", move, { passive: true });
    svg.addEventListener("mouseleave", () => { tip.style.display = "none"; xh.setAttribute("opacity", "0"); });
  }


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
    const C = DATA.meta.config, st = C.strategy, cs = C.cash, gr = C.grades, w = C.weights, rk = C.risk, tg = C.target, u = DATA.meta.universe || {};
    const f = u.filters || {};
    const steps = st.entry_steps_pct.map((p, i) => `${i + 1}차 ${p === 0 ? "현재가" : `현재가 ${p}%`} (${Math.round(st.entry_split[i] * 100)}%)`).join(" → ");
    $app.innerHTML = `<div class="rules"><h1 class="page" style="margin-bottom:12px">매매 원칙</h1>
      <div class="card"><h2>0. 분석 방식 — 모임 시트의 틀을 전 종목에</h2><ul>
        <li>대상: 코스피·코스닥 ${n0(u.listed)}개 중 <b>시총 ${n0(f.min_mcap_eok)}억↑, 거래대금 ${n0((f.min_trade_value_mil || 0) / 100)}억↑ 보통주</b> ${n0(u.analyzed)}개 (+모임 발표 종목은 항상 포함)</li>
        <li><b>투자아이디어</b>(왜 사야 하나)·<b>Risk</b>·<b>목표가 근거</b>·<b>비고(희석요소·경영진 Check)</b>를 종목마다 데이터로 자동 작성</li>
        <li>목표가: 증권사 컨센서스 → 없으면 모델 적정가(업종 중앙 PER × 예상 EPS × ${tg.model_haircut}, 현재가 +${tg.model_max_upside_pct}% 상한) → 모임 목표가</li>
        <li>DART(희석·부채·대주주)는 1차 점수 상위 ${rk.dart_top_n}종목과 모임 종목만 조회</li></ul></div>
      <div class="card"><h2>1. 등급과 행동</h2>
        <table class="mini"><thead><tr><th>등급</th><th>총점</th><th style="text-align:left">행동</th></tr></thead><tbody>
          <tr><td>${gradeShort.green}</td><td>${gr.green}점 이상</td><td style="text-align:left">계획한 분할매수 실행</td></tr>
          <tr><td>${gradeShort.yellow}</td><td>${gr.yellow}~${gr.green}점</td><td style="text-align:left">비중 절반(×${st.grade_multiplier.yellow})으로 천천히</td></tr>
          <tr><td>${gradeShort.white}</td><td>${gr.white}~${gr.yellow}점</td><td style="text-align:left">신규 매수 보류</td></tr>
          <tr><td>${gradeShort.red}</td><td>${gr.white}점 미만</td><td style="text-align:left">매수 금지${gr.red_if_negative_upside ? " · 현재가 ≥ 목표가여도 🔴" : ""}</td></tr></tbody></table>
        <p class="small">총점 = 업사이드 ${w.upside} · 밸류에이션 ${w.valuation} · 실적 모멘텀 ${w.momentum} · 가격 위치 ${w.price_position} 가중평균 − 리스크 감점(최대 ${rk.max_total}점). 충족률 ${Math.round(gr.min_coverage * 100)}% 미만이면 최고 ⚪.</p></div>
      <div class="card"><h2>2. 진입 — 3회 분할매수</h2><ul><li>${steps}</li>
        <li>2·3차 가격 ±${st.support_snap_pct}% 안에 최근 ${st.support_lookbacks.join("·")}일 저점(지지선)이 있으면 지지선 바로 위로 조정</li></ul></div>
      <div class="card"><h2>3. 비중</h2><ul>
        <li>순위 상위 <b>${st.portfolio_size}종목</b>(🟢·🟡)에만 배분: 등급 배수 × 총점 ÷ 60일 변동성</li>
        <li><b>한 종목 최대 ${st.max_weight_pct}%</b></li></ul></div>
      <div class="card"><h2>4. 손절</h2><ul>
        <li>평균 진입가 대비 <b>${st.stop_loss_pct}%</b> 또는 주요 지지선 ${st.stop_below_support_pct}% 이탈 중 <b>먼저 닿는 가격</b></li>
        <li>투자 논리 훼손(실적 쇼크, 대규모 희석, 경영진 이슈) 시 즉시 정리</li></ul></div>
      <div class="card"><h2>5. 익절</h2><ul>
        <li>1차: 목표가까지 상승여력의 <b>${Math.round(st.take_profit_1_progress * 100)}%</b> 도달 → 보유분 <b>${Math.round(st.take_profit_1_fraction * 100)}%</b> 매도</li>
        <li>2차: <b>목표가 도달</b> → 잔량 대부분 매도</li>
        <li>추적 손절: 1차 익절 이후 최고가 대비 <b>${st.trailing_stop_pct}%</b></li></ul></div>
      <div class="card"><h2>6. 현금 관리</h2>
        <table class="mini"><thead><tr><th>코스피 추세</th><th>기본 현금</th></tr></thead><tbody>
          <tr><td>${cs.ma_short}·${cs.ma_long}일선 모두 위</td><td>${cs.base_pct.above_both}%</td></tr>
          <tr><td>혼조</td><td>${cs.base_pct.mixed}%</td></tr><tr><td>모두 아래</td><td>${cs.base_pct.below_both}%</td></tr></tbody></table>
        <p class="small">🟢 종목 수에 따라 가감: ${cs.green_adjust.map((r) => `${r.min_green}개↑ ${r.adj >= 0 ? "+" : ""}${r.adj}%p`).join(" · ")} (범위 ${cs.min_pct}~${cs.max_pct}%)</p>
        <p class="small">현재 <b>${DATA.meta.cash.cash_pct}%</b> — ${esc(DATA.meta.cash.trend_desc)}, 🟢 ${DATA.meta.cash.n_green}종목</p></div>
      <div class="card"><h2>7. 점검 습관</h2><ul>
        <li>매수 전 <b>체크포인트(희석·경영진)</b>와 DART 공시를 직접 확인</li>
        <li>모델 적정가 종목은 증권사 커버리지가 없는 종목 — 사업 내용을 먼저 공부</li>
        <li>이 점수는 기계적 참고 지표입니다. 최종 판단은 각자 합니다.</li></ul></div>
    </div>`;
  }

  // ------------------------------------------------------------ 라우터
  function setNav(k) {
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === k));
  }
  function route() {
    const h = location.hash || "#/";
    $status.style.display = h === "#/" || h === "#" || h === "" ? "" : "none";
    const m = h.match(/^#\/stock\/([0-9A-Z]{6})/);
    if (!state.jumpAll) window.scrollTo(0, 0);
    if (m) { setNav("rank"); renderStock(m[1]); return; }
    if (h.startsWith("#/sectors")) { setNav("sectors"); renderSectors(); return; }
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
