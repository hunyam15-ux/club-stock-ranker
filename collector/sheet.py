"""모임 구글 시트(메인 탭) CSV 읽기·정리.

시트 구조(2026-11 확인):
  1행: 제목행(무시)
  2행: 헤더 — [빈칸(=발표자), 번호, 섹터, 기업명, Q&A, 발표일, 티커, 투자아이디어, Risk,
        발표일 주가, 현재가, 1W, 1M, 3M, 6M, 12M, 발표일~수익률, 목표가, 근거, 비고(...),
        자료첨부, 기타, 시가총액(억원/억달러), PER, 차트(365일), 52주 고가, 52주 저가, 차이]
  그 아래 메인 표, 빈 행들, 그리고 '발표자/종목명/종목코드' 형식의 두 번째 표.
  → 메인 표만 읽고 두 번째 표 헤더를 만나면 멈춘다.
헤더 이름으로 열을 찾기 때문에 열 순서가 바뀌어도 동작한다.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field, asdict

from .util import get, log, to_num

# 헤더 이름(앞부분 일치) → 내부 키
COLUMN_ALIASES = {
    "presenter": ["발표자"],
    "no": ["번호"],
    "sector": ["섹터"],
    "name": ["기업명", "종목명"],
    "qna": ["Q&A", "QnA"],
    "ticker": ["티커", "종목코드"],
    "idea": ["투자아이디어"],
    "risk": ["Risk", "리스크"],
    "price_at_pitch": ["발표일 주가"],
    "sheet_price": ["현재가"],
    "target": ["목표가"],
    "basis": ["근거"],
    "note": ["비고"],
    "etc": ["기타"],
    "sheet_mcap": ["시가총액"],
    "sheet_per": ["PER"],
    "sheet_high52": ["52주 고가"],
    "sheet_low52": ["52주 저가"],
}

DOMESTIC_RE = re.compile(r"^(?:(KRX|KOSPI|KOSDAQ|KONEX)\s*:\s*)?([0-9][0-9A-Z]{5})$", re.I)


@dataclass
class Pitch:
    presenter: str | None
    date: str | None
    price_at_pitch: float | None
    target: float | None
    target_raw: str | None
    row_no: str | None


@dataclass
class SheetStock:
    code: str
    market_hint: str | None
    name: str
    sector: str | None
    idea: str = ""
    risk: str = ""
    basis: str = ""
    note: str = ""
    qna: str = ""
    etc: str = ""
    pitches: list[Pitch] = field(default_factory=list)
    sheet_price: float | None = None
    sheet_mcap: float | None = None
    sheet_per: float | None = None
    sheet_high52: float | None = None
    sheet_low52: float | None = None

    def to_dict(self):
        return asdict(self)


def csv_url(sheet_id: str, gid: str | int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def fetch_csv(sess, sheet_id: str, gid) -> str:
    r = get(sess, csv_url(sheet_id, gid), timeout=30)
    r.encoding = "utf-8"
    text = r.text
    if "<html" in text[:500].lower():
        raise RuntimeError("시트가 CSV 대신 HTML(로그인 페이지 등)을 돌려줬습니다. 공유 설정을 확인하세요.")
    return text


def parse_ticker(raw: str | None) -> tuple[str | None, str | None]:
    """'KOSDAQ:073010' → ('073010','KOSDAQ'), '005930' → ('005930', None), 'IONQ' → (None, None)."""
    if not raw:
        return None, None
    s = raw.strip().upper().replace(" ", "")
    m = DOMESTIC_RE.match(s)
    if not m:
        return None, None
    mk = m.group(1)
    if mk == "KRX":
        mk = "KOSPI"
    return m.group(2), mk


def parse_target(raw: str | None) -> float | None:
    """'7,600' → 7600, '15,000~20,000' → 17500(중간값), 'N/A' → None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    nums = [to_num(x) for x in re.split(r"[~～\-–]\s*(?=\d)", s)]
    nums = [n for n in nums if n is not None and n > 0]
    if not nums:
        return None
    return sum(nums[:2]) / len(nums[:2])


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip())


def _find_header(rows: list[list[str]]) -> int:
    for i, row in enumerate(rows[:20]):
        cells = {_norm(c) for c in row}
        if "기업명" in cells and "티커" in cells:
            return i
    raise RuntimeError("시트에서 '기업명'과 '티커' 헤더 행을 찾지 못했습니다.")


