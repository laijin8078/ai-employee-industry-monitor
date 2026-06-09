"""
主流程编排
==========
AI员工的核心执行引擎，编排完整的10步情报处理流水线：
1. 定时触发
2. 并行采集（3个渠道）
3. 数据清洗去重
4. AI初筛
5. AI深度分析
6. 竞品汇总
7. 报告生成
8. 附件处理
9. 通知发送
10. 数据归档

用法:
    python -m src.main --once              # 单次执行
    python -m src.main --once --mock       # 使用模拟数据测试
    python -m src.main --schedule          # 启动定时调度（每两周）
"""

import argparse
import sys
import time
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from .config.settings import get_settings
from .models.schemas import RawItem, CleanedItem, DeepAnalysis
from .crawlers import WechatCrawler, WebsiteCrawler, NewsCrawler
from .processors import DataCleaner
from .analyzers import LLMClient, IntelligenceScreener, DeepAnalyzer
from .reporters import JSONReporter, HTMLReporter
from .notifiers import EmailNotifier
from .storage import IntelligenceDB


class JobCancelledError(Exception):
    """任务被用户取消"""
    pass


# ============================================
# 日志配置
# ============================================

def setup_logging():
    """配置日志输出"""
    logger.remove()  # 移除默认 handler
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    # 文件日志
    log_dir = Path(__file__).resolve().parent.parent / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "intelligence.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {name}:{function}:{line} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="30 days",
        encoding="utf-8",
    )


# ============================================
# 流水线编排
# ============================================

