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


## 260820

# ToolBox\napcat的功能实现
## 功能概述
- 1、该功能允许角色通过napcat，用自己的qq账号给指定用户，多为用户，群聊发送消息，文件，链接，表情包等
- 2、该功能基于项目核心的拓展，使用项目的catbrain记忆功能，使用项目的llm回复，以及可以使用其它工具
- 3、toolbox里有接口型工具，触发型工具，和兼顾二者的混合型工具，NapCat控制模块属于混合型工具
- 4、各种接口较为复杂，可以参考```D:\QQbot\AstrBotLauncher-0.3.0```的astrbot，必要时直接复用功能或者plugins下的插件
## 具体模块功能需求
### 项目根目录的napcat
已完成
### napcat核心文件
已完成
### napcat\message模块（接口模块，自发进行，不受toolcalls控制，仅使用于单人聊天）
已完成
### napcat\groupchat模块（接口模块，自发进行，不受toolcalls控制，仅使用于群聊）
- 1、新建get_group_message.py，获取群聊消息，分用户，跳过所有表情包，聊天记录等信息
- 1.1、补充：message里只获得用户消息，而该模块只获得群聊消息
- 1.2、所有消息获取逻辑和message一样，向上匹配同一个用户，直到用户替换
- 1.3、群聊名称有黑名单，从config.py读取黑名单，并且不接收黑名单的消息，默认为空
- 1.4、get_group_message.py接收消息不立刻触发回复，回复逻辑见下面
- 2、新建get_group_record.py，获取之前的消息，分用户，跳过所有表情包，聊天记录等信息
- 2.1、补充：表情包和跳过消息逻辑不同于message，是任何表情包，聊天记录包，全部跳过
- 2.2、补充：向上检索条数需要标注用户名，即content内容为【{username}】:消息内容，检索条数默认为50，可以配置
- 2.3、获取聊天记录和message一样，缓存，作为短期记忆发送
- 3、新建napcat_active.py，用于控制是否发送用户消息
- 3.1、如果判断@{角色昵称}，则立刻给出回复
- 3.2、群聊消息在message内更新6次（以6为基准，加减20%取整，基数可配置，且每个群可以选择单独配置，默认为全局），则由ai判断是否需要回复，不需要输入pass，需要则流式输出
- 3.3、pass只允许循环一次（可配置，默认为1），之后再更新次数打标则必须发送
- 4、新建群性质概括模块，group_info.py
- 4.1、ai在群里每发送100条消息（默认100，可以配置），则触发get_group_record.py拉去最近50条消息，然后50条之外的200条内，随机抽取15%有效文本消息（200条可配置，半分比不可），作为基础信息
- 4.2、发送至ai概括群话题，和群性质，保存在.NapCat\group_info\群聊名.json
- 4.3、通过tool调用，开启深度思考，决策是否更新，json内容如下：
{
'group_name': "group_name",
'group_topic': "群聊天话题，不同于主程序的topic，这个topic由ai全部自己概括"
'group_character': "两三句话概括群聊性质和聊天内容"
'most_active_user': "群聊三至五个发言多且有效的人",
}
- 5、关于提示词构建，仅当有用户在群内单独@ai账户的时候，才使用单独内容用户档案，否则原档案处改成群聊档案，且后置词和标题改成在群名内聊天
- 5.1、补充：长期记忆摘要则需要仅根据当前话题，没有用户就随机匹配
- 6、上述内容仅@触发的回复，需要按照assistant和user对应关系，存进public_short_memory，type为qq_response；群聊无用户的消息，仅存储assistant消息，type为qq_groupchat，且只容纳10条（可配置）
- 7、group_bot.py，该模块用于解析群机器人的消息，群机器人的单独@，解耦图片，文本内容，进行处理，先回答我最后的问题再给出方案
### 新建image模块
- 1、新建image_search方法，获取的消息里包含图片（必须严格是图片，不是表情包，或gif）
- 2、新建vision_decide.py，深度思考让ai判断是否需要看图片（即当前话题和图片强相关）
- 3、如果需要则不走后续message和group的回复，转而直接使用toolbox\catvision，该工具目前还未实现，先保留方案
### napcat\active_sender模块（触发模块，需要toolcalls控制，用于主动发送信息或者文件）
- 1、先在analysis.py注册tool，说明这个工具是给用户发送文件，在某用户要求ai给谁发消息或群发消息的时候启用
- 2、新建get_friendlist.py获取用户列表获取，是一个供ai使用的tool
- 3、新建get_grouplist.py获取群聊列表，是一个供ai使用的tool
- 4、新建sender.py，用于实现发送内容
- 4.1、该sender可以发送链接，文本，图片，文件，聊天记录，
- 4.2、该sender有从整个D盘找目标文件的功能，验证链接是否404的功能
- 4.3、实际上也包含供ai使用的tool
- 5、新建single_send.py，该模块负责让ai从get_friendlist获取用户列表，找到需要发送的一个或多个用户后拟定消息发送，若有需要，则发送链接和文件
- 6、新建group_send.py，该模块负责让ai从get_grouplist.py获取用户列表
- 7、新增excuse.py，若ai有任何疑问，则返回询问文本，通过toolbox_tts合成语音，向用户询问，且必须以角色口吻
- 7.1、补充：如果启用了excuse，则需要由toolbox直接获取sensevoice得到后续需求，之后获得完整需求就继续，如果判断终止（可以发起再询问，也可以终止）就终止tool进程，该过程暂时阻塞sensevoice_llm，防止快速回复导致混乱
- 7.2、excuese的回复内容和用户回复确认内容，都需要保存在public_short_memory，且所有工具调用返回询问，返回确认的消息，type都叫“toolbox_response”，有user和assistant对应关系
- 8、该模块获得的提示词从toolbox来，即触发toolbox调用工具的提示词，和该模块的提示词完全相同
#### 注意，上述excuse方法写成通用，供toolbox之后加其它模块也使用
### napcat\vision_active
### 针对前端的修改
- 1、把napcat改成和catbrain一样，有独立子球，分别配置主动回复、私聊回复、群聊回复、角色账号名
- 2、根据上述要求，同步修改config.yml，增加节点
# 原则
- 1、逐字分析我的需求，有任何疑问提出，确保没有歧义
- 2、toolbox下的所有类名都需要TB前缀
- 3、无时无刻必须遵守桥接原则，toolbox内的数据由toolbox传递给pipeline，除了文件直接更改，任何数据传递都要经过pipeline，保证逻辑整洁有原则
有问题提出，先分析项目，暂时实现我需要的功能
此外，还需回答我的问题，napcat能否执行群机器人指令，且正常获取群机器人的消息，如@幻梦这样的，或者需要我用什么手段获得样本



