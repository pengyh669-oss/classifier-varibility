import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";

const analysis = JSON.parse(await fs.readFile(".codex-work/downword-analysis.json", "utf8"));
const correctedPath = "outputs/downword_fix_20260425/语音转录_已修正.xlsx";
const reportPath = "outputs/downword_fix_20260425/下位词相似候选清单.xlsx";

const correctedWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(correctedPath));
const correctedSheet = correctedWorkbook.worksheets.getItem("Sheet1");
const correctedValues = correctedSheet.getRange("A1:J5000").values;

const failedRows = analysis.exactCorrections
  .map((item) => ({ row: item.row, value: correctedValues[item.row - 1]?.[7] }))
  .filter((item) => item.value !== "下位词");

const correctedPreview = await correctedWorkbook.inspect({
  kind: "table",
  range: "Sheet1!A1:J12",
  include: "values",
  tableMaxRows: 12,
  tableMaxCols: 10,
  summary: "corrected workbook preview",
});

const reportWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(reportPath));
const reportChecks = [];
for (const [sheetName, range] of [
  ["相似候选汇总", "A1:H12"],
  ["相似候选明细", "A1:G12"],
  ["已自动修正明细", "A1:F12"],
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
    secondRow: parsed.values?.[1],
  });
}

const formulaErrors = await reportWorkbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "report formula error scan",
});

const renderChecks = [];
for (const [label, workbook, sheetName, range] of [
  ["corrected", correctedWorkbook, "Sheet1", "A1:J20"],
  ["summary", reportWorkbook, "相似候选汇总", "A1:H20"],
  ["detail", reportWorkbook, "相似候选明细", "A1:G20"],
  ["corrections", reportWorkbook, "已自动修正明细", "A1:F20"],
  ["downWords", reportWorkbook, "下位词词表", "A1:C20"],
]) {
  const rendered = await workbook.render({ sheetName, range, scale: 1 });
  renderChecks.push({
    label,
    sheetName,
    rendered: Boolean(rendered),
  });
}

console.log(JSON.stringify({
  exactCorrectionsExpected: analysis.exactCorrectionCount,
  failedCorrectionCount: failedRows.length,
  failedRows,
  correctedPreview: correctedPreview.ndjson.split(/\r?\n/)[0],
  reportChecks,
  renderChecks,
  formulaErrors: formulaErrors.ndjson,
}, null, 2));
