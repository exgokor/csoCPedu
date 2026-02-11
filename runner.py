"""
통합 실행기 - 엑셀 파일에서 ID/PW를 읽고 강의+퀴즈 통합 자동화
"""

import sys
import time
import tkinter as tk
from tkinter import filedialog

from openpyxl import load_workbook

from selenium.webdriver.common.by import By

import config
from main import create_driver, login, run_lectures, get_lecture_courses, get_pending_lectures


def select_excel_file():
    """tkinter 파일 다이얼로그로 .xlsx 파일 선택"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="계정 엑셀 파일 선택",
        filetypes=[("Excel 파일", "*.xlsx"), ("모든 파일", "*.*")],
    )
    root.destroy()
    return file_path


def read_accounts(file_path):
    """엑셀에서 ID/PW 목록 읽기 (첫 행 헤더, 이후 데이터)"""
    wb = load_workbook(file_path, read_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()

    accounts = []
    for row in rows:
        if row and len(row) >= 2 and row[0] and row[1]:
            accounts.append({
                "user_id": str(row[0]).strip(),
                "user_pw": str(row[1]).strip(),
            })
    return accounts


def test_course(driver):
    """[테스트] API 기반 과정/차시 목록 조회까지만 (실제 수강/응시 생략)"""
    print("\n[테스트] 마이페이지 이동...")
    driver.get(config.MYPAGE_URL)
    time.sleep(3)

    courses = get_lecture_courses(driver)

    if not courses:
        print("[테스트] 모든 과정 이미 수료 완료!")
        return

    print(f"[테스트] 미수료 과정 {len(courses)}개:")
    for i, c in enumerate(courses, 1):
        print(f"  {i}. {c['title']}")

    # 첫 번째 과정만 강의실 입장 + 차시 조회 테스트
    course = courses[0]
    classroom_js = (
        f"goClassRoom('{course['curriCd']}',"
        f"'{course['curriYear']}',"
        f"'{course['curriTerm']}',"
        f"'{course['enrollNo']}')"
    )
    print(f"\n[테스트] 강의실 입장: {course['title']}")
    driver.get(config.MYPAGE_URL)
    time.sleep(3)
    driver.execute_script(classroom_js)
    time.sleep(5)

    pending, total = get_pending_lectures(driver, course)
    print(f"[테스트] 전체 {total}개 차시, 미완료 {len(pending)}개")
    if pending:
        for lec in pending:
            status_parts = []
            if not lec["lectureDone"]:
                status_parts.append(f"강의 {lec['curriPercent']}%")
            if lec["quizYn"] == "Y" and lec["quizPass"] != "P":
                status_parts.append("퀴즈 미통과")
            print(f"  - {lec['title']} ({', '.join(status_parts)})")
    else:
        print("[테스트] 모든 차시 완료 (강의+퀴즈)")

    print("[테스트] 실제 수강/응시는 생략합니다.")


MAX_RESTART = 3  # 셀레니움 완전 재시작 최대 횟수


def run_for_account(user_id, user_pw):
    """단일 계정에 대해 강의+퀴즈 통합 실행. 실패 시 셀레니움 재시작."""
    for attempt in range(1, MAX_RESTART + 1):
        driver = create_driver()

        try:
            # 로그인
            if not login(driver, user_id, user_pw):
                print(f"  → [{user_id}] 로그인 실패! 다음 계정으로 넘어갑니다.")
                return

            done = run_lectures(driver, user_id, user_pw)
            if done:
                return

            # 여기 도달 = run_lectures가 False 반환 (미완료 과정 남음)
            print(f"\n  [재시작 {attempt}/{MAX_RESTART}] 미완료 과정 남음 → 셀레니움 완전 재시작")

        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"\n  → [{user_id}] 오류 발생: {e}")
            print(f"  [재시작 {attempt}/{MAX_RESTART}] 셀레니움 완전 재시작")
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        time.sleep(5)

    print(f"  → [{user_id}] 최대 재시작({MAX_RESTART}회) 초과. 다음 계정으로 넘어갑니다.")


def main():
    print("=" * 60)
    print("  통합 실행기 - 엑셀 계정 기반 강의+퀴즈 자동화")
    print("=" * 60)

    # 1. 엑셀 파일 선택
    print("\n엑셀 파일을 선택하세요...")
    file_path = select_excel_file()

    if not file_path:
        print("파일을 선택하지 않았습니다. 종료합니다.")
        sys.exit(0)

    print(f"선택된 파일: {file_path}")

    # 2. 계정 목록 읽기
    accounts = read_accounts(file_path)

    if not accounts:
        print("엑셀에서 계정을 읽지 못했습니다. (첫 행: USER_ID | USER_PW)")
        sys.exit(1)

    print(f"\n총 {len(accounts)}개 계정 로드:")
    for i, acc in enumerate(accounts, 1):
        masked_pw = acc["user_pw"][:2] + "*" * (len(acc["user_pw"]) - 2)
        print(f"  {i}. {acc['user_id']} / {masked_pw}")

    # 3. 계정별 순차 실행 (항상 강의+퀴즈 통합)
    for idx, acc in enumerate(accounts, 1):
        print(f"\n{'#' * 60}")
        print(f"  계정 {idx}/{len(accounts)}: {acc['user_id']}")
        print(f"{'#' * 60}")

        run_for_account(acc["user_id"], acc["user_pw"])

        print(f"\n  → [{acc['user_id']}] 완료!")
        if idx < len(accounts):
            print("  → 5초 후 다음 계정으로 넘어갑니다...")
            time.sleep(5)

    print(f"\n{'=' * 60}")
    print("  모든 계정 처리 완료!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