# ToolBox\meowvision
## 功能概述
- 1、该功能负责项目的所有视觉事件，为极其重要的视觉模块
- 2、该模块内置vision_port，默认使用```qvq-plus```模型，可以配置，为aliyun平台
- 3、toolbox里有接口型工具，触发型工具，该工具为触发型工具，仅在toolbox_core决定使用该tool的时候才触发
## 具体模块功能要求
### 新建toolbox\meovision\port
- 1、该port目前支支持阿里云平台
- 2、视觉理解模型调用参考如下
```
from openai import OpenAI
import os

# 初始化OpenAI客户端
client = OpenAI(
    # 如果没有配置环境变量，请用百炼API Key替换：api_key="sk-xxx"
    api_key = os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://[workspace-id].cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)

reasoning_content = ""  # 定义完整思考过程
answer_content = ""     # 定义完整回复
is_answering = False   # 判断是否结束思考过程并开始回复

# 创建聊天完成请求
completion = client.chat.completions.create(
    model="qvq-plus",  # 此处以 qvq-max 为例，可按需更换模型名称
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://img.alicdn.com/imgextra/i1/O1CN01gDEY8M1W114Hi3XcN_!!6000000002727-0-tps-1024-406.jpg"
                    },
                },
                {"type": "text", "text": "这道题怎么解答？"},
            ],
        },
    ],
    stream=True,
    # 解除以下注释会在最后一个chunk返回Token使用量
    # stream_options={
    #     "include_usage": True
    # }
)

print("\n" + "=" * 20 + "思考过程" + "=" * 20 + "\n")

for chunk in completion:
    # 如果chunk.choices为空，则打印usage
    if not chunk.choices:
        print("\nUsage:")
        print(chunk.usage)
    else:
        delta = chunk.choices[0].delta
        # 打印思考过程
        if hasattr(delta, 'reasoning_content') and delta.reasoning_content != None:
            print(delta.reasoning_content, end='', flush=True)
            reasoning_content += delta.reasoning_content
        else:
            # 开始回复
            if delta.content != "" and is_answering is False:
                print("\n" + "=" * 20 + "完整回复" + "=" * 20 + "\n")
                is_answering = True
            # 打印回复过程
            print(delta.content, end='', flush=True)
            answer_content += delta.content

# print("=" * 20 + "完整思考过程" + "=" * 20 + "\n")
# print(reasoning_content)
# print("=" * 20 + "完整回复" + "=" * 20 + "\n")
# print(answer_content)
```
- 3、apikey单独配置
### meowvision核心功能
- 1、新建vision_core.py，用于传输图片，传输回复至toolbox，再pipeline给tts合成
- 2、新建config.py，用于集中所有配置项
- 3、新建get_prompt.py，获取用户提示词，用户当前消息
- 4、新建sender.py模块，用于发送一张或多张图片，同时也传递用户消息和角色提示词
- 5、新建get_response模块，直接获取视觉模型看了图片后，以ai身份的回复
- 5.1、补充，视觉模型的参数也可以配置，默认512的maxtoken，不要求流式，但是需要正则匹配优化，去掉think，方括号圆括号等
- 6、get_response获得的消息需要单独一条assistant存储仅public_short_memory，type为vision_response，且清除逻辑和主动回复一样，在llm_fast_response清除时，其之前的该类型也连带删除
- 7、该记录也需要加入长期记忆记录
### meowvision\image_handle模块
- 1、该模块下全是ai调用的工具
- 2、新建截图工具
- 3、新建图片编码工具
- 4、新建图片裁切工具，适用用户说“看看屏幕右上角”这样的情况
- 5、该工具并非给视觉模型调用，而是toolbox父级决策，决策完毕后在把图片缓存并发送
## toolbox注册
- 1、该模块为触发型工具，需要再analysis注册
# 原则
- 1、逐字分析我的需求，有任何疑问提出，确保没有歧义
- 2、toolbox下的所有类名都需要TB前缀
- 3、无时无刻必须遵守桥接原则，toolbox内的数据由toolbox传递给pipeline，任何数据传递都要经过pipeline，保证逻辑整洁有原则
有问题提出，先分析项目，暂时实现我需要的功能





# ToolBox\meowvision\watching
## 功能概述
- 1、这是一个视觉的拓展模块
- 2、主要功能为，在ai决策需要长期观察屏幕时才开启
- 3、该功能启动和结束都由ai控制，及ai填写参数后启动，ai决策停止后结束
- 4、该模块主要负责长期检测屏幕或传输的画面数据，通过算法给视觉模型进行分析回馈
## 功能子模块介绍
### start_tool.py模块，用于手机ai决定的配置
- 1、以toolcalls的方式让ai决定是否调用工具，必须开启深度思考,(在用户有陪他打游戏，或者让角色陪自己看屏幕的意图，则决定使用该工具)
- 2、这个工具需要让ai决定截屏频率（规定在20秒至两分钟），截屏区域，是否需要前后图片变化程度检测，持续时间（30分钟至5小时），前置词，游戏窗口绑定等
- 2.1、补充：前后图片变化检查需要判断该游戏的 界面变化会不会很大，是不是第一人称，满足上述情况才开启
- 3、收集完配置项后
- 4、如果ai不确定，需要发起excuse向用户提问，尽量明确
- 5、ai确定输出后，把所有配置数据传递至vision_loop模块，开始执行循环
- 6、该功能可以获得用户当前打开的窗口列表，让ai决定循环和哪个窗口进程绑定
- 7、获取的信息保存在项目根目录的.temp\内
### vision_loop.py模块
- 1、该循环收到ai决定的配置信息，并根据循环持续时间，截屏区域，截屏间隔
- 2、该循环与游戏窗口强绑定，若游戏窗口在循环时间内消失，则立刻结束循环
- 3、循环强制结束，通过toolbox向llm发消息，告知用户强制结束了游戏；若是循环时间限制到了，则告知用户，通过toolbox提示llm，生成自己不想玩了类似的提示
- 4、循环过程中，将根据间隔持续用image_handle获取截屏，处理截屏，并根据是否需要前后图片变化程度检查，传递图片
- 5、得到图片，获取短期记忆，角色提示词，游戏相关数据库内容（先保留，后续完成知识库后实现），前置词和后置词由start_tool.py配置，强调游戏场景，谁在玩游戏，注意内容
- 5.1、补充，角色提示词需要获取用户档案，但是不需要获取长期记忆摘要
- 6、所有内容和短期记忆一通过api传递给模型，让ai根据图片，以角色身份给出评价，抒发情感，发出吐槽和赞扬的内容
- 7、仅ai回复的assistant消息写进长期记忆记录和public_short_memory
- 8、ai回复内容需要进行正则处理，去掉括号去掉think，然后发送至tts合成
- 8.1、注意标注来源，不要和其它语音合成混乱
## 原则
- 1、逐字分析我的需求，有任何疑问提出，确保没有歧义
- 2、toolbox下的所有类名都需要TB前缀
- 3、无时无刻必须遵守桥接原则，toolbox内的数据由toolbox传递给pipeline，任何数据传递都要经过pipeline，保证逻辑整洁有原则（toolbox内不用）
先分析项目，有问题提出


