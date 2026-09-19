# -*- coding: utf-8 -*-
"""文档助手 Agent：检索 → 数据处理 → 配图 → 出稿 的工具循环。

工具集
------
    web_search / web_open      联网检索（沿用原有实现）
    make_chart / make_table    数据 → 图表 / 表格
    image_search / gen_image   配图（网络搜图 / 硅基流动生图）
    write_doc / write_ppt      出稿（按 fmt 只暴露其中一个）

设计要点
--------
* 图片、数据来源自动汇总进文末「资料来源 / 图片来源」，不靠模型自觉
* 配图总数受 image.max_per_doc 限制；任何图片工具失败都不影响出稿
* 排版交給 render/layouts，模型只选版式与主题
"""

import json
import re

from . import datatool as DT
from . import render as R


class DocAgent:
    def __init__(self, ctx, config):
        """文档助手 Agent：联网检索并生成成品文件"""
        self.ctx = ctx
        self.config = config
        from .browser import DynamicBrowser
        from .port import DocLLM
        from .search import WebSearch
        self.llm = DocLLM(config)
        self.browser = DynamicBrowser(config.driver_dir, config.driver_mirror, config.timeout)
        self.search = WebSearch(config, self.browser)
        self.assets = R.assets_dir(config.output_dir)
        self.images = []            # [{"title","source","w","h"}]
        self.datas = []             # [{"title","url"}]
        self.last_error = ""
        self._gen = None
        self._img_search = None

    # ==================== 主流程 ====================
    def run(self, request, doc_type, fmt, short_memory=None):
        """执行检索与写作，返回 {"path","reason"}"""
        if not self.llm.available():
            return {"path": "", "reason": self.llm.last_error or "LLM 端口不可用"}
        from .prompts import agent_tools, system_prompt, user_prompt

        messages = [
            {"role": "system", "content": system_prompt(doc_type, fmt, self.config)},
            {"role": "user", "content": user_prompt(request, doc_type, fmt, short_memory or [])},
        ]
        tools = self._tools(agent_tools(), fmt)
        written = ""
        for _ in range(max(1, self.config.agent_rounds)):
            resp = self.llm.chat(messages, tools=tools, tool_choice="auto")
            if not resp or not resp.choices:
                break
            msg = resp.choices[0].message
            calls = list(msg.tool_calls or [])
            if not calls:
                break
            messages.append(self._assistant_msg(msg, calls))
            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except Exception:
                    args = {}
                text, path = self._run_tool(call.function.name, args)
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "name": call.function.name, "content": text})
                if path:
                    written = path
            if written:
                break
        if written:
            return {"path": written, "reason": ""}
        forced = self._force_write(request, doc_type, fmt)
        if forced:
            return {"path": forced, "reason": ""}
        return {"path": "", "reason": getattr(self.llm, "last_error", "") or "模型未产出文件"}

    def _tools(self, tools, fmt):
        """按产出格式与能力开关过滤工具"""
        drop = {"write_doc"} if fmt == "pptx" else {"write_ppt"}
        if not self.config.images_enabled or self.config.image_max <= 0:
            drop |= {"image_search", "gen_image"}
        return [t for t in tools if t["function"]["name"] not in drop]

    def _assistant_msg(self, msg, calls):
        """构造 assistant 消息"""
        return {"role": "assistant", "content": msg.content or "",
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name,
                                             "arguments": c.function.arguments}} for c in calls]}

    # ==================== 工具执行 ====================
    def _run_tool(self, name, args):
        """执行工具，返回 (结果文本, 落盘路径)"""
        self._last_path = ""
        try:
            if name == "web_search":
                return self._web_search(args), ""
            if name == "web_open":
                return self.search.open(str(args.get("url") or ""), bool(args.get("dynamic"))), ""
            if name == "make_chart":
                return self._make_chart(args), ""
            if name == "make_table":
                return self._make_table(args), ""
            if name == "image_search":
                return self._image_search(args), ""
            if name == "gen_image":
                return self._gen_image(args), ""
            if name == "write_doc":
                return self._write_doc(args), self._last_path
            if name == "write_ppt":
                return self._write_ppt(args), self._last_path
        except Exception as e:
            self.ctx.log.exception(f"[docwriter] 工具 {name} 执行失败")
            return f"工具执行失败：{e}", ""
        return f"未知工具：{name}", ""

    def _web_search(self, args):
        page = int(args.get("page") or 1)
        items = self.search.search(str(args.get("query") or ""), page)
        for it in items[:3]:
            self.datas.append({"title": it.get("title", ""), "url": it.get("url", "")})
        return self._format_results(items, page)

    def _make_chart(self, args):
        rows = args.get("rows") or []
        path = DT.make_chart(rows, self.assets, kind=str(args.get("kind") or "bar"),
                             title=str(args.get("title") or ""),
                             filename=str(args.get("filename") or args.get("title") or "chart"),
                             theme=self._theme(args), top=int(args.get("top") or 8),
                             xlabel=str(args.get("xlabel") or ""), ylabel=str(args.get("ylabel") or ""))
        if not path:
            return "图表生成失败：数据为空或绘图异常，请检查 rows（需含 name/value）。"
        return f"图表已生成，路径：{path}（请直接引用该路径）"

    def _make_table(self, args):
        header, body = DT.make_table(args.get("rows") or [], header=args.get("header"),
                                     max_rows=int(args.get("max_rows") or 12))
        if not body:
            return "表格生成失败：数据为空。"
        lines = ["| " + " | ".join(str(h) for h in header) + " |",
                 "| " + " | ".join("---" for _ in header) + " |"]
        lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
        return "表格已就绪（Markdown，可直接放进 content；PPT 可用 header/rows 字段）：\n" + "\n".join(lines)

    def _image_search(self, args):
        if self._img_left() <= 0:
            return f"配图数量已达上限（{self.config.image_max} 张），请改用已有图片或文字排版。"
        from .imagesearch import ImageSearch, build_source_list

        if self._img_search is None:
            self._img_search = ImageSearch(self.config)
        query = str(args.get("query") or "").strip()
        n = min(int(args.get("count") or 1), self._img_left())
        got = self._img_search.fetch(query, self.assets, n=n)
        if not got:
            return (f"没搜到合适图片（{self._img_search.last_error or '结果尺寸/格式不达标'}），"
                    "请改用 make_chart 或省略配图。")
        for g in got:
            self.images.append({"title": g.get("title") or query, "source": g.get("source"),
                                "w": g.get("w"), "h": g.get("h"), "path": g.get("path")})
        lines = [f"已下载 {len(got)} 张图片（引用路径如下）："]
        lines += [f"- {g['path']}（{g.get('w')}×{g.get('h')}）" for g in got]
        lines += ["来源：" + s for s in build_source_list(got)[:4]]
        return "\n".join(lines)

    def _gen_image(self, args):
        if self._img_left() <= 0:
            return f"配图数量已达上限（{self.config.image_max} 张），请改用已有图片或文字排版。"
        if self.config.image_source == "search":
            return "当前配置只允许网络搜图（image.source=search），请改用 image_search。"
        from .imagegen import ImageGen

        if self._gen is None:
            self._gen = ImageGen(self.config)
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return "生图失败：提示词为空。"
        path = self._gen.generate(prompt, self.assets, filename=str(args.get("filename") or ""),
                                  aspect=str(args.get("aspect") or "square"))
        if not path:
            return (f"生图失败（{getattr(self._gen, 'last_error', '') or '未知原因'}），"
                    "请改用 image_search 或 make_chart。")
        self.images.append({"title": prompt[:40], "source": "AI 生成（Kwai-Kolors/Kolors）",
                            "w": "", "h": "", "path": path})
        return f"配图已生成，路径：{path}（请直接引用该路径）"

    # ==================== 出稿 ====================
    _last_path = ""

    def _theme(self, args):
        """主题：工具参数 > 配置 > 默认"""
        theme = str((args or {}).get("theme") or "").strip()
        if theme:
            return theme
        cfg_theme = str(getattr(self.config, "theme", "auto") or "auto")
        return cfg_theme if cfg_theme and cfg_theme != "auto" else "tech"

    def _write_doc(self, args):
        content = str(args.get("content") or "")
        source_md = self._source_markdown()
        if source_md:
            content = content.rstrip() + "\n\n---\n" + source_md
        path = R.write_doc(str(args.get("filename") or "文档"), content,
                           self.config.output_dir, theme=self._theme(args),
                           title=str(args.get("title") or ""),
                           subtitle=str(args.get("subtitle") or ""),
                           meta=["docwriter 自动生成"],
                           cover=bool(self.config.cover), toc=bool(self.config.toc))
        self._last_path = path
        return f"已生成文件：{path}"

    def _write_ppt(self, args):
        slides = args.get("slides") or []
        if not isinstance(slides, list):
            slides = []
        slides = [s for s in slides if isinstance(s, dict) and s.get("title") is not None]
        self._insert_source_slide(slides)
        path = R.write_ppt(str(args.get("filename") or "演示文稿"), slides,
                           self.config.output_dir, theme=self._theme(args),
                           title=str(args.get("title") or ""),
                           subtitle=str(args.get("subtitle") or ""))
        self._last_path = path
        return f"已生成文件：{path}"

    def _insert_source_slide(self, slides):
        """把「资料来源」页插到结尾页之前（没有结尾页就追加）"""
        src = self._source_bullets()
        if not src or len(slides) >= 24:
            return
        item = {"layout": "bullets", "title": "资料来源", "bullets": src}
        try:
            last = R.pick_layout(slides[-1], len(slides) - 1, len(slides))
        except Exception:
            last = ""
        if slides and last == "end":
            slides.insert(len(slides) - 1, item)
        else:
            slides.append(item)

    def _source_markdown(self):
        """文末来源清单（Markdown）"""
        parts = []
        if self.datas:
            seen, lines = set(), []
            for i, d in enumerate(self.datas, 1):
                url = str(d.get("url") or "")
                if not url or url in seen:
                    continue
                seen.add(url)
                lines.append(f"{len(lines) + 1}. {str(d.get('title') or '资料')[:60]} — {url}")
                if len(lines) >= 12:
                    break
            if lines:
                parts.append("## 资料来源\n" + "\n".join(lines))
        if self.images:
            lines = [f"{i}. {str(it.get('title') or '图片')[:50]}"
                     f"（{it.get('w') or '?'}×{it.get('h') or '?'}） 来源：{it.get('source')}"
                     for i, it in enumerate(self.images, 1)]
            parts.append("## 图片来源\n" + "\n".join(lines))
        return "\n\n".join(parts)

    def _source_bullets(self):
        """PPT 来源页要点（每条一行，控制条数）"""
        out = []
        for d in self.datas[:3]:
            url = str(d.get("url") or "")
            if url:
                out.append(f"{str(d.get('title') or '资料')[:18]}｜{url[:38]}")
        for it in self.images[:3]:
            out.append(f"配图：{str(it.get('title') or '')[:14]}｜{str(it.get('source') or '')[:34]}")
        return out[:6]

    def _img_left(self):
        """剩余可配图张数"""
        return max(0, int(self.config.image_max) - len(self.images))

    # ==================== 兜底 ====================
    def _force_write(self, request, doc_type, fmt):
        """兜底：不给工具，要求模型直接输出结构化内容并落盘（不含配图）"""
        from .prompts import force_prompt
        from .render import write_doc, write_ppt

        content = self.llm.chat_text([
            {"role": "system", "content": force_prompt(request, doc_type, fmt)},
            {"role": "user", "content": "请按要求直接输出 JSON。"},
        ])
        data = self._parse_json(content)
        if not data:
            return ""
        filename = str(data.get("filename") or "")
        theme = self._theme(data)
        try:
            if fmt == "pptx":
                slides = data.get("slides") or []
                if not slides:
                    return ""
                self._insert_source_slide(slides)
                return write_ppt(filename, slides, self.config.output_dir, theme=theme,
                                 title=str(data.get("title") or ""),
                                 subtitle=str(data.get("subtitle") or ""))
            body = str(data.get("content") or "")
            if not body.strip():
                return ""
            source_md = self._source_markdown()
            if source_md:
                body = body.rstrip() + "\n\n---\n" + source_md
            return write_doc(filename, body, self.config.output_dir, theme=theme,
                             title=str(data.get("title") or ""),
                             subtitle=str(data.get("subtitle") or ""),
                             cover=bool(self.config.cover))
        except Exception:
            return ""

    @staticmethod
    def _parse_json(content):
        """从模型输出中解析 JSON 对象"""
        if not content:
            return {}
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _format_results(items, page):
        """格式化搜索结果"""
        if not items:
            return f"第 {page} 页没有搜索到结果，可稍后重试或换关键词。"
        lines = [f"第 {page} 页搜索结果："]
        for i, it in enumerate(items, 1):
            lines.append(f"{i}. {it.get('title', '')}\n   URL: {it.get('url', '')}\n"
                         f"   摘要: {it.get('snippet', '')}")
        return "\n".join(lines)
