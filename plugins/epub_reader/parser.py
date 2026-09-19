import os
import re

from bs4 import BeautifulSoup


SKIP_TAGS = ("script", "style", "img", "svg", "image", "audio", "video",
             "head", "title", "meta", "link", "iframe", "object", "embed")

# 中文数字 → 阿拉伯数字（支持「第X本/卷/册/部/集」口语）
_CN_NUM = {"零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
           "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}


def list_books(books_dir):
    """列出书库中的 epub 文件名列表"""
    folder = _abs(books_dir)
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(".epub"))


# ==================== 书名匹配 ====================
def _norm(text):
    """归一化：只保留汉字/字母/数字并转小写（抹平标点、空格、装饰符号差异）"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(text or "").lower())


def _segments(text):
    """按非文字符号切片，返回归一化后的片段（用于「片段命中」判断）"""
    return [_norm(s) for s in re.split(r"[^\w\u4e00-\u9fff]+", str(text or ""), flags=re.UNICODE)
            if _norm(s)]


def _split_volume(name):
    """拆出 (书名主体, 卷号)

    支持三种常见命名：
        86-不存在的战区-_-_01               → 尾部数字
        败北女角太多了！09卷精翻              → 数字 + 卷/册/部/集
        [千岁同学].千岁同学 02（副标题）       → 数字后接括号副标题
    """
    s = str(name or "")
    m = re.search(r"(\d{1,3})\s*[卷册部集]?\s*$", s)
    if m:
        return s[:m.start()], str(int(m.group(1)))
    m = re.search(r"(\d{1,3})\s*(?=[（(])", s)
    if m:
        return s[:m.start()], str(int(m.group(1)))
    m = re.search(r"(\d{1,3})\s*[卷册部集]", s)
    if m:
        return s[:m.start()], str(int(m.group(1)))
    return s, ""


def query_volumes(query):
    """从口语里提取全部可能的卷号（"01" / "第1本" / "第一本" / "十二卷"）"""
    text = str(query or "")
    vols = set()
    for d in re.findall(r"\d{1,3}", text):
        vols.add(str(int(d)))
    for cn in re.findall(r"第([零一二三四五六七八九十两]{1,3})[本卷册部集]", text):
        if "十" in cn:
            head, _, tail = cn.partition("十")
            tens = int(_CN_NUM.get(head, "1") or "1")
            ones = int(_CN_NUM.get(tail, "0") or "0") if tail else 0
            vols.add(str(tens * 10 + ones))
        else:
            num = "".join(_CN_NUM.get(c, "") for c in cn)
            if num.isdigit():
                vols.add(str(int(num)))
    return vols


# ==================== 明确卷号（「第X本/卷/册/部/集」或整串序号） ====================
_VOL_AR = re.compile(r"第\s*(\d{1,2})\s*[本卷册部集]")
_VOL_CN = re.compile(r"第\s*([零一二三四五六七八九十两]{1,3})\s*[本卷册部集]")
_BARE_NUM = re.compile(r"^\s*第?\s*(\d{1,2})\s*[本卷册部集]?\s*$")
_VOL_PHRASE = re.compile(r"第?\s*(?:\d{1,2}|[零一二三四五六七八九十两]{1,3})\s*[本卷册部集]")


def _cn_to_int(text):
    """中文数字 → int（支持 十二 / 二十 / 二十三）"""
    s = str(text or "")
    if "十" in s:
        head, _, tail = s.partition("十")
        tens = int(_CN_NUM.get(head, "1") or "1")
        ones = int(_CN_NUM.get(tail, "0") or "0") if tail else 0
        return tens * 10 + ones
    num = "".join(_CN_NUM.get(c, "") for c in s)
    return int(num) if num.isdigit() else -1


def explicit_volume(query):
    """提取"明确卷号"，返回 str 或 ""

    明确 = 「第2本 / 第二卷 / 第十二册」这种带"第…本"结构的说法（可出现在句子任意位置），
    或整串就是一个裸序号（"2"）。裸数字夹在书名里（如"86不存在战区的01"）不算，
    避免把书名里的数字当卷号。
    """
    text = str(query or "")
    m = _VOL_AR.search(text)
    if m:
        return str(int(m.group(1)))
    m = _VOL_CN.search(text)
    if m:
        n = _cn_to_int(m.group(1))
        if n > 0:
            return str(n)
    m = _BARE_NUM.match(text)
    if m:
        return str(int(m.group(1)))
    return ""


def strip_volume_phrase(query):
    """去掉卷号短语，留下书名线索（用于"读86第二本"这类混合口语）"""
    return _VOL_PHRASE.sub(" ", str(query or ""))


def series_of(name):
    """书名的系列主体（去掉尾部卷号并归一化）"""
    return _norm(_split_volume(name)[0])


def series_summary(books_dir):
    """把书库归纳成系列清单：[{"name","count","vols"}]（按卷数降序）"""
    groups = {}
    for f in list_books(books_dir):
        stem = os.path.splitext(f)[0]
        key = series_of(stem) or _norm(stem)
        item = groups.setdefault(key, {"name": _split_volume(stem)[0].strip(" -_·."), "count": 0,
                                       "vols": [], "stems": []})
        item["count"] += 1
        item["vols"].append(_split_volume(stem)[1])
        item["stems"].append(stem)
    return sorted(groups.values(), key=lambda x: -x["count"])


def _recent_state_series(state_dir):
    """最近一次在读的系列（按进度文件修改时间取最新一条），返回系列主体或 ""。"""
    if not state_dir or not os.path.isdir(state_dir):
        return "", ""
    newest, best_name = 0.0, ""
    try:
        names = os.listdir(state_dir)
    except Exception:
        return "", ""
    for f in names:
        if not f.lower().endswith(".json"):
            continue
        p = os.path.join(state_dir, f)
        try:
            t = os.path.getmtime(p)
        except Exception:
            continue
        if t > newest:
            newest, best_name = t, os.path.splitext(f)[0]
    return (series_of(best_name), best_name) if best_name else ("", "")


def recent_state_book(state_dir):
    """最近一次在读的书名（按进度文件修改时间；无则 ""）"""
    return _recent_state_series(state_dir)[1]


def _lcs_len(a, b):
    """最长公共子序列长度（书名很短，DP 开销可忽略）"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for ch in a:
        cur = [0]
        for j, other in enumerate(b):
            cur.append(prev[j] + 1 if ch == other else max(cur[j], prev[j + 1]))
        prev = cur
    return prev[-1]


