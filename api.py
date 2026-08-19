# 吟美Api web
import os
import sys
import time
import uuid
import asyncio
import subprocess
from threading import Thread
from flask import Flask, jsonify, request
from flask_apscheduler import APScheduler

from func.toolbox.obs.browser_subtitle_server import get_subtitle_server
from func.log.default_log import DefaultLog
from func.toolbox.vtuber.emote_oper import EmoteOper
from func.tts.tts_core import TTsCore
from func.llm.llm_core import LLmCore
from func.llm_active.active_core import AutoActiveCore
from func.catbrain.prompt_builder import MeowPromptBuilder
from func.pipeline.system_prompt import SystemPromptBridge
from func.pipeline.config_reader import ConfigReader
from func.sensevoice.sensevoice_core import SenseVoiceCore

from func.toolbox.danmaku.blivedm.blivedm_core import BlivedmCore
from func.config.app_config import AppConfig
from func.toolbox.vtuber.state import VtuberState
from func.toolbox.minecraft.logreader import MinecraftLogReader

log = DefaultLog().getLogger()


appConfig = AppConfig()  #基础数据
Ai_Name = appConfig.ai_name  # Ai名称


log.info("======================================")
log.warning(
    """                                                                                                                                      
    /\_/\                                                                    
   （o.o ）                                          
    > ^ <
    喵呜~~                                             
"""
)
log.info(f"开始启动人工智能【{Ai_Name}】！")


# 1.b站直播间 2.api web
mode = appConfig.mode

# ============= B站直播间 =====================
blivedmCore = BlivedmCore()
# ============================================

# ============= api web =====================
app = Flask(__name__, template_folder="./html")
sched1 = APScheduler()
sched1.init_app(app)
# ============================================

# ============= LLM参数 =====================
llmCore = LLmCore()  # llm核心
get_subtitle_server()
# ============================================

# ============= CatBrain 角色灵魂 =====================
catbrain_builder = MeowPromptBuilder()
SystemPromptBridge().register_builder(catbrain_builder)
# 价值观 12 小时累计计时器（中断后从 .temp 恢复继续累计）
from func.catbrain.CatValues.values_timer import MeowValuesTimer
MeowValuesTimer().start()
# ============================================

# ============= 角色主动回复 =====================
active_core = AutoActiveCore()  # 空闲主动回复核心（计时器启动后立即开始计时）
# ============================================

# ============= 语音合成 =====================
ttsCore = TTsCore() # 语音核心
# ============================================

# ============= vtuber操作 =====================
vtuberState = VtuberState()  # vtuber运行态
emoteOper = EmoteOper() # 表情初始化
# ========================================

log.info("--------------------")
log.info("AI虚拟主播-启动成功！")
log.info("--------------------")
log.info("======================================")

# http说话复读【postman调用】
@app.route("/say", methods=["POST"])
def http_say():
    text = request.data.decode("utf-8")
    tts_say_thread = Thread(target=ttsCore.tts_say, args=(text,))
    tts_say_thread.start()
    return jsonify({"status": "成功"})

# http人物表情输出
@app.route("/emote", methods=["POST"])
def http_emote():
    data = request.json
    text = data["text"]
    emote_thread1 = Thread(target=emoteOper.emote_ws, args=(1, 0.2, text))
    emote_thread1.start()
    return jsonify({"status": "成功"})


