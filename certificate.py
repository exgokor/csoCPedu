"""
수료증 PDF 처리 - CDP Page.printToPDF로 수료증 추출

getCertificateSource()는 새 창에서 수료증 HTML을 렌더링 후 window.print()를 호출함.
window.print()가 인쇄 다이얼로그를 띄워서 브라우저가 먹통이 되므로,
print()를 차단한 뒤 CDP로 직접 PDF를 추출하는 방식을 사용.
"""

import base64
import os
import time

import telegram_bot


CERT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certificates")


def download_and_send_certificate(driver, cert_js, user_id, chat_id=None):
    """수료증 PDF 추출 → 텔레그램 전송 → 로컬 파일 삭제

    CDP Page.addScriptToEvaluateOnNewDocument로 새 창이 열리기 전에
    window.print()를 차단하여 인쇄 다이얼로그가 뜨지 않도록 함.

    Args:
        driver: Selenium WebDriver (마이페이지에 있어야 함)
        cert_js: getCertificateSource(...) onclick 문자열
        user_id: 계정 ID (파일명용)
        chat_id: 텔레그램 chat_id (None이면 기본값 사용)

    Returns:
        bool: 성공 여부
    """
    original_window = driver.current_window_handle

    try:
        # 1. CDP로 모든 새 문서에서 window.print() 차단 (페이지 로드 전에 실행됨)
        print(f"  [수료증] window.print 사전 차단 설정...")
        result = driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "window.print = function() { console.log('print blocked by CDP'); };"
        })
        script_id = result.get("identifier", "")

        # 2. getCertificateSource 호출
        print(f"  [수료증] getCertificateSource 호출...")
        driver.execute_script(cert_js)
        time.sleep(5)

        # 3. 새 창으로 전환
        new_window = None
        for handle in driver.window_handles:
            if handle != original_window:
                new_window = handle
                break

        if not new_window:
            print(f"  [수료증] 수료증 창이 열리지 않았습니다!")
            return False

        driver.switch_to.window(new_window)
        print(f"  [수료증] 수료증 창 전환 완료")
        time.sleep(3)

        # 4. CDP로 PDF 추출
        print(f"  [수료증] CDP Page.printToPDF 실행...")
        pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True,
            "paperWidth": 8.27,    # A4
            "paperHeight": 11.69,  # A4
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
        })
        pdf_bytes = base64.b64decode(pdf_data["data"])
        print(f"  [수료증] PDF 추출 완료 ({len(pdf_bytes):,} bytes)")

        # 5. 임시 파일 저장
        os.makedirs(CERT_DIR, exist_ok=True)
        filename = f"수료증_{user_id}.pdf"
        filepath = os.path.join(CERT_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(pdf_bytes)
        print(f"  [수료증] 임시 저장: {filepath}")

        # 6. 텔레그램 전송
        telegram_bot.send_document(
            pdf_bytes, filename,
            caption=f"[{user_id}] 수료증",
            chat_id=chat_id,
        )
        print(f"  [수료증] 텔레그램 전송 완료!")

        # 7. 로컬 파일 삭제
        try:
            os.remove(filepath)
            print(f"  [수료증] 임시 파일 삭제 완료")
        except Exception:
            pass

        return True

    except Exception as e:
        print(f"  [수료증] 처리 실패: {e}")
        return False

    finally:
        # 사전 차단 스크립트 제거
        if script_id:
            try:
                driver.execute_cdp_cmd("Page.removeScriptToEvaluateOnNewDocument", {
                    "identifier": script_id
                })
            except Exception:
                pass

        # 수료증 창 닫고 원래 창으로 복귀
        try:
            current_windows = driver.window_handles
            for handle in current_windows:
                if handle != original_window:
                    driver.switch_to.window(handle)
                    driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(original_window)
        except Exception:
            pass


def download_and_send_certificate_v2(driver, cert_js, user_id, chat_id=None):
    """대안 방식: 새 드라이버로 수료증 페이지를 열어 PDF 추출

    getCertificateSource가 원래 브라우저를 먹통으로 만드는 경우 사용.
    cert_js에서 URL 파라미터를 추출하여 별도 드라이버로 접근.
    """
    from main import create_driver, login
    import config
    import re

    original_window = driver.current_window_handle

    try:
        # 1. 현재 세션의 쿠키 복사
        cookies = driver.get_cookies()

        # 2. 새 드라이버 생성 + 쿠키 주입
        cert_driver = create_driver()
        cert_driver.get(config.BASE_URL)
        time.sleep(2)

        for cookie in cookies:
            try:
                cert_driver.add_cookie({
                    "name": cookie["name"],
                    "value": cookie["value"],
                    "domain": cookie.get("domain", ""),
                })
            except Exception:
                pass

        # 3. window.print 차단 후 getCertificateSource 호출
        cert_driver.get(config.MYPAGE_URL)
        time.sleep(3)

        # print 차단 스크립트를 미리 주입
        cert_driver.execute_script("""
            window._origOpen = window.open;
            window.open = function(url, name, specs) {
                var w = window._origOpen(url, name, specs);
                if (w) {
                    var origPrint = w.print;
                    Object.defineProperty(w, 'print', {
                        value: function() { console.log('print blocked'); },
                        writable: true
                    });
                }
                return w;
            };
        """)
        time.sleep(1)

        cert_driver.execute_script(cert_js)
        time.sleep(5)

        # 4. 새 창으로 전환
        main_window = cert_driver.current_window_handle
        new_window = None
        for handle in cert_driver.window_handles:
            if handle != main_window:
                new_window = handle
                break

        if not new_window:
            print(f"  [수료증v2] 수료증 창이 열리지 않았습니다!")
            cert_driver.quit()
            return False

        cert_driver.switch_to.window(new_window)
        cert_driver.execute_script("window.print = function() {};")
        time.sleep(2)

        # 5. CDP로 PDF 추출
        print(f"  [수료증v2] CDP Page.printToPDF 실행...")
        pdf_data = cert_driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True,
            "paperWidth": 8.27,
            "paperHeight": 11.69,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
        })
        pdf_bytes = base64.b64decode(pdf_data["data"])
        print(f"  [수료증v2] PDF 추출 완료 ({len(pdf_bytes):,} bytes)")

        # 6. 텔레그램 전송
        filename = f"수료증_{user_id}.pdf"
        telegram_bot.send_document(
            pdf_bytes, filename,
            caption=f"[{user_id}] 수료증",
            chat_id=chat_id,
        )
        print(f"  [수료증v2] 텔레그램 전송 완료!")

        cert_driver.quit()
        return True

    except Exception as e:
        print(f"  [수료증v2] 처리 실패: {e}")
        try:
            cert_driver.quit()
        except Exception:
            pass
        return False


def extract_cert_js_from_mypage(driver):
    """마이페이지에서 수료 완료 과정의 getCertificateSource JS 목록 추출

    Returns:
        list[dict]: [{"title": "과정명", "cert_js": "getCertificateSource(...)"}, ...]
    """
    try:
        certs = driver.execute_script("""
            var results = [];
            var links = document.querySelectorAll("a[onclick*='getCertificateSource']");
            links.forEach(function(a) {
                var onclick = a.getAttribute("onclick");
                var container = a.closest(".lectureBtn") || a.closest("li") || a.parentElement;
                var titleEl = container ? container.parentElement.querySelector(".lectureTit, .tit, h4, h3") : null;
                var title = titleEl ? titleEl.innerText.trim() : "";
                results.push({title: title, cert_js: onclick});
            });
            return results;
        """)
        return certs or []
    except Exception as e:
        print(f"  [수료증] JS 추출 실패: {e}")
        return []
