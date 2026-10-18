/**
 * MeowLLM 配置页 —— 参数表（纯数据，不含逻辑）
 *
 * 这里是**唯一**的参数定义处：分组、字段、类型、默认值、说明都写在这。
 * 加一个参数只需在对应 group 的 fields 里加一行，render/collect 会自动带上。
 *
 * 字段结构：
 *   { path, label, type, def?, help, options?, min?, max?, step?, placeholder? }
 *
 * type 取值：
 *   text     —— 单行文本
 *   number   —— 数字（配合 min/max/step）
 *   select   —— 下拉（options: string[] 或 [{value,label}]）
 *   checkbox —— 布尔
 *   list     —— 字符串数组，界面上用逗号分隔（空 = []）
 *   path     —— 单行文本，但按"相对路径"提示（相对 .vendor/.MeowLLM/）
 *
 * 每条 path 都是 .vendor/.MeowLLM/config.yml 里 meowllm 节点下的点号路径。
 */

const MLL_SCHEMA = [
  // ============================================================ 服务
  {
    id: 'server',
    icon: '🐾',
    title: '服务与连接',
    desc: '监听地址、端口与超时。主项目通过 /api/meowllm/config 读写这一份，'
      + '启动时按 ports.state_dir 里的 port.json 找到真实端口。',
    groups: [
      {
        title: '监听',
        fields: [
          {
            path: 'server.host', label: '监听地址', type: 'text', def: '127.0.0.1',
            help: '默认只监听本机，主项目就在本机，够用。云端要在容器里跑就必须 0.0.0.0；'
              + '本机要接云端只用 SSH 隧道，隧道出口仍是 127.0.0.1，所以本地这里保持默认。',
          },
          {
            path: 'server.port', label: '端口', type: 'number', def: 18100, min: 1, max: 65535, step: 1,
            help: '主项目据此拼出 base_url。被占用时会按「端口回退数」往后自动找，'
              + '真实端口写进 paths.state_dir/port.json，所以改端口不用改主项目配置。',
          },
          {
            path: 'server.port_fallback', label: '端口回退数', type: 'number', def: 9, min: 0, max: 64, step: 1,
            help: '在 [端口, 端口+回退数) 区间里找第一个空闲端口。设 0 = 端口被占就直接报错，不再自动漂移。',
          },
          {
            path: 'server.request_timeout', label: '单次请求超时（秒）', type: 'number', def: 120, min: 5, max: 3600, step: 5,
            help: '一次 chat 完成的硬超时。8B 首字可能要几十秒，别设太小。',
          },
        ],
      },
      {
        title: '对外标识',
        fields: [
          {
            path: 'model.name', label: '模型名', type: 'text', def: 'meowllm-local',
            help: 'OpenAI 协议里 model 字段的回显值，不参与任何推理逻辑；主项目拿它当请求标识，'
              + '改名只影响日志与回显。',
          },
        ],
      },
    ],
  },

  // ==================================================== 引擎（DualStream）
  {
    id: 'dualstream',
    icon: '⚡',
    title: '引擎 · DualStream',
    desc: '真实模型推理的引擎。这里的参数只在 engine.kind = dualstream 时生效；'
      + '改完必须重启 MeowLLM 进程（权重在启动时一次性加载）。',
    groups: [
      {
        title: '引擎选择',
        fields: [
          {
            path: 'engine.kind', label: '引擎类型', type: 'select', def: 'dualstream',
            options: [
              { value: 'dualstream', label: 'dualstream —— 真实双流模型' },
              { value: 'stub', label: 'stub —— 零权重假引擎（只验管道）' },
            ],
            help: 'dualstream 走 model_dir 里的权重做真推理，是唯一能验证效果的引擎；'
              + 'stub 不发一次前向，只回固定串，用来验流式/时序/落盘这些管道。'
              + '两种都必须出现在下面的 safety.allow_engine 白名单里，否则启动被拒。',
          },
          {
            path: 'engine.dualstream.model_dir', label: '权重目录', type: 'path',
            def: 'models/Qwen3-0.6B', placeholder: 'models/Qwen3-0.6B',
            help: '相对 .vendor/.MeowLLM/ 的路径（也接受绝对路径）。目录里要有 config.json、'
              + 'tokenizer 文件和一个或多个 *.safetensors。本机现有：models/Qwen3-0.6B。',
          },
        ],
      },
      {
        title: '加载',
        fields: [
          {
            path: 'engine.dualstream.device', label: '设备', type: 'select', def: 'cuda',
            options: ['cuda', 'cpu'],
            help: 'cuda = GPU（必须）；cpu 只用来在没有显卡的机器上验管道，速度慢几个数量级。',
          },
          {
            path: 'engine.dualstream.dtype', label: '精度', type: 'select', def: 'bfloat16',
            options: ['bfloat16', 'float16', 'float32'],
            help: '权重与激活的数值精度。bfloat16 最稳（Ampere 及以后都支持）；'
              + '老卡不支持 bf16 时用 float16（可能出现溢出）；float32 只在 CPU 上选，显存翻倍。',
          },
        ],
      },
      {
        title: '双流时序（分段说话 / 思考）',
        fields: [
          {
            path: 'engine.dualstream.language', label: '探针语言', type: 'select', def: 'en',
            options: [
              { value: 'en', label: 'en —— 英文提示词' },
              { value: 'zh', label: 'zh —— 中文提示词' },
            ],
            help: '双流探针（判断「这一段说完了吗、还要不要说」）用的角色扮演提示词语言。'
              + '小模型对英文提示词更敏感，所以默认 en；纯中文对话可试 zh。',
          },
          {
            path: 'engine.dualstream.probe_kind', label: '探针语义', type: 'select', def: 'roleplay',
            options: [
              { value: 'roleplay', label: 'roleplay —— 角色扮演分段' },
              { value: 'math', label: 'math —— 数学推理分步' },
            ],
            help: '探针问「要不要继续」的语境。聊天用 roleplay；只有做推理实验才换 math。',
          },
          {
            path: 'engine.dualstream.probe_every_tokens', label: '探针间隔（tokens）', type: 'number',
            def: 20, min: 1, max: 512, step: 1,
            help: '每生成多少个 token 插一次探针。数值越小切换越灵敏，但探针本身要算，'
              + '整体吞吐会下降；20 是实测比较均衡的值。',
          },
          {
            path: 'engine.dualstream.max_segments', label: '最多说几段', type: 'number',
            def: 6, min: 1, max: 32, step: 1,
            help: '一轮回复最多切成几段说出来（像人一句一句讲）。1 = 不分段，一次性吐完。',
          },
          {
            path: 'engine.dualstream.stop_after_no', label: '连续几个 no 收尾', type: 'number',
            def: 2, min: 1, max: 8, step: 1,
            help: '探针连续这么多次判断「不用再说了」就结束这一轮。调大 = 更啰嗦，调小 = 更容易说半句就停。',
          },
          {
            path: 'engine.dualstream.fast_prefill', label: 'SDPA 快路', type: 'checkbox', def: true,
            help: 'prompt 预处理走 PyTorch SDPA 融合核，长 prompt 明显更快。'
              + '只有在数值异常（nan/花字）或显存吃紧时才关掉换回手写 attention。',
          },
        ],
      },
    ],
  },

  // ============================================================ 上下文
  {
    id: 'context',
    icon: '📐',
    title: '上下文与生成',
    desc: '窗口大小、裁剪上限与采样参数。这些是「怎么说话」的部分；'
      + '和记忆（δ-mem）互不影响。',
    groups: [
      {
        title: '窗口',
        fields: [
          {
            path: 'context.n_ctx', label: '上下文窗口（tokens）', type: 'number',
            def: 8192, min: 256, max: 131072, step: 256,
            help: '模型一次能看的总长度。它同时是 δ-mem 状态递推的窗口长度 —— '
              + '改了窗口，记忆的写入方式也要跟着一致。',
          },
          {
            path: 'context.n_threads', label: 'CPU 线程数', type: 'number', def: 0, min: 0, max: 128, step: 1,
            help: '0 = 自动（按物理核数）。只有 CPU 推理时才真正用得上。',
          },
          {
            path: 'context.max_prompt_tokens', label: '单流 prompt 上限', type: 'number',
            def: 4096, min: 128, max: 131072, step: 128,
            help: '单流模式下一轮最多喂多少 token，超了从最早处裁。设 0 = 不额外裁剪（只受 n_ctx 限制）。',
          },
          {
            path: 'context.dual_max_prompt_tokens', label: '双流 prompt 上限', type: 'number',
            def: 2048, min: 128, max: 131072, step: 128,
            help: '双流模式的上限，要给它留出思考和分段的预算。设太大会把思考位挤掉。',
          },
        ],
      },
      {
        title: '采样',
        fields: [
          {
            path: 'gen.temperature', label: '温度', type: 'number', def: 0.8, min: 0, max: 3, step: 0.05,
            help: '越高越发散。角色扮演 0.7~0.9；要稳定复现就调到 0（此时等于贪心解码）。',
          },
          {
            path: 'gen.top_p', label: 'Top P', type: 'number', def: 0.9, min: 0, max: 1, step: 0.05,
            help: '核采样：只在累计概率前 P 的候选里抽。0.9 是常见折中。',
          },
          {
            path: 'gen.top_k', label: 'Top K', type: 'number', def: 40, min: 0, max: 1000, step: 1,
            help: '只在概率最高的 K 个候选里抽。0 = 不限。',
          },
          {
            path: 'gen.repeat_penalty', label: '重复惩罚', type: 'number', def: 1.05, min: 0.5, max: 2, step: 0.01,
            help: '1.0 = 不惩罚；越大越不容易重复同一个词，但过大会让句子变生硬。',
          },
          {
            path: 'gen.talk_max_tokens', label: '正文最大 tokens', type: 'number',
            def: 256, min: 1, max: 8192, step: 16,
            help: '只管正文（不含思考）。设太小回复会被硬生生截断。',
          },
          {
            path: 'gen.seed', label: '随机种子', type: 'text', def: null, placeholder: '留空 = 每次随机',
            help: '填整数可复现同一段输出（调参对比时很有用）。留空 = 每次都随机。',
          },
          {
            path: 'gen.stop', label: '停止词', type: 'list', def: [],
            help: '逗号分隔。生成到其中任意一个就停。留空 = 不设（推荐，交给模型自己收尾）。',
          },
        ],
      },
      {
        title: '思考档位',
        fields: [
          {
            path: 'thinking.default_level', label: '默认档位', type: 'select', def: 'off',
            options: [
              { value: 'off', label: 'off —— 不思考（最快）' },
              { value: 'low', label: 'low —— 短思考' },
              { value: 'medium', label: 'medium —— 默认思考' },
              { value: 'high', label: 'high —— 长思考' },
            ],
            help: '请求里没显式给 thinking_level 时用这一档。主项目默认发 off（聊天不想要思考延时）。',
          },
          {
            path: 'thinking.budgets.off', label: 'off 预算（tokens）', type: 'number',
            def: 0, min: 0, max: 8192, step: 32,
            help: '这一档最多给多少思考 token。off 一般是 0。',
          },
          {
            path: 'thinking.budgets.low', label: 'low 预算（tokens）', type: 'number',
            def: 256, min: 0, max: 8192, step: 32,
            help: 'low 档的思考预算上限。',
          },
          {
            path: 'thinking.budgets.medium', label: 'medium 预算（tokens）', type: 'number',
            def: 768, min: 0, max: 8192, step: 32,
            help: 'medium 档的思考预算上限。',
          },
          {
            path: 'thinking.budgets.high', label: 'high 预算（tokens）', type: 'number',
            def: 2048, min: 0, max: 32768, step: 32,
            help: 'high 档的思考预算上限。思考越长首字越慢。',
          },
          {
            path: 'thinking.force_off_when_tools', label: '带工具时强制关思考', type: 'checkbox', def: true,
            help: '请求里带 tools 时忽略档位、一律不思考。工具调用要求严格 JSON，'
              + '思考内容容易把格式带跑，建议保持开。',
          },
        ],
      },
    ],
  },

  // ====================================================== δ-mem 记忆（参数）
  {
    id: 'dmem',
    icon: '🧠',
    title: '记忆 · δ-mem',
    desc: '论文 δ-mem 的在线联想记忆。**参数只有一份（所有用户共享），状态一人一份** —— '
      + '每个用户的 r×r 状态矩阵单独落盘在自己的目录里。'
      + '这里的数值必须和训练时一致，否则权重形状对不上，引擎会降级成「不挂记忆」。',
    groups: [
      {
        title: '开关与权重',
        fields: [
          {
            path: 'memory.delta_mem.enabled', label: '启用 δ-mem', type: 'checkbox', def: false,
            help: '总开关。关掉时引擎完全不碰记忆，行为与没装这个功能完全一致 —— '
              + '所以随时可以安全降级。',
          },
          {
            path: 'memory.delta_mem.weights', label: '权重文件', type: 'path',
            def: '', placeholder: 'models/dmem-261018/dmem.safetensors',
            help: '相对 .vendor/.MeowLLM/ 的路径。训练产物统一放 models/<run>/dmem.safetensors，'
              + '这样本地与云端的目录结构一致（云端把整个 models/ 同步过去即可）。'
              + '文件指纹会写进每个用户的状态，换权重后旧状态会被拒绝加载，防止拿错记忆。',
          },
        ],
      },
      {
        title: '结构（必须与训练一致）',
        fields: [
          {
            path: 'memory.delta_mem.rank', label: '低秩维 r', type: 'number', def: 64, min: 1, max: 256, step: 1,
            help: '状态矩阵是 r×r。越大记忆容量越大、越慢；r=64 时全部 14.68M 参数。'
              + '换 r 必须重新训练。',
          },
          {
            path: 'memory.delta_mem.n_states', label: '状态份数 N', type: 'number', def: 1, min: 1, max: 8, step: 1,
            help: '多份状态（MSW 分组投影）并行存，1 = 单份。改它等于改模型结构，必须与训练一致。',
          },
          {
            path: 'memory.delta_mem.chunk', label: '写入粒度 chunk', type: 'number', def: 16, min: 1, max: 512, step: 1,
            help: '1 = 逐 token 写（TSW，最细但最慢）；16 = 每 16 token 合成一段写（SSW，推荐）。'
              + '必须与训练一致，否则状态分布对不上。',
          },
          {
            path: 'memory.delta_mem.layers', label: '挂载层', type: 'text', def: '', placeholder: '留空 = 全层',
            help: '留空 = 挂在所有层；"8-19" = 只挂中间 12 层（省显存）；'
              + '"0,5,9" = 指定层。必须与训练一致。',
          },
          {
            path: 'memory.delta_mem.alpha', label: '注入强度 α', type: 'number', def: 16.0, min: 0, max: 512, step: 0.5,
            help: '记忆读向量注入 attention 的倍率。论文取 16；权重里学到的 log_alpha 会在加载时覆盖它。'
              + 'α 被学成 0 就意味着「白训了」，训练后可以在这儿先手排查。',
          },
          {
            path: 'memory.delta_mem.calibrate_on_load', label: '加载时定标', type: 'checkbox', def: false,
            help: '启动后用一次前向重新校准 α。会多花几秒，一般不需要；'
              + '只有在换了 backbone 或发现输出突然变怪时才开。',
          },
          {
            path: 'memory.delta_mem.alpha_scale', label: '注入强度倍数', type: 'number',
            def: 1.0, min: 0.05, max: 64, step: 0.5,
            help: '把每层学出来的 α 乘以这个倍数（1.0 = 不动）。'
              + '注意：上面那个「注入强度 α」只是**初始化值**，训练后每层都有自己的可学习 '
              + 'log_alpha（实测 ≈16），改它不会改变任何东西 —— 想调"记忆对 attention 的影响力"'
              + '只能用这个倍数。纯推理期旋钮，不改结构，随时可以乘回去。',
          },
          {
            path: 'memory.delta_mem.window', label: '写入窗口（tokens）', type: 'number',
            def: 0, min: 0, max: 131072, step: 128,
            help: '写记忆那一趟前向一次吃多少 token。0 = 跟上下文窗口一样（n_ctx）。'
              + '这个值只影响写入分块、不影响模型结构，但**建议与训练时一致**（现有权重是 1024）；'
              + '填 8192 会让一次性保留 28 层的 hidden，显存直接涨到几百 MB。',
          },
          {
            path: 'memory.delta_mem.allow_untrained', label: '权重缺失也硬挂', type: 'checkbox', def: false,
            help: '权重文件不存在时，是否仍用随机初始化把 δ-mem 挂上去。'
              + '默认关：随机权重会往 attention 里注入噪声，比"没有记忆"更糟，而且从外面看不出来。'
              + '只有单纯想验管道时才开。',
          },
        ],
      },
    ],
  },

  // ==================================================== δ-mem 记忆（存储）
  {
    id: 'dmem_store',
    icon: '💾',
    title: '记忆 · 落盘与隔离',
    desc: '状态存在哪儿、谁的能存、显存里同时留几个人的。默认布局是 '
      + 'character/userinfo/<uid>/mem/ —— 和主项目的用户目录对齐，一人一份、零交叉。',
    groups: [
      {
        title: '布局',
        fields: [
          {
            path: 'memory.delta_mem.layout', label: '存储布局', type: 'select', def: 'userinfo',
            options: [
              { value: 'userinfo', label: 'userinfo —— 每用户一个目录（推荐）' },
              { value: 'flat', label: 'flat —— 全用户堆在一个目录' },
            ],
            help: 'userinfo = character/userinfo/<uid>/mem/，删一个用户就删一个目录；'
              + 'flat 只是兼容旧状态与迁移用，多人时会互相踩。',
          },
          {
            path: 'memory.delta_mem.userinfo_dir', label: '用户目录根', type: 'path',
            def: '../../character/userinfo', placeholder: '../../character/userinfo',
            help: '相对 .vendor/.MeowLLM/ 的路径。默认指到主项目的 character/userinfo，'
              + '这样每个 uid 的记忆和它的 profile.json 是邻居，方便一起备份。',
          },
          {
            path: 'memory.delta_mem.state_dir', label: '兼容目录', type: 'path',
            def: 'character/memory/.dmem',
            help: '只有 layout=flat、或从旧布局迁移状态时才会用到。'
              + 'userinfo 布局下这里不写任何东西。',
          },
        ],
      },
      {
        title: '准入与缓存',
        fields: [
          {
            path: 'memory.delta_mem.formal_pattern', label: '正式号正则', type: 'text',
            def: '^\\d{6}$', placeholder: '^\\d{6}$',
            help: '只有匹配这个正则的 uid 才允许读写落盘状态，默认 6 位数字（如 000001）。'
              + 'temp-* 临时会话一律不落盘，避免把试聊写进长期记忆。',
          },
          {
            path: 'memory.delta_mem.strict_formal', label: '严格模式', type: 'checkbox', def: true,
            help: '开：不匹配的 uid 直接拒绝读写（含控制面调用）。'
              + '关：只记一条警告然后当「无记忆」处理。建议保持开。',
          },
          {
            path: 'memory.delta_mem.max_cached_owners', label: '显存里最多留几个用户', type: 'number',
            def: 8, min: 1, max: 256, step: 1,
            help: '状态常驻显存，超了按 LRU 卸载（下一轮再从磁盘读回来）。'
              + '群聊/多用户场景调大，单用户调到 2~4 更省显存。',
          },
          {
            path: 'memory.delta_mem.persist', label: '落盘', type: 'checkbox', def: true,
            help: '关掉就是纯内存模式：重启即丢。只有做实验对比时才关。',
          },
          {
            path: 'memory.delta_mem.backup_keep', label: '保留几份备份', type: 'number',
            def: 5, min: 0, max: 100, step: 1,
            help: '每次写入前在 mem/backup/<时间>/ 留一份，保最近 N 份。0 = 不留。'
              + '注意：这一项不在服务端默认表里，属于可选覆盖。',
          },
        ],
      },
    ],
  },

  // ============================================================ 缓存 / 队列
  {
    id: 'runtime',
    icon: '⏱',
    title: '缓存 · 队列 · 路径',
    desc: '性能相关的运行时开关。改了只影响速度，不影响模型输出内容。',
    groups: [
      {
        title: '前缀缓存',
        fields: [
          {
            path: 'cache.prefix.enabled', label: '启用前缀缓存', type: 'checkbox', def: true,
            help: '把每轮都不变的 prompt 前缀的 KV 留在显存里复用，显著降低首字延迟。'
              + '它靠「易变标记」判断前缀到哪儿为止，标记配错就会缓存失效（变慢但不会出错）。',
          },
          {
            path: 'cache.prefix.slots', label: '缓存槽位数', type: 'number', def: 4, min: 1, max: 32, step: 1,
            help: '同时保留几份不同的前缀。多人/多场景来回切时才需要 >1，槽位占显存。',
          },
          {
            path: 'cache.prefix.min_prefix_tokens', label: '最短可缓存前缀（tokens）', type: 'number',
            def: 256, min: 16, max: 8192, step: 16,
            help: '前缀短于这个长度就不折腾缓存了（收益抵不上开销）。',
          },
          {
            path: 'cache.prefix.volatile_markers', label: '易变标记', type: 'list', def: [],
            help: '逗号分隔。prompt 里出现这些行说明「后面每轮都会变」，缓存到它之前为止。'
              + '默认包含时间、情绪、心里装着的事这几行。',
          },
        ],
      },
      {
        title: '会话缓存',
        fields: [
          {
            path: 'cache.session.enabled', label: '启用会话缓存', type: 'checkbox', def: true,
            help: '按 session_id 记住同一段对话的 KV 进度。主项目按 uid 发 session_id 时收益最大。',
          },
          {
            path: 'cache.session.max_sessions', label: '最多几个会话', type: 'number',
            def: 8, min: 1, max: 128, step: 1,
            help: '同时挂在显存里的会话数，超了按最久没用淘汰。',
          },
          {
            path: 'cache.session.ttl_seconds', label: '会话有效期（秒）', type: 'number',
            def: 3600, min: 60, max: 86400, step: 60,
            help: '这么久没用过的会话直接释放。',
          },
        ],
      },
      {
        title: '队列',
        fields: [
          {
            path: 'queue.max_concurrency', label: '并发上限', type: 'number', def: 1, min: 1, max: 16, step: 1,
            help: '同时能跑几个生成。单卡跑本地模型基本只能是 1，调大不会更快，只会互相等。',
          },
          {
            path: 'queue.interactive_first', label: '交互优先', type: 'checkbox', def: true,
            help: '队列里优先跑「用户正在等」的请求，把后台任务（情绪更新、记忆重构）往后放。'
              + '关掉会明显感觉打字变慢。',
          },
        ],
      },
      {
        title: '路径',
        fields: [
          {
            path: 'paths.state_dir', label: '状态目录', type: 'path', def: '.test/state/meowllm',
            help: '相对 .vendor/.MeowLLM/。port.json、pid、镜像状态都在这，'
              + '主项目靠 port.json 找端口，所以别随便清。',
          },
          {
            path: 'paths.log_dir', label: '日志目录', type: 'path', def: '.test/logs',
            help: '相对 .vendor/.MeowLLM/。服务日志落这里。',
          },
        ],
      },
    ],
  },

  // ============================================================ 安全
  {
    id: 'safety',
    icon: '🛡',
    title: '安全闸',
    desc: '防止误把「云端大模型」的配置拿到本机跑爆显存。默认值是保守的，'
      + '本机跑 8B 时需要显式放宽。',
    groups: [
      {
        title: '闸门',
        fields: [
          {
            path: 'safety.max_local_model_params_b', label: '本机参数量上限（B）', type: 'number',
            def: 1.0, min: 0.1, max: 405, step: 0.5,
            help: '超过就拒绝加载（按 config.json 估参数量）。0.6B 用 1.0 就够；'
              + '8B（9.096B）必须调到 12，否则启动直接被拒。',
          },
          {
            path: 'safety.allow_engine', label: '引擎白名单', type: 'list', def: ['dualstream'],
            help: '逗号分隔。engine.kind 不在这里面就启动失败。'
              + '要用 stub 验管道就得把 stub 加进来。',
          },
          {
            path: 'safety.require_env_override', label: '硬件覆盖必须走环境变量', type: 'checkbox', def: false,
            help: '开：加载真实权重必须设 MEOWLLM_ALLOW_LOCAL_MODEL=1 才放行（脚本里显式声明过才跑）。'
              + '关：只要白名单和参数量过关就直接加载。',
          },
        ],
      },
    ],
  },
];

// Node 侧也能 require 到（自检脚本用），浏览器里挂到 window。
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { MLL_SCHEMA };
}
