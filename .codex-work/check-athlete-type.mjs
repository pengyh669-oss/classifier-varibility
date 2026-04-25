import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load("转录数据/语音转录.xlsx"));
const sheet = workbook.worksheets.getItem("Sheet1");
const values = sheet.getRange("A1:J5000").values;
const header = values[0];
const nounIndex = header.indexOf("名词（内容）");
const typeIndex = header.indexOf("名词类型");

const rows = [];
for (let i = 1; i < values.length; i += 1) {
  const row = values[i];
  if (!row.some((value) => value !== null && value !== undefined && value !== "")) continue;
  if (String(row[nounIndex] ?? "").trim() === "运动员") {
    rows.push({
      row: i + 1,
      test_id: row[0],
      question_id: row[1],
      noun: row[nounIndex],
      nounType: row[typeIndex],
    });
  }
}

const notNormal = rows.filter((row) => String(row.nounType ?? "").trim() !== "普通词");
console.log(JSON.stringify({
  totalAthleteRows: rows.length,
  allNormalWord: notNormal.length === 0,
  notNormalCount: notNormal.length,
  notNormal,
  rows,
}, null, 2));
