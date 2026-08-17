# 数据实体
from func.config.default_config import defaultConfig
import queue
import threading
from func.tools.singleton_mode import singleton

# 加载配置
config = defaultConfig().get_config()

@singleton
class LLmData:
    Ai_Name: str = config["AiName"]  # Ai名称
    local_llm_type: str = config["llm"]["local_llm_type"] # 模型加载方式

    # ============= LLM参数 =====================
    QuestionList = queue.Queue()  # LLM回复问题
    QuestionName = queue.Queue()
    AnswerList = queue.Queue()  # Ai回复队列
    history = []
    is_ai_ready = True  # 定义ai回复是否转换完成标志
    is_stream_out = False  # 标识LLM流式处理是同一段回复，True：正在同一段回复中 False：结束同一段流式回复
    split_flag = config["llm"]["split_flag"]
    split_str = split_flag.split("|")
    split_limit = config["llm"]["split_limit"]  # 分割的最小字符数量
    # ============================================

@singleton
class TTsData:
    SayCount = 0
    say_lock = threading.Lock()
    ReplyTextList = queue.Queue()  # Ai回复框文本队列
    is_tts_ready = True  # 定义语音是否生成完成标志
    # 选择语音
    select_sovits = config["speech"]["select"]

@singleton
class VtuberData:
    switch = config["emote"]["switch"]
    # ============= vtuber studio连接参数 =====================
    vtuber_websocket = config["emote"]["vtuber_websocket"]
    vtuber_pluginName = config["emote"]["vtuber_pluginName"]
    vtuber_pluginDeveloper = config["emote"]["vtuber_pluginDeveloper"]
    vtuber_authenticationToken = config["emote"]["vtuber_authenticationToken"]
    # ========================================

    # ============= 场景 =====================
    song_background = config["obs"]["song_background"]
    now_clothes = "便衣"
    # ========================================

    mood_num = 0  # 感情值

@singleton
class BiliDanmakuData:
    # ============= B站直播间 =====================
    room_id = config["danmaku"]["blivedm"]["room_id"]  # 输入直播间编号
    # ******** blivedm ********
    # b站直播身份验证：
    SESSDATA = config["danmaku"]["blivedm"]["sessdata"]

    # 在B站开放平台申请的开发者密钥
    ACCESS_KEY_ID = config["danmaku"]["blivedm"]["ACCESS_KEY_ID"]
    ACCESS_KEY_SECRET = config["danmaku"]["blivedm"]["ACCESS_KEY_SECRET"]
    # 在B站开放平台创建的项目ID
    APP_ID = config["danmaku"]["blivedm"]["APP_ID"]
    # 在B站主播身份码
    ROOM_OWNER_AUTH_CODE = config["danmaku"]["blivedm"]["ROOM_OWNER_AUTH_CODE"]
    # ============================================

@singleton
class CommonData:
    mode = config["app"]["mode"] # b站直播间:"blivedm"|api web:"api"
    port = config["app"]["port"]
    Ai_Name: str = config["AiName"]  # Ai名称
