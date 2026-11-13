# -*- coding: utf-8 -*-
"""蔚蓝档案角色表：中文名 → danbooru 名，另有仅英文名的新角色池。

数据来源：danbooru 全量 `*_(blue_archive)` tag（按图片数排序，2026-11 快照），
只保留**正式角色**（剔除换装 tag：swimsuit/dress/bunny/track 等，以及社团、机器人、道具）。
随机出图时从「中文表 + 英文池」一起抽，保证新老角色都能抽到。
"""

SERIES = "blue archive"
SERIES_CN = "蔚蓝档案"

# 中文名 → danbooru 角色名（不含作品括注）
CHARACTERS = {
    "白子": "shiroko", "星野": "hoshino", "日奈": "hina", "优香": "yuuka",
    "野宫": "nonomi", "阿露": "aru", "未花": "mika", "妃咲": "kisaki",
    "爱丽丝": "aris", "濑名": "sena", "阿罗娜": "arona", "普拉娜": "plana",
    "阿丝娜": "asuna", "花子": "hanako", "阿子": "ako", "白子·恐怖": "shiroko terror",
    "莲见": "hasumi", "诺亚": "noa", "卡琳": "karin", "圣娅": "seia",
    "和纱": "kazusa", "小春": "koharu", "夏": "natsu", "伊吹": "ibuki",
    "美游": "miyu", "日富美": "hifumi", "都子": "miyako", "羽留": "ui",
    "千夏": "chinatsu", "千寻": "chihiro", "阿卡内": "akane", "阿莉丝": "aris",
    "明日奈": "asuna", "梨绪": "rio", "时": "toki", "凯": "kei",
    "佳代子": "kayoko", "真理": "mari", "柚子": "yuzu", "伊织": "iori",
    "阿兹莎": "azusa", "芹香": "serika", "阿露": "aru", "野乃美": "nonomi",
    "智惠": "tomoe", "美智瑠": "michiru", "泉": "izumi", "风香": "fuuka",
    "椿": "tsubaki", "樱子": "sakurako", "绫音": "ayane", "真纪": "maki",
    "日向": "hinata", "日奈": "hina", "春香": "haruka", "瞬": "shun",
    "心奈": "kokona", "若藻": "wakamo", "桔梗": "kikyou", "筑紫": "tsukuyo",
    "敦子": "atsuko", "良美": "yoshimi", "绘里": "eri", "皐月": "satsuki",
    "英美": "eimi", "二子": "niko", "鹤城": "tsurugi", "小雪": "koyuki",
    "爱莉": "airi", "美咲": "misaki", "澪": "miyo", "吹雪": "fubuki",
    "花江": "hanae", "华": "kanoe", "萌": "moe", "猫": "moe",
    "阿罗娜": "arona", "莉音": "rin", "千秋": "chiaki", "香穗": "kaho",
    "琴音": "kotone", "小夜": "sayuri", "纱雪": "saya", "米娜": "mina",
    "阿莉花": "iroha", "梅露": "meru", "菫": "sumire", "周防": "suou",
    "辉夜": "kaguya", "昴": "subaru", "海香": "umika", "纯子": "sumika",
    "树里": "juri", "和泉": "izumi", "乃香": "nodoka", "桃香": "momoka",
    "晴": "hare", "绫": "akira", "胡桃": "kurumi", "诗郎": "shuro",
    "桐乃": "kirino", "真琴": "makoto", "枫": "kaede", "千鹤": "chise",
    "紫": "yukari", "此花": "konoka", "小百合": "kotori", "铃美": "suzumi",
    "凛": "rin", "樱": "sakurako", "蕾莎": "reisa", "响": "hibiki",
    "咲": "saki", "榛名": "haruna", "阿露": "aru", "千夏": "chinatsu",
    "康娜": "kanna", "绿": "midori", "桃井": "momoi", "妮露": "neru",
    "花凛": "karin", "时雨": "shigure", "乙女": "otogi", "香澄": "kasumi",
    "晴奈": "haruna", "千明": "chiaki", "美知留": "michiru", "红叶": "kaho",
    "伊豆奈": "izuna", "忍": "izuna", "阿知花": "atsuko", "优子": "yuzu",
    "绫子": "ayane", "莉央": "rio", "智": "toki", "阿莉丝": "aris",
    "梅": "megu", "切莉诺": "cherino", "莲华": "renge", "阿莉": "airi",
    "米娜": "mina", "翠": "midori", "美和": "miwa", "阿莉莎": "arisa",
}

