import builtins
import json
import random
import re
import time
import sys
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import config

# print에 타임스탬프 자동 추가 (MM/DD HH:MM) - runner.py에서 이미 설정된 경우 스킵
if not hasattr(builtins.print, '_timestamped'):
    _original_print = builtins.print

    def _timestamped_print(*args, **kwargs):
        if kwargs.get("end") == "\r":
            return _original_print(*args, **kwargs)
        ts = datetime.now().strftime("%m/%d %H:%M")
        return _original_print(f"[{ts}]", *args, **kwargs)

    _timestamped_print._timestamped = True
    builtins.print = _timestamped_print

CONTENTS_LIST_URL = f"{config.BASE_URL}/classRoom/curriContentsListAjax"
ENROLL_LIST_URL = f"{config.BASE_URL}/sub/myPage/currentEnrollListAjax"
SURVEY_URL = f"{config.BASE_URL}/classRoom/findResearchContentsList"

EXTRA_WAIT = 90  # 영상 끝난 후 여유 대기 시간 (1분 30초)
DEFAULT_DURATION = 4200  # 기본 영상 대기시간 (70분)


def create_driver():
    """Chrome 브라우저 드라이버 생성"""
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def login(driver, user_id=None, user_pw=None):
    """자동 로그인 (user_id/user_pw 미지정 시 config에서 읽음)"""
    if user_id is None:
        user_id = config.USER_ID
    if user_pw is None:
        user_pw = config.USER_PW

    print("[1단계] 로그인 페이지 이동...")
    driver.get(config.LOGIN_URL)
    time.sleep(2)

    driver.find_element(By.ID, "userId").send_keys(user_id)
    driver.find_element(By.CSS_SELECTOR, ".ip_pw>input").send_keys(user_pw)

    driver.execute_script("goLogin();")
    time.sleep(3)

    if "goLogin" in driver.current_url:
        print("[오류] 로그인 실패. .env 파일의 ID/PW를 확인하세요.")
        return False

    print("[1단계] 로그인 성공!")
    return True


def check_session(driver):
    """세션이 살아있는지 확인. 로그인 페이지로 튕기면 False."""
    try:
        current_url = driver.current_url
        if "goLogin" in current_url or "login" in current_url.lower():
            return False
        return True
    except Exception:
        return False


def ensure_login(driver, user_id=None, user_pw=None):
    """세션 확인 후 만료됐으면 재로그인. 성공 시 True."""
    if check_session(driver):
        return True
    print("\n  [세션 만료] 재로그인 시도...")
    return login(driver, user_id, user_pw)


def fetch_post(driver, url, params):
    """Selenium 브라우저 내에서 fetch POST 호출 (세션/쿠키 자동 포함)"""
    try:
        result = driver.execute_async_script(
            "var callback = arguments[arguments.length - 1];"
            "var params = new URLSearchParams(arguments[0]);"
            "fetch(arguments[1], {"
            "  method: 'POST',"
            "  headers: {"
            "    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',"
            "    'X-Requested-With': 'XMLHttpRequest'"
            "  },"
            "  body: params.toString()"
            "})"
            ".then(r => r.text())"
            ".then(t => callback(t))"
            ".catch(e => callback('FETCH_ERROR:' + e.message));",
            params, url
        )
        if result and result.startswith("FETCH_ERROR:"):
            print(f"    → fetch 오류: {result}")
            return None
        return json.loads(result)
    except json.JSONDecodeError:
        print(f"    → JSON 파싱 실패! 응답 (앞 300자): {result[:300] if result else 'None'}")
        return None
    except Exception as e:
        print(f"    → fetch 호출 실패: {e}")
        return None


def get_lecture_courses(driver):
    """currentEnrollListAjax API로 미수료 과정 조회"""
    data = fetch_post(driver, ENROLL_LIST_URL, {"pageIndex": "1"})
    if not data:
        print("  → 수강 목록 API 호출 실패!")
        return []

    courses = []
    for item in data.get("dataList", []):
        title = item.get("curriNm", "")
        complete_date = item.get("completeDate", "")
        curri_cd = item.get("curriCd", "")
        curri_year = str(item.get("curriYear", ""))
        curri_term = str(item.get("curriTerm", ""))
        enroll_no = str(item.get("enrollNo", "1"))

        if complete_date:
            print(f"  [수료완료] {title} (수료일: {complete_date}) → 건너뜀")
            continue

        courses.append({
            "title": title,
            "curriCd": curri_cd,
            "curriYear": curri_year,
            "curriTerm": curri_term,
            "enrollNo": enroll_no,
        })

    return courses


