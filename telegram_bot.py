"""
텔레그램 봇 유틸리티 - 알림 전송 + 원격 제어 (long polling)
"""

import io
import threading
import time
import requests

import config

API_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def _enabled():
    """텔레그램 설정이 되어있는지 확인"""
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def send_message(text, chat_id=None):
    """텍스트 메시지 전송"""
    if not _enabled():
        return None
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    try:
        resp = requests.post(f"{API_BASE}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
        return resp.json()
    except Exception as e:
        print(f"  [텔레그램] 메시지 전송 실패: {e}")
        return None


def send_photo(image_bytes, caption="", chat_id=None):
    """스크린샷(PNG bytes) 전송"""
    if not _enabled():
        return None
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    try:
        files = {"photo": ("screenshot.png", io.BytesIO(image_bytes), "image/png")}
        data = {"chat_id": chat_id, "caption": caption}
        resp = requests.post(f"{API_BASE}/sendPhoto", data=data, files=files, timeout=30)
        return resp.json()
    except Exception as e:
        print(f"  [텔레그램] 사진 전송 실패: {e}")
        return None


def send_document(file_bytes, filename, caption="", chat_id=None):
    """문서(PDF 등) 전송"""
    if not _enabled():
        return None
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    try:
        files = {"document": (filename, io.BytesIO(file_bytes), "application/pdf")}
        data = {"chat_id": chat_id, "caption": caption}
        resp = requests.post(f"{API_BASE}/sendDocument", data=data, files=files, timeout=30)
        return resp.json()
    except Exception as e:
        print(f"  [텔레그램] 문서 전송 실패: {e}")
        return None


def _take_pc_screenshot():
    """전체 PC 화면 스크린샷 → PNG bytes"""
    from PIL import ImageGrab
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── 원격 제어 (long polling) ──

class TelegramController:
    """텔레그램 long polling으로 명령 수신

    지원 명령어:
      /status 또는 status  → 현재 상태 + PC 전체 스크린샷
      /restart 또는 restart → 실패 계정을 "대기"로 변경
    """

    def __init__(self, runner_state, gsheet_module=None):
        self.state = runner_state
        self.gsheet = gsheet_module
        self._thread = None
        self._stop_event = threading.Event()
        self._last_update_id = 0

    def start(self):
        if not _enabled():
            print("  [텔레그램] 봇 토큰 미설정 → 원격 제어 비활성화")
            return
        # 시작 시 밀린 메시지 무시 (현재 update_id 이후만 처리)
        try:
            resp = requests.get(f"{API_BASE}/getUpdates", params={"offset": -1}, timeout=5)
            data = resp.json()
            results = data.get("result", [])
            if results:
                self._last_update_id = results[-1]["update_id"]
        except Exception:
            pass
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print("  [텔레그램] 원격 제어 시작 (long polling)")

    def stop(self):
        self._stop_event.set()

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                params = {
                    "offset": self._last_update_id + 1,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                }
                resp = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=35)
                data = resp.json()

                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    message = update.get("message", {})
                    text = message.get("text", "").strip().lower()
                    chat_id = str(message.get("chat", {}).get("id", ""))

                    if chat_id != str(config.TELEGRAM_CHAT_ID):
                        continue

                    if text in ("/status", "status"):
                        self._handle_status(chat_id)
                    elif text in ("/restart", "restart"):
                        self._handle_restart(chat_id)

            except requests.exceptions.Timeout:
                continue
            except Exception as e:
                print(f"  [텔레그램] polling 오류: {e}")
                time.sleep(5)

    def _handle_status(self, chat_id):
        with self.state.lock:
            if not self.state.current_user:
                msg = "현재 대기 중 (처리 중인 계정 없음)"
            else:
                msg = (
                    f"현재 처리 중\n"
                    f"계정: {self.state.current_user}\n"
                    f"과정: {self.state.current_course or '-'}\n"
                    f"진행: {self.state.progress or '-'}\n"
                    f"완료: {self.state.completed_accounts}/{self.state.total_accounts}"
                )
                if self.state.failed_accounts:
                    msg += f"\n실패: {', '.join(self.state.failed_accounts)}"

        # 전체 PC 화면 스크린샷 전송
        try:
            screenshot = _take_pc_screenshot()
            send_photo(screenshot, caption=msg, chat_id=chat_id)
            return
        except Exception as e:
            print(f"  [텔레그램] PC 스크린샷 실패: {e}")

        send_message(msg, chat_id)

    def _handle_restart(self, chat_id):
        if not self.gsheet:
            send_message("구글시트 미연결 → restart 불가", chat_id)
            return

        with self.state.lock:
            failed = list(self.state.failed_accounts)

        if not failed:
            send_message("실패한 계정이 없습니다.", chat_id)
            return

        restarted = []
        for user_id in failed:
            ok = self.gsheet.update_status(user_id, "대기", "restart 명령으로 재시작")
            if ok:
                restarted.append(user_id)

        with self.state.lock:
            for uid in restarted:
                if uid in self.state.failed_accounts:
                    self.state.failed_accounts.remove(uid)

        send_message(f"재시작 요청: {', '.join(restarted)}\n다음 루프에서 재처리됩니다.", chat_id)


class RunnerState:
    """runner.py와 텔레그램 컨트롤러가 공유하는 상태 객체"""

    def __init__(self):
        self.lock = threading.Lock()
        self.current_user = None
        self.current_course = None
        self.progress = ""
        self.total_accounts = 0
        self.completed_accounts = 0
        self.failed_accounts = []

    def set_current(self, user_id, course=None, progress=""):
        with self.lock:
            self.current_user = user_id
            self.current_course = course
            self.progress = progress

    def mark_completed(self):
        with self.lock:
            self.completed_accounts += 1
            self.current_user = None
            self.current_course = None
            self.progress = ""

    def mark_failed(self, user_id):
        with self.lock:
            self.completed_accounts += 1
            if user_id not in self.failed_accounts:
                self.failed_accounts.append(user_id)
            self.current_user = None
            self.current_course = None
            self.progress = ""
