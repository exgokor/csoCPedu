import re
import time
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import config

EXTRA_WAIT = 300  # 영상 끝난 후 여유 대기 시간 (5분)
DEFAULT_DURATION = 4200  # 기본 영상 대기시간 (70분)


def create_driver():
    """Chrome 브라우저 드라이버 생성"""
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-popup-blocking")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def login(driver):
    """자동 로그인"""
    print("[1단계] 로그인 페이지 이동...")
    driver.get(config.LOGIN_URL)
    time.sleep(2)

    driver.find_element(By.ID, "userId").send_keys(config.USER_ID)
    driver.find_element(By.CSS_SELECTOR, ".ip_pw>input").send_keys(config.USER_PW)

    driver.execute_script("goLogin();")
    time.sleep(3)

    if "goLogin" in driver.current_url:
        print("[오류] 로그인 실패. .env 파일의 ID/PW를 확인하세요.")
        return False

    print("[1단계] 로그인 성공!")
    return True


def get_courses(driver):
    """마이페이지에서 강의(과정) 목록 조회"""
    courses = []
    lectures = driver.find_elements(By.CSS_SELECTOR, "#currentCurriList .lecture")

    for lecture in lectures:
        try:
            gauge_text = lecture.find_element(By.CSS_SELECTOR, ".lecture_gauge i").text
            progress = int(gauge_text.replace("%", ""))

            title = lecture.find_element(By.CSS_SELECTOR, "dd h4 a").text.strip()

            enter_btn = lecture.find_element(By.CSS_SELECTOR, ".lectureBtn a.btn.type1")
            onclick_js = enter_btn.get_attribute("href")

            courses.append({
                "title": title,
                "progress": progress,
                "enter_js": onclick_js,
            })
        except Exception:
            continue

    return courses


def parse_minutes(text):
    """'m분' 형식에서 숫자 추출"""
    match = re.search(r"(\d+)\s*분", text)
    if match:
        return int(match.group(1))
    return 0