# func\database模块
## 功能概述
- 1、项目核心模块之一，用于数据库的更新和使用
- 2、文件类型主要有网页信息，文档信息
- 3、该模块会被napcat和system_prompt.py使用
- 补充：system_prompt.py将拼接数据库加载的结果
## 项目根目录
- 1、新建database_core.py，用于所有的数据初始化和数据传输
- 2、config.py用于配置项的汇总
- 3、找到pipeline，在其中新建msg_database的内容，所有msg收到的sensevoice或者qq消息，全部都由这个传递给database_core.py，进行关键词匹配
- 4、database_core需要汇总信息到pipeline\system_prompt
## 关于database_core
- 1、database_core收到一条消息，需要进行关键词匹配
- 2、如果有“搜索”“搜搜”“搜一下”（可以适当扩展一下，禁止过多）这样的词语匹配，立刻调用search模块进行搜索
- 3、如果有“知道”“了解”“听说过”类似这样的词语匹配，立刻调用store\searching.py模块的检索部分构建提示词
- 4、同时得做非关键词审查，比如“知道了”“不知道”“不了解”“没听说过”类似这样的词出现，被上述误判，需要有单独方法拦截
- 5、新增alluser_record.py，用于存储所有用户消息，及标注为user的全部存储，且仅包含用户名称，可以配置文件更新消息条数，默认15
- 5.1、保存的alluser_record.json，实际上内部存储2轮（默认2，可配置），及last和past_1两个属性的聊天记录文本，目的防止更新聊天记录，导致聊天内容截断，话题不连续，格式如下
```
{
  'state': "last",
  'text': "[用户1]xxxxx\n[用户2]xxxx\n[用户2]xxxxx\n......"
}
{
  'state': "past_1",
  'text': "[用户1]xxxxx\n[用户2]xxxx\n[用户2]xxxxx\n......"
}
```
- 5.2、每次更新都删去最下面的一条past，然后把last下移一个，然后写新的last
- 5.3、补充：alluser_record.json保存逻辑和catbrain的聊天记录逻辑类似，但是注意有明显不同，如这里只记录用户消息，且文件格式是json
## func\database\commet模块移植整合
- 1、源项目在D:\Git\Comet下，主要分析后端api文件夹
- 2、把项目的源代码整合进func\database\commet，并在项目启动的时候初始化
- 3、告诉我需要安装的库，如果有必要，让我手动配置环境
- 4、api的服务功能舍弃，只保留数据库rag功能
## database\store模块，用于更新数据库，加载数据库（加载多少由当前用户消息决定）
- 1、新建database\store\port，用于配置硅基流动的```BAAI/bge-m3```模型，参考如下
```
import requests
response = requests.post(
    "https://api.siliconflow.cn/v1/embeddings",
    headers={
        "Authorization": "Bearer $SILICONFLOW_API_KEY",
        "Content-Type": "application/json"
    },
    json={
        "input": {"image": "https://example.com/image.jpg"},
        "model": "Qwen/Qwen3-VL-Embedding-8B"
    }
)
print(response.json())

```
- 1.1、注意，需要使用视觉模型，且仅当有图片使用的时候才传输图片，详见下方
- 1.2、新建learning.py,当search模块发出了搜索完成信号后，访问```.temp\database\web_result```下的每个搜索结果，通过api调用向量模型，存储进知识库，构建索引
- 1.2.1、补充，该文件开始构建索引前（不是一次性全部移出），就从temp里移出，按方案（待定，需要你推荐）存储到项目根目录的```.DataBase```内
- 1.3、新建searching.py，从database_core获得用户信息，用tool_choice（不思考）从中提取keys，要求禁止输出过于宽泛的内容，比如“游戏”“战争”“家庭”这种没有针对性的名词概念
- 1.3.1、补充，如果实在找不出有针对性的索引，那么直接跳过
- 1.4、新建build_prompt.py获得索引后，去.DataBase启用知识库，检索5条最相关的内容（可配置），然后传递至database_core.py,插入system_prompt.py(在用户档案下方，markdown标题为“{角色名}的知识库”)
- 1.5、当database_core由关键词匹配触发了索引,则检索15条最相关内容（可配置），其余逻辑同上
### 关于napcat回复
- 1、新建qq_image.py,进行图片索引
- 2、在pipeline新建toolbox_database,仅当napcat内部触发了视觉模块，才传输图片到database进行索引提取
- 3、其余提示词构建逻辑不变，仅增加图片的传递
## database\search模块，用于搜索学习
- 1、内置port模块，和llm完全相同，且单独配置apikey和temperature，默认0.7
- 2、每次alluser_record.json更新同时，把已有数据发送给llm，（注意！此处llm传递是项目唯一不需要提示词的地方）
- 2.1、让ai深度思考，然后决定是否调用tool（只有在话题极为混乱，语法都无法辨别，完全找不到更新知识库的内容时，才决定不用工具）
- 2.2、新增search_task.py的tool供ai使用，该工具让ai设置搜索任务，尽量多个，单个任务的json格式如下
```
{
  'task_id': 1
  'search_keys': "原神，二次元游戏，米哈游"
  'web_url': "www.baidu.com\xxx"
}
```
- 2.3、上述search_keys值，需要给ai严格限制，禁止输出过于宽泛的内容，比如“游戏”“战争”“家庭”这种没有针对性的名词概念，必须专有名词优先，名称优先
- 2.3.1、补充，若ai思考后，认为，只能得出没有针对性概念的名词，直接结束
- 2.4、根据web可以供ai选择，如```www.mcmod.cn```(对应minecraft相关知识检索), ```mzh.moegirl.org.cn/```（对应二次元相关模块检索）```games.gg```(游戏信息检索)，```www.zhihu.com```(话题观点检索)，这些内容可以配置
- 2.4.1、各种网站可能会碰到人机验证和各种爬取阻碍，给我写三种方案保证能获得信息，且不对网站服务器造成伤害，配置可以为每个网站选择特定方案
- 2.5、任务完成后，相同网站队列，不同网站并行，开始爬取相关数据
- 2.5.1、补充：爬取条数每个网站单独配置，默认为5
- 2.6、得到的所有结果缓存在.temp\database\web_result下，目前我不确定格式如何保存，因为爬取的内容可能有图片，各种文本，数据，目前我倾向于，一次爬取结果以一个文件夹打包
- 2.7、搜索完成后，向store模块发出信号
## 关于前端和配置项（config.yml）
- 1、同步修改config.yml
- 2、主界面新增“数据库”球，点开后有两个子球“搜索”和“知识”，分别对应搜索模块，和存储及检索模块
- 3、子球和catbrain一样，沿着弧线排列

