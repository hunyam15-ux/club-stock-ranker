# 모임 매수 순위 (국내주식)

투자모임 구글 시트에 발표된 **국내 종목**을 현재가 기준으로 점수를 매겨
🟢 개꿀(적극 매수) / 🟡 분할매수 / ⚪ 관망 / 🔴 비싸다(매수 금지) 등급과 매수 순위,
종목별 매매 전략(분할매수·손절·익절·비중), 권장 현금 비중을 보여주는 정적 웹사이트입니다.

> ⚠️ 투자 참고용이며 투자 권유가 아닙니다.

```
collector/      Python 데이터 수집·점수 계산
  sheet.py        모임 시트 CSV 읽기(메인 표만, 6자리 국내 코드만)
  market.py       네이버 금융 시세·지표·일봉 (pykrx 보조)
  consensus.py    FnGuide 실적·추정치 (네이버 보조)
  dart.py         DART: 확정 실적·부채비율·CB/BW/유상증자·최대주주
  scoring.py      점수·등급·한 줄 근거
  strategy.py     분할매수·손절·익절·비중·현금 비중
  main.py         전체 실행 → site/data/*.json
config/
  scoring.yaml    ★ 점수 가중치·등급 기준·매매 규칙 (여기만 고치면 됨)
  settings.yaml   시트 ID/gid, 수집 옵션
site/           화면(HTML/JS/CSS, 빌드 불필요) + data/(자동 생성)
tests/          단위·통합 테스트, 데모 데이터 생성기
.github/workflows/update.yml   평일 16:40 KST 자동 갱신 + GitHub Pages 배포
```

---

## 1. 처음 배포하기 (GitHub Pages, 10분)

1. GitHub에서 새 저장소를 만들고(예: `club-stock-ranker`) 이 폴더 전체를 올립니다.
   ```bash
   cd club-stock-ranker
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<아이디>/club-stock-ranker.git
   git push -u origin main
   ```
