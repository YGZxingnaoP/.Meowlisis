# -*- coding: utf-8 -*-
"""角色库：中文名 → danbooru 角色 tag（按作品分组）。

只收录 danbooru 图量充足的作品：蔚蓝档案 / 鸣潮 / 明日方舟 / 原神。
异环（neverness to everness）角色图量为 0，画不出来，故不收录。
"""

SERIES_CN = {"blue archive": "蔚蓝档案", "wuthering waves": "鸣潮",
             "arknights": "明日方舟", "genshin impact": "原神"}

BA = [
    ("白子", "shiroko"), ("星野", "hoshino"), ("日奈", "hina"), ("优香", "yuuka"),
    ("野宫", "nonomi"), ("阿露", "aru"), ("未花", "mika"), ("妃咲", "kisaki"),
    ("爱丽丝", "aris"), ("阿罗娜", "arona"), ("普拉娜", "plana"), ("阿丝娜", "asuna"),
    ("花子", "hanako"), ("阿子", "ako"), ("莲见", "hasumi"), ("诺亚", "noa"),
    ("卡琳", "karin"), ("圣娅", "seia"), ("和纱", "kazusa"), ("小春", "koharu"),
    ("夏", "natsu"), ("伊吹", "ibuki"), ("美游", "miyu"), ("日富美", "hifumi"),
    ("都子", "miyako"), ("羽留", "ui"), ("千夏", "chinatsu"), ("千寻", "chihiro"),
    ("阿卡内", "akane"), ("梨绪", "rio"), ("时", "toki"), ("佳代子", "kayoko"),
    ("真理", "mari"), ("柚子", "yuzu"), ("伊织", "iori"), ("阿兹莎", "azusa"),
    ("芹香", "serika"), ("智惠", "tomoe"), ("美智瑠", "michiru"), ("泉", "izumi"),
    ("风香", "fuuka"), ("椿", "tsubaki"), ("樱子", "sakurako"), ("绫音", "ayane"),
    ("真纪", "maki"), ("日向", "hinata"), ("春香", "haruka"), ("瞬", "shun"),
    ("心奈", "kokona"), ("若藻", "wakamo"), ("桔梗", "kikyou"), ("筑紫", "tsukuyo"),
    ("敦子", "atsuko"), ("良美", "yoshimi"), ("绘里", "eri"), ("皐月", "satsuki"),
    ("英美", "eimi"), ("二子", "niko"), ("鹤城", "tsurugi"), ("小雪", "koyuki"),
    ("爱莉", "airi"), ("美咲", "misaki"), ("澪", "miyo"), ("吹雪", "fubuki"),
    ("花江", "hanae"), ("华", "kanoe"), ("萌", "moe"), ("莉音", "rin"),
    ("千秋", "chiaki"), ("香穗", "kaho"), ("琴音", "kotone"), ("小夜", "sayuri"),
    ("纱雪", "saya"), ("米娜", "mina"), ("阿莉花", "iroha"), ("梅露", "meru"),
    ("菫", "sumire"), ("周防", "suou"), ("辉夜", "kaguya"), ("昴", "subaru"),
    ("海香", "umika"), ("纯子", "sumika"), ("树里", "juri"), ("乃香", "nodoka"),
    ("桃香", "momoka"), ("晴", "hare"), ("绫", "akira"), ("胡桃", "kurumi"),
    ("诗郎", "shuro"), ("桐乃", "kirino"), ("真琴", "makoto"), ("枫", "kaede"),
    ("千鹤", "chise"), ("紫", "yukari"), ("此花", "konoka"), ("小百合", "kotori"),
    ("铃美", "suzumi"), ("凛", "rin"), ("蕾莎", "reisa"), ("响", "hibiki"),
    ("咲", "saki"), ("榛名", "haruna"), ("康娜", "kanna"), ("绿", "midori"),
    ("桃井", "momoi"), ("妮露", "neru"), ("花凛", "karin"), ("时雨", "shigure"),
    ("乙女", "otogi"), ("香澄", "kasumi"), ("晴奈", "haruna"), ("伊豆奈", "izuna"),
    ("梅", "megu"), ("切莉诺", "cherino"), ("莲华", "renge"),
]