def get_pending_lectures(driver, course):
    """curriContentsListAjax API로 미완료 차시 목록 조회
    조건: contentsType='F', openChk='Y', 강의 미완료 OR 퀴즈 미통과
    """
    payload = {
        "curriCd": course["curriCd"],
        "curriYear": course["curriYear"],
        "curriTerm": course["curriTerm"],
    }

    data = fetch_post(driver, CONTENTS_LIST_URL, payload)
    if not data:
        print("    → curriContentsListAjax API 호출 실패!")
        return [], 0

    contents = data.get("dataList", [])

    # 실제 강의(contentsType=F)만 카운트
    all_lectures = [item for item in contents if item.get("contentsType") == "F"]
    total_count = len(all_lectures)

    pending = []
    completed_list = []

    for idx, item in enumerate(all_lectures, 1):
        contents_nm = item.get("contentsNm", "")

        # 강의 완료 판정: curriPercent >= 100 또는 totalTime >= showTime
        curri_percent = item.get("curriPercent", "")
        try:
            percent_val = float(curri_percent) if curri_percent else 0
        except (ValueError, TypeError):
            percent_val = 0

        show_time = item.get("showTime", 0) or 0
        total_time_str = item.get("totalTime", "0") or "0"
        try:
            total_time_val = int(total_time_str)
        except (ValueError, TypeError):
            total_time_val = 0

        lecture_done = (percent_val >= 100) or (show_time > 0 and total_time_val >= show_time)

        # 퀴즈 통과 판정
        quiz_yn = item.get("quizYn", "N")
        quiz_pass = item.get("quizPass", "")
        quiz_needed = (quiz_yn == "Y" and quiz_pass != "P")

        # 강의 완료 AND 퀴즈 불필요(또는 이미 통과) → 건너뜀
        if lecture_done and not quiz_needed:
            completed_list.append((idx, contents_nm))
            continue

        # goContents() JS 구성
        js = (f"goContents('{item.get('courseId','')}','{item.get('contentsId','')}',"
              f"'{item.get('contentsWidth','')}','{item.get('contentsHeight','')}',"
              f"'{item.get('studyStatus','')}','{item.get('totalTime','')}',"
              f"'{item.get('showTime','')}','{item.get('curriPercent','')}',"
              f"'undefined','{item.get('encryptedYn','N')}',"
              f"'{item.get('mediaContentsKey','')}',"
              f"'{item.get('sizeApp','N')}')")

        pending.append({
            "title": contents_nm,
            "enter_js": js,
            "showTime": show_time,
            "totalTime": total_time_val,
            "curriPercent": percent_val,
            "lectureDone": lecture_done,
            # 퀴즈 정보
            "quizYn": quiz_yn,
            "quizPass": quiz_pass,
            "courseId": item.get("courseId", ""),
            "contentsId": item.get("contentsId", ""),
        })

    # 차시 상태 요약 출력
    print(f"  {total_count}개 차시 중 "
          f"완료 {len(completed_list)}개 / 미완료 {len(pending)}개")

    if completed_list:
        print(f"    [완료]")
        for num, name in completed_list:
            print(f"      {num}차시. {name}")
    if pending:
        print(f"    [미완료]")
        for item in pending:
            status_parts = []
            if not item["lectureDone"]:
                status_parts.append(f"강의 {item['curriPercent']}%")
            if item["quizYn"] == "Y" and item["quizPass"] != "P":
                status_parts.append("퀴즈 미통과")
            print(f"      {item['title']} ({', '.join(status_parts)})")

    return pending, total_count