2. **DART API 키 등록**: [opendart.fss.or.kr](https://opendart.fss.or.kr) → 인증키 신청(무료) →
   저장소 **Settings → Secrets and variables → Actions → New repository secret**
   이름 `DART_API_KEY`, 값에 키 입력. (키는 코드에 절대 넣지 않습니다. 없어도 사이트는 동작하고 DART 항목만 N/A)
3. **Pages 켜기**: Settings → Pages → Build and deployment → Source를 **GitHub Actions**로 선택.
4. **첫 수집 실행**: Actions 탭 → `데이터 갱신 및 배포` → **Run workflow**.
   3~5분 뒤 완료되면 주소가 나옵니다: `https://<아이디>.github.io/club-stock-ranker/`

이후에는 **평일 16:40(KST)** 에 자동으로 갱신·배포됩니다.

주의
- 무료 계정의 GitHub Pages는 **공개 저장소**에서만 됩니다. 사이트 URL을 아는 사람은 누구나 볼 수 있고,
  시트의 투자아이디어·Risk 메모도 함께 공개됩니다. 공개를 원치 않으면 Vercel 비밀번호 보호나 비공개 Pages(유료) 등을 쓰세요.
- 시트 공유 설정이 **링크가 있는 모든 사용자: 뷰어** 여야 CSV로 읽힙니다.
- Vercel을 쓰고 싶다면: 저장소를 Vercel에 연결하고 Framework = Other, Output Directory = `site`.
  데이터 갱신은 위 GitHub Actions가 계속 담당(커밋 → Vercel 자동 재배포)하므로 Pages 단계만 빼면 됩니다.

## 2. 로컬 실행

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DART_API_KEY=발급받은키                          # Windows: set DART_API_KEY=...
python -m collector.main                                # site/data/ 생성 (테스트: --limit 5)
cd site && python -m http.server 8000                   # http://localhost:8000
```

네트워크 없이 화면만 보려면 가짜 데이터로 데모를 만들 수 있습니다(화면에 '데모 데이터' 경고 표시):
```bash
python -m tests.make_demo /tmp/demo && cd /tmp/demo && python -m http.server 8000
```
테스트: `python -m pytest -q`

## 3. 데이터 갱신 방법

| 방법 | 설명 |
|---|---|
| 자동 | 평일 16:40 KST (`.github/workflows/update.yml`의 cron `40 7 * * 1-5`, UTC 기준) |
| 수동 | Actions → `데이터 갱신 및 배포` → Run workflow |
| 시간 변경 | cron 수정. 예) 17:30 KST = `30 8 * * 1-5` |

안전장치
- 시트를 못 읽으면 **즉시 중단**(기존 사이트 그대로 유지, Actions 실패로 표시).
- 현재가를 실시간 원천(네이버/pykrx)에서 못 가져온 종목이 절반을 넘으면 중단.
- 못 가져온 값은 만들어 내지 않고 **N/A**로 표시합니다. 값마다 출처를 기록하고, 화면 상단에 갱신 시각과 시세 기준일이 나옵니다.

데이터 원천과 우선순위

| 항목 | 1순위 | 보조 |
|---|---|---|
| 현재가·등락률 | 네이버 금융 | 일봉 종가 → 시트 현재가 |
| 시총·PER·PBR·배당·52주 고저 | 네이버 금융 | pykrx → 시트 |
| 컨센서스 목표가 | 네이버(FnGuide 컨센서스) | FnGuide |
| 올해·내년 매출·영업이익·EPS(E) | FnGuide Financial Highlight | 네이버 기업실적분석 |
| 확정 실적·부채비율 | DART 단일회사 주요계정 | FnGuide/네이버 연간 |
| CB·BW·유상증자 | DART 주요사항보고 | — |
| 최대주주 지분 | DART 최대주주 현황 | — |
| 섹터 PER 기준 | 네이버 동일업종 PER | 모임 섹터 중앙값 → 전체 중앙값 |
| 코스피 추세 | 네이버 지수 일봉 | — |

알아둘 점
- **컨센서스 상향/하향**: 과거 추정치를 무료로 받을 곳이 없어 매일 `site/data/history/`에 스냅샷을 저장해 비교합니다.
  운영 시작 후 약 15일이 지나야 값이 생기고, 그전에는 N/A로 두고 EPS 성장률만으로 모멘텀을 계산합니다.
- **잠재 희석률**: 최근 3년 CB·BW, 1년 유상증자 *발행 결정* 공시의 '주식총수 대비 비율' 합계입니다.
  이미 전환·상환된 물량을 빼지 않은 보수적 추정이므로 상세 화면의 공시 목록으로 확인하세요.
- 시트의 두 번째 표(발표자/종목명/종목코드 형식)와 해외 종목, 티커가 없는 섹터 행은 제외합니다.
  같은 종목을 여러 번 발표했다면 하나로 합치고, 목표가는 **가장 최근 발표의 목표가**를 씁니다. 메모는 날짜별로 이어 붙입니다.
- ETF(예: SOL 반도체전공정)는 PER·컨센서스가 없어 대부분 N/A → 보통 ⚪(데이터 부족)로 나옵니다.
- 네이버·FnGuide 화면 구조가 바뀌면 해당 항목만 N/A가 됩니다. Actions 로그의 `WARNING` 줄과
  상세 화면 하단의 '수집 실패 항목'을 보고 `market.py`/`consensus.py`의 파서를 고치면 됩니다.

## 4. 점수 가중치·규칙 수정 방법

`config/scoring.yaml`만 수정 → 커밋·푸시 → Actions **Run workflow**(수동 실행해야 새 점수로 다시 계산됩니다).

```yaml
weights:            # 비율로 계산(합이 100일 필요 없음)
  upside: 35        # 업사이드
  valuation: 25     # 섹터 대비 PER·PBR, Forward PER
  momentum: 20      # 내년 EPS 성장률, 컨센서스 변화
  price_position: 20  # 52주 위치, 1M·3M 수익률
grades: {green: 65, yellow: 52, white: 40}   # 등급 컷
upside: {target_source: club_first}           # 모임 목표가 우선 | consensus_first | average
risk: {max_total: 25, dilution_points: 12, debt_points: 8, ...}
strategy: {entry_steps_pct: [0, -5, -10], stop_loss_pct: -8, max_weight_pct: 15, ...}
cash: {base_pct: {above_both: 20, mixed: 35, below_both: 50}, ...}
```

계산 방식 요약
- 각 항목 0~100점(구간 선형). 예: 업사이드 −10% 이하 0점, +50% 이상 100점.
- 총점 = 항목 점수 가중평균 − 리스크 감점(희석·부채비율·시트 Risk/비고의 키워드).
- **N/A 항목은 0점이 아니라 계산에서 빠지고** 나머지 가중치로 다시 나눕니다. 그 대신 데이터 충족률이 60% 미만이면 최고 ⚪.
- 현재가 ≥ 목표가면 점수와 상관없이 🔴.
- 순위는 등급 순 → 같은 등급 안에서 총점 순.
- 권장 비중 ∝ 등급 배수 × 총점 ÷ 60일 변동성, 한 종목 최대 15%, 합계는 (100 − 권장 현금 비중)%.
- 매매 원칙 페이지는 이 설정값을 그대로 읽어 표시하므로 설정을 바꾸면 설명도 함께 바뀝니다.
