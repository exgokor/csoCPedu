# Plan: auto-education (교육 자동 수강 크롤러)

## 1. 개요

| 항목 | 내용 |
|------|------|
| Feature | auto-education |
| 목표 | 한국제약바이오협회 보수교육 사이트 자동 로그인 + 영상 자동재생 |
| 대상 사이트 | https://www.kpbma-cpedu.com |
| 기술 스택 | Python, Selenium (브라우저 자동화) |
| 우선순위 | High |

## 2. 요구사항

### 2.1 핵심 기능 (Must Have)

| ID | 기능 | 설명 |
|----|------|------|
| F-01 | 자동 로그인 | userId/passwd 변수로 입력받아 `/login/goLoginPrcAjax` POST 로그인 |
| F-02 | 수강 목록 조회 | 마이페이지에서 수강 가능한 교육 목록 파싱 |
| F-03 | 영상 자동 재생 | 교육 영상 페이지 진입 후 자동 재생 및 완료 대기 |
| F-04 | 순차 수강 | 영상 완료 후 다음 강의로 자동 이동 |
| F-05 | 진행 상태 출력 | 현재 수강 중인 강의명, 진행률 콘솔 출력 |

### 2.2 선택 기능 (Nice to Have)

| ID | 기능 | 설명 |
|----|------|------|
| F-06 | 중단/재개 | 프로그램 종료 후 이어서 수강 |
| F-07 | 수강 완료 알림 | 전체 수강 완료 시 알림 |

## 3. 기술 분석

### 3.1 대상 사이트 구조

```
로그인: POST /login/goLoginPrcAjax
  - userId: 아이디
  - passwd: 비밀번호

교육 상세: /sub/education/educationUserDetail?p={encoded_param}
마이페이지: /sub/myPage/
기술: jQuery 기반, AJAX 통신, Slick/Swiper UI
```

### 3.2 기술 선택

| 기술 | 선택 이유 |
|------|----------|
| Selenium | 영상 재생은 실제 브라우저 필요 (JS 렌더링, 동영상 플레이어 제어) |
| Chrome WebDriver | 가장 범용적, ChromeDriver 자동 관리 가능 |
| python-dotenv | ID/PW 등 민감정보 `.env` 파일로 분리 |

### 3.3 프로젝트 구조 (예상)

```
AutoEduCation/
├── .env                  # ID/PW (gitignore 대상)
├── .env.example          # 환경변수 템플릿
├── main.py               # 진입점
├── config.py             # 설정 로드
├── crawler/
│   ├── __init__.py
│   ├── auth.py           # 로그인 처리
│   ├── course.py         # 수강 목록 조회
│   └── player.py         # 영상 재생 제어
├── requirements.txt      # 의존성
└── docs/                 # PDCA 문서
```

## 4. 리스크 및 고려사항

| 리스크 | 대응 방안 |
|--------|----------|
| 사이트 구조 변경 | CSS Selector를 변수화하여 유지보수 용이하게 |
| 영상 플레이어 제어 | JS 실행으로 플레이어 직접 제어, 또는 클릭 이벤트 시뮬레이션 |
| 세션 만료 | 주기적 세션 체크, 만료 시 재로그인 |
| 팝업/모달 | 예외 처리로 팝업 자동 닫기 |

## 5. 구현 순서

```
Step 1: 프로젝트 셋업 (환경변수, 의존성)
Step 2: 자동 로그인 구현 (F-01)
Step 3: 수강 목록 조회 (F-02)
Step 4: 영상 자동 재생 (F-03)
Step 5: 순차 수강 연결 (F-04)
Step 6: 진행 상태 출력 (F-05)
Step 7: 통합 테스트 및 예외 처리
```

## 6. 의존성

```
selenium
webdriver-manager
python-dotenv
```
