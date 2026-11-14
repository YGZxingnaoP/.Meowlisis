# -*- coding: utf-8 -*-
"""蔚蓝色图：一条命令 → 蔚蓝档案角色 → MOSS 8 步出图 → 按日期归档 → 合并转发。"""

import os
import random
import re
import shutil
import time

from . import theme
from .appearance import AppearanceBook
from .comfy import MossClient
from .danbooru import DanbooruTags
from .law import PromptLaw
from .pack import send as send_pack
from .prompt import PromptWriter
from .settings import Settings


class BlueArchiveApp:
    """只做蔚蓝档案：角色名 → 出图 → 归档 → 发送"""

    def __init__(self, ctx, cfg):
        """加载配置、内核客户端、法典、外观表与 tag 服务。"""
        self.ctx = ctx
        self.log = ctx.log
        self.llm = ctx.llm()
        self.napcat = ctx.napcat()
        self.cfg = Settings(cfg, ctx.root())
        self.comfy = MossClient(self.cfg, self.log)
        self.law = PromptLaw(self.cfg.law_file, log=self.log,
                             budget=self.cfg.law_budget)
        self.appear = AppearanceBook(self.cfg.appear_file, log=self.log)
        self.tags = DanbooruTags(self.cfg.tag_cache_file, log=self.log,
                                 enabled=self.cfg.danbooru_enabled,
                                 timeout=self.cfg.danbooru_timeout)
        self.writer = PromptWriter(self.cfg, self.log, self.llm, law=self.law)
        self._busy = False
        self._last = 0.0

    # ==================== 解析 ====================
    def parse(self, text):
        """返回 (角色名, 张数, 是否保守, 是否多人, 作品筛选)；非本插件消息返回 None。"""
        body = str(text or "").strip()
        prefix = self.cfg.trigger
        idx = body.lower().find(prefix.lower())
        if idx < 0:
            return None
        rest = body[idx + len(prefix):].strip()
        rest = rest.strip(" :,，:：、")
        tokens = [t for t in re.split(r"[\s,，、]+", rest) if t]
        count = None
        char = ""
        safe = False
        multi = False
        star = ""
        for t in tokens:
            low = t.lower()
            hit_series = theme.match_series(t)
            if hit_series:
                star = hit_series
            elif low in ("safemode", "safe", "保守", "安全", "sfw"):
                safe = True
            elif low in ("interact", "multi", "多人", "双人"):
                multi = True
            elif re.fullmatch(r"\d+", t):
                count = int(t)
            elif not char:
                char = t
        count = max(1, min(self.cfg.max_images or 9, count or self.cfg.default_images))
        return (theme.canonical(char) if char else "", count, safe, multi, star)

    # ==================== 入口 ====================
    def handle(self, text, qq_context):
        """入口：冷却与并发检查后起一批出图。"""
        parsed = self.parse(text)
        if parsed is None:
            return False
        char, count, safe, multi, star = parsed
        # 群里强制保守模式：群里一律不露点
        if str((qq_context or {}).get("message_type") or "") == "group":
            safe = True
        if self._busy:
            self._say(qq_context, "上一批还在画喵，等它出完~")
            return True
        wait = self.cfg.cooldown - (time.time() - self._last)
        if wait > 0:
            self._say(qq_context, "刚画过，歇 %d 秒再点喵~" % int(wait))
            return True
        self._busy = True
        self._last = time.time()
        try:
            self._work(char, count, qq_context, safe=safe, multi=multi, series=star)
        except Exception:
            self.log.exception("[image_factory] 出图流程异常")
            self._say(qq_context, "工厂里着火了喵（内部异常），看日志…")
        finally:
            self._busy = False
        return True

    def _pick(self, char, count, multi=False, series=""):
        """选角：单人→每张一个角色；interact→每张 2~3 个随机角色；series 限定作品。"""
        pool = theme.roster(series)
        if multi:
            groups = []
            for _ in range(max(1, int(count or 1))):
                k = random.randint(2, 3) if len(pool) >= 3 else 2
                groups.append(random.sample(pool, min(k, len(pool))))
            return groups
        if char:
            return [char] * max(1, int(count or 1))
        if not pool:
            return []
        return random.sample(pool, min(int(count or 1), len(pool)))

    # ==================== 主流程 ====================
    def _work(self, char, count, qq_context, safe=False, multi=False, series=""):
        """主流程：选角色 → 提示词 → 出图 → 归档 → 合并转发。"""
        t0 = time.time()
        if char and theme.char_tag(char) == "":
            self._say(qq_context, "「%s」不在蔚蓝档案名单里喵，换个名字试试~" % char)
            return
        chosen = self._pick(char, count, multi=multi, series=series)
        self.log.info("[image_factory] 角色=%s 张数=%d 模式=%s"
                      % (chosen, len(chosen), "保守" if safe else "R-18"))

        ok, msg = self.comfy.ensure_engine()
        if not ok:
            self._say(qq_context, "画图内核没起来喵（%s）" % msg)
            return

        batch_dir = os.path.join(self.cfg.archive_dir, time.strftime("%Y-%m-%d"),
                                 time.strftime("%H%M%S"))
        os.makedirs(batch_dir, exist_ok=True)
        images, notes = [], []
        for i, name in enumerate(chosen):
            multi_n = len(name) if isinstance(name, list) else 0
            if isinstance(name, list):
                tags_join = [theme.char_tag(n) for n in name if theme.char_tag(n)]
                name = "、".join(name)
                tag = ", ".join(tags_join)
            else:
                tag = self.tags.resolve(name, theme.en_name(name)) or theme.char_tag(name)
            appearance = self.appear.get("蔚蓝档案", name) or ""
            prompt = self.writer.write(name, appearance, i, len(chosen),
                                       char_tag=tag, safe=safe, multi=multi_n)
            if not prompt:
                notes.append("%s: 提示词为空" % name)
                continue
            self.log.info("[image_factory] %s 提示词(%d 字)：%s"
                          % (name, len(prompt), prompt[:260].replace("\n", " ")))
            positive = ("%s, %s" % (self.cfg.quality, prompt)) if self.cfg.quality else prompt
            # LoRA 自带触发词：@ 开头的（如 @szcb911style）必须放最前面，其余拼在质量词后
            trig = [l.get("trigger") for l in (self.cfg.loras or []) if l.get("trigger")]
            head = list(dict.fromkeys(t for t in trig if t.startswith("@")))
            tail = list(dict.fromkeys(t for t in trig if not t.startswith("@")))
            if tail:
                positive = "%s, %s, %s" % (self.cfg.quality, ", ".join(tail), prompt) \
                    if self.cfg.quality else "%s, %s" % (", ".join(tail), prompt)
            if head:
                positive = ", ".join(head) + ", " + positive
            graph = self.comfy.build_graph(positive, self.cfg.negative)
            ok, pid, err = self.comfy.submit(graph)
            if not ok:
                notes.append("%s: 提交失败(%s)" % (name, err))
                continue
            ok, outs, wmsg = self.comfy.wait(pid)
            if not ok or not outs:
                notes.append("%s: 出图失败(%s)" % (name, wmsg))
                continue
            for k, item in enumerate(outs):
                path = self.comfy.download(item, batch_dir, index=len(images))
                if path:
                    images.append(path)
            self.log.info("[image_factory] %s 完成（%d 秒）" % (name, int(time.time() - t0)))

        if not images:
            self._say(qq_context, "一张都没画出来喵…（%s）" % "；".join(notes[:3]))
            return
        ok, detail = send_pack(self.napcat, qq_context, images,
                               pay_image=self.cfg.pay_image,
                               sender=self.cfg.forward_sender,
                               fallback_single=self.cfg.forward_fallback)
        self.log.info("[image_factory] 完成 %d 张，耗时 %.0f 秒，发送=%s(%s)"
                      % (len(images), time.time() - t0, ok, detail or ""))
        if not ok:
            self._say(qq_context, "图画好了但没发出去喵（%s）" % detail)
            return
        self._prune(images)

    # ==================== 杂项 ====================
    def _prune(self, images):
        """按配置清理旧批次目录（0 = 永久保留）。"""
        keep = int(self.cfg.keep_images or 0)
        if keep <= 0:
            return
        base = self.cfg.archive_dir
        batches = []
        for day in sorted(os.listdir(base), reverse=True):
            dpath = os.path.join(base, day)
            if not os.path.isdir(dpath):
                continue
            for b in sorted(os.listdir(dpath), reverse=True):
                bpath = os.path.join(dpath, b)
                if os.path.isdir(bpath):
                    batches.append(bpath)
        for old in batches[keep:]:
            shutil.rmtree(old, ignore_errors=True)

    def _say(self, qq_context, text):
        """向来源会话发一条提示（默认静默）。"""
        if not self.cfg.notify_progress:
            return
        try:
            target = str((qq_context or {}).get("target_id") or "")
            mt = str((qq_context or {}).get("message_type") or "group")
            if not target:
                return
            if mt == "private":
                self.napcat.send_private_text(target, text)
            else:
                self.napcat.send_group_text(target, text)
        except Exception:
            pass