def _build_colmap(header: list[str]) -> dict[str, int]:
    hdr = [_norm(h) for h in header]
    cmap: dict[str, int] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for idx, h in enumerate(hdr):
            if any(h == a or h.startswith(a) for a in aliases):
                cmap[key] = idx
                break
    # 발표일: '발표일' 정확 일치(‘발표일 주가’, ‘발표일~수익률’ 제외)
    for idx, h in enumerate(hdr):
        if h == "발표일":
            cmap["date"] = idx
            break
    # 발표자 헤더가 없으면 '번호' 왼쪽의 빈 헤더 열을 발표자로 사용(현재 시트 구조)
    if "presenter" not in cmap and "no" in cmap:
        for idx in range(cmap["no"] - 1, -1, -1):
            if hdr[idx] == "":
                cmap["presenter"] = idx
                break
    for req in ("name", "ticker"):
        if req not in cmap:
            raise RuntimeError(f"필수 열 '{req}' 을(를) 찾지 못했습니다.")
    return cmap


def parse_sheet(text: str) -> tuple[list[SheetStock], dict]:
    rows = list(csv.reader(io.StringIO(text)))
    h = _find_header(rows)
    cmap = _build_colmap(rows[h])

    def cell(row, key) -> str:
        i = cmap.get(key)
        if i is None or i >= len(row):
            return ""
        return (row[i] or "").strip()

    stats = {"rows": 0, "domestic_rows": 0, "foreign_or_no_ticker": [], "columns": cmap}
    by_code: dict[str, SheetStock] = {}
    for row in rows[h + 1:]:
        cells = {_norm(c) for c in row}
        if "종목명" in cells and "종목코드" in cells:
            break  # 두 번째 표 시작 → 메인 표만 사용
        name = cell(row, "name")
        if not name:
            continue
        stats["rows"] += 1
        code, mk = parse_ticker(cell(row, "ticker"))
        if not code:
            stats["foreign_or_no_ticker"].append(f"{name}({cell(row, 'ticker') or '티커 없음'})")
            continue
        stats["domestic_rows"] += 1
        pitch = Pitch(
            presenter=cell(row, "presenter") or None,
            date=cell(row, "date") or None,
            price_at_pitch=to_num(cell(row, "price_at_pitch")),
            target=parse_target(cell(row, "target")),
            target_raw=cell(row, "target") or None,
            row_no=cell(row, "no") or None,
        )
        st = by_code.get(code)
        if st is None:
            st = SheetStock(code=code, market_hint=mk, name=name, sector=cell(row, "sector") or None)
            by_code[code] = st
        st.pitches.append(pitch)
        # 텍스트 메모는 여러 번 발표된 경우 날짜와 함께 이어 붙인다
        for key in ("idea", "risk", "basis", "note", "qna", "etc"):
            v = cell(row, key)
            if v:
                cur = getattr(st, key)
                tag = f"[{pitch.date or '날짜 미상'} 발표 {pitch.presenter or ''}] " if cur else ""
                setattr(st, key, (cur + "\n\n" if cur else "") + tag + v)
        # 최신 발표 기준으로 기본 정보 갱신
        if _latest(st.pitches) is pitch:
            st.name = name
            st.sector = cell(row, "sector") or st.sector
        for key in ("sheet_price", "sheet_mcap", "sheet_per", "sheet_high52", "sheet_low52"):
            v = to_num(cell(row, key))
            if v is not None:
                setattr(st, key, v)

    stocks = list(by_code.values())
    for st in stocks:
        st.pitches.sort(key=lambda p: p.date or "", reverse=True)
    log.info("시트: %d행, 국내 %d행 → %d종목 (제외 %d)", stats["rows"], stats["domestic_rows"],
             len(stocks), len(stats["foreign_or_no_ticker"]))
    return stocks, stats


def _latest(pitches: list[Pitch]) -> Pitch:
    return max(pitches, key=lambda p: p.date or "")


def club_target(st: SheetStock) -> tuple[float | None, Pitch | None]:
    """가장 최근 발표 중 목표가가 있는 것."""
    for p in st.pitches:  # 최신순 정렬됨
        if p.target:
            return p.target, p
    return None, None