WUWA = [
    ("忌炎", "jiyan"), ("吟霖", "yinlin"), ("长离", "changli"), ("今汐", "jinhsi"),
    ("守岸人", "shorekeeper"), ("椿", "camellya"), ("珂莱塔", "carlotta"),
    ("卡提希娅", "cartethyia"), ("弗洛洛", "phrolova"), ("坎特蕾拉", "cantarella"),
    ("折枝", "zhezhi"), ("散华", "sanhua"), ("白芷", "baizhi"), ("维里奈", "verina"),
    ("鉴心", "jianxin"), ("凌阳", "lingyang"), ("莫特斐", "mortefi"),
    ("卡卡罗", "calcharo"), ("漂泊者", "rover"), ("女漂泊者", "female rover"),
    ("安可", "encore"), ("丹瑾", "danjin"), ("桃祈", "taoqi"), ("秧秧", "yangyang"),
    ("炽霞", "chixia"), ("赞妮", "zani"), ("夏空", "ciaccona"), ("洛可可", "roccia"),
    ("菲比", "phoebe"), ("布兰特", "brant"), ("露帕", "lupa"), ("尤诺", "iuno"),
    ("琳奈", "lynae"), ("遣砂", "chisa"), ("艾默斯", "aemeath"), ("德妮娅", "denia"),
    ("绯雪", "hiyuki"), ("希格莉卡", "sigrika"), ("奥古斯塔", "augusta"),
    ("露米", "lumi"), ("扶光", "buling"), ("仇远", "qiuyuan"),
    ("香里要", "xiangli yao"), ("卡提希娅", "cartethyia"),
]

AK = [
    ("阿米娅", "amiya"), ("凯尔希", "kal'tsit"), ("陈", "ch'en"), ("斯卡蒂", "skadi"),
    ("能天使", "exusiai"), ("德克萨斯", "texas"), ("银灰", "silverash"),
    ("安洁莉娜", "angelina"), ("天火", "ifrit"), ("白面鸮", "ptilopsis"),
    ("星熊", "hoshiguma"), ("拉普兰德", "lappland"), ("蓝毒", "blue poison"),
    ("幽灵鲨", "specter"), ("森蚺", "eunectes"), ("泥岩", "mudrock"),
    ("推进之王", "siege"), ("麦哲伦", "magallan"), ("华法琳", "warfarin"),
    ("歌蕾蒂娅", "gladiia"), ("令", "ling"), ("年", "nian"), ("夕", "dusk"),
    ("史尔特尔", "surtr"), ("棘刺", "thorns"), ("山", "mountain"),
    ("铃兰", "suzuran"), ("温蒂", "weedy"), ("阿", "aak"), ("槐琥", "waai fu"),
    ("莫斯提马", "mostima"), ("菲亚梅塔", "fiammetta"), ("浊心斯卡蒂", "skadi the corrupting heart"),
    ("归溟幽灵鲨", "specter the unchained"), ("焰尾", "texas the omertosa"),
    ("迷迭香", "rosetta"), ("早露", "ceobe"), ("刻俄柏", "ceobe"),
    ("风笛", "bagpipe"), ("黑", "schwarz"), ("夜魔", "nightmare"),
    ("雪雉", "snowsant"), ("伊桑", "ethan"), ("埃拉托", "erato"),
]

GI = [
    ("胡桃", "hu tao"), ("甘雨", "ganyu"), ("雷电将军", "raiden shogun"),
    ("纳西妲", "nahida"), ("芙宁娜", "furina"), ("神里绫华", "kamisato ayaka"),
    ("宵宫", "yoimiya"), ("八重神子", "yae miko"), ("刻晴", "keqing"),
    ("莫娜", "mona"), ("琴", "jean"), ("凝光", "ningguang"), ("北斗", "beidou"),
    ("荧", "lumine"), ("派蒙", "paimon"), ("申鹤", "shenhe"), ("夜兰", "yelan"),
    ("妮露", "nilou"), ("娜维娅", "navia"), ("克洛琳德", "clorinde"),
    ("阿蕾奇诺", "arlecchino"), ("希诺宁", "xilonen"), ("玛拉妮", "mualani"),
    ("珊瑚宫心海", "sangonomiya kokomi"), ("优菈", "eula"), ("菲谢尔", "fischl"),
    ("芭芭拉", "barbara"), ("丽莎", "lisa"), ("安柏", "amber"), ("香菱", "xiangling"),
    ("行秋", "xingqiu"), ("诺艾尔", "noelle"), ("班尼特", "bennett"),
    ("雷泽", "razor"), ("温迪", "venti"), ("钟离", "zhongli"),
    ("达达利亚", "tartaglia"), ("可莉", "klee"), ("阿贝多", "albedo"),
    ("枫原万叶", "kaedehara kazuha"), ("流浪者", "wanderer"), ("提纳里", "tighnari"),
    ("赛诺", "cyno"), ("迪希雅", "dehya"), ("坎蒂丝", "candace"), ("莱依拉", "layla"),
    ("珐露珊", "faruzan"), ("科莱", "collei"), ("多莉", "dori"), ("绮良良", "kirara"),
    ("五郎", "gorou"), ("托马", "thoma"), ("早柚", "sayu"), ("九条裟罗", "kujou sara"),
    ("罗莎莉亚", "rosaria"), ("迪奥娜", "diona"), ("烟绯", "yanfei"),
    ("云堇", "yunjin"), ("千织", "chiori"), ("希格雯", "sigewinne"),
]


