# src/agent_dsl/llm_agent.py
import json
import requests
from typing import Optional, List
from pathlib import Path

class DeepSeekClient:
    """
    DeepSeek Chat API 调用。
    优先从项目根目录的 config.json 读取 deepseek_api_key；
    若没有则进入离线演示模式（简单关键词“模拟”）。
    """
    def __init__(self, model: str = "deepseek-chat"):
        self.model = model
        self.api_key = self._load_api_key()
        self.api_url = "https://api.deepseek.com/v1/chat/completions"

    def _load_api_key(self) -> str:
        config_path = Path(__file__).resolve().parents[1] / "config.json"
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                key = cfg.get("deepseek_api_key")
                if key:
                    print(f"[DeepSeekClient] 从 config.json 读取到 API Key。")
                    return key
            except Exception as e:
                print(f"[DeepSeekClient] 读取 config.json 出错：{e}")
        print("[DeepSeekClient] 未找到有效 API Key，使用离线演示模式。")
        return "DEMO_KEY_HERE"

    def classify_intent(
        self,
        user_input: str,
        available_targets: List[str],
        exclude: Optional[List[str]] = None
    ) -> Optional[str]:
        """返回最合适的目标状态；若失败返回 None。"""
        ex_set = set(exclude or [])            # ← 不覆盖参数名，单独用 ex_set
        candidates = [t for t in available_targets if t not in ex_set]
        if not candidates:
            return None

        # 离线演示：简单关键字匹配
        if self.api_key == "DEMO_KEY_HERE":
            text = user_input.lower()
            for t in candidates:
                if t.lower() in text or text in t.lower():
                    return t
            return None

        system_prompt = (
            "你是一个智能意图分类器。"
            "给定用户输入和候选状态名称，你需要从候选集中选择最可能匹配的状态。"
            "只输出状态名称本身，不要解释。"
        )
        user_prompt = f"候选状态：{candidates}\n用户输入：{user_input}\n请返回最合适的状态名称："

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 20,
            "temperature": 0.3,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(self.api_url, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            result = data["choices"][0]["message"]["content"].strip()
            # 优先精确/包含匹配候选集合
            for cand in candidates:
                if cand.lower() == result.lower() or cand.lower() in result.lower():
                    return cand
            token = (result.split() or [""])[0]
            return token if token in candidates else None
        except Exception as e:
            print(f"[DeepSeekClient] 调用失败：{e}")
            return None
