# -*- coding: utf-8 -*-
"""按预设映射批量精简释义：只保留考试范围内的常用义项。

脚本内置一份 133 条的「词 -> 精简释义」映射，用来把词典级别的长释义压成考试义。
用法：把 背词助手数据.json 放在脚本同目录，关闭背词助手页面后运行
      python tools/trim_meanings.py
"""
import json, os, sys, time

S = {
"receive":"v. 收到, 接到, 接待","receiver":"n. 接收器, 听筒, 接受者",
"accept":"v. 接受, 承认, 同意","incident":"n. 事件, 事变；adj. 附带的",
"exhibit":"v. 展出, 显示；n. 展览品","display":"v. 展示, 显示；n. 展示, 显示器",
"owe":"v. 欠(债), 归功于","dash":"v. 猛冲, 猛撞；n. 破折号, 猛冲",
"rush":"v. 冲, 匆忙行事；n. 冲, 匆忙","thrust":"v. 猛推, 插入；n. 推力, 要点",
"trust":"v. 信任, 信赖；n. 信任","dive":"v. 跳水, 潜水, 俯冲；n. 跳水",
"drown":"v. 淹死, 淹没","clash":"v. 冲突, 抵触；n. 冲突",
"crash":"v. 撞碎, 坠毁, 破产；n. 碰撞, 坠毁","smash":"v. 打碎, 猛撞；n. 破碎(声)",
"shame":"n. 羞耻, 遗憾；v. 使羞愧","cash":"n. 现金；v. 兑现",
"flash":"v. 闪光, 闪现；n. 闪光, 一瞬间","ease":"v. 减轻, 缓和；n. 容易, 舒适",
"relax":"v. 放松, 休息","upset":"v. 使心烦, 打乱；adj. 心烦的",
"sense":"n. 感觉, 意义, 理智；v. 感觉到","sensitive":"adj. 敏感的, 灵敏的",
"sensible":"adj. 明智的, 合情理的","tense":"adj. 紧张的, 拉紧的；n. 时态",
"intense":"adj. 强烈的, 紧张的","intensive":"adj. 加强的, 密集的",
"stand":"v. 站, 忍受；n. 立场, 看台","steady":"adj. 稳定的, 平稳的；v. 使稳定",
"stable":"adj. 稳定的, 牢固的；n. 马厩","establish":"v. 建立, 设立, 确立",
"establishment":"n. 建立, 机构, 企业","construction":"n. 建设, 建筑物, 结构",
"mount":"v. 登上, 增加；n. 山(峰)","amount":"n. 数量, 总额；v. 总计, 等于",
"beg":"v. 乞讨, 恳求","bold":"adj. 大胆的, 粗体的","ball":"n. 球, 舞会",
"act":"v. 行动, 表演；n. 行为, 法案, 幕","action":"n. 行动, 作用, 情节",
"active":"adj. 积极的, 活跃的, 主动的","activity":"n. 活动, 活跃","actor":"n. 演员",
"exact":"adj. 准确的, 精确的；v. 强求","precise":"adj. 精确的, 准确的",
"precisely":"adv. 精确地, 恰好","react":"v. 反应, 反抗","behave":"v. 表现, 举止",
"able":"adj. 能够的, 有能力的","capacity":"n. 容量, 能力",
"capital":"n. 首都, 资本, 大写字母；adj. 主要的","escape":"v. 逃跑, 逃避；n. 逃跑",
"avoid":"v. 避免, 避开","labor":"n. 劳动, 劳工；v. 劳动, 努力",
"sweat":"n. 汗；v. 出汗","sweet":"adj. 甜的, 甜美的；n. 糖果",
"salt":"n. 盐；adj. 咸的；v. 腌","sugar":"n. 糖；v. 加糖",
"calm":"adj. 平静的, 镇静的；v. 使平静","mature":"adj. 成熟的；v. 成熟",
"champion":"n. 冠军, 拥护者；v. 支持","camp":"n. 营地, 露营；v. 露营",
"campaign":"n. 运动, 战役；v. 参加运动","tent":"n. 帐篷",
"content":"n. 内容, 目录；adj. 满足的；v. 使满足","satisfaction":"n. 满意, 满足",
"classic":"adj. 经典的；n. 经典作品","classical":"adj. 古典的, 传统的",
"officer":"n. 军官, 官员","official":"adj. 官方的, 正式的；n. 官员",
"combine":"v. 结合, 联合","connect":"v. 连接, 联系","connection":"n. 连接, 关系",
"link":"v. 连接, 联系；n. 联系, 环节","join":"v. 参加, 连接；n. 接合处",
"joint":"adj. 共同的, 联合的；n. 关节, 接头","loose":"adj. 松的, 宽松的；v. 释放",
"code":"n. 代码, 准则, 法典","communicate":"v. 交流, 传达",
"communication":"n. 交流, 通信","community":"n. 社区, 团体",
"barber":"n. 理发师","beard":"n. 胡须","rear":"adj. 后部的；n. 后部；v. 抚养, 饲养",
"bathe":"v. 洗澡, 沐浴","basin":"n. 盆, 水池, 流域","shower":"n. 淋浴, 阵雨；v. 淋浴",
"basis":"n. 基础, 根据","basic":"adj. 基本的, 基础的",
"backward":"adj. 向后的, 落后的；adv. 向后","inward":"adj. 向内的, 内心的；adv. 向内",
"outward":"adj. 向外的, 外表的；adv. 向外","outdoors":"adv. 在户外；n. 户外",
"nearby":"adj. 附近的；adv. 在附近","underneath":"prep. 在…下面；adv. 在下面",
"lower":"adj. 较低的；v. 降低, 放下","undertake":"v. 承担, 从事",
"cast":"v. 投, 抛, 投射；n. 演员阵容","forecast":"v. 预报, 预测；n. 预报",
"ahead":"adv. 向前, 提前；adj. 领先的","shoulder":"n. 肩；v. 肩负, 承担",
"abroad":"adv. 在国外, 到海外","broad":"adj. 宽的, 广泛的",
"road":"n. 路, 道路, 途径","broadcast":"v. 广播, 播放；n. 广播",
"wide":"adj. 宽的, 广泛的；adv. 广泛地","aboard":"adv. 在船(车、飞机)上；prep. 上(船等)",
"adjust":"v. 调整, 适应","justify":"v. 证明…正当, 辩护",
"just":"adv. 刚刚, 正好, 仅仅；adj. 公正的","judge":"n. 法官, 裁判；v. 判断, 审判",
"daylight":"n. 日光, 白昼","merit":"n. 优点, 功绩；v. 值得",
"weak":"adj. 虚弱的, 薄弱的","grave":"n. 坟墓；adj. 严重的, 严肃的",
"severe":"adj. 严重的, 严厉的","grant":"v. 授予, 同意；n. 拨款, 授予",
"junior":"adj. 年少的, 初级的；n. 晚辈","senior":"adj. 年长的, 高级的；n. 长辈",
"angle":"n. 角, 角度","square":"n. 正方形, 广场, 平方；adj. 正方形的, 公正的",
"reply":"v. 回答, 答复；n. 回答","responsible":"adj. 负责的, 有责任的",
"approach":"v. 接近, 着手处理；n. 方法, 接近","grace":"n. 优雅, 恩惠",
"race":"n. 赛跑, 种族；v. 赛跑, 竞赛","compare":"v. 比较, 对比",
"rest":"n. 休息, 其余部分；v. 休息, 依靠",
"accident":"n. 事故, 意外","solar":"adj. 太阳的, 日光的",
"final":"n. 决赛, 期末考试；adj. 最后的",
"complete":"adj. 完全的, 完整的；v. 完成",
}

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    f = os.path.join(base, "背词助手数据.json")
    d = json.load(open(f, encoding="utf-8"))
    n = old_len = new_len = 0
    for w in d["words"]:
        k = w["word"].strip().lower()
        if k in S:
            old_len += len(w.get("meaning", ""))
            new_len += len(S[k])
            w["meaning"] = S[k]
            n += 1
    tmp = f + ".tmp"
    # 关键：刷新时间戳，否则程序下次启动会认为「浏览器缓存更新」而用旧数据覆盖本次修改
    d["updatedAt"] = int(time.time() * 1000)
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, f)
    except PermissionError:
        os.remove(tmp)
        print("失败：数据文件被占用，请先关闭背词助手的浏览器页面后重试")
        sys.exit(1)
    print("精简词数:", n, "| 字数:", old_len, "→", new_len,
          "| 压缩", round(100 - new_len / old_len * 100, 1), "%")

if __name__ == "__main__":
    main()
