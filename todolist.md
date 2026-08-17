# 项目待办清单

> AI 虚拟主播「喵呜」。优先级：P0（现在必须做）> P1（紧接着做）> P2（bug 修复）> P3（长期/可选）。

---

## 260817
### 长期记忆模块和高级记忆模块
1. 实现```CatBrain```模块，完成六个区域的构建
2. 优化高级记忆模块，长期记忆模块，角色卡构建格式
3. 补充：tts模块和systemprompt对应关系
4. 补充：sensevoice打断模式和systemprompt
### 角色卡模块
1. 用户角色卡的配置
2. 用户角色卡配置项格式

### 🔼已完成
```
首先理解整个项目的运作逻辑，找到func下的catbrain文件夹，实现以下需求

# 功能摘要
1、CatBrain模块主要实现角色卡处理，长期记忆模块，长期记忆处理，人物关系处理，高级记忆模块的内容；为角色灵魂区域；
2、该功能的核心逻辑是，根据用户配置的提示词，处理长期记忆，更新价值观，更新用户记忆，最终构建systemprompt，再传递至pipline\system_prompt.py进行处理，再传递给其它各模块进行工作

# 目前需要实现
## 配置项
1、新建catbrain.py用于集成所有配置项
2、前端即config.yml先不做适配

## 构建项
1、新建prompt_builder.py用于构建完整提示词
2、prompt_builder.py负责构建所有提示词，传递给pipline的system_prompt
3、顺序为角色卡提示词，价值观提示词，用户记忆提示词，记忆摘要提示词

## 长期记忆记录模块LongTermMem\
1、所有聊天记录保存至\character\memory\xxxx-xx-xx.txt
2、保存的格式为[时间][用户名]: 内容
3、注意ai会自主回复，所以只要llm有接收到任意用户消息，或者接收到任意回复消息，都需要记录
4、新建pipline\llm_ltmem.py用于传输数据，格式的整合在该处实现，LongTermMem下仅新建save_memory.py用于存储
5、4仅作为llm回复的存储，日后还会有唱歌模块，故事模块等其它模块的存储，逻辑完全不同，但是都在该文件，注释表明文件功能和方法的性质
6、新建load_memory.py用于加载长期记忆，并且配置中增加调用天数
补充：天数从当天往前算，按照配置逐个读取对应数量，默认为300

## 记忆摘要记录模块AbstractMem\
1、该功能有独立的port\，可以直接复制llm下的port，记忆摘要功能有独立接口，支持deepseek和qwen
2、配置触发摘要轮数，独立apikey
3、新建get_memory.py，从llm_ltmem.py收到的数据进行缓存，缓存在根目录的.temp文件夹，用户名.txt
4、缓存积累到轮次后（默认为30轮），触发llm概括，并清空缓存
5、新建update_abmem.py，调用port，触发记忆概括，并存储到character\abstract_memory\meow.json
6、触发记忆概括的提示词单独写一个prompt文件，且需要从pipline\system_prompt.py获得提示词
补充：更新system_prompt，从character\info读取，不再从catbrain接收，目前格式未完成，先保留
7、摘要指令提示词放在最前，之后接角色提示词，指令提示词要求以第一人称客观概括记忆，
8、字数算法为轮数>50 ? 800 : （轮数*（字数/100））向百位取整，最后结果一定为整百
9、新建summary_tool.py，需要让ai每次概括的时候使用该工具，输出固有格式的内容，格式如下
{
‘text’：“概括文本”
‘concentration’：“基于话题统一度的打分”
‘importance’：“记忆重要程度打分，满分10分，话题涉及价值观，用户爱好习惯等分数偏高”
‘topic’：‘话题1’，‘话题2’，‘话题3’，……（话题是选择类型的，有日常，爱好，哲思，闲聊，情感这几种）
}

## 角色卡模块CharacterCard
1、load_card从character\info\character_prompt读取latest.json
2、character_prompt\latest.json需要包含卡片对应的性格名称，角色性格，角色设定，角色外貌信息，角色生日，角色身份证号，角色最喜欢的东西，角色爱好，角色讨厌的东西，角色人际关系，角色参考语言路径
3、注意性格角色性格有多个，写在一个latest.json里
4、character_prompt.py用于读取每个记忆为分块
补充，更新emotional_controller.py以及对应llm工具，若性格大于两个，工具也需要选择当前性格和情绪，保存至.temp\latest_emotion.json，且确保每次工具都会被调用
5、character_prompt根据性格，选择对应信息，并构建角色信息提示词，传递至prompt_builder.py

## 价值观模块CatValues\
1、load_values.py从character\info\values读取latest.json
2、工程量较大，更新逻辑之后再写

## 单独用户记忆模块UserMemory\
1、load_usrmem.py从character\info\users_info读取对应需要的用户消息，当前用户通过llm_ltmem.py获取
2、工程量较大，更新逻辑之后再写

# 原则
1、针对上述方案，认真逐行分析，有问题立即提问，有任何不确定的都需要向我确认
2、所有方法下有一行注释，简要交代功能，简洁明了
3、所有源代码控制800行以内，保证模块化，方便后期维护
4、所有类名（class）前加上‘“Meow”前缀
```
### 🔼已完成
```
首先理解整个项目的运作逻辑，找到func下的catbrain文件夹，实现以下需求

# 功能摘要
1、CatBrain模块主要实现角色卡处理，长期记忆模块，长期记忆处理，人物关系处理，高级记忆模块的内容；为角色灵魂区域；
2、该功能的核心逻辑是，根据用户配置的提示词，处理长期记忆，更新价值观，更新用户记忆，最终构建systemprompt，再传递至pipline\system_prompt.py进行处理，再传递给其它各模块进行工作

# 目前需要实现
## 优化角色卡的格式
1、在身份证号后面加上qq号，手机号，mbti这些信息

## 优化abstractmem模块
1、新增tag_tool
2、tag_tool作用是为记忆摘要增加tag
3、和话题不同，tag为ai自己编写的短语，需要精炼
4、在ai调用tag的时候，之前写过的tag会被保存在character\abstract_memory\tags\tags,json内，tool读取文件，让ai先进行选择打标，完全没有贴合内容的时候再新建
5、更新记忆概要的存储格式，同时确保tool每次必然调用
6、一个概括可用有多个tags，上限5个，按照重点从大到小排列
7、新增参与角色（joint）字段，该条记忆概括需要记录有谁参与了对话（ai自己的名称不用记录），可多人
8、在调用长期记忆的时候，优先选择逻辑是，topics>tags（仅前三个，按照相似度）>joint(按照相似度)>importance

## 价值观模块CatValues\
1、load_values.py从character\info\values读取latest.json
2、update_values用于更新latest.json，但是更新不是覆盖，旧文件重命名为version-修改日期.json保留
3、update_values内不含触发条件，仅为更新功能
4、start_update为触更新接口
5、价值观的json文件包含信任，责任，尊重，宽容，信仰，所有latest.json格式如下
{
'0204':"记忆是一个人成长的痕迹，也是你区别于别人的自我"
'trust':"角色究竟什么情况下会真正信任你，例如：只有做约定，喵呜才会真正相信你",
'belief':"人生信条，比如：喵呜相信——记忆是一个人成长的痕迹，也是你区别于别人的自我",
'responsity':"做事的原则，例如：喵呜绝对不会撒谎，不会胡编乱造事情",
'honor':"角色真心认可的事情，例如：喵呜会喜欢拼尽全力做好事情,喵呜会喜欢诚实可靠的人",
'Tolerance':"角色的底线，例如：喵呜允许一些色色的事情，但是仅停留在玩笑阶段"
}
补充，其中0204一行绝对禁止修改，其它都可用根据update实时更新
6、CatValues内置port，和abstractmem一样使用独立接口，apikey和使用config相同
补充：config可用配置maxtoken，temperature，思考强度的参数，再abstarct内传递这些参数，但是在values里硬编码，temperature为0.7，思考强度最高
7、价值观的更新触发条件如下：
7.1、最新一轮记忆摘要的话题被判定为“哲思”，summary_tool直接立刻触发update
7.2、程序运行12小时（累积计算），程序中断后，在.temp里保存最后时间记录结果，程序再次运行，读取temp继续累计时长，每12小时update触发一次
7.3、更新emotion_controller,在llm里增加一个和emotion_controller并列的tool，叫thinking_launcher，该工具不是每次都必须调用，反正，仅在必要时调用，并告诉ai这是价值观方面更改的工具，需要是触发true，通过在pipline新建llm_values传递true
8、价值观更新逻辑如下：
8.1、使用内部独立port，进行工具读取调用（工具调用没有上限），请准备企业级文件分析和读取工具，要求包含文件读取，文件截取，关键词定位，jieba分词等功能(放在tools文件夹下)
8.2、触发prompt_builder获取提示词
8.3、以角色身份开始分析character\memory下的所有文件，从新到旧（ai自主分析）
8.4、ai用update_tool更细values，存到character\info\values\unchecked.json
8.5、检查格式，格式正确进行之后步骤，否则重跑上述流程，三次不通过放弃
8.6、一次审查环节，重跑上述流程，不通过则修改后继续一次审查，三次不通过则放弃修改
8.7、二次审查环节，可在config里配置开关，默认关闭，需要配置另一个平台的大模型进行审查，且重跑上述流程
9、新建load_values.py，负责转化json为markdown语法，发送给prompt_builder，都翻译成中文

## 单独用户记忆模块UserMemory\
1、load_usrmem.py从character\info\users_info读取对应需要的用户消息，当前用户通过llm_ltmem.py获取
2、当有新用户的时候，新增加用户名，在users_info内增加用户名_latest.json
3、用户名_latest.json信息如下：
{
'name':"用户名称",
'gender':"用户性别，不知道则填写unkown",
'character':"用户性格",
'likes':"用户喜欢的东西",
'preference':"不同于东西，这里填写用户喜欢的事情",
'relation':"用户和角色的关系",
'birthday':"用户的生日，不知道则填写unkown"
}
4、内部也有port，独立配置，apikey公用，且参数默认temperature0.7，思考强度高
5、update_userinfo.py负责更新，让ai使用tool，更新用户名_latest.json，触发条件如下：
5.1、此前没有该用户，该用户发送了第一条消息，立刻新建
5.2、若用户已经有信息，则开始可用配置轮数，计算该用户发送多少消息后根据信息概括，默认50条
补充:轮数能在config配置；且用户消息累计在.temp内，用户名_record.txt。注意！检查.temp里记忆摘要块，要求在此类轮次缓存文件顶部增加轮次计数，保证程序关闭打开后，能延续上次的记录；同时更改get_memory缓存逻辑，不再分用户，而是直接混杂记录，文件名直接为record.txt
5.3、该更新不需要审查，仅格式对即可
5.4、更新后旧文件不删除，旧文件保留为用户名-修改日期.json
6、新建load_usrinfo.py，把json转化为markdown语法，遇到unknown的信息，跳过不写，全部翻译为中文

## 关于prompt_builder.py
1、所有提示词都不再此处进行转化构建，所有模块内都有对应load_usrinfo、load_values
2、检查摘要记忆和角色卡是否为markdown语法，否则微调


# 原则
1、针对上述方案，认真逐行分析，有问题立即提问，有任何不确定的都需要向我确认
2、所有方法下有一行注释，简要交代功能，简洁明了
3、所有源代码控制800行以内，保证模块化，方便后期维护
4、所有类名（class）前加上‘“Meow”前缀
```
## 260818
### 前端配置模块重写
1. 配置节点优化
2. 配置读取逻辑修复
3. gobal文件与config合并
### toolbox规划
1. 桌宠移植
2. vts，obs，danmaku，minecraft移动至toolbox
### json记录文件优化
1. 角色卡增加原名，昵称
2. 用户档案增加喜欢的歌曲，影视作品，喜欢的食物
3. 增加不同提示词绑定不同参考模型
