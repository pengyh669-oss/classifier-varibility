import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "转录数据/LLM转录.xlsx";
const backupPath = "转录数据/LLM转录.backup_before_parrot_fix.xlsx";
const outputDir = "outputs/llm_parrot_fix_20260425";
const fallbackPath = `${outputDir}/LLM转录_鹦鹉已修正.xlsx`;
const targetNoun = "鹦鹉";
const targetType = "下位词";

try {
  await fs.access(backupPath);
} catch {
  await fs.copyFile(inputPath, backupPath);
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheet = workbook.worksheets.getItem("Sheet1");
const values = sheet.getRange("A1:J10000").values;
const header = values[0];
const nounIndex = header.indexOf("名词（内容）");
const typeIndex = header.indexOf("名词类型");

const changed = [];
const allTargetRows = [];

for (let i = 1; i < values.length; i += 1) {
  const row = values[i];
  if (!row.some((value) => value !== null && value !== undefined && value !== "")) continue;
  const noun = String(row[nounIndex] ?? "").trim();
  const nounType = String(row[typeIndex] ?? "").trim();
  if (noun !== targetNoun) continue;

  allTargetRows.push({
    row: i + 1,
    test_id: row[0],
    question_id: row[1],
    oldType: row[typeIndex],
  });

  if (nounType !== targetType) {
    sheet.getRange(`H${i + 1}`).values = [[targetType]];
    changed.push({
      row: i + 1,
      test_id: row[0],
      question_id: row[1],
      oldType: row[typeIndex],
      newType: targetType,
    });
  }
}

const output = await SpreadsheetFile.exportXlsx(workbook);
let savedPath = inputPath;
let originalOverwritten = true;
try {
  await output.save(inputPath);
} catch (error) {
  if (error?.code !== "EBUSY") throw error;
  await fs.mkdir(outputDir, { recursive: true });
  await output.save(fallbackPath);
  savedPath = fallbackPath;
  originalOverwritten = false;
}

console.log(JSON.stringify({
  targetRowsCount: allTargetRows.length,
  changedCount: changed.length,
  allTargetRows,
  changed,
  backupPath,
  savedPath,
  originalOverwritten,
}, null, 2));
