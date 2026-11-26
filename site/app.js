/* 모임 매수 순위 — 정적 SPA (해시 라우팅). 데이터: data/latest.json, data/prices/{code}.json */
(() => {
  "use strict";
  const $app = document.getElementById("app");
  const $status = document.getElementById("status");
  let DATA = null;
  const priceCache = {};
  const state = { sort: "rank", dir: 1, sector: "", grades: new Set(), mcap: "", q: "" };

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

  // ------------------------------------------------------------ 데이터 로드
  async function load() {
    try {
      const r = await fetch("data/latest.json", { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      DATA = await r.json();
    } catch (e) {
      $status.innerHTML = "";
      $app.innerHTML = `<div class="card sec" style="margin-top:16px"><h2>아직 수집된 데이터가 없습니다</h2>
        <p class="muted">GitHub 저장소의 <b>Actions → 데이터 갱신 및 배포 → Run workflow</b>를 한 번 실행하면 데이터가 채워집니다. (README 참고)</p></div>`;
      return false;
    }
    return true;
  }

  async function prices(code) {
    if (priceCache[code]) return priceCache[code];
    const r = await fetch(`data/prices/${code}.json`, { cache: "no-store" });
    if (!r.ok) throw new Error("no chart");
    return (priceCache[code] = (await r.json()).rows);
  }

  // ------------------------------------------------------------ 상단 상태 영역
  function renderStatus() {
    const m = DATA.meta, c = m.cash || {}, gc = m.grade_counts || {};
    const mk = m.market;
    const trendCls = c.trend_state === "above_both" ? "up" : c.trend_state === "below_both" ? "down" : "";
    let warn = "";
    if (m.demo) warn += `<div class="banner err">⚠️ 화면 확인용 <b>데모 데이터</b>입니다. 실제 시세가 아닙니다.</div>`;
    if (!m.dart_enabled) warn += `<div class="banner">DART API 키가 설정되지 않아 확정 실적·희석 물량·대주주 지분은 N/A로 표시됩니다.</div>`;
    $status.innerHTML = `<div class="strip">
      <div class="tile"><div class="k">데이터 갱신</div><div class="v small" style="font-size:17px">${esc(m.generated_at)}</div>
        <div class="s">시세 기준일 ${esc(m.price_as_of || "N/A")} · 대상 ${m.sheet?.stocks ?? "-"}종목</div></div>
      <div class="tile"><div class="k">권장 현금 비중</div><div class="v">${isNum(c.cash_pct) ? c.cash_pct.toFixed(0) + "%" : "N/A"}</div>
        <div class="s">주식 ${isNum(c.cash_pct) ? (100 - c.cash_pct).toFixed(0) : "-"}% · 🟢 ${c.n_green ?? 0}종목</div></div>
      <div class="tile"><div class="k">코스피</div><div class="v">${mk ? n0(mk.last) : "N/A"}</div>
        <div class="s ${trendCls}">${esc(c.trend_desc || "")}</div></div>
      <div class="tile"><div class="k">등급 분포</div><div class="gcounts">
        ${["green", "yellow", "white", "red"].map((g) => `<span class="g g-${g}">${gradeShort[g]} ${gc[g] ?? 0}</span>`).join("")}</div></div>
    </div>${warn}`;
  }

  // ------------------------------------------------------------ 순위(메인)
  const MCAP = [
    ["", "시총 전체"], ["0-1000", "1천억 미만"], ["1000-5000", "1천억~5천억"], ["5000-10000", "5천억~1조"],
    ["10000-100000", "1조~10조"], ["100000-1e12", "10조 이상"],
  ];
  const COLS = [
    ["rank", "순위", "l"], ["name", "종목", "l"], ["grade", "등급", "l"], ["total", "총점"], ["price", "현재가"],
    ["upside", "업사이드"], ["per", "PER"], ["pbr", "PBR"], ["fwd_per", "Fwd PER"], ["mcap", "시총"],
    ["weight", "권장 비중"], ["reason", "판단 근거", "l"],
  ];
  const gOrder = { green: 0, yellow: 1, white: 2, red: 3 };
  const sortVal = {
    rank: (s) => s.rank, name: (s) => s.name, grade: (s) => gOrder[s.score.grade] * 1000 - (s.score.total ?? 0),
    total: (s) => s.score.total, price: (s) => s.price, upside: (s) => s.score.upside_pct, per: (s) => s.per,
    pbr: (s) => s.pbr, fwd_per: (s) => s.fwd_per, mcap: (s) => s.mcap_eok, weight: (s) => s.weight_pct,
    reason: (s) => s.score.reason,
  };

  function filtered() {
    let L = DATA.stocks.slice();
    if (state.sector) L = L.filter((s) => s.sector === state.sector);
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
    $app.innerHTML = `
      <div class="filters">
        <input id="q" type="search" placeholder="종목명·코드 검색" value="${esc(state.q)}">
        <select id="sector"><option value="">섹터 전체</option>${sectors.map((s) => `<option ${s === state.sector ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <select id="mcap">${MCAP.map(([v, l]) => `<option value="${v}" ${v === state.mcap ? "selected" : ""}>${l}</option>`).join("")}</select>
        ${["green", "yellow", "white", "red"].map((g) => `<button class="chip ${state.grades.has(g) ? "on" : ""}" data-g="${g}">${gradeShort[g]}</button>`).join("")}
        <span class="count" id="count"></span>
      </div>
      <div class="card"><div class="tbl-wrap"><table class="rank"><thead><tr>
        ${COLS.map(([k, l, a]) => `<th class="${a || ""}" data-k="${k}">${l} <span class="arr">${state.sort === k ? (state.dir > 0 ? "▲" : "▼") : ""}</span></th>`).join("")}
      </tr></thead><tbody id="tb"></tbody></table></div><div class="mlist" id="ml"></div></div>
      <p class="tiny muted" style="margin-top:8px">업사이드 = (목표가 − 현재가) ÷ 현재가. 목표가는 ${DATA.meta.config.upside.target_source === "consensus_first" ? "컨센서스 우선" : DATA.meta.config.upside.target_source === "average" ? "모임·컨센서스 평균" : "모임 목표가 우선, 없으면 컨센서스"}. 행을 누르면 상세 화면으로 이동합니다.</p>`;
    const draw = () => {
      const L = filtered();
      document.getElementById("count").textContent = `${L.length}종목`;
      document.getElementById("tb").innerHTML = L.map(rowHtml).join("") || `<tr><td colspan="12" class="l muted">조건에 맞는 종목이 없습니다.</td></tr>`;
      document.getElementById("ml").innerHTML = L.map(cardHtml).join("") || `<p class="sec muted">조건에 맞는 종목이 없습니다.</p>`;
    };
    draw();
    $app.querySelector("#q").addEventListener("input", (e) => { state.q = e.target.value.trim(); draw(); });
    $app.querySelector("#sector").addEventListener("change", (e) => { state.sector = e.target.value; draw(); });
    $app.querySelector("#mcap").addEventListener("change", (e) => { state.mcap = e.target.value; draw(); });
    $app.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
      const g = b.dataset.g; state.grades.has(g) ? state.grades.delete(g) : state.grades.add(g);
      b.classList.toggle("on"); draw();
    }));
    $app.querySelectorAll("th").forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.k;
      if (state.sort === k) state.dir *= -1;
      else { state.sort = k; state.dir = ["total", "upside", "weight", "mcap"].includes(k) ? -1 : 1; }
      renderRank();
    }));
    $app.querySelector("#tb").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-code]"); if (tr) location.hash = `#/stock/${tr.dataset.code}`;
    });
  }

  function rowHtml(s) {
    const sc = s.score;
    return `<tr data-code="${esc(s.code)}">
      <td class="l rk ${s.rank <= 3 ? "top" : ""}">${s.rank}</td>
      <td class="l nm">${esc(s.name)}<small>${esc(s.code)} · ${esc(s.sector)}</small></td>
      <td class="l">${gradeBadge(s)}</td>
      <td><span class="score"><b>${isNum(sc.total) ? sc.total.toFixed(0) : "N/A"}</b>${bar(sc.total)}</span></td>
      <td>${won(s.price)}<div class="tiny">${sgn(s.change_pct, 2)}</div></td>
      <td>${sgn(sc.upside_pct, 0)}<div class="tiny muted">${esc(s.target_source || "")}</div></td>
      <td>${perf(s.per)}</td><td>${x1(s.pbr, "")}</td><td>${perf(s.fwd_per)}</td><td>${eok(s.mcap_eok)}</td>
      <td>${s.weight_pct ? s.weight_pct.toFixed(1) + "%" : '<span class="muted">0%</span>'}</td>
      <td class="reason">${esc(sc.reason)}</td></tr>`;
  }

  function cardHtml(s) {
    const sc = s.score;
    return `<a class="mcard" href="#/stock/${esc(s.code)}">
      <div class="mrow"><div><span class="rk ${s.rank <= 3 ? "top" : ""}">${s.rank}</span> <b>${esc(s.name)}</b> <span class="tiny muted">${esc(s.code)} · ${esc(s.sector)}</span></div>
        <div><b>${isNum(sc.total) ? sc.total.toFixed(0) : "N/A"}</b><span class="tiny muted">점</span></div></div>
      <div class="mrow" style="margin-top:6px">${gradeBadge(s)}<div>${won(s.price)} <span class="tiny">${sgn(s.change_pct, 2)}</span></div></div>
      <div class="mstats"><span>업사이드 ${sgn(sc.upside_pct, 0)}</span><span>PER ${perf(s.per)}</span><span>PBR ${x1(s.pbr, "")}</span><span>시총 ${eok(s.mcap_eok)}</span><span>비중 ${(s.weight_pct || 0).toFixed(1)}%</span></div>
      <div class="reason">${esc(sc.reason)}</div></a>`;
  }

  // ------------------------------------------------------------ 상세
  async function renderStock(code) {
    const s = DATA.stocks.find((x) => x.code === code);
    if (!s) { $app.innerHTML = `<p class="loading">종목을 찾을 수 없습니다. <a href="#/">순위로</a></p>`; return; }
    const sc = s.score, c = sc.components, est = s.est || {}, pl = s.plan;
    const yr = est.year;
    const comp = (k, l) => {
      const v = c[k]?.score;
      return `<div class="comp"><span>${l} <span class="tiny muted">×${c[k]?.weight ?? 0}</span></span>${bar(v)}<b class="num" style="text-align:right">${isNum(v) ? v.toFixed(0) : "N/A"}</b></div>`;
    };
    const pd = sc.penalty_detail || {};
    const dart = s.dart || {};
    const dil = dart.dilution;
    const fin = dart.financials || {};
    const yrow = (label, key, unit) => {
      const cell = (o) => (o && isNum(o[key]) ? (unit === "won" ? n0(o[key]) : eok(o[key])) : NA);
      return `<tr><td>${label}</td><td>${cell(est.prev)}</td><td>${cell(est.cur)}${est.cur?.estimate ? "" : ""}</td>
        <td>${sgn(est[key + "_g_cur"], 0)}</td><td>${cell(est.next)}</td><td>${sgn(est[key + "_g_next"], 0)}</td></tr>`;
    };
    const tag = (o) => (o && Object.keys(o).length ? (o.estimate ? '<span class="pill">E</span>' : '<span class="pill">확정</span>') : "");

    $app.innerHTML = `
      <a class="back" href="#/">← 매수 순위</a>
      <div class="card">
        <div class="dhead">
          <div><h1>${esc(s.name)}</h1>
            <div class="meta">${esc(s.code)} · ${esc(s.market || "")} · 섹터 ${esc(s.sector)} · ${s.rank}위${s.is_etf ? " · ETF" : ""}</div></div>
          <div class="dprice"><div class="p">${won(s.price)}</div>
            <div>${sgn(s.change_pct, 2)} <span class="tiny muted">${esc(String(s.price_time || "").replace("T", " ").slice(0, 16))} · ${esc(s.sources?.price || "")}</span></div></div>
        </div>
        <div class="verdict">${gradeBadge(s)}<span class="tot">${isNum(sc.total) ? sc.total.toFixed(1) : "N/A"}점</span><span class="why">${esc(sc.reason)}</span></div>
      </div>

      <div class="grid2">
        <div class="card sec"><h2>점수 구성 <span class="muted">데이터 충족률 ${(sc.coverage * 100).toFixed(0)}%</span></h2>
          ${comp("upside", "업사이드")}${comp("valuation", "밸류에이션")}${comp("momentum", "실적 모멘텀")}${comp("price_position", "가격 위치")}
          <div class="comp"><span>리스크 감점</span><span class="small muted">희석 ${pd.dilution ?? "N/A"} · 부채 ${pd.debt ?? "N/A"} · 메모 ${pd.memo ?? 0}</span><b class="num down" style="text-align:right">−${sc.penalty}</b></div>
          <p class="tiny muted" style="margin:6px 0 0">가중평균 ${sc.base ?? "N/A"}점 − 감점 ${sc.penalty}점 = 총점. 데이터가 없는 항목은 제외하고 나머지 가중치로 계산.</p>
        </div>
        <div class="card sec"><h2>목표가 · 업사이드</h2>
          <div class="kv">
            <div><div class="k">적용 목표가</div><div class="v">${won(s.target)}</div><div class="x">${esc(s.target_source || "없음")}</div></div>
            <div><div class="k">업사이드</div><div class="v">${sgn(sc.upside_pct, 1)}</div></div>
            <div><div class="k">모임 목표가</div><div class="v">${won(s.target_club)}</div></div>
            <div><div class="k">컨센서스 목표가</div><div class="v">${won(s.target_cons)}</div><div class="x">${esc(s.cons_date || "")}</div></div>
          </div>
          <h2 style="margin-top:16px">모임 발표 이력</h2>
          <table class="mini"><thead><tr><th>발표일</th><th>발표자</th><th>발표일 주가</th><th>목표가</th><th>이후 수익률</th></tr></thead><tbody>
            ${(s.pitches || []).map((p) => `<tr><td>${esc(p.date || "N/A")}</td><td>${esc(p.presenter || "N/A")}</td><td>${won(p.price_at_pitch)}</td>
              <td>${p.target ? won(p.target) : esc(p.target_raw || "N/A")}</td><td>${sgn(p.return_since, 1)}</td></tr>`).join("")}
          </tbody></table>
        </div>
      </div>

      <div class="card sec" style="margin-top:12px"><h2>주요 지표</h2>
        <div class="kv">
          <div><div class="k">시가총액</div><div class="v">${eok(s.mcap_eok)}</div><div class="x">${esc(s.sources?.mcap || "")}</div></div>
          <div><div class="k">PER (Trailing)</div><div class="v">${perf(s.per)}</div><div class="x">비교 ${x1(s.bench?.per)} · ${esc(s.bench?.per_src || "")}</div></div>
          <div><div class="k">PBR</div><div class="v">${x1(s.pbr, "배")}</div><div class="x">비교 ${x1(s.bench?.pbr)} · ${esc(s.bench?.pbr_src || "")}</div></div>
          <div><div class="k">Forward PER</div><div class="v">${perf(s.fwd_per)}</div><div class="x">${esc(s.fwd_basis || "")}</div></div>
          <div><div class="k">ROE</div><div class="v">${p1(s.roe)}</div><div class="x">최근 연간</div></div>
          <div><div class="k">배당수익률</div><div class="v">${p1(s.div_yield)}</div></div>
          <div><div class="k">52주 고가 / 저가</div><div class="v">${n0(s.high52)} / ${n0(s.low52)}</div><div class="x">범위 내 위치 ${isNum(s.range_pos) ? (s.range_pos * 100).toFixed(0) + "%" : "N/A"}</div></div>
          <div><div class="k">수익률 1W · 1M · 3M</div><div class="v small">${sgn(s.ret_1w)} · ${sgn(s.ret_1m)} · ${sgn(s.ret_3m)}</div><div class="x">6M ${sgn(s.ret_6m)} · 12M ${sgn(s.ret_12m)}</div></div>
          <div><div class="k">변동성(60일, 연율)</div><div class="v">${p1(s.vol_annual)}</div></div>
          <div><div class="k">부채비율</div><div class="v">${p1(s.debt_ratio)}</div><div class="x">${esc(s.debt_basis || "")}</div></div>
          <div><div class="k">컨센서스 변화</div><div class="v">${sgn(s.revision_pct)}</div><div class="x">${esc(s.revision_basis || "과거 스냅샷 누적 중")}</div></div>
          <div><div class="k">최대주주 지분</div><div class="v">${p1(dart.holder?.pct)}</div><div class="x">${esc(dart.holder?.name || "")} ${esc(dart.holder?.basis || "")}</div></div>
        </div>
      </div>

      <div class="card sec" style="margin-top:12px"><h2>52주 차트 <span class="muted">일봉 · 상승 빨강 / 하락 파랑</span></h2>
        <div class="chart-box" id="chart"><p class="muted small">차트 불러오는 중…</p></div>
        <div class="legend"><span><i style="border-color:#0e9f6e;border-top-style:dashed"></i>목표가</span><span><i style="border-color:#17191c"></i>분할매수가</span>
          <span><i style="border-color:#1b64da;border-top-style:dashed"></i>손절가</span><span><i style="border-color:#9aa1ad;border-top-style:dotted"></i>52주 고·저</span></div>
      </div>

      <div class="card sec" style="margin-top:12px"><h2>예상 실적 <span class="muted">단위: 억원, EPS 원 · FnGuide/네이버 컨센서스</span></h2>
        <div class="tbl-wrap" style="display:block"><table class="mini"><thead><tr><th></th><th>${yr - 1} ${tag(est.prev)}</th><th>${yr} ${tag(est.cur)}</th><th>성장률</th><th>${yr + 1} ${tag(est.next)}</th><th>성장률</th></tr></thead>
          <tbody>${yrow("매출액", "revenue")}${yrow("영업이익", "op_income")}${yrow("EPS", "eps", "won")}</tbody></table></div>
        ${est.turnaround_next ? '<p class="small up">내년 흑자전환 예상</p>' : ""}
        <p class="tiny muted" style="margin:8px 0 0">DART 확정 실적${fin.annual ? ` (${fin.annual.year}년 사업보고서, ${esc(fin.annual.fs)})` : ""}: 매출 ${eok(fin.annual?.revenue)} · 영업이익 ${eok(fin.annual?.op_income)} · 순이익 ${eok(fin.annual?.net_income)}</p>
      </div>

      <div class="card sec" style="margin-top:12px"><h2>매매 전략 <span class="muted">권장 비중 ${(s.weight_pct || 0).toFixed(1)}% (최대 ${DATA.meta.config.strategy.max_weight_pct}%)</span></h2>
        ${pl ? planHtml(s, pl) : '<p class="muted">시세 데이터가 없어 전략을 산출하지 못했습니다.</p>'}
      </div>

      <div class="grid2">
        <div class="card sec"><h2>리스크</h2>
          <div class="kv" style="grid-template-columns:1fr 1fr">
            <div><div class="k">잠재 희석률 (CB·BW·유증)</div><div class="v">${p1(s.dilution_pct)}</div><div class="x">${esc(dil?.basis || (dart.enabled ? "" : "DART 키 미설정"))}</div></div>
            <div><div class="k">시트 메모 리스크 키워드</div><div class="v small">${sc.memo_hits?.length ? esc(sc.memo_hits.join(", ")) : "없음"}</div></div>
          </div>
          ${dil?.events?.length ? `<table class="mini" style="margin-top:10px"><thead><tr><th>공시일</th><th>종류</th><th>주식수</th><th>주식총수 대비</th><th>전환/행사가</th></tr></thead><tbody>
            ${dil.events.slice(0, 10).map((e) => `<tr><td><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${esc(e.rcept_no)}" target="_blank" rel="noopener">${esc(e.date)}</a></td><td>${esc(e.type)}</td><td>${n0(e.shares)}</td><td>${p1(e.pct_of_shares)}</td><td>${won(e.conv_price)}</td></tr>`).join("")}
          </tbody></table>` : `<p class="small muted">${dart.enabled ? "조회 기간 내 CB·BW·유상증자 결정 공시 없음" : ""}</p>`}
          <div class="memo-t" style="margin-top:10px">Risk (시트)</div><pre class="memo">${esc(s.sheet?.risk || "—")}</pre>
          <div class="memo-t">비고 · 주가희석요소 및 경영진 Check (시트)</div><pre class="memo">${esc(s.sheet?.note || "—")}</pre>
        </div>
        <div class="card sec"><h2>시트 원문 메모</h2>
          <div class="memo-t">투자아이디어</div><pre class="memo">${esc(s.sheet?.idea || "—")}</pre>
          <div class="memo-t">목표가 근거</div><pre class="memo">${esc(s.sheet?.basis || "—")}</pre>
          ${s.sheet?.qna ? `<div class="memo-t">Q&amp;A</div><pre class="memo">${esc(s.sheet.qna)}</pre>` : ""}
          ${s.sheet?.etc ? `<div class="memo-t">기타</div><pre class="memo">${esc(s.sheet.etc)}</pre>` : ""}
        </div>
      </div>
      ${s.errors?.length ? `<p class="errs">수집 실패 항목: ${esc(s.errors.join(" / "))}</p>` : ""}`;

    try {
      const rows = await prices(code);
      drawChart(document.getElementById("chart"), rows, s);
    } catch (e) {
      document.getElementById("chart").innerHTML = `<p class="muted small">차트 데이터 N/A</p>`;
    }
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
    if (isNum(s.target)) lines.push([s.target, "#0e9f6e", "6 4", "목표"]);
    if (s.plan) {
      s.plan.entries.forEach((e) => lines.push([e.price, "#17191c", "", `${e.step}차`]));
      lines.push([s.plan.stop, "#1b64da", "6 4", "손절"]);
    }
    const hi = Math.max(...rows.map((r) => r[2])), lo = Math.min(...rows.map((r) => r[3]));
    lines.push([hi, "#9aa1ad", "2 3", "52주高"], [lo, "#9aa1ad", "2 3", "52주低"]);
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
      g += `<line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" stroke="#f0f1f4"/><text x="${W - padR + 6}" y="${y + 4}" font-size="11" fill="#8a909c">${Math.round(v).toLocaleString("ko-KR")}</text>`;
    }
    // 월 라벨
    let lastM = "";
    rows.forEach((r, i) => {
      const m = r[0].slice(0, 7);
      if (m !== lastM && i > 3 && (W >= 600 || +m.slice(5) % 2 === 1)) g += `<text x="${X(i)}" y="${H - 8}" font-size="11" fill="#8a909c" text-anchor="middle">${m.slice(2).replace("-", ".")}</text>`;
      lastM = m;
    });
    // 캔들
    rows.forEach((r, i) => {
      const [, o, h, l, c] = r, up = c >= o, col = up ? "#e5322d" : "#1b64da";
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
    labs.forEach((l) => { g += `<text x="${padL + 4}" y="${l.y}" font-size="10.5" fill="${l.col}" paint-order="stroke" stroke="#fff" stroke-width="3">${l.t}</text>`; });
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="52주 일봉 차트">${g}<line id="xh" y1="${padT}" y2="${H - padB}" stroke="#17191c" stroke-width=".6" opacity="0"/></svg><div class="tip" id="tip"></div>`;
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

  // ------------------------------------------------------------ 섹터
  function renderSectors() {
    const secs = Object.entries(DATA.sectors).sort((a, b) => b[1].n - a[1].n || a[0].localeCompare(b[0], "ko"));
    const by = Object.fromEntries(DATA.stocks.map((s) => [s.code, s]));
    $app.innerHTML = `<h1 class="page">섹터 뷰</h1>
      <p class="small muted" style="margin:4px 0 0">모임 시트의 섹터 분류 기준. 평균·중앙값은 PER·PBR이 양수인 종목만으로 계산합니다.</p>
      <div class="secgrid">${secs.map(([name, st]) => `<div class="card"><h3>${esc(name)} <span class="tiny muted">${st.n}종목</span></h3>
        <div class="kv" style="grid-template-columns:1fr 1fr;margin-bottom:8px">
          <div><div class="k">평균 PER (중앙값)</div><div class="v">${x1(st.per_mean)} <span class="tiny muted">(${x1(st.per_median)})</span></div></div>
          <div><div class="k">평균 PBR (중앙값)</div><div class="v">${x1(st.pbr_mean, "배")} <span class="tiny muted">(${x1(st.pbr_median, "배")})</span></div></div></div>
        ${st.codes.map((c) => by[c]).filter(Boolean).sort((a, b) => a.rank - b.rank).map((s) => `<a class="mrow" href="#/stock/${esc(s.code)}">
          <span><b>${esc(s.name)}</b> <span class="tiny muted">${s.rank}위</span></span>
          <span class="small">${gradeShort[s.score.grade]} · PER ${perf(s.per)} · PBR ${x1(s.pbr, "")}</span></a>`).join("")}
      </div>`).join("")}</div>`;
  }

  // ------------------------------------------------------------ 매매 원칙
  function renderRules() {
    const C = DATA.meta.config, st = C.strategy, cs = C.cash, gr = C.grades, w = C.weights, rk = C.risk;
    const wsum = Object.values(w).reduce((a, b) => a + b, 0);
    const steps = st.entry_steps_pct.map((p, i) => `${i + 1}차 ${p === 0 ? "현재가" : `현재가 ${p}%`} (${Math.round(st.entry_split[i] * 100)}%)`).join(" → ");
    $app.innerHTML = `<div class="rules"><h1 class="page" style="margin-bottom:12px">매매 원칙</h1>
      <div class="card"><h2>1. 등급과 행동</h2>
        <table class="mini"><thead><tr><th>등급</th><th>총점</th><th>행동</th></tr></thead><tbody>
          <tr><td>${gradeShort.green}(적극 매수)</td><td>${gr.green}점 이상</td><td class="l" style="text-align:left">계획한 분할매수 전부 실행 가능</td></tr>
          <tr><td>${gradeShort.yellow}</td><td>${gr.yellow}~${gr.green}점</td><td style="text-align:left">비중 절반(×${st.grade_multiplier.yellow})으로 천천히</td></tr>
          <tr><td>${gradeShort.white}</td><td>${gr.white}~${gr.yellow}점</td><td style="text-align:left">신규 매수 보류, 보유분은 손절·익절 규칙만 적용</td></tr>
          <tr><td>${gradeShort.red}(매수 금지)</td><td>${gr.white}점 미만</td><td style="text-align:left">신규 매수 금지${gr.red_if_negative_upside ? " · 현재가가 목표가 이상이어도 🔴" : ""}</td></tr>
        </tbody></table>
        <p class="small muted">총점 = 업사이드 ${w.upside} · 밸류에이션 ${w.valuation} · 실적 모멘텀 ${w.momentum} · 가격 위치 ${w.price_position} 가중평균(합 ${wsum}) − 리스크 감점(최대 ${rk.max_total}점). 데이터 충족률이 ${Math.round(gr.min_coverage * 100)}% 미만이면 최고 ⚪.</p></div>
      <div class="card"><h2>2. 진입 — 3회 분할매수</h2><ul>
        <li>${steps}</li>
        <li>2·3차 가격 ±${st.support_snap_pct}% 안에 최근 ${st.support_lookbacks.join("·")}일 저점(지지선)이 있으면 그 지지선 바로 위로 조정</li>
        <li>등급이 🟡 이하로 떨어지면 남은 차수는 보류</li></ul></div>
      <div class="card"><h2>3. 비중</h2><ul>
        <li>권장 비중 ∝ 등급 배수(🟢 ${st.grade_multiplier.green} · 🟡 ${st.grade_multiplier.yellow}) × 총점 ÷ 60일 변동성 → 주식 몫(100% − 현금 비중) 안에서 배분</li>
        <li><b>한 종목 최대 ${st.max_weight_pct}%</b> (넘는 몫은 다른 종목에 재배분, 남으면 현금)</li></ul></div>
      <div class="card"><h2>4. 손절</h2><ul>
        <li>평균 진입가 대비 <b>${st.stop_loss_pct}%</b> 또는 주요 지지선 ${st.stop_below_support_pct}% 이탈 중 <b>먼저 닿는 가격</b></li>
        <li>가격과 상관없이 <b>투자 논리가 훼손되면</b>(실적 쇼크, 대규모 희석, 경영진 이슈 등) 즉시 정리</li>
        <li>손절 후 같은 종목 재진입은 등급이 다시 🟢가 된 뒤에만</li></ul></div>
      <div class="card"><h2>5. 익절</h2><ul>
        <li>1차: 목표가까지 상승여력의 <b>${Math.round(st.take_profit_1_progress * 100)}%</b> 도달 시 보유분 <b>${Math.round(st.take_profit_1_fraction * 100)}%</b> 매도</li>
        <li>2차: <b>목표가 도달</b> 시 잔량 대부분 매도</li>
        <li>추적 손절: 1차 익절 이후 종가 기준 최고가 대비 <b>${st.trailing_stop_pct}%</b> 하락 시 잔량 매도</li>
        <li>목표가가 상향되면 2차 익절가도 따라 올리되, 1차 익절 물량은 되사지 않음</li></ul></div>
      <div class="card"><h2>6. 현금 관리</h2>
        <table class="mini"><thead><tr><th>코스피 추세</th><th>기본 현금</th></tr></thead><tbody>
          <tr><td>${cs.ma_short}·${cs.ma_long}일선 모두 위</td><td>${cs.base_pct.above_both}%</td></tr>
          <tr><td>하나만 위(혼조)</td><td>${cs.base_pct.mixed}%</td></tr>
          <tr><td>모두 아래</td><td>${cs.base_pct.below_both}%</td></tr></tbody></table>
        <p class="small">🟢 종목 수에 따라 가감: ${cs.green_adjust.map((r) => `${r.min_green}개 이상 ${r.adj >= 0 ? "+" : ""}${r.adj}%p`).join(" · ")} (범위 ${cs.min_pct}~${cs.max_pct}%)</p>
        <p class="small">현재: <b>${DATA.meta.cash.cash_pct}%</b> — ${esc(DATA.meta.cash.trend_desc)}, 🟢 ${DATA.meta.cash.n_green}종목</p></div>
      <div class="card"><h2>7. 점검 습관</h2><ul>
        <li>매수 전 종목 상세의 <b>비고(희석 요소·경영진 Check)</b>와 DART 희석 공시를 반드시 확인</li>
        <li>N/A가 많은 종목은 점수가 과대·과소평가될 수 있으므로 원자료 확인 후 판단</li>
        <li>이 규칙과 점수는 기계적 참고 지표입니다. 최종 판단은 각자 합니다.</li></ul></div>
    </div>`;
  }

  // ------------------------------------------------------------ 라우터
  function route() {
    const h = location.hash || "#/";
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.remove("on"));
    const m = h.match(/^#\/stock\/([0-9A-Z]{6})/);
    window.scrollTo(0, 0);
    if (m) { renderStock(m[1]); return; }
    if (h.startsWith("#/sectors")) { document.querySelector('[data-nav="sectors"]').classList.add("on"); renderSectors(); return; }
    if (h.startsWith("#/rules")) { document.querySelector('[data-nav="rules"]').classList.add("on"); renderRules(); return; }
    document.querySelector('[data-nav="rank"]').classList.add("on");
    renderRank();
  }

  load().then((ok) => {
    if (!ok) return;
    renderStatus();
    window.addEventListener("hashchange", route);
    route();
  });
})();
