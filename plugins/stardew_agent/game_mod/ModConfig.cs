using StardewModdingAPI;

namespace BlindWhaleFarmer
{
    public class ModConfig
    {
        /// <summary>DeepSeek API Key。留空时读取环境变量 DEEPSEEK_API_KEY。</summary>
        public string ApiKey { get; set; } = "";

        /// <summary>OpenAI 兼容接口地址（不含 /chat/completions）。</summary>
        public string BaseUrl { get; set; } = "https://api.deepseek.com";

        /// <summary>模型名（内置 AI 用；Python 插件那边用自己的模型）。</summary>
        public string Model { get; set; } = "deepseek-v4-flash";

        public float Temperature { get; set; } = 0.3f;

        public int MaxTokens { get; set; } = 4096;

        public int RequestTimeoutSeconds { get; set; } = 120;

        /// <summary>开关内置 AI 的快捷键。</summary>
        public SButton ToggleKey { get; set; } = SButton.F8;

        /// <summary>联机时弹出中文输入框的键。</summary>
        public SButton ChatInputKey { get; set; } = SButton.F6;

        /// <summary>联机时怎么安排自己：solo 自己玩、command 主要听指令、hybrid 指令做完接着自己玩。</summary>
        public string CompanionMode { get; set; } = GameActions.ModeHybrid;

        /// <summary>接管键：中止 AI 动作并交还玩家；再按一次交还。</summary>
        public SButton TakeOverKey { get; set; } = SButton.F7;

        /// <summary>等待模型回复时冻结游戏时间。</summary>
        public bool FreezeTimeWhileThinking { get; set; } = false;

        /// <summary>一次回复里最多执行多少个工具调用。</summary>
        public int MaxActionsPerStep { get; set; } = 6;

        /// <summary>提示词里保留多少条最近的行动记录。</summary>
        public int HistoryLines { get; set; } = 25;

        /// <summary>文字地图以玩家为中心的横向/纵向半径（格）。</summary>
        public int MapRadiusX { get; set; } = 14;
        public int MapRadiusY { get; set; } = 9;

        /// <summary>附近物体列表的搜索半径（格）。</summary>
        public int ScanRadius { get; set; } = 16;

        /// <summary>在屏幕左上角显示 AI 的想法和当前动作。</summary>
        public bool ShowHud { get; set; } = true;

        /// <summary>自动点掉出货结算界面、无需选择的升级界面（默认关：由角色自己读、自己确认）。</summary>
        public bool AutoConfirmNightMenus { get; set; } = true;

        /// <summary>剧情卡死时自动跳过（默认关：角色要认真读剧情）。</summary>
        public bool RecoverStuckEvents { get; set; } = true;

        /// <summary>走路时顺手采集野生采集物的范围（格，含斜角）。0 表示不顺手采。</summary>
        public int ForageRadius { get; set; } = 1;

        /// <summary>额外写给 AI 的目标/要求。</summary>
        public string ExtraInstructions { get; set; } = "";

        /// <summary>攻略文件（相对模组目录或绝对路径）。</summary>
        public string GuideFile { get; set; } = Guide.DefaultFile;

        /// <summary>在设置页改过的攻略：篇名 → 全文。</summary>
        public System.Collections.Generic.Dictionary<string, string> GuideOverrides { get; set; } = new();

        /// <summary>把每次发送给模型的完整提示词写到日志文件。</summary>
        public bool LogPrompts { get; set; } = false;

        /// <summary>开启本地 MCP 服务器（只监听 127.0.0.1）。</summary>
        public bool EnableMcp { get; set; } = true;

        /// <summary>MCP 服务器端口，地址为 http://127.0.0.1:端口/mcp。</summary>
        public int McpPort { get; set; } = 18080;

        /// <summary>给 Python 插件用的 REST 接口：GET /state 读状态、POST /command 执行工具。</summary>
        public bool EnableApi { get; set; } = true;

        /// <summary>REST 接口端口，地址为 http://127.0.0.1:端口/state。</summary>
        public int ApiPort { get; set; } = 8765;

        /// <summary>启动游戏后自动读档（等价于真人点「读取存档」）。</summary>
        public bool AutoLoadSave { get; set; } = true;

        /// <summary>自动读哪个存档；留空读最近修改的存档。</summary>
        public string AutoLoadSaveName { get; set; } = "";

        /// <summary>允许截图（QQ 主动分享用）。</summary>
        public bool TakeScreenshots { get; set; } = true;

        /// <summary>截图方向修正：none / vertical / horizontal / rot180。</summary>
        public string ScreenFlip { get; set; } = "none";

        /// <summary>MCP 客户端思考时冻结游戏时间。</summary>
        public bool McpFreezeTime { get; set; } = false;

        public int McpIdleSeconds { get; set; } = 120;

        /// <summary>MCP 客户端停下时把整个游戏暂停（按任意键继续）。</summary>
        public bool PauseWhenAiStops { get; set; } = true;

        /// <summary>每次游玩最多玩几个游戏日（睡一觉算一天）。0 = 不限。</summary>
        public int SessionDays { get; set; } = 0;

        /// <summary>每次游玩最多玩多少现实分钟。0 = 不限。</summary>
        public int SessionMinutes { get; set; } = 0;
    }
}
