"""
爬虫基类
=======
提供通用的请求、重试、缓存、反爬冷却和降级能力。
"""

import hashlib
import json
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
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

        # 失败计数器
        self._fail_count: int = 0

        # 反爬冷却：{source_name: {"until": datetime, "reason": str}}
        self._blocked_sources: dict[str, dict] = {}

        # 本轮来源健康报告：{source_name: {"status": str, "error": str, "raw_count": int, "fallback_used": bool}}
        self.source_health: dict[str, dict] = {}

        # 403 反爬日志去重（同源只报一次）
        self._antispam_logged: set = set()

        # 取消检查（由外部设置）
        self.cancel_check = lambda: False

    # ---------- 反爬冷却 ----------

    def is_source_blocked(self, source_name: str) -> bool:
        """检查来源是否处于冷却期"""
        entry = self._blocked_sources.get(source_name)
        if not entry:
            return False
        if datetime.now() < entry["until"]:
            return True
        # 冷却期已过，自动解除
        del self._blocked_sources[source_name]
        return False

    def block_source(self, source_name: str, reason: str, cooldown_seconds: int = 600):
        """
        标记来源为 blocked，进入冷却期。
        默认 10 分钟冷却，可按来源调整。
        """
        until = datetime.now() + timedelta(seconds=cooldown_seconds)
        self._blocked_sources[source_name] = {"until": until, "reason": reason}
        self.source_health[source_name] = {
            "status": "blocked", "error": reason,
            "raw_count": 0, "fallback_used": False,
        }
        # 只打一次日志
        if source_name not in self._antispam_logged:
            logger.warning(f"🛡️ [{source_name}] 触发反爬保护，冷却 {cooldown_seconds}s: {reason}")
            self._antispam_logged.add(source_name)

    # ---------- 来源健康 ----------

    def record_source_health(self, source_name: str, status: str, raw_count: int = 0,
                              error: str = "", fallback_used: bool = False):
        """记录来源健康状态"""
        self.source_health[source_name] = {
            "status": status, "error": error,
            "raw_count": raw_count, "fallback_used": fallback_used,
        }

    # ---------- 请求会话 ----------

    @property
    def session(self) -> requests.Session:
        """懒加载 HTTP 会话"""
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
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

    def fetch(self, url: str, timeout: int = None, source_name: str = "") -> Optional[str]:
        """
        发起 HTTP GET 请求，含重试、延迟和反爬检测。

        - 遇到 403 + antispider → 立即停止重试，标记 source 为 blocked
        - SSLError → 不重试，直接返回 None 供上层 fallback
        """
        if timeout is None:
            timeout = self.crawler_config.get("timeout_seconds", 30)

        max_retries = self.crawler_config.get("max_retries", 3)
        interval_min = self.crawler_config.get("request_interval_min", 5)
        interval_max = self.crawler_config.get("request_interval_max", 10)

        for attempt in range(1, max_retries + 1):
            try:
                delay = random.uniform(interval_min, interval_max)
                time.sleep(delay)

                resp = self.session.get(url, timeout=timeout)

                # 反爬检测：HTTP 403 且 URL 包含 antispider 特征
                if resp.status_code == 403:
                    is_antispam = any(kw in url.lower() for kw in ["antispider", "captcha", "verify", "challenge"])
                    if is_antispam or "sogou" in url.lower():
                        src = source_name or url
                        self.block_source(src, f"HTTP 403 反爬拦截", cooldown_seconds=600)
                        return None  # 立即停止，不重试

                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"
                self._fail_count = 0
                return resp.text

            except requests.exceptions.SSLError as e:
                # SSL 错误不重试，交给上层 Playwright fallback
                src = source_name or url
                logger.info(f"🔒 [{src}] SSL 验证失败，将启用浏览器兜底: {e}")
                self._fail_count += 1
                return None

            except requests.RequestException as e:
                src = source_name or url
                # 403 反爬（通用检测）
                if hasattr(e, 'response') and e.response is not None and e.response.status_code == 403:
                    is_antispam = any(kw in url.lower() for kw in ["antispider", "captcha", "verify", "challenge"])
                    if is_antispam or "sogou" in url.lower():
                        self.block_source(src, f"HTTP 403 ({e})", cooldown_seconds=600)
                        return None

                if attempt < max_retries:
                    logger.debug(f"请求失败 (第{attempt}/{max_retries}次): [{src}] {e}")
                else:
                    self._fail_count += 1
                    logger.error(f"请求彻底失败(fail#{self._fail_count}): [{src}] {e}")
                    return None

        return None

    def fetch_fast(self, url: str, source_name: str = "") -> Optional[str]:
        """
        快速请求（用于新闻搜索等对速度要求高的场景）。
        延迟 0.5-2 秒，超时 10 秒，仅重试 1 次。
        """
        for attempt in range(1, 3):
            try:
                time.sleep(random.uniform(0.5, 2.0))
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 403:
                    is_antispam = any(kw in url.lower() for kw in ["antispider", "captcha", "verify", "challenge"])
                    if is_antispam or "sogou" in url.lower():
                        self.block_source(source_name or url, "HTTP 403 反爬拦截", cooldown_seconds=600)
                        return None
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"
                self._fail_count = 0
                return resp.text
            except requests.exceptions.SSLError:
                return None
            except requests.RequestException:
                if attempt == 2:
                    self._fail_count += 1
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
                if item_dict.get("publish_date"):
                    item_dict["publish_date"] = datetime.fromisoformat(item_dict["publish_date"])
                items.append(RawItem(**item_dict))

            logger.info(f"从缓存加载 {len(items)} 条数据 (缓存时间: {data.get('cached_at')})")
            return items
        except Exception as e:
            logger.error(f"缓存加载失败: {cache_path} — {e}")
            return []

    def load_cached_data_recent(self, channel: str, max_age_days: int = 7) -> list[RawItem]:
        """
        查最近 N 天内最近一次成功的缓存（兜底增强版）。
        优先精确匹配 channel，匹配不到则尝试 channel_all。
        """
        candidates = []
        # 精确匹配
        cache_path = self._get_cache_path(channel)
        if cache_path.exists():
            candidates.append(cache_path)
        # 兜底匹配（如 website_美的净水 → website_all）
        if "_" in channel:
            fallback_channel = channel.rsplit("_", 1)[0] + "_all"
            fb_path = self._get_cache_path(fallback_channel)
            if fb_path.exists():
                candidates.append(fb_path)

        best_path = None
        best_mtime = 0
        cutoff = datetime.now() - timedelta(days=max_age_days)

        for p in candidates:
            try:
                mtime = p.stat().st_mtime
                mtime_dt = datetime.fromtimestamp(mtime)
                if mtime_dt >= cutoff and mtime > best_mtime:
                    best_mtime = mtime
                    best_path = p
            except OSError:
                continue

        if best_path:
            try:
                data = json.loads(best_path.read_text(encoding="utf-8"))
                items = []
                for item_dict in data.get("items", []):
                    if item_dict.get("publish_date"):
                        item_dict["publish_date"] = datetime.fromisoformat(item_dict["publish_date"])
                    items.append(RawItem(**item_dict))
                logger.info(f"从近期缓存加载 {len(items)} 条 (文件: {best_path.name}, 时间: {data.get('cached_at')})")
                return items
            except Exception as e:
                logger.error(f"近期缓存加载失败: {best_path} — {e}")

        # 退回到原有缓存加载
        return self.load_cached_data(channel)

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
        """执行爬取，返回 RawItem 列表。子类必须实现此方法。"""
        ...
