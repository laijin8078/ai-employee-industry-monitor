"""
浏览器采集器（可选 Playwright 兜底）
===================================
当 requests 因 SSL/JS 渲染/反爬失败时，
使用 Playwright 浏览器进行兜底采集。

Playwright 为可选依赖，未安装时优雅降级。
"""

from typing import Optional
from loguru import logger

# Playwright 为可选依赖
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    _has_playwright = True
except ImportError:
    sync_playwright = None
    PlaywrightTimeoutError = Exception
    _has_playwright = False


class BrowserFetcher:
    """通用浏览器采集器，用于处理 requests 无法采集的页面"""

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30000,
        user_data_dir: Optional[str] = None,
    ):
        """
        Args:
            headless: 是否无头模式
            timeout_ms: 页面加载超时（毫秒）
            user_data_dir: 持久化浏览器 Profile 目录（用于微信等需要登录的站点）
        """
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_data_dir = user_data_dir

    @property
    def is_available(self) -> bool:
        return _has_playwright

    def fetch_html(self, url: str, wait_selector: Optional[str] = None) -> dict:
        """
        使用 Playwright 浏览器获取页面 HTML。

        Args:
            url: 目标 URL
            wait_selector: 可选，等待某个 CSS 选择器出现后再获取内容

        Returns:
            {"url": str, "status": int|None, "html": str, "error": str|None}
        """
        if not self.is_available:
            return {
                "url": url, "status": None, "html": "",
                "error": "Playwright 未安装（pip install playwright && playwright install chromium）",
            }

        logger.info(f"[Browser] 正在加载: {url}")

        try:
            with sync_playwright() as p:
                # 启动浏览器
                if self.user_data_dir:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=self.user_data_dir,
                        headless=self.headless,
                        locale="zh-CN",
                        timezone_id="Asia/Shanghai",
                        viewport={"width": 1366, "height": 768},
                        ignore_https_errors=True,
                    )
                    browser = None
                else:
                    browser = p.chromium.launch(headless=self.headless)
                    context = browser.new_context(
                        ignore_https_errors=True,
                        locale="zh-CN",
                        timezone_id="Asia/Shanghai",
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        viewport={"width": 1366, "height": 768},
                    )

                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)

                try:
                    response = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )

                    if wait_selector:
                        page.wait_for_selector(wait_selector, timeout=10000)

                    html = page.content()
                    status = response.status if response else None

                    return {
                        "url": url,
                        "status": status,
                        "html": html,
                        "error": None,
                    }

                except PlaywrightTimeoutError as e:
                    return {"url": url, "status": None, "html": "", "error": f"timeout: {e}"}

                finally:
                    context.close()
                    if browser:
                        browser.close()

        except Exception as e:
            return {"url": url, "status": None, "html": "", "error": str(e)}

    def is_accessible(self, url: str) -> bool:
        """快速检查 URL 是否可通过浏览器访问"""
        result = self.fetch_html(url)
        if result["error"]:
            logger.warning(f"[Browser] 不可达: {url} — {result['error']}")
            return False
        return bool(result["html"] and len(result["html"]) > 200)
