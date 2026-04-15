const PROP_KEY = "SPREADSHEET_ID";

function _getOrCreateSpreadsheetId_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty(PROP_KEY);
  if (id) return id;

  const ss = SpreadsheetApp.create("slack-ai-chat demo export");
  const dict = ss.getActiveSheet();
  dict.setName("pii_dictionary");
  dict.appendRow(["ts", "event_id", "pii_type", "token", "value"]);

  const log = ss.insertSheet("message_log");
  log.appendRow(["ts", "event_id", "sanitized_text", "pii_summary_json"]);

  props.setProperty(PROP_KEY, ss.getId());
  return ss.getId();
}

function doPost(e) {
  const ssId = _getOrCreateSpreadsheetId_();
  const ss = SpreadsheetApp.openById(ssId);

  const payload = JSON.parse((e && e.postData && e.postData.contents) || "{}");
  const messageLog = payload.message_log;
  const piiDict = payload.pii_dictionary || [];

  if (messageLog) {
    const sheet = ss.getSheetByName("message_log");
    sheet.appendRow([
      messageLog.ts || "",
      messageLog.event_id || "",
      messageLog.sanitized_text || "",
      messageLog.pii_summary_json || "",
    ]);
  }

  if (Array.isArray(piiDict) && piiDict.length) {
    const sheet = ss.getSheetByName("pii_dictionary");
    piiDict.forEach((r) => {
      sheet.appendRow([r.ts || "", r.event_id || "", r.pii_type || "", r.token || "", r.value || ""]);
    });
  }

  return ContentService.createTextOutput("ok").setMimeType(ContentService.MimeType.TEXT);
}

