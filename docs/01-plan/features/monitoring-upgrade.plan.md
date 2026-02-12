# Plan: monitoring-upgrade (모니터링 및 외부 연동 업그레이드)

## 1. 개요

| 항목 | 내용 |
|------|------|
| Feature | monitoring-upgrade |
| 목표 | 엑셀→구글 스프레드시트 전환, 텔레그램 알림(스크린샷/수료증), 실시간 모니터링 |
| 기반 | 기존 auto-education (강의+퀴즈+설문 자동화) 코드 유지 |
| 기술 스택 | Python, Selenium, Google Sheets (Web App), Telegram Bot API |
| 우선순위 | High |

## 2. 현재 상태 (AS-IS)

```
runner.py
├── tkinter 파일 다이얼로그로 .xlsx 파일 선택
├── openpyxl로 엑셀에서 ID/PW 읽기
├── 계정별 순차 실행 (create_driver → login → run_lectures)
└── 콘솔 출력만 (외부 알림 없음)
```

**한계점:**
- 엑셀 파일을 수동으로 관리해야 함 (다른 PC에서 접근 불편)
- 실행 상태를 확인하려면 콘솔을 직접 봐야 함
- 수료증 다운로드/전달이 수동

## 3. 목표 상태 (TO-BE)

```
runner.py (개선)
├── Google Spreadsheet에서 계정 목록 읽기 (Web App 방식)
├── Google Spreadsheet에 진행 상태 실시간 업데이트
├── 계정별 작업 완료 시 → 텔레그램 알림 (스크린샷 첨부)
├── 수료증 PDF 다운로드 → 텔레그램 전송
└── 에러/예외 발생 시 → 텔레그램 알림
```

## 4. 요구사항

### 4.1 핵심 기능 (Must Have)

| ID | 기능 | 설명 |
|----|------|------|
| M-01 | 구글 스프레드시트 읽기 | Web App(배포된 Apps Script)으로 계정 목록 가져오기. API Key 불필요 |
| M-02 | 구글 스프레드시트 쓰기 | 진행 상태(시작/완료/에러) 실시간 업데이트 |
| M-03 | 텔레그램 봇 알림 | 계정별 작업 완료/실패 시 메시지 전송 |
| M-04 | 강의실 스크린샷 | 각 계정 작업 완료 시 Selenium 스크린샷 → 텔레그램 전송 |
| M-05 | 수료증 PDF 다운로드 | 수료 완료 후 마이페이지에서 수료증 PDF 다운로드 |
| M-06 | 수료증 텔레그램 전송 | 다운로드한 PDF를 텔레그램 문서로 전송 |

### 4.2 확장 기능 (Should Have)

| ID | 기능 | 설명 |
|----|------|------|
| S-01 | 텔레그램 원격 제어 | /status (현재 진행 상태 조회), /restart (실패 계정 재시작) |
| S-02 | 멀티 PC 중복 방지 | 계정 완료 시 doPost로 상태 변경 → 다른 PC에서 "진행중/완료" 계정 건너뜀 |
| S-03 | 에러 스크린샷 | 오류 발생 시 해당 화면 스크린샷 → 텔레그램 전송 |
| S-04 | 실패 자동 재시도 큐 | 실패 계정 마킹 → /restart 또는 다음 실행 시 우선 재시도 |

## 5. 기술 설계

### 5.1 구글 스프레드시트 연동 (Web App 방식)

**왜 API가 아니라 Web App인가?**
- Google API 키/OAuth 설정이 복잡하고 갱신 필요
- Apps Script Web App은 URL 하나로 GET/POST 가능
- 서비스 계정 없이도 동작

