# 项目待办清单（todolist.md）

> AI 虚拟主播「喵呜」。优先级：P0（现在必须做）> P1（紧接着做）> P2（bug 修复）> P3（长期/可选）。

---

## 一、现在必须做（P0）

1. **系统提示词 / catbrain**：`system_prompt.py` 的 `_prompt` 恒为空，LLM 没角色设定。要读 `character/*.yaml` 拼 system prompt 注入 bridge。
2. **角色卡加载与关键词匹配**：重加角色卡配置，按关键词/权重选卡，设置 `TTsCore.current_character`。
3. **情绪落地**：`LLMEmotionBridge.set_emotion()` 是空壳，要把情绪接到 `EmoteOper`（表情 + `mood()`）。

---

## 二、紧接着做（P1）

4. **重建被删的 4 个功能**：
   - 上舰感谢（修回调归属：`self.BlivedmCore.ttsCore.tts_say`）。
   - 场景切换失败提示（走 tts 队列，别塞字符串）。
   - 说话摇摆（重做 `is_tts_ready` 状态机：播放开始 False、结束 True）。
   - Minecraft 单实例 + 去重。
5. **记忆模块**：摘要/长期存档/聊天记录检索/mem0（短期记忆已可用）。
6. **提示词对应参考音频**：`resolve_character()` 依赖 P0-1，完成后生效。
7. **补 LLM 端口**：Ollama、BigModel 客户端（前端 tab 已删，实现后加回）。
8. **视觉/搜索/唱歌/翻译/Agent/欢迎语**：实现后重加配置和前端面板。

---

## 三、Bug 修复（P2）

9. `obs.song_background` 类型错误，应改「场景名→音乐路径」map。
10. `action_oper.py` 硬编码 `J:\ai\vup背景\...` 绝对路径，要配置化。
11. `config_gui.py` 保存会丢 config.yml 注释、改格式。
12. `api.py` 的 `/chat` 用字符串拼 JSON，需改 `json.dumps`。
13. `tts/subtitle.py` 暂停时丢字幕且没 `task_done()`。
14. 确认模型名：`deepseek-v4-flash`、`qwen3-max`、`glm-4.7-flash` 是否有效。
15. `gui/index.html` 引用 `MiaoWuFace.png`，但图在根目录不在 gui 下。
16. `action_oper.py` 的 `msg_deal_scene/msg_deal_clothes` 是死代码。

---

## 四、长期 / 可选（P3）

17. napcat 适配。
18. README 施工内容：扬声器采集、WebSocket 音频。
19. 主动聊天/节日祝福/每日提醒/点歌/翻唱/网页浏览/视频理解/绘画/讲故事/文件读取/知识库。
20. `PipelineCore` 没被用，决定是否接入主流程。
