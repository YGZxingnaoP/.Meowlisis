# -*- coding: utf-8 -*-
import threading
import random
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from func.llm.utils.message_builder import MessageBuilder
from func.llm.utils.response_processor import ResponseProcessor, StreamingResponseProcessor
from func.llm.utils.scene_manager import SceneManager
from func.memory.memory import MemoryManager
from func.tools.string_util import StringUtil
from func.obs.browser_subtitle_server import get_subtitle_server

class AIResponseHandler:
    """AI 响应处理器，负责处理所有 LLM 分支的响应生成"""
    
    def __init__(self, llm_core):
        self.core = llm_core
        self.log = llm_core.log
        self.llmData = llm_core.llmData
        self.config = llm_core.config
        self.obs = llm_core.obs
        self.ttsCore = llm_core.ttsCore
        self.actionOper = llm_core.actionOper
        self.llm = llm_core.llm
        self.local_llm_type = llm_core.local_llm_type
        self.ollama_stream = llm_core.ollama_stream
        self.mem0_managers = llm_core.mem0_managers

    def _create_streaming_processor(self, traceid: str, prompt: str):
            # 获取字幕服务器实例（启动一次）
            subtitle_server = get_subtitle_server()
        
            if not hasattr(self, '_last_obs_update'):
                self._last_obs_update = 0

            def update_obs(full_text, _chunk):
                # 1. 更新 OBS 传统文本源（可选）
                if self.obs and self.obs.switch:
                    now = time.time()
                    if now - self._last_obs_update >= 0.3:
                        self.obs.show_text("LiveSubtitle", full_text)
                        self._last_obs_update = now

                # 2. 推送到 HTML 浏览器源（美化字幕）
                #subtitle_server.send_subtitle(full_text)

            return StreamingResponseProcessor(
                split_chars=self.core.llmData.split_str,
                split_limit=self.core.llmData.split_limit,
                on_chunk=update_obs
            )

    def process(self):
        """
        从问题队列中提取一条，生成回复并存入回复队列中
        """
        self.core.llmData.is_ai_ready = False
        llm_json = self.core.llmData.QuestionList.get()
        uid = llm_json["uid"]
        username = llm_json["username"]
        prompt = llm_json["prompt"]
        traceid = llm_json["traceid"]

        title = prompt
        if "query" in llm_json:
            title = llm_json["query"]
            self.obs.show_text("状态提示", f'{self.core.llmData.Ai_Name}搜索问题"{title}"')
        else:
            self.obs.show_text("状态提示", f'{self.core.llmData.Ai_Name}思考问题"{title}"')

        relation = self.core.llmData.relations.get(username)
        if relation is None:
            relation = "粉丝"

        # 根据用户消息选择角色卡
        selected_character = self.core.select_character_by_message(prompt)

        # ---------- Ollama ----------
        if self.local_llm_type == "ollama":
            self._handle_ollama(prompt, uid, username, relation, traceid, selected_character)
            return

        # ---------- Aliyun ----------
        elif self.local_llm_type == "aliyun":
            self._handle_aliyun(prompt, uid, username, relation, traceid, selected_character)
            return

        # ---------- DeepSeek ----------
        elif self.local_llm_type == "deepseek":
            self._handle_deepseek(prompt, uid, username, relation, traceid, selected_character)
            return

        # ---------- BigModel ----------
        elif self.local_llm_type == "bigmodel":
            self._handle_bigmodel(prompt, uid, username, relation, traceid, selected_character)
            return

        else:
            self.log.warning(f"[{traceid}] 未匹配到任何 LLM 类型，使用默认处理")
            self.core.llmData.is_ai_ready = True
            return

    def _adjust_max_tokens(self, traceid: str, original_max_tokens: int, prompt_len: int, token_strategy: str) -> int:
        """根据策略调整 max_tokens，返回调整后的值"""
        if token_strategy == 'smart':
            # 聪明猫：增加512，但不超过2048
            new_max = min(original_max_tokens + 512, 2048)
            if new_max != original_max_tokens:
                self.log.info(f"[{traceid}] 聪明猫模式，max_tokens 从 {original_max_tokens} 调整为 {new_max}")
            return new_max
        elif token_strategy == 'chat':
            # 聊天猫：原有动态缩短逻辑
            if prompt_len <= 20:
                new_max = max(1, original_max_tokens // 4)
                self.log.info(f"[{traceid}] 聊天猫模式，用户消息极短（{prompt_len}字），max_tokens 从 {original_max_tokens} 调整为 {new_max}")
                return new_max
            elif prompt_len <= 40:
                new_max = max(1, original_max_tokens // 2)
                self.log.info(f"[{traceid}] 聊天猫模式，用户消息较短（{prompt_len}字），max_tokens 从 {original_max_tokens} 调整为 {new_max}")
                return new_max
            else:
                self.log.info(f"[{traceid}] 聊天猫模式，用户消息长度 {prompt_len} 字，max_tokens 保持 {original_max_tokens}")
                return original_max_tokens
        else:  # normal 或其他
            self.log.info(f"[{traceid}] 普通猫模式，max_tokens 保持 {original_max_tokens}")
            return original_max_tokens

    def _handle_ollama(self, prompt, uid, username, relation, traceid, selected_character):
        """处理 Ollama 分支"""
        self.log.info(f"[{traceid}]{prompt}")

        uid_str = str(uid)
        memory = self.core._ensure_memory_manager(uid_str, username)
        memory.add_user_message(prompt, username)

        use_long_term = self.core.should_use_long_term_memory(prompt)
        if use_long_term:
            messages = memory.build_messages(prompt, username=username, include_long_term=True)
            self.log.info(f"[{traceid}] 触发长期记忆，加载背景")
        else:
            messages = memory.build_messages(prompt, username=username, include_long_term=False)
            self.log.info(f"[{traceid}] 未触发长期记忆，仅使用短期记忆")

        # 构建最终消息（使用选中的角色卡）
        builder = MessageBuilder(character=selected_character)
        messages = builder.build(messages, relation, username, include_identity=True)

        # 配置选项
        llm_config = self.config.get('llm', {})
        ollama_config = llm_config.get('ollama', {})
        options = {
            "temperature": ollama_config.get('temperature', 0.7),
            "num_predict": ollama_config.get('max_tokens', 256),
            "num_ctx": ollama_config.get('num_ctx', 4096),
            "top_p": ollama_config.get('top_p', 0.9),
            "repeat_penalty": ollama_config.get('repeat_penalty', 1.1),
        }

        # 加载角色卡中的温度和 token 限制
        if selected_character.temperature is not None:
            options["temperature"] = selected_character.temperature
        if selected_character.max_tokens is not None:
            options["num_predict"] = selected_character.max_tokens

        self.log.info(f"[{traceid}] 使用 auto 模式，消息格式保持原始 OpenAI 风格")

        # 动态调整 max_tokens
        prompt_len = len(prompt)
        original_max_tokens = options["max_tokens"]
        token_strategy = getattr(selected_character, 'token_strategy', 'chat')
        options["max_tokens"] = self._adjust_max_tokens(traceid, original_max_tokens, prompt_len, token_strategy)

        # 超时设置
        response_cfg = self.config.get('response', {})
        timeout_seconds = response_cfg.get('timeout_seconds', 3)
        timeout_phrases = response_cfg.get('timeout_phrases', ["喵呜想一想"])
        timeout_triggered = threading.Event()
        timer = None

        def on_timeout():
            if not timeout_triggered.is_set():
                if 5 < len(prompt) < 10:
                    phrase = f"{username}说：{prompt}"
                else:
                    phrase = random.choice(timeout_phrases)
                self.log.info(f"[{traceid}] 响应超时，插入缓冲语音: {phrase}")
                self.ttsCore.tts_say(phrase)
                timeout_triggered.set()

        timer = threading.Timer(timeout_seconds, on_timeout)
        timer.start()

        stream_mode = self.ollama_stream and hasattr(self.llm, 'generate_stream')

        if stream_mode:
            self.log.info(f"[{traceid}] 使用流式输出（严格 think 丢弃）")
            response_generator = self.llm.generate_stream(messages, options=options)
            processor = self._create_streaming_processor(traceid, prompt)
            all_content = ""
            #subtitle_server = get_subtitle_server()
            for chunk in response_generator:
                if not processor.first_chunk_received:
                    timer.cancel()
                processor.process_chunk(chunk, traceid, prompt, self.core.llmData.AnswerList, self.log.info)
                all_content += chunk
                #subtitle_server.send_subtitle(all_content)

            processor.finalize(traceid, prompt, self.core.llmData.AnswerList, self.log.info)

            # 清理最终内容并保存到记忆
            final_content = ResponseProcessor.remove_analysis(processor.filtered_content)
            memory.add_assistant_message(final_content)
            self.core._write_chat_record(username, final_content, self.core.llmData.Ai_Name)

            if not processor.first_chunk_received:
                timer.cancel()
                self.log.info(f"[{traceid}] 流式未收到任何块，超时可能已触发")
        else:
            self.log.info(f"[{traceid}] 使用非流式输出")
            response = self.llm.generate(messages, options=options)
            timer.cancel()
            if timeout_triggered.is_set():
                self.log.info(f"[{traceid}] 模型在超时后返回，缓冲语音已插入")

            response = response.replace("You", username)
            processor = ResponseProcessor(
                split_chars=self.core.llmData.split_str,
                split_limit=self.core.llmData.split_limit
            )
            processor.process_and_queue(response, traceid, prompt, self.core.llmData.AnswerList, self.log.info)
            filtered_content = ResponseProcessor.remove_analysis(response)
            memory.add_assistant_message(filtered_content)
            self.core._write_chat_record(username, filtered_content, self.core.llmData.Ai_Name)

        # 场景切换
        scene = SceneManager.get_scene(all_content if stream_mode else response)
        if scene:
            self.actionOper.changeScene(scene)

        current_question_count = self.core.llmData.QuestionList.qsize()
        self.log.info(f"[{traceid}][AI回复]{all_content if stream_mode else response}")
        self.log.info(f"[{traceid}]System>>[{username}]的回复已存入队列，当前剩余问题数:{current_question_count}")

        self.core.llmData.is_ai_ready = True

    def _handle_aliyun(self, prompt, uid, username, relation, traceid, selected_character):
        """处理阿里云分支"""
        uid_str = str(uid)
        memory = self.core._ensure_memory_manager(uid_str, username)
        memory.add_user_message(prompt, username)

        use_long_term = self.core.should_use_long_term_memory(prompt)
        if use_long_term:
            messages = memory.build_messages(prompt, username=username, include_long_term=True)
        else:
            messages = memory.build_messages(prompt, username=username, include_long_term=False)

        # 构建最终消息（使用选中的角色卡）
        builder = MessageBuilder(character=selected_character)
        messages = builder.build(messages, relation, username, include_identity=True)

        # 配置选项
        aliyun_cfg = self.config.get('llm', {}).get('aliyun', {})
        config_max_tokens = aliyun_cfg.get('max_tokens', 1024)

        options = {
            "temperature": selected_character.temperature if selected_character.temperature is not None else aliyun_cfg.get('temperature', 0.7),
            "max_tokens": selected_character.max_tokens if selected_character.max_tokens is not None else config_max_tokens,
        }

        # 动态调整 max_tokens
        prompt_len = len(prompt)
        original_max_tokens = options["max_tokens"]
        token_strategy = getattr(selected_character, 'token_strategy', 'chat')
        options["max_tokens"] = self._adjust_max_tokens(traceid, original_max_tokens, prompt_len, token_strategy)

        # 根据模式转换消息格式
        if hasattr(self.llm, 'use_dashscope') and self.llm.use_dashscope:
            self.log.info(f"[{traceid}] 使用 DashScope 原生模式，转换消息为多模态格式")
            messages = self.core._convert_to_multimodal_messages(messages)
        else:
            self.log.info(f"[{traceid}] 使用 OpenAI 兼容模式，保持原有消息格式")

        # 思考模式控制（阿里云专用）
        aliyun_config = self.config.get('llm', {}).get('aliyun', {})
        enable_thinking = aliyun_config.get('enable_thinking', True)
        if not enable_thinking:
            system_index = None
            for i, msg in enumerate(messages):
                if msg.get('role') == 'system':
                    system_index = i
                    break
            no_think_tag = "<no_think>"
            if system_index is not None:
                original = messages[system_index].get('content', '')
                messages[system_index]['content'] = f"{no_think_tag}\n{original}\n{no_think_tag}"
            else:
                messages.insert(0, {"role": "system", "content": f"{no_think_tag}\n{no_think_tag}"})

        # 超时设置
        response_cfg = self.config.get('response', {})
        timeout_seconds = response_cfg.get('timeout_seconds', 3)
        timeout_phrases = response_cfg.get('timeout_phrases', ["喵呜想一想"])
        timeout_triggered = threading.Event()
        timer = None

        def on_timeout():
            if not timeout_triggered.is_set():
                phrase = random.choice(timeout_phrases)
                self.log.info(f"[{traceid}] 响应超时，插入缓冲语音: {phrase}")
                self.ttsCore.tts_say(phrase)
                timeout_triggered.set()

        timer = threading.Timer(timeout_seconds, on_timeout)
        timer.start()

        # 流式处理
        response_generator = self.llm.generate_stream(messages, options=options)
        processor = self._create_streaming_processor(traceid, prompt)
        all_content = ""
        #subtitle_server = get_subtitle_server()
        for chunk in response_generator:
            if not processor.first_chunk_received:
                timer.cancel()
            processor.process_chunk(chunk, traceid, prompt, self.core.llmData.AnswerList, self.log.info)
            all_content += chunk
            #subtitle_server.send_subtitle(all_content)

        processor.finalize(traceid, prompt, self.core.llmData.AnswerList, self.log.info)

        if not processor.first_chunk_received:
            timer.cancel()
            self.log.info(f"[{traceid}] 流式未收到任何块，超时可能已触发")

        # 清理并保存
        filtered_content = ResponseProcessor.remove_analysis(all_content)
        memory.add_assistant_message(filtered_content)
        self.core._write_chat_record(username, filtered_content, self.core.llmData.Ai_Name)

        # 场景切换
        scene = SceneManager.get_scene(all_content)
        if scene:
            self.actionOper.changeScene(scene)

        current_question_count = self.core.llmData.QuestionList.qsize()
        self.log.info(f"[{traceid}][AI回复]{all_content}")
        self.log.info(f"[{traceid}]System>>[{username}]的回复已存入队列，当前剩余问题数:{current_question_count}")

        self.core.llmData.is_ai_ready = True

    def _handle_deepseek(self, prompt, uid, username, relation, traceid, selected_character):
        """处理 DeepSeek 分支"""
        uid_str = str(uid)
        memory = self.core._ensure_memory_manager(uid_str, username)
        memory.add_user_message(prompt, username)

        use_long_term = self.core.should_use_long_term_memory(prompt)
        if use_long_term:
            messages = memory.build_messages(prompt, username=username, include_long_term=True)
        else:
            messages = memory.build_messages(prompt, username=username, include_long_term=False)

        # 构建最终消息（使用选中的角色卡）
        builder = MessageBuilder(character=selected_character)
        messages = builder.build(messages, relation, username, include_identity=True)

        # 配置选项
        deepseek_cfg = self.config.get('llm', {}).get('deepseek', {})
        config_max_tokens = deepseek_cfg.get('max_tokens', 1024)

        options = {
            "temperature": selected_character.temperature if selected_character.temperature is not None else deepseek_cfg.get('temperature', 0.7),
            "max_tokens": selected_character.max_tokens if selected_character.max_tokens is not None else config_max_tokens,
            "top_p": deepseek_cfg.get('top_p', 0.9),
        }

        # 动态调整 max_tokens
        prompt_len = len(prompt)
        original_max_tokens = options["max_tokens"]
        token_strategy = getattr(selected_character, 'token_strategy', 'chat')
        options["max_tokens"] = self._adjust_max_tokens(traceid, original_max_tokens, prompt_len, token_strategy)

        # 超时设置
        response_cfg = self.config.get('response', {})
        timeout_seconds = response_cfg.get('timeout_seconds', 3)
        timeout_phrases = response_cfg.get('timeout_phrases', ["喵呜想一想"])
        timeout_triggered = threading.Event()
        timer = None

        def on_timeout():
            if not timeout_triggered.is_set():
                phrase = random.choice(timeout_phrases)
                self.log.info(f"[{traceid}] 响应超时，插入缓冲语音: {phrase}")
                self.ttsCore.tts_say(phrase)
                timeout_triggered.set()

        timer = threading.Timer(timeout_seconds, on_timeout)
        timer.start()

        # 根据配置决定是否使用流式
        use_stream = deepseek_cfg.get('stream', True) and hasattr(self.llm, 'generate_stream')

        if use_stream:
            response_generator = self.llm.generate_stream(messages, options=options)
            processor = self._create_streaming_processor(traceid, prompt)
            all_content = ""
            #subtitle_server = get_subtitle_server()
            for chunk in response_generator:
                if not processor.first_chunk_received:
                    timer.cancel()
                processor.process_chunk(chunk, traceid, prompt, self.core.llmData.AnswerList, self.log.info)
                all_content += chunk
                #subtitle_server.send_subtitle(all_content)

            processor.finalize(traceid, prompt, self.core.llmData.AnswerList, self.log.info)

            if not processor.first_chunk_received:
                timer.cancel()
                self.log.info(f"[{traceid}] 流式未收到任何块，超时可能已触发")

            filtered_content = ResponseProcessor.remove_analysis(all_content)
            memory.add_assistant_message(filtered_content)
            self.core._write_chat_record(username, filtered_content, self.core.llmData.Ai_Name)
        else:
            response = self.llm.generate(messages, options=options)
            timer.cancel()
            if timeout_triggered.is_set():
                self.log.info(f"[{traceid}] 模型在超时后返回，缓冲语音已插入")

            filtered_content = ResponseProcessor.remove_analysis(response)
            memory.add_assistant_message(filtered_content)
            self.core._write_chat_record(username, filtered_content, self.core.llmData.Ai_Name)

            processor = ResponseProcessor(
                split_chars=self.core.llmData.split_str,
                split_limit=self.core.llmData.split_limit
            )
            processor.process_and_queue(response, traceid, prompt, self.core.llmData.AnswerList, self.log.info)

        # 场景切换
        scene = SceneManager.get_scene(all_content if use_stream else response)
        if scene:
            self.actionOper.changeScene(scene)

        current_question_count = self.core.llmData.QuestionList.qsize()
        self.log.info(f"[{traceid}][AI回复]{all_content if use_stream else response}")
        self.log.info(f"[{traceid}]System>>[{username}]的回复已存入队列，当前剩余问题数:{current_question_count}")

        self.core.llmData.is_ai_ready = True

    def _handle_bigmodel(self, prompt, uid, username, relation, traceid, selected_character):
        """处理智谱 BigModel 分支"""
        uid_str = str(uid)
        memory = self.core._ensure_memory_manager(uid_str, username)
        memory.add_user_message(prompt, username)

        use_long_term = self.core.should_use_long_term_memory(prompt)
        if use_long_term:
            messages = memory.build_messages(prompt, username=username, include_long_term=True)
            self.log.info(f"[{traceid}] 触发长期记忆，加载背景")
        else:
            messages = memory.build_messages(prompt, username=username, include_long_term=False)
            self.log.info(f"[{traceid}] 未触发长期记忆，仅使用短期记忆")

        # 构建最终消息（使用选中的角色卡）
        builder = MessageBuilder(character=selected_character)
        messages = builder.build(messages, relation, username, include_identity=True)

        # 配置选项
        options = {
            "temperature": selected_character.temperature if selected_character.temperature is not None else 0.7,
            "max_tokens": selected_character.max_tokens if selected_character.max_tokens is not None else 1024,
        }

        # 动态调整 max_tokens
        prompt_len = len(prompt)
        original_max_tokens = options["max_tokens"]
        token_strategy = getattr(selected_character, 'token_strategy', 'chat')
        options["max_tokens"] = self._adjust_max_tokens(traceid, original_max_tokens, prompt_len, token_strategy)

        # 超时设置
        response_cfg = self.config.get('response', {})
        timeout_seconds = response_cfg.get('timeout_seconds', 3)
        timeout_phrases = response_cfg.get('timeout_phrases', ["喵呜想一想"])
        timeout_triggered = threading.Event()
        timer = None

        def on_timeout():
            if not timeout_triggered.is_set():
                phrase = random.choice(timeout_phrases)
                self.log.info(f"[{traceid}] 响应超时，插入缓冲语音: {phrase}")
                self.ttsCore.tts_say(phrase)
                timeout_triggered.set()

        timer = threading.Timer(timeout_seconds, on_timeout)
        timer.start()

        # 流式处理
        response_generator = self.llm.generate_stream(messages, options=options)
        processor = self._create_streaming_processor(traceid, prompt)
        all_content = ""
        #subtitle_server = get_subtitle_server()
        for chunk in response_generator:
            if not processor.first_chunk_received:
                timer.cancel()
            processor.process_chunk(chunk, traceid, prompt, self.core.llmData.AnswerList, self.log.info)
            all_content += chunk
            #subtitle_server.send_subtitle(all_content)

        processor.finalize(traceid, prompt, self.core.llmData.AnswerList, self.log.info)

        if not processor.first_chunk_received:
            timer.cancel()
            self.log.info(f"[{traceid}] 流式未收到任何块，超时可能已触发")

        # 清理并保存
        filtered_content = ResponseProcessor.remove_analysis(all_content)
        memory.add_assistant_message(filtered_content)
        self.core._write_chat_record(username, filtered_content, self.core.llmData.Ai_Name)

        # 场景切换
        scene = SceneManager.get_scene(all_content)
        if scene:
            self.actionOper.changeScene(scene)

        current_question_count = self.core.llmData.QuestionList.qsize()
        self.log.info(f"[{traceid}][AI回复]{all_content}")
        self.log.info(f"[{traceid}]System>>[{username}]的回复已存入队列，当前剩余问题数:{current_question_count}")

        self.core.llmData.is_ai_ready = True

