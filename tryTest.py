"""
KPBMA 보수교육 시험 자동 응시
- goContentsList API로 퀴즈 상태 조회 (quizYn=Y, quizPass=N)
- getCurriQuizList API 응답에서 정답 자동 파싱
- 모달에서 자동 정답 선택 후 제출
"""

import json
import re
import time
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import config
from main import create_driver, login

CONTENTS_LIST_URL = f"{config.BASE_URL}/classRoom/curriContentsListAjax"
ENROLL_LIST_URL = f"{config.BASE_URL}/sub/myPage/currentEnrollListAjax"

# getCurriQuizList XHR 응답을 가로채서 window._quizData에 저장
XHR_INTERCEPT_JS = """
(function() {
    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    window._quizData = null;
    XMLHttpRequest.prototype.open = function() {
        this._url = arguments[1];
        origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        var xhr = this;
        this.addEventListener('load', function() {
            if (xhr._url && xhr._url.indexOf('getCurriQuizList') !== -1) {
                try {
                    window._quizData = JSON.parse(xhr.responseText);
                } catch(e) {}
            }
        });
        origSend.apply(this, arguments);
    };
})();
"""


def strip_html(text):
    """HTML 태그 제거 및 텍스트 정규화"""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&')
    return re.sub(r'\s+', ' ', clean).strip()


def fetch_post(driver, url, params):
    """Selenium 브라우저 내에서 fetch POST 호출 (세션/쿠키 자동 포함)"""
    # URLSearchParams로 form-urlencoded 전송
    js = """
    var params = new URLSearchParams(arguments[0]);
    var resp = await fetch(arguments[1], {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: params.toString()
    });
    var text = await resp.text();
    return text;
    """
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


def get_exam_courses(driver):
    """currentEnrollListAjax API로 미수료 과정 조회
    조건: completeDate가 비어있는 과정만
    """
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


def get_pending_quizzes(driver, course):
    """강의실 내에서 curriContentsListAjax API 직접 호출하여 미응시 퀴즈 필터링
    조건: quizYn='Y' AND quizPass='N'
    """
    payload = {
        "curriCd": course["curriCd"],
        "curriYear": course["curriYear"],
        "curriTerm": course["curriTerm"],
    }

    data = fetch_post(driver, CONTENTS_LIST_URL, payload)
    if not data:
        print("    → curriContentsListAjax API 호출 실패!")
        return []

    contents = data.get("dataList", [])

    # 디버그: 첫 번째 항목의 전체 키와 값 출력
    if contents:
        print(f"    [디버그] 전체 항목 수: {len(contents)}")
        sample = contents[0]
        print(f"    [디버그] 첫 항목 키: {list(sample.keys())}")
        # quiz 관련 필드만 출력
        for k, v in sample.items():
            if 'quiz' in k.lower() or 'Quiz' in k:
                print(f"    [디버그] {k} = {v}")
        # 두 번째 항목도 (다를 수 있으니)
        if len(contents) > 1:
            sample2 = contents[1]
            for k, v in sample2.items():
                if 'quiz' in k.lower() or 'Quiz' in k:
                    print(f"    [디버그] 항목2: {k} = {v}")

    pending = []
    passed = 0
    no_quiz = 0

    for item in contents:
        quiz_yn = item.get("quizYn", "N")
        quiz_pass = item.get("quizPass", "")
        contents_nm = item.get("contentsNm", "")
        contents_id = item.get("contentsId", "")
        course_id = item.get("courseId", "")

        if quiz_yn != "Y":
            no_quiz += 1
            continue

        if quiz_pass == "P":
            passed += 1
            print(f"    [Pass] {contents_nm}")
            continue

        # quizYn=Y, quizPass=N → 미응시
        pending.append({
            "contentsNm": contents_nm,
            "contentsId": contents_id,
            "courseId": course_id,
            "quizCnt": item.get("quizCnt", 5),
        })
        print(f"    [미응시] {contents_nm}")

    print(f"    → 퀴즈 현황: 미응시 {len(pending)}개 / Pass {passed}개 / 퀴즈없음 {no_quiz}개")
    return pending


