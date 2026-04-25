import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "转录数据/LLM转录.xlsx";
const reportPath = "outputs/llm_downword_fix_20260425/LLM下位词相似候选清单.xlsx";
const analysis = JSON.parse(await fs.readFile(".codex-work/llm-cleanup-analysis.json", "utf8"));

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheet = workbook.worksheets.getItem("Sheet1");
const values = sheet.getRange("A1:J10000").values;

const failedDown = analysis.downCorrections
  .map((item) => ({ row: item.row, value: values[item.row - 1]?.[7] }))
  .filter((item) => item.value !== "下位词");

const failedAthlete = analysis.athleteCorrections
  .map((item) => ({ row: item.row, value: values[item.row - 1]?.[7] }))
  .filter((item) => item.value !== "普通词");

const athleteBadRows = [];
for (let i = 1; i < values.length; i += 1) {
  const row = values[i];
  if (!row.some((value) => value !== null && value !== undefined && value !== "")) continue;
  if (String(row[5] ?? "").trim() === "运动员" && String(row[7] ?? "").trim() !== "普通词") {
    athleteBadRows.push({
      row: i + 1,
      question_id: row[1],
      nounType: row[7],
    });
  }
}

const reportWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(reportPath));
const reportChecks = [];
for (const [sheetName, range] of [
  ["相似候选汇总", "A1:H12"],
  ["相似候选明细", "A1:G12"],
  ["已自动修正明细", "A1:F12"],
  ["运动员检查", "A1:F12"],
  ["下位词词表", "A1:C12"],
]) {
  const table = await reportWorkbook.inspect({
    kind: "table",
    range: `${sheetName}!${range}`,
    include: "values",
    tableMaxRows: 12,
    tableMaxCols: 8,
    summary: `${sheetName} preview`,
  });
  const parsed = table.ndjson
    .trim()
    .split(/\r?\n/)
    .map((line) => JSON.parse(line))
    .at(-1);
  reportChecks.push({
    sheetName,
    rows: parsed.rows,
    cols: parsed.cols,
    firstRow: parsed.values?.[0],
    secondRow: parsed.values?.[1] ?? null,
  });
}

const formulaErrors = await reportWorkbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});

const renderChecks = [];
for (const [label, targetWorkbook, sheetName, range] of [
  ["llm", workbook, "Sheet1", "A1:J20"],
  ["summary", reportWorkbook, "相似候选汇总", "A1:H20"],
  ["detail", reportWorkbook, "相似候选明细", "A1:G20"],
  ["corrections", reportWorkbook, "已自动修正明细", "A1:F20"],
  ["athlete", reportWorkbook, "运动员检查", "A1:F20"],
  ["downWords", reportWorkbook, "下位词词表", "A1:C20"],
]) {
  const rendered = await targetWorkbook.render({ sheetName, range, scale: 1 });
  renderChecks.push({ label, sheetName, rendered: Boolean(rendered) });
}

console.log(JSON.stringify({
  downCorrectionsExpected: analysis.downCorrectionCount,
  failedDownCount: failedDown.length,
  failedDown,
  athleteCorrectionsExpected: analysis.athleteCorrectionCount,
  failedAthleteCount: failedAthlete.length,
  failedAthlete,
  athleteBadRows,
  reportChecks,
  renderChecks,
  formulaErrors: formulaErrors.ndjson,
}, null, 2));
