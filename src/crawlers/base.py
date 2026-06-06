"""
爬虫基类
=======
提供通用的请求、重试、缓存和反爬能力。
"""

import hashlib
import json
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

from ..models.schemas import RawItem


class BaseCrawler(ABC):
    """爬虫抽象基类，提供通用能力。"""

    def __init__(self, settings, cache_dir: Path):
        """
        Args:
            settings: Settings 实例
            cache_dir: 缓存数据目录
        """
        self.settings = settings
        self.crawler_config = settings.crawler_settings
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 请求会话
        self._session: Optional[requests.Session] = None

        # 失败计数器（用于告警判断）
        self._fail_count: int = 0

    @property
    def session(self) -> requests.Session:
        """懒加载 HTTP 会话"""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
        return self._session

    # ---------- 请求方法 ----------

    def fetch(self, url: str, timeout: int = None) -> Optional[str]:
        """
        发起 HTTP GET 请求，含重试和延迟。

        Args:
            url: 目标 URL
            timeout: 超时秒数，默认从配置读取

        Returns:
            响应文本，失败返回 None
        """
        if timeout is None:
            timeout = self.crawler_config.get("timeout_seconds", 30)

        max_retries = self.crawler_config.get("max_retries", 3)
        interval_min = self.crawler_config.get("request_interval_min", 5)
        interval_max = self.crawler_config.get("request_interval_max", 10)

        for attempt in range(1, max_retries + 1):
            try:
                # 随机延迟（反爬）
                delay = random.uniform(interval_min, interval_max)
                time.sleep(delay)

                resp = self.session.get(url, timeout=timeout)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"
                self._fail_count = 0  # 重置失败计数
                return resp.text

            except requests.RequestException as e:
                logger.warning(f"请求失败 (第{attempt}/{max_retries}次): {url} — {e}")
                if attempt == max_retries:
                    self._fail_count += 1
                    logger.error(f"请求彻底失败({self._fail_count}次连续失败): {url}")
                    return None

        return None

    def fetch_json(self, url: str, timeout: int = None) -> Optional[dict]:
        """发起请求并解析 JSON 响应。"""
        text = self.fetch(url, timeout)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON 解析失败: {url} — {e}")
        return None

    # ---------- 缓存方法 ----------

    def _get_cache_path(self, channel: str) -> Path:
        """获取某个渠道的缓存文件路径"""
        return self.cache_dir / f"cache_{channel}.json"

    def cache_raw_data(self, items: list[RawItem], channel: str):
        """缓存数据到本地 JSON 文件"""
        cache_path = self._get_cache_path(channel)
        data = {
            "cached_at": datetime.now().isoformat(),
            "channel": channel,
            "count": len(items),
            "items": [item.model_dump(mode="json") for item in items],
        }
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"已缓存 {len(items)} 条数据到 {cache_path}")

    def load_cached_data(self, channel: str) -> list[RawItem]:
        """
        从缓存加载数据（爬取失败时的回退策略）。

        Returns:
            RawItem 列表；如无缓存则返回空列表
        """
        cache_path = self._get_cache_path(channel)
        if not cache_path.exists():
            logger.warning(f"无缓存数据: {channel}")
            return []

        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            items = []
            for item_dict in data.get("items", []):
                # 恢复 datetime 字段
                if item_dict.get("publish_date"):
                    item_dict["publish_date"] = datetime.fromisoformat(item_dict["publish_date"])
                items.append(RawItem(**item_dict))

            logger.info(f"从缓存加载 {len(items)} 条数据 (缓存时间: {data.get('cached_at')})")
            return items
        except Exception as e:
            logger.error(f"缓存加载失败: {cache_path} — {e}")
            return []

    # ---------- 工具方法 ----------

    def _make_hash(self, text: str) -> str:
        """生成内容哈希"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @property
    def should_alert(self) -> bool:
        """连续失败3次以上触发告警"""
        return self._fail_count >= 3

    # ---------- 抽象方法 ----------

    @abstractmethod
    def crawl(self, *args, **kwargs) -> list[RawItem]:
        """
        执行爬取，返回 RawItem 列表。
        子类必须实现此方法。
        """
        ...