def _score_book(base, norm_query, volumes):
    """书名与口语查询的匹配得分（0 = 不匹配）

    口语（"我要听86不存在战区的01"）与文件名（"86-不存在的战区-_-_01"）之间存在
    标点与虚词差异，因此用「书名主体 LCS 覆盖率」和「分片命中」两级打分，
    再用卷号消歧（同系列多卷）。
    """
    stem, vol = _split_volume(base)
    norm_stem = _norm(stem)
    score = 0.0

    # ① 主体覆盖率：口语里按顺序出现主体全部字符即可（容忍插入"的"等虚词）
    if len(norm_stem) >= 2:
        cover = _lcs_len(norm_stem, norm_query) / float(len(norm_stem))
        if cover >= 0.75:
            score = cover

    # ② 分片命中：文件名任一「非纯数字且≥2字」的片段出现在口语中
    if score <= 0:
        for seg in _segments(base):
            if len(seg) >= 2 and not seg.isdigit() and seg in norm_query:
                score = 0.9
                break

    # ③ 卷号 + 任一片段命中：覆盖「第3本86」这类"卷号+简称"口语
    if score <= 0 and vol and vol in volumes:
        for seg in _segments(base):
            if len(seg) >= 2 and seg in norm_query:
                score = 0.8
                break

    # ④ 卷号消歧：口语指明了卷号且与本书一致 → 大幅加分
    if score > 0 and vol and vol in volumes:
        score += 0.5
    return score


def match_book(books_dir, query, state_dir=None, prefer=""):
    """按书名/关键词模糊匹配书，返回 (完整路径, 标题)

    - 书名匹配：精确/归一化包含/打分（支持"读86第二本"这类混合口语）
    - 只说卷号："第二本" / "从第二本开始读" / "第2卷"，按
      「书名线索 → prefer 提示（当前在读系列）→ 唯一候选 → 有进度文件 → 最近在读系列 → 最大系列」
      依次消歧；仍无法唯一确定才返回空（交给上层询问）
    """
    folder = _abs(books_dir)
    files = list_books(books_dir)
    if not files or not query:
        return "", ""
    raw = str(query).strip()
    if not raw:
        return "", ""
    low = raw.lower()
    norm_query = _norm(raw)
    volumes = query_volumes(raw)

    best_path, best_title, best_score = "", "", 0.0
    for name in files:
        base = os.path.splitext(name)[0]
        path = os.path.join(folder, name)
        # ① 精确命中（含原名反转包含）
        if base.lower() in low or low in base.lower():
            return path, base
        # ② 归一化后互相包含
        norm_base = _norm(base)
        if norm_base and (norm_base in norm_query or norm_query in norm_base):
            return path, base
        # ③ 打分选最优
        score = _score_book(base, norm_query, volumes)
        if score > best_score:
            best_path, best_title, best_score = path, base, score
    if best_path:
        return best_path, best_title

    # ④ 只说了卷号（或卷号 + 少量线索）：按卷号定位
    return _match_by_volume(folder, files, raw, volumes, state_dir, prefer)


