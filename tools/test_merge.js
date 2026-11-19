#!/usr/bin/env node
/* mergeWords / mergeDeleted 单元测试：从背词助手.html 里切出 SYNC-CORE 直接 eval
   用法：node tools/test_merge.js */
const fs = require("fs");
const html = fs.readFileSync(__dirname + "/../../outputs/单词复习/背词助手.html", "utf8")
  .replace(/\r\n/g, "\n");
const m = html.match(/\/\* ==== SYNC-CORE-BEGIN[\s\S]*?\/\* SYNC-CORE-END \*\//);
if (!m) { console.error("SYNC-CORE 段没找到"); process.exit(1); }
eval(m[0]);

let pass = 0, fail = 0;
function eq(name, cond, detail) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name + (detail ? "  " + detail : "")); }
}
const W = (id, word, extra) => Object.assign({ id: id, word: word, meaning: "n. 测试" }, extra || {});

// T1 两边各有独有词 → 并集
(() => {
  const r = mergeWords([W(1, "apple")], [W(2, "banana")], [], []);
  eq("T1 独有词并集", r.words.length === 2);
})();

// T2 同 id 同词文，一边 mt 新
(() => {
  const a = W(1, "apple", { step: 1 }), b = W(1, "apple", { step: 3, mt: 9999 });
  const r = mergeWords([a], [b], [], []);
  eq("T2 mt 新者胜", r.words[0].step === 3);
})();

// T3 无 mt，lastRated 不同日
(() => {
  const a = W(1, "apple", { lastRated: "2026-11-07" });
  const b = W(1, "apple", { lastRated: "2026-11-08" });
  const r = mergeWords([a], [b], [], []);
  eq("T3 lastRated 新者胜", r.words[0].lastRated === "2026-11-08");
})();

// T4 lastRated 同日 → step 大者
(() => {
  const a = W(1, "apple", { lastRated: "2026-11-08", step: 1 });
  const b = W(1, "apple", { lastRated: "2026-11-08", step: 4 });
  const r = mergeWords([a], [b], [], []);
  eq("T4 step 大者胜", r.words[0].step === 4);
})();

// T5 全字段平 → 取 local（幂等关键）
(() => {
  const a = W(1, "apple", { step: 2, tag: "local" }), b = W(1, "apple", { step: 2, tag: "server" });
  const r = mergeWords([a], [b], [], []);
  eq("T5 平局取 local", r.words[0].tag === "local");
})();

// T6 同 id 不同词文 → server 词重编号
(() => {
  const a = W(5, "apple"), b = W(5, "bread");
  const r = mergeWords([a], [b], [], []);
  const bread = r.words.find(w => w.word === "bread");
  eq("T6 id 撞车重编号", r.words.length === 2 && bread && bread.id > 5);
  eq("T6b 不给撞车写墓碑", r.deleted.length === 0);
})();

// T7 不同 id 同词文 → recency 大者胜，败者墓碑
(() => {
  const a = W(1, "apple", { mt: 1000 }), b = W(9, "apple", { mt: 2000 });
  const r = mergeWords([a], [b], [], []);
  eq("T7 同词文合并", r.words.length === 1 && r.words[0].mt === 2000);
  eq("T7b 败者墓碑", r.deleted.some(t => String(t.id) === "1" && t.word === "apple"));
})();

// T8 墓碑命中（词不比墓碑新）→ 删
(() => {
  const a = [W(1, "apple", { mt: 500 })], tomb = [{ id: 1, word: "apple", at: 900 }];
  const r = mergeWords(a, [], tomb, []);
  eq("T8 墓碑删除", r.words.length === 0);
})();

// T9 复活（词比墓碑新）→ 保留
(() => {
  const a = [W(1, "apple", { mt: 1200 })], tomb = [{ id: 1, word: "apple", at: 900 }];
  const r = mergeWords(a, [], tomb, []);
  eq("T9 新于墓碑复活", r.words.length === 1);
})();

// T10 幂等性 merge(merge(A,B),B) == merge(A,B)
(() => {
  const A = [W(1, "apple", { mt: 100 }), W(2, "bear", { lastRated: "2026-11-08" })];
  const B = [W(2, "bear", { mt: 200, step: 2 }), W(3, "cat")];
  const r1 = mergeWords(A, B, [], []);
  const r2 = mergeWords(r1.words, B, r1.deleted, []);
  eq("T10 幂等", JSON.stringify(r1) === JSON.stringify(r2));
})();

// T11 交换律：词集合相等
(() => {
  const A = [W(1, "apple", { mt: 100 }), W(2, "bear", { step: 1 })];
  const B = [W(2, "bear", { mt: 200 }), W(3, "cat", { mt: 50 })];
  const s1 = mergeWords(A, B, [], []).words.map(w => w.word).sort().join(",");
  const s2 = mergeWords(B, A, [], []).words.map(w => w.word).sort().join(",");
  eq("T11 交换律词集", s1 === s2);
})();

// T12 墓碑上限 2000
(() => {
  const big = []; for (let i = 0; i < 3000; i++) big.push({ id: i, word: "w" + i, at: i });
  const r = mergeWords([], [], [], big);
  eq("T12 墓碑上限 2000", r.deleted.length === 2000);
})();

