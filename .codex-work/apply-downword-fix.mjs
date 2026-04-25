import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const speechPath = "转录数据/语音转录.xlsx";
const backupPath = "转录数据/语音转录.backup_before_downword_fix.xlsx";
const outputDir = "outputs/downword_fix_20260425";
const correctedCopyPath = `${outputDir}/语音转录_已修正.xlsx`;
const reportPath = `${outputDir}/下位词相似候选清单.xlsx`;
const analysisPath = ".codex-work/downword-analysis.json";
const nounTypeTarget = "下位词";

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
  await fs.copyFile(speechPath, backupPath);
}

const speechWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(speechPath));
const speechSheet = speechWorkbook.worksheets.getItem("Sheet1");

for (const correction of analysis.exactCorrections) {
  speechSheet.getRange(`H${correction.row}`).values = [[nounTypeTarget]];
}

const updatedSpeech = await SpreadsheetFile.exportXlsx(speechWorkbook);
let correctedFile = speechPath;
let originalOverwritten = true;
try {
  await updatedSpeech.save(speechPath);
} catch (error) {
  if (error?.code !== "EBUSY") throw error;
  correctedFile = correctedCopyPath;
  originalOverwritten = false;
  await updatedSpeech.save(correctedCopyPath);
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
const correctionRows = analysis.exactCorrections.map((item) => ({
  "原表行号": item.row,
  "test_id": item.test_id,
  "question_id": item.question_id,
  "名词（内容）": item.noun,
  "原名词类型": item.oldType,
  "新名词类型": item.newType,
}));
correctionSheet
  .getRange(`A1:F${Math.max(correctionRows.length + 1, 1)}`)
  .values = rowsToMatrix(
    ["原表行号", "test_id", "question_id", "名词（内容）", "原名词类型", "新名词类型"],
    correctionRows,
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
  correctedFile,
  originalOverwritten,
  backupFile: backupPath,
  reportFile: reportPath,
  correctedRows: analysis.exactCorrectionCount,
  similarCandidateGroups: analysis.similarCandidateCount,
  similarCandidateRows: detailRows.length,
}, null, 2));
