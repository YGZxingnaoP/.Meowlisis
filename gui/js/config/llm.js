/**
 * 配置面板生成器 - llm 模块
 * 由 config.js 拆分而来，统一挂载到全局 Config 对象
 */

Object.assign(Config, {
    llm_model() {
        const type = this._val('llm.local_llm_type', 'deepseek');
        let h = this._section('LLM 大模型') +
            `<div class="form-group"><label>${this._t('LLM类型')}</label>
            <select data-path="llm.local_llm_type" onchange="Config.toggleMeowLLMLink(this)">
                <option value="deepseek" ${type === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                <option value="aliyun" ${type === 'aliyun' ? 'selected' : ''}>${this._t('阿里云')}</option>
                <option value="gemini" ${type === 'gemini' ? 'selected' : ''}>Gemini</option>
                <option value="meowllm" ${type === 'meowllm' ? 'selected' : ''}>MeowLLM</option>
            </select>${this._mllLink(type === 'meowllm')}</div>`;

        h += `<div class="modal-tabs">
            <button class="modal-tab${type === 'deepseek' ? ' active' : ''}" data-tab="deepseek">DeepSeek</button>
            <button class="modal-tab${type === 'aliyun' ? ' active' : ''}" data-tab="aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab${type === 'gemini' ? ' active' : ''}" data-tab="gemini">Gemini</button>
            <button class="modal-tab${type === 'meowllm' ? ' active' : ''}" data-tab="meowllm">MeowLLM</button>
        </div>`;

        h += `<div class="tab-content${type === 'deepseek' ? ' active' : ''}" data-tab-content="deepseek">` +
            this._password('API Key', 'llm.deepseek.api_key', '') +
            this._text('Base URL', 'llm.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'llm.deepseek.model', 'deepseek-chat') +
            this._num('温度', 'llm.deepseek.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.deepseek.max_tokens', 1024, 1, 8192, 16) +
            this._num('Top P', 'llm.deepseek.top_p', 0.9, 0, 1, 0.05) +
            this._check('启用流式输出', 'llm.deepseek.stream', true) +
            this._check('启用思考模式', 'llm.deepseek.enable_thinking', false) +
            `</div>`;

        h += `<div class="tab-content${type === 'aliyun' ? ' active' : ''}" data-tab-content="aliyun">` +
            this._password('API Key', 'llm.aliyun.api_key', '') +
            this._text('Base URL', 'llm.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'llm.aliyun.model', 'qwen-plus') +
            this._num('温度', 'llm.aliyun.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.aliyun.max_tokens', 1024, 1, 8192, 16) +
            this._num('Top P', 'llm.aliyun.top_p', 0.9, 0, 1, 0.05) +
            this._check('启用流式输出', 'llm.aliyun.stream', true) +
            this._check('启用思考模式', 'llm.aliyun.enable_thinking', false) +
            `</div>`;

        h += `<div class="tab-content${type === 'gemini' ? ' active' : ''}" data-tab-content="gemini">` +
            this._password('API Key', 'llm.gemini.api_key', '') +
            this._text('Base URL', 'llm.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'llm.gemini.model', 'gemini-3.6-flash') +
            this._num('温度', 'llm.gemini.temperature', 0.7, 0, 2, 0.1) +
            this._num('最大输出 tokens', 'llm.gemini.max_tokens', 1024, 1, 8192, 16) +
            this._num('Top P', 'llm.gemini.top_p', 0.9, 0, 1, 0.05) +
            this._check('启用流式输出', 'llm.gemini.stream', true) +
            this._check('启用思考模式', 'llm.gemini.enable_thinking', false) +
            `</div>`;

        h += this.llm_meowllmPane(type);

        h += this._num('短期记忆轮数', 'llm.short_term_rounds', 5, 1, 60, 1) +
            this.splitFlagEditor('llm.split_flag') +
            this._num('最小分段长度', 'llm.split_limit', 6, 1, 100, 1);
        return h;
    },
    llm_prompt(front) {
        const f = front || {};
        const frontPrompt = f.prompt || '';
        const activeFront = f.prompt_active || '';
        const napcatFront = f.prompt_napcat || '';
        const postPrompt = f.post_prompt || '';
        return this._section('提示词（前置词放最前，后置词放最后）') +
            `<div class="form-group"><label>${this._t('前置词（行为约束，system prompt 最前）')}</label>
                <textarea id="frontPromptInput" class="auto-grow" rows="3" placeholder="${this._t('一次回复不要一次性解决复杂问题...')}">${this._esc(frontPrompt)}</textarea>
                <div class="help-text">${this._t('放在 system prompt 最前面，约束本次回复行为')}</div>
            </div>` +
            `<div class="form-group"><label>${this._t('主动回复前置词')}</label>
                <textarea id="activeFrontPromptInput" class="auto-grow" rows="2" placeholder="${this._t('一次回复不要一次性解决复杂问题...')}">${this._esc(activeFront)}</textarea>
                <div class="help-text">${this._t('主动找话题时的行为约束')}</div>
            </div>` +
            `<div class="form-group"><label>${this._t('NapCat 前置词')}</label>
                <textarea id="napcatFrontPromptInput" class="auto-grow" rows="2" placeholder="${this._t('一次回复不要一次性解决复杂问题...')}">${this._esc(napcatFront)}</textarea>
                <div class="help-text">${this._t('QQ 回复时的行为约束')}</div>
            </div>` +
            `<div class="form-group"><label>${this._t('后置词（人设，system prompt 最后）')}</label>
                <textarea id="postPromptInput" class="auto-grow" rows="2" placeholder="${this._t('你是...，大家都叫你...')}">${this._esc(postPrompt)}</textarea>
                <div class="help-text">${this._t('放在 system prompt 最后，描述角色身份')}</div>
            </div>`;
    },
    _narrationFormula() {
        return `<div class="formula-box">
            <div class="formula-box-title">${this._t('计算公式')}</div>
            <div class="formula-block">
                <div class="formula-row">
                    <span class="formula-name">${this._t('水词密度分')}</span>
                    <span class="formula-expr">Density = 100 − ( W / L × 100 )</span>
                    <span class="formula-cond">${this._t('若 W / L ≥ θ 则 Density = 0')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('超长惩罚')}</span>
                    <span class="formula-expr">${this._t('Penalty = 0，当 L ≤ L')}<sub>0</sub></span>
                    <span class="formula-expr">${this._t('Penalty = min( P<sub>cap</sub>, ( L − L<sub>0</sub> ) × r )，当 L &gt; L<sub>0</sub>')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('原始得分')}</span>
                    <span class="formula-expr">Raw<sub>t</sub> = max( 0, Density − Penalty )</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('平滑得分')}</span>
                    <span class="formula-expr">S<sub>t</sub> = λ · S<sub>t−1</sub> + ( 1 − λ ) · Raw<sub>t</sub></span>
                    <span class="formula-cond">${this._t('λ = 0.75（下降）/ 0.55（上升）/ 0.70（相等）')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('清洗档位')}</span>
                    <span class="formula-expr">${this._t('S ≥ 60 不清洗；30 ≤ S &lt; 60 清部分；S &lt; 30 全清')}</span>
                </div>
            </div>
            <div class="formula-params">
                ${this._t('W = 命中水词字符数，L = 回复总字符数，θ = 密度阈值，L<sub>0</sub> = 超长阈值，r = 惩罚系数，P<sub>cap</sub> = 惩罚封顶，λ = 惯性系数')}
            </div>
        </div>`;
    },
    llm_algorithm() {
        return this._narrationFormula() +
            this._section('回复丰富性算法 (narration)') +
            this._check('启用清洗算法', 'llm.narration.enabled', true,
                '关闭后不做水词清洗，也不更新平滑得分') +
            this._check('分数记录', 'llm.narration.score_log_enabled', false,
                '开启后把每次对话的原始/平滑得分按启动时间分组写入 character/memory/llm_response_score.json') +
            this._section('平滑得分（EWMA）') +
            this._num('初始得分 S0', 'llm.narration.initial_score', 70, 0, 100, 1) +
            this._num('下降惯性系数 λ_down', 'llm.narration.lambda_down', 0.75, 0, 1, 0.05,
                'Raw < S 时使用，越大下降越慢') +
            this._num('上升惯性系数 λ_up', 'llm.narration.lambda_up', 0.55, 0, 1, 0.05,
                'Raw > S 时使用，越小上升越快') +
            this._num('相等惯性系数 λ_equal', 'llm.narration.lambda_equal', 0.70, 0, 1, 0.05) +
            this._section('原始得分（Raw）') +
            this._num('水词密度阈值', 'llm.narration.density_threshold', 0.8, 0, 1, 0.05,
                '水词占比 ≥ 该值时 DensityScore 直接为 0') +
            this._num('超长阈值 L', 'llm.narration.length_threshold', 30, 1, 500, 1,
                '回复字符数超过该值开始惩罚') +
            this._num('超长惩罚系数', 'llm.narration.length_penalty_rate', 0.4, 0, 5, 0.1,
                'Penalty = (L - 阈值) × 系数') +
            this._num('超长惩罚封顶', 'llm.narration.length_penalty_cap', 20, 0, 100, 1) +
            this._section('清洗档位') +
            this._num('部分清洗上限', 'llm.narration.part_level_upper', 60, 0, 100, 1,
                'S ≥ 该值完全不清洗') +
            this._num('部分清洗下限', 'llm.narration.part_level_lower', 30, 0, 100, 1,
                '该值 ≤ S < 上限时清洗口头禅/连接词/重复短句；S < 该值全清');
    },

    // 分割符编辑器：每个符号单独展示为小块，隐藏 input 保存 | 分隔的字符串,
    splitFlagEditor(path) {
        const raw = this._val(path, ',|，|。|!|！|?|？');
        const chars = String(raw || '').split('|').filter(c => c !== '');
        const tags = chars.map(c =>
            `<span class="split-tag" data-char="${c}">${c}<button type="button" class="split-tag-remove">&times;</button></span>`
        ).join('');
        return `<div class="form-group"><label>${this._t('分割符（点击 × 删除）')}</label>
            <div class="split-flag-editor" data-split-flag-editor="${path}">
                <div class="split-tags">${tags}</div>
                <div class="split-add-row">
                    <input type="text" class="split-add-input" placeholder="${this._t('输入一个符号后回车添加')}" maxlength="2">
                </div>
                <input type="hidden" data-path="${path}" value="${raw}">
            </div>
            <div class="help-text">${this._t('每个符号单独作为一个分段点，例如逗号、句号、感叹号')}</div>
        </div>`;
    },

    // ============ CatBrain 子模块（四球分别打开） ============
    // 记忆摘要,
    _abstractFormula() {
        return `<div class="formula-box">
            <div class="formula-box-title">${this._t('记忆摘要流程')}</div>
            <div class="formula-block">
                <div class="formula-row">
                    <span class="formula-name">${this._t('触发')}</span>
                    <span class="formula-expr">${this._t('每 summary_rounds 条消息 → 摘要模型读取最近 scope_reply_limit 条回复')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('写入')}</span>
                    <span class="formula-expr">${this._t('单次最多 max_events 个事件；每个事件最多 tags_limit 个标签')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('排序')}</span>
                    <span class="formula-expr">Final = Fused × (1 + w<sub>ev</sub>·(E−0.5)) × (1 + w<sub>rec</sub>·(R−0.5)) × (1 + w<sub>acc</sub>·(A−0.5))</span>
                    <span class="formula-cond">${this._t('启用证据排序时生效：E=证据归一化，R=新近度，A=准确度')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('证据')}</span>
                    <span class="formula-expr">E = rein·0.5<sup>Δt/rein_half</sup> − disp·0.5<sup>Δt/disp_half</sup></span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('归档')}</span>
                    <span class="formula-expr">${this._t('E ≤ archive_threshold 且负分持续 archive_days 天 → 归档候选')}</span>
                </div>
                <div class="formula-row">
                    <span class="formula-name">${this._t('召回')}</span>
                    <span class="formula-expr">${this._t('相关度 ≥ 本次最高相关度 × recall_gate_ratio → 进入提示词；最多 summary_top_limit 条')}</span>
                </div>
            </div>
            <div class="formula-params">${this._t('summary_rounds 按消息行数计（user/assistant 各一条）；标签通道和 RRF 融合决定“先找什么”，证据/新近/准确度只在启用证据排序后作为乘数微调；证据分会随半衰期自然衰减，避免旧记忆永远压新记忆。')}</div>
        </div>`;
    },

    catbrain_abstract() {
        const ab = this._val('catbrain.abstract_mem.llm_type', 'deepseek');
        const helpApi = this._t('API Key / Base URL 在「基本设置 → API 平台」的「记忆摘要」/「记忆审查」节点配置；这里只配模型参数，避免两处输入框打架');
        let h = this._abstractFormula();
        h += `<div class="modal-tabs">
            <button type="button" class="modal-tab active" data-tab="ab_basic">${this._t('基础')}</button>
            <button type="button" class="modal-tab" data-tab="ab_write">${this._t('写入')}</button>
            <button type="button" class="modal-tab" data-tab="ab_rank">${this._t('检索排序')}</button>
            <button type="button" class="modal-tab" data-tab="ab_evidence">${this._t('证据')}</button>
            <button type="button" class="modal-tab" data-tab="ab_behavior">${this._t('清理 / 共处')}</button>
            <button type="button" class="modal-tab" data-tab="ab_review">${this._t('审查')}</button>
            <button type="button" class="modal-tab" data-tab="ab_model">${this._t('模型')}</button>
        </div>`;

        h += `<div class="tab-content active" data-tab-content="ab_basic">` +
            this._section('触发与召回') +
            this._num('摘要触发条数', 'catbrain.abstract_mem.summary_rounds', 30, 1, 500, 1,
                '每累计多少条消息触发一次摘要。这里按消息行数算：user 一条、assistant 一条，一轮=2 条；不是“对话轮数”。') +
            this._num('摘要注入上限', 'catbrain.abstract_mem.summary_top_limit', 30, 1, 200, 1,
                '每次构造角色提示词时，最多注入多少条摘要。0 表示不限制，容易把上下文塞爆，不建议。') +
            this._num('话题更新间隔(秒)', 'catbrain.abstract_mem.topic_update_interval', 60, 1, 3600, 1,
                '后台重新判断“当前话题”的间隔。越小话题切换越跟手，但会增加模型调用。') +
            this._num('召回门槛比例', 'catbrain.abstract_mem.recall_gate_ratio', 0.1, 0, 1, 0.05,
                '召回相关度必须 ≥ 本次最高相关度 × 该比例。调大更严格（只留最相关的），调小更宽松。') +
            this._check('启用摘要召回', 'catbrain.abstract_mem.recall_enabled', true,
                '关闭后只继续写入摘要，不再把摘要召回进角色提示词；适合只做记忆归档、不参与聊天的场景。') +
            this._num('单次召回月数上限', 'catbrain.abstract_mem.recall_months_limit', 3, 0, 24, 1,
                '召回判定模型一次最多返回几个月。0=不限制月数；它只限制一次回忆的月份数量，不是记忆库的保留期限。') +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="ab_write">` +
            this._section('摘要写入') +
            this._num('单次最多事件数', 'catbrain.abstract_mem.max_events', 10, 1, 100, 1,
                '一次摘要最多写入多少个事件。防止一段长对话一次刷出几十条记忆，把库撑爆。') +
            this._num('附带近期记忆条数', 'catbrain.abstract_mem.recent_memory_lines', 12, 0, 100, 1,
                '摘要提示词里附带多少条“已记忆要点”，让模型知道哪些已经记过、避免重复写入。0=不附带。') +
            this._num('单事件标签上限', 'catbrain.abstract_mem.tags_limit', 3, 1, 20, 1,
                '每个事件最多生成几个标签。标签用于召回和共处强化，太多会稀释匹配。') +
            this._num('检索词条上限', 'catbrain.abstract_mem.grep_limit', 10, 1, 100, 1,
                '摘要工具单次 grep 最多返回多少条历史原文。') +
            this._num('工具调用最大轮数', 'catbrain.abstract_mem.tool_rounds', 80, 1, 500, 1,
                '摘要模型最多进行多少轮工具调用（grep/召回/判断/写入）。太小可能写不完，太大可能空转。') +
            this._num('单次范围回复上限', 'catbrain.abstract_mem.scope_reply_limit', 80, 1, 500, 1,
                '每次摘要最多读取多少条历史回复作为上下文。') +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="ab_rank">` +
            this._section('检索与排序') +
            this._check('启用证据排序', 'catbrain.abstract_mem.rank_use_evidence', false,
                '开启后，在相关度排序之后再乘上证据/新近度/准确度权重；关闭则只按相关度（RRF）排序。') +
            this._num('证据分饱和上限', 'catbrain.abstract_mem.rank_evidence_saturation', 5.0, 0.1, 100, 0.1,
                '证据分归一化上限：达到该值就按满分算，避免老记忆因历史累计分过高而一票通吃。') +
            this._num('新近度半衰期(天)', 'catbrain.abstract_mem.rank_recency_half_life_days', 14, 1, 3650, 1,
                '新近度每过这么多天衰减一半。越小越偏向近期记忆，越大越看重旧记忆。') +
            this._num('证据权重', 'catbrain.abstract_mem.rank_w_evidence', 0.1, 0, 1, 0.05,
                'Final 乘数里证据分的权重；0=不参与。') +
            this._num('新近权重', 'catbrain.abstract_mem.rank_w_recency', 0.0, 0, 1, 0.05,
                '新近度的权重；0=不参与。') +
            this._num('准确度权重', 'catbrain.abstract_mem.rank_w_accuracy', 0.1, 0, 1, 0.05,
                '准确度的权重；0=不参与。') +
            this._num('RRF K', 'catbrain.abstract_mem.rank_rrf_k', 20, 1, 200, 1,
                'RRF 融合常数。越大各通道排名越平均，越小越偏向某个通道的头部结果。') +
            this._num('标签通道权重', 'catbrain.abstract_mem.rank_w_tag', 2.0, 0, 10, 0.5,
                '标签命中通道在 RRF 里的权重。越大越优先标签完全匹配的记忆。') +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="ab_evidence">` +
            this._section('证据衰减') +
            this._num('强化值半衰期(天)', 'catbrain.abstract_mem.evidence.rein_half_life_days', 30, 1, 3650, 1,
                '强化值每过这么多天衰减一半；越大，正面记忆越持久。') +
            this._num('质疑值半衰期(天)', 'catbrain.abstract_mem.evidence.disp_half_life_days', 180, 1, 3650, 1,
                '质疑值每过这么多天衰减一半；越大，负面/矛盾印象越难消退。') +
            this._num('归档候选阈值', 'catbrain.abstract_mem.evidence.archive_threshold', -2.0, -10, 10, 0.1,
                '净证据分 ≤ 该值时进入归档候选。负数越大越容易归档，正数则几乎不归档。') +
            this._num('负分持续天数后归档', 'catbrain.abstract_mem.evidence.archive_days', 14, 1, 365, 1,
                '连续低于阈值多少天后真正归档；避免一次误判就把记忆删掉。') +
            this._section('信号增量') +
            this._num('same 强化增量', 'catbrain.abstract_mem.evidence.same_delta', 0.5, 0, 10, 0.1,
                '判定为同一件事时，强化值增加多少。') +
            this._num('opposite 质疑增量', 'catbrain.abstract_mem.evidence.opposite_delta', 1.0, 0, 10, 0.1,
                '判定为矛盾/否定时，质疑值增加多少。') +
            this._num('复述强化增量', 'catbrain.abstract_mem.evidence.same_recite_delta', 0.1, 0, 10, 0.1,
                '用户复述已有记忆时额外增加的强化值；通常很小，用来区分“强调”和“第一次说”。') +
            this._section('准确度（1/3/5 档）') +
            this._num('same 准确度增量', 'catbrain.abstract_mem.accuracy.same_increment', 1, 0, 5, 1,
                '同一件事判定正确时，accuracy 增加多少；上限 5。') +
            this._num('opposite 准确度减量', 'catbrain.abstract_mem.accuracy.opposite_decrement', 2, 0, 5, 1,
                '矛盾判定时，accuracy 减少多少；下限 1。') +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="ab_behavior">` +
            this._section('临时约定清理') +
            this._check('开启临时约定清理', 'catbrain.abstract_mem.temp_promise.enabled', true,
                '摘要时顺带检查带 temp_promise 标签的约定是否已完成/过期，完成后不再反复提醒。') +
            this._num('每次最多判定条数', 'catbrain.abstract_mem.temp_promise.max_items', 30, 1, 200, 1,
                '每次清理最多检查多少条临时约定。') +
            this._section('共处强化') +
            this._check('开启共处强化', 'catbrain.abstract_mem.cooccur.enabled', true,
                '本次新事件与旧记忆共享标签时，给旧记忆小幅加强，模拟“一起出现过”。') +
            this._num('共处强化增量', 'catbrain.abstract_mem.cooccur.delta', 0.1, 0, 10, 0.1,
                '每条共享标签的旧记忆增加多少强化值。') +
            this._num('每次最多强化条数', 'catbrain.abstract_mem.cooccur.max_boost', 5, 0, 100, 1,
                '一次摘要最多强化多少条旧记忆，防止一篇长文把整库都加强。') +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="ab_review">` +
            this._section('记忆审查') +
            this._check('开启记忆审查', 'catbrain.abstract_mem.review.enabled', true,
                '摘要写入前，用审查模型检查事件内容/准确度；关闭则摘要模型直接写入。') +
            this._select('记忆审查 LLM 类型', 'catbrain.abstract_mem.review.llm_type', [
                { value: '', label: '跟随摘要后端' },
                { value: 'deepseek', label: 'DeepSeek' },
                { value: 'aliyun', label: '阿里云' },
                { value: 'gemini', label: 'Gemini' },
                { value: 'meowllm', label: 'MeowLLM' }
            ], '', '留空=跟随摘要后端；也可以指定独立后端做二次审查。') +
            this._text('审查模型', 'catbrain.abstract_mem.review.model', '',
                '留空则复用摘要后端对应模型；只在审查使用独立后端时需要填。') +
            this._num('审查 max_tokens', 'catbrain.abstract_mem.review.max_tokens', 2048, 1, 32768, 16) +
            this._num('工具调用最大次数', 'catbrain.abstract_mem.review.max_rounds', 3, 1, 20, 1,
                '审查模型最多调用多少次审查工具；太大可能拖慢摘要。') +
            '<div class="help-text">' + helpApi + '</div>' +
            `</div>`;

        h += `<div class="tab-content" data-tab-content="ab_model">` +
            this._section('摘要模型') +
            this._llmTypeSelect('摘要 LLM 类型', 'catbrain.abstract_mem.llm_type', ab) +
            '<div class="help-text">' + helpApi + '</div>' +
            this._fold('DeepSeek',
                this._text('模型', 'catbrain.abstract_mem.deepseek.model', 'deepseek-chat') +
                this._num('温度', 'catbrain.abstract_mem.deepseek.temperature', 0.7, 0, 2, 0.1) +
                this._num('max_tokens', 'catbrain.abstract_mem.deepseek.max_tokens', 2048, 1, 32768, 16)) +
            this._fold(this._t('阿里云'),
                this._text('模型', 'catbrain.abstract_mem.aliyun.model', 'qwen-plus') +
                this._num('温度', 'catbrain.abstract_mem.aliyun.temperature', 0.7, 0, 2, 0.1) +
                this._num('max_tokens', 'catbrain.abstract_mem.aliyun.max_tokens', 2048, 1, 32768, 16)) +
            this._fold('Gemini',
                this._text('模型', 'catbrain.abstract_mem.gemini.model', 'gemini-3.6-flash') +
                this._num('温度', 'catbrain.abstract_mem.gemini.temperature', 0.7, 0, 2, 0.1) +
                this._num('max_tokens', 'catbrain.abstract_mem.gemini.max_tokens', 2048, 1, 32768, 16)) +
            `</div>`;
        return h;
    },

    // 价值观,
    catbrain_values() {
        const cv = this._val('catbrain.cat_values.llm_type', 'deepseek');
        const cvOn = (k) => cv === k ? ' active' : '';
        let h = this._section('价值观 (cat_values)');
        h += this._llmTypeSelect('价值观 LLM 类型', 'catbrain.cat_values.llm_type', cv);
        h += `<div class="modal-tabs">
            <button class="modal-tab${cvOn('deepseek')}" data-tab="values_ds">DeepSeek</button>
            <button class="modal-tab${cvOn('aliyun')}" data-tab="values_aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab${cvOn('gemini')}" data-tab="values_gemini">Gemini</button>
        </div>`;
        h += `<div class="tab-content${cvOn('deepseek')}" data-tab-content="values_ds">` +
            this._password('API Key', 'catbrain.cat_values.deepseek.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'catbrain.cat_values.deepseek.model', 'deepseek-chat') +
            `</div>`;
        h += `<div class="tab-content${cvOn('aliyun')}" data-tab-content="values_aliyun">` +
            this._password('API Key', 'catbrain.cat_values.aliyun.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'catbrain.cat_values.aliyun.model', 'qwen-plus') +
            `</div>`;
        h += `<div class="tab-content${cvOn('gemini')}" data-tab-content="values_gemini">` +
            this._password('API Key', 'catbrain.cat_values.gemini.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'catbrain.cat_values.gemini.model', 'gemini-3.6-flash') +
            `</div>`;
        h += this._num('价值观 max_tokens', 'catbrain.cat_values.max_tokens', 8192, 1, 65536, 16) +
            this._num('工具调用最大轮数', 'catbrain.cat_values.max_tool_rounds', 100, 1, 1000, 1) +
            this._num('计时检查间隔(秒)', 'catbrain.cat_values.timer_check_seconds', 300, 1, 86400, 1) +
            this._num('更新触发间隔(小时)', 'catbrain.cat_values.update_interval_hours', 12, 1, 720, 1) +
            this._num('哲思触发冷却(分钟)', 'catbrain.cat_values.philosophy_cooldown_minutes', 30, 1, 1440, 1);
        const sr = this._val('catbrain.cat_values.second_review.llm_type', 'aliyun');
        h += this._check('启用二次审查', 'catbrain.cat_values.second_review.enabled', false);
        h += this._llmTypeSelect('二次审查 LLM 类型', 'catbrain.cat_values.second_review.llm_type', sr);
        h += this._fold('二次审查 · DeepSeek',
            this._password('API Key', 'catbrain.cat_values.second_review.deepseek.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.second_review.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'catbrain.cat_values.second_review.deepseek.model', 'deepseek-chat'));
        h += this._fold('二次审查 · ' + this._t('阿里云'),
            this._password('API Key', 'catbrain.cat_values.second_review.aliyun.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.second_review.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'catbrain.cat_values.second_review.aliyun.model', 'qwen-plus'));
        h += this._fold('二次审查 · Gemini',
            this._password('API Key', 'catbrain.cat_values.second_review.gemini.api_key', '') +
            this._text('Base URL', 'catbrain.cat_values.second_review.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'catbrain.cat_values.second_review.gemini.model', 'gemini-3.6-flash'));
        return h;
    },

    // 用户记忆,
    catbrain_usermem() {
        const um = this._val('catbrain.user_memory.llm_type', 'deepseek');
        const umOn = (k) => um === k ? ' active' : '';
        let h = this._section('用户记忆 (user_memory)');
        h += this._num('用户信息更新轮数', 'catbrain.user_memory.update_rounds', 50, 1, 1000, 1);
        h += this._llmTypeSelect('用户记忆 LLM 类型', 'catbrain.user_memory.llm_type', um);
        h += `<div class="modal-tabs">
            <button class="modal-tab${umOn('deepseek')}" data-tab="usermem_ds">DeepSeek</button>
            <button class="modal-tab${umOn('aliyun')}" data-tab="usermem_aliyun">${this._t('阿里云')}</button>
            <button class="modal-tab${umOn('gemini')}" data-tab="usermem_gemini">Gemini</button>
        </div>`;
        h += `<div class="tab-content${umOn('deepseek')}" data-tab-content="usermem_ds">` +
            this._password('API Key', 'catbrain.user_memory.deepseek.api_key', '') +
            this._text('Base URL', 'catbrain.user_memory.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'catbrain.user_memory.deepseek.model', 'deepseek-chat') +
            `</div>`;
        h += `<div class="tab-content${umOn('aliyun')}" data-tab-content="usermem_aliyun">` +
            this._password('API Key', 'catbrain.user_memory.aliyun.api_key', '') +
            this._text('Base URL', 'catbrain.user_memory.aliyun.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') +
            this._text('模型', 'catbrain.user_memory.aliyun.model', 'qwen-plus') +
            `</div>`;
        h += `<div class="tab-content${umOn('gemini')}" data-tab-content="usermem_gemini">` +
            this._password('API Key', 'catbrain.user_memory.gemini.api_key', '') +
            this._text('Base URL', 'catbrain.user_memory.gemini.base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/') +
            this._text('模型', 'catbrain.user_memory.gemini.model', 'gemini-3.6-flash') +
            `</div>`;
        h += this._num('用户记忆温度', 'catbrain.user_memory.temperature', 0.7, 0, 2, 0.1) +
            this._num('用户记忆 max_tokens', 'catbrain.user_memory.max_tokens', 2048, 1, 32768, 16);
        return h;
    },
    _llmTypeSelect(label, path, current) {
        return `<div class="form-group"><label>${label}</label>
            <select data-path="${path}" onchange="Config.toggleMeowLLMLink(this)">
                <option value="deepseek" ${current === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                <option value="aliyun" ${current === 'aliyun' ? 'selected' : ''}>${this._t('阿里云')}</option>
                <option value="gemini" ${current === 'gemini' ? 'selected' : ''}>Gemini</option>
                <option value="meowllm" ${current === 'meowllm' ? 'selected' : ''}>MeowLLM</option>
            </select>${this._mllLink(current === 'meowllm')}</div>`;
    },
    _mllStyle() {
        return `<style>
            .mll-jump{display:inline-flex;align-items:center;gap:8px;padding:10px 20px;border:none;border-radius:12px;
                background:linear-gradient(160deg,var(--pink-main,#FFB6C1),var(--pink-deep,#FF69B4));color:#fff;
                font-size:13px;font-family:inherit;line-height:1;cursor:pointer;
                box-shadow:0 4px 14px var(--shadow-deep,rgba(255,105,180,.3));
                transition:transform .08s ease,filter .15s ease}
            .mll-jump:hover{filter:brightness(1.05)}
            .mll-jump:active{transform:translateY(1px)}
            .mll-tip{margin-top:9px;padding:13px 15px;border:1px dashed var(--pink-main,#FFB6C1);border-radius:14px;
                background:var(--pink-light,#FFF0F5);color:var(--text-light,#888);font-size:12px;line-height:1.8}
        </style>`;
    },
    _mllLink(show) {
        return `${this._mllStyle()}<div class="mll-tip mll-hint" style="display:${show ? '' : 'none'}">
            <div>${this._t('MeowLLM 的连接、引擎（DualStream）、生成、思考、δ-mem 记忆等参数，统一在子服务里配置。')}</div>
            <div style="margin-top:9px">
                <button type="button" class="mll-jump" onclick="window.open('/meowllm.html','_blank')">
                    <span>🐾</span><span>${this._t('打开 MeowLLM 配置页')}</span>
                </button>
            </div>
        </div>`;
    },
    toggleMeowLLMLink(sel) {
        const group = sel.closest('.form-group');
        if (!group) return;
        const hint = group.querySelector('.mll-hint');
        if (hint) hint.style.display = sel.value === 'meowllm' ? '' : 'none';
    },
    llm_meowllmContent() {
        return `${this._mllStyle()}
            <div class="mll-tip">
                <div style="font-size:13px;color:var(--pink-deep,#FF69B4);margin-bottom:6px;font-weight:600">${this._t('MeowLLM 参数在独立页面里配置')}</div>
                <div>${this._t('连接、引擎（DualStream）、生成、思考、δ-mem 记忆与落盘等全部参数都收在子服务（.vendor/.MeowLLM/config.yml），这里不再重复一份，避免两处配置打架。配置页左侧有侧边栏，DualStream 引擎和 δ-mem 记忆是分开的两块。')}</div>
                <div style="margin-top:12px">
                    <button type="button" class="mll-jump" onclick="window.open('/meowllm.html','_blank')">
                        <span>🐾</span><span>${this._t('打开 MeowLLM 配置页')}</span>
                    </button>
                </div>
            </div>`;
    },
    llm_meowllmPane(active) {
        return `<div class="tab-content${active === 'meowllm' ? ' active' : ''}" data-tab-content="meowllm" id="meowllmPane">
            ${this.llm_meowllmContent()}
        </div>`;
    },
    catbrain_rulesbreak(armor) {
        const a = armor || {};
        const armorPrompt = a.prompt || '';
        const armorNapcat = a.prompt_napcat || '';
        const armorNsfw = a.nsfw_personality || '';
        const armorNsfwHobby = a.nsfw_hobby || '';
        const armorNsfwFavorite = a.nsfw_favorite || '';
        const armorNsfwWordNorm = a.nsfw_word_norm || '';
        let h = this._section('原则词（破甲词）');
        h += this._check('QQ 启用', 'rulebreak.enabled_qq', true) +
            this._check('主线程启用', 'rulebreak.enabled_msg', false) +
            this._num('触发好感度下限', 'rulebreak.affinity_min', 3, -10, 10, 1,
                '仅好感度大于该值的用户才允许触发原则词注入');
        h += `<div class="form-group"><label>${this._t('主线程原则词')}</label>
                <textarea id="armorPromptInput" class="auto-grow" rows="3" placeholder="${this._t('守底线的原则词...')}">${this._esc(armorPrompt)}</textarea>
                <div class="help-text">${this._t('主线程检测到色情内容时，插入 system prompt 顶部')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('QQ 原则词')}</label>
                <textarea id="armorNapcatPromptInput" class="auto-grow" rows="3" placeholder="${this._t('守底线的原则词...')}">${this._esc(armorNapcat)}</textarea>
                <div class="help-text">${this._t('QQ 私聊/群聊 @ 检测到色情内容时，插入 system prompt 顶部')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('NSFW 性格（触发时覆盖角色性格）')}</label>
                <textarea id="armorNsfwInput" class="auto-grow" rows="3" placeholder="${this._t('触发破甲词时替换角色卡「角色性格」的内容...')}">${this._esc(armorNsfw)}</textarea>
                <div class="help-text">${this._t('检测到色情内容触发破甲词时，用此内容替换角色卡「角色性格」行，消除调皮/生气等性格冲突')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('NSFW 爱好（触发时覆盖角色爱好）')}</label>
                <textarea id="armorNsfwHobbyInput" class="auto-grow" rows="2" placeholder="${this._t('触发破甲词时替换角色卡「角色爱好」的内容...')}">${this._esc(armorNsfwHobby)}</textarea>
                <div class="help-text">${this._t('检测到色情内容触发破甲词时，用此内容替换角色卡「角色爱好」行')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('NSFW 最喜欢的东西（触发时覆盖）')}</label>
                <textarea id="armorNsfwFavoriteInput" class="auto-grow" rows="2" placeholder="${this._t('触发破甲词时替换角色卡「最喜欢的东西」的内容...')}">${this._esc(armorNsfwFavorite)}</textarea>
                <div class="help-text">${this._t('检测到色情内容触发破甲词时，用此内容替换角色卡「最喜欢的东西」行')}</div>
            </div>`;
        h += `<div class="form-group"><label>${this._t('NSFW 字数规范（触发时覆盖字数限制）')}</label>
                <textarea id="armorNsfwWordNormInput" class="auto-grow" rows="2" placeholder="${this._t('触发破甲词时替换默认字数限制，如：每次回复至少80字，详细描写...')}">${this._esc(armorNsfwWordNorm)}</textarea>
                <div class="help-text">${this._t('检测到色情内容触发破甲词时，用此内容替换「每次回复10个字左右，严格控制在20字以内」')}</div>
            </div>`;
        h += this._section('审查端口（独立 DeepSeek）') +
            this._password('API Key', 'rulebreak.deepseek.api_key', '') +
            this._text('Base URL', 'rulebreak.deepseek.base_url', 'https://api.deepseek.com/v1') +
            this._text('模型', 'rulebreak.deepseek.model', 'deepseek-chat') +
            this._num('温度', 'rulebreak.deepseek.temperature', 0.3, 0, 2, 0.1) +
            this._num('max_tokens', 'rulebreak.deepseek.max_tokens', 512, 1, 4096, 16);
        return h;
    },

    // ============ TTS（含 SoVITS 服务端 + 参考音频 + 模型配置） ============,
});