def get_quiz_data(driver, timeout=15):
    """인터셉트된 퀴즈 데이터 가져오기 (최대 timeout초 대기)"""
    for _ in range(timeout * 2):
        data = driver.execute_script("return window._quizData;")
        if data:
            return data
        time.sleep(0.5)
    return None


def build_answer_map(quiz_list):
    """API 응답의 quizList에서 {quizOrder: answer} 매핑 생성"""
    by_order = {}
    by_text = []

    for q in quiz_list:
        order = q.get("quizOrder")
        answer = q.get("answer", "")
        question_text = strip_html(q.get("contents", ""))

        choices = []
        for i in range(1, 6):
            ex = q.get(f"example{i}", "")
            if ex:
                choices.append(strip_html(ex))

        by_order[order] = {
            "answer": answer,
            "question": question_text,
            "choices": choices,
        }

        by_text.append({
            "order": order,
            "answer": answer,
            "question": question_text,
            "choices": choices,
        })

    return by_order, by_text


def select_answers_on_modal(driver, answer_map_by_order, answer_map_by_text):
    """
    모달에서 각 문제의 정답을 선택
    체크박스 ID 패턴: answer{정답번호}_{문제번호}
    """
    answered = 0
    quiz_cnt = 0

    # 모달에 표시된 문제 수 파악
    for i in range(1, 30):
        if driver.find_elements(By.CSS_SELECTOR, f"#answer1_{i}"):
            quiz_cnt = i
        else:
            break

    if quiz_cnt == 0:
        print("    → 체크박스를 찾을 수 없습니다!")
        try:
            html = driver.execute_script(
                "return document.querySelector('#quizList').innerHTML.substring(0, 3000);"
            )
            print(f"    [디버그] #quizList HTML:\n{html}")
        except Exception:
            pass
        return 0

    print(f"    → 모달에 {quiz_cnt}문제 감지됨")

    for i in range(1, quiz_cnt + 1):
        print(f"\n    --- 문제 {i}/{quiz_cnt} 처리 중 ---")
        correct_answer = None
        q_preview = ""

        # 방법 1: quizOrder 히든 필드로 매칭
        order_el = driver.find_elements(
            By.CSS_SELECTOR, f"input[name='quizOrder_{i}']"
        )
        if order_el:
            try:
                quiz_order = int(order_el[0].get_attribute("value"))
                print(f"    [매칭] quizOrder_{i} = {quiz_order}")
                if quiz_order in answer_map_by_order:
                    correct_answer = answer_map_by_order[quiz_order]["answer"]
                    q_preview = answer_map_by_order[quiz_order]["question"][:40]
                    print(f"    [매칭] 정답: {correct_answer}번")
                else:
                    print(f"    [매칭] quizOrder {quiz_order}이 answer_map에 없음!")
            except (ValueError, TypeError) as e:
                print(f"    [매칭] quizOrder 파싱 실패: {e}")
        else:
            print(f"    [매칭] quizOrder_{i} 히든 필드 없음")

        # 방법 2: 문제 텍스트 + 보기로 매칭 (폴백)
        if not correct_answer:
            print(f"    [폴백] 텍스트 매칭 시도...")
            correct_answer = match_by_text(driver, i, answer_map_by_text)
            if correct_answer:
                print(f"    [폴백] 텍스트 매칭 성공 → 정답 {correct_answer}번")
            else:
                print(f"    [폴백] 텍스트 매칭도 실패!")

        if not correct_answer:
            print(f"    ✗ 문제 {i}: 정답을 찾지 못함!")
            continue

        # 체크박스 클릭: #answer{정답번호}_{문제번호}
        checkbox_id = f"answer{correct_answer}_{i}"
        print(f"    [클릭] #{checkbox_id} 체크박스 찾는 중...")

        cb = driver.find_elements(By.CSS_SELECTOR, f"#{checkbox_id}")
        if not cb:
            print(f"    [클릭] #{checkbox_id} 못 찾음!")
            continue

        # 클릭 시도 (3가지 방법)
        click_success = False
        for attempt, method in enumerate(["js_click", "js_checked", "selenium_click"], 1):
            if method == "js_click":
                driver.execute_script("arguments[0].click();", cb[0])
            elif method == "js_checked":
                driver.execute_script(
                    "arguments[0].checked = true;"
                    "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));"
                    "arguments[0].dispatchEvent(new Event('click', {bubbles: true}));",
                    cb[0]
                )
            else:
                try:
                    cb[0].click()
                except Exception:
                    pass

            time.sleep(0.5)

            after_checked = driver.execute_script("return arguments[0].checked;", cb[0])
            print(f"    [클릭] 시도 {attempt} ({method}): 체크 = {after_checked}")

            if after_checked:
                click_success = True
                break

        if click_success:
            answered += 1
            print(f"    ✓ 문제 {i}: {q_preview} → 정답 {correct_answer}번 선택 완료!")
        else:
            print(f"    ✗ 문제 {i}: 체크 실패!")

        time.sleep(1)

    return answered


