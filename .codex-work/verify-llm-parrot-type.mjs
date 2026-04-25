import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load("转录数据/LLM转录.xlsx"));
const sheet = workbook.worksheets.getItem("Sheet1");
const values = sheet.getRange("A1:J10000").values;

const rows = [];
const notDownWord = [];
for (let i = 1; i < values.length; i += 1) {
  const row = values[i];
  if (!row.some((value) => value !== null && value !== undefined && value !== "")) continue;
  if (String(row[5] ?? "").trim() === "鹦鹉") {
    const item = {
      row: i + 1,
      test_id: row[0],
      question_id: row[1],
      nounType: row[7],
    };
    rows.push(item);
    if (String(row[7] ?? "").trim() !== "下位词") {
      notDownWord.push(item);
    }
  }
}

console.log(JSON.stringify({
  totalParrotRows: rows.length,
  allDownWord: notDownWord.length === 0,
  notDownWordCount: notDownWord.length,
  notDownWord,
  rows,
}, null, 2));
