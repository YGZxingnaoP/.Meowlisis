import os
import threading

from func.toolbox.plugins.sdk import InterfaceTool, ToolboxPlugin, TriggerTool

from .config import DocWriterConfig
from .agent import DocAgent


def _signal(path):
    """构造完成信号"""
    return (f"【文档助手】任务完成：文件《{os.path.basename(path)}》已生成并放入猫猫文件柜。"
            "请用你的角色口吻告诉用户已经做好了，不用展开文件内容。")


def _complete_voice(ctx, username, path, short_memory):
    """语音链路：完成信号交给主链路 LLM 生成回复"""
    from func.pipeline.toolbox_llm import ToolboxLLMBridge
    ToolboxLLMBridge().send_to_llm(_signal(path), username or "用户", source="toolbox")


def _complete_qq(ctx, qq_context, username, path, short_memory):
    """QQ 链路：完成信号交给 QQ LLM 生成回复，并发送文件"""
    core = ctx.napcat()
    target = str(qq_context.get("target_id") or qq_context.get("user_id") or "")
    if not target:
        return
    signal = _signal(path)
    if str(qq_context.get("message_type", "")) == "group":
        from func.pipeline.toolbox_llm import NapcatGroupLLMBridge
        group_name = str(qq_context.get("group_name") or target)
        NapcatGroupLLMBridge().reply(
            username or "用户", target, group_name, signal, short_memory or [], "",
            on_segment=lambda seg: core.send_group_text(target, seg))
        core.send_group_file(target, path)
    else:
        from func.pipeline.toolbox_llm import NapcatLLMBridge
        NapcatLLMBridge().send_to_llm(
            username or "用户", target, signal, short_memory or [],
            on_segment=lambda seg: core.send_private_text(target, seg))
        core.call_action_sync("upload_private_file",
                              {"user_id": int(target), "file": path,
                               "name": os.path.basename(path)})


def _resolve_args(arguments):
    """整理工具参数"""
    arguments = arguments or {}
    request = str(arguments.get("request") or "").strip()
    topic = str(arguments.get("topic") or "").strip()
    doc_type = str(arguments.get("doc_type") or "").strip().lower()
    fmt = str(arguments.get("format") or "").strip().lower()
    text = f"{request} {topic}"
    if doc_type not in ("thesis", "doc", "ppt"):
        low = text.lower()
        if "ppt" in fmt or "ppt" in low or "幻灯" in text or "演示" in text:
            doc_type = "ppt"
        elif "论文" in text:
            doc_type = "thesis"
        else:
            doc_type = "doc"
    if fmt not in ("docx", "pptx"):
        fmt = "pptx" if doc_type == "ppt" else "docx"
    return request, doc_type, fmt


def _run_job(request, doc_type, fmt, ctx, channel, qq_context, user_ctx):
    """后台执行任务并冒出完成信号"""
    try:
        config = DocWriterConfig(ctx.config)
        result = DocAgent(ctx, config).run(request, doc_type, fmt,
                                           (user_ctx or {}).get("short_memory") or [])
        path = (result or {}).get("path")
        if not path:
            reason = (result or {}).get("reason") or "未知原因"
            ctx.log.error(f"文档助手任务失败：{reason}")
            _report_fail(ctx, channel, qq_context, f"文档助手没写成：{reason}")
            return
        username = (user_ctx or {}).get("username")
        short_memory = (user_ctx or {}).get("short_memory")
        if channel == "qq":
            _complete_qq(ctx, qq_context, username, path, short_memory)
        else:
            _complete_voice(ctx, username, path, short_memory)
    except Exception:
        ctx.log.exception("文档助手任务失败")


def _report_fail(ctx, channel, qq_context, text):
    """失败播报：语音/弹幕走 TTS，QQ 走文本"""
    if channel == "qq" and qq_context:
        try:
            core = ctx.napcat()
            target = str(qq_context.get("target_id") or qq_context.get("user_id") or "")
            if str(qq_context.get("message_type", "")) == "group":
                core.send_group_text(target, text)
            else:
                core.send_private_text(target, text)
        except Exception:
            ctx.log.exception("文档助手失败提示发送失败")
        return
    try:
        ctx.tts().send_stream(text, source="toolbox_docwriter")
    except Exception:
        ctx.log.exception("文档助手失败提示播报失败")


