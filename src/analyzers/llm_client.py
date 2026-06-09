"""
LLM API 客户端
==============
封装 Anthropic Claude API 调用，
支持批量分析、结构化 JSON 输出、错误重试。
"""

import asyncio
import json
import re
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from loguru import logger

# anthropic 为可选依赖（mock 模式不需要）
try:
    from anthropic import Anthropic
    _has_anthropic = True
except ImportError:
    Anthropic = None
    _has_anthropic = False


class LLMClient:
    """Claude API 调用封装"""

    # JSON 提取正则（匹配 ```json ... ``` 或直接 { ... }）
    JSON_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)```|(\{[\s\S]*\})")

    def __init__(
        self,
        api_key: str,
        provider: str = "anthropic",
        api_base: str = "",
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_concurrent: int = 5,
        api_timeout: int = 30,
    ):
        """
        Args:
            api_key: Anthropic API Key
            provider: anthropic / deepseek / openai_compatible
            api_base: OpenAI-compatible API base URL
            model: 模型名称
            max_tokens: 最大输出 token
            temperature: 生成温度（0-1，越低越确定）
            max_concurrent: 最大并发调用数
        """
        self.provider = (provider or "anthropic").lower()
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_concurrent = max_concurrent

        # 单次 API 调用超时（秒），防止请求长时间阻塞
        self.api_timeout = api_timeout

        self._client = Anthropic(api_key=api_key) if (self.provider == "anthropic" and api_key and _has_anthropic) else None
        self._semaphore = asyncio.Semaphore(max_concurrent)

    @property
    def is_available(self) -> bool:
        """检查 API 是否可用"""
        if self.provider == "anthropic":
            return self._client is not None
        return bool(self.api_key)

    def chat(
        self,
        user_message: str,
        system_prompt: str = "",
        temperature: float = None,
        max_tokens: int = None,
    ) -> Optional[str]:
        """
        单次对话调用。

        Args:
            user_message: 用户消息
            system_prompt: 系统提示
            temperature: 温度（默认用实例配置）
            max_tokens: 最大 token（默认用实例配置）

        Returns:
            AI 响应文本，失败返回 None
        """
        if not self.is_available:
            logger.error("LLM 客户端未初始化（缺少 API Key）")
            return None

        if temperature is None:
            temperature = self.temperature
        if max_tokens is None:
            max_tokens = self.max_tokens

        try:
            # 设置超时防止长时间卡住（连接10s，读取30s）
            import httpx
            try:
                # 使用线程池执行同步调用，并设置超时以防阻塞
                def _call():
                    if self.provider == "anthropic":
                        return self._client.messages.create(
                            model=self.model,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            system=system_prompt,
                            messages=[{"role": "user", "content": user_message}],
                        )
                    return self._chat_openai_compatible(
                        user_message=user_message,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(_call)
                    try:
                        message = future.result(timeout=self.api_timeout)
                    except FuturesTimeout:
                        logger.error(f"LLM 调用超时（>{self.api_timeout}s）")
                        return None

                if isinstance(message, str):
                    return message

                # 提取 Anthropic 文本内容
                content = message.content
                if isinstance(content, list):
                    text = "".join(
                        block.text if hasattr(block, "text") else str(block)
                        for block in content
                    )
                else:
                    text = str(content)

                return text

            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                return None
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return None

    def _chat_openai_compatible(
        self,
        user_message: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """调用 DeepSeek / OpenAI-compatible Chat Completions API"""
        import httpx

        api_base = self.api_base
        if not api_base:
            api_base = "https://api.deepseek.com" if self.provider == "deepseek" else "https://api.openai.com/v1"
        url = f"{api_base.rstrip('/')}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.api_timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def chat_json(
        self,
        user_message: str,
        system_prompt: str = "",
        temperature: float = None,
    ) -> Optional[dict]:
        """
        单次对话调用，并尝试解析为 JSON。

        支持两种输出模式：
        1. JSON 代码块: ```json { ... } ```
        2. 纯 JSON: { ... }
        """
        response = self.chat(
            user_message=user_message,
            system_prompt=system_prompt + "\n请直接输出JSON，不要包含其他文本。",
            temperature=temperature or 0.2,  # JSON 模式使用更低温度
        )

        if response is None:
            return None

        return self._extract_json(response)

    def batch_analyze(
        self,
        items: list,
        system_prompt: str,
        user_message_template: str,
        temperature: float = None,
        max_concurrent: int = None,
    ) -> list[Optional[dict]]:
        """
        批量分析（顺序执行，可升级为异步并发）。

        Args:
            items: 待分析条目列表
            system_prompt: 系统提示
            user_message_template: 用户消息模板（{title}, {content} 等占位符）
            temperature: 温度
            max_concurrent: 并发数

        Returns:
            分析结果列表（与 items 顺序对应）
        """
        if max_concurrent is None:
            max_concurrent = self.max_concurrent

        results = []
        total = len(items)

        for i, item in enumerate(items, 1):
            # 构建用户消息
            if hasattr(item, 'raw'):
                # CleanedItem
                title = item.raw.title
                content = item.raw.content
                source = item.raw.source_name
                publish_date = str(item.raw.publish_date or "")
            elif hasattr(item, 'item'):
                # ScreeningResult
                title = item.item.raw.title
                content = item.item.raw.content
                source = item.item.raw.source_name
                publish_date = str(item.item.raw.publish_date or "")
            else:
                title = str(item)
                content = ""
                source = ""
                publish_date = ""

            user_message = user_message_template.format(
                title=title,
                content=content[:2000],  # 限制内容长度
                source=source,
                publish_date=publish_date,
                index=i,
            )

            logger.info(f"[LLM批量] 分析 {i}/{total}: {title[:50]}...")

            result = self.chat_json(
                user_message=user_message,
                system_prompt=system_prompt,
                temperature=temperature,
            )
            results.append(result)

        return results

    def _extract_json(self, text: str) -> Optional[dict]:
        """从 AI 响应中提取 JSON"""
        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试正则提取
        match = self.JSON_PATTERN.search(text)
        if match:
            json_str = match.group(1) or match.group(2)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"JSON 解析失败: {json_str[:100]}...")

        logger.warning(f"无法从响应中提取 JSON: {text[:200]}...")
        return None

    def generate_summary(self, text: str, max_length: int = 150) -> str:
        """生成简短摘要"""
        if not self.is_available:
            return text[:max_length]

        response = self.chat(
            user_message=f"请用不超过{max_length}字概括以下内容的核心要点：\n\n{text[:3000]}",
            system_prompt="你是一个专业的文本摘要助手。请用简洁的中文概括。",
            temperature=0.2,
            max_tokens=300,
        )
        return response or text[:max_length]