# 只有英文名的角色（新角色/冷门/异格），随机池同样包含
EN_ONLY = (
    "asuna", "hibiki", "saki", "haruka", "himari", "shun", "kokona", "reisa",
    "natsu", "chinatsu", "chise", "rin", "sora", "shimiko", "ein", "hanae",
    "mashiro", "tsukuyo", "utaha", "aoi", "yukino", "renge", "megu",
    "cherino", "kaho", "kotone", "sayuri", "miyo", "kanoe", "eri", "miyo",
    "kikyou", "konoka", "kaede", "makoto", "kirino", "shuro", "kurumi",
    "chihiro", "akira", "hare", "nodoka", "momoka", "juri", "sumika", "umika",
    "subaru", "kaguya", "suou", "sumire", "meru", "iroha", "mina", "saya",
    "arina", "rena", "mimori", "izumi", "sof", "akari", "erika", "shizuko",
    "marina", "malkuth", "takane", "kotama", "kaya", "niya", "mina", "karen",
    "ritsu", "hiromi", "natsuki", "maia", "kuzunoha", "yakumo", "kokuriko",
    "ayumu", "akemi", "azami", "shouko", "tomoe", "misuzu", "pina", "minori",
    "fuyu", "rei", "kai", "tsubasa", "beatrice", "youko", "mirai", "anna",
    "erina", "nagomi", "ayame", "suiko", "minato", "shinon", "arata",
    "mayumi", "mai", "nanami", "sanae", "mitsuki", "haine", "kurokage",
    "momiji", "kokoro", "tsumugi", "nagusa", "yume", "hibiki", "junko",
    "mine", "rumi", "nozomi", "hikari", "moe", "tsubaki", "miyako",
    "wadako", "seia", "iroha", "kisaki", "reisa",
)

# 别名（玩家常用简称/错写）
ALIASES = {
    "水星野": "星野", "泳装星野": "星野", "泳装白子": "白子",
    "小梓": "阿兹莎", "梓": "阿兹莎", "圣亚": "圣娅",
    "咪卡": "未花", "米卡": "未花", "妃关": "妃咲",
    "阿萝娜": "阿罗娜", "阿罗那": "阿罗娜", "爱莉丝": "爱丽丝",
    "机器人": "爱丽丝", "蔚蓝白子": "白子", "小夏": "夏",
}


def canonical(name):
    """别名归一到正式中文名（认不出原样返回）。"""
    n = str(name or "").strip()
    return ALIASES.get(n, n)


def roster():
    """随机池：中文名 + 仅英文名（去重）。"""
    names = list(CHARACTERS.keys())
    seen = {v.lower() for v in CHARACTERS.values()}
    for en in EN_ONLY:
        if en.lower() not in seen:
            names.append(en)
            seen.add(en.lower())
    return names


def char_tag(name):
    """名字（中文或英文）→ danbooru tag；认不出返回空串。"""
    n = canonical(name)
    en = CHARACTERS.get(n)
    if not en:
        low = n.lower()
        for v in CHARACTERS.values():
            if v.lower() == low:
                en = v
                break
        if not en and low in {x.lower() for x in EN_ONLY}:
            en = low
    if not en:
        return ""
    return "%s (%s)" % (en, SERIES)


def en_name(name):
    """名字 → 英文名；认不出返回空串。"""
    n = canonical(name)
    if n in CHARACTERS:
        return CHARACTERS[n]
    low = n.lower()
    for v in CHARACTERS.values():
        if v.lower() == low:
            return v
    return low if low in {x.lower() for x in EN_ONLY} else ""