def get_lecture_items(driver):
    """강의실 내부에서 각 차시(영상) 목록과 수강 상태 조회"""
    items = []

    # edu_info span에서 "들은시간/들을시간" 파싱
    # 셀렉터 패턴: [id$='_001'] > div > div.edu_info > span 등
    info_spans = driver.find_elements(By.CSS_SELECTOR, "div.edu_info > span")

    # 학습하기 버튼들
    study_btns = driver.find_elements(By.CSS_SELECTOR, "a.btn.ver2[href*='goContents']")

    # 차시 제목들
    titles = driver.find_elements(By.CSS_SELECTOR, "div.edu_info .edu_title, div.edu_info h4, div.edu_tit")

    for idx, btn in enumerate(study_btns):
        try:
            onclick_js = btn.get_attribute("href")
            if not onclick_js or "goContents" not in onclick_js:
                continue

            # 해당 차시의 시간 정보 찾기
            listened = 0
            total = 0
            title = f"차시 {idx + 1}"

            # 버튼의 부모 요소에서 시간 정보 찾기
            try:
                parent_row = btn.find_element(By.XPATH, "./ancestor::div[contains(@class,'edu_btn')]/parent::div")
                span_text = parent_row.find_element(By.CSS_SELECTOR, "div.edu_info > span").text
                # "m분/m분" 패턴 파싱
                parts = span_text.split("/")
                if len(parts) == 2:
                    listened = parse_minutes(parts[0])
                    total = parse_minutes(parts[1])
            except Exception:
                pass

            # 제목 찾기
            try:
                parent_row = btn.find_element(By.XPATH, "./ancestor::div[contains(@class,'edu_btn')]/parent::div")
                title_el = parent_row.find_element(By.CSS_SELECTOR, ".edu_tit, .edu_title, h4")
                title = title_el.text.strip() or title
            except Exception:
                pass

            items.append({
                "index": idx,
                "title": title,
                "listened": listened,
                "total": total,
                "is_complete": listened >= total and total > 0,
                "enter_js": onclick_js.replace("javascript:", ""),
            })
        except Exception:
            continue

    return items


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
    """단일 차시(영상) 학습 처리"""
    original_window = driver.current_window_handle

    print(f"      학습하기 클릭...")
    driver.execute_script(lecture_item["enter_js"])
    time.sleep(5)

    # 새 창으로 전환
    for handle in driver.window_handles:
        if handle != original_window:
            driver.switch_to.window(handle)
            print("      → 학습 팝업 창으로 전환 완료")
            break

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

        # 2. 마이페이지 이동
        print("\n[2단계] 마이페이지 이동 중...")
        driver.get(config.MYPAGE_URL)
        time.sleep(3)

        courses = get_courses(driver)
        incomplete = [c for c in courses if c["progress"] < 100]

        if not incomplete:
            print("\n모든 과정을 이미 수강 완료했습니다!")
            return

        print(f"\n미완료 과정 {len(incomplete)}개 발견:")
        for i, c in enumerate(incomplete, 1):
            print(f"  {i}. {c['title']} (진행률: {c['progress']}%)")

        # 3. 각 과정 순차 처리
        for course_idx, course in enumerate(incomplete, 1):
            print(f"\n{'=' * 60}")
            print(f"[과정 {course_idx}/{len(incomplete)}] {course['title']}")
            print(f"{'=' * 60}")

            # 마이페이지로 돌아가서 강의실 입장
            driver.get(config.MYPAGE_URL)
            time.sleep(3)

            # 강의 목록 다시 조회
            updated_courses = get_courses(driver)
            target = None
            for uc in updated_courses:
                if uc["title"] == course["title"]:
                    target = uc
                    break

            if not target:
                print("  → 과정을 찾을 수 없습니다. 건너뜁니다.")
                continue

            if target["progress"] >= 100:
                print("  → 이미 완료된 과정입니다. 건너뜁니다.")
                continue

            # 강의실 입장
            print(f"  [3단계] 강의실 입장...")
            js_code = target["enter_js"].replace("javascript:", "")
            driver.execute_script(js_code)
            time.sleep(5)

            # 강의실 내부에서 차시 목록 조회
            lecture_items = get_lecture_items(driver)

            if not lecture_items:
                # 차시 목록 파싱 실패 시 단일 학습하기 버튼으로 폴백
                print("  → 차시 목록 파싱 실패. 학습하기 버튼 직접 처리...")
                try:
                    study_btns = driver.find_elements(By.CSS_SELECTOR, "a.btn.ver2[href*='goContents']")
                    for btn_idx, btn in enumerate(study_btns):
                        onclick_js = btn.get_attribute("href")
                        if onclick_js and "goContents" in onclick_js:
                            print(f"\n    --- 차시 {btn_idx + 1}/{len(study_btns)} ---")
                            fake_item = {
                                "title": f"차시 {btn_idx + 1}",
                                "enter_js": onclick_js.replace("javascript:", ""),
                            }
                            process_lecture(driver, fake_item)
                            # 강의실 페이지로 복귀
                            driver.get(config.MYPAGE_URL)
                            time.sleep(3)
                            js_code = target["enter_js"].replace("javascript:", "")
                            driver.execute_script(js_code)
                            time.sleep(5)
                except Exception as e:
                    print(f"  → 폴백 처리 오류: {e}")
                continue

            # 미완료 차시만 필터링
            incomplete_items = [item for item in lecture_items if not item["is_complete"]]

            print(f"  총 {len(lecture_items)}개 차시 중 미완료 {len(incomplete_items)}개:")
            for item in lecture_items:
                status = "✓" if item["is_complete"] else "✗"
                print(f"    [{status}] {item['title']} ({item['listened']}분/{item['total']}분)")

            if not incomplete_items:
                print("  → 모든 차시 수강 완료!")
                continue

            # 미완료 차시 순차 수강
            for lec_idx, item in enumerate(incomplete_items, 1):
                print(f"\n    --- [{lec_idx}/{len(incomplete_items)}] {item['title']} ---")
                print(f"    진행: {item['listened']}분/{item['total']}분")

                # 강의실 페이지로 복귀 (2번째 차시부터)
                if lec_idx > 1:
                    driver.get(config.MYPAGE_URL)
                    time.sleep(3)
                    js_code = target["enter_js"].replace("javascript:", "")
                    driver.execute_script(js_code)
                    time.sleep(5)

                    # 차시 목록 다시 조회해서 최신 상태 확인
                    refreshed = get_lecture_items(driver)
                    found = False
                    for r in refreshed:
                        if r["index"] == item["index"]:
                            if r["is_complete"]:
                                print(f"    → 이미 완료됨. 건너뜁니다.")
                                found = True
                                break
                            item = r
                            found = True
                            break
                    if found and r["is_complete"]:
                        continue

                process_lecture(driver, item)
                time.sleep(3)

            print(f"\n  → 과정 '{course['title']}' 모든 차시 수강 완료!")

        print(f"\n{'=' * 60}")
        print("모든 미완료 과정의 모든 차시 수강 완료!")
        print(f"{'=' * 60}")

    except KeyboardInterrupt:
        print("\n\n사용자가 중단했습니다. (Ctrl+C)")
    except Exception as e:
        print(f"\n오류 발생: {e}")
    finally:
        input("\nEnter 키를 누르면 브라우저가 종료됩니다...")
        driver.quit()


if __name__ == "__main__":
    main()
