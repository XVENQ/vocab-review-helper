// 一次性脚本：修正 HINT_MN 里 wander 的措辞（HINT_MN 区段内替换，避免误伤 BUILTIN）
const fs = require("fs");
const p = "C:/Users/xuenc/Desktop/wokBuddy/outputs/单词复习/背词助手.html";
let html = fs.readFileSync(p, "utf8");
const hm = html.indexOf("const HINT_MN");
const seg = html.slice(hm);
const m = seg.match(/"wander":"[^"]*"/);
if (!m) { console.log("HINT_MN 内未找到 wander"); process.exit(1); }
console.log("旧文案:", m[0]);
const newEntry = '"wander":"wander(漫游 wand 走) → 闲逛、走神；形近 wonder(惊奇)：wander 乱走，wonder 惊叹"';
html = html.slice(0, hm) + seg.replace(m[0], newEntry);
fs.writeFileSync(p, html, "utf8");
console.log("已修正");