## 原则
- 1、逐字分析我的需求，有任何疑问提出，确保没有歧义
- 2、database下的所有类名都需要CatLearn前缀
- 3、无时无刻必须遵守桥接原则，toolbox内的数据由toolbox传递给pipeline，任何数据传递都要经过pipeline，保证逻辑整洁有原则（toolbox内不用）
先分析项目，有问题提出




# toolbox新增天气查询模块和新闻查询模块
## toolbox\weather
1、该工具需要在analysis注册，并给ai选择
2、该工具访问https://www.weather.com.cn/
3、该工具需要触发excuse询问用户需要的城市，今天还是明天，还是所有的天气预报（如果需求已经详细就ok）
4、根据需求传递内容给toolbox的llm回复，并给tts发送，类型为toolbox_weather
## toolbox\news
1、该工具需要在analysis注册，并给ai选择
2、调用工具后，内部需要获得提示词
3、访问https://www.readhub.cn/hot，爬取最新3条数据标题，进一步获取其中的正文文本
4、获取文本后，和角色提示词一同发送给toolbox的llm模块，让其概括新闻并告诉用户
5、回复内容给tts，类型为tool_nes
6、前端增加toolbox子界面球，为“新闻”
## napcat对接
1、回答问题，如果我需要napcat模块也能调用这两个模块，该怎么办
分析我的需求，实现前先向我提问，避免歧义

接下来根据我的需求修改
# toolbox\danmaku模块的重构（该模块为混合型工具，同样由触发型工具和接口型工具组成）
## 关于模式的修改
1、合并api和blivedm模式，只由一个api负责
2、直接删除运行模式的配置项，这个配置已经毫无作用
## 关于danmaku模块的重构
1、保留弹幕获取模块在toolbox里的结构
2、在toolbox\danmaku新建config.py，用于所有配置项的集合，包括该模块是否启用，随机取样标准等
3、新增danmaku_core.py，用于整个模块的数据传递等
## danmaku\web（连接工具）
1、该模块复用之前的连接
2、需要拥有的接口功能有：
2.1、直接获取直播间的输入信息，如弹幕，送礼物，点赞等
2.2、可以获取在线列表，舰长列表等所有信息
2.3、可以主动在自己直播间发弹幕，发表情
## danmaku\get_danmaku模块（接口型工具模块，直接获取外部数据，进行独自的工作流程）
1、新建get_danmaku.py模块，用于接收弹幕所有弹幕到缓存列表，sc列表（不保存文件，仅存缓存）
1.1、若是sc列表，单独保存，即sc的读取始终优先于弹幕，且sc列表需要保存进.temp\bilive_sc.json,记录用户名和sc内容，确保每一条都会被回复
### 一下是回复模块，根据功能自己决定模块名称，确保每个文件代码行数小于500
2、若队列里只有一条弹幕，弹幕则传递至toolbox_llm，传递发弹幕的用户名，给llm进行回复，并完整走tts
2.1、传递给llm的同时，被回复的弹幕需要由toolbox_tts传递给tts合成语音，即原来的朗读弹幕功能（可配置开关）
2.1.1、朗读弹幕的格式有多种，随机选择触发，如下
```
{username}说:{弹幕内容}
{弹幕内容}，来自{username}
我来看看，{username}说：{弹幕内容}
```
3、若队列里只有多条弹幕，有三种方案如下，（方案的配置可以选择固定一种，或者三种随机）
3.1、直接选取文本字符最长的一条
3.2、选择最新的一条
3.3、全部传递至llm，统一回复（如果总字符数大于200，自动回退至3.1）
4、弹幕的回复需要经过toolbox_llm传递至llm快速回复，以及toolbox的analysis，即跟正常msg流程一模一样
4.1、弹幕的格式需要带用户名，如果采用了上述的3.3，提示词则不带用户档案
4.2、角色提示词逻辑使用system_prompt,并且需要特定后置词，由bilibili直播间来的，需要把跟{username}说话，改成在回复{username}的弹幕
4.3、如果有多个用户的弹幕，后置词为“你收到了好多弹幕，**挑选**一些回复一下”
5、在收到新弹幕的时候，由toolbox_tts检测当前是否有说话任务，有任何任务就只把弹幕放进队列而不传递（同时也需要唱歌，但是唱歌模块没做好，暂时保留）
5.1、队列没有上限，记录用户名和完整内容即可
5.2、sc单独保留，如果有sc，那么回复队列有先调用sc里的内容，不管弹幕
5.3、检测到没有语音任务，立刻调用队列，根据算法开始回复，且每次回复，清空弹幕队列，sc不清空，只清空被回复的
## 关于桥接
1、删除原来的danmuku_llm.py，直接启用这个模块
2、检查napcat相关的pipeline是否都有用，如果有用，都整合进对应toolbox，如napcat_ltmem就整合进toolbox_ltmem里
3、danmaku相关的pipeline模块也全整合进toolbox
## danmaku\active_sender模块（触发型工具，需要在analysis里注册，负责主动发弹幕，主动跟在线列表里的人说话）
1、该功能和qq回复一样，任何消息过来，有在直播间发弹幕的需求，就调用该工具
2、工具调用，需要提示词，且需要由llm内置的模型，拟定回复内容
## 关于前端
1、首先把toolbox父级配置球的标题改成“工具箱”
2、danmaku球的配置需要适配
3、同步更新config.py
## 原则
1、逐字分析我的需求，有任何疑问提出，确保没有歧义
2、toolbox下的所有类名都需要TB前缀
3、无时无刻必须遵守桥接原则，toolbox内的数据由toolbox传递给pipeline，任何数据传递都要经过pipeline，保证逻辑整洁有原则（toolbox内不用）
逐字分析我的方案，先提问

