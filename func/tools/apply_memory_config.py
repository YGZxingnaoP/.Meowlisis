# -*- coding: utf-8 -*-
# func/tools/apply_memory_config.py
# 记忆检索配置迁移：把新增配置键写入 config.yml，并给前端配置面板补齐对应输入项

import os
import datetime

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yml")
GUI_LLM_JS = os.path.join(BASE_DIR, "gui", "js", "config", "llm.js")

# 需要补充的配置键：(节点路径, 键名, 默认值)
ADD_KEYS = [
    ("catbrain.abstract_mem", "rank_evidence_saturation", 5.0),
    ("catbrain.abstract_mem", "rank_recency_half_life_days", 14),
    ("catbrain.abstract_mem", "summary_relevance_guarantee", 8),
    ("catbrain.long_term_mem", "inject_recent", False),
    ("catbrain.long_term_mem", "inject_recent_lines", 20),
    # 摘要写入门槛（减少低价值/重复摘要）
    ("catbrain.abstract_mem", "min_importance", 5),
    ("catbrain.abstract_mem", "max_events", 10),
    ("catbrain.abstract_mem", "recent_memory_lines", 12),
]

# 需要上调的历史默认值：(节点路径, 键名, 旧值, 新值)
BUMP_KEYS = [
    ("catbrain.abstract_mem", "summary_top_limit", 20, 30),
]

# 前端「记忆摘要」面板新增的「检索排序」折叠块
GUI_ABSTRACT_ANCHOR = "            this._num('话题更新间隔(秒)', 'catbrain.abstract_mem.topic_update_interval', 60, 1, 3600, 1);\n"
GUI_ABSTRACT_BLOCK = """        h += this._fold('检索排序 (rank)',
            this._num('证据分饱和上限', 'catbrain.abstract_mem.rank_evidence_saturation', 5.0, 0.1, 100, 0.1) +
            this._num('新近度半衰期(天)', 'catbrain.abstract_mem.rank_recency_half_life_days', 14, 1, 3650, 1) +
            this._num('相关性保底条数', 'catbrain.abstract_mem.summary_relevance_guarantee', 8, 0, 100, 1)
        );
"""

# 前端「记忆摘要」面板新增的「写入过滤 (write)」折叠块
GUI_WRITE_BLOCK = """        h += this._fold('写入过滤 (write)',
            this._num('最小重要度', 'catbrain.abstract_mem.min_importance', 5, 0, 10, 1) +
            this._num('单次最多事件数', 'catbrain.abstract_mem.max_events', 10, 1, 100, 1) +
            this._num('附带近期记忆条数', 'catbrain.abstract_mem.recent_memory_lines', 12, 0, 100, 1)
        );
"""

# 前端「长期记忆」面板新增的原文兜底项
GUI_LT_OLD = "            this._num('长期记忆回溯天数', 'catbrain.long_term_mem.memory_days', 300, 1, 3650, 1);"
GUI_LT_NEW = ("            this._num('长期记忆回溯天数', 'catbrain.long_term_mem.memory_days', 300, 1, 3650, 1) +\n"
              "            this._check('注入最近原文', 'catbrain.long_term_mem.inject_recent', false) +\n"
              "            this._num('注入原文条数', 'catbrain.long_term_mem.inject_recent_lines', 20, 1, 200, 1);")

# 前端「摘要检索条数上限」的默认值同步为 30
GUI_TOP_LIMIT_OLD = "this._num('摘要检索条数上限', 'catbrain.abstract_mem.summary_top_limit', 20, 1, 200, 1)"
GUI_TOP_LIMIT_NEW = "this._num('摘要检索条数上限', 'catbrain.abstract_mem.summary_top_limit', 30, 1, 200, 1)"


def _backup(path: str):
    """写入前备份原文件（带时间戳）"""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(path, "r", encoding="utf-8") as f:
        data = f.read()
    with open(f"{path}.bak_{stamp}", "w", encoding="utf-8") as f:
        f.write(data)


def _node(cfg: dict, path: str, create: bool = False):
    """按点号路径取（或创建）YAML 节点"""
    node = cfg
    for seg in path.split("."):
        if not isinstance(node, dict):
            return None
        if seg not in node or not isinstance(node[seg], dict):
            if not create:
                return None
            node[seg] = {}
        node = node[seg]
    return node


def patch_config() -> list:
    """补齐 config.yml 新增键并上调历史默认值，返回改动描述"""
    if not os.path.isfile(CONFIG_PATH):
        return [f"找不到 {CONFIG_PATH}"]
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    changed = []
    for path, key, value in ADD_KEYS:
        node = _node(cfg, path, create=True)
        if node is None or key in node:
            continue
        node[key] = value
        changed.append(f"{path}.{key} = {value!r}")
    for path, key, old, new in BUMP_KEYS:
        node = _node(cfg, path)
        if node is not None and node.get(key) == old:
            node[key] = new
            changed.append(f"{path}.{key}: {old} -> {new}")
    if changed:
        _backup(CONFIG_PATH)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
    return changed


def patch_gui() -> list:
    """给前端配置面板补齐新增输入项，返回改动描述"""
    if not os.path.isfile(GUI_LLM_JS):
        return [f"找不到 {GUI_LLM_JS}"]
    with open(GUI_LLM_JS, "r", encoding="utf-8") as f:
        text = f.read()
    changed = []
    if "rank_evidence_saturation" not in text and GUI_ABSTRACT_ANCHOR in text:
        text = text.replace(GUI_ABSTRACT_ANCHOR, GUI_ABSTRACT_ANCHOR + GUI_ABSTRACT_BLOCK, 1)
        changed.append("abstract_mem 新增「检索排序 (rank)」块")
    if "min_importance" not in text and GUI_ABSTRACT_ANCHOR in text:
        text = text.replace(GUI_ABSTRACT_ANCHOR, GUI_ABSTRACT_ANCHOR + GUI_WRITE_BLOCK, 1)
        changed.append("abstract_mem 新增「写入过滤 (write)」块")
    if "inject_recent" not in text and GUI_LT_OLD in text:
        text = text.replace(GUI_LT_OLD, GUI_LT_NEW, 1)
        changed.append("long_term_mem 新增「注入最近原文」项")
    if GUI_TOP_LIMIT_OLD in text:
        text = text.replace(GUI_TOP_LIMIT_OLD, GUI_TOP_LIMIT_NEW, 1)
        changed.append("摘要检索条数上限默认值 20 -> 30")
    if changed:
        _backup(GUI_LLM_JS)
        with open(GUI_LLM_JS, "w", encoding="utf-8") as f:
            f.write(text)
    return changed


def main():
    """执行迁移并打印改动结果"""
    print("[config.yml]", patch_config() or "无变化")
    print("[llm.js]", patch_gui() or "无变化")


if __name__ == "__main__":
    main()
