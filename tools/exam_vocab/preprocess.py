#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真题扫描件预处理：转正 + 切页 + 轻微增强

为什么必须做这一步：
  35 张照片的朝向不一致（部分整张旋转 90°），让视觉模型自己"判断方向"是
  最大的一类错误来源。先把每张图统一转正、切成单页，模型只需照着读。

输出：docs/exam_vocab/pages/img{NN}_{L|R}.png
      文件名里的 L/R 只是物理左右，**真实页码由转录时读到的印刷页码决定**，
      这样即使某张照片多出第三页碎片，也不会让全局页码错位。
"""
import io
import json
import os
import sys

from PIL import Image, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RAW = os.path.join(ROOT, "docs", "exam_vocab", "raw")
OUT = os.path.join(ROOT, "docs", "exam_vocab", "pages")
SRC = "C:/Users/xuenc/.workbuddy/clipboard-images"

# 页面与版心的裁剪余量（去掉扫描黑边）
PAD_L = 0.02
PAD_R = 0.02


def enhance(im):
    im = im.convert("RGB")
    im = ImageEnhance.Contrast(im).enhance(1.25)
    im = ImageEnhance.Sharpness(im).enhance(1.6)
    return im


def main():
    os.makedirs(OUT, exist_ok=True)
    man = json.loads(io.open(os.path.join(RAW, "_manifest.json"), encoding="utf-8").read())
    rows = []
    for r in man:
        p = os.path.join(SRC, r["file"])
        im = Image.open(p)
        w, h = im.size
        rot = 0
        if h > w:                       # 竖版 = 被旋转过，逆时针转正
            im = im.rotate(90, expand=True)
            rot = 90
        im = enhance(im)
        w, h = im.size
        mid = w // 2
        # 中缝两侧各留 1.5% 余量，避免把对页的字带进来
        cut = int(w * 0.015)
        left = im.crop((int(w * PAD_L), 0, mid - cut, h))
        right = im.crop((mid + cut, 0, int(w * (1 - PAD_R)), h))
        for side, img in (("L", left), ("R", right)):
            name = "img%02d_%s.png" % (r["idx"], side)
            img.save(os.path.join(OUT, name), optimize=True)
        rows.append({"idx": r["idx"], "file": r["file"], "rotated": rot,
                     "src_size": [w, h], "page_size": list(left.size),
                     "pages": ["img%02d_L.png" % r["idx"], "img%02d_R.png" % r["idx"]]})
        print("img%02d %s  rot=%d  page=%dx%d" % (r["idx"], r["tag"], rot, left.size[0], left.size[1]))

    io.open(os.path.join(OUT, "_pages.json"), "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=1))
    print("\n共 %d 张源图 → %d 张单页，输出 %s" % (len(rows), len(rows) * 2, OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
