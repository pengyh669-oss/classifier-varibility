import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const files = [
  "转录数据/语音转录.xlsx",
  "数据源/result_data_downWord.xlsx",
];

for (const file of files) {
  const input = await FileBlob.load(file);
  const workbook = await SpreadsheetFile.importXlsx(input);
  console.log(`\n=== ${file} ===`);
  const info = await workbook.inspect({
    kind: "workbook",
    summary: "workbook sheets and dimensions",
  });
  console.log(info.ndjson);
  const table = await workbook.inspect({
    kind: "table",
    range: "A1:Z12",
    include: "values",
    tableMaxRows: 12,
    tableMaxCols: 26,
    summary: "top-left cells",
  });
  console.log(table.ndjson);
}
