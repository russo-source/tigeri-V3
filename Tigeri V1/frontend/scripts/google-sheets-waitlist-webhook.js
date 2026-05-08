/**
 * Google Apps Script — Waitlist Form -> Google Sheets
 * ---------------------------------------------------
 * Receives JSON payload from your Next.js API route:
 * {
 *   "email": "user@company.com",
 *   "timestamp": "2026-04-14T10:00:00.000Z"
 * }
 *
 * Setup:
 * 1) Open your Google Sheet -> Extensions -> Apps Script.
 * 2) Paste this full file into Code.gs.
 * 3) Deploy -> New deployment -> Web app.
 * 4) Execute as: Me.
 * 5) Who has access: Anyone.
 * 6) Copy web app URL and set in frontend .env.local:
 *    GOOGLE_SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/.../exec
 */

// Config
var SHEET_NAME = "Waitlist";

// Header row (written once)
var HEADERS = [
  "Timestamp (IST)",
  "Email"
];

function formatTimestamp(value) {
  var parsedDate = new Date(value);
  if (isNaN(parsedDate.getTime())) {
    parsedDate = new Date();
  }

  return Utilities.formatDate(
    parsedDate,
    "Asia/Kolkata",
    "dd MMM yyyy, hh:mm:ss a 'IST'"
  );
}

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonResponse({
        success: false,
        error: "Missing request body. Send a POST request to the deployed Web App URL.",
      });
    }

    var raw = e.postData.contents;
    var data = JSON.parse(raw);

    var email = (data.email || "").toString().trim().toLowerCase();
    var timestamp = formatTimestamp((data.timestamp || "").toString());

    var emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    if (!email || !emailRegex.test(email)) {
      return jsonResponse({ success: false, error: "Invalid email." });
    }

    // Get or create target sheet
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(SHEET_NAME);

    if (!sheet) {
      sheet = ss.insertSheet(SHEET_NAME);
    }

    // Write header if sheet is empty
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(HEADERS);
      var headerRange = sheet.getRange(1, 1, 1, HEADERS.length);
      headerRange.setFontWeight("bold");
      headerRange.setBackground("#f3f4f6");
      sheet.setFrozenRows(1);
    }

    // Optional duplicate guard by email (checks last 500 rows)
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      var start = Math.max(2, lastRow - 499);
      var emails = sheet.getRange(start, 2, lastRow - start + 1, 1).getValues();

      for (var i = 0; i < emails.length; i++) {
        if ((emails[i][0] || "").toString().trim().toLowerCase() === email) {
          return jsonResponse({ success: true, duplicate: true });
        }
      }
    }

    sheet.appendRow([timestamp, email]);

    sheet.autoResizeColumns(1, HEADERS.length);

    return jsonResponse({ success: true });
  } catch (err) {
    Logger.log("doPost error: " + err);
    return jsonResponse({ success: false, error: err.toString() });
  }
}

function doGet() {
  return ContentService
    .createTextOutput(JSON.stringify({ status: "ok", message: "Waitlist webhook is live." }))
    .setMimeType(ContentService.MimeType.JSON);
}

function testDoPost() {
  var fakeEvent = {
    postData: {
      contents: JSON.stringify({
        email: "test@example.com",
        timestamp: new Date().toISOString(),
      }),
    },
  };

  var result = doPost(fakeEvent);
  Logger.log(result.getContent());
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
