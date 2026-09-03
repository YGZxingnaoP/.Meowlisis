/**
 * 配置面板生成器 - toolbox 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
    napcat() {
        // 总览（向后兼容，实际由四个子球分别配置）
        return this.napcat_account() + this.napcat_private() + this.napcat_group() + this.napcat_send();
    },
    napcat_account() {
        return this._section('NapCat 连接与角色名') +
            this._check('启用 NapCat', 'napcat.enabled', false) +
            this._text('WebSocket 地址', 'napcat.ws_url', 'ws://127.0.0.1:3001') +
            this._password('Access Token（可空）', 'napcat.access_token', '') +
            this._text('角色名（群内 @ 该昵称触发立即回复）', 'napcat.self_nickname', '喵利呜西斯') +
            this._check('调试：原始事件落盘', 'napcat.debug_event_dump', false,
                '开启后把 NapCat 原始事件写入 .temp/napcat_raw_events.jsonl（用于拿群机器人消息样本）');
    },
    napcat_private() {
        return this._section('NapCat 私聊回复') +
            this._check('启用私聊回复', 'napcat.private_reply_enabled', true) +
            this._num('拉取历史条数', 'napcat.history_limit', 30, 1, 200, 1,
                '向上获取的聊天记录条数，作为 napcat 私聊回复的短期记忆') +
            this._num('短期记忆轮数', 'napcat.short_mem_rounds', 30, 1, 200, 1,
                'qq_response 类型短期记忆保留轮数（1 轮 = 用户 + AI），不成对的孤立消息按条数兜底裁剪') +
            this._check('启用短期记忆', 'napcat.short_mem_enabled', true) +
            this._check('启用长期记忆', 'napcat.ltmem_enabled', false) +
            this._select('深度思考级别', 'napcat.thinking_level', [
                { value: 'off', label: '关闭' },
                { value: 'low', label: '低' },
                { value: 'medium', label: '中' },
                { value: 'high', label: '高' }
            ], 'medium', 'DeepSeek/Aliyun 当前仅支持开/关，medium 及以上均开启思考') +
            this._num('回复字数', 'napcat.reply_word_count', 10, 1, 100, 1,
                '每次回复约该字数，严格上限 = 该值 + 10') +
            this._check('启用表情发送', 'napcat.emote_enabled', true) +
            this._num('表情触发概率(%)', 'napcat.emote_probability', 30, 0, 100, 1,
                '最终概率 = 配置概率 + 用户好感度') +
            this._text('表情文件目录', 'napcat.emote_dir', '.NapCat/EmoteLab');
    },
    napcat_group() {
        return this._section('NapCat 群聊回复') +
            this._check('启用群聊回复', 'napcat.group_reply_enabled', true) +
            this._num('回复字数', 'napcat.group_reply_word_count', 10, 1, 100, 1,
                '群聊每次回复约该字数，严格上限 = 该值 + 10（独立于私聊回复字数）') +
            this._list('群聊名称黑名单（逗号分隔，空=不拦截）', 'napcat.group_blacklist', []) +
            this._num('群聊历史拉取条数', 'napcat.group_history_limit', 50, 1, 500, 1,
                'get_group_record 向上获取的群聊历史条数（content 标注【用户名】:内容）') +
            this._num('群聊短期记忆容纳条数', 'napcat.group_memory_limit', 10, 1, 200, 1,
                'qq_groupchat 类型仅存 assistant 消息，最多容纳条数') +
            this._kvDictEditor('群机器人映射（机器人名 → QQ号）', 'napcat.group_bots', {},
                '识别群机器人，如 幻梦 → 3889006601', '机器人名', 'QQ号') +
            this._section('群聊主动插话（按消息数判断）') +
            this._check('启用群聊主动插话', 'napcat.group_active_enabled', true) +
            this._num('触发基数（更新 N 次后判断）', 'napcat.group_reply_base', 6, 1, 100, 1,
                '群聊消息累计该次数后由 AI 判断是否插话') +
            this._num('触发抖动比例(±)', 'napcat.group_reply_jitter', 0.2, 0, 0.5, 0.05,
                '实际阈值 = 基数 ± 该比例，取整随机') +
            this._num('pass 允许连续次数', 'napcat.group_pass_rounds', 1, 0, 20, 1,
                'AI 连续输出 pass 的次数，超过后必须发送') +
            this._groupConfigEditor('每群单独配置（群号 → 触发基数/pass次数）', 'napcat.group_per_group',
                '留空则使用上面的全局配置；仅填写的字段覆盖全局') +
            this._section('群性质概括 (group_info)') +
            this._num('概括间隔（AI 发送条数）', 'napcat.group_info_interval', 100, 1, 10000, 1) +
            this._num('概括最近条数', 'napcat.group_info_recent', 50, 1, 500, 1) +
            this._num('概括采样范围（最近条数之外）', 'napcat.group_info_sample_range', 200, 1, 2000, 1);
    },
    napcat_send() {
        return this._section('NapCat 主动发送（触发型工具）') +
            this._check('启用主动发送', 'napcat.active_sender.enabled', true,
                'AI 主动给好友/群发消息、文件、链接（受 toolcalls 控制）') +
            this._num('冷却时间(秒)', 'napcat.active_sender.cooldown', 60, 0, 3600, 1,
                '两次主动发送的最小间隔');
    },

    // ============ Minecraft ============,
    minecraft() {
        return this._section('Minecraft 日志读取') +
            this._check('启用 Minecraft 日志读取', 'minecraft.enabled', false) +
            this._text('日志文件路径', 'minecraft.log_path', '') +
            this._text('编码', 'minecraft.encoding', 'utf-8') +
            this._num('检查间隔（秒）', 'minecraft.check_interval', 30, 1, 60, 1) +
            this._check('使用玩家名作为 UID', 'minecraft.use_player_name', false) +
            this._text('固定用户名', 'minecraft.username_fixed', 'YGZ醒脑片') +
            this._check('在提示词中包含玩家名', 'minecraft.include_player_name_in_prompt', true) +
            this._list('玩家白名单（逗号分隔，空=不过滤）', 'minecraft.filter_players', []) +
            this._check('忽略自己发送的消息', 'minecraft.ignore_self_messages', false);
    },

    // ============ 角色主动回复 (llm_active) ============,
    llm_active() {
        return this._section('角色主动回复 (llm_active)') +
            this._num('空闲冷却时间(秒)', 'llm_active.cold_time', 90, 1, 3600, 1,
                '空闲后触发主动回复的基础等待时间，实际等待 = 该值 × 随机(0.8~1.2)') +
            this._num('连续触发阈值 n', 'llm_active.n', 1, 0, 100, 1,
                '连续空闲触发次数 ≤ n 使用继承话题策略，> n 使用创造话题策略') +
            this._num('摘要检索条数上限', 'llm_active.origin_summary_limit', 30, 1, 200, 1,
                '创造话题策略时检索记忆摘要的最大条数') +
            this._num('最近说话人数量', 'llm_active.origin_speaker_limit', 3, 1, 3, 1,
                '创造话题策略时读取最近说话人档案的数量（最多3个）') +
            this._num('主动回复插播记忆上限(条)', 'llm_active.active_mem_limit', 50, 1, 500, 1,
                '主动回复单条消息在短期记忆中的兜底保留条数（尾部无后续对话时按此裁剪）');
    },

    // ============ B站浏览配置（视觉模型 + 内容收集） ============,
    webBrowseConfig() {
        const visionType = this._val('llm_active.vision.llm_type', 'aliyun');
        let h = this._section('B站浏览视觉模型 (llm_active.vision)') +
            `<div class="form-group"><label>${this._t('视觉 LLM 类型')}</label>
            <select data-path="llm_active.vision.llm_type">
                <option value="aliyun" ${visionType === 'aliyun' ? 'selected' : ''}>${this._t('阿里云')}</option>
                <option value="gemini" ${visionType === 'gemini' ? 'selected' : ''}>Gemini</option>
            </select></div>` +
            this._password('API Key', 'llm_active.vision.api_key', '',
                '独立于 MeowVision，仅用于 B站视频截图的内容理解') +
            this._text('Base URL', 'llm_active.vision.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'llm_active.vision.model', 'qwen3.7-flash') +
            this._num('温度', 'llm_active.vision.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm_active.vision.max_tokens', 600, 1, 8192, 16,
                '内容描述(≤300字) + 话题 + tags 的输出预算') +
            this._num('Top P', 'llm_active.vision.top_p', 0.9, 0, 1, 0.05) +
            this._section('Gemini 视觉') +
            this._password('Gemini API Key', 'llm_active.vision.gemini.api_key', '') +
            this._text('Gemini Base URL', 'llm_active.vision.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('Gemini 模型', 'llm_active.vision.gemini.model', 'gemini-3.6-flash') +
            this._num('Gemini 温度', 'llm_active.vision.gemini.temperature', 0.7, 0, 2, 0.1) +
            this._num('Gemini 最大输出 tokens', 'llm_active.vision.gemini.max_tokens', 600, 1, 8192, 16) +
            this._num('Gemini Top P', 'llm_active.vision.gemini.top_p', 0.9, 0, 1, 0.05);

        h += this._section('B站内容收集 (llm_active.web_browse)') +
            this._check('启用 B站内容收集', 'llm_active.web_browse.enabled', true,
                '开启后后台线程定时抓取账号首页视频，抽帧 → 视觉概括 → 作为主动回复素材') +
            this._num('采集间隔(秒)', 'llm_active.web_browse.interval', 600, 30, 86400, 10,
                '每隔多久尝试补一个视频（默认 10 分钟）') +
            this._num('缓存上限', 'llm_active.web_browse.max_cache', 5, 1, 20, 1,
                '缓存达到该数量后暂停补货，消费后自动补') +
            this._num('抽帧数', 'llm_active.web_browse.frames', 5, 1, 10, 1,
                '视频 n 等分，每段随机抽 1 帧，压缩到 720p') +
            this._list('允许主题（逗号分隔）', 'llm_active.web_browse.allow_topics', ['二次元', '科普', '游戏'],
                '过滤视频的主题，空=随机') +
            this._select('严格程度', 'llm_active.web_browse.strictness', [
                { value: 'strict', label: 'strict（只允许列表内主题）' },
                { value: 'loose', label: 'loose（允许其它主题）' }
            ], 'strict') +
            this._check('禁止抽象视频', 'llm_active.web_browse.forbid_abstract', true,
                'LLM 语义判断，默认禁止抽象/整活类视频') +
            this._num('UP主 mid', 'llm_active.web_browse.mid', 0, 0, 999999999, 1,
                '0=自动用登录态抓自己账号首页视频；也可手动填指定 UP 主 mid') +
            this._text('SESSDATA', 'llm_active.web_browse.sessdata', '',
                'B站登录态，可点下方「B站扫码登录」自动获取；与弹幕兜底通道独立') +
            this._text('bili_jct', 'llm_active.web_browse.bili_jct', '',
                'B站 csrf 令牌，扫码登录自动写入');
        return h;
    },

    // ============ B站内容浏览面板 ============,
    webBrowsePanel(status, cache, collected) {
        const caches = cache || [];
        const collecteds = collected || [];

        let h = this.webBrowseConfig();

        h += `<div class="speaker-actions">
            <button type="button" class="btn btn-secondary webbrowse-refresh-btn">${this._t('刷新列表')}</button>
            <button type="button" class="btn btn-primary bili-login-btn" data-target="web_browse">${this._t('B站扫码登录')}</button>
        </div>`;

        h += this._section('待使用缓存（' + caches.length + '）');
        h += `<div id="webBrowseCacheList">` + this._videoList(caches, false) + `</div>`;

        h += this._section('已收藏（' + collecteds.length + '）');
        h += `<div id="webBrowseCollectedList">` + this._videoList(collecteds, true) + `</div>`;
        return h;
    },
    _videoList(items, isCollected) {
        if (!items || !items.length) {
            return isCollected
                ? `<div class="help-text">${this._t('暂无已收藏视频。主动回复使用过的视频会移动到此处。')}</div>`
                : `<div class="help-text">${this._t('暂无缓存视频，等待后台采集或先扫码登录并配置视觉 API Key。')}</div>`;
        }
        return items.map(v => this._videoCard(v, isCollected)).join('');
    },
    _videoCard(v, isCollected) {
        v = v || {};
        const tags = (v.tags || []).map(t => `<span class="webbrowse-tag">${this._esc(t)}</span>`).join('');
        const urlHtml = (v.url && isCollected)
            ? `<a class="webbrowse-link" href="${this._escAttr(v.url)}" target="_blank" rel="noopener">${this._t('打开视频 ↗')}</a>`
            : '';
        return `<div class="char-card">
            <div class="char-card-title">${this._esc(v.title || '(无标题)')}</div>
            <div class="webbrowse-meta">
                <span>${this._t('UP：')}${this._esc(v.uploader || '-')}</span>
                <span>${this._t('时长：')}${this._esc(v.len || '-')}</span>
                <span>${this._t('话题：')}${this._esc(v.topic || '-')}</span>
                ${urlHtml}
            </div>
            ${tags ? `<div class="webbrowse-tags">${tags}</div>` : ''}
            <div class="webbrowse-content">${this._esc(v.content || '')}</div>
        </div>`;
    },

    // ============ 字幕 ============,
    subtitle() {
        return this._section('字幕模块') +
            `<div class="help-text">${this._t('浏览器字幕模块：TTS 播放字幕与歌词字幕统一输出（HTTP 8080 / WebSocket 8765，暂无配置项）。')}</div>`;
    },

    // ============ Toolbox 父级模型 ============,
    toolbox() {
        const type = this._val('toolbox.llm_type', 'deepseek');
        let h = this._section('Toolbox 父级模型') +
            this._llmTypeSelect('父级 LLM 类型', 'toolbox.llm_type', type);
        h += `<div class="modal-tabs">
            <button class="modal-tab active" data-tab="toolbox_ds">DeepSeek</button>
            <button class="modal-tab" data-tab="toolbox_aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab" data-tab="toolbox_gemini">Gemini</button>
        </div>`;
        h += `<div class="tab-content active" data-tab-content="toolbox_ds">` +
            this._password('API Key', 'toolbox.deepseek.api_key', '') +
            this._text('Base URL', 'toolbox.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'toolbox.deepseek.model', 'deepseek-chat') +
            this._num('温度', 'toolbox.deepseek.temperature', 0.7, 0, 2, 0.1) +
            this._num('max_tokens', 'toolbox.deepseek.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="toolbox_aliyun">` +
            this._password('API Key', 'toolbox.aliyun.api_key', '') +
            this._text('Base URL', 'toolbox.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'toolbox.aliyun.model', 'qwen-plus') +
            this._num('温度', 'toolbox.aliyun.temperature', 0.7, 0, 2, 0.1) +
            this._num('max_tokens', 'toolbox.aliyun.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += `<div class="tab-content" data-tab-content="toolbox_gemini">` +
            this._password('API Key', 'toolbox.gemini.api_key', '') +
            this._text('Base URL', 'toolbox.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'toolbox.gemini.model', 'gemini-3.6-flash') +
            this._num('温度', 'toolbox.gemini.temperature', 0.7, 0, 2, 0.1) +
            this._num('max_tokens', 'toolbox.gemini.max_tokens', 2048, 1, 32768, 16) +
            `</div>`;
        h += this._section('excuse 通用询问链路') +
            this._check('启用 excuse 询问', 'toolbox.excuse_enabled', true,
                'AI 有疑问时以角色口吻语音询问，并阻塞等待用户文本输入补充需求') +
            this._num('excuse 等待超时(秒)', 'toolbox.excuse_timeout', 60, 1, 600, 1);
        return h;
    },

    // ============ MeowVision 视觉模块 ============,
    meowvision() {
        const type = this._val('meowvision.llm_type', 'aliyun');
        return this._section('MeowVision 视觉理解') +
            `<div class="form-group"><label>${this._t('视觉 LLM 类型')}</label>
            <select data-path="meowvision.llm_type">
                <option value="aliyun" ${type === 'aliyun' ? 'selected' : ''}>${this._t('阿里云')}</option>
                <option value="gemini" ${type === 'gemini' ? 'selected' : ''}>Gemini</option>
            </select></div>` +
            this._password('API Key', 'meowvision.api_key', '') +
            this._text('Base URL', 'meowvision.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'meowvision.model', 'qvq-plus') +
            this._num('温度', 'meowvision.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'meowvision.max_tokens', 512, 1, 8192, 16,
                '视觉回复最大 token，默认 512') +
            this._num('Top P', 'meowvision.top_p', 0.9, 0, 1, 0.05) +
            this._section('Gemini 视觉') +
            this._password('Gemini API Key', 'meowvision.gemini.api_key', '') +
            this._text('Gemini Base URL', 'meowvision.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('Gemini 模型', 'meowvision.gemini.model', 'gemini-3.6-flash') +
            this._num('Gemini 温度', 'meowvision.gemini.temperature', 0.7, 0, 2, 0.1) +
            this._num('Gemini 最大输出 tokens', 'meowvision.gemini.max_tokens', 512, 1, 8192, 16) +
            this._num('Gemini Top P', 'meowvision.gemini.top_p', 0.9, 0, 1, 0.05) +
            this._text('图片缓存目录', 'meowvision.cache_dir', './.temp/vision_cache',
                '截图/裁切/编码结果统一缓存目录；NapCat 收到的图片也会先落到此目录避免直接用 url') +
            this._section('Watching 长期观察') +
            this._check('启用 Watching（长期观察屏幕）', 'meowvision.watching.enabled', true,
                'AI 判断用户有「陪打游戏 / 陪看屏幕」意图时才进入长期观察流程') +
            this._num('变化检测相似阈值', 'meowvision.watching.change_similarity_threshold', 0.85, 0, 1, 0.05,
                '前后两帧相似度达到该值判定为「无变化」，无变化时本轮不传视觉模型') +
            this._num('窗口消失确认秒数', 'meowvision.watching.window_gone_confirm_seconds', 5, 1, 60, 1,
                '绑定游戏窗口消失后，连续多少秒未检测到才判定强制结束');
    },

    // ============ 待办提醒 (calendar) ============,
    calendarPanel() {
        return `<div class="calendar-panel">
            <div class="calendar-toolbar">
                <input type="text" id="newBacklogUserInput" placeholder="${this._t('输入用户名')}">
                <button type="button" class="btn btn-primary" id="addBacklogUserBtn">${this._t('新建用户')}</button>
            </div>
            <div id="backlogUserList"></div>
        </div>`;
    },

    // ============ 天气查询 (weather) ============,
    weather() {
        return this._section('天气查询（触发型工具）') +
            this._check('启用天气查询', 'weather.enabled', true,
                'AI 根据用户天气询问触发查询并播报，数据来自中国天气网（受 toolcalls 控制）');
    },

    // ============ 新闻查询 (news) ============,
    news() {
        return this._section('新闻查询（触发型工具）') +
            this._check('启用新闻查询', 'news.enabled', true,
                'AI 根据用户新闻/热点询问触发爬取并概括，数据来自 Readhub（受 toolcalls 控制）') +
            this._num('爬取条数', 'news.top_n', 3, 1, 10, 1,
                '每次爬取并概括的新闻条数（默认 3，最多 10）');
    },

    // ============ 新建待办提醒 (add_backlog) ============,
    addBacklog() {
        return this._section('新建待办（触发型工具）') +
            this._check('启用新建待办', 'add_backlog.enabled', true,
                'AI 根据用户「记一下 / 提醒我几点做什么」触发，深度思考后写入 character/backlog（受 toolcalls 控制）') +
            this._check('QQ 对接', 'add_backlog.qq_enabled', true,
                '开启后 QQ 私聊 / 群聊@ 也可触发新建待办，且待办 qq 提醒强制开启');
    },

    // ============ 海龟汤 (turtle_soup) ============,
    turtle_soup() {
        return this._section('海龟汤（触发型工具）') +
            this._check('启用海龟汤', 'turtle_soup.enabled', true,
                'AI 根据用户「玩海龟汤 / 情境猜谜」触发，生成谜题并主持游戏（受 toolcalls 控制）') +
            this._check('QQ 对接', 'turtle_soup.qq_enabled', true,
                '开启后 QQ 私聊 / 群聊@ 也可触发海龟汤，QQ 线仅发文本、不播语音') +
            this._text('题库归档目录', 'turtle_soup.bank_dir', './character/turtle_soup',
                '结束的局会归档到这里，供以后复用') +
            this._text('运行时缓存目录', 'turtle_soup.cache_dir', './.temp/turtle_soup',
                '进行中的局缓存到这里（含谜底谜面），结束或启动时清理') +
            this._num('低难度汤面字数', 'turtle_soup.surface_len.easy', 20, 10, 60, 1,
                '低难度（easy）汤面目标字数') +
            this._num('高难度汤面字数', 'turtle_soup.surface_len.hard', 40, 20, 100, 1,
                '高难度（hard）汤面目标字数');
    },

    // ============ 歌曲（meowsinger）子球 ============,
});
