import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

async function probe(file, sheetName, range) {
  const input = await FileBlob.load(file);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const sheet = workbook.worksheets.getItem(sheetName);
  const values = sheet.getRange(range).values;
  const nonEmptyRows = values
    .map((row, index) => ({ index: index + 1, hasValue: row.some((v) => v !== null && v !== undefined && v !== "") }))
    .filter((row) => row.hasValue);
  console.log(JSON.stringify({
    file,
    sheetName,
    range,
    rows: values.length,
    cols: values[0]?.length,
    lastNonEmptyRowInRange: nonEmptyRows.at(-1)?.index ?? 0,
    firstRow: values[0],
  }, null, 2));
}

await probe("转录数据/语音转录.xlsx", "Sheet1", "A1:J5000");
await probe("数据源/result_data_downWord.xlsx", "selected_120_images", "A1:W500");
