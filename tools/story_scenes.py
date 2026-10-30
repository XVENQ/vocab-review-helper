# -*- coding: utf-8 -*-
"""15 篇故事的段落划分与 60 个配图场景。

p = 给图片模型的画面描述（末尾会自动拼统一风格前缀）
z = 中文说明，显示在占位卡上，帮人判断该画什么
原则：只描述「看得见的东西」——人物动作、物件、光线、地点。
抽象概念（justice / capacity）不直接画，改用象征物（法槌、文件架）。
"""

# 每篇 4 段的句子数分配（必须与 split_sents 结果吻合）
SPLIT = {
    "A Small Accident":              [3, 3, 2, 3],
    "Up the Mountain":               [2, 2, 3, 2],
    "The Old Man Next Door":         [3, 2, 3, 3],
    "The Science Fair":              [2, 2, 2, 2],
    "A Letter from Abroad":          [2, 2, 2, 4],
    "The Race":                      [2, 2, 2, 3],
    "A Quiet Evening":               [2, 2, 2, 2],
    "The Missing Wallet":            [3, 3, 2, 3],
    "The New Community Center":      [3, 2, 2, 3],
    "The Letter That Was Never Sent": [3, 3, 2, 3],
    "Fourth Place":                  [2, 2, 3, 2],
    "The Old Radio":                 [2, 2, 3, 4],
    "Why We Forget":                 [3, 3, 3, 2],
    "The Cost of Convenience":       [2, 3, 2, 4],
    "What Justice Means":            [2, 3, 2, 2],
}