def match_by_text(driver, question_num, answer_map_by_text):
    """문제 번호의 보기 텍스트를 읽어서 API 데이터와 매칭 (폴백)"""
    modal_choices = []
    for j in range(1, 6):
        cb = driver.find_elements(By.CSS_SELECTOR, f"#answer{j}_{question_num}")
        if cb:
            try:
                label = driver.find_element(
                    By.CSS_SELECTOR, f"label[for='answer{j}_{question_num}']"
                )
                modal_choices.append(re.sub(r'\s+', '', label.text.strip()))
            except Exception:
                pass

    if not modal_choices:
        return None

    best_match = None
    best_score = 0

    for item in answer_map_by_text:
        score = 0
        api_choices = [re.sub(r'\s+', '', c) for c in item["choices"]]

        for mc in modal_choices:
            for ac in api_choices:
                if mc and ac and (mc in ac or ac in mc):
                    score += 1
                    break

        if score > best_score:
            best_score = score
            best_match = item

    if best_match and best_score >= 2:
        return best_match["answer"]
    return None


def take_single_quiz(driver, course_id, contents_id):
    """단일 퀴즈 응시 (goQuiz 호출부터 제출까지)"""

    # 1. XHR 인터셉터 설치
    driver.execute_script(XHR_INTERCEPT_JS)
    driver.execute_script("window._quizData = null;")
    time.sleep(1)

    # 2. goQuiz(courseId, contentsId) 호출
    print(f"    → goQuiz('{course_id}', '{contents_id}') 호출...")
    try:
        driver.execute_script(f"goQuiz('{course_id}','{contents_id}');")
    except Exception as e:
        print(f"    → goQuiz 호출 실패: {e}")
        return False

    time.sleep(2)

    # alert 체크 ("등록된 퀴즈가 없습니다" 등)
    try:
        alert = driver.switch_to.alert
        alert_text = alert.text
        print(f"    → 알림: {alert_text}")
        alert.accept()
        time.sleep(1)
        if "퀴즈가 없" in alert_text or "등록" in alert_text:
            print(f"    → 퀴즈 미등록 항목, 건너뜀")
            return False
    except Exception:
        pass  # alert 없으면 정상 진행

    time.sleep(1)

    # 3. API 응답에서 퀴즈 데이터 가져오기
    quiz_data = get_quiz_data(driver)
    if not quiz_data:
        print("    → 퀴즈 데이터 수신 실패!")
        return False

    quiz_list = quiz_data.get("dataList2", [])
    if not quiz_list:
        print("    → dataList2에 문제가 없습니다.")
        return False

    print(f"    → 문제 데이터 {len(quiz_list)}개 확보! (정답 포함)")

    # 정답 매핑 생성
    answer_by_order, answer_by_text = build_answer_map(quiz_list)

    for order, info in answer_by_order.items():
        q_preview = info["question"][:40]
        print(f"      #{order}: {q_preview}... → 정답 {info['answer']}번")

    # 4. 모달 대기
    try:
        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "#quizList"))
        )
        print("    → 시험 모달 열림!")
    except Exception:
        print("    → #quizList 모달을 찾을 수 없습니다.")
        return False

    time.sleep(2)

    # 5. 정답 선택
    answered = select_answers_on_modal(driver, answer_by_order, answer_by_text)

    if answered == 0:
        print("    → 정답을 선택하지 못했습니다!")
        return False

    print(f"    → 총 {answered}문제 정답 선택 완료!")
    time.sleep(1)

    # 6. 제출
    try:
        submit_btn = driver.find_element(By.CSS_SELECTOR, "#modalSubmit")
        print("    → 제출 버튼 클릭...")
        submit_btn.click()
        time.sleep(3)

        # 확인 팝업 (alert) - 여러 번 뜰 수 있음
        for _ in range(3):
            try:
                alert = driver.switch_to.alert
                print(f"    → 알림: {alert.text}")
                alert.accept()
                time.sleep(2)
            except Exception:
                break

        # 퀴즈 팝업 닫기
        try:
            driver.execute_script("closePopQ();")
            print("    → closePopQ() 호출 완료")
            time.sleep(2)
        except Exception:
            print("    → closePopQ() 호출 실패 (이미 닫혔을 수 있음)")

        print("    → 시험 제출 완료!")
        return True
    except Exception as e:
        print(f"    → 제출 버튼 클릭 실패: {e}")
        return False