# calendar模块拓展
## 模块功能概述
1、该功能负责固定时间提醒用户待办，比如睡觉时间提醒睡觉，学习时间提醒学习
2、通过读取character\backlog\{username}.json获取待办列表
3、固定时间通过时间判断，主动提醒
## 新增character\backlog文件夹
1、该文件夹分用户存储json，即存储为username.json
2、改json仅在前端可以修改
3、json格式示例
```
{
"username": "YGZ醒脑片",
"to_do_list_1": {"day": "none", "time": "22:00", "type": "steady", "repeat_interval": "300", "loop": "2", "content": "提醒主人睡觉"，"qq": "false"}
"to_do_list_1": {"day": "08-22", "time": "13:00", "type": "instant", "content": "提醒主人抢演唱会门票", "qq": "true"}
}
```
## 新增backlog.py
1、负责读取backlogs下的文件，获取需要提醒的事项
2、读取参数如下
2.1、day指的是在哪一天提醒，如果不填，默认每天
2.2、time只的是在一天的什么时候提醒，填写13:00这样的时间点，需要提前五分钟或30秒提醒一次
2.3、type指的是是否持续，如果是instant，则根据2.2提醒一次或两次则结束；如果是steady，则需要填写repeat_interval和loop参数，之后进行多次提醒
2.4、repeat_interval指代第二次提醒间隔，loop表示重复提醒次数
2.5、content则是提醒内容
2.6、qq则是是否需要调用napcat，用qq提醒
3、如果触发了提醒，则根据用户构建用户提示词（从pipeline\system_prompt.py），然后向llm发出句子“**现在是{time}，你必须提醒{username}，{content}**”，之后传递给语音合成
4、新建pipeline\calendar_llm.py用于传递内容
5、llm回复类型和llm_active的短期记忆类型一样，且只有assistant消息记录如短期记忆，长期记忆记录，且需要根据对应消息，记录到用户对应聊天记录
6、新建pipeline\calendar_toolbox.py，若开启了qq提醒，则通过该文件传输内容给对应用户，哟toolbox内的llm负责拟写提醒词，角色提示词和引导词和上述完全相同
## 关于前端
1、同步修改前端界面，在主界面增加一个“待办”的球
2、有新建用户按钮，每个用户卡片可以折叠
3、一个用户可以对应多个todolist
4、每个参数都可以配置，选择参数做一个点击替换的按钮
## 原则
1、类名需要有Date前缀
2、注释不要多
3、有问题立刻提出，避免所有歧义
现在分析我的需求，向我提问
此外，分析一下，为什么public_short_memory.json的消息排列，每个种类都十分整齐，主动回复的消息删除逻辑是怎么实现和时间对应，仅在之后的一轮快速回复消息删除的时候，才连带删除的