def click_play_button(driver):
    """커스텀 플레이어(kollus)의 재생 버튼 클릭"""
    time.sleep(5)

    # iframe이 있으면 전환
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            driver.switch_to.frame(iframe)
            if driver.find_elements(By.CSS_SELECTOR, "#kollus_player, video, .vjs-big-play-button"):
                print("      → iframe 내부로 전환 완료")
                break
            driver.switch_to.default_content()
    except Exception:
        pass

    # 1) kollus 플레이어의 big play button
    try:
        play_btn = driver.find_element(
            By.CSS_SELECTOR, "#kollus_player button.vjs-big-play-button"
        )
        play_btn.click()
        print("      → 재생 버튼(kollus button) 클릭 완료!")
        time.sleep(2)
        return True
    except Exception:
        pass

    # 2) JS로 kollus button 클릭
    try:
        driver.execute_script(
            "var btn = document.querySelector('#kollus_player button.vjs-big-play-button');"
            "if(btn) btn.click();"
        )
        print("      → JS로 재생 버튼 클릭!")
        time.sleep(2)
        return True
    except Exception:
        pass

    # 3) SVG 부모 클릭
    try:
        driver.execute_script(
            "var svg = document.querySelector('svg.svg-big-play-button-dims');"
            "if(svg) svg.parentElement.click();"
        )
        print("      → SVG 부모 요소 클릭!")
        time.sleep(2)
        return True
    except Exception:
        pass

    # 4) video 태그 직접 재생
    try:
        driver.execute_script(
            "var v = document.querySelector('video'); if(v) v.play();"
        )
        print("      → JS로 영상 직접 재생!")
        time.sleep(2)
        return True
    except Exception:
        pass

    print("      → 재생 버튼을 찾지 못했습니다. 수동으로 재생해주세요.")
    input("      → 수동 재생 후 Enter를 눌러주세요...")
    return True


def get_video_duration(driver):
    """플레이어에서 영상 총 시간(초) 파싱"""
    time.sleep(3)

    # 1) JS로 video duration
    try:
        duration = driver.execute_script(
            "var v = document.querySelector('video'); return v ? v.duration : null;"
        )
        if duration and duration > 0:
            print(f"      → 영상 길이 감지: {int(duration // 60)}분 {int(duration % 60)}초")
            return int(duration)
    except Exception:
        pass

    # 2) 페이지에서 hh:mm:ss 파싱
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text
        match = re.search(r"/\s*(\d{1,2}:\d{2}:\d{2})", page_text)
        if match:
            h, m, s = map(int, match.group(1).split(":"))
            duration = h * 3600 + m * 60 + s
            if duration > 0:
                print(f"      → 영상 길이 감지: {duration // 60}분 {duration % 60}초")
                return duration
    except Exception:
        pass

    print(f"      → 영상 길이 감지 실패. 기본 {DEFAULT_DURATION // 60}분으로 대기합니다.")
    return DEFAULT_DURATION


def wait_and_close(driver, duration_seconds, original_window):
    """영상 시간 + 여유시간 대기, 창이 닫히면 즉시 다음으로"""
    total_wait = duration_seconds + EXTRA_WAIT
    print(f"      → 총 대기: {total_wait // 60}분 {total_wait % 60}초 "
          f"(영상 {duration_seconds // 60}분 + 여유 {EXTRA_WAIT // 60}분)")

    elapsed = 0
    check_interval = 10
    while elapsed < total_wait:
        time.sleep(check_interval)
        elapsed += check_interval
        remaining = total_wait - elapsed
        mins, secs = divmod(remaining, 60)
        print(f"      ⏱ 남은 시간: {mins}분 {secs}초   ", end="\r")

        # alert 감지 (영상 완료 시 뜸)
        try:
            alert = driver.switch_to.alert
            print(f"\n      → Alert 감지: {alert.text}")
            alert.accept()
            print("      → Alert 확인 완료! 다음으로 넘어갑니다.")
            time.sleep(2)
            # alert 후 창이 남아있으면 닫기
            try:
                if driver.current_window_handle != original_window:
                    driver.close()
                    driver.switch_to.window(original_window)
            except Exception:
                try:
                    driver.switch_to.window(original_window)
                except Exception:
                    pass
            return
        except Exception:
            pass

        # 창이 닫혔는지 체크
        try:
            current_windows = driver.window_handles
            if len(current_windows) == 1:
                print(f"\n      → 학습 창 닫힘 감지! 다음으로 넘어갑니다.")
                driver.switch_to.window(original_window)
                return
        except Exception:
            break

    print(f"\n      → 대기 완료! 학습 창 닫기...")

    try:
        if driver.current_window_handle != original_window:
            driver.close()
            driver.switch_to.window(original_window)
            print("      → 학습 창 닫기 완료")
    except Exception:
        try:
            driver.switch_to.window(original_window)
        except Exception:
            pass


