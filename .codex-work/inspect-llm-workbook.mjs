import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const file = "转录数据/LLM转录.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));

const info = await workbook.inspect({
  kind: "workbook",
  summary: "workbook sheets",
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