```
接下来在func\llm下新增一个优化ai回复丰富性的算法：

func\llm\narration模块的实现
1、新建adjunct_word.json，内容包含所有ai常见的水词，内容如下：

1. 语气词 / 句末助词
喵，呜，啦，呀，呢，吧，嘛，哟，哦，诶，嘿，哈，嗯，唔，哼，啊，哇
喵呜，呜喵，诶嘿，嘿嘿，哈哈哈，欸嘿嘿，喵嘿嘿，哼哼，哎，哎呀，啊呀，呜哇，哎哟，哦豁，呀呀，呜呜
复制
2. 填充词 / 口头禅（无实质信息）
那个，这个，就是说，怎么说呢，其实，反正，基本上，说实话，讲道理，我觉得，我想，我看，我猜，我估计，大概，可能，也许，说不定，好像，感觉，有点，非常，特别，超级，真的，实在，完全，简直，确实，大概，基本上，某种意义上，换句话说，也就是说，实际上，众所周知，众所周知的是
复制
3. 连接词 / 转折词（常用且可删减）
不过，但是，然而，可是，虽然，尽管，因为，所以，于是，而且，并且，以及，然后，接着，那么，既然，要是，如果，就算，哪怕，反正，毕竟，其实，实际上，其实呢，话说回来，换句话说，也就是说，总而言之，综上所述
复制
4. 冗余程度副词（修饰性，可删）
很，非常，特别，超级，极其，相当，比较，稍微，有点，一些，好多，大量，极其，实在，简直，完全，几乎，差不多，绝对，肯定，一定，必须，务必，特别地，相当地
复制
5. 重复性短句（凑字数）
好不好，对不对，行不行，是不是，有没有，会不会，该不会，要不要，能不能，是不是呀，对不对呀，行不行呀，好不好嘛，这样那样，这个那个，这里那里，现在呢，然后呢，接着呢
复制
2、新建narration_core.py打分系统，具体内容如下

一、基础变量（同原始方案）
L：当前回复总字符数（含标点）
W：命中五类水词清单的字符总数
人类基准锚点：25 字符
二、单轮原始得分 Rawₜ（0~100）
Step 1：水词密度分
[
DensityScore = 100 - \left( \frac{W}{L} \times 100 \right)
]
若水词占比 ≥ 80%，此项直接得 0。

Step 2：超长冗余惩罚
[
Penalty =
\begin{cases}
0, & L \leq 30 \
(L - 30) \times 0.4, & L > 30
\end{cases}
]
封顶扣 20 分。

Step 3：原始得分
[
Raw_t = \max(0, DensityScore - Penalty)
]

三、多轮惯性平滑得分 Sₜ（核心）
引入指数加权移动平均（EWMA），让当前轮的最终得分受前几轮影响：
[
\boxed{S_t = \lambda \cdot S_{t-1} + (1-\lambda) \cdot Raw_t}
]

惯性系数 ( \lambda = 0.7 )（推荐值，取值范围 0.6~0.8）
初始值 ( S_0 = 70 )（假定对话开始时处于“正常”状态）
物理含义：
当前轮得分 = 70% 的历史惯性 + 30% 的当前表现
如果 AI 连续 3~4 轮都很啰嗦，分数会缓慢下降；反之亦然
单轮“抽风”（突然变长）不会导致剧烈波动，符合人类说话的自然起伏
四、最终动作触发判断
用平滑得分 ( S_t ) 代替原始得分，决定后端是否干预
3、在llm的接受模块增加清洗方法
3.1、清洗标准标准为前多次回复得出，算法如上
3.2、清洗等级有三档
3.2.1、100至60，完全不清洗
3.2.2、60至30分，清洗口头禅、连接词 / 转折词、重复性短句
3.2.3、30至10分，则上述命中全部清理
4、算法写在单独文件里，llm流式接收时调用，在送出并传递pipeline前完成清理，即保存进记忆的，语音合成的，都是清洗后结果
有问题提出，没问题实施
```
# 主动回复的b站内容收集功能
## 新建func\llm_active\origin\vision文件夹，新增视觉模块（完全和meowvision的port相同，独立属于自动回复模块，api不复用）用于传递图片
1、需要传递图片，主动回复的角色提示词
## 新建func\llm_active\origin\web_browse文件夹
1、可以爬取bilibili的视频(默认b站，可以配置，但是提示每个网站爬取方案不同)
2、根据视频的标签和标题判断是否合适
3、在config.py里可以配置视频的主题，严格程度，无配置随机
（默认禁止抽象视频，必须是二次元，科普，游戏相关的）
4、如果符合主题，在视频的前中后截取三帧（保证随机且均匀），可以配置，3为默认
5、把截取的帧压缩称720p，传递给配置的视觉模型（包括视频标题，标签，up主信息，简洁内容）
6、同时传递提示词，但是引导词写“这是你在b站上看到的视频，图片是几张截图，描述一下你看到的内容，结合视频标题，描述一下视频内容，控制在100字”
7、ai需要判断话题，在tags里面选择tag打标
8、内容直接存进.temp\web_browse_cache\{视频标题}.json
9、视频上限存储5个，可配置
10、每间隔10分钟就执行一遍上述程序，知道缓存达到了上限，不再执行，间隔时间可以配置
11、存储的json需要包含视频标题，视频本身标签，概括内容，话题，tags
## 更新origin的找话题方法
1、随机话题时随机内容包含视频项，比如缓存了三个视频，那video_1\2\3也加入随机匹配，若匹配到视频内容.temp\web_browse_cache\匹配内容，话题匹配，则直接使用网页内容
2、如没有匹配到没有内容，再使用记忆，直接让ai说话
### 先告诉我之前仅用记忆，提示词是怎么传递的，再决定视频内容定义怎么传递
## 新建func\llm_active\active_singing文件夹
1、还在施工，仅新建留空
## 原则
1、代码需要模块化，不要一个文件堆砌所有功能
2、有疑问提出，先解决歧义


