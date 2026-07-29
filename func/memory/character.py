import yaml
from pathlib import Path
from typing import Dict, List, Optional

class CharacterCard:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.data = self._load()
        self.name = self.data.get("name", "喵呜")
        self.description = self.data.get("description", "")
        self.discipline = self.data.get("discipline", "")
        self.personality = self.data.get("personality", "")
        self.examples = self.data.get("examples", [])
        self.temperature = self.data.get("temperature")
        self.max_tokens = self.data.get("max_tokens")
        self.keywords = self.data.get("keywords", [])
        self.weight = self.data.get("weight", 1.0)
        self.token_strategy = self.data.get("token_strategy", "chat")

    def _load(self) -> Dict:
        with open(self.file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def build_system_prompt(self) -> str:
        prompt = f"你是一个角色，名叫{self.name}。{self.description}\n\n"
        prompt += "以下是你的性格设定：\n"
        prompt += self.personality
        prompt += "\n\n请严格按照以上设定扮演，只输出对话内容，不要添加动作描述或多余解释。"
        return prompt

    def build_few_shot_messages(self) -> List[Dict[str, str]]:
        messages = []
        for ex in self.examples:
            messages.append({"role": "user", "content": ex["user"]})
            messages.append({"role": "assistant", "content": ex["assistant"]})
        return messages