def _build():
    """构建中文名 → 英文名与作品索引。"""
    chars, series_of = {}, {}
    for series, group in (("blue archive", BA), ("wuthering waves", WUWA),
                          ("arknights", AK), ("genshin impact", GI)):
        for cn, en in group:
            chars[cn] = en
            series_of[cn] = series
    return chars, series_of


CHARACTERS, SERIES_OF = _build()

ALIASES = {
    "泳装星野": "星野", "水星野": "星野", "小梓": "阿兹莎", "梓": "阿兹莎",
    "圣亚": "圣娅", "咪卡": "未花", "米卡": "未花", "妃关": "妃咲",
    "阿萝娜": "阿罗娜", "爱莉丝": "爱丽丝", "吱吱": "小吱",
    "长离离": "长离", "今夕": "今汐", "小姨": "长离",
    "胡桃桃": "胡桃", "将军": "雷电将军", "雷神": "雷电将军", "芙芙": "芙宁娜",
    "绫华": "神里绫华", "神子": "八重神子", "小草神": "纳西妲", "草神": "纳西妲",
    "阿米驴": "阿米娅", "驴": "阿米娅", "银老板": "银灰", "德狗": "德克萨斯",
    "能天": "能天使", "陈sir": "陈", "蒂蒂": "斯卡蒂",
}


def canonical(name):
    """别名归一。"""
    n = str(name or "").strip()
    return ALIASES.get(n, n)


def roster(series=""):
    """随机池：series 为空=全部作品；否则只取该作品的角色。"""
    key = str(series or "").strip()
    if not key:
        return list(CHARACTERS.keys())
    want = SERIES_ALIAS.get(key, key)
    return [n for n, s in SERIES_OF.items() if s == want]


SERIES_ALIAS = {
    "蔚蓝档案": "blue archive", "碧蓝档案": "blue archive", "ba": "blue archive",
    "鸣潮": "wuthering waves", "wuwa": "wuthering waves",
    "明日方舟": "arknights", "方舟": "arknights", "ak": "arknights",
    "原神": "genshin impact", "gi": "genshin impact",
}


def match_series(text):
    """从一段话里认出作品名，返回 danbooru 作品 tag 或空串。"""
    raw = str(text or "").lower()
    for cn, tag in SERIES_ALIAS.items():
        if cn.lower() in raw:
            return tag
    return ""


def series_of(name):
    """角色所属作品（danbooru 作品 tag）。"""
    return SERIES_OF.get(canonical(name), "")


def char_tag(name):
    """中文名 → danbooru 角色 tag（带作品括注）。"""
    n = canonical(name)
    en = CHARACTERS.get(n)
    if not en:
        low = n.lower()
        for k, v in CHARACTERS.items():
            if v.lower() == low:
                en, n = v, k
                break
    if not en:
        return ""
    series = SERIES_OF.get(n, "")
    return "%s (%s)" % (en, series) if series else en


def en_name(name):
    """中文名 → 英文名（不含作品括注）。"""
    n = canonical(name)
    if n in CHARACTERS:
        return CHARACTERS[n]
    low = n.lower()
    for v in CHARACTERS.values():
        if v.lower() == low:
            return v
    return low if low else ""