# func\meowsinger
## 模块功能概述
- 该模块复制歌曲搜索下载，歌曲字幕清洗，点歌播放，翻唱，歌曲翻唱，完整翻唱（带伴奏）
- meowsinger是项目的核心模块之一
- meowsinger和database的搜索模块有联动
## func\meowsinger下的核心文件
- 1、新建meowsinger_core.py，为核心文件，复制内容的传输和决策
- 2、新建config.py，所有配置项集中于此
- 3、新建if_start.py，用于判断整个模块是否启动
- 3.1、判断逻辑有两种，一种是关键词前缀，一种是关键词加意图分析
- 3.2、关键词前缀（可配置，以Meowlisis为例，大小写敏感，必须在最前），用户的消息前带“Meowlisis点歌”，命中则走点歌模块；用户消息前带“Meowlisis唱歌”，命中则走翻唱模块
- 3.3、关键词加意图分析，匹配到关键词“唱首歌，唱歌”（可配置），则交给llm进行意图分析，是否有确定歌名，有就走翻唱模块；匹配到关键词“点歌，放歌，放首歌”，同之前，有则走点歌模块
- 3.4、此外还需要接受学歌任务的方法，详见下方（特定用户，发送配置指令，仅在开启了空闲时学歌是启用）
- 4、新建stop.py，负责播放线程是否掐断，是否中途结束唱歌或点歌
- 4.1、该模块同上，有关键词前缀
## func\meowsinger\port模块
- 1、该port支持llm和aliyun平台，支持toolchoice和流式输出
- 2、apikey和参数完全独立，仅负责给这个port
- 3、这个port仅被meowsinger内部调用
## func\meowsinger\get_title模块
- 1、新建get_title.py，调用meowsinger\port，提取输入信息中要求的歌名，如果没有歌名就直接回复没有相关的歌名
- 1.1、没有具体歌名，不需要等待回复，这个过程是一次性的
- 1.2、该提取功能需要使用function_calling，并非tool_choice，需要深度思考
- 1.3、如果没有调用工具，或者判断没有歌名信息，则开始
- 2、工具新建title_tool.py用于存放工具
## func\meowsinger\netease模块
- 1、新建get_song.py从get_title模块获取歌名
- 2、如果走点歌模块，则使用该模块
- 3、新建netease_music.py从netease获取对应歌曲
- 3.1、同时获取歌词，并且需要清洗歌词时间戳，确保为**分-秒-毫秒**格式（详细格式可以看character\songs\raw_list下的所有文件）
- 3.2、获取的歌曲和歌词保存在character\songs\raw_list\歌名文件夹里（同时帮我整理现在目录下的文件，把歌词和歌曲放在一个文件夹）
- 4、歌曲下载完成后，需要报一遍歌名，然后开始播放，同时按时间发送字幕（先保留方法，字幕还需要维护）
- 5、播放开始的同时，给sentiment模块发送信号，准备搜索和感想
## func\meowsinger\cover模块 
- 1、新建get_song.py从get_title模块获取歌名，处理逻辑和netease完全相同
- 2、如果走翻唱模块，且该歌曲没有学习过，则先搜索该歌曲（如果在raw_list则直接使用），翻唱逻辑直接参考D:\Git\Live2D-Virtual-Girlfriend内的方法
- 2.1、所有翻唱相关代码全在模块内部
- 3、翻唱学习阶段可以设置为空闲时学习和立刻学习（可配置）
- 3.1、立刻学习即收到指令就学习
- 3.2、空闲时学习需要向用户询问是否可以学歌，只在指定的用户回复了特定信息（如：“喵利呜西斯，可以开始学歌啦”，必须一个字不差，且不能有其它内容，如：“可以，喵利呜西斯，可以开始学歌啦”就不通过）后才开始rvc任务
- 3.3、rvc任务可以堆积，当触发空闲学歌开始，则每个任务依次开始执行（每次执行一个，完成了再下一个，不需要考虑掐断，一旦开始就不结束）
- 4、如果学习完成，歌曲文件不要和伴奏合并！歌曲，伴奏，歌词，存进character\songs\meow_list\歌名文件夹
- 5、如果走翻唱模块，且该歌曲没有学习过，先向llm发送需要学习，让用户下一次再叫角色唱这首歌
- 6、如果翻唱模块，歌曲之前学过（character\songs\meow_list\存在对应文件夹），则先报一遍歌名，然后同时播放伴奏和翻唱音频，同时按时间发送字幕（先保留方法，字幕还需要维护）
- 7、翻唱的语音pth和ckpt权重模型直接读取tts配置，使用配置的语音合成模型
- 8、翻唱开始的时候，给sentiment模块发送信号，准备搜索和感想
## func\meowsinger\sentiment模块
- 1、收到开始翻唱或开始播放歌曲的信号，则通过pipeline\singer_database.py给database发送搜索歌名的请求，执行搜索操作
- 2、检测是否唱完，完整唱完一首歌就给database模块database\song_review发唱歌结束信号
### database模块的兼容
- 1、新建database\song_review模块
- 2、新建get_song.py从pipeline\singer_database.py收到歌名
- 3、新建search_song.py收到歌名后传递引导词至search，要求llm从moegirl和baidu两个地方搜索歌曲，并提取有用信息，整合至搜索结果.temp\search_result(需要llm摘要)，即完整走一遍关键词触发的搜索
- 4、新建store_song.py，把搜索结果写入知识库，即完整走一遍入库流程，包括去重，文档转移，向量分析
- 5、新建get_lyrics.py获取歌词{lrc}，直接去对应文件夹读取完整歌词
- 6、新建build_prompt_song.py，该内容不是构建系统提示词，而是构建引导词消息，具体如下
- 6.1、你刚刚唱/放（根据点歌还是翻唱决定）了一首歌，{歌名}，歌词是{lrc}，这首歌{search_result}，结合你喜欢的歌词和这首歌的信息，和大家分享一下你的感受吧~（300字）
- 6.2、如上引导词不写入任何记忆
- 7、合成完成后等待，如果收到stop的中断信号，则删除缓存，如果收到唱歌结束的信号，则通过pipeline\database_llm.py传递至llm
- 7.1、提示词构建不需要用户信息，不需要用户档案，其它不变
## func\meowsinger\stop模块
- 1、该模块负责检测是否需要掐断播放
- 2、仅在用户发送配置消息的时候触发，（如：“停止唱歌”、“停停停”，且这个可以和被语段包含，“不要唱了，停停停”也算通过）
- 3、如果提前掐断了，需要通过pipeline\singer_database.py给database发送放弃感想合成的指令
## 与meowsinger相关的pipeline模块新建桥接文件
- 1、新建pipeline\msg_singer，用于传递语音合成，msg，和弹幕内容至meowsinger模块(napcat相关全部不传递)
- 1.1、其中可以配置是否只有sc弹幕才通过，普通弹幕不通过
- 2、新建pipeline\singer_database.py，用于传递搜索任务和知识库读取任务，角色卡构建信号任务给database模块
- 3、新建pipeline\singer_llm.py，负责把上述所有回复信息（翻唱不会这首歌，点歌不清楚歌名，翻唱不清楚歌名，这些回复需要带user，且带完整system_prompt，以角色身份回答）交给llm合成
- 4、新建database_llm.py，用于传递引导词去llm，且该内容传递的maxtoken需要自定义（默认为2048，可配置）
## 前端和配置节点
- 1、总结上述所有配置节点，在config.yml里新增
- 2、在主界面增加一个“歌曲”配置球
- 3、该配置求有“模型”（配置模型参数，api），“歌曲”（配置点歌模块的触发条件和相关设置），“翻唱”（配置翻唱的相关设置和触发条件）
- 4、所有前端配置词都需要和llm的分段标点一样，是块状的，不是逗号分割
## 其它注意事项
- 1、用户点歌的指令需要加入短期记忆，用户记忆和长期记忆记录
- 1.1、如果开启前缀判定，需要清除前缀
- 2、所有走llm的ai消息都需要加入短期记忆和长期记忆（包含所有感想）
- 3、带用户的加入短期记忆和长期记忆，也加入用户记忆（如回复用户不知带歌名，回复用户不会唱这首歌）
- 4、在唱歌的时候，所有弹幕，所有msg，sensevoice合成结果都需要拦截，并且汇总，在感谢说完后，再统一交给ai回复，单独写提示词，说“刚刚在你唱歌的时候xxx说xxx”
- 4.1、该方案需要你全面了解项目，然后给我罗列所有需要拦截的内容，以及会遇到的问题！
- 5、所有配置特定触发词语都可以多个
# func\toolbox\meowsongs模块
## 模块功能概述
- 1、该模块是即兴哼唱的，所有播放不带伴奏，只播放rvc后的内容
- 2、该模块为触发型工具，需要在analysis里注册
- 3、该模块绝大多少情况不会播放完整的歌，只有部分片段
- 4、napcat和项目本体都可以使用该工具
- 5、toolbox\analysis只负责决定调用，不负责触发后的任何输出
## meowsongs核心模块
- 1、meowsongs_core.py，负责传输文本
- 2、config.py，所有配置汇总，如播放的长度上限（默认一整首歌），功能开关
- 3、字幕也需要，但是先留空
## meowsongs\impromptu_sing模块，根据歌词匹配，即兴播放单句歌曲
- 1、使用toolbox的工具，根据用户消息，角色提示词，决定播放哪一首歌曲的哪一段，如果没有明确要求就随机
- 1.1、使用function_calling，不需要toolchoice
- 1.2、参数有：歌名song_title, 开始的句子start_lrc，结束的句子end_lrc
- 1.3、如果ai没有给输出，或者不确定(让ai尽可能填写，不确定的填random)，不触发excuse
- 1.4、随机情况出现，歌名在character\songs\meow_list随机挑选，start_lrc在对应歌名里随机挑选，end_lrc默认start_lrc后面第二句（若start_lrc已经在结尾，则向前延申，保证一次唱三句）
- 1.4.1、补充，如果一次跨度小于3秒，则继续延申句子，保证播放长度有3秒钟
- 1.5、实际上ai输出要调用三次，第一次决定先输出歌词还是歌名，输出确定的一个或者都输出
- 1.5.1、若仅输出歌名，则歌名确定，后面全随机
- 1.5.2、若仅输出歌词，需要全文件歌词匹配（次为模糊匹配，匹配相似度最高的），从而获得歌名
- 1.5.3、都不输出，则纯随机匹配
- 2、该模块需要有和tts一样的打断逻辑，配置（打断音量）直接使用tts的
- 3、该模块字幕也需要传递，先保留
## 根据napcat的适配
需要你分析napcat，才私聊和群聊@的情境下，按照用户需求主动调用工具，并按语音方式发送，先给我方案
# 原则
1、所有代码都需要模块化，保证一个文件代码不超过800行，方便维护
2、所有meowsinger模块的类名需要有“Meow”前缀
3、所有toolbox下类名有“TB”前缀
4、所有代码不要注释，仅在文件开头简要交代功能，在每个方法下写一行简洁的注释交代作用
5、所有方案准确分析，不要有猜测和歧义，提问优先
根据我的方案提出问题，解决歧义

