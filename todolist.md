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

# ToolBox\napcat的功能实现
## 功能概述
- 1、该功能允许角色通过napcat，用自己的qq账号给指定用户，多为用户，群聊发送消息，文件，链接，表情包等
- 2、该功能基于项目核心的拓展，使用项目的catbrain记忆功能，使用项目的llm回复，以及可以使用其它工具
- 3、toolbox里有接口型工具，触发型工具，和兼顾二者的混合型工具，NapCat控制模块属于混合型工具
- 4、各种接口较为复杂，可以参考```D:\QQbot\AstrBotLauncher-0.3.0```的astrbot，必要时直接复用功能或者plugins下的插件
## 具体模块功能需求
### 项目根目录的napcat
- 1、检查```D:\QQbot\NapCat```下的完整性
- 2、告诉我需要复制什么文件到项目根目录进行整合，整合位置在将在项目根目录```.NapcCat\```
- 3、在前端主界面主球附带的三个启动球，新增第四个球，“NapCat”启动球
### napcat核心文件
- 1、napcat_core.py，负责和napcat的连接，负责得到napcat数据请求和传递
- 2、config.py，所有配置项都集中于此，比如napcat是否启用，查找聊天数，端口数值
- 3、在toolbox里注册触发模块，接口类模块自己配置开关
### napcat\message模块（接口模块，自发进行，不受toolcalls控制，仅使用于单人聊天）
- 1、新建get_message.py获取当前用户发送的消息，用户昵称
- 2、新建get_record.py获取当前用户聊天记录，整合为短期记忆，从当前条数向上获取30（默认30，可以配置）条信息，整合为openai的json格式，直接作为短期记忆，用户消息对应user，角色消息对应assistant
- 2.1、没有名称的动画表情跳过，有名称的动画表情保留
- 3、得到用户消息后，内容传递至pipeline\toolbox_llm.py
- 3.1、获得用户消息，以昵称为用户名，当前消息为用户消息，发送至toolbox_core，然后传递至pipline\toolbox_llm，短期记忆也传递
- 3.2、llm接收后，回复过程和获取构建提示词逻辑不变
- 3.3、llm接收后，不再访问public_short_memory.json，而是使用napcat传递的短期记忆，所以需要在pipeline和llm合适地方新建方法
- 3.4、llm流式正则处理后（和发送给tts的一样）传递给tool_llm.py,在发还给tool_core，在给napcat，作为消息发送
- 4、用户消息也需要记录到长期记忆，内容传递至toolbox_ltmem.py
- 4.1、当前用户消息和对话消息，需要传递至pipeline\short_memory.py，存储到短期记忆public_short_memory
- 4.2、从napcat来的消息type为“qq_response”
- 4.3、qq_response类型消息为有对应关系的user+assistant为一轮
- 4.4、清除逻辑，当存储的qq_response类型消息达到30轮（默认，可以配置，由napcat内的config传递至pipeline\short_memory.py），则从最旧的一条开始删除
- 4.5、从napcat来的消息记录到短期记忆的时候，需要增加“【来自QQ的消息】”前缀
- 4.6、存储到长期记忆也一样，保证时间和用户名的格式，同时之后也加上“【来自QQ的消息】”
- 4.7、存储到短期记忆和长期记忆可以配置开关，默认长期记忆不开启，短期记忆开启
- 5、新建emote_sender.py，用于发送表情包gif
- 5.1、所有表情包位于项目根目录的.NapcCat\EmoteLab内部，仅发送这些动态gif（写一个脚本清理一下文件名，仅保留"MiaoWu_"后面的表情名称）
- 5.2、表情包的调用是受到一个用户消息后，有概率触发（默认30%，可以配置）
- 5.3、新增emote_choose.py，开启深度思考，选择表情发送
- 5.4、需要从system_prompt.py获得角色提示词，以及获取聊天记录（不是短期记忆，是用户聊天记录）
- 5.5、好感度越高越有概率发送表情，所以概率的公式是```（配置的概率 + 好感度）%```
- 5.6、新增一个json，把所有表情的使用场景列出来告诉ai，这个json先随便填写，表情极多且复杂，之后我手动填写，仅新建文件
- 6、在napcat下也新建port文件，内容完全复用llm下的，且api单独配置
- 6.1、补充，该port仅用于发送表情的工具调用，和llm回复完全没有关系
### napcat\groupchat模块（接口模块，自发进行，不受toolcalls控制，仅使用于群聊）
- 1、暂时先新建空文件，暂时不实现
### napcat\active_sender模块（触发模块，需要toolcalls控制，用于主动发送信息或者文件）
- 1、先在analysis.py注册tool，说明这个工具是给用户发送文件
- 2、新建get_friendlist.py获取用户列表获取
- 3、新建get_grouplist.py获取群聊列表
- 4、新建sender.py，用于实现发送内容，暂时仅先实现基础框架，保留
# 原则
- 1、逐字分析我的需求，有任何疑问提出，确保没有歧义
- 2、napcat下的所有类名都需要TB前缀
有问题提出，先分析项目，暂时实现我需要的功能
