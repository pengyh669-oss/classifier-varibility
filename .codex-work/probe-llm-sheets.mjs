import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load("转录数据/LLM转录.xlsx"));

for (const sheetName of ["Sheet1", "Sheet2", "Sheet3"]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const values = sheet.getRange("A1:J10000").values;
  let lastNonEmptyRow = 0;
  let nonEmptyRows = 0;
  for (let i = 0; i < values.length; i += 1) {
    if (values[i].some((value) => value !== null && value !== undefined && value !== "")) {
      lastNonEmptyRow = i + 1;
      nonEmptyRows += 1;
    }
  }
  console.log(JSON.stringify({
    sheetName,
    lastNonEmptyRow,
    nonEmptyRows,
    firstRow: values[0],
  }));
}