def process_lecture(driver, lecture_item):
    """단일 차시(영상) 학습 처리. 실패 시 False 반환."""
    original_window = driver.current_window_handle

    print(f"      학습하기 클릭...")
    driver.execute_script(lecture_item["enter_js"])
    time.sleep(5)

    # alert 체크 (세션 만료 등으로 오류 alert이 뜰 수 있음)
    try:
        alert = driver.switch_to.alert
        alert_text = alert.text
        print(f"      → Alert 감지: {alert_text}")
        alert.accept()
        time.sleep(1)
        return False
    except Exception:
        pass

    # 새 창으로 전환
    new_window = None
    for handle in driver.window_handles:
        if handle != original_window:
            new_window = handle
            driver.switch_to.window(handle)
            print("      → 학습 팝업 창으로 전환 완료")
            break

    if not new_window:
        print("      → 학습 창이 열리지 않았습니다!")
        return False

    # 플레이 버튼 클릭
    click_play_button(driver)

    # 모달 팝업 확인 버튼 (뜰 수도 안 뜰 수도)
    time.sleep(2)
    try:
        modal_btn = driver.find_element(By.CSS_SELECTOR, ".btn-group>button[title='Submit']")
        modal_btn.click()
        print("      → 모달 확인 버튼 클릭!")
        time.sleep(1)
    except Exception:
        pass

    # 영상 시간 파싱
    duration = get_video_duration(driver)

    # 대기 + 창 닫기
    wait_and_close(driver, duration, original_window)
    return True