def _start(arguments, ctx, channel, qq_context=None, user_ctx=None):
    """启动后台生成任务"""
    request, doc_type, fmt = _resolve_args(arguments)
    threading.Thread(target=_run_job,
                     args=(request, doc_type, fmt, ctx, channel, qq_context, user_ctx or {}),
                     daemon=True).start()


class WriteDocumentTool(TriggerTool):
    name = "write_document"
    description = (
        "撰写论文、Word 文档或制作 PPT 演示文稿：会联网检索资料、处理数据出表格与图表、"
        "按需配图（网络搜图 / AI 生图），并用统一设计系统排版输出成品文件。"
        "【仅在用户明确要求写论文/写Word文档/写文档/写报告/写方案/做PPT/做幻灯片/演示文稿时调用】"
        "【严格禁止】普通闲聊、问答、查天气新闻、搜索单个词条、画画、发消息等一律不调用。"
        "调用后立即返回，无需等待。"
    )
    parameters = {
        "request": {"type": "string", "description": "用户原话需求"},
        "topic": {"type": "string", "description": "主题或标题，可省略"},
        "doc_type": {"type": "string", "enum": ["thesis", "doc", "ppt"], "description": "类型"},
        "format": {"type": "string", "enum": ["docx", "pptx"], "description": "产出格式"},
    }
    required = ["request"]
    prompt_hint = ("- 用户要求写论文/写Word文档/写报告/写方案/做PPT/幻灯片/演示文稿 → "
                   "调用 write_document。")

    def handle(self, arguments, ctx):
        """语音链路：后台生成，完成后交给 LLM 出话"""
        _start(arguments, ctx, "voice", user_ctx=dict(self.context))
        return "已开始生成"

    def handle_qq(self, arguments, qq_context, ctx):
        """QQ 链路：后台生成，完成后交给 QQ LLM 出话并发文件"""
        _start(arguments, ctx, "qq", qq_context=qq_context, user_ctx=dict(self.context))
        return "已开始生成"


class DocWriterProbeTool(InterfaceTool):
    """连通性自检（不进 LLM）：查看 LLM / 生图 / 搜图 三个端口状态。"""

    name = "docwriter_probe"
    description = "文档助手端口自检：LLM、生图（硅基流动）、搜图是否可用"

    def call(self, ctx, **kwargs):
        """调用方式：PluginManager().call_interface("docwriter_probe", deep=True)"""
        from .config import DocWriterConfig
        from .imagegen import ImageGen
        from .imagesearch import ImageSearch
        from .port import DocLLM

        config = DocWriterConfig(ctx.config)
        llm = DocLLM(config)
        out = {
            "llm": {"ok": bool(llm.available()), "model": config.model, "error": llm.last_error},
            "image": {"enabled": config.images_enabled, "source": config.image_source,
                      "model": config.image.get("model")},
            "output_dir": config.output_dir,
            "theme": config.theme,
        }
        if kwargs.get("deep"):
            ok, msg = ImageGen(config).probe()
            out["image"]["probe"] = {"ok": ok, "msg": msg}
            hits = ImageSearch(config).search(str(kwargs.get("query") or "风景"), n=3)
            out["search_image"] = {"ok": bool(hits), "count": len(hits)}
        return out


class Plugin(ToolboxPlugin):
    id = "docwriter"
    title = "文档助手"
    version = "2.0.0"
    default_enabled = True

    def trigger_tools(self):
        """返回触发型工具列表"""
        return [WriteDocumentTool()]

    def interface_tools(self):
        """返回接口型工具列表（供程序内自检调用）"""
        return [DocWriterProbeTool()]

    def prompt_hint(self):
        """返回意图分析引导文案"""
        return ("- 文档助手：用户要求写论文/写Word文档/写报告/写方案/做PPT/幻灯片/演示文稿 → "
                "调用 write_document。")

    def setup(self, ctx):
        """插件初始化"""
        self.log = ctx.log


PLUGIN = Plugin()
