import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputPath = "转录数据/LLM转录.xlsx";
const backupPath = "转录数据/LLM转录.backup_before_downword_fix.xlsx";
const outputDir = "outputs/llm_downword_fix_20260425";
const fallbackPath = `${outputDir}/LLM转录_已修正.xlsx`;
const reportPath = `${outputDir}/LLM下位词相似候选清单.xlsx`;
const analysisPath = ".codex-work/llm-cleanup-analysis.json";

function toCellValue(value) {
  if (value instanceof Set) return [...value].join("、");
  if (Array.isArray(value)) return value.join("、");
  return value ?? "";
}

function rowsToMatrix(headers, rows) {
  return [
    headers,
    ...rows.map((row) => headers.map((header) => toCellValue(row[header]))),
  ];
}

const analysis = JSON.parse(await fs.readFile(analysisPath, "utf8"));
await fs.mkdir(outputDir, { recursive: true });

try {
  await fs.access(backupPath);
} catch {
  await fs.copyFile(inputPath, backupPath);
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheet = workbook.worksheets.getItem("Sheet1");

for (const correction of analysis.downCorrections) {
  sheet.getRange(`H${correction.row}`).values = [[correction.newType]];
}

for (const correction of analysis.athleteCorrections) {
  sheet.getRange(`H${correction.row}`).values = [[correction.newType]];
}

const output = await SpreadsheetFile.exportXlsx(workbook);
let savedPath = inputPath;
let originalOverwritten = true;
try {
  await output.save(inputPath);
} catch (error) {
  if (error?.code !== "EBUSY") throw error;
  await output.save(fallbackPath);
  savedPath = fallbackPath;
  originalOverwritten = false;
}

const reportWorkbook = Workbook.create();

const summarySheet = reportWorkbook.worksheets.add("相似候选汇总");
const summaryRows = analysis.similarCandidates.map((item) => ({
  "名词（内容）": item.noun,
  "可能对应的下位词": item.downWord,
  "原表行号": item.rows.join("、"),
  "question_id": item.questionIds.join("、"),
  "当前名词类型": item.types,
  "判断依据": item.reason,
  "相似度": item.score,
  "出现次数": item.rows.length,
}));
summarySheet
  .getRange(`A1:H${Math.max(summaryRows.length + 1, 1)}`)
  .values = rowsToMatrix(
    ["名词（内容）", "可能对应的下位词", "原表行号", "question_id", "当前名词类型", "判断依据", "相似度", "出现次数"],
    summaryRows,
  );

const detailSheet = reportWorkbook.worksheets.add("相似候选明细");
const detailRows = analysis.similarCandidates.flatMap((item) =>
  item.rows.map((row, index) => ({
    "原表行号": row,
    "question_id": item.questionIds[index] ?? "",
    "名词（内容）": item.noun,
    "可能对应的下位词": item.downWord,
    "当前名词类型": item.types,
    "判断依据": item.reason,
    "相似度": item.score,
  })),
);
detailSheet
  .getRange(`A1:G${Math.max(detailRows.length + 1, 1)}`)
  .values = rowsToMatrix(
    ["原表行号", "question_id", "名词（内容）", "可能对应的下位词", "当前名词类型", "判断依据", "相似度"],
    detailRows,
  );

const correctionSheet = reportWorkbook.worksheets.add("已自动修正明细");
const downCorrectionRows = analysis.downCorrections.map((item) => ({
  "原表行号": item.row,
  "test_id": item.test_id,
  "question_id": item.question_id,
  "名词（内容）": item.noun,
  "原名词类型": item.oldType,
  "新名词类型": item.newType,
}));
correctionSheet
  .getRange(`A1:F${Math.max(downCorrectionRows.length + 1, 1)}`)
  .values = rowsToMatrix(
    ["原表行号", "test_id", "question_id", "名词（内容）", "原名词类型", "新名词类型"],
    downCorrectionRows,
  );

const athleteSheet = reportWorkbook.worksheets.add("运动员检查");
const athleteRows = analysis.athleteCorrections.map((item) => ({
  "原表行号": item.row,
  "test_id": item.test_id,
  "question_id": item.question_id,
  "名词（内容）": item.noun,
  "原名词类型": item.oldType,
  "新名词类型": item.newType,
}));
athleteSheet
  .getRange(`A1:F${Math.max(athleteRows.length + 1, 1)}`)
  .values = rowsToMatrix(
    ["原表行号", "test_id", "question_id", "名词（内容）", "原名词类型", "新名词类型"],
    athleteRows,
  );

const downWordSheet = reportWorkbook.worksheets.add("下位词词表");
const downWordRows = analysis.uniqueDownWords.map((word) => {
  const sourceRows = analysis.promptRows.filter((item) => item.downWord === word);
  return {
    "下位词": word,
    "来源行号": sourceRows.map((item) => item.row).join("、"),
    "来源prompt": sourceRows.map((item) => item.prompt).join(" | "),
  };
});
downWordSheet
  .getRange(`A1:C${Math.max(downWordRows.length + 1, 1)}`)
  .values = rowsToMatrix(["下位词", "来源行号", "来源prompt"], downWordRows);

const reportOutput = await SpreadsheetFile.exportXlsx(reportWorkbook);
await reportOutput.save(reportPath);

console.log(JSON.stringify({
  savedPath,
  originalOverwritten,
  backupPath,
  reportPath,
  downCorrectedRows: analysis.downCorrectionCount,
  athleteCorrectedRows: analysis.athleteCorrectionCount,
  similarCandidateGroups: analysis.similarCandidateCount,
  similarCandidateRows: detailRows.length,
}, null, 2));