**구조:**
```
[Google Apps Script - Web App]
  ├── doGet()  → 스프레드시트에서 계정 목록 JSON 반환 (상태가 "대기" 또는 빈 행만)
  ├── doPost() → 상태 업데이트 수신 (계정ID, 상태, 메시지, 타임스탬프)
  └── 배포: "누구나 접근 가능" 웹 앱으로 배포

[Python - runner.py]
  ├── requests.get(WEB_APP_URL)  → "대기" 상태 계정만 가져오기
  └── requests.post(WEB_APP_URL) → 계정 완료/실패 시 상태 변경
```

**멀티 PC 동시 실행 흐름:**
```
PC-A: doGet() → [{user1: 대기}, {user2: 대기}, {user3: 대기}]
PC-A: user1 시작 → doPost(user1, "진행중")
PC-B: doGet() → [{user2: 대기}, {user3: 대기}]  ← user1은 이미 진행중이라 제외
PC-A: user1 완료 → doPost(user1, "수료완료")
PC-A: user2 시작 → doPost(user2, "진행중")
PC-B: doGet() → [{user3: 대기}]  ← user1 완료, user2 진행중이라 제외
```

**스프레드시트 구조:**
| A (user_id) | B (user_pw) | C (telegram_chat_id) | D (상태) | E (진행률) | F (최종 업데이트) | G (비고) |
|-------------|-------------|---------------------|----------|-----------|-----------------|---------|
| testuser1 | pass123 | 123456789 | 수료완료 | 100% | 2026-02-12 14:30 | 수료증 전송됨 |
| testuser2 | pass456 | 123456789 | 진행중 | 60% | 2026-02-12 14:25 | 6/10차시 |
| testuser3 | pass789 | 987654321 | 대기 | | | |
| testuser4 | pass000 | 987654321 | 실패 | 30% | 2026-02-12 13:00 | 세션 만료 |

**상태 값:**
- `대기` (또는 빈칸): 아직 시작 안 함 → doGet()에 포함
- `진행중`: 현재 어떤 PC에서 처리 중 → doGet()에서 제외
- `수료완료`: 모든 과정 완료 → doGet()에서 제외
- `실패`: 에러로 중단 → /restart 명령으로 "대기"로 되돌리기 가능

### 5.2 텔레그램 봇 연동

```
[Telegram Bot API]
  ├── sendMessage()    → 텍스트 알림 (시작/완료/에러)
  ├── sendPhoto()      → 스크린샷 전송 (base64 또는 파일)
  └── sendDocument()   → 수료증 PDF 전송

[Python 모듈]
  telegram_bot.py
  ├── send_message(chat_id, text)
  ├── send_screenshot(chat_id, image_bytes)
  └── send_pdf(chat_id, pdf_bytes, filename)
```

**텔레그램 알림 시점:**
1. 계정 작업 시작 시 → "🔄 [user_id] 교육 수강 시작"
2. 각 과정 완료 시 → "✅ [과정명] 완료 (강의+퀴즈+설문)" + 스크린샷
3. 수료증 발급 시 → "📄 수료증" + PDF 첨부
4. 에러 발생 시 → "❌ [user_id] 오류: 메시지" + 에러 스크린샷
5. 전체 완료 시 → "🎉 전체 N개 계정 처리 완료" + 요약

### 5.3 수료증 PDF 처리 (CDP 방식)

**사이트 동작 분석:**
```html
<!-- 마이페이지 수료 과정의 수료증 버튼 -->
<a href="#" onclick="getCertificateSource('CURRI0000004','2024','4','U','2',1,'A','100');">
  수료증보기
</a>
```
- `getCertificateSource()` 호출 → 새 창에 수료증 HTML 렌더링 → `window.print()` 호출
- 사용자가 "PDF로 저장" 프린터 선택 후 수동 저장하는 구조

**자동화 흐름 (Chrome DevTools Protocol):**
```
1. 마이페이지에서 getCertificateSource(...) JS 실행
2. 새 창(수료증 페이지)으로 전환
3. CDP Page.printToPDF 명령으로 PDF 바이트 직접 추출 (프린트 대화상자 안 뜸)
4. 로컬 파일로 임시 저장 (py파일 위치/certificates/ 폴더)
5. 텔레그램 sendDocument()로 PDF 전송
6. 로컬 임시 파일 삭제
7. 수료증 창 닫고 원래 창으로 복귀
```