class IntelligencePipeline:
    """情报采集分析流水线"""

    def __init__(self, mock_mode: bool = False, log_callback=None, job_id_override: str = None, cancel_check=None):
        """
        Args:
            mock_mode: 使用模拟数据（用于测试，不需要真实爬虫和API）
            log_callback: 可选回调函数，用于实时推送日志到前端
                         签名: (level: str, message: str, step: str, source: str, status: str)
            job_id_override: 外部指定的 job_id（API层传入），为空则自动生成
            cancel_check: 可选回调 () -> bool，返回 True 表示任务已被取消
        """
        self.mock_mode = mock_mode
        self.log_callback = log_callback
        self.cancel_check = cancel_check or (lambda: False)
        self.settings = get_settings()
        self.job_id = job_id_override or f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        # 初始化数据库
        self.db = IntelligenceDB(self.settings.db_path)

        # 初始化 LLM 客户端
        self.llm = LLMClient(
            api_key=self.settings.llm_api_key if not mock_mode else "",
            provider=self.settings.llm_provider,
            api_base=self.settings.ai_settings.get("api_base", ""),
            model=self.settings.ai_settings.get("model", "claude-sonnet-4-6"),
            max_tokens=self.settings.ai_settings.get("max_tokens", 4096),
            temperature=self.settings.ai_settings.get("temperature", 0.3),
            max_concurrent=self.settings.ai_settings.get("max_concurrent", 5),
        )

        # 初始化爬虫（仅非 mock 模式）
        if not mock_mode:
            self.wechat_crawler = WechatCrawler(self.settings, self.settings.raw_data_dir)
            self.website_crawler = WebsiteCrawler(self.settings, self.settings.raw_data_dir)
            self.news_crawler = NewsCrawler(self.settings, self.settings.raw_data_dir)
            # 注入取消检查回调
            for c in [self.wechat_crawler, self.website_crawler, self.news_crawler]:
                c.cancel_check = self.cancel_check

        # 初始化处理器
        self.cleaner = DataCleaner(
            title_similarity_threshold=self.settings.title_similarity_threshold,
            max_news_age_days=self.settings.max_news_age_days,
            keyword_whitelist=self.settings.keyword_whitelist,
            competitor_blacklist=self.settings.competitor_blacklist,
        )

        # 初始化分析器
        self.screener = IntelligenceScreener(self.llm, self.settings.company_context)
        self.deep_analyzer = DeepAnalyzer(self.llm, self.settings.company_context)

        # 初始化报告生成器
        self.json_reporter = JSONReporter(
            self.settings.reports_dir, self.settings.company_context
        )
        self.html_reporter = HTMLReporter(self.settings.templates_dir)

        # 初始化通知器
        self.notifier = EmailNotifier(self.settings.smtp_config)

    # ==================== 日志辅助 ====================

    def _emit_log(self, level: str, message: str, step: str = "", source: str = "", status: str = ""):
        """发送日志到 logger 和可选的 log_callback。每次调用同时检查取消信号。"""
        # 先检查取消（确保高频调用点能及时响应中断）
        if self.cancel_check and self.cancel_check():
            raise JobCancelledError(self.job_id)
        log_func = getattr(logger, level, logger.info)
        log_func(message)
        if self.log_callback:
            try:
                self.log_callback(level, message, step, source, status)
            except Exception:
                pass

    def _check_cancelled(self):
        """检查任务是否被取消，若已取消则抛出异常中断流水线"""
        if self.cancel_check and self.cancel_check():
            raise JobCancelledError(self.job_id)

    def _update_heartbeat(self, stage: str = "", items_collected: int = None):
        """更新任务心跳（防止被标记为超时）"""
        try:
            self.db.update_job_heartbeat(self.job_id, stage=stage, items_collected=items_collected)
        except Exception:
            pass

    # ==================== 主流程 ====================

    def run(self) -> dict:
        """
        执行完整的情报采集分析流水线。

        Returns:
            执行结果摘要字典
        """
        start_time = time.time()
        channels_succeeded = []
        channels_failed = []

        try:
            self._emit_log("info", "=" * 50, step="启动")
            self._emit_log("info", f"🚀 AI情报系统启动 [Job: {self.job_id}]", step="启动")
            self._emit_log("info", f"   模式: {'Mock模拟' if self.mock_mode else '真实采集'}", step="启动")
            self._emit_log("info", f"   监控范围: {len(self.settings.competitor_wechat)}公众号 "
                        f"+ {len(self.settings.competitor_websites)}网站 "
                        f"+ {len(self.settings.industry_keywords)}关键词", step="启动")
            self._emit_log("info", "=" * 50, step="启动")

            # 创建任务记录
            self.db.create_job(self.job_id)
            self._update_heartbeat(stage="starting")
            # === 步骤 2: 数据采集（3个渠道并行） ===
            self._check_cancelled()
            self._update_heartbeat(stage="collecting")
            logger.info("\n📡 [步骤 2/10] 数据采集 — 3个渠道并行启动...")
            raw_items, channels_succeeded, channels_failed, source_health = self._collect_data()

            if not raw_items:
                logger.warning("⚠ 所有渠道采集均为空！")
                # 尝试从缓存回退
                raw_items = self._load_all_cached()
                if not raw_items:
                    return self._empty_result(channels_failed)

            logger.info(f"✅ 采集完成: {len(raw_items)} 条原始数据")
            self._update_heartbeat(stage="collecting", items_collected=len(raw_items))

            # === 步骤 3: 数据清洗与去重 ===
            self._check_cancelled()
            self._update_heartbeat(stage="cleaning", items_collected=len(raw_items))
            self._emit_log("info", "🧹 [步骤 3/10] 数据清洗与去重...", step="清洗")
            cleaned_items = self.cleaner.process(raw_items)
            dedup_count = self.cleaner.get_dedup_stats(cleaned_items).get('duplicates_removed', 0)
            self._emit_log("success", f"✅ 清洗完成: {len(cleaned_items)} 条有效数据 (去重 {dedup_count} 条)", step="清洗", status="success")

            # 保存原始数据
            self.db.save_raw_items(self.job_id, [c.raw for c in cleaned_items])

            # === 步骤 4: AI 初筛 ===
            self._check_cancelled()
            self._update_heartbeat(stage="screening", items_collected=len(cleaned_items))
            self._emit_log("info", f"🔍 [步骤 4/10] AI 初筛 — {len(cleaned_items)} 条数据判断相关性和优先级...", step="AI初筛")
            # 注入进度回调，前端可看到实时进度
            self.screener._progress_callback = lambda msg: self._emit_log("info", msg, step="AI初筛")
            screening_results = self.screener.screen(cleaned_items)
            important_count = len(self.screener.filter_important(screening_results))
            self._emit_log("success", f"✅ 初筛完成: {len(screening_results)}条判定, {important_count}条需要深度分析", step="AI初筛", status="success")

            # === 步骤 5: AI 深度分析 ===
            self._check_cancelled()
            important = self.screener.filter_important(screening_results)
            self._update_heartbeat(stage="analyzing")
            self._emit_log("info", f"🧠 [步骤 5/10] AI 深度分析 — {len(important)} 条重要情报...", step="深度分析")
            deep_analyses = self.deep_analyzer.analyze(important)
            self._emit_log("success", f"✅ 深度分析完成: {len(deep_analyses)}条", step="深度分析", status="success")

            # === 步骤 6: 竞品汇总 ===
            self._update_heartbeat(stage="summarizing")
            logger.info(f"\n📋 [步骤 6/10] 竞品动态汇总...")
            # (汇总在 json_reporter.generate 中完成)

            # === 步骤 7: 生成报告 ===
            self._update_heartbeat(stage="reporting")
            self._emit_log("info", "📝 [步骤 7/10] 生成情报报告...", step="报告生成")
            report = self.json_reporter.generate(
                analyses=deep_analyses,
                all_screening_results=screening_results,
                report_date=date.today(),
                notification_recipients=self.settings.email_recipients,
                source_health=source_health,
            )

            # 保存 JSON 报告
            json_path = self.json_reporter.save(report)
            report_file_stem = Path(json_path).stem

            # 生成 HTML 报告
            html_content = self.html_reporter.render(report)
            html_path = self.html_reporter.save(report, self.settings.reports_dir, filename_stem=report_file_stem)
            self._emit_log("success", f"✅ 报告生成完成: JSON={Path(json_path).name}, HTML={Path(html_path).name if html_path else 'N/A'}", step="报告生成", status="success")

            # === 步骤 8: 附件处理（MVP 跳过） ===
            logger.info(f"\n📎 [步骤 8/10] 附件处理 — MVP版本跳过")

            # === 步骤 9: 发送通知 ===
            self._update_heartbeat(stage="notifying")
            self._emit_log("info", "📬 [步骤 9/10] 发送通知...", step="通知")
            notification_sent = self._send_notifications(report, html_content, json_path)
            self._emit_log("info" if notification_sent else "warning",
                f"{'✅ 通知已发送' if notification_sent else '⚠ 通知跳过（SMTP未配置）'}", step="通知",
                status="success" if notification_sent else "warning")

            # === 步骤 10: 数据归档 ===
            logger.info(f"\n💾 [步骤 10/10] 数据存储与归档...")
            report_dict = self.json_reporter._report_to_dict(report)
            report_dict["report_html_path"] = html_path or ""
            self.db.save_report(report_dict)
            self.db.cleanup_old_data(max_age_days=90)
            logger.info("✅ 数据已归档")

            # === 确定最终状态 ===
            elapsed = time.time() - start_time
            if channels_failed and not channels_succeeded:
                final_status = "failed"
            elif channels_failed and channels_succeeded:
                final_status = "partial"  # 部分渠道成功
            else:
                final_status = "success"

            self._update_heartbeat(stage="completed")
            self.db.update_job(
                self.job_id,
                status=final_status,
                channels_succeeded=channels_succeeded,
                channels_failed=channels_failed,
                total_items_collected=len(raw_items),
                important_items_found=len(deep_analyses),
                report_generated=True,
                duration_seconds=round(elapsed, 1),
            )

            # 输出最终摘要
            status_emoji = "🎉" if final_status == "success" else ("⚠️" if final_status == "partial" else "❌")
            self._emit_log("success" if final_status == "success" else "warning",
                f"{status_emoji} 情报采集分析完成！", step="完成", status=final_status)
            self._emit_log("info", f"   耗时: {elapsed:.1f} 秒", step="完成")
            self._emit_log("info", f"   采集: {len(raw_items)} 条 → 清洗: {len(cleaned_items)} 条 → 重要分析: {len(deep_analyses)} 条", step="完成")
            self._emit_log("info", f"   渠道: 成功{len(channels_succeeded)} / 失败{len(channels_failed)}", step="完成")
            if channels_failed:
                self._emit_log("warning", f"   失败渠道: {', '.join(channels_failed)}", step="完成")
            self._emit_log("info", f"   下次监控: {report.next_monitoring_date}", step="完成")

            return {
                "status": final_status,
                "job_id": self.job_id,
                "total_collected": len(raw_items),
                "cleaned": len(cleaned_items),
                "deep_analyzed": len(deep_analyses),
                "channels_succeeded": channels_succeeded,
                "channels_failed": channels_failed,
                "report_path": json_path,
                "html_path": html_path,
                "duration_seconds": round(elapsed, 1),
            }

        except JobCancelledError:
            # 注意：不能调用 _emit_log（会再次触发取消检查），直接用 logger 和 callback
            elapsed = time.time() - start_time
            logger.warning("🛑 用户中断采集")
            if self.log_callback:
                try:
                    self.log_callback("warning", "🛑 用户中断采集", "取消", "", "cancelled")
                except Exception:
                    pass
            self.db.update_job(
                self.job_id,
                status="failed",
                channels_succeeded=channels_succeeded,
                channels_failed=channels_failed,
                error_message="用户手动中断",
                duration_seconds=round(elapsed, 1),
            )
            return {"status": "cancelled", "job_id": self.job_id, "duration_seconds": round(elapsed, 1)}

        except Exception as e:
            logger.exception(f"❌ 流水线执行异常: {e}")
            elapsed = time.time() - start_time
            self.db.update_job(
                self.job_id,
                status="failed",
                channels_succeeded=channels_succeeded,
                channels_failed=channels_failed,
                error_message=str(e)[:500],
                duration_seconds=round(elapsed, 1),
            )
            return {"status": "failed", "error": str(e)}

    # ==================== 数据采集 ====================

    def _collect_data(self) -> tuple[list[RawItem], list[str], list[str], dict]:
        """
        并行采集3个渠道。

        Returns:
            (all_items, succeeded_channels, failed_channels, source_health)
        """
        all_items = []
        succeeded = []
        failed = []
        source_health = {}  # source_name → {"status": ..., "strategy": ..., "count": ..., "error": ...}

        if self.mock_mode:
            self._emit_log("info", "🎭 使用模拟数据...", step="采集")
            all_items = generate_mock_data()
            aggregated_health = {
                "wechat:美的净水": {"channel": "wechat", "source": "美的净水", "status": "ok", "error": "", "raw_count": 3, "fallback_used": False},
                "website:沁园": {"channel": "website", "source": "沁园", "status": "ok", "error": "", "raw_count": 2, "fallback_used": False},
                "website:安吉尔": {"channel": "website", "source": "安吉尔", "status": "ok", "error": "", "raw_count": 1, "fallback_used": False},
                "news:百度新闻": {"channel": "news", "source": "百度新闻", "status": "ok", "error": "", "raw_count": 4, "fallback_used": False},
            }
            return all_items, ["wechat", "website", "news"], [], aggregated_health

        # 输出各渠道具体监控目标
        wechat_names = self.settings.competitor_wechat
        website_configs = self.settings.competitor_websites
        keywords = self.settings.industry_keywords

        self._emit_log("info", f"📡 启动并行采集: {len(wechat_names)}个公众号 + {len(website_configs)}个网站 + 新闻搜索", step="采集", status="running")

        # 并行执行3个爬虫
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}

            futures["wechat"] = executor.submit(
                self.wechat_crawler.crawl,
                wechat_names,
                self.settings.max_news_age_days,
            )
            futures["website"] = executor.submit(
                self.website_crawler.crawl,
                website_configs,
                self.settings.max_news_age_days,
            )
            futures["news"] = executor.submit(
                self.news_crawler.crawl,
                keywords,
                self.settings.news_sources,
                self.settings.max_news_age_days,
            )

            # 收集结果（30分钟总超时，每30秒检查一次取消信号）
            for channel, future in futures.items():
                channel_label = {"wechat": "微信公众号", "website": "竞品官网", "news": "行业新闻"}.get(channel, channel)
                try:
                    self._emit_log("info", f"⏳ {channel_label} 采集中...", step="采集", source=channel, status="running")
                    # 分段等待，每5秒检查取消信号（确保快速响应中断）
                    items = None
                    waited = 0
                    chunk = 5  # 每5秒检查一次
                    total_timeout = 1800  # 总超时30分钟
                    while waited < total_timeout:
                        try:
                            items = future.result(timeout=chunk)
                            break
                        except TimeoutError:
                            waited += chunk
                            self._check_cancelled()  # 检查用户是否点了停止
                            self._update_heartbeat(stage="collecting")  # 保持心跳
                    if items is None:
                        raise TimeoutError(f"{channel_label} 采集超时（>{total_timeout}秒）")
                    if items:
                        # 按来源统计
                        source_counts = {}
                        for item in items:
                            src = getattr(item, 'source_name', '未知')
                            source_counts[src] = source_counts.get(src, 0) + 1

                        all_items.extend(items)
                        succeeded.append(channel)
                        source_health[channel] = {"status": "ok", "strategy": "requests", "count": len(items), "error": None}

                        # 详细日志：每个来源的结果
                        for src_name, count in source_counts.items():
                            self._emit_log("success", f"✅ [{channel_label}] {src_name}: 获取 {count} 条", step="采集", source=src_name, status="success")
                        self._emit_log("success", f"✅ {channel_label}: 共获取 {len(items)} 条", step="采集", source=channel, status="success")
                    else:
                        if channel == "wechat":
                            succeeded.append(channel)
                            source_health[channel] = {"status": "empty", "strategy": "search_engine", "count": 0, "error": "本期公众号无更新"}
                            self._emit_log("info", f"ℹ {channel_label}: 本期未发现新文章", step="采集", source=channel, status="empty")
                        else:
                            failed.append(channel)
                            source_health[channel] = {"status": "empty", "strategy": "requests", "count": 0, "error": "0条结果"}
                            self._emit_log("warning", f"⚠ {channel_label}: 0 条结果", step="采集", source=channel, status="empty")
                        # 输出该渠道每个目标的状态
                        if channel == "wechat":
                            for name in wechat_names:
                                wname = name if isinstance(name, str) else name.get("name", str(name))
                                self._emit_log("info", f"  ℹ 公众号「{wname}」: 本期未发现新文章", step="采集", source=wname, status="empty")
                        elif channel == "website":
                            for ws in website_configs:
                                wname = ws.get("name", "") if isinstance(ws, dict) else str(ws)
                                self._emit_log("warning", f"  ⚠ 网站「{wname}」: 未获取到数据", step="采集", source=wname, status="empty")

                except Exception as e:
                    failed.append(channel)
                    err_msg = str(e)[:100]
                    source_health[channel] = {"status": "failed", "strategy": "timeout", "count": 0, "error": err_msg}
                    self._emit_log("error", f"❌ {channel_label}: {err_msg}", step="采集", source=channel, status="failed")
                    # 该渠道所有目标标记失败
                    if channel == "wechat":
                        for name in wechat_names:
                            wname = name if isinstance(name, str) else name.get("name", str(name))
                            self._emit_log("error", f"  ❌ 公众号「{wname}」: 采集异常", step="采集", source=wname, status="failed")
                    elif channel == "website":
                        for ws in website_configs:
                            wname = ws.get("name", "") if isinstance(ws, dict) else str(ws)
                            self._emit_log("error", f"  ❌ 网站「{wname}」: 采集异常", step="采集", source=wname, status="failed")
                    logger.error(f"   ❌ {channel}: {e}")

        # 汇总来源健康（从各爬虫实例收集）
        aggregated_health = {}
        for channel, crawler in [("wechat", getattr(self, 'wechat_crawler', None)),
                                  ("website", getattr(self, 'website_crawler', None)),
                                  ("news", getattr(self, 'news_crawler', None))]:
            if crawler and hasattr(crawler, 'source_health'):
                for src_name, health in crawler.source_health.items():
                    key = f"{channel}:{src_name}"
                    aggregated_health[key] = {
                        "channel": channel, "source": src_name,
                        "status": health.get("status", "unknown"),
                        "error": health.get("error", ""),
                        "raw_count": health.get("raw_count", 0),
                        "fallback_used": health.get("fallback_used", False),
                    }

        self._emit_log("info",
            f"📊 采集汇总: 成功渠道 {len(succeeded)}/3, 共 {len(all_items)} 条原始数据",
            step="采集", status="success" if succeeded else "failed")

        # 有被屏蔽/降级的源输出合并日志（前端只显示一条）
        blocked_entries = {k: v for k, v in aggregated_health.items() if v["status"] in ("blocked", "degraded")}
        if blocked_entries:
            blocked_list = [f"{v['source']}({v['status']})" for v in blocked_entries.values()]
            self._emit_log("warning",
                f"🛡️ 反爬/降级源: {', '.join(blocked_list)}（已跳过，由正常源补偿）",
                step="采集", status="warning")

        return all_items, succeeded, failed, aggregated_health

    def _load_all_cached(self) -> list[RawItem]:
        """从缓存加载所有渠道数据（失败回退）"""
        all_items = []
        for channel in ["wechat", "website", "news"]:
            # 尝试不同渠道的爬虫缓存
            for crawler in [getattr(self, 'wechat_crawler', None),
                           getattr(self, 'website_crawler', None),
                           getattr(self, 'news_crawler', None)]:
                if crawler:
                    cached = crawler.load_cached_data(f"{channel}_all")
                    if cached:
                        all_items.extend(crawler.filter_recent_items(cached, self.settings.max_news_age_days))
                        break
        return all_items

    # ==================== 通知 ====================

    def _send_notifications(
        self,
        report,
        html_content: str,
        json_path: str,
    ) -> bool:
        """发送邮件和企微通知"""
        sent = False

        # 判断通知策略
        if self.notifier.should_send_immediate(report):
            # 高优先级：立即发送邮件 + 企微
            logger.info("   🚨 发现高优先级情报，立即通知！")
            sent = self.notifier.send_report(
                report, self.settings.email_recipients, html_content, json_path
            )

            webhook = self.settings.wechat_bot_webhook
            if webhook:
                self.notifier.send_wechat_bot(report, webhook)

        elif report.important_items > 0:
            # 中优先级：仅发送邮件
            logger.info("   📧 发送邮件报告")
            sent = self.notifier.send_report(
                report, self.settings.email_recipients, html_content, json_path
            )

        else:
            # 无重要情报：发送简要邮件
            logger.info("   📧 发送简要邮件（本期无重大动态）")
            sent = self.notifier.send_report(
                report, self.settings.email_recipients, html_content, json_path
            )

        return sent

    def _empty_result(self, failed_channels: list[str]) -> dict:
        """生成空结果（所有采集失败时）"""
        logger.warning("本期无有效数据，检查以下渠道: " + ", ".join(failed_channels))
        self.db.update_job(
            self.job_id,
            status="failed",
            channels_failed=failed_channels,
            error_message="所有渠道采集失败",
        )
        return {
            "status": "empty",
            "job_id": self.job_id,
            "failed_channels": failed_channels,
            "message": "所有渠道采集均失败或无数据",
        }


