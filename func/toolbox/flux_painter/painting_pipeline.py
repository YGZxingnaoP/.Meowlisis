# -*- coding: utf-8 -*-
import os
import time
from func.pipeline.id_signup import display_name
from func.toolbox.flux_painter.comfy_connector import create_connector

DEFAULT_NEGATIVE = ("lowres,bad anatomy,bad hands,error,missing fingers,extra digits,"
                    "worst quality,jpeg artifacts,watermark,signature,text")
REJECT_TEXT = "不给看不给看awa"


class TBPaintPipelineMixin:
    """出图主流程：提示词 → 织图 → 轮询 → 归档 → 发 QQ。"""

    def _send_qq_image(self, session, image_path):
        """把成品图+角色点评发给 QQ。"""
        try:
            if not self.config.enabled or not image_path or not os.path.isfile(image_path):
                return
            channel = session.get("channel", "")
            reply = str(session.get("reply") or "").strip()
            if not reply:
                reply = self._line_need("图已经画好了，跟主人说一句。")
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ncore = TBNapCatCore()
            qc = session.get("qq_context") or {}
            owner = str(session.get("owner_uid") or qc.get("user_id") or qc.get("target_id") or "")
            img = {"type": "image",
                   "data": {"file": ncore.api_client._to_file_uri(image_path)}}
            if channel.startswith("qq_group_"):
                gid = str(qc.get("target_id") or qc.get("group_id") or "")
                if not gid:
                    return
                nsfw, why = False, "safe(未开启)"
                cached = session.get("nsfw")
                if cached:
                    nsfw, why = cached
                elif self.config.nsfw_enabled:
                    nsfw, why = self._nsfw_check(image_path)
                    self.log.info(f"[flux_painter] 群裸图审查 {os.path.basename(image_path)} -> {why}")
                if nsfw:
                    delivered = False
                    if owner:
                        delivered = self._qq_private_send(ncore, owner, gid, [
                            {"type": "text", "data": {"text": reply}}, img])
                    msg = []
                    if owner:
                        msg.append({"type": "at", "data": {"qq": owner}})
                    if delivered:
                        tail = reply + "（这张比较大胆，已私发给你啦~【私】）"
                    else:
                        tail = reply + "（这张比较大胆，群里就不发了）"
                    msg.append({"type": "text", "data": {"text": (" " + tail) if owner else tail}})
                    ncore.call_action_sync("send_group_msg", {"group_id": int(gid), "message": msg})
                    return
                msg = []
                if owner:
                    msg.append({"type": "at", "data": {"qq": owner}})
                    msg.append({"type": "text", "data": {"text": " " + reply}})
                else:
                    msg.append({"type": "text", "data": {"text": reply}})
                msg.append(img)
                ncore.call_action_sync("send_group_msg", {"group_id": int(gid), "message": msg})
            elif owner:
                ncore.call_action_sync("send_private_msg", {
                    "user_id": int(owner),
                    "message": [{"type": "text", "data": {"text": reply}}, img]})
        except Exception:
            self.log.exception("[flux_painter] QQ 发图失败")

    def _opener_line(self, channel, request):
        """接单开场白：角色按自己此刻的语气现生成，每次不同（生成失败才随机取兜底池）"""
        uid = str(self._context.get("meowid") or "")
        who = display_name(uid) or "对方"
        with self._opener_lock:
            avoid = list(self._opener_recent.get(str(channel)) or ())
        line = ""
        for _ in range(2):
            try:
                from func.toolbox.character_voice import TBoxCharacterVoice
                line = TBoxCharacterVoice().line(
                    f"{who}点单让你画「{request}」，你已经动笔了。应{who}一声："
                    f"让{who}知道你开始画了、大概要等一会儿，画完会给他看。",
                    uid, history=self._context.get("short_memory") or [],
                    max_chars=40, avoid=avoid)
            except Exception:
                self.log.exception("[flux_painter] 开场白生成失败")
                line = ""
            if line:
                break
        if not line:
            self.log.warning("[flux_painter] 开场白生成失败，本次不应声")
            return ""
        with self._opener_lock:
            recent = self._opener_recent.setdefault(str(channel), [])
            recent.append(line)
            del recent[:-6]
        return line

    def _save_memory(self, uid, user_text, reply, scope=None):
        """记录到短期/长期/用户记忆（uid 缺失就不写；只传通道，轮号取写入时刻的当前轮）。"""
        if not uid:
            self.log.error("[flux_painter] 无身份编号，跳过记忆写入")
            return
        if not self.config.memory_enabled:
            return
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({"role": "user", "content": f"【绘画】{user_text}",
                                "type": self.config.memory_type}, self.config.memory_rounds,
                               trim_mode="rounds", scope=scope)
            ShortMemory().save({"role": "assistant", "content": f"【绘画】{reply}",
                                "type": self.config.memory_type}, self.config.memory_rounds,
                               trim_mode="rounds", scope=scope)
        except Exception:
            pass
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            from func.config.app_config import AppConfig
            bridge = MeowLLMLtMemBridge()
            bridge.record_user_message(uid, f"（让我画图）{user_text}")
            bridge.record_ai_message(uid, AppConfig().ai_name, f"（画了图）{reply}")
        except Exception:
            pass

    def _nsfw_check(self, image_path):
        """敏感/裸露判定（NudeNet onnx，与 QQ 群聊共用同一模型；阈值按底模家族取）。"""
        ns = self.config.moss_nsfw() if self.config.is_moss else {
            "enabled": self.config.nsfw_enabled,
            "threshold": self.config.nsfw_threshold,
            "fail_action": self.config.nsfw_fail,
        }
        if not ns.get("enabled"):
            return False, "safe(未开启)"
        try:
            from func.toolbox.flux_painter.nsfw_judge import TBNsfwJudge
            j = TBNsfwJudge(self.config)
            okm, mmsg = j.ensure_model()
            if okm:
                return j.judge(image_path, threshold=ns.get("threshold"))
            nsfw = ns.get("fail_action") == "dm"
            return nsfw, "model:" + str(mmsg)
        except Exception as e:
            nsfw = ns.get("fail_action") == "dm"
            return nsfw, f"judge_error:{e}"

    def _run(self, session):
        """一次完整绘画：提示词→出图→归档→审查→语音/展示→记忆"""
        channel = session["channel"]
        uid = session["meowid"]
        request = session["request"]
        memories = session.get("memories") or []
        persona = session.get("persona") or ""
        released = False

        try:
            self._bcast(channel, {"type": "status", "text": "AI 正在构思画面…"})

            ref_image = str(session.get("init_image") or "")
            ref_note = str(session.get("ref_note") or "")

            def on_stream(text):
                """流式回调：把提示词片段推给界面。"""
                self._bcast(channel, {"type": "producing", "text": text})

            role_hint = ""
            try:
                from func.toolbox.flux_painter.char_resolver import TBRoleResolver
                _resolver = TBRoleResolver(self.config)
                _card = _resolver.resolve_from_text(request)
                if _card and _card.get("name_en"):
                    role_hint = (
                        "\n\n【角色（已查证）】%s / %s / 作品：%s。"
                        "提示词只准使用这个角色 tag 与作品 tag：`%s`、`%s`；"
                        "严禁音译、严禁写别的作品。外观（发色/瞳色/服装）由你自己判断填写，"
                        "不确定就不写，宁缺勿错。"
                        % (_card.get("name"), _card.get("name_en"),
                           _card.get("series") or "?",
                           _card.get("tag") or _card.get("name_en"),
                           _card.get("series") or ""))
                    try:
                        _top = list(_card.get("top_tags") or [])
                        _ok = bool(_top)
                        if not _ok:
                            from func.toolbox.flux_painter.prompts.danbooru_tool import top_tags
                            _ok, _top = top_tags(_card.get("tag") or _card["name_en"],
                                                 config=self.config, log=self.log)
                        if _ok and _top:
                            role_hint += ("\n外观参考（danbooru 高频 tag，数据非猜测）：%s。"
                                          "合适就用，不合适忽略。"
                                          % ", ".join(t.replace("_", " ") for t in _top))
                    except Exception:
                        self.log.exception("[flux_painter] 角色高频 tag 获取异常")
                    self.log.info("[flux_painter] 角色资料注入: %s (%s / %s)"
                                  % (_card.get("name"), _card["name_en"],
                                     _card.get("series")))
            except Exception:
                self.log.exception("[flux_painter] 角色资料解析异常")
            if role_hint:
                request = request + role_hint

            elements = self.producer.run(request, nickname=display_name(uid),
                                         persona=persona,
                                         memory=memories,
                                         on_stream=on_stream,
                                         base_elements=session.get("base_elements"),
                                         base_request=session.get("base_request"),
                                         reference_image=ref_image or None)
            if not elements:
                self.log.error("[flux_painter] 提示词 LLM 未产出画作要素，本次绘画提前结束")
                self._say_need(channel, "你想了半天没想好怎么画，跟主人说一句，让他换一句试试。")
                self._bcast(channel, {"type": "status", "text": "没想好怎么画"})
                return
            positive = str(elements["positive"] or "").strip()
            reply = str(elements["reply"] or "")
            title = str(elements["title"] or session.get("topic") or "画")
            canvas_key = elements["canvas"]
            self.log.info(f"[flux_painter] 提示词产出 title={title} len={len(positive)} "
                          f"canvas={canvas_key} request={request[:60]!r}")

            try:
                from func.toolbox.flux_painter.char_resolver import TBRoleResolver
                _resolver = TBRoleResolver(self.config)
                _card = _resolver.resolve_from_text(request)
                if _card and self.config.family == "anima":
                    en = _card["name_en"]
                    series = str(_card.get("series") or "")
                    want = "%s (%s)" % (en, series) if series else en
                    known_series = set()
                    try:
                        doc = _resolver._load()[0]
                        known_series = {str(s).lower() for s in (doc.get("series") or {})}
                    except Exception:
                        known_series = set()
                    parts = [p.strip() for p in positive.split(",")]
                    cleaned = []
                    for p in parts:
                        low = p.lower()
                        if not p:
                            continue
                        if p.endswith(")") and "(" in p and low != want.lower():
                            continue                     # 写错作品的括注 tag
                        if low == en.lower() and want.lower() != low:
                            continue                     # 同一角色的裸名（下面补全括注）
                        if not series and low == want.lower():
                            cleaned.append(p)
                            continue
                        if low in known_series and low != series.lower():
                            continue                     # 写错作品的裸作品 tag
                        cleaned.append(p)
                    if not any(p.lower() == want.lower() for p in cleaned):
                        head = 1 if cleaned and cleaned[0].lower() in ("1girl", "1boy", "2girls") else 0
                        cleaned.insert(head, want)
                        self.log.info("[flux_painter] 角色 tag 归一为: %s" % want)
                    positive = ", ".join(cleaned)
            except Exception:
                self.log.exception("[flux_painter] 角色 tag 归一异常")

            try:
                if not self._wants_multiple(request):
                    positive = self._strip_interaction(positive)
            except Exception:
                self.log.exception("[flux_painter] solo 去交互异常")

            if not reply:
                reply = self._line_need("图已经画好了，跟主人说一声，可以带点得意。")

            cinema = str(elements.get("cinema") or "").strip()
            if cinema and not self._wants_multiple(request):
                cinema = self._strip_cinema_interaction(cinema)
            if cinema:
                positive = (positive.rstrip() + ", " + cinema) if positive else cinema

            style_extra, artist_kw, style_on = self._style_hint(request)
            if not artist_kw and not style_extra and style_on:
                _hit = self.artist.pick_artists(1)
                if _hit:
                    artist_kw = str(_hit[0].get("name") or "").strip()
                    self.log.info(f"[flux_painter] 风格化需求 → 画师库随机抽中: {artist_kw}")
                else:
                    self.log.warning("[flux_painter] 风格化需求但画师库为空，跳过画师")
            named, manual = [], []
            if artist_kw:
                hit = None
                try:
                    if self.artist.ensure_data()[0]:
                        hit = self.artist.search(artist_kw, top=1)  # 精确优先
                except Exception:
                    hit = None
                if hit and hit[0].get("name") == artist_kw:
                    named = [hit[0]]
                elif hit:
                    manual.append("@" + str(hit[0].get("name") or "").strip())  # 点名近似→库内全名
                else:
                    manual.append("@" + artist_kw)                              # 库外/名单直接按原名
            for s in style_extra:
                s = str(s).strip()
                tag = "@" + s.lstrip("@").strip()
                if s and tag not in manual:
                    manual.append(tag)
            if artist_kw or manual:
                parts = ["@" + str(a.get("name") or "").strip() for a in named if a.get("name")]
                parts += manual
                artist_tags = ", ".join(parts) + ", " if parts else ""
            else:
                artist_tags = ""
            quality = self.config.active_quality()
            final_positive = ((artist_tags + quality + ", " + positive)
                              if artist_tags else
                              ((quality + ", " + positive) if quality else positive))
            try:
                final_positive = self._verified_positive(final_positive)
            except Exception:
                self.log.exception("[flux_painter] 角色 tag 查证异常")
            try:
                _dial = getattr(self.config, "family", "anima")
                _trig = []
                _hook = getattr(connector.dialect(), "trigger_words", None)
                if callable(_hook):
                    _trig = [t for t in (_hook(connector) or []) if t]
                if _trig:
                    head = [t for t in _trig if t.startswith("@")]
                    tail = [t for t in _trig if not t.startswith("@")]
                    if head:
                        final_positive = ", ".join(dict.fromkeys(head)) + ", " + final_positive
                    if tail:
                        _prefix = ", ".join(tail) + ", "
                        if artist_tags:
                            final_positive = artist_tags + _prefix + final_positive
                        else:
                            final_positive = _prefix + final_positive
                    self.log.info(f"[flux_painter] 追加 LoRA 触发词: {', '.join(_trig)}")
            except Exception:
                pass
            negative = self.config.active_negative() or DEFAULT_NEGATIVE
            w, h = self._canvas_size(canvas_key)

            self._bcast(channel, {"type": "prompt",
                                  "positive": final_positive, "negative": negative,
                                  "title": title})

            ok, message = self._ensure_comfy()
            if not ok:
                self.log.error(f"[flux_painter] 绘图引擎未就绪: {message}")
                self._say_need(channel, f"画图引擎没启动（原因：{message}），跟主人说一句，别提技术词。")
                return
            self.log.info("[flux_painter] 绘图引擎就绪")
            connector = create_connector(self.config)
            prefix = f"flux_{time.strftime('%Y%m%d_%H%M%S')}"
            ref_name = ""
            if ref_image:
                ref_name = connector.upload_image(ref_image)
                if not ref_name:
                    self.log.warning("[flux_painter] 参考图上传失败，本张按文生图继续")
                else:
                    self.log.info(f"[flux_painter] 参考图已上传: {ref_name}")

            def on_event(stage):
                """事件回调：把阶段/进度推给界面。"""
                self._bcast(channel, {"type": "progress", "text": stage})

            ok_done = False
            images, wmsg = [], ""
            dialect = connector.dialect()
            mode = str(getattr(self.config, "quality_mode", "fast") or "fast").lower()
            if mode not in dialect.quality_modes:
                mode = dialect.quality_modes[0]
            pro_p = getattr(self.config, "pro", {}) or {}
            pro_on = bool(mode == "pro" and (dialect.family != "anima" or pro_p.get("enabled", True)))
            if pro_on:
                try:
                    missing = connector.missing_pro_nodes()
                except Exception:
                    missing = []
                if missing:
                    self.log.warning(f"[flux_painter] pro 档位缺节点 {missing}，本次降级快速档"
                                     "（检查自定义节点是否已安装/加载）")
                    pro_on = False
                else:
                    self.log.info(f"[flux_painter] 画质档位=pro（{dialect.family} / "
                                  f"{dialect.quality_labels.get('pro', 'pro')}）")
            else:
                self.log.info(f"[flux_painter] 画质档位=fast（{dialect.family} / "
                              f"{dialect.quality_labels.get('fast', 'fast')}）")
            progress_on = bool(getattr(self.config, "progress_detail", True))
            last_eta = self._last_paint_time(pro_on)
            for clip_type in connector.clip_types():
                if pro_on:
                    graph = connector.build_pro_graph(final_positive, negative, w, h,
                                                      prefix=prefix, clip_type=clip_type,
                                                      params=pro_p)
                else:
                    graph = connector.build_graph(final_positive, negative, w, h,
                                                  prefix=prefix, clip_type=clip_type)
                if ref_name:
                    graph = connector.with_init_image(graph, ref_name,
                                                      self.config.img2img_denoise_for(dialect.family), w, h)
                on_event("提交任务…")
                sok, prompt_id, serr = connector.submit(graph, client_id=channel)
                if not sok and pro_on:
                    self.log.warning(f"[flux_painter] pro 图提交失败，降级快速档重试: {serr[:200]}")
                    pro_on = False
                    graph = connector.build_graph(final_positive, negative, w, h,
                                                  prefix=prefix, clip_type=clip_type)
                    if ref_name:
                        graph = connector.with_init_image(graph, ref_name,
                                                          self.config.img2img_denoise_for(dialect.family), w, h)
                    sok, prompt_id, serr = connector.submit(graph, client_id=channel)
                if not sok:
                    self.log.error(f"[flux_painter] 任务提交失败 clip={clip_type}: {serr[:200]}")
                    self._say_need(channel, f"画图任务没提交成功（原因：{serr[:120]}），跟主人说一句。")
                    return
                self.log.info(f"[flux_painter] 任务已提交 clip={clip_type} prompt_id={prompt_id}")
                self._bcast(channel, {"type": "status", "text": "AI 正在作画…"})
                t_paint0 = time.time()
                if progress_on:
                    self._bcast(channel, {"type": "progress", "stage": "已入队", "percent": 0,
                                          "step": "", "elapsed": 0, "eta": last_eta or 0})
                wok, images, wmsg = connector.watch(
                    prompt_id, graph=graph, timeout=int(getattr(self.config, "wait_timeout", 5400)),
                    client_id=channel,
                    on_progress=((lambda ev: self._bcast(
                        channel, dict(ev, type="progress", eta=last_eta or 0)))
                        if progress_on else None))
                if wok:
                    self._record_paint_time(pro_on, int(time.time() - t_paint0))
                    ok_done = True
                    self.log.info(f"[flux_painter] 出图完成 clip={clip_type}")
                    break
                self.log.error(f"[flux_painter] 出图失败 clip={clip_type}: {wmsg[:200]}")
                low = str(wmsg).lower()
                if not any(k in low for k in ("clip", "text encoder", "type", "load")):
                    break
                self.log.warning(f"[flux_painter] CLIP type {clip_type} 失败，切换重试: {wmsg[:160]}")
                on_event("切换文本编码重试…")
            if not ok_done:
                self.log.error(f"[flux_painter] 全部文本编码尝试均失败: {wmsg[:200]}")
                self._say_need(channel, f"图没画出来（原因：{str(wmsg)[:100]}），跟主人说一句，可以吐槽。")
                self._bcast(channel, {"type": "error", "text": str(wmsg)[:200]})
                return
            local_paths = connector.images_local(images)
            if not local_paths:
                self.log.error("[flux_painter] 图已生成但本地文件未找到")
                self._say_need(channel, "图出来了但找不到文件，跟主人说一句。")
                return
            final_image = local_paths[0]
            self.log.info(f"[flux_painter] 图片文件: {final_image}")

            _pro_snap = None
            if pro_on:
                _pro_snap = {
                    "base_cfg": pro_p.get("base_cfg"), "base_steps": pro_p.get("base_steps"),
                    "hires": {k: (pro_p.get("hires") or {}).get(k)
                              for k in ("enabled", "upscale_model", "scale", "resize")},
                    "usdu": {k: (pro_p.get("usdu") or {}).get(k)
                             for k in ("enabled", "denoise", "steps", "tile_width", "tile_height")},
                    "detailers": {k: {kk: (pro_p.get("detailers", {}).get(k) or {}).get(kk)
                                      for kk in ("enabled", "denoise", "detector", "steps")}
                                  for k in ("hand", "face", "eye")},
                    "sam_model": pro_p.get("sam_model"),
                }
            aok, folder, saved = self.archive.save(
                title, final_image,
                meta={"request": request, "title": title,
                      "positive": final_positive, "negative": negative,
                      "reply": reply, "canvas": canvas_key, "channel": channel,
                      "quality_mode": ("pro" if pro_on else "fast"),
                      "img2img": bool(ref_name), "ref_note": ref_note,
                      "pro_params": _pro_snap})
            self.archive.prune(self.config.keep_last_sessions)
            if not aok:
                self.log.warning("[flux_painter] 归档失败，改用源图")
                self._say_need(channel, "图出来了，但归档没成功，跟主人说一句。")
                saved = final_image
            else:
                self.log.info(f"[flux_painter] 画作已归档: {saved}")

            img_url = self._image_url(saved)
            session["final_image"] = saved
            session["reply"] = reply
            self._remember_paint(channel, request, elements, saved, session.get("owner_uid"),
                                 init_image=session.get("init_image"))

            with self._lock:
                self._running.discard(channel)
                released = True
            self.log.info(f"[flux_painter] 作画状态已释放 channel={channel}")

            _qc = session.get("qq_context") or {}
            _qq_private = bool(_qc) and str(_qc.get("message_type", "")) != "group"
            session["ok_show"] = (not self.config.review_enabled) or _qq_private
            rmode = str(getattr(self.config, "review_mode", "onnx") or "onnx").lower()
            if self.config.review_enabled and not _qq_private and rmode == "manual":
                self._say_need(channel, "画好了，等主人检查；让他看一眼、说要不要收。")
                self._review_flow(session, img_url, reply)
            elif self.config.review_enabled and not _qq_private:
                nsfw, why = self._nsfw_check(saved)
                session["nsfw"] = (nsfw, why)
                if nsfw:
                    session["ok_show"] = False
                    self.log.info(f"[flux_painter] 画板审查(onnx) 命中 -> {why}")
                    self._bcast(channel, {"type": "rejected", "text": REJECT_TEXT})
                    self._say_need(channel, "这张画得有点大胆，你先收起来，跟主人说一句，别道歉。")
                else:
                    session["ok_show"] = True
                    self.log.info(f"[flux_painter] 画板审查(onnx) 通过 -> {why}")
                    self._bcast(channel, {"type": "done", "image": img_url})
                    self._say(channel, reply)
            else:
                if _qq_private:
                    self.log.info("[flux_painter] QQ 私聊渠道，跳过审查直发")
                self._bcast(channel, {"type": "done", "image": img_url})
                self._say(channel, reply)
            if session.get("qq_context"):
                self._send_qq_image(session, saved)
            self._save_memory(uid, request, reply, session.get("memory_scope"))
        except Exception:
            self.log.exception(f"[flux_painter] 绘画异常 key={channel}")
            self._say_need(channel, "画到一半出了点岔子，跟主人说一句，别道歉。")
        finally:
            with self._lock:
                still = (not released) and channel in self._running
                if still:
                    self._running.discard(channel)
            if still:
                self.log.info(f"[flux_painter] 作画状态已释放(异常收尾) channel={channel}")
            self._clear_review(channel)

    def _remember_paint(self, channel, request, elements, final_image, owner_uid,
                        init_image=""):
        """出图成功后缓存本轮完整提示词与成品图（供改图续画）"""
        try:
            with self._last_lock:
                self._last_paint[str(channel)] = {
                    "ts": time.time(),
                    "request": str(request or ""),
                    "elements": {
                        "positive": str((elements or {}).get("positive") or ""),
                        "cinema": str((elements or {}).get("cinema") or ""),
                        "character": str((elements or {}).get("character") or ""),
                        "canvas": str((elements or {}).get("canvas") or ""),
                        "title": str((elements or {}).get("title") or ""),
                        "reply": str((elements or {}).get("reply") or ""),
                    },
                    "final_image": str(final_image or ""),
                    "init_image": str(init_image or ""),
                    "owner_uid": str(owner_uid or ""),
                }
            if init_image:
                self._persist_reference(channel, init_image)
            else:
                self._drop_reference(channel)
        except Exception:
            self.log.exception("[flux_painter] 缓存上一轮绘画失败")
