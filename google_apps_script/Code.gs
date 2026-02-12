/**
 * KPBMA 교육 자동화 - 구글 스프레드시트 Web App
 *
 * 스프레드시트 구조 (첫 행 헤더):
 *   A: user_id | B: user_pw | C: telegram_chat_id | D: 상태 | E: 진행률 | F: 최종업데이트 | G: 비고
 *
 * 보안:
 *   - 요청 시 token 파라미터로 인증 (GSHEET_SECRET_TOKEN과 동일해야 함)
 *   - user_id, user_pw는 XOR + Base64로 암호화하여 전송
 *
 * 사용법:
 *   1. 아래 SECRET_TOKEN을 원하는 값으로 변경
 *   2. 아래 ENCRYPT_KEY를 원하는 값으로 변경 (.env의 GSHEET_ENCRYPT_KEY와 동일하게)
 *   3. 이 스크립트를 구글 스프레드시트의 Apps Script 에디터에 붙여넣기
 *   4. 배포 > 웹 앱 > "누구나" 액세스, "나"로 실행 > 배포
 *   5. 배포 URL을 .env의 GSHEET_WEB_APP_URL에 등록
 */

// ★ 이 두 값을 변경하세요. .env 파일과 동일하게 맞춰야 합니다.
var SECRET_TOKEN = "change-me-to-your-secret";
var ENCRYPT_KEY = "my-encrypt-key-2026";

// ── 암호화 유틸 ──

function xorEncrypt(text, key) {
  var result = [];
  for (var i = 0; i < text.length; i++) {
    result.push(text.charCodeAt(i) ^ key.charCodeAt(i % key.length));
  }
  return Utilities.base64Encode(result);
}

// ── 인증 체크 ──

function checkToken(e) {
  var params = e ? (e.parameter || {}) : {};
  return params.token === SECRET_TOKEN;
}

function unauthorizedResponse() {
  return ContentService
    .createTextOutput(JSON.stringify({ error: "Unauthorized" }))
    .setMimeType(ContentService.MimeType.JSON);
}

// ── doGet: 대기 계정 조회 (암호화하여 반환) ──

function doGet(e) {
  if (!checkToken(e)) return unauthorizedResponse();

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = sheet.getDataRange().getValues();

  var accounts = [];
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var userId = String(row[0] || "").trim();
    var userPw = String(row[1] || "").trim();
    var chatId = String(row[2] || "").trim();
    var status = String(row[3] || "").trim();

    if (!userId || !userPw) continue;
    if (status && status !== "대기") continue;

    accounts.push({
      user_id: xorEncrypt(userId, ENCRYPT_KEY),
      user_pw: xorEncrypt(userPw, ENCRYPT_KEY),
      telegram_chat_id: chatId || "",
      _encrypted: true,
    });
  }

  return ContentService
    .createTextOutput(JSON.stringify(accounts))
    .setMimeType(ContentService.MimeType.JSON);
}

// ── doPost: 상태 업데이트 ──

function doPost(e) {
  if (!checkToken(e)) return unauthorizedResponse();

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var payload;

  try {
    payload = JSON.parse(e.postData.contents);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ error: "Invalid JSON" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  var userId = String(payload.user_id || "").trim();
  var status = String(payload.status || "").trim();
  var message = String(payload.message || "").trim();

  if (!userId || !status) {
    return ContentService
      .createTextOutput(JSON.stringify({ error: "user_id and status required" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  var data = sheet.getDataRange().getValues();
  var updated = false;

  for (var i = 1; i < data.length; i++) {
    if (String(data[i][0]).trim() === userId) {
      sheet.getRange(i + 1, 4).setValue(status);
      if (payload.progress) {
        sheet.getRange(i + 1, 5).setValue(String(payload.progress));
      }
      sheet.getRange(i + 1, 6).setValue(new Date().toLocaleString("ko-KR"));
      if (message) {
        sheet.getRange(i + 1, 7).setValue(message);
      }
      updated = true;
      break;
    }
  }

  return ContentService
    .createTextOutput(JSON.stringify({ success: updated, user_id: userId, status: status }))
    .setMimeType(ContentService.MimeType.JSON);
}