**핵심 코드:**
```python
import base64, os

def download_certificate_pdf(driver, cert_js, user_id):
    """CDP로 수료증 PDF 추출 → 파일 저장 → bytes 반환"""
    original_window = driver.current_window_handle

    # 1. 수료증 페이지 열기
    driver.execute_script(cert_js)
    time.sleep(3)

    # 2. 새 창으로 전환
    for handle in driver.window_handles:
        if handle != original_window:
            driver.switch_to.window(handle)
            break

    time.sleep(2)

    # 3. CDP로 PDF 추출 (프린트 다이얼로그 없이)
    pdf_data = driver.execute_cdp_cmd('Page.printToPDF', {
        'printBackground': True,
        'preferCSSPageSize': True,
        'paperWidth': 8.27,   # A4
        'paperHeight': 11.69, # A4
    })
    pdf_bytes = base64.b64decode(pdf_data['data'])

    # 4. 임시 파일 저장
    cert_dir = os.path.join(os.path.dirname(__file__), 'certificates')
    os.makedirs(cert_dir, exist_ok=True)
    filename = f"수료증_{user_id}.pdf"
    filepath = os.path.join(cert_dir, filename)
    with open(filepath, 'wb') as f:
        f.write(pdf_bytes)

    # 5. 창 닫고 복귀
    driver.close()
    driver.switch_to.window(original_window)

    return filepath, pdf_bytes, filename
```

**텔레그램 전송 후 파일 삭제:**
```python
# 전송
send_pdf(chat_id, pdf_bytes, filename)
# 삭제
os.remove(filepath)
```

### 5.4 스크린샷 흐름

```python
# Selenium 내장 스크린샷
screenshot_bytes = driver.get_screenshot_as_png()
# → 바로 텔레그램 sendPhoto()로 전송
```

### 5.5 텔레그램 원격 제어

**구현 방식: Polling (별도 스레드)**
```
[메인 스레드]                    [텔레그램 Polling 스레드]
runner.py 실행                   getUpdates() 주기적 호출
  ├── 계정1 처리 중...            ├── /status 수신 → 현재 상태 응답
  ├── 계정2 처리 중...            ├── /restart 수신 → 실패 계정 "대기"로 변경 (구글시트)
  └── 공유 상태 객체 참조  ←──→   └── 공유 상태 객체 업데이트
```

**지원 명령어:**
| 명령어 | 동작 |
|--------|------|
| `/status` | 현재 처리 중인 계정, 진행률, 남은 계정 수 응답 |
| `/restart` | 구글시트에서 "실패" 상태 계정을 "대기"로 변경 → 다음 루프에서 재처리 |

**공유 상태 객체:**
```python
import threading

class RunnerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_user = None       # 현재 처리 중인 계정
        self.current_course = None     # 현재 과정명
        self.progress = ""             # "3/10차시"
        self.total_accounts = 0
        self.completed_accounts = 0
        self.failed_accounts = []
```

## 6. 파일 구조 (변경 계획)

```
PythoncsoCPedu/
├── config.py              # (수정) TELEGRAM_*, GSHEET_* 설정 추가
├── main.py                # (유지) 핵심 강의 로직 변경 없음
├── tryTest.py             # (유지) 퀴즈 로직 변경 없음
├── runner.py              # (대폭 수정) 엑셀→구글시트, 텔레그램 연동
├── telegram_bot.py        # (신규) 텔레그램 봇 유틸리티
├── gsheet.py              # (신규) 구글 스프레드시트 Web App 통신
├── certificate.py         # (신규) 수료증 PDF 다운로드/처리
├── requirements.txt       # (수정) requests 추가
├── .env                   # (수정) TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GSHEET_WEB_APP_URL 추가
└── google_apps_script/
    └── Code.gs            # (신규) Apps Script 소스 (참고용)
```

