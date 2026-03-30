// Icebreaker Generator — Google Apps Script API
// Deploy as: Web App → Execute as: Me → Who has access: Anyone
// Then copy the URL into Streamlit config

const SHEET_NAME = "Sheet20";
const OUTPUT_COL = "Personalisation";

function doGet(e) {
  try {
    const params = e.parameter || {};
    const sheetName = params.sheet || SHEET_NAME;
    const outputCol = params.output_col || OUTPUT_COL;
    const limit = parseInt(params.limit || "0");

    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    if (!sheet) {
      return json({ status: "error", message: "Sheet not found: " + sheetName });
    }

    const data = sheet.getDataRange().getValues();
    if (data.length < 2) {
      return json({ status: "ok", count: 0, rows: [] });
    }

    const headers = data[0].map(String);
    const outIdx = headers.indexOf(outputCol);

    const pending = [];
    for (let i = 1; i < data.length; i++) {
      // skip rows where output column is already filled
      if (outIdx >= 0 && String(data[i][outIdx]).trim() !== "") continue;
      // skip completely empty rows
      if (data[i].every(cell => String(cell).trim() === "")) continue;

      const row = { row_number: i + 1 }; // +1 because row 1 is header
      headers.forEach((h, j) => { row[h] = data[i][j]; });
      pending.push(row);

      if (limit > 0 && pending.length >= limit) break;
    }

    return json({ status: "ok", count: pending.length, rows: pending });

  } catch (err) {
    return json({ status: "error", message: err.toString() });
  }
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    const sheetName = payload.sheet || SHEET_NAME;
    const outputCol = payload.output_col || OUTPUT_COL;
    const updates = payload.updates || []; // [{row_number: 5, value: "..."}, ...]

    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    if (!sheet) {
      return json({ status: "error", message: "Sheet not found: " + sheetName });
    }

    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(String);
    const colIdx = headers.indexOf(outputCol) + 1; // convert to 1-indexed

    if (colIdx === 0) {
      return json({ status: "error", message: "Column not found: " + outputCol });
    }

    // Batch write — group by column for efficiency
    updates.forEach(u => {
      sheet.getRange(u.row_number, colIdx).setValue(u.value);
    });

    // Flush all writes at once
    SpreadsheetApp.flush();

    return json({ status: "ok", written: updates.length });

  } catch (err) {
    return json({ status: "error", message: err.toString() });
  }
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
