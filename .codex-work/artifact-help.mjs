import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = await FileBlob.load("转录数据/语音转录.xlsx");
const workbook = await SpreadsheetFile.importXlsx(input);
const help = await workbook.help("worksheet.getRange");
console.log(help);
