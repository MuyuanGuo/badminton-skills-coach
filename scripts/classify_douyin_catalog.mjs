import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const sourcePath = path.join(root, "data", "douyin_video_index.json");
const outputDir = path.join(root, "output");
const source = JSON.parse(await fs.readFile(sourcePath, "utf8"));

const taxonomies = [
  ["发球与接发", /发球|接发|偷后场|发接发/],
  ["后场技术", /杀球|重杀|点杀|劈杀|吊球|高远球|后场|架拍|挥拍|鞭打|内旋|外旋/],
  ["网前技术", /搓球|勾球|扑球|放网|网前|推球|展搓|收搓/],
  ["中前场与抽挡", /抽挡|平抽|挡网|封网|中场|抓推|抓扑/],
  ["步法与移动", /步法|启动|蹬跨|并步|交叉步|回动|移动|弹性|重心|身位/],
  ["发力与身体运用", /发力|手腕|手指|小臂|肩|肘|核心|转体|蹬转|动力链|放松/],
  ["握拍与基本动作", /握拍|拍面|框架|击球点|击球|引拍|随挥|基本功/],
  ["单打战术", /单打|控网|拉吊|突击|四方球|节奏|线路|落点/],
  ["双打战术", /双打|轮转|抓回头|防守反击|封网|补位|站位|混双|男双|女双/],
  ["训练与纠错", /训练|练习|纠错|错误|改正|辅助|方法|教学|业余球友/],
  ["比赛分析", /比赛|复盘|回合|运动员|世锦赛|奥运|公开赛|大师赛/],
  ["装备与参数", /球拍|拍线|磅|手胶|底胶|线孔|连钉|球鞋|装备/],
];

const adStrong = /紫电青霜|华羽|首发|发售|上新|直播间|购买|下单|福利|抽奖|礼盒|新品|库存|价格|链接|同款|预售|品牌合作/;
const equipment = /球拍|拍线|磅数|手胶|底胶|线孔|连钉|球鞋|装备/;
const teaching = /羽毛球教学|羽毛球训练|教学|训练|发力|杀球|吊球|高远球|步法|搓球|勾球|扑球|放网|发球|接发|握拍|挥拍|架拍|击球|双打|单打|战术|落点|线路|拍面|框架|纠错|基本功/;
const nonTeaching = /生日|拜年|新年|春节|放假|通知|停播|开播|日常|花絮|合影|见面会|招生|招募|学员反馈|感谢大家|粉丝|吃饭|旅游|搞笑/;
const manualExclusions = new Map([
  ["7239168493294226740", "排除：广告/器材推广"],
  ["7588003889807756593", "排除：非教学"],
]);

function classify(video, index) {
  const text = `${video.title} ${video.raw_text}`;
  const ad = adStrong.test(text);
  const hasTeaching = teaching.test(text);
  const equipmentOnly = equipment.test(text) && !hasTeaching;
  const explicitNonTeaching = nonTeaching.test(text) && !hasTeaching;
  const authorStatus = index < source.profile_declared_works
    ? "主页作品区确认"
    : "待复核（超出主页标注数量）";

  let decision = "排除：非教学";
  let reason = "未发现明确教学动作、训练方法或战术信息";
  if (ad && hasTeaching) {
    decision = "待复核：教学夹带推广";
    reason = "同时出现教学信号与品牌、发售或购买信号";
  } else if (ad || equipmentOnly) {
    decision = "排除：广告/器材推广";
    reason = ad ? "出现品牌、发售、直播间或购买信号" : "仅讨论器材，未发现教学信号";
  } else if (hasTeaching && !explicitNonTeaching) {
    decision = "保留：教学";
    reason = "包含明确技术、训练、纠错或战术信号";
  } else if (explicitNonTeaching) {
    reason = "内容更接近日常、通知、招生或花絮";
  }

  if (manualExclusions.has(video.video_id)) {
    decision = manualExclusions.get(video.video_id);
    reason = "用户指定去除";
  } else if (decision.startsWith("待复核")) {
    decision = "保留：教学";
    reason = "用户复核确认保留";
  }

  const matched = taxonomies.filter(([, pattern]) => pattern.test(text)).map(([name]) => name);
  let primary = matched[0] || "其他教学";
  if (decision !== "保留：教学" && !decision.startsWith("待复核")) primary = "";

  return {
    ...video,
    author_status: authorStatus,
    decision,
    decision_reason: reason,
    primary_category: primary,
    tags: matched.join("；"),
  };
}

const rows = source.videos.map(classify);
const kept = rows.filter((row) => row.decision === "保留：教学");
const review = rows.filter((row) => row.decision.startsWith("待复核"));
const excludedAds = rows.filter((row) => row.decision === "排除：广告/器材推广");
const excludedOther = rows.filter((row) => row.decision === "排除：非教学");

const csvHeaders = [
  "video_id", "url", "title", "author_status", "decision", "decision_reason",
  "primary_category", "tags", "raw_text",
];
const csvEscape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const csv = [
  csvHeaders.join(","),
  ...rows.map((row) => csvHeaders.map((header) => csvEscape(row[header])).join(",")),
].join("\n") + "\n";

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(path.join(root, "data", "douyin_video_classified.csv"), csv, "utf8");
await fs.writeFile(
  path.join(root, "data", "douyin_teaching_filtered.json"),
  JSON.stringify({
    source_profile: source.profile_url,
    generated_at: new Date().toISOString(),
    methodology: "基于主页作品区与标题文案的规则初筛；待复核项需查看视频画面或逐条作者页。",
    counts: {
      total: rows.length,
      kept_teaching: kept.length,
      review: review.length,
      excluded_ads: excludedAds.length,
      excluded_non_teaching: excludedOther.length,
    },
    videos: kept,
  }, null, 2) + "\n",
  "utf8",
);