def detect_survey_modal(driver, max_wait=10):
    """설문 모달이 떠있는지 확인 (최대 max_wait초 대기)"""
    for attempt in range(max_wait):
        try:
            found = driver.execute_script("""
                // 설문 입력 요소 탐색
                var selectors = [
                    "[id^='resAnswer_']", "[id^='example0_']",
                    "textarea[name*='resAnswer']", "input[name*='example']",
                    "[id*='Research']", "[id*='research']",
                    "[id*='survey']", "[id*='Survey']"
                ];
                for (var i = 0; i < selectors.length; i++) {
                    var els = document.querySelectorAll(selectors[i]);
                    for (var j = 0; j < els.length; j++) {
                        if (els[j].offsetParent !== null) return 'found:' + selectors[i];
                    }
                }
                // 모달 체크
                var modals = document.querySelectorAll('.modal, .popup, [class*="modal"], [class*="pop"]');
                for (var k = 0; k < modals.length; k++) {
                    var m = modals[k];
                    var style = window.getComputedStyle(m);
                    if (style.display !== 'none' && style.visibility !== 'hidden' && m.offsetParent !== null) {
                        var text = m.innerText || '';
                        if (text.indexOf('설문') !== -1 || text.indexOf('만족') !== -1 || text.indexOf('교육 과정') !== -1) {
                            return 'modal:' + (m.id || m.className);
                        }
                    }
                }
                return '';
            """)
            if found:
                print(f"  → 설문 감지됨: {found}")
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def submit_survey(driver, course):
    """설문 자동 작성 및 제출 (DOM에서 직접 요소 탐색, JS로 값 설정)"""
    print(f"\n  [설문] 설문 작성 시작...")

    # DOM에서 설문 항목 스캔 + 강의 제목 목록도 페이지에서 추출
    scan_result = driver.execute_script("""
        var results = [];
        // 객관식: example{N}_{resNo} 패턴의 input 그룹핑
        var radios = document.querySelectorAll("input[id^='example']");
        var groups = {};
        radios.forEach(function(r) {
            var match = r.id.match(/example(\\d+)_(\\d+)/);
            if (match) {
                var resNo = parseInt(match[2]);
                if (!groups[resNo]) groups[resNo] = {type:'K', resNo:resNo, count:0};
                groups[resNo].count++;
            }
        });
        for (var key in groups) {
            results.push(groups[key]);
        }
        // 주관식: resAnswer_{resNo} 패턴의 textarea
        var textareas = document.querySelectorAll("textarea[id^='resAnswer_'], textarea[name^='resAnswer'], textarea[id*='resAnswer']");
        textareas.forEach(function(ta) {
            var id = ta.id || ta.name || '';
            var match = id.match(/\\d+/);
            if (match) {
                results.push({type:'J', resNo:parseInt(match[0]), elId:id});
            }
        });
        results.sort(function(a, b) { return a.resNo - b.resNo; });
        return results;
    """)

    if not scan_result:
        print("  → 설문 항목을 DOM에서 찾지 못했습니다!")
        return False

    k_count = sum(1 for s in scan_result if s['type'] == 'K')
    j_count = sum(1 for s in scan_result if s['type'] == 'J')
    print(f"  → 설문 {len(scan_result)}개 항목 감지 (객관식 {k_count}개, 주관식 {j_count}개)")

    # 주관식 답변용 강의 제목 (하드코딩 폴백 포함)
    lecture_titles = [
        "의약품 유통 및 유통질서 이해",
        "의약품 지출보고서제도 이해 및 작성사례",
        "리베이트 적발사례 및 제재사항",
        "위탁자 입장에서의 유의점 및 수탁자 입장에서의 유의점",
        "의약품 판촉영업 신고제도와 유통질서 준수",
        "공정거래법상 부당한 고객유인행위 규제",
        "판촉영업자 의무사항 및 (재)위탁 유의사항",
        "세법상 적격증빙 및 관리 방안",
        "의약품 판촉영업 실무 (자문 사례 위주)",
        "의약품 광고 관련 법령 및 의무사항의 이해",
        "의약품 판촉영업자 직업윤리",
    ]

    # 주관식 항목들 (마지막 주관식 식별용)
    subjective_items = [s for s in scan_result if s["type"] == "J"]

    for item in scan_result:
        res_no = item["resNo"]

        if item["type"] == "K":
            # 객관식: 보기 중 랜덤 1개 클릭
            choice_count = item.get("count", 5)
            choice = random.randint(0, choice_count - 1)
            input_id = f"example{choice}_{res_no}"

            try:
                label_text = driver.execute_script("""
                    var el = document.getElementById(arguments[0]);
                    if (el) {
                        // label 클릭 시도 (가장 자연스러운 방식)
                        var l = document.querySelector("label[for='" + arguments[0] + "']");
                        if (l) {
                            l.click();
                        } else {
                            el.click();
                        }
                        // 체크 안 됐으면 강제 설정
                        if (!el.checked) {
                            el.checked = true;
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                        return l ? l.innerText.trim() : '';
                    }
                    return null;
                """, input_id)
                if label_text is not None:
                    print(f"  → 설문 {res_no} (객관식): \"{label_text or f'{choice+1}번'}\" 선택")
                else:
                    print(f"  → 설문 {res_no}: #{input_id} 요소 없음")
            except Exception as e:
                print(f"  → 설문 {res_no}: #{input_id} 클릭 실패 - {e}")

        elif item["type"] == "J":
            # 주관식: JS로 직접 값 설정
            el_id = item.get("elId", f"resAnswer_{res_no}")
            is_last = (item == subjective_items[-1]) if subjective_items else False

            if is_last:
                answer = "없음"
            else:
                picks = random.sample(lecture_titles, 2)
                answer = ", ".join(picks)

            try:
                success = driver.execute_script("""
                    var ta = document.getElementById(arguments[0]);
                    if (!ta) {
                        // name으로도 시도
                        var tas = document.querySelectorAll("textarea[name='" + arguments[0] + "']");
                        if (tas.length > 0) ta = tas[0];
                    }
                    if (ta) {
                        ta.value = arguments[1];
                        ta.dispatchEvent(new Event('input', {bubbles: true}));
                        ta.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                    return false;
                """, el_id, answer)
                if success:
                    print(f"  → 설문 {res_no} (주관식): \"{answer[:50]}\"")
                else:
                    print(f"  → 설문 {res_no}: #{el_id} 요소 없음")
            except Exception as e:
                print(f"  → 설문 {res_no}: #{el_id} 입력 실패 - {e}")

        time.sleep(0.5)

    # 제출 버튼 찾기 + 클릭
    time.sleep(1)
    try:
        submitted = driver.execute_script("""
            var selectors = [
                "button[onclick*='Research']", "button[onclick*='research']",
                "button[onclick*='save']", "button[onclick*='Save']",
                "a[onclick*='Research']", "a[onclick*='research']",
                "a[onclick*='save']", "#btnSave", ".btn-submit",
                "button.btn-primary", "input[type='submit']",
                "button[type='submit']"
            ];
            for (var i = 0; i < selectors.length; i++) {
                var btns = document.querySelectorAll(selectors[i]);
                for (var j = 0; j < btns.length; j++) {
                    if (btns[j].offsetParent !== null) {
                        btns[j].click();
                        return 'btn:' + selectors[i];
                    }
                }
            }
            // JS 함수 직접 호출 시도
            if (typeof saveResearch === 'function') {
                saveResearch();
                return 'js:saveResearch';
            }
            return '';
        """)

        if submitted:
            print(f"  → 설문 제출! ({submitted})")
        else:
            print("  → 설문 제출 버튼을 찾지 못했습니다!")

        time.sleep(3)

        # alert 처리
        for _ in range(3):
            try:
                alert = driver.switch_to.alert
                print(f"  → 알림: {alert.text}")
                alert.accept()
                time.sleep(1)
            except Exception:
                break

        print("  → 설문 제출 완료!")
        return True
    except Exception as e:
        print(f"  → 설문 제출 실패: {e}")
        return False


