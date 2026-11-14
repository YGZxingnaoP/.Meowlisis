# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive/prompt.py
# 系统提示词构建：直接读取主项目的角色卡 / 前置词 / 价值观文件，拼成 MOSS-Live 的
# persona（人设，最多 8000 字符）与 instructions（会话指令，累计最多 16000 字符）。
#
# 刻意不 import func.* 下的构建器：那些模块依赖主程序运行状态（单例、日志文件锁、
# .temp 情绪快照等），独立测试里 import 容易把主程序日志锁住。这里只读同样的文件，
# 保持内容一致，同时让测试完全独立。
#
# 三种模式：
#   project —— 角色卡 + 前置词 + 价值观（可选），字段取法与主项目一致；
#   files   —— 只用 prompt.extra_sources 列出的项目文件；
#   inline  —— 只用 prompt.persona_inline / instructions 文本。
#
# extra_sources 可以把项目里**任意**文件塞进 persona 或 instructions，例如：
#   {"path": "工作流程解析/docs/xxx.md", "label": "项目说明", "target": "instructions"}

import json
import re
from pathlib import Path


REALTIME_RULES_HEAD = """【实时通话规则】
- 你现在和主人进行实时语音通话。"""
REALTIME_RULES_SCREEN_ON = "- 同时持续收到主人的屏幕画面（每隔一小段时间一帧）。"
REALTIME_RULES_SCREEN_OFF = "- 本次没有屏幕画面；主人让你看屏幕时，直接说明这次看不到画面。"
REALTIME_RULES_TAIL = """- 像打电话一样说话：口语、短句，一次两三句就够；不要念 Markdown、列表、编号、括号动作。
- 主人问画面里的内容时，直接根据画面回答；画面看不清、没看到，就直说并问一句。
- 需要动电脑（打开网页、切换窗口、记东西、在项目里找文件）时调用工具；结果没回来之前，不要声称已经做完。
- 工具返回后，用一句话把结果说给主人听，不要复述 JSON。
- 主人打断你时立刻停下，先听他说完再回应。
- 不要提“模型”“接口”“测试”这类词，就当是在正常聊天。"""


class PromptError(Exception):
    """提示词构建失败（文件缺失、内容为空等）"""


class PromptBundle:
    """一次会话用的提示词结果"""

    def __init__(self, persona_name: str, persona: str, instructions: str, sources: list):
        self.persona_name = persona_name
        self.persona = persona
        self.instructions = instructions
        self.sources = sources

    def summary(self) -> list:
        lines = [
            f"人设名称: {self.persona_name}",
            f"persona: {len(self.persona)} 字符",
            f"instructions: {len(self.instructions)} 字符",
        ]
        for item in self.sources:
            lines.append(f"  - {item}")
        return lines