def main():
    if not config.USER_ID or config.USER_ID == "여기에_아이디_입력":
        print("=" * 50)
        print("오류: .env 파일에 USER_ID와 USER_PW를 입력하세요.")
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

        # 3. 시험 대상 과정 조회 (수료증보기 버튼 없는 것만)
        courses = get_exam_courses(driver)

        if not courses:
            print("\n시험 응시할 과정이 없습니다! (모두 수료 완료)")
            return

        print(f"\n시험 대상 과정 {len(courses)}개:")
        for i, c in enumerate(courses, 1):
            print(f"  {i}. {c['title']} ({c['curriCd']}, {c['curriYear']}년 {c['curriTerm']}기)")

        # 4. 각 과정별 처리
        results = []
        for idx, course in enumerate(courses, 1):
            print(f"\n{'=' * 60}")
            print(f"[과정 {idx}/{len(courses)}] {course['title']}")
            print(f"{'=' * 60}")

            # 강의실 입장 먼저 (goContentsList는 강의실 세션 필요)
            classroom_js = (
                f"goClassRoom('{course['curriCd']}',"
                f"'{course['curriYear']}',"
                f"'{course['curriTerm']}',"
                f"'{course['enrollNo']}')"
            )
            print(f"\n  [3단계] 강의실 입장...")
            driver.get(config.MYPAGE_URL)
            time.sleep(3)
            driver.execute_script(classroom_js)
            time.sleep(5)

            # 강의실 안에서 curriContentsListAjax 호출하여 미응시 퀴즈 조회
            print(f"\n  [4단계] 컨텐츠 목록 조회 (API)...")
            pending = get_pending_quizzes(driver, course)

            if not pending:
                print(f"  → 미응시 퀴즈 없음! 건너뜁니다.")
                results.append({"title": course["title"], "passed": 0, "total": 0})
                continue

            # 각 미응시 퀴즈 순차 응시
            passed_cnt = 0
            for q_idx, quiz in enumerate(pending, 1):
                print(f"\n  --- 퀴즈 {q_idx}/{len(pending)}: {quiz['contentsNm']} ---")

                success = take_single_quiz(driver, quiz["courseId"], quiz["contentsId"])
                if success:
                    passed_cnt += 1

                time.sleep(2)

            results.append({
                "title": course["title"],
                "passed": passed_cnt,
                "total": len(pending),
            })

            # 다음 과정 전 상태 재확인
            print(f"\n  [확인] 퀴즈 상태 재조회...")
            remaining = get_pending_quizzes(driver, course)
            if remaining:
                print(f"  → 아직 미응시 {len(remaining)}개 남음!")
            else:
                print(f"  → 모든 퀴즈 Pass 완료!")

            time.sleep(3)

        # 결과 요약
        print(f"\n{'=' * 60}")
        print("시험 결과 요약")
        print(f"{'=' * 60}")
        for r in results:
            if r["total"] == 0:
                print(f"  [이미 Pass] {r['title']}")
            else:
                print(f"  [{r['passed']}/{r['total']} 통과] {r['title']}")

    except KeyboardInterrupt:
        print("\n\n사용자가 중단했습니다. (Ctrl+C)")
    except Exception as e:
        print(f"\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        input("\nEnter 키를 누르면 브라우저가 종료됩니다...")
        driver.quit()


if __name__ == "__main__":
    main()
