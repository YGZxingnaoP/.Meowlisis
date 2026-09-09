# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/knowledge.py
# ANIMA3 提示词法典检索：
#   1) ensure_md：把法典拷贝到 .ComfyNode/prompt_reference（源缺失时用已拷副本）
#   2) _read：按标题层级(#~####)把 md 切成章节表，0~4 章另存为常驻规则区
#   3) retrieve：jieba 分词需求 → 词条命中章节标题(+8)/正文(+2) 打分 → 返回(规则区, 命中最相关章节)
import os
import re
import shutil

MD_SOURCE = r"D:\ComfyUI\ANIMA3 提示词生成模板 v3.0.md"
STOP_WORDS = {"的", "了", "画", "一个", "一张", "想要", "想", "给我", "帮我", "来张",
              "我", "你", "她", "他", "它", "我们", "你们", "她们", "他们", "和",
              "就", "在", "把", "像", "一样", "那种", "这个", "那个", "么", "呢",
              "吧", "啊", "呀", "哦", "嗯", "看", "到", "着", "穿", "站", "坐",
              "躺", "是", "有", "要", "会", "能", "让", "给", "也", "都", "很",
              "真", "挺", "主人", "喵", "拟", "着", "过", "让", "请", "帮",
              "两个", "三个", "俩人", "两人", "给我画", "帮我画"}
EXTRA_WORDS = ["黑丝", "白丝", "丝袜", "女仆", "猫娘", "猫耳", "狐耳", "兽耳", "兽娘",
               "双马尾", "单马尾", "哥特", "洛丽塔", "泳装", "比基尼", "校服", "体操服",
               "兔女郎", "护士", "警察", "旗袍", "和服", "巫女", "骑士", "魔法师",
               "小恶魔", "天使", "吸血鬼", "人鱼", "龙娘", "机械娘", "眼镜娘",
               "风景", "夜景", "海边", "夕阳", "黄昏", "教室", "办公室", "卧室",
               "浴室", "图书馆", "天台", "街道", "雨", "雪", "樱花", "星空",
               "百合", "男娘", "扶她", "肌肉", "贫乳", "巨乳", "内裤", "胸罩",
               "高跟鞋", "长筒袜", "绝对领域", "手铐", "项圈", "猫尾", "尾巴",
               "单人", "双人", "三人", "多人", "自拍", "展示", "狗耳"]
TOPIC_HINT = {"诱惑", "暴露", "自慰", "展示", "自拍", "口交", "足交", "素股", "手交",
              "乳交", "调戏", "传教士", "站立", "坐位", "后入", "种付", "骑乘", "睡奸",
              "催眠", "反转", "过激", "百合", "NTR", "束缚", "物化", "男娘", "异种",
              "调教", "胁迫", "偷窥", "事后", "另类", "大车", "隐奸", "表情", "反应",
              "液体", "景别", "视角", "POV", "镜头", "分镜", "构图", "场所", "私密",
              "半公开", "公共", "天气", "质感", "运动", "光学", "故障", "氛围",
              "头发", "眼睛", "体型", "肤色", "精灵", "恶魔", "天使", "翅膀", "机械",
              "服装", "制服", "材质", "透明", "镂空", "破损", "胶衣", "裸", "道具"}


class TBAnimaKnowledge:
    """ANIMA3 法典章节索引 + 按需求检索"""

    def __init__(self, config):
        self.config = config
        self._sections = None
        self._head = None
        try:
            import jieba
            for w in list(EXTRA_WORDS) + list(TOPIC_HINT):
                jieba.add_word(w)
        except Exception:
            pass

    def ensure_md(self):
        """拷贝法典到 .ComfyNode/prompt_reference，返回 (ok, path)"""
        ref_dir = self.config.prompt_reference_dir
        os.makedirs(ref_dir, exist_ok=True)
        target = os.path.join(ref_dir, "ANIMA3_prompt_law.md")
        if os.path.isfile(target):
            return True, target
        if os.path.isfile(MD_SOURCE):
            shutil.copy(MD_SOURCE, target)
            return True, target
        return False, target

    def _read(self):
        """加载并按标题层级切章（缓存）；0~4 章为常驻规则区"""
        if self._sections is not None:
            return self._sections
        ok, path = self.ensure_md()
        text = ""
        if ok:
            try:
                text = open(path, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                text = ""
        lines = text.splitlines()
        sections = []
        cur = {"title": "(前言)", "text": []}
        for ln in lines:
            m = re.match(r"^(\#{1,4})\s+(.*)$", ln.strip())
            if m:
                if cur["text"]:
                    sections.append(cur)
                cur = {"title": m.group(2).strip(), "text": []}
            else:
                cur["text"].append(ln)
        if cur["text"]:
            sections.append(cur)
        rules = []
        for s in sections:
            t = s["title"]
            if t.startswith(("0.", "1.", "2.", "3.", "4.", "15.")) or t in ("0.", "15."):
                rules.append(f"### {t}\n" + "\n".join(s["text"]))
        self._head = "\n".join(rules)
        self._sections = sections
        return sections

    def _words(self, text):
        """jieba 分词并过滤停用词/单字噪音，返回关键词列表"""
        try:
            import jieba
            words = [w.strip().lower() for w in jieba.cut(text or "")]
        except Exception:
            words = re.findall(r"[\u4e00-\u9fffA-Za-z0-9@_]+", text or "")
        out = []
        for w in words:
            w = w.strip()
            if not w or len(w) < 2 or w in STOP_WORDS:
                continue
            if w not in out:
                out.append(w)
        return out[:24]

    def retrieve(self, query, top=6, per_limit=1600):
        """返回 (规则区文本, 命中最相关章节拼接文本)；无命中则章节区为空串"""
        self._read()
        words = self._words(query)
        if not words:
            return (self._head or "")[:4500], ""
        scored = []
        for idx, s in enumerate(self._sections):
            title = s["title"]
            body = "\n".join(s["text"])[:2500]
            score = 0
            for w in words:
                if w in title:
                    score += 8
                elif w in body:
                    score += 2
            if score > 0:
                scored.append((score, idx, s))
        scored.sort(key=lambda x: (-x[0], x[1]))
        parts = []
        for _, _, s in scored[:top]:
            parts.append(f"### [{s['title']}]\n" + "\n".join(s["text"])[:per_limit])
        return (self._head or "")[:4500], "\n\n".join(parts)