# http启动 NapCat（GUI 启动球调用）
@app.route("/api/start_napcat", methods=["POST"])
def start_napcat():
    try:
        napcat_dir = os.path.join(".NapCat", "NapCat.Shell")
        start_bat = os.path.join(napcat_dir, "napcat.quick.bat")
        if os.path.exists(start_bat):
            if sys.platform == "win32":
                subprocess.Popen([start_bat], cwd=napcat_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([start_bat], cwd=napcat_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return jsonify({'status': 'error', 'message': 'napcat.quick.bat not found'}), 400
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# http接口处理【postman接口调用】
@app.route("/msg", methods=["POST"])
def input_msg():
    data = request.json
    query = data["msg"]  # 获取弹幕内容
    user_name = data["username"]  # 获取用户昵称
    traceid = str(uuid.uuid4())
    llmCore.msg_deal(traceid, query, user_name)
    return jsonify({"status": "成功"})


# 聊天回复弹框处理【html回复框回调】
@app.route("/chatreply", methods=["GET"])
def chatreply():
    CallBackForTest = request.args.get("CallBack")
    jsonStr = ttsCore.http_chatreply()
    if CallBackForTest is not None:
        jsonStr = CallBackForTest + jsonStr
    return jsonStr

# 聊天【用户funasr语音对话】
@app.route("/chat", methods=["POST", "GET"])
def chat():
    CallBackForTest = request.args.get("CallBack")
    username = request.args.get("username")
    text = request.args.get("text")
    # =========处理消息开始========
    status = "成功"
    traceid = str(uuid.uuid4())
    if text is None:
        jsonStr = "({\"traceid\": \"" + traceid + "\",\"status\": \"值为空\",\"content\": \"" + text + "\"})"
        return jsonStr
    # 消息处理
    llmCore.msg_deal(traceid, text, username)
    jsonStr = "({\"traceid\": \"" + traceid + "\",\"status\": \"" + status + "\",\"content\": \"" + text + "\"})"
    # =========end========
    if CallBackForTest is not None:
        jsonStr = CallBackForTest + jsonStr
    return jsonStr


def main():
    # 初始化衣服
    emoteOper.emote_ws(1, 0.2, "初始化")  # 解除当前衣服
    emoteOper.emote_ws(1, 0.2, "便衣")  # 穿上新衣服
    vtuberState.now_clothes = "便衣"

    # 获取全局配置
    config = ConfigReader().get()

    sensevoice_config = config.get('sensevoice', {})

    # 优先使用 SenseVoice（如果启用）
    if sensevoice_config.get('enabled', False):
        from func.pipeline.sensevoice_llm import SenseVoiceLLMBridge
        sensevoice_bridge = SenseVoiceLLMBridge()
        asr_core = SenseVoiceCore(callback=sensevoice_bridge.send_to_llm)
        asr_core.start()
        log.info("已启用 SenseVoice 语音识别后台线程（高精度流式+声纹）")

    # Minecraft 日志读取
    mc_reader = MinecraftLogReader()
    mc_reader.load_config()
    mc_reader.start()
    log.info("已启用 Minecraft 日志读取")

    # NapCat 客户端（正向 WS 连接 QQ）
    from func.toolbox.napcat.napcat_core import TBNapCatCore
    napcat_core = TBNapCatCore()
    napcat_core.start()

    # 注册退出清理
    import atexit
    atexit.register(mc_reader.stop)
    atexit.register(napcat_core.stop)

    if "blivedm" in mode or "api" in mode:
        # LLM回复
        sched1.add_job(func=llmCore.check_answer, trigger="interval", seconds=1, id="answer", max_instances=100)
        # 角色主动回复计时检测
        sched1.add_job(func=active_core.check_active, trigger="interval", seconds=1, id="active", max_instances=1)
        # tts语音合成
        sched1.add_job(func=ttsCore.check_tts, trigger="interval", seconds=1, id="tts", max_instances=1000)
        sched1.start()

        # 开启web
        app_thread = Thread(target=apprun)
        app_thread.start()

    # 可以监听多个弹幕平台
    if "blivedm" in mode:
        asyncio.run(blivedmCore.listen_blivedm_task())
    else:
        while True:
            time.sleep(10)
    log.info("结束")


# http服务
def apprun():
    # 禁止输出日志
    app.logger.disabled = True
    # 启动web应用
    app.run(host="0.0.0.0", port=appConfig.port)

if __name__ == "__main__":
    main()