# ============================================
# 模拟数据（用于测试）
# ============================================

def generate_mock_data() -> list[RawItem]:
    """
    生成模拟采集数据（基于需求文档的案例）。
    用于在无真实爬虫/API时测试完整流水线。
    """
    now = datetime.now()

    return [
        # === 案例2: 竞品新品发布（高优先级）===
        RawItem(
            source_channel="wechat",
            source_name="美的净水",
            title="美的智净3.0系列发布｜3000G超大流量，引领企业饮水新时代",
            url="https://mp.weixin.qq.com/s/mock_midea_new",
            content=(
                "美的净水正式发布智净3.0系列商用直饮机，核心参数："
                "3000G超大流量，比上一代提升50%，支持500人以上大型企业使用。"
                "采用RO反渗透技术，出水为纯净水，不含矿物质。"
                "定价区间8000-12000元，主攻大型企业市场。"
                "产品支持物联网远程管理，可接入美的智慧楼宇系统。"
            ),
            publish_date=now - timedelta(days=10),
            raw_metadata={"reads": "10万+", "account": "美的净水"},
        ),

        # === 案例3: 行业政策变化（高优先级）===
        RawItem(
            source_channel="news",
            source_name="今日头条",
            title="《饮用净水水质标准》2026版发布，新增纳滤出水矿物质含量要求",
            url="https://www.toutiao.com/mock_policy",
            content=(
                "国家市场监管总局近日发布《饮用净水水质标准》2026版，"
                "新标准首次对纳滤净水器出水提出矿物质含量量化要求："
                "钙镁离子含量≥20mg/L。该标准将于2026年9月1日起正式实施。"
                "这是中国首次在饮用水国标层面明确'保留矿物质'的指标要求。"
                "RO反渗透产品因定位为纯净水，暂不受此标准约束。"
                "业内专家表示，这将利好纳滤技术路线，加速行业洗牌。"
            ),
            publish_date=now - timedelta(days=8),
            raw_metadata={"source": "国家市场监管总局", "reads": "5万+"},
        ),

        # === 行业动态（中优先级）===
        RawItem(
            source_channel="news",
            source_name="新浪财经",
            title="2026上半年中国净水器市场报告：纳滤品类增长42%",
            url="https://finance.sina.com.cn/mock_report",
            content=(
                "奥维云网（AVC）发布2026上半年净水器市场报告："
                "纳滤净水器市场份额从去年15%增至21%，增速42%，远超RO品类5%增速。"
                "消费者对'保留矿物质'认知度显著提升，中高端市场偏好纳滤。"
                "商用净水器市场规模达到180亿元，同比增长28%。"
            ),
            publish_date=now - timedelta(days=5),
            raw_metadata={"source": "奥维云网"},
        ),

        # === 竞品动态: 沁园家用纳滤新品 ===
        RawItem(
            source_channel="website",
            source_name="沁园",
            title="沁园发布2026年家用纳滤净水器新品QY-NF800",
            url="https://www.qinyuan.com.cn/news/mock_new",
            content=(
                "沁园正式发布家用纳滤净水器QY-NF800，采用纳滤膜技术，"
                "针对家庭厨房场景，出水流量800G。产品尚未进入商用市场。"
                "618期间该产品促销力度较大，价格比原价低30%。"
            ),
            publish_date=now - timedelta(days=7),
            raw_metadata={"site_url": "https://www.qinyuan.com.cn/news/"},
        ),

        # === 竞品动态: 安吉尔融资 ===
        RawItem(
            source_channel="news",
            source_name="腾讯新闻",
            title="安吉尔获知名投资机构C轮融资5亿元，宣布进军海外市场",
            url="https://news.qq.com/mock_angel",
            content=(
                "安吉尔净水器完成C轮融资5亿元，投资方包括红杉资本等知名机构。"
                "安吉尔CEO表示，将利用本轮融资加速海外市场拓展，"
                "重点布局东南亚和中东市场。同时加大纳滤技术研发投入。"
            ),
            publish_date=now - timedelta(days=12),
            raw_metadata={"source": "腾讯新闻"},
        ),

        # === 无关内容（应被过滤）===
        RawItem(
            source_channel="news",
            source_name="今日头条",
            title="美的集团发布2026年智能冰箱新品，搭载AI食材管理",
            url="https://www.toutiao.com/mock_irrelevant",
            content="美的冰箱发布2026年新品，搭载AI视觉识别技术...",
            publish_date=now - timedelta(days=3),
            raw_metadata={"source": "今日头条"},
        ),

        # === 重复内容（应被去重）===
        RawItem(
            source_channel="news",
            source_name="新浪财经",
            title="美的智净3.0系列发布 3000G超大流量引领企业饮水新趋势",
            url="https://finance.sina.com.cn/mock_dup",
            content="美的智净3.0系列发布，3000G超大流量，引领企业饮水新时代...",
            publish_date=now - timedelta(days=10),
            raw_metadata={"source": "新浪财经转载"},
        ),

        # === 行业动态: 华为直饮水招标 ===
        RawItem(
            source_channel="news",
            source_name="腾讯新闻",
            title="华为2026年办公区直饮水系统招标启动，优先考虑纳滤技术方案",
            url="https://news.qq.com/mock_huawei",
            content=(
                "华为发布2026年度办公区直饮水系统招标公告，覆盖深圳、东莞等5个城市。"
                "招标文件中明确'优先考虑纳滤技术方案，要求出水保留天然矿物质'。"
                "这是大型科技企业首次在招标中明确倾向纳滤技术。"
            ),
            publish_date=now - timedelta(days=4),
            raw_metadata={"source": "招标信息"},
        ),

        # === 低优先级: 一般行业新闻 ===
        RawItem(
            source_channel="news",
            source_name="今日头条",
            title="某地自来水管道改造工程完成，惠及10万居民",
            url="https://www.toutiao.com/mock_low",
            content="该市自来水管道改造工程历时2年...",
            publish_date=now - timedelta(days=2),
            raw_metadata={"source": "地方新闻"},
        ),

        # === 招聘信息（应被过滤）===
        RawItem(
            source_channel="website",
            source_name="美的净水",
            title="美的净水诚聘研发工程师，薪资20-35K",
            url="https://water.midea.com/jobs/mock",
            content="岗位职责：负责净水器滤芯研发...五险一金，年终奖金...",
            publish_date=now - timedelta(days=6),
            raw_metadata={"site_url": "https://water.midea.com/"},
        ),
    ]


