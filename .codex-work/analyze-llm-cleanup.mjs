import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const llmPath = "转录数据/LLM转录.xlsx";
const downPath = "数据源/result_data_downWord.xlsx";
const nounTypeDown = "下位词";
const athleteNoun = "运动员";
const athleteType = "普通词";

function clean(value) {
  return String(value ?? "")
    .replace(/\s+/g, "")
    .replace(/[。．.，,、；;：:！？!?（）()【】\[\]“”"']/g, "")
    .trim();
}

function extractDownWord(prompt) {
  const text = String(prompt ?? "").trim();
  const match = text.match(/_+(.+?)[。．.，,、；;：:！？!?\s]*$/);
  return match ? clean(match[1]) : "";
}

function levenshtein(a, b) {
  const aa = Array.from(a);
  const bb = Array.from(b);
  const dp = Array.from({ length: aa.length + 1 }, (_, i) => [i]);
  for (let j = 1; j <= bb.length; j += 1) dp[0][j] = j;
  for (let i = 1; i <= aa.length; i += 1) {
    for (let j = 1; j <= bb.length; j += 1) {
      const cost = aa[i - 1] === bb[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + cost,
      );
    }
  }
  return dp[aa.length][bb.length];
}

function charJaccard(a, b) {
  const sa = new Set(Array.from(a));
  const sb = new Set(Array.from(b));
  const intersection = [...sa].filter((ch) => sb.has(ch)).length;
  const union = new Set([...sa, ...sb]).size;
  return union === 0 ? 0 : intersection / union;
}

function bestSimilar(noun, downWords) {
  const normalized = clean(noun);
  if (!normalized || normalized === athleteNoun) return null;
  let best = null;

  for (const down of downWords) {
    if (!down || normalized === down) continue;

    const includes =
      normalized.length >= 2 &&
      down.length >= 2 &&
      (normalized.includes(down) || down.includes(normalized));
    const distance = levenshtein(normalized, down);
    const maxLen = Math.max(Array.from(normalized).length, Array.from(down).length);
    const editScore = maxLen === 0 ? 0 : 1 - distance / maxLen;
    const overlap = charJaccard(normalized, down);

    let reason = "";
    let score = Math.max(editScore, overlap);
    if (includes) {
      reason = "包含关系";
      score = Math.max(score, 0.95);
    } else if (editScore >= 0.67 && maxLen >= 2) {
      reason = "编辑距离接近";
    } else if (overlap >= 0.5 && maxLen >= 3) {
      reason = "字符重合较高";
    } else {
      continue;
    }

    if (!best || score > best.score) {
      best = { downWord: down, score, reason };
    }
  }
  return best;
}

const downWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(downPath));
const downSheet = downWorkbook.worksheets.getItem("selected_120_images");
const downValues = downSheet.getRange("A1:W500").values;
const downHeader = downValues[0];
const promptIdx = downHeader.indexOf("prompt");

const downWords = [];
const promptRows = [];
for (let i = 1; i < downValues.length; i += 1) {
  const prompt = downValues[i][promptIdx];
  if (!prompt) continue;
  const downWord = extractDownWord(prompt);
  if (!downWord) continue;
  downWords.push(downWord);
  promptRows.push({ row: i + 1, prompt, downWord });
}

const uniqueDownWords = [...new Set(downWords)].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
const downWordSet = new Set(uniqueDownWords);

const llmWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(llmPath));
const sheet = llmWorkbook.worksheets.getItem("Sheet1");
const values = sheet.getRange("A1:J10000").values;
const header = values[0];
const nounIdx = header.indexOf("名词（内容）");
const typeIdx = header.indexOf("名词类型");

const downCorrections = [];
const athleteCorrections = [];
const similarByPair = new Map();

for (let i = 1; i < values.length; i += 1) {
  const row = values[i];
  if (!row.some((value) => value !== null && value !== undefined && value !== "")) continue;

  const noun = clean(row[nounIdx]);
  const type = clean(row[typeIdx]);
  if (noun === athleteNoun && type !== athleteType) {
    athleteCorrections.push({
      row: i + 1,
      test_id: row[0],
      question_id: row[1],
      noun: row[nounIdx],
      oldType: row[typeIdx],
      newType: athleteType,
    });
    continue;
  }

  if (downWordSet.has(noun)) {
    if (type !== nounTypeDown) {
      downCorrections.push({
        row: i + 1,
        test_id: row[0],
        question_id: row[1],
        noun: row[nounIdx],
        oldType: row[typeIdx],
        newType: nounTypeDown,
      });
    }
    continue;
  }

  const similar = bestSimilar(noun, uniqueDownWords);
  if (similar) {
    const key = `${noun}\t${similar.downWord}`;
    if (!similarByPair.has(key)) {
      similarByPair.set(key, {
        noun,
        downWord: similar.downWord,
        reason: similar.reason,
        score: Number(similar.score.toFixed(3)),
        rows: [],
        questionIds: [],
        types: new Set(),
      });
    }
    const entry = similarByPair.get(key);
    entry.rows.push(i + 1);
    entry.questionIds.push(row[1]);
    entry.types.add(String(row[typeIdx] ?? ""));
  }
}

const similarCandidates = [...similarByPair.values()]
  .map((entry) => ({
    ...entry,
    types: [...entry.types].filter(Boolean).join("、"),
  }))
  .sort((a, b) => b.score - a.score || a.noun.localeCompare(b.noun, "zh-Hans-CN"));

const report = {
  downWordCount: downWords.length,
  uniqueDownWordCount: uniqueDownWords.length,
  uniqueDownWords,
  promptRows,
  downCorrectionCount: downCorrections.length,
  downCorrections,
  athleteCorrectionCount: athleteCorrections.length,
  athleteCorrections,
  similarCandidateCount: similarCandidates.length,
  similarCandidates,
};

await fs.writeFile(".codex-work/llm-cleanup-analysis.json", JSON.stringify(report, null, 2), "utf8");
console.log(JSON.stringify({
  downWordCount: report.downWordCount,
  uniqueDownWordCount: report.uniqueDownWordCount,
  downCorrectionCount: report.downCorrectionCount,
  athleteCorrectionCount: report.athleteCorrectionCount,
  similarCandidateCount: report.similarCandidateCount,
  firstDownCorrections: downCorrections.slice(0, 10),
  athleteCorrections,
  firstSimilarCandidates: similarCandidates.slice(0, 20),
}, null, 2));
