/**
 * Orbit 可调参数 + 数据表（从 orbit.js 拆出，纯数据，不含任何逻辑）
 * 需在 js/orbit.js 之前加载。
 */
const OrbitData = {
    CFG: {
        // 卡尺寸写在 css/cards.css（.slot 136×188），下面所有倍率都从它出发
        //
        // ==================== 旋转几何 ====================
        // 完整模型见 js/orbit/rotation.js 顶部注释，这里只放数字。三句话版本：
        //   卡片先在正圆上均匀分布，再把纵向压扁 FLAT 倍 → 屏幕上的椭圆
        //       x = R · sin(a)        y = R · FLAT · cos(a)
        //
        //   ★ 铁律 1：R 是常量。运行时任何人都不许重算、不许按视口夹取、
        //             不许为了"适配小窗口 / 让半径变大"去改它。
        //             小窗口塞不下就【切边】，不做任何等比缩放：
        //             _applyZoom() 已删除，_lockRadius() 会盯住轨道元素，
        //             谁给它们写 transform 就当场抹掉。
        //   ★ 铁律 2：扁平只由 FLAT 一个系数控制，不要再引入第二个"半径"。
        //   ★ 半径(R) 与 卡片尺寸(SCALE_*) 是两个独立旋钮，永远不要互相抵消。
        //
        //   （历史事故：曾经用 RX/RY 两个独立半径表达扁平，还有 _fitRadius() 在 init
        //     按视口高度重算——结果"调半径"同时改了形状，窗口一变半径就收缩，
        //     这个 bug 反复修不掉。别再走回头路。）
        // 三个环是【各自独立】的常量，互不推导。挤不挤只跟"周长 ÷ 卡宽"有关：
        //   圈上张数 n、椭圆半轴 (a, b=R·FLAT)，周长 ≈ π[3(a+b) − √((3a+b)(a+3b))]
        //   平均间距 = 周长 / n，最好 ≥ 卡宽（最近那张 196），否则一圈全叠住。
        // 现在这三条都是"扁而宽"：宽度（横轴）拉大，高度（纵轴 = R×FLAT）压小。
        //   横向半轴 = R / LR / TR ；纵向半轴 = 它 × FLAT 系数。
        //   调形状只动这两个：要更宽 → 加大半轴；要更扁 → 减小压扁系数。
        R: 620,                    // 配置轨半径（常量）      → 椭圆 1240 × 422，13 张
        FLAT: 0.34,                // 垂直压扁系数（约 3:1）
        LR: 380,                   // 启动内环半径（常量）    → 椭圆 760 × 274，9 张
        LFLAT: 0.36,
        TR: 460,                   // 工具箱环半径（常量）    → 椭圆 920 × 386，11 张
                                   //   宽度上限被面板卡住：面板 1180px - 边框20 - 内边距40 = 1120，
                                   //   .toolbox-system 就是 1120 宽 → 半轴最多 1120/2 − 卡半宽 98 = 462。
                                   //   想再宽得先加宽工具箱面板。原先只有 215 → 430×215，
                                   //   间距 ~95px 对 196px 的卡 = 十一条全糊在一起。
        TFLAT: 0.42,
        RING_DY_VH: 0.02,          // 配置层下移量，必须 = orbit.css 里 .orbit-outer 的 2vh，改一个就得改另一个
        LAUNCH_UP_K: 1.0,          // 启动簇整体上移量 = LRY × 这个系数
                                   //   LRY = LR × LFLAT = 165，即启动轨最低那张正好落在配置轨中心线，
                                   //   于是启动卡整体都高于配置卡（LRY × 1.0）。想再高就加大这个数。

        // ==================== 空间模型（动方向之前先把这段读完）====================
        //
        // ★★ 模型：俯视圆盘 ★★
        //    观察者从【上方】斜看一个平放的圆盘：
        //      屏幕【下方】那张  = 离观察者【最近】= 最大 / 最亮 / 压在最上面
        //      屏幕【上方】那张  = 最【远】        = 最小 / 最暗 / 压在最下面
        //      屏幕【左右】两侧  = 中距            = 中间大小
        //    椭圆不是另一个半径，就是"圆盘被斜看压扁"的结果（R 恒定的正圆 + FLAT 压扁）。
        //    所以下面 a = 0° 那张落在屏幕正下方 = 最近那张。
        //
        // 屏幕坐标系（CSS transform）：x 向右增大，y 向下增大。
        //
        //   a     = 卡心角度 = el._ang + rotation
        //   x     = R · sin(a)          y = R · FLAT · cos(a)     ← 位置：只由 R / FLAT 决定
        //   depth = cos(a) · DEPTH_DIR                            ← 深度：决定大小 / 明暗 / 层级
        //
        //   把 a 的实际取值代进去，对照屏幕：
        //     a = 0°     →  x = 0     y = +R·FLAT    卡在【屏幕正下方】
        //     a = ±90°   →  x = ±R    y = 0          卡在【屏幕最左 / 最右】
        //     a = 180°   →  x = 0     y = −R·FLAT    卡在【屏幕正上方】
        //
        //   DEPTH_DIR = 1（当前值）对应的深度表：
        //     屏幕正下方   depth = +1  → 缩放最大、最亮、z 最高、带 .front（"最前面那张"）
        //     屏幕最左/最右 depth =  0  → 居中值
        //     屏幕正上方   depth = −1  → 缩放最小、最暗、z 最低
        //
        //   ★★ 这个方向是用户确认过的（他称之为"远大近小"）：下方那张最大、上方最小。
        //      不要再凭"感觉反了"去翻转它。要翻只有 DEPTH_DIR 一个开关，
        //      而且它【只】改 depth，不改坐标 —— 椭圆形状、半径、卡心位置一律不受影响。
        //
        //   ⚠️ 位置那两个分量永远用 cos(a) 本身，不要乘 DEPTH_DIR，
        //      否则整个椭圆会被翻过来（形状就变了，不是"翻方向"）。
        //

        // ==================== 卡片尺寸（就是这条方向轴上的大小差）====================
        //
        //   ① 轨道半径 = 卡心到中心的距离 → 只由 R / FLAT 决定，运行时恒定不动
        //   ② 卡片尺寸 = 卡片自己多大     → 只由 SCALE_* 决定，随 depth 变化
        //
        //   公式：sc = 基准倍率 × (SCALE_MIN + 深度归一 × SCALE_SPAN)
        //         深度归一 = (depth + 1) / 2 ∈ [0,1]；0 = 最远（depth −1），1 = 最近（depth +1）
        //
        //   当前值下每张卡的实际大小（.slot 基准 136 × 188）：
        //     配置卡 / 工具箱卡   最远 sc = 1.20 × 0.72 = 0.864 → 118 × 162
        //                         最近 sc = 1.20 × 1.20 = 1.440 → 196 × 271
        //     启动卡              最远 sc = 1.00 × 0.70 = 0.700 →  95 × 132
        //                         最近 sc = 1.00 × 1.04 = 1.040 → 141 × 196
        //     → 启动卡在任何深度都比配置卡小。
        //
        //   ⚠️ 曾经把 SCALE_SPAN 改成 0（想做成"尺寸恒定"），被用户否掉了：
        //      这个大小差就是他要的"远大近小"，不许再抹平。
        //   ⚠️ "改半径"和"改尺寸"是两件事：碰 R / FLAT 的那次改动，绝不顺手动 SCALE_*。
        // ---------- 近大远小（视差）就靠这 6 个数，其余一律不要碰 ----------
        // sc = 基准倍率 × (SCALE_MIN + 深度归一 × SCALE_SPAN)
        //      深度归一 = (depth + 1) / 2 ∈ [0,1]，depth = cos(a) × DEPTH_DIR
        //      基准尺寸 = css/cards.css 的 .slot 136 × 188
        // 当前值（用户确认过是对的）：
        //   配置卡/工具箱卡  最远 1.20×0.72 = 0.864 → 118×162（屏幕上方，最暗、z 最低）
        //                    最近 1.20×1.20 = 1.440 → 196×271（屏幕下方，最亮、z 最高、.front）
        //   启动卡           0.700 → 95×132  ~  1.040 → 141×196（每个深度都比配置卡小）
        // 怎么调：
        //   整体变大变小          → 只动 CONFIG_SCALE / LAUNCH_SCALE
        //   视差更强（小得更小）  → 降 SCALE_MIN，同时把 SPAN 加到 SPAN+(旧MIN−新MIN)，最近那张才不变大
        //   视差更弱              → SPAN 往 0 收；收到 0 = 一圈同尺寸（参考实现就是 0，但本机不要）
        //   启动卡要更小/更大     → 只动 LAUNCH_SCALE
        // ⚠️ 安全上限：最近那张的【高度】别超过纵向半轴 R×FLAT 的 ~0.9 倍，
        //    否则近端那几张会糊到中心去：188 × CONFIG_SCALE × (SCALE_MIN+SCALE_SPAN) ≤ 0.9 × R×FLAT
        //    （当前 271 ≤ 0.9×250 = 225 ✗ 已经超了！要留余量就把 CONFIG_SCALE 降到 ~1.05）
        // ⚠️ 尺寸（这 6 个数）和半径（R/FLAT/LR/TR）是两套旋钮，永远不要互相抵消。
        CONFIG_SCALE: 1.20,        // 配置卡 / 工具箱卡基准倍率
        SCALE_MIN: 0.72,           // 最远那张的倍率
        SCALE_SPAN: 0.48,          // 最远 → 最近，加多少
        LAUNCH_SCALE: 1.00,        // 启动卡基准倍率
        L_SCALE_MIN: 0.70,
        L_SCALE_SPAN: 0.34,
        LAUNCH_Z_BASE: 200,        // 启动卡的层级基准：整层抬到 205~305，
                                   //   永远高于配置卡的 5~105 → "启动卡压在配置卡之上"
                                   // 中心球：配置态 z=55（= 半径中心的深度），
                                   //   启动器展开时 255（= LAUNCH_Z_BASE + 55），跟启动卡交错
        SUB_STAGGER: 0.03,         // 子卡扇展错峰：第 i 张比前一张晚这么多秒飞出（0 = 同时飞出）
                                   //   配合 css/cards.css 里 .sub 的 0.36s 过渡用
        DEPTH_DIR: 1,              // 深度方向：1 = 屏幕下方那张算"近"（当前，用户已确认）
                                   //           -1 = 屏幕上方那张算"近"（只翻大小/明暗/层级，不翻位置）

        // ==================== 交互时序（不要动）====================
        LAUNCH_STAGGER: 45,        // 展开时每张启动卡的错峰延迟（ms）→ 一张张弹出去
        FLIP_DELAY: 160,           // 翻牌到打开面板的间隔（ms）

        // ==================== 子卡扇形（交互，不要动）====================
        FOCUS_SCALE: 1.62,         // 父卡摊开子卡时放大到的倍数
        PARENT_DY: -52,            // 摊开时父卡上移多少（子卡 270 高，父卡不下移就顶不出空间）
                                   // 子卡的【动画起点】另算：是"被点中那张卡"原来的位置
                                   // （屏幕正下方），见 deck.js _spread 的 d.subOrigin
        KID_SPACING: 224,          // 子卡横向间距（子卡 198 宽、倾斜 7° 后包围盒 230）
        KID_DY0: 232,              // 子卡基准下移距离（父卡底边在 -52+136=84，倾斜后子卡上沿 86）
        KID_DY_SPAN: 18,           // 每远一档再多下移（小窗口也不至于切到最外面那张）
        KID_ROT: 7,                // 子卡倾斜角（度）
        KID_HALF: 155,             // 子卡 198×270 倾斜后包围盒半高（扇形自适应要用，见 _fanSpan）

        // 工具箱面板是固定 1180×800 且 overflow:hidden，可用纵向空间比浏览器视口小得多，
        // 所以子卡要小一号、扇形要更靠上，否则最外侧那几张会被面板切掉。
        TOOL: {
            FOCUS_SCALE: 1.45,
            PARENT_DY: -60,
            KID_SPACING: 190,      // 工具箱子卡 CSS 里缩到 150 宽，间距跟着收
            KID_DY0: 177,
            KID_DY_SPAN: 14,
            KID_ROT: 6,
            KID_HALF: 115          // 150×204 倾斜后包围盒半高
        }
    },

    // ==================== 数据表 ====================
    // self:true 标记"这张卡自己有父级面板"（sensevoice / active / tts / napcat / flux_painter）。
    // 注意：点父卡的统一行为是"摊开 / 收起"，不从这里进面板。
    // 其中 sensevoice、active 的父级面板和子卡面板内容完全一样（只是标题不同，已确认）；
    // tts / napcat / flux_painter 是"总设置"合并表单，各部分在子卡里都有，
    // 只是不能一次保存 —— 需要的话可以用这个标记给它们各生成一张"总设置"子卡。
    launcherPlanets: [
        { id: 'phone', label: '接口', card: 'launcher_phone', tooltip: '启动手机接口服务' },
        { id: 'main', label: '主程序', card: 'launcher_main', tooltip: '启动主程序' },
        { id: 'sovits', label: 'SoVITS', card: 'launcher_sovits', tooltip: '启动 SoVITS 服务' },
        { id: 'sensevoice', label: 'SenseVoice', card: 'launcher_sensevoice', tooltip: '启动 SenseVoice 服务' },
        { id: 'painting', label: '绘画', card: 'launcher_painting', tooltip: '启动内置 ComfyUI 绘画引擎' },
        { id: 'napcat', label: 'NapCat', card: 'launcher_napcat', tooltip: 'NapCat 快速启动' },
        { id: 'netease', label: '网易云', card: 'launcher_netease', tooltip: '启动网易云搜歌服务' },
        { id: 'rvc', label: 'RVC', card: 'launcher_rvc', tooltip: '启动 RVC 翻唱服务' },
        { id: 'desktopet', label: '桌宠', card: 'launcher_desktopet', tooltip: '启动桌宠' }
    ],

    outerPlanets: [
        { id: 'basic', label: '基本', card: 'basic', tooltip: '基础与 app 设置' },
        { id: 'character', label: '角色卡', card: 'character', tooltip: '角色卡配置' },
        {
            id: 'sensevoice', label: 'SenseVoice', card: 'sensevoice', tooltip: '语音识别配置', self: true,
            kids: [
                { id: 'sensevoice_config', label: '识别', card: 'sensevoice_config', tooltip: '语音识别配置' },
                { id: 'sensevoice_mic', label: '闭麦', card: 'sensevoice_mic', tooltip: '闭麦（麦克风开关）' },
                { id: 'sensevoice_audio', label: '音频', card: 'sensevoice_audio', tooltip: '音频采集设置' }
            ]
        },
        {
            id: 'llm', label: 'LLM', card: 'llm', tooltip: '大语言模型配置',
            kids: [
                { id: 'llm_model', label: '模型', card: 'llm_model', tooltip: 'LLM 模型设置' },
                { id: 'llm_prompt', label: '提示词', card: 'llm_prompt', tooltip: 'LLM 提示词设置' },
                { id: 'llm_algorithm', label: '算法', card: 'llm_algorithm', tooltip: 'LLM 算法设置' }
            ]
        },
        {
            id: 'active', label: '主动回复', card: 'active', tooltip: '角色主动回复配置', self: true,
            kids: [
                { id: 'active_config', label: '配置', card: 'active_config', tooltip: '主动回复配置' },
                { id: 'active_browse', label: '浏览', card: 'active_browse', tooltip: 'B站内容浏览' }
            ]
        },
        {
            id: 'catbrain', label: 'CatBrain', card: 'catbrain', tooltip: '角色灵魂配置',
            kids: [
                { id: 'ltmem', label: '长期记忆', card: 'catbrain_ltmem', tooltip: '长期记忆配置' },
                { id: 'abstract', label: '记忆摘要', card: 'catbrain_abstract', tooltip: '记忆摘要配置' },
                { id: 'rulesbreak', label: '原则词', card: 'catbrain_rulesbreak', tooltip: '破甲原则词配置' },
                { id: 'values', label: '价值观', card: 'catbrain_values', tooltip: '价值观配置' },
                { id: 'usermem', label: '用户记忆', card: 'catbrain_usermem', tooltip: '用户记忆配置' }
            ]
        },
        {
            id: 'database', label: '数据库', card: 'database', tooltip: '数据库知识库配置',
            kids: [
                { id: 'db_search', label: '搜索', card: 'db_search', tooltip: '搜索学习配置' },
                { id: 'db_store', label: '知识', card: 'db_store', tooltip: '存储及检索配置' },
                { id: 'db_source', label: '来源', card: 'db_source', tooltip: '网页数据来源配置' },
                { id: 'db_prefill', label: '预填', card: 'db_prefill', tooltip: '一键预填充知识库' }
            ]
        },
        {
            id: 'tts', label: 'TTS', card: 'tts', tooltip: '语音合成与 SoVITS 配置', self: true,
            kids: [
                { id: 'tts_model', label: '模型', card: 'tts_model', tooltip: '语音模型设置' },
                { id: 'tts_params', label: '参数', card: 'tts_params', tooltip: '语音参数设置' },
                { id: 'tts_config', label: '配置', card: 'tts_config', tooltip: '语音合成配置' },
                { id: 'tts_pause', label: '间隔', card: 'tts_pause', tooltip: '合成间隔设置' }
            ]
        },
        { id: 'subtitle', label: '字幕', card: 'subtitle', tooltip: '字幕模块配置' },
        {
            id: 'vts', label: 'VTS', card: 'vts', tooltip: 'VTuber / VTS 配置',
            kids: [
                { id: 'vts_config', label: '配置', card: 'vts_config', tooltip: 'VTS 配置' },
                { id: 'vts_emotion', label: '表情', card: 'vts_emotion', tooltip: 'VTS 表情绑定' },
                { id: 'desktopet', label: '桌宠', card: 'desktopet', tooltip: '桌宠配置' },
                { id: 'vts_params', label: '参数', card: 'vts_params', tooltip: 'VTS 模型参数' }
            ]
        },
        { id: 'toolbox', label: '工具箱', card: 'toolbox', tooltip: '工具箱（Minecraft 等工具）', overlay: true },
        {
            id: 'meowsinger', label: '歌曲', card: 'meowsinger', tooltip: '点歌翻唱与感想配置',
            kids: [
                { id: 'meowsinger_model', label: '模型', card: 'meowsinger_model', tooltip: '歌曲模型设置' },
                { id: 'meowsinger_song', label: '歌曲', card: 'meowsinger_song', tooltip: '点歌设置' },
                { id: 'meowsinger_cover', label: '翻唱', card: 'meowsinger_cover', tooltip: '翻唱设置' },
                { id: 'meowsinger_sentiment', label: '感想', card: 'meowsinger_sentiment', tooltip: '感想设置' }
            ]
        },
        { id: 'calendar', label: '待办', card: 'calendar', tooltip: '待办提醒' }
    ],

    toolboxPlanets: [
        { id: 'minecraft', label: 'Minecraft', card: 'minecraft', tooltip: 'Minecraft 日志读取配置' },
        { id: 'meowvision', label: '视觉', card: 'meowvision', tooltip: 'MeowVision 视觉模块配置' },
        {
            id: 'napcat', label: 'NapCat', card: 'napcat', tooltip: 'NapCat QQ 机器人配置', self: true,
            kids: [
                { id: 'napcat_private', label: '私聊回复', card: 'napcat_private', tooltip: '私聊回复配置' },
                { id: 'napcat_group', label: '群聊回复', card: 'napcat_group', tooltip: '群聊回复与主动插话配置' },
                { id: 'napcat_send', label: '主动发送', card: 'napcat_send', tooltip: '主动发送触发型工具配置' },
                { id: 'napcat_account', label: '角色名', card: 'napcat_account', tooltip: '连接与角色名配置' }
            ]
        },
        { id: 'weather', label: '天气', card: 'weather', tooltip: '天气查询配置' },
        { id: 'news', label: '新闻', card: 'news', tooltip: '新闻查询配置' },
        { id: 'danmaku', label: '弹幕', card: 'danmaku', tooltip: 'B站直播弹幕配置' },
        { id: 'add_backlog', label: '提醒', card: 'add_backlog', tooltip: '新建待办触发工具配置' },
        { id: 'meowsongs', label: '哼唱', card: 'meowsongs', tooltip: '即兴哼唱配置' },
        { id: 'turtle_soup', label: '海龟汤', card: 'turtle_soup', tooltip: '海龟汤触发工具配置' },
        {
            id: 'flux_painter', label: '绘画', card: 'flux_painter', tooltip: 'Flux 绘画（内置 ComfyUI 文生图）配置', self: true,
            kids: [
                { id: 'flux_painter_service', label: '服务', card: 'flux_service', tooltip: '绘画引擎服务与运行环境' },
                { id: 'flux_painter_model', label: '模型', card: 'flux_model', tooltip: '底模与提示词模型配置' },
                { id: 'flux_painter_prompt', label: '提示词', card: 'flux_prompt', tooltip: '提示词固定件与画师配置' },
                { id: 'flux_painter_workflow', label: '工作流', card: 'flux_workflow', tooltip: '采样与画质、Pro 流程配置' }
            ]
        }
    ],
};