# ============================================
# 定时调度
# ============================================

def run_scheduled():
    """启动定时调度（每两周一次，周一 09:00）"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    settings = get_settings()
    schedule_config = settings.schedule_config

    scheduler = BlockingScheduler()

    # 构建 cron 表达式
    time_str = schedule_config.get("time", "09:00")
    hour, minute = time_str.split(":")
    day_of_week = schedule_config.get("day_of_week", "monday")
    day_map = {
        "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
    }
    dow = day_map.get(day_of_week.lower(), "mon")

    cron_trigger = CronTrigger(
        day_of_week=dow,
        hour=int(hour),
        minute=int(minute),
    )

    scheduler.add_job(
        run_once,
        trigger=cron_trigger,
        id="biweekly_intelligence",
        name="竞品与行业动态情报采集",
        replace_existing=True,
    )

    logger.info(f"⏰ 定时任务已配置: 每两周 {dow} {time_str}")
    logger.info(f"   下次执行: {cron_trigger.get_next_fire_time(None, datetime.now())}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("定时调度已停止")


def run_once(job_id: str = None):
    """执行一次情报采集流水线"""
    setup_logging()

    # 校验配置
    settings = get_settings()
    errors = settings.validate()
    if errors:
        for e in errors:
            logger.warning(f"配置警告: {e}")
        # 仅警告，不阻止运行（LLM API Key 可能用于仅爬取+规则分析）

    pipeline = IntelligencePipeline(mock_mode=False, job_id_override=job_id)
    result = pipeline.run()

    # 清理
    pipeline.db.close()

    return result


def cleanup_jobs(older_than_days: int = 7):
    """清理异常任务记录（超时/失败的任务）"""
    setup_logging()
    settings = get_settings()
    db = IntelligenceDB(settings.db_path)

    # 先标记超时任务
    timed_out = db.mark_stale_jobs_as_timeout(timeout_minutes=10)
    logger.info(f"标记超时任务: {timed_out} 个")

    # 清理旧任务
    stats = db.cleanup_jobs(older_than_days=older_than_days)
    logger.info(f"清理结果: failed={stats['failed']}, timeout={stats['timeout']}, raw_data={stats['raw_intelligence']}")

    db.close()
    logger.info("✅ 任务清理完成")


# ============================================
# CLI 入口
# ============================================

def main():
    parser = argparse.ArgumentParser(
        description="竞品与行业动态情报AI员工",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python -m src.main --once              # 执行一次情报采集
  python -m src.main --once --mock       # 使用模拟数据测试完整流程
  python -m src.main --schedule          # 启动定时调度（每两周）
  python -m src.main --validate          # 验证配置
  python -m src.main --cleanup-jobs      # 清理超时/失败的旧任务
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="执行一次情报采集")
    group.add_argument("--schedule", action="store_true", help="启动定时调度")
    group.add_argument("--validate", action="store_true", help="验证配置文件")
    group.add_argument("--mock", action="store_true", help="使用模拟数据运行")
    group.add_argument("--cleanup-jobs", action="store_true", help="清理超时和失败的旧任务记录")

    parser.add_argument("--config", type=str, help="指定配置文件路径")

    args = parser.parse_args()

    # 验证配置
    if args.validate:
        setup_logging()
        settings = get_settings(args.config)
        errors = settings.validate()
        if errors:
            for e in errors:
                logger.error(f"配置验证失败: {e}")
        else:
            logger.info(f"配置验证通过")
            logger.info(f"   监控范围: {len(settings.competitor_wechat)}公众号, "
                  f"{len(settings.competitor_websites)}网站, "
                  f"{len(settings.industry_keywords)}关键词")
            logger.info(f"   AI模型: {settings.ai_settings['model']}")
            logger.info(f"   数据目录: {settings.data_dir}")
            logger.info(f"   通知收件人: {len(settings.email_recipients)}人")
            logger.info(f"   LLM可用: {'是' if settings.anthropic_api_key else '否（将使用规则兜底）'}")
        return

    # 模拟模式
    if args.mock:
        setup_logging()
        logger.info("🎭 启动模拟模式 — 使用内置Mock数据测试流水线")
        settings = get_settings(args.config)
        pipeline = IntelligencePipeline(mock_mode=True)
        result = pipeline.run()
        pipeline.db.close()

        # 打印报告摘要（使用 logger 避免 GBK 编码问题）
        if result.get("status") == "success":
            logger.info("=" * 60)
            logger.info("[模拟运行报告摘要]")
            logger.info("=" * 60)
            logger.info(f"  采集总数: {result['total_collected']}")
            logger.info(f"  深度分析: {result['deep_analyzed']}")
            logger.info(f"  报告路径: {result['report_path']}")
            logger.info(f"  HTML路径: {result['html_path']}")
            logger.info(f"  耗时: {result['duration_seconds']}秒")
            logger.info("报告文件:")
            logger.info(f"  JSON: {result['report_path']}")
            logger.info(f"  HTML: {result['html_path']}")

        return

    # 单次执行
    if args.once:
        result = run_once()
        return result

    # 清理异常任务
    if args.cleanup_jobs:
        cleanup_jobs()
        return

    # 定时调度
    if args.schedule:
        setup_logging()
        run_scheduled()


if __name__ == "__main__":
    main()
