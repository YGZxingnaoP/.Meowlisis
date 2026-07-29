# 数据实体
from func.config.default_config import defaultConfig
import queue
import threading
from func.tools.singleton_mode import singleton
from func.tools.file_util import FileUtil

# 加载配置
config = defaultConfig().get_config()

@singleton
class LLmData:
    Ai_Name: str = config["AiName"]  # Ai名称
    relations = config["llm"]["relations"] # 用户关系
    local_llm_type: str = config["llm"]["local_llm_type"] # 模型加载方式
    cmd = config["llm"]["cmd"]  # 触发指令
    public_sentiment_key: str = config["llm"]["public_sentiment_key"] # 舆情判断

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

    # ============= 欢迎列表 =====================
    WelcomeList = []  # welcome欢迎列表
    # ========================================

    # ============= 进入房间的欢迎语 =====================
    is_llm_welcome = config["welcome"]["is_llm_welcome"]
    welcome_not_allow = config["welcome"]["welcome_not_allow"]
    # ============================================

@singleton
class TTsData:
    SayCount = 0
    say_lock = threading.Lock()
    ReplyTextList = queue.Queue()  # Ai回复框文本队列
    is_tts_ready = True  # 定义语音是否生成完成标志
    # 选择语音
    select_vists = config["speech"]["select"]
    # 语音合成线程池
    speech_max_threads = config["speech"]["speech_max_threads"]

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

    # ============= 摇摆 =====================
    swing_motion = 2  # 1.摇摆中 2.停止摇摆
    auto_swing_lock = threading.Lock()
    # ========================================

    mood_num = 0  # 感情值

@singleton
class SingData:
    create_song_lock = threading.Lock()
    play_song_lock = threading.Lock()

    # ============= 唱歌参数 =====================
    sing_cfg = config.get('sing', {})   # 安全获取 sing 节点，默认空字典
    singUrl = sing_cfg.get('singUrl', '')   # 默认空字符串
    song_not_convert = sing_cfg.get('song_not_convert', [])
    create_song_timout = sing_cfg.get('create_song_timout', 60)

    SongQueueList = queue.Queue()
    SongMenuList = queue.Queue()
    SongNowName = {}
    is_singing = 2
    is_creating_song = 2
    sing_play_flag = 0    
    # ============================================

@singleton
class ImageData:
    # ============= 搜图参数 =====================
    SearchImgList = queue.Queue()
    is_SearchImg = 2  # 1.搜图中 2.搜图完成
    # ============================================
    httpProxies = config["searchImg"]["HttpProxies"]
    imageNum = config["searchImg"]["imageNum"]
    physical_save_folder = config["searchImg"]["physical_save_folder"]  # 绘画保存图片物理路径
    width = config["searchImg"]["width"]  # 图片宽度
    height = config["searchImg"]["height"]  # 图片高度

@singleton
class SearchData:
    httpProxies = config["searchWeb"]["HttpProxies"]
    searchNum = config["searchWeb"]["searchNum"]
    # ============= 搜文参数 =====================
    SearchTextList = queue.Queue()
    is_SearchText = 2  # 1.搜文中 2.搜文完成
    # ============================================

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