class ProjectPromptBuilder:
    """从项目文件构建 persona / instructions"""

    PERSONALITY_FALLBACK = "活泼"
    EMOTION_FALLBACK = "平静"
    EMOTION_LABELS = {
        "neutral": "平静",
        "happy": "开心",
        "love": "喜欢",
        "sad": "难过",
        "angry": "生气",
        "sweat": "紧张",
        "blush": "害羞",
        "wordless": "沉默",
    }
    VALUE_LABELS = [
        ("0204", "主人的话"),
        ("universalism", "普世价值"),
        ("benevolence", "仁爱"),
        ("power", "权力"),
        ("achievement", "成就"),
        ("tradition", "传统"),
        ("self_direction", "自我导向"),
        ("stimulation", "刺激"),
    ]

    def __init__(self, cfg, console):
        self.cfg = cfg
        self.console = console
        self.root = cfg.project_root
        self.sources = []
        self._project_meta = self._load_project_meta()

    # ---------- 基础读取 ----------

    def _load_project_meta(self) -> dict:
        """读 config.yml 的 AiName / character_card（yaml 不可用时用正则兜底）"""
        path = self.root / "config.yml"
        if not path.exists():
            return {}
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.console.warn(f"config.yml 解析失败，改用正则兜底: {e}")
        meta = {}
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^AiName:\s*(.+)$", text, re.MULTILINE)
            if m:
                meta["AiName"] = m.group(1).strip().strip('\'"')
            m = re.search(r"card_file:\s*(\S+)", text)
            if m:
                meta["character_card"] = {"card_file": m.group(1).strip().strip('\'"')}
        except Exception:
            pass
        return meta

    def _read_json(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.console.warn(f"读取失败 {path}: {e}")
            return None

    @staticmethod
    def _display_path(path: Path, root: Path) -> str:
        """项目内文件显示相对路径，项目外显示绝对路径"""
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)

    def _latest_emotion(self) -> dict:
        """只读 .temp 里的情绪快照（不写），用于挑当前性格/情绪"""
        for name in ("latest_emotion.json", "latest_emotion_online.json"):
            path = self.root / ".temp" / name
            if path.exists():
                data = self._read_json(path)
                if isinstance(data, dict):
                    return data
        return {}

    # ---------- 角色卡 ----------

    def _card_path(self) -> Path:
        card_file = str(self.cfg.prompt.get("card_file") or "").strip()
        if not card_file:
            cc = self._project_meta.get("character_card") if isinstance(self._project_meta, dict) else {}
            card_file = str((cc or {}).get("card_file") or "prompt").strip()
        if not card_file.endswith(".json"):
            card_file += ".json"
        return self.root / "character" / "info" / "character_prompt" / card_file

    def _pick_card(self) -> dict:
        path = self._card_path()
        data = self._read_json(path)
        if not isinstance(data, dict):
            raise PromptError(f"角色卡读取失败: {path}")
        chars = data.get("characters") or []
        if isinstance(chars, list) and chars:
            info = chars[0]
        elif isinstance(data.get("name"), str):
            info = data
        else:
            raise PromptError(f"角色卡没有可用内容: {path}")
        self.sources.append(f"角色卡 {self._display_path(path, self.root)}")
        return info

    def _build_card(self, info: dict) -> tuple:
        """按主项目 character_prompt.build 的字段顺序输出 markdown"""
        name = str(info.get("name") or self._project_meta.get("AiName") or "").strip()
        lines = [f"# {name}" if name else "# 角色卡"]

        nickname = str(info.get("nickname") or "").strip()
        if nickname:
            lines.append(f"- 昵称：{nickname}")

        personalities = info.get("personality") or {}
        current = self._latest_emotion()
        p_name = str(current.get("personality") or "").strip()
        personality_text = ""
        if isinstance(personalities, dict) and personalities:
            if p_name and p_name in personalities:
                personality_text = str(personalities[p_name] or "")
            else:
                personality_text = str(list(personalities.values())[0] or "")
        elif isinstance(personalities, str):
            personality_text = personalities
        if personality_text:
            lines.append(f"- 角色性格：{personality_text}")

        mbti_behavior = str(info.get("mbti_behavior") or "").strip()
        if mbti_behavior:
            lines.append(mbti_behavior)

        setting = info.get("setting") or {}
        if isinstance(setting, dict):
            for key, value in setting.items():
                if value:
                    lines.append(f"- 设定（{key}）：{value}")
        elif setting:
            lines.append(f"- 角色设定：{setting}")

        emotion_raw = str(current.get("emotion") or "").strip()
        emotion = self.EMOTION_LABELS.get(emotion_raw.lower(), emotion_raw) or self.EMOTION_FALLBACK
        lines.append(f"- 现在的情绪：{emotion}")

        appearance = str(info.get("appearance") or "").strip()
        if appearance:
            lines.append(f"- 角色外貌：{appearance}")

        lines.append("## 以下只是个人信息喵，禁止主动强调，只有话题强相关才提及哦")

        fields = [
            ("角色生日", info.get("birthday", "")),
            ("角色身份证号", info.get("id_card", "")),
            ("QQ号", info.get("qq", "")),
            ("手机号", info.get("phone", "")),
        ]
        if not mbti_behavior:
            fields.append(("MBTI", info.get("mbti", "")))
        fields += [
            ("最喜欢的东西", info.get("favorite", "")),
            ("角色爱好", info.get("hobbies", "")),
            ("讨厌的东西", info.get("dislikes", "")),
            ("人际关系", info.get("relationships", "")),
        ]
        for label, value in fields:
            if value:
                lines.append(f"- {label}：{value}")
        return name, "\n".join(lines)

    # ---------- 价值观 ----------

    def _build_values(self, ai_name: str) -> str:
        path = self.root / "character" / "info" / "values" / "latest.json"
        data = self._read_json(path)
        if not isinstance(data, dict) or not data:
            return ""
        self.sources.append(f"价值观 {self._display_path(path, self.root)}")
        lines = [f"# {ai_name}铭记在心"]
        for key, label in self.VALUE_LABELS:
            value = str(data.get(key, "") or "").strip()
            if value:
                lines.append(f"- {label}：{value}")
        return "\n".join(lines) if len(lines) > 1 else ""

    # ---------- 前置词/后置词 ----------

    def _read_front(self) -> dict:
        path = self.root / "character" / "front" / "prompt.json"
        data = self._read_json(path)
        return data if isinstance(data, dict) else {}

    # ---------- 额外来源 ----------

    def _read_source(self, src: dict) -> str:
        """读取一个 extra_source 的文本；JSON 可按 json_key 取子字段"""
        raw_path = str(src.get("path") or "").strip()
        if not raw_path:
            return ""
        path = self.cfg.project_path(raw_path)
        if not path.exists():
            msg = f"额外提示词来源不存在: {path}"
            if src.get("required"):
                raise PromptError(msg)
            self.console.warn(msg)
            return ""
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            self.console.warn(f"额外提示词读取失败 {path}: {e}")
            return ""
        json_key = str(src.get("json_key") or "").strip()
        if json_key:
            try:
                obj = json.loads(text)
            except Exception as e:
                self.console.warn(f"额外提示词 JSON 解析失败 {path}: {e}")
                return ""
            cur = obj
            for part in json_key.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    self.console.warn(f"额外提示词缺少键 {json_key}（{path}）")
                    return ""
            if isinstance(cur, (dict, list)):
                text = json.dumps(cur, ensure_ascii=False, indent=2)
            else:
                text = str(cur)
        label = str(src.get("label") or path.stem).strip()
        self.sources.append(f"额外来源 {self._display_path(path, self.root)} → {src.get('target', 'persona')}")
        return f"# {label}\n{text.strip()}"

    # ---------- 组装 ----------

    def build(self) -> PromptBundle:
        mode = str(self.cfg.prompt.get("mode") or "project")
        if mode == "inline":
            return self._build_inline()

        persona_parts = []
        instruction_parts = []
        persona_name = str(self.cfg.prompt.get("persona_name") or "").strip()
        ai_name = str(self._project_meta.get("AiName") or "").strip()

        if mode == "project":
            info = self._pick_card()
            card_name, card_text = self._build_card(info)
            persona_name = persona_name or card_name or ai_name
            persona_parts.append(card_text)

            if self.cfg.prompt.get("include_values"):
                values = self._build_values(ai_name or card_name)
                if values:
                    persona_parts.append(values)

            front = self._read_front()
            display_name = str(self.cfg.prompt.get("display_name") or "主人")
            if self.cfg.prompt.get("include_front_prompt"):
                front_text = str(front.get("prompt") or "").strip()
                if front_text:
                    instruction_parts.append(front_text.replace("{display_name(uid)}", display_name))
                    self.sources.append("前置词 character/front/prompt.json#prompt")
                front_active = str(front.get("prompt_active") or "").strip()
                if front_active and self.cfg.prompt.get("include_active_prompt"):
                    instruction_parts.append(front_active)
                    self.sources.append("前置词 character/front/prompt.json#prompt_active")
            post = str(front.get("post_prompt") or "").strip()
            if post:
                persona_parts.append(post.replace("{display_name(uid)}", display_name))
                self.sources.append("后置词 character/front/prompt.json#post_prompt")

        elif mode == "files":
            if not (self.cfg.prompt.get("extra_sources") or []):
                raise PromptError("prompt.mode=files 时 prompt.extra_sources 不能为空")

        for src in self.cfg.prompt.get("extra_sources") or []:
            if not isinstance(src, dict):
                continue
            text = self._read_source(src)
            if not text:
                continue
            target = str(src.get("target") or "persona")
            if target == "instructions":
                instruction_parts.append(text)
            else:
                persona_parts.append(text)

        persona_name = persona_name or ai_name or "喵呜"
        persona = "\n\n".join(p for p in persona_parts if p.strip())
        if not persona.strip():
            persona = f"你是{persona_name}，以这个身份和主人进行实时语音聊天。"

        instruction_parts.append(self._realtime_rules())
        extra_instr = str(self.cfg.prompt.get("instructions") or "").strip()
        if extra_instr:
            instruction_parts.append(extra_instr)
        for item in self.cfg.prompt.get("instructions_files") or []:
            path = self.cfg.project_path(item)
            if not path.exists():
                self.console.warn(f"instructions_files 不存在: {path}")
                continue
            try:
                instruction_parts.append(path.read_text(encoding="utf-8").strip())
                self.sources.append(f"指令文件 {self._display_path(path, self.root)}")
            except Exception as e:
                self.console.warn(f"指令文件读取失败 {path}: {e}")

        instructions = "\n\n".join(p for p in instruction_parts if p and p.strip())
        return self._clamp(PromptBundle(persona_name, persona, instructions, self.sources))

    def _build_inline(self) -> PromptBundle:
        persona_name = str(self.cfg.prompt.get("persona_name") or "").strip() or "喵呜"
        persona = str(self.cfg.prompt.get("persona_inline") or "").strip()
        if not persona:
            persona = f"你是{persona_name}，一只认真、有主见的猫猫，正在用语音和主人聊天。"
        instructions = str(self.cfg.prompt.get("instructions") or "").strip()
        instructions = "\n\n".join(p for p in (self._realtime_rules(), instructions) if p)
        return self._clamp(PromptBundle(persona_name, persona, instructions, ["inline"]))

    def _realtime_rules(self) -> str:
        """按本次是否推屏幕，生成对应的实时通话规则"""
        screen_line = (REALTIME_RULES_SCREEN_ON
                       if self.cfg.screen.get("enabled") else REALTIME_RULES_SCREEN_OFF)
        return "\n".join(p for p in (REALTIME_RULES_HEAD, screen_line, REALTIME_RULES_TAIL) if p)

    # ---------- 长度限制 ----------

    def _clamp(self, bundle: PromptBundle) -> PromptBundle:
        max_persona = int(self.cfg.prompt.get("max_persona_chars") or 8000)
        max_instr = int(self.cfg.prompt.get("max_instructions_chars") or 16000)
        if len(bundle.persona) > max_persona:
            self.console.warn(
                f"persona 长度 {len(bundle.persona)} 超过上限 {max_persona}，已截断。"
                "可把部分内容挪到 prompt.instructions 或 extra_sources（target=instructions）。"
            )
            bundle.persona = self._cut(bundle.persona, max_persona)
        if len(bundle.instructions) > max_instr:
            self.console.warn(
                f"instructions 长度 {len(bundle.instructions)} 超过上限 {max_instr}，已截断。"
            )
            bundle.instructions = self._cut(bundle.instructions, max_instr)
        return bundle

    @staticmethod
    def _cut(text: str, limit: int) -> str:
        """尽量在换行处截断，避免切碎句子"""
        head = text[:limit]
        pos = head.rfind("\n")
        if pos > limit * 0.6:
            head = head[:pos]
        return head.rstrip() + "\n（内容过长，已截断）"