# 字幕模块补完
- 1、找到toolbox\obs
- 2、删除obs相关的所有内容
- 3、只保留字幕相关
- 4、更新字幕文本框，在收到字幕的时候，禁止换行（待机时允许两行）
- 5、pipeline内新增get_subtitle.py，用于接受所有歌词和tts语音触发的字幕（只有播放处来的走字幕，napcat相关不需要）
根据我的需求分析问题，先不改代码，解决歧义，给出方案
# vtuber模块补完

# 桌宠模块更新

# 听歌识曲接龙模块
## 在toolbox\meowsongs下增加pass_the_baton接口工具
该功能可以配置是否开启，在前端toolbox子界面的哼唱球了，增加相关配置节点
### 音乐类型识别
- 1、可以配置开关
- 2、开启该功能后，当用户开始说话，发送音频
### 音乐匹配和播放
- 1、需要内含曲库，音频匹配，直接复用Audio-Fingerprint项目，告诉我要准备什么
- 2、往后唱两句（可以配置，默认为2）
- 3、同时需要通过toolbox传递信息，引导词写用户刚刚唱了一首歌，{对应的歌词}，发表一下感想
先分析问题并且提问，并告诉我，该怎么解决sensevoice和音乐识别冲突的问题


# CatBrain的记忆模块修改
## 仅修改abstract_mem模块
### 保存格式的修改
- 1、彻底重构原来的json数据格式，解决你内容混乱的问题
- 2、json格式如下：
```
{
'time': "2026-08-31-20-18",
'joint': ['YGZ醒脑片', 'Hgeminizjy'],
'event': "事件内容，50字以内，包括人物，具体事件内容"
'accuracy': 5,（满分5，有疑问就3，有严重质疑就1，如果完全确定就5）
'importance': 8,（事件重要程度）
'tags': [xxx, xxx],
'topics': [xxx, xxx],
'evidence':{
            'reinforcement'
            xxxxx（参数和NEKO相同，沿用其计算公式）
            }
}
```
### 创建和去重逻辑改动
- 1、保留原来的所有触发概括逻辑
- 2、彻底改动function calling的工具
- 2.1、工具增加记忆摘要格式如上
- 2.2、工具可以多次调用，每次必须概括出一个事件，每个事件对应一次调用
- 3、记录的时候就触发去重逻辑
- 3.1、**此过程为新增**，即tool_calls完成记忆概括的内容，先保存至```.temp\abmem_temp```内部
- 3.2、检索所有（all）相关的tags（首个命中）和topics，的文本内容，进行加强，弱化和确认
- 3.3、需要整合为一个function_calling，让ai得到内容比对，并判断“相同”，“相反”，“无关”，例子如下
```
# event_1的内容去重检查
传递所有相关文本text_1\text_2\text_3
ai需要回复
{
'text_1': 'same',
'text_2': 'opposite',
'text_3': 'origin'
... ...
}
# event_2的内容去重检查同上
```
- 3.4、如果ai一个same也没有输出，则在meow_{month}.json文件里新增条目
- 3.5、ai输出的每一个same和opposite都用于对evidence进行调整更新
- 3.6、origin参数判定为无关，则不做操作
### 归档和更新逻辑
- 1、evidence的去重和更新逻辑见上
- 2、归档内容移动到character\abstract_memory下的wrong_mem.json里，不再使用
- 3、归档逻辑不需要确认，直接从json删除
### 调用逻辑增加记录
- 1、调用摘要记忆构建提示词的时候，保留原来的importance，joint，topic等的匹配逻辑
- 2、同时使用NEKO项目的计算参数，记忆强度和准确性的优先级排到最高
## 原则