def run_lectures(driver, user_id=None, user_pw=None):
    """강의+퀴즈 통합 루프 (로그인 완료된 driver 필요)
    차시별로 강의 수강 → 퀴즈 응시를 순차 처리.
    모든 차시 완료 시 True 반환.
    """
    from tryTest import take_single_quiz, XHR_INTERCEPT_JS

    # 마이페이지 이동 (API 호출을 위해 사이트 도메인에 있어야 함)
    print("\n[2단계] 마이페이지 이동 중...")
    driver.get(config.MYPAGE_URL)
    time.sleep(3)

    # API로 미수료 과정 조회
    courses = get_lecture_courses(driver)

    if not courses:
        print("\n모든 과정을 이미 수강 완료했습니다!")
        return True

    print(f"\n미수료 과정 {len(courses)}개 발견:")
    for i, c in enumerate(courses, 1):
        print(f"  {i}. {c['title']}")

    survey_submitted = False  # 설문 제출 여부 추적

    # 각 과정 순차 처리
    for course_idx, course in enumerate(courses, 1):
        print(f"\n{'=' * 60}")
        print(f"[과정 {course_idx}/{len(courses)}] {course['title']}")
        print(f"{'=' * 60}")

        # goClassRoom JS로 강의실 입장
        classroom_js = (
            f"goClassRoom('{course['curriCd']}',"
            f"'{course['curriYear']}',"
            f"'{course['curriTerm']}',"
            f"'{course['enrollNo']}')"
        )

        print(f"  [3단계] 강의실 입장...")
        driver.get(config.MYPAGE_URL)
        time.sleep(3)
        driver.execute_script(classroom_js)
        time.sleep(5)

        # 설문 모달 감지 (강의실 입장 직후)
        if detect_survey_modal(driver):
            if submit_survey(driver, course):
                survey_submitted = True
            continue

        # API로 미완료 차시 목록 조회 (강의 미완료 OR 퀴즈 미통과)
        pending, total_count = get_pending_lectures(driver, course)

        if not pending:
            # 모든 차시 완료인데 설문이 안 떴을 수 있음 → 한번 더 체크
            print("  → 모든 차시 완료! 설문 모달 재확인 중...")
            if detect_survey_modal(driver, max_wait=15):
                if submit_survey(driver, course):
                    survey_submitted = True
            else:
                print("  → 설문 모달 없음. 건너뜁니다.")
            continue

        # 순차 처리 (강의 → 퀴즈)
        completed = 0
        retry_count = 0
        MAX_RETRY = 3
        QUIZ_MAX_RETRY = 3
        processed_contents = {}  # contentsId → 처리 횟수 (반복 방지)
        MAX_SAME_RETRY = 1  # 같은 차시 최대 재처리 횟수

        while pending:
            current = pending[0]
            cid = current["contentsId"]

            # 같은 차시가 다시 pending에 나오면 재처리 제한
            if processed_contents.get(cid, 0) > MAX_SAME_RETRY:
                print(f"\n    --- {current['title']} ---")
                print(f"    → 이미 {processed_contents[cid]}회 처리했으나 서버 미반영. 건너뜁니다.")
                pending.pop(0)
                continue

            processed_contents[cid] = processed_contents.get(cid, 0) + 1
            completed += 1
            print(f"\n    --- [{completed}/{len(pending) + completed - 1}] {current['title']} ---")

            # 세션 체크
            if not check_session(driver):
                print("\n  [세션 만료] 재로그인 시도...")
                if not login(driver, user_id, user_pw):
                    print("  → 재로그인 실패! 이 과정을 건너뜁니다.")
                    break
                driver.get(config.MYPAGE_URL)
                time.sleep(3)
                driver.execute_script(classroom_js)
                time.sleep(5)

            # --- 강의 수강 ---
            if not current["lectureDone"]:
                print(f"    [강의] 수강 시작...")
                success = process_lecture(driver, current)

                if not success:
                    retry_count += 1
                    completed -= 1
                    print(f"  → 차시 처리 실패! (재시도 {retry_count}/{MAX_RETRY})")
                    if retry_count >= MAX_RETRY:
                        print("  → 최대 재시도 초과. 이 과정을 건너뜁니다.")
                        break
                    if not login(driver, user_id, user_pw):
                        print("  → 재로그인 실패!")
                        break
                    driver.get(config.MYPAGE_URL)
                    time.sleep(3)
                    driver.execute_script(classroom_js)
                    time.sleep(5)
                    continue

                retry_count = 0
            else:
                print(f"    [강의] 이미 완료 → 건너뜀")

            # --- 퀴즈 응시 ---
            if current["quizYn"] == "Y" and current["quizPass"] != "P":
                print(f"    [퀴즈] 응시 시작...")
                # 강의실 페이지로 돌아가서 퀴즈 응시
                driver.get(config.MYPAGE_URL)
                time.sleep(3)
                driver.execute_script(classroom_js)
                time.sleep(5)
                driver.execute_script(XHR_INTERCEPT_JS)

                quiz_passed = False
                for quiz_attempt in range(1, QUIZ_MAX_RETRY + 1):
                    quiz_ok = take_single_quiz(driver, current["courseId"], current["contentsId"])
                    if quiz_ok:
                        print(f"    [퀴즈] 제출 완료!")
                        quiz_passed = True
                        break
                    else:
                        print(f"    [퀴즈] 실패 (시도 {quiz_attempt}/{QUIZ_MAX_RETRY})")
                        if quiz_attempt < QUIZ_MAX_RETRY:
                            time.sleep(3)
                            driver.execute_script(XHR_INTERCEPT_JS)

                if not quiz_passed:
                    print(f"    [퀴즈] 최대 재시도 초과. 다음 차시로 넘어갑니다.")

            time.sleep(3)

            # API 재호출로 상태 확인
            print(f"  → API로 차시 상태 재조회...")
            driver.get(config.MYPAGE_URL)
            time.sleep(3)
            driver.execute_script(classroom_js)
            time.sleep(5)

            # 설문 모달 감지 (차시 처리 후)
            if detect_survey_modal(driver):
                print("  → 설문 모달 감지!")
                if submit_survey(driver, course):
                    survey_submitted = True
                pending = []
                break

            pending, _ = get_pending_lectures(driver, course)

            if pending:
                print(f"  → 남은 미완료 차시: {len(pending)}개")
            else:
                print(f"  → 모든 차시 완료!")

        print(f"\n  → 과정 '{course['title']}' ({completed}개 차시 처리)")

    # 설문까지 제출했으면 완료 처리 (서버 반영 지연/접근불가 항목 무시)
    if survey_submitted:
        print(f"\n{'=' * 60}")
        print("모든 강의+퀴즈+설문 완료!")
        print(f"{'=' * 60}")
        return True

    # 최종 확인: API로 미수료 과정 재조회
    driver.get(config.MYPAGE_URL)
    time.sleep(3)
    remaining = get_lecture_courses(driver)

    if remaining:
        print(f"\n[미완료] 아직 {len(remaining)}개 과정 남음:")
        for c in remaining:
            print(f"  - {c['title']}")
        return False

    print(f"\n{'=' * 60}")
    print("모든 미완료 과정의 모든 차시(강의+퀴즈) 완료!")
    print(f"{'=' * 60}")
    return True


def main():
    if not config.USER_ID or config.USER_ID == "여기에_아이디_입력":
        print("=" * 50)
        print("오류: .env 파일에 USER_ID와 USER_PW를 입력하세요.")
        print("  .env 파일 위치: AutoEduCation/.env")
        print("=" * 50)
        sys.exit(1)

    driver = create_driver()

    try:
        # 1. 로그인
        if not login(driver):
            return

        # 2. 강의 수강
        run_lectures(driver, config.USER_ID, config.USER_PW)

    except KeyboardInterrupt:
        print("\n\n사용자가 중단했습니다. (Ctrl+C)")
    except Exception as e:
        print(f"\n오류 발생: {e}")
    finally:
        input("\nEnter 키를 누르면 브라우저가 종료됩니다...")
        driver.quit()


if __name__ == "__main__":
    main()
