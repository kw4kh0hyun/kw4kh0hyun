# StatementKit — 은행 명세서 PDF → CSV, 업로드 없이

은행 명세서 PDF를 CSV · QuickBooks · Xero · OFX · QIF로 바꿔 주는 웹 서비스입니다.
**파일이 브라우저 밖으로 나가지 않고**, 모든 거래를 **잔액(running balance)으로 검증**합니다.

```bash
npm install
LICENSE_SECRET=$(openssl rand -hex 32) npm start   # http://localhost:3000
npm test                                           # 파서·내보내기·라이선스 테스트 14개
```

---

## 1. 왜 이 문제인가 (조사 요약)

| 근거 | 내용 |
|---|---|
| 지불 의사가 증명됨 | 1인 개발 제품 *Bank Statement Converter*는 이 기능 하나로 MRR $1k(10개월) → $5k(2022.10) → $7k(2023.03) → $10k+ 까지 공개 성장 ([IH $5k](https://www.indiehackers.com/product/bank-statement-converter/hit-5000-mrr--NF8OlUNHQn2Y0rzLu35), [IH $7k](https://www.indiehackers.com/product/bank-statement-converter/hit-7000-mrr--NP_cygGl3FILZco8qzY), [창업자 블로그](https://bankstatementconverter.com/blog/posts/2022-02-25-zero-to-one-thousand-mrr), [Starter Story](https://www.starterstory.com/stories/bankstatementconverter)) |
| 누가 겪나 | r/Bookkeeping · r/Accounting · r/smallbusiness · r/freelance · r/personalfinance · r/ynab — 은행이 CSV를 90일치만 주거나 아예 안 줘서, 세금 신고·장부 정리·대출 서류 때 PDF 명세서를 손으로 옮기는 사람들 |
| 기존 제품의 불만 | ① **민감한 은행 명세서를 낯선 서버에 업로드**해야 함 — 클라우드 변환기들의 보관 기간이 24시간~5년으로 제각각 ([조사](https://localextract.app/blog/how-to-convert-bank-statement-pdf-to-csv)) ② 변환이 틀려도 알 방법이 없음 ③ 한 번 쓰려는데 **구독**을 강요 |

> 참고: 이 작업 환경에서는 reddit.com 접속이 차단되어 레딧 원문을 직접 읽지 못했습니다. 위 근거는 공개 매출 기록과 2차 자료이고, 출시 전에 아래 4절의 방법으로 레딧에서 직접 검증하는 것을 권장합니다.

## 2. 차별점 = 기존 불만에 대한 답

1. **업로드 없음 (기술적으로 보장)** — PDF.js로 브라우저 안에서 파싱. 서버는 페이지 전달과 라이선스 확인만 함.
   엄격한 CSP(`connect-src 'self'`)로 페이지가 다른 사이트에 데이터를 보낼 수 없고, 페이지를 연 뒤 오프라인이 되어도 동작합니다.
   → 회계사가 고객 데이터를 다룰 때 *"제3자 업로드 금지"* 규정과 충돌하지 않음.
2. **잔액 검증** — 모든 행에서 `이전 잔액 + 금액 = 인쇄된 잔액`을 확인하고, `시작 잔액 + 합계 = 마감 잔액`까지 맞춰 봄. 안 맞는 행은 노란색으로 표시하고 그 자리에서 고칠 수 있음.
3. **구독 없는 기간권** — $9 / 30일, 자동 갱신 없음 (가격·기간은 환경변수로 변경).

## 3. 기능

| | Free | Pro 기간권 |
|---|---|---|
| 미리보기 · 잔액 검증 | 무제한 | 무제한 |
| CSV 내보내기 | 하루 1개 명세서, 3페이지까지 | 무제한 |
| 여러 파일 한 번에 (12개월치 병합·정렬) | – | ✓ |
| QuickBooks CSV · Xero CSV · OFX · QIF | – | ✓ |

지원 레이아웃 (테스트로 검증됨):
- 영국식 `Paid out / Paid in / Balance`, 하루 한 번만 날짜 표시, 여러 줄 설명, 여러 페이지
- 미국식 부호 있는 `Amount` 열 + `$`, `MM/DD`
- **최신 거래가 위에 오는** 명세서 (자동 감지 후 검증)
- 헤더 없는 유럽식 `1.234,56`, 부호 없는 금액 → 잔액 변화로 입출금 판별
- 비밀번호 걸린 PDF(브라우저에서 비밀번호 입력), 스캔본은 감지해서 안내
- 날짜: `2026-03-05`, `05/03/2026`, `5 Mar`, `Mar 5, 2026`, `03/05` … DD/MM vs MM/DD 자동 판별, 연말→연초 연도 넘김 처리
- CSV 수식 주입(`=HYPERLINK…`) 방어, OFX FITID 고정(재가져오기 시 중복 방지)

## 4. 수익화까지 남은 일 (사람이 해야 하는 것)

1. **결제 연결 (Stripe, 코드 변경 불필요)**
   - Stripe에서 $9 일회성 상품의 *Payment Link* 생성 → 결제 후 리디렉션 URL을 `https://<도메인>/?session_id={CHECKOUT_SESSION_ID}` 로 설정
   - 환경변수: `STRIPE_PAYMENT_LINK`, `STRIPE_SECRET_KEY`(제한 키: Checkout Sessions 읽기만), `LICENSE_SECRET`(긴 랜덤 문자열), 선택 `PRICE_LABEL`, `PASS_DAYS`
   - 결제가 끝나면 서버가 Stripe에서 결제 여부를 확인하고 서명된 라이선스 키를 발급 → 브라우저에 저장. 고객 응대용 수동 발급: `LICENSE_SECRET=… npm run issue-key -- email 30`
2. **배포** — Node 18+ 어디든 (Render, Fly.io, Railway 등). `npm install --omit=dev && npm start`. 데이터베이스 없음.
3. **레딧 검증 → 출시**
   - 먼저 r/Bookkeeping, r/Accounting, r/smallbusiness 에서 `bank statement pdf`, `convert statement to csv`, `statement to excel` 검색 → 최근 질문 글에 **도움이 되는 답**(은행 CSV 다운로드 방법 등)을 먼저 달고, 맞는 경우에만 도구를 언급
   - 각 서브레딧 자기홍보 규칙 확인 필수. r/SideProject, r/InternetIsBeautiful 는 "업로드 없는 변환기"로 직접 소개 가능
   - 실제 은행 명세서에서 실패한 레이아웃 제보를 받아 파서 보강 (잔액 검증 덕분에 실패가 바로 드러남)
4. **SEO 랜딩 페이지** — "Chase statement to CSV", "Barclays statement to Excel" 같은 은행별 페이지가 경쟁 제품의 주요 유입원.

## 5. 한계 (정직하게)

- 실제 은행 PDF가 아니라 **합성 명세서 4종**으로 검증했습니다. 실제 은행별 레이아웃에서는 추가 보정이 필요할 수 있습니다 — 그래서 잔액 검증과 행 편집 기능을 넣었습니다.
- 스캔본(OCR) 미지원.
- 무료 한도는 브라우저(localStorage)에서만 적용되므로 우회 가능합니다. 이 가격대에서는 의도된 트레이드오프입니다 (서버에 파일을 보내지 않는 것이 핵심 가치).

## 구조

```
server.js           정적 파일 + 엄격한 CSP + /api/config, /api/license/claim(Stripe 확인), /api/license/verify
lib/parser.js       위치 기반 텍스트 → 거래 (줄/셀 묶기, 헤더 감지, 날짜·금액 파싱, 부호 추론, 잔액 검증)
lib/pdf-text.js     PDF.js 문서 → 위치 있는 텍스트 (브라우저·Node 공용)
lib/export.js       CSV / QuickBooks / Xero / OFX / QIF
lib/license.js      HMAC 서명 라이선스 키 (DB 불필요)
public/             랜딩 + 변환기 UI
test/               pdfkit으로 합성 명세서 PDF를 만들어 실제 PDF.js로 파싱하는 테스트
```