// T13 缺字段容错
(() => {
  let ok = true;
  try {
    mergeWords([W(1, "apple")], undefined, undefined, undefined);
    mergeWords([], [], undefined, undefined);
    mergeWords([{}], [{}], [{ id: 1 }], []);
  } catch (e) { ok = false; console.log(e.message); }
  eq("T13 缺字段容错", ok);
})();

// T14 profInit 边界
(() => {
  eq("T14a 新词 45", profInit({ step: 0, lapse: 0 }) === 45);
  eq("T14b step6 无失败 clamp 90", profInit({ step: 6, lapse: 0 }) === 90);
  eq("T14c lapse6 → 15", profInit({ step: 0, lapse: 6 }) === 15);
  eq("T14d 缺字段 → 45", profInit({}) === 45);
})();

// T15 profUpdate delta 与 clamp
(() => {
  eq("T15a 重来 −8", profUpdate({ prof: 50 }, 0) === 42);
  eq("T15b 困难 −3", profUpdate({ prof: 50 }, 1) === 47);
  eq("T15c 良好 +4（spent 无信息 ×1.0）", profUpdate({ prof: 50, word: "apple" }, 2, 10000) === 54);
  eq("T15d 简单 +7", profUpdate({ prof: 50, word: "apple" }, 3, 10000) === 57);
  eq("T15e 上限 clamp 100", profUpdate({ prof: 98, word: "apple" }, 3, 10000) === 100);
  eq("T15f 下限 clamp 0", profUpdate({ prof: 3 }, 0) === 0);
})();

// T16 timeFactor：band 外无信息；词长移动阈值
(() => {
  const P = (w, ms, r) => profUpdate({ prof: 50, word: w }, r, ms) - 50;
  eq("T16a spent=0 无信息", P("apple", 0, 2) === 4);
  eq("T16b spent<2s 无信息", P("apple", 1000, 2) === 4);
  eq("T16c spent>60s 无信息", P("apple", 120000, 2) === 4);
  // apple 5 字母：fast=3000+250*5=4250（≤4250 → ×1.3）；slow=8000+800*5=12000
  eq("T16d apple 快答 ×1.3", P("apple", 4000, 2) === 5);   // round(4×1.3)=5
  eq("T16e apple 中速 ×1.0", P("apple", 8000, 2) === 4);
  eq("T16f apple 慢答 ×0.6", P("apple", 13000, 2) === 2);  // round(4×0.6)=2
  // 词长越长阈值越宽：4400ms 时 thrust(6字母,fast=4500) 拿快答加成，apple(5字母,fast=4250) 已出快区
  eq("T16g 阈值随词长移动", P("thrust", 4400, 2) === 5 && P("apple", 4400, 2) === 4);
})();

// T17 intervalMult 三点
(() => {
  eq("T17a prof0 → 0.75", intervalMult(0) === 0.75);
  eq("T17b prof100 → 1.3", intervalMult(100) === 1.3);
  eq("T17c prof50 ≈ 1.025", Math.abs(intervalMult(50) - 1.025) < 1e-9);
})();

// T18 newer：prof 决胜 + 无 prof 回落 timeMs
(() => {
  const a = W(1, "apple", { lastRated: "2026-11-08", step: 2, prof: 80 });
  const b = W(1, "apple", { lastRated: "2026-11-08", step: 2, prof: 30 });
  eq("T18a prof 高者胜", newer(a, b) === true && newer(b, a) === false);
  const c = W(1, "apple", { lastRated: "2026-11-08", step: 2, timeMs: 100 });
  const d = W(1, "apple", { lastRated: "2026-11-08", step: 2, timeMs: 200 });
  eq("T18b 无 prof 回落 timeMs", newer(d, c) === true);
})();

// T19 幂等含 prof：merge(merge(A,B),B) 与 merge(A,B) 全等
(() => {
  const A = [W(1, "apple", { mt: 100, prof: 72 })];
  const B = [W(1, "apple", { mt: 200, prof: 31, step: 3 })];
  const r1 = mergeWords(A, B, [], []);
  const r2 = mergeWords(r1.words, B, r1.deleted, []);
  eq("T19 幂等含 prof", JSON.stringify(r1) === JSON.stringify(r2));
})();

// T20 等 prof 平局取 local（幂等关键不因 prof 引入而破坏）
(() => {
  const a = W(1, "apple", { step: 2, prof: 50, tag: "local" });
  const b = W(1, "apple", { step: 2, prof: 50, tag: "server" });
  const r = mergeWords([a], [b], [], []);
  eq("T20 等 prof 平局取 local", r.words[0].tag === "local");
})();

// T21 quotaSort：逾期优先，同期限内 prof 升序，缺 prof 容错
(() => {
  const due = [
    W(3, "cat",  { nextDate: "2026-11-14", prof: 80 }),
    W(1, "apple",{ nextDate: "2026-11-13", prof: 70 }),
    W(2, "bear", { nextDate: "2026-11-14", prof: 20 }),
    W(4, "dog",  { nextDate: "2026-11-14" }),              // 缺 prof → 按 0
  ];
  const out = quotaSort(due).map(w => w.word);
  eq("T21a 逾期优先在前", out[0] === "apple");
  eq("T21b 同期限内 prof 升序", out.slice(1).join(",") === "dog,bear,cat");
  eq("T21c 不改原数组", due[0].word === "cat");
})();

console.log("\n通过 %d / %d", pass, pass + fail);
process.exit(fail ? 1 : 0);