def _match_by_volume(folder, files, raw, volumes, state_dir=None, prefer=""):
    """按明确卷号定位书：书名线索 → 在读系列提示 → 进度文件 → 最近在读 → 最大系列"""
    vol = explicit_volume(raw)
    if not vol:
        return "", ""
    cands = [os.path.splitext(f)[0] for f in files
             if _split_volume(os.path.splitext(f)[0])[1] == vol]
    if not cands:
        return "", ""
    # ① 书名线索（去掉卷号短语后剩下的字）打分
    rest = _norm(strip_volume_phrase(raw))
    if rest:
        scored = sorted(((_score_book(c, rest, {vol}), c) for c in cands),
                        key=lambda x: -x[0])
        if scored and scored[0][0] > 0:
            return os.path.join(folder, scored[0][1] + ".epub"), scored[0][1]
    # ② 当前/上一次在读的书所属系列（最可靠）
    if prefer:
        want = series_of(prefer)
        same = [c for c in cands if series_of(c) == want]
        if len(same) == 1:
            return os.path.join(folder, same[0] + ".epub"), same[0]
    if len(cands) == 1:
        return os.path.join(folder, cands[0] + ".epub"), cands[0]
    # ③ 有进度文件的（读过/在读）
    stated = [c for c in cands
              if os.path.isfile(os.path.join(state_dir or os.path.join(folder, "_state"),
                                             f"{c}.json"))]
    if len(stated) == 1:
        return os.path.join(folder, stated[0] + ".epub"), stated[0]
    # ③ 最近在读的系列
    recent_series, _ = _recent_state_series(state_dir or os.path.join(folder, "_state"))
    if recent_series:
        same = [c for c in cands if series_of(c) == recent_series]
        if len(same) == 1:
            return os.path.join(folder, same[0] + ".epub"), same[0]
    # ④ 最大系列（卷数唯一最多）
    counts = {}
    for c in cands:
        counts.setdefault(series_of(c), []).append(c)
    if len(counts) == 1:
        only = list(counts.values())[0][0]
        return os.path.join(folder, only + ".epub"), only
    sizes = sorted(((len(v), k) for k, v in counts.items()), reverse=True)
    if len(sizes) == 1 or (len(sizes) > 1 and sizes[0][0] > sizes[1][0]):
        pick = counts[sizes[0][1]][0]
        return os.path.join(folder, pick + ".epub"), pick
    return "", ""


# ==================== EPUB 解析 ====================
def load_book(path):
    """解析 EPUB，返回 {"title", "chapters":[{"title","text"}]}"""
    from ebooklib import epub
    book = epub.read_epub(path)
    titles = _toc_titles(book)
    chapters = []
    for idx, item in enumerate(_spine_items(book)):
        text = _extract_text(item)
        if not text:
            continue
        name = (item.get_name() or "").replace("\\", "/")
        title = titles.get(name) or titles.get(os.path.basename(name))
        if not title:
            title = os.path.splitext(os.path.basename(name))[0].replace("_", " ")
        chapters.append({"title": title or f"第{idx + 1}章", "text": text})
    return {"title": os.path.splitext(os.path.basename(path))[0], "chapters": chapters}


def split_sections(text, paras_per_section=8):
    """把章节正文按段落切成小节"""
    paras = [p.strip() for p in re.split(r"\n+", text or "") if p.strip()]
    if not paras:
        return []
    step = max(1, int(paras_per_section or 8))
    return ["\n".join(paras[i:i + step]) for i in range(0, len(paras), step)]


def _abs(path):
    """解析为绝对路径"""
    return path if os.path.isabs(path) else os.path.join(os.getcwd(), path)


def _spine_items(book):
    """按 spine 顺序取全部文档项（过滤 None，绝不漏章）"""
    get_item = book.get_item_with_id if hasattr(book, "get_item_with_id") else book.get_item
    items = []
    for item_id, _ in book.spine:
        try:
            item = get_item(item_id)
        except Exception:
            item = None
        if item is not None:
            items.append(item)
    return items


def _toc_titles(book):
    """从目录提取 href -> 标题 映射"""
    titles = {}

    def walk(items):
        for x in items or []:
            if isinstance(x, tuple):
                link, children = x
                href = getattr(link, "href", None)
                if href:
                    titles[str(href).split("#")[0].replace("\\", "/")] = getattr(link, "title", "")
                walk(children)
            else:
                href = getattr(x, "href", None)
                if href:
                    titles[str(href).split("#")[0].replace("\\", "/")] = getattr(x, "title", "")

    try:
        walk(book.toc)
    except Exception:
        pass
    return titles


def _extract_text(item):
    """提取章节纯文本（脚本/图片/多媒体全部剔除，不影响朗读）"""
    raw = _decode(item)
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.find_all(SKIP_TAGS):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _decode(item):
    """按 utf-8/gbk 依次尝试解码章节内容"""
    try:
        data = item.get_content()
    except Exception:
        return ""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return data.decode(enc, errors="ignore")
        except Exception:
            continue
    return ""
