# 项目待办清单

---

## 260819
# 角色主动回复功能实现
## 功能概述
角色在空闲的时候会主动根据先前话题，或者根据记忆自行找合适话题，主动发起聊天；触发主要由llm快速回复模块是否收到新内容决定；触发判定时间高度可配置。
## 具体要求
### 新建func\llm_active模块
#### 基本文件
- 1、新建active_core.py，模块的输出从这里汇总，为模块的对外输出和接收集中点，包含检测第几次触发ai自主回复
- 1.1、可以配置n次后触发自主话题决策，少于等于n次，使用inherit策略，大于n次使用origin策略，次数默认为1，详见后续内容
- 2、新建timer.py用于计时，计时逻辑为配置项加随机数，公式为```cold_time*math.random(0.8, 1.2)```
- 2.1、cold_time用于检测llm是否有收到新消息，如果没有就不中断，直到计时结束，触发自主回复
- 2.2、cold_time默认值为90，单位为秒
- 3、新建config.py，所有配置项在这里集中
- 4、新建get_prompt.py，从pipeline\system_prompt.py获得完整角色提示词
- 4.1、此时不传递username，不需要获取username，原来“# 现在跟你说话的是username”改成“# 现在已经{cold_time}秒没人跟你说话了”，在get_prompt里完成添加
- 5、新建get_shortmem.py，从pipeline\short_memory.py获得完整短期记忆
- 6、新建pipline\llm_timer，用于传递llm是否收到回复，并更新timer计时器
- 6.1、补充，每次计时器重置，等待时间公式里的随机数也跟着重置
- 7、内部有port，和llm文件夹下的port完全相同
- 7.1、apikey使用llm相同的
- 7.2、参数也沿用llm的，如temperature，（注意maxtoken为llm配置的两倍，且有上限2048）
#### 继承型自动回复（inherit策略）
- 1、新建llm_active\inherit文件夹
- 2、所有ai交流内容需要由get_prompt.py获取系统提示词
- 3、根据短期记忆（由get_shortmem获取），当前话题，让ai决策是继续使用inherit策略还是origin策略
- 3.1、使用tool_choice，不需要深度思考
- 3.2、不需要更新情绪和性格选择等
- 3.3、若选择不使用inherit延续话题，则跳到之后的origin流程，详见下方
- 4、不需要引导词，直接在toolcalls内让ai输出主动回复内容，逻辑是：给ai发送当前短期记忆，当前话题，当前用户提示词（不含用户档案），通过toolchoice让ai填写是否延续话题，是的话继续填写主动回复内容，然后返回json
- 5、返回内容进行和llm一样的正则优化逻辑（指去掉括号内容，注意！和流式不一样，仅文本截取方式相同）
- 6、得到文本段，通过pipeline\llm_tts.py进行语音合成，不分段，整段合成
- 7、ai回复的内容以assistant身份，type填写llm_fast_response，发送至pipeline\short_memory.py保存至json，只有ai消息，没有用户消息
- 8、收到llm回复瞬间，重置timer
#### 创造型自动回复（origin策略）
- 1、新建llm_active\origin文件夹
- 2、所有ai交流内容需要由get_prompt.py获取系统提示词（不含用户档案）
- 3、在自主对话触发大于n次后触发，或者inherit阶段决定使用origin时触发
- 4、新建random_topic.py随机一个话题（保证字典和llm以及catbrain里的topic一致），随机一个tag（从tags.json文件读取）
- 5、读取短期记忆最近说话的三个人（最多三个，最少一个）
- 6、根据如上信息，搜索character下的用户档案，和30条（可以配置，默认30）记忆摘要，作为信息发送给ai分析
- 7、此时需要深度思考，流式输出，不再使用tool
- 8、引导词示例：你是喵利呜西斯，无聊的你正在回忆着过去，思考着什么：{长期记忆}{用户档案}
- 9、输出内容通过llm_tts发送至tts合成，逻辑和llm一模一样，直接照搬
- 10、输出内容也需要加入短期记忆，且只传递ai的输出，引导词禁止传递，type填写llm_fast_response
## 其它细节问题
- 1、pipeline\system_prompt里有一个在前置词后增加“现在和你说话的是username”的功能，把该功能移到llm\prompt_get.py里面
- 2、llm_active模块也需要对前置词处理，在后面增加“已经{cold_time}秒没人跟你说话了，你必须自己找话题说话”（确实有两处提示，下面用户档案处也有markdown提示，这是刻意设计）
# 原则
- 1、逐字分析我的需求，有任何疑问提出，确保没有歧义
- 2、llm_active下的所有类名都需要Auto前缀
有问题提出，先分析项目