SCENES = {
"A Small Accident": [
 ("a boy on a bicycle bumping an old man's bag on a quiet street, a paper receipt falling out",
  "男孩骑车撞到老人的包，小票掉出来"),
 ("the boy standing still and bowing his head to apologize, the old man listening kindly",
  "男孩停下道歉，老人耐心听着"),
 ("the old man showing an empty wallet and a bank card, smiling gently",
  "老人只有卡没有现金，仍然笑着"),
 ("a few neighbors smiling and nodding on the street, warm afternoon, seen from a distance",
  "邻居们点头称许，一周后梦里重现"),
],
"Up the Mountain": [
 ("two brothers climbing a green mountain path with backpacks, morning mist, seen from behind",
  "兄弟二人背着包上山"),
 ("a small pool of water among rocks near a mountain top, dark rain clouds gathering",
  "山顶附近的小水潭，乌云压过来"),
 ("wet slippery rocks on a mountain trail, rain falling, a young hiker stepping carefully",
  "雨里石头打滑，走得很小心"),
 ("two figures sheltering under a large ancient rock, rain outside, warm dry space",
  "躲进古老的大岩石下避雨"),
],
"The Old Man Next Door": [
 ("an old bald man walking slowly with a cane on a quiet street, gentle expression",
  "李爷爷秃着头，走路缓慢"),
 ("a sick old man sitting by a window in winter, a neighbor handing him a bag of food",
  "冬天生病，邻居送来食物"),
 ("a thank-you card held in old hands, a simple wooden chair beside a bed",
  "一张感谢卡，一把结实的新椅子"),
 ("ice melting on a road in early spring, a young man smiling at an old man",
  "冰雪融化，我对他笑了"),
],
"The Science Fair": [
 ("a school science fair hall with blank display boards, children walking between tables",
  "科技展大厅，摊位排开"),
 ("a boy building a wooden triangle and right angle to hold a ball, tools on the table",
  "男孩用三角形和直角托住小球"),
 ("a boy pointing at a blank display board with a drawn triangle, teacher watching",
  "他在展板上画出图形并讲解"),
 ("a teacher and students finishing a small model together, afternoon classroom light",
  "老师帮忙完成最后一步"),
],
"A Letter from Abroad": [
 ("a laptop on a wooden desk showing a mail window, evening lamp light, a cup of tea",
  "叔叔在国外，每月通邮件"),
 ("a short handwritten reply on paper beside a keyboard, morning light",
  "回信很短：每天学一点"),
 ("a young student closing a book and turning off a desk lamp at night",
  "父母不许熬夜，我改早睡"),
 ("an old dusty cable in a desk drawer, warm afternoon light",
  "成绩上升，抽屉里翻出旧电缆"),
],
"The Race": [
 ("children lined up at the start of a school running race, morning light, seen from the side",
  "报名参赛，只想跑完"),
 ("a lonely runner at the back of a track, head down, long shadows",
  "跑在最后，和人比很绝望"),
 ("a runner training alone on an empty road at sunrise, steady pace",
  "每天清晨跑十分钟"),
 ("a runner crossing a finish line with a surprised happy face, friends cheering",
  "比赛日第五名，自己都吃惊"),
],
"A Quiet Evening": [
 ("a teenager reading aloud in a low voice at a desk, warm lamp, night window",
  "考前夜低声朗读，怕吵到妈妈"),
 ("a mother and teenager sitting close on a sofa, a hand on the shoulder, quiet room",
  "手搭在她肩上，说我们太担心了"),
 ("a small hot room at night, an open window, a glass of water on a table",
  "房间很热，开始出汗"),
 ("a young person washing face with cool water, early morning light",
  "用凉水洗脸，第二天心很平"),
],
"The Missing Wallet": [
 ("a messy bedroom, a teenager looking under a bed, morning light",
  "钱包不见了，翻床底"),
 ("a coat hanging on a chair being checked, a sister laughing in the background",
  "妹妹开玩笑说是外星人拿的"),
 ("a father pulling a wallet out from between sofa cushions, a broken cup on the floor",
  "爸爸从沙发缝里掏出钱包"),
 ("a wallet placed in a small wooden tray on a shelf, tidy room",
  "从此钱包固定放在一处"),
],
"The New Community Center": [
 ("an empty lot near a small park, low buildings in the distance, morning light",
  "社区没有聚会的地方"),
 ("construction workers pouring a foundation, wooden frames, safety helmets",
  "打地基，公司承接屋顶"),
 ("a woman pointing at a simple building plan on a table, neighbors listening",
  "陈女士负责方案，讲好处与坏处"),
 ("a small new community center with a parking area behind it, warm afternoon",
  "折中方案落地，中心建成"),
],
"The Letter That Was Never Sent": [
 ("a teenager writing a long letter at a desk, crumpled paper, evening lamp",
  "十五岁写下长信，没有寄出"),
 ("two young men meeting again on a street, one laughing, warm afternoon",
  "多年后重逢，他笑了"),
 ("two people sitting face to face at a small table, talking, cups of tea",
  "需要的不是信，是当面说话"),
 ("a sealed old letter lying in a desk drawer, dust, soft window light",
  "信从没离开过桌面"),
],
"Fourth Place": [
 ("runners gathered at a town race start line, spring morning, simple banners",
  "每年春天的长跑，表姐第一次参赛"),
 ("a young woman running alone on a road before sunrise, breath visible",
  "密集训练三个月"),
 ("a runner at the halfway mark of a race, tired but determined",
  "半程想放弃，还是跑完"),
 ("a coach talking with a young runner, holding a simple plan on paper",
  "教练说：满足来自完成，不是赢"),
],
"The Old Radio": [
 ("an old wooden radio on a kitchen counter, morning light through a window",
  "爷爷厨房里的木壳收音机"),
 ("an old man sitting by a radio in the evening, warm lamp, listening",
  "每晚听首都的新闻广播"),
 ("an old television and a radio side by side in a living room",
  "电视出现，人们以为广播会消失"),
 ("an old wooden radio on a desk at night, moonlight through a window",
  "月下还能听到古典音乐会"),
],
"Why We Forget": [
 ("an open wooden box with papers flying out, soft light, simple background",
  "记忆不是装满的盒子"),
 ("two stacks of paper cards, one slowly fading, one crowded and overlapping",
  "遗忘分两类：流失与拥挤"),
 ("a person placing a labeled card into a wooden file shelf, calm room",
  "有用的是结构，给事实一个位置"),
 ("a well organized bookshelf with labeled boxes, warm light, tidy room",
  "结构让信息更稳定地留存"),
],
"The Cost of Convenience": [
 ("a cardboard parcel on a doorstep, morning light, quiet street",
  "每个省时的设备都在索取回报"),
 ("a person clicking a page on a laptop, shopping bags beside the desk, evening light",
  "网购的好处一眼可见"),
 ("a closed small shop with a shutter down on a town street, empty sidewalk",
  "小店关门，镇中心就业消失"),
 ("a balance scale with a parcel on one side and coins on the other, simple background",
  "一边增财富，一边加深贫困"),
],
"What Justice Means": [
 ("stone courthouse steps with tall columns, morning light, no people",
  "正义易要求，难定义"),
 ("an open law book on a wooden desk beside a small lamp, quiet room",
  "法律能写下来，判断活在人心"),
 ("a wooden gavel resting on a desk, simple background, warm light",
  "逮捕不等于有罪"),
 ("two empty chairs facing a table in a plain room, soft daylight",
  "法官只承诺一个程序"),
],
}

# 统一风格前缀：60 张要像同一本书里的插画
STYLE = ("children's storybook illustration, soft watercolor, warm natural light, "
         "muted colors, simple background, no text, no letters, no watermark")
# 负向词：小模型最容易翻车的几项
NEGATIVE = ("text, letters, words, watermark, signature, nsfw, extra fingers, "
            "deformed hands, distorted face, multiple heads, lowres, jpeg artifacts")
