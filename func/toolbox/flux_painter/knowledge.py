# -*- coding: utf-8 -*-
import os
import re
import shutil

MD_SOURCE_ENV = "FLUXPAINTER_KNOWLEDGE_MD"
MD_SOURCE_FALLBACK = r"D:\ComfyUI\ANIMA3 提示词生成模板 v3.0.md"

def knowledge_md_source(ref_dir=None, names=None):
    """提示词法典 md 源路径（自包含优先，不再硬依赖 D:\\ComfyUI）"""
    env = os.environ.get(MD_SOURCE_ENV, "").strip()
    if env and os.path.isfile(env):
        return env
    if ref_dir:
        for name in (names or ("ANIMA3 提示词生成模板 v3.0.md", "ANIMA3_prompt_law.md")):
            p = os.path.join(ref_dir, name)
            if os.path.isfile(p):
                return p
    return MD_SOURCE_FALLBACK
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

    MD_NAMES = ("ANIMA3 提示词生成模板 v3.0.md", "ANIMA3_prompt_law.md")
    MD_TARGET = "ANIMA3_prompt_law.md"
    ALWAYS_PREFIX = ("0.", "1.", "2.", "3.", "4.", "11.", "15.")
    ALWAYS_WORDS = ("互斥", "冲突", "镜头", "视角", "景别", "POV", "构图", "分镜", "视线",
                    "TAG COUNT", "SLOT ORDER", "OUTPUT PROTOCOL", "SELF-CHECK")

    def __init__(self, config):
        """初始化。"""
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
        target = os.path.join(ref_dir, self.MD_TARGET)
        if os.path.isfile(target):
            return True, target
        src = knowledge_md_source(ref_dir, self.MD_NAMES)
        if os.path.isfile(src):
            shutil.copy(src, target)
            return True, target
        return False, target

    def full_text(self):
        """法典全文（短法典直接整篇注入，不走检索）"""
        ok, path = self.ensure_md()
        if not ok:
            return ""
        try:
            return open(path, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            return ""

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

    def retrieve(self, query, top=10, per_limit=2600, budget=42000):
        """返回 (规则区文本, 章节文本)。"""
        self._read()
        words = self._words(query)
        scored = []
        if words:
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

        picked, seen, total = [], set(), 0

        def take(idx, s, limit):
            """按关键词取章节正文。"""
            nonlocal total
            txt = f"### [{s['title']}]\n" + "\n".join(s["text"])[:limit]
            if total + len(txt) > budget:
                return False
            picked.append(txt)
            seen.add(idx)
            total += len(txt)
            return True

        for _, idx, s in scored[:top]:
            take(idx, s, per_limit)
        for idx, s in enumerate(self._sections):          # 兜底常驻（检索打不中时法典依然生效）
            if idx in seen:
                continue
            t = s["title"]
            if t.startswith(self.ALWAYS_PREFIX) or any(w in t for w in self.ALWAYS_WORDS):
                take(idx, s, per_limit)
        return (self._head or ""), "\n\n".join(picked)

    def index(self, with_digest=True, line_limit=110):
        """法典目录：全部章节标题（+首行摘要），供 LLM 自己决定要读哪些章节"""
        self._read()
        out = []
        for s in self._sections:
            t = s["title"]
            if with_digest:
                body = " ".join(x.strip() for x in s["text"] if x.strip())
                body = re.sub(r"\s+", " ", body)[:line_limit]
                out.append(f"- {t} :: {body}" if body else f"- {t}")
            else:
                out.append(f"- {t}")
        return "\n".join(out)

    def read(self, section, per_limit=3600, max_sections=3):
        """按章节名/编号读全文（支持 '11.2'、'视角方向'、'POV' 等模糊匹配）"""
        self._read()
        key = str(section or "").strip().lower()
        if not key:
            return "（未指定章节名；可先调 law_index 看目录）"
        secs = self._sections
        exact = [s for s in secs if s["title"].lower() == key]
        starts = [s for s in secs if s["title"].lower().startswith(key)]
        contains = [s for s in secs if key in s["title"].lower()]
        pick = exact or starts or contains
        if not pick:
            return f"（法典中找不到章节「{section}」。请用 law_index 查看可用章节名）"
        out, total = [], 0
        for s in pick[:max_sections]:
            txt = f"### [{s['title']}]\n" + "\n".join(s["text"])[:per_limit]
            if total and total + len(txt) > per_limit * 2:
                break
            out.append(txt)
            total += len(txt)
        return "\n\n".join(out)

    def search(self, query, top=3, per_limit=800):
        """关键词检索（与 retrieve 同一套打分），返回最相关章节片段（省 token：默认 3 章×800 字）。"""
        self._read()
        words = self._words(query)
        if not words:
            return "（查询词为空；请给出画面/主题/场景等关键词）"
        scored = []
        for idx, s in enumerate(self._sections):
            title = s["title"]
            body = "\n".join(s["text"])[:3000]
            score = 0
            for w in words:
                if w in title:
                    score += 8
                elif w in body:
                    score += 2
            if score > 0:
                scored.append((score, idx, s))
        if not scored:
            return f"（未命中「{query}」；可换词，或用 law_index 按目录挑章节）"
        scored.sort(key=lambda x: (-x[0], x[1]))
        parts, total, cap = [], 0, per_limit * top
        for _, _, s in scored[:top]:
            txt = f"### [{s['title']}]\n" + "\n".join(s["text"])[:per_limit]
            if total and total + len(txt) > cap:
                break
            parts.append(txt)
            total += len(txt)
        return "\n\n".join(parts)

class TBMossKnowledge(TBAnimaKnowledge):
    """MOSS 的素材来源：**直接复用 ANIMA3 法典**（同一个 md、同一套检索）"""

    MD_NAMES = ("ANIMA3 提示词生成模板 v3.0.md", "ANIMA3_prompt_law.md")
    MD_TARGET = "ANIMA3_prompt_law.md"
    ALWAYS_PREFIX = ("0.", "1.", "2.", "3.", "4.", "11.", "15.")
    ALWAYS_WORDS = ("互斥", "冲突", "镜头", "视角", "景别", "POV", "构图", "分镜", "视线",
                    "TAG COUNT", "SLOT ORDER", "OUTPUT PROTOCOL", "SELF-CHECK")