## 7. 구현 순서

```
Phase 1: 인프라 셋업
  Step 1: 텔레그램 봇 생성 (@BotFather) + .env 설정
  Step 2: telegram_bot.py 구현 (send_message, send_photo, send_document)
  Step 3: Google Apps Script 작성 (doGet: 대기 계정 조회, doPost: 상태 업데이트)
  Step 4: Apps Script Web App 배포 + .env에 URL 등록
  Step 5: gsheet.py 구현 (fetch_pending_accounts, update_status)

Phase 2: runner.py 리팩토링
  Step 6: 엑셀 읽기 → gsheet.fetch_pending_accounts() 교체
  Step 7: 계정 시작 시 doPost("진행중"), 완료 시 doPost("수료완료"/"실패")
  Step 8: 작업 시작/완료/에러 시 텔레그램 알림 추가
  Step 9: 각 계정 완료 시 강의실 화면 스크린샷 + 텔레그램 전송

Phase 3: 수료증 처리
  Step 10: getCertificateSource() JS 파라미터 추출 로직 구현
  Step 11: certificate.py 구현 (CDP Page.printToPDF로 PDF 추출)
  Step 12: 수료증 PDF → 텔레그램 전송 → 로컬 파일 삭제

Phase 4: 텔레그램 원격 제어
  Step 13: RunnerState 공유 상태 객체 구현
  Step 14: 텔레그램 Polling 스레드 (getUpdates 루프)
  Step 15: /status 명령 → 현재 진행 상태 응답
  Step 16: /restart 명령 → 구글시트 "실패" → "대기" 변경

Phase 5: 안정화
  Step 17: 에러 시 스크린샷 자동 전송
  Step 18: 계정별 텔레그램 chat_id 지원 (스프레드시트 C열)
  Step 19: 네트워크 에러/타임아웃 시 재시도 로직 (gsheet, telegram)
```

## 8. 향후 확장 가능 기능

| # | 기능 | 설명 | 난이도 |
|---|------|------|--------|
| 1 | **구글시트 조건부 서식** | Apps Script로 상태별 색상 자동 적용 (대기=흰, 진행중=노랑, 완료=초록, 실패=빨강) | 하 |
| 2 | **텔레그램 로그 채널** | 별도 채널에 상세 실행 로그 스트리밍 (디버깅용) | 하 |
| 3 | **수료 만료 알림** | 수료 기한 D-7, D-3, D-1 자동 알림 → 텔레그램 전송 | 하 |

## 9. 의존성 변경

```
# 기존 유지
selenium
webdriver-manager
python-dotenv

# 추가
requests          # 텔레그램 API + Google Web App 통신

# 제거 가능
openpyxl          # 구글시트 전환 후 불필요 (하위호환 위해 유지도 가능)
```

## 10. 환경 변수 (.env 추가)

```
# 기존
USER_ID=...
USER_PW=...

# 텔레그램
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGhIjKlMnOpQrStUvWxYz
TELEGRAM_CHAT_ID=123456789

# 구글 스프레드시트 Web App
GSHEET_WEB_APP_URL=https://script.google.com/macros/s/xxxxx/exec
```

## 11. 리스크 및 대응

| 리스크 | 대응 방안 |
|--------|----------|
| Google Apps Script 일일 호출 제한 (20,000회) | 상태 업데이트 배치 처리 (차시 단위가 아닌 과정 단위) |
| 텔레그램 API rate limit (30msg/sec) | 계정 간 1초 딜레이, 대량 메시지 시 큐 처리 |
| Web App URL 노출 시 보안 | URL에 비밀 토큰 파라미터 추가, IP 화이트리스트 |
| 수료증 PDF 다운로드 방식 변경 | fetch 방식과 파일 다운로드 방식 둘 다 구현 |
| 구글시트 동시 쓰기 충돌 | Apps Script 내 LockService 활용 |