const workbook = Workbook.create();
const summary = workbook.worksheets.add("分类汇总");
const catalog = workbook.worksheets.add("全部作品");
const teachingSheet = workbook.worksheets.add("保留教学");
const reviewSheet = workbook.worksheets.add("待复核");

const categoryCounts = new Map();
for (const row of kept) {
  categoryCounts.set(row.primary_category, (categoryCounts.get(row.primary_category) || 0) + 1);
}
const categoryRows = [...categoryCounts.entries()].sort((a, b) => b[1] - a[1]);
const noteStartRow = Math.max(10, 5 + categoryRows.length);
const noteEndRow = noteStartRow + 2;

summary.getRange("A1:F1").merge();
summary.getRange("A1").values = [["刘辉羽毛球：抖音作品复核与教学分类"]];
summary.getRange("A3:B8").values = [
  ["指标", "数量"],
  ["采集唯一链接", rows.length],
  ["保留教学", kept.length],
  ["待复核", review.length],
  ["排除广告/器材推广", excludedAds.length],
  ["排除非教学", excludedOther.length],
];
summary.getRange(`D3:E${3 + categoryRows.length}`).values = [
  ["教学主类", "数量"],
  ...categoryRows,
];
summary.getRange(`A${noteStartRow}:F${noteEndRow}`).merge();
summary.getRange(`A${noteStartRow}`).values = [[
  "复核说明：作者归属以“刘辉羽毛球”主页作品区为依据；主页标注460条，实际捕获470个唯一链接，超出部分标为待复核。分类基于标题与文案，混合推广内容不直接纳入教学知识库。",
]];

const sheetHeaders = [
  "视频ID", "标题", "作者复核", "处理结果", "判定理由", "主分类", "标签", "链接",
];
function writeRows(sheet, data, tableName) {
  const matrix = [
    sheetHeaders,
    ...data.map((row) => [
      row.video_id, row.title, row.author_status, row.decision,
      row.decision_reason, row.primary_category, row.tags, row.url,
    ]),
  ];
  sheet.getRangeByIndexes(0, 0, matrix.length, sheetHeaders.length).values = matrix;
  const table = sheet.tables.add(`A1:H${matrix.length}`, true, tableName);
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  sheet.getRange(`A1:H${matrix.length}`).format.font = { name: "Arial", size: 10 };
  sheet.getRange("A1:H1").format = {
    fill: "#176B5B",
    font: { bold: true, color: "#FFFFFF", name: "Arial", size: 10 },
  };
  sheet.getRange(`B2:B${matrix.length}`).format.wrapText = true;
  sheet.getRange(`E2:G${matrix.length}`).format.wrapText = true;
  sheet.getRange(`A1:A${matrix.length}`).format.columnWidth = 19;
  sheet.getRange(`B1:B${matrix.length}`).format.columnWidth = 48;
  sheet.getRange(`C1:D${matrix.length}`).format.columnWidth = 23;
  sheet.getRange(`E1:E${matrix.length}`).format.columnWidth = 38;
  sheet.getRange(`F1:G${matrix.length}`).format.columnWidth = 24;
  sheet.getRange(`H1:H${matrix.length}`).format.columnWidth = 42;
}

writeRows(catalog, rows, "AllVideos");
writeRows(teachingSheet, kept, "TeachingVideos");
writeRows(reviewSheet, review, "ReviewVideos");

summary.showGridLines = false;
summary.getRange("A1:F1").format = {
  fill: "#123B36",
  font: { bold: true, color: "#FFFFFF", name: "Arial", size: 16 },
  verticalAlignment: "center",
};
summary.getRange("A1:F1").format.rowHeight = 30;
summary.getRange("A3:B3").format = {
  fill: "#176B5B", font: { bold: true, color: "#FFFFFF" },
};
summary.getRange(`D3:E${3 + categoryRows.length}`).format.borders = {
  preset: "inside", style: "thin", color: "#D7E1DF",
};
summary.getRange("D3:E3").format = {
  fill: "#B85C38", font: { bold: true, color: "#FFFFFF" },
};
summary.getRange(`A${noteStartRow}:F${noteEndRow}`).format = {
  fill: "#F2F5F4", font: { color: "#384744", size: 10 }, wrapText: true,
};
summary.getRange(`A1:A${noteEndRow}`).format.columnWidth = 29;
summary.getRange(`B1:B${noteEndRow}`).format.columnWidth = 14;
summary.getRange(`C1:C${noteEndRow}`).format.columnWidth = 4;
summary.getRange("D1:D20").format.columnWidth = 28;
summary.getRange("E1:E20").format.columnWidth = 12;

const preview = await workbook.render({
  sheetName: "分类汇总",
  range: `A1:F${noteEndRow}`,
  scale: 1.5,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "douyin-classification-preview.png"),
  new Uint8Array(await preview.arrayBuffer()),
);

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(path.join(outputDir, "刘辉羽毛球-抖音教学分类.xlsx"));

console.log(JSON.stringify({
  total: rows.length,
  kept: kept.length,
  review: review.length,
  excludedAds: excludedAds.length,
  excludedOther: excludedOther.length,
  categories: categoryRows,
}, null, 2));
