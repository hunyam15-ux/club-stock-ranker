"""화면 확인용 데모 사이트 생성 (네트워크 불필요).

  python -m tests.make_demo /tmp/demo   →  /tmp/demo 에 site 복사 + 가짜 데이터
  cd /tmp/demo && python -m http.server 8000

※ 모든 숫자는 난수로 만든 가짜 값이며 화면 상단에 '데모 데이터' 경고가 뜹니다.
   실제 배포(site/data)에는 절대 쓰이지 않습니다.
"""
import csv
import io
import json
import shutil
import sys
from pathlib import Path

from collector import consensus, main as M, market

from . import fake_sources as F

ROOT = Path(__file__).resolve().parent.parent
SECTORS = ["반도체", "반도체", "반도체", "조선", "조선", "화장품", "화장품", "방산", "2차전지", "금융", "자동차", "자동차", "소비재", "리츠"]


def demo_csv() -> str:
    W = 28
    hdr = ['', '번호', '섹터', '기업명', 'Q&A', '발표일', '티커', '투자아이디어', 'Risk', '발표일 주가', '현재가', '1W', '1M', '3M',
           '6M', '12M', '발표일~수익률', '목표가', '근거', '비고( 주가희석요소 및 경영진  Check 필수 )', '자료첨부', '기타',
           '시가총액(억원/억달러)', 'PER', '차트(365일)', '52주 고가', '52주 저가', '차이']
    rows = [[''] * W, hdr]
    for i, sec in enumerate(SECTORS, 1):
        code = f"{900000 + i * 7:06d}"
        last = F.fake_daily(None, code)[-1][4]
        r = [''] * W
        r[0], r[1], r[2], r[3] = ["데모A", "데모B", "데모C"][i % 3], str(i), sec, f"데모종목{i:02d}"
        r[5], r[6] = f"2025-{(i % 9) + 1:02d}-15", f"KRX:{code}"
        r[7] = f"(데모) 투자아이디어 예시 {i}\n- 포인트 1\n- 포인트 2"
        r[8] = "(데모) CB 오버행 가능성" if i % 4 == 0 else "(데모) 업황 둔화"
        r[9] = f"{round(last * 0.8):,}"
        r[17] = f"{round(last * (0.9 + (i % 5) * 0.15), -2):,.0f}" if i % 6 else "N/A"
        r[18] = "(데모) 목표 PER 기준"
        r[19] = "(데모) 경영진 체크 메모"
        rows.append(r)
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def main(out: str):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out, ignore=shutil.ignore_patterns("data"))
    text = demo_csv()
    M.fetch_csv = lambda *a, **k: text
    market.fetch_daily, market.fetch_naver_summary, market.fetch_naver_main = F.fake_daily, F.fake_summary, F.fake_main
    consensus.fetch_fnguide = F.fake_fnguide
    assert M.main(["--out", str(out / "data")]) == 0
    p = out / "data" / "latest.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["meta"]["demo"] = True
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    print("demo ->", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/demo")
