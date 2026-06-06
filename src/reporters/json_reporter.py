"""
JSON 报告生成器
===============
将 AI 分析结果组织为结构化的情报报告（JSON格式），
格式与需求文档中的期望输出完全对齐。
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

from ..models.schemas import (
    DeepAnalysis,
    CompetitorSummary,
    IntelligenceReport,
    ScreeningResult,
)


class JSONReporter:
    """JSON 格式报告生成器"""

    def __init__(self, reports_dir: Path, company_context: dict):
        """
        Args:
            reports_dir: 报告输出目录
            company_context: 公司背景信息
        """
        self.reports_dir = reports_dir
        self.company_context = company_context
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._source_health = {}  # 最近一次的来源健康度数据

    def generate(
        self,
        analyses: list[DeepAnalysis],
        all_screening_results: list[ScreeningResult],
        report_date: Optional[date] = None,
        notification_recipients: list[str] = None,
        source_health: dict = None,
    ) -> IntelligenceReport:
        """
        生成完整的情报报告。

        Args:
            analyses: 深度分析结果（重要情报）
            all_screening_results: 所有初筛结果（含低优先级和无关）
            report_date: 报告日期，默认今天
            notification_recipients: 通知接收人
            source_health: 各渠道来源健康度 {"channel": {"status", "strategy", "count", "error"}}

        Returns:
            IntelligenceReport 实例
        """
        if report_date is None:
            report_date = date.today()

        # 计算报告区间（过去14天）
        period_end = report_date
        period_start = report_date - timedelta(days=14)
        report_period = f"{period_start} 至 {period_end}（两周）"

        # 统计
        total_items = len(all_screening_results)
        important_screening = [r for r in all_screening_results if r.is_important]
        important_items = len(important_screening)

        # 按类别分组
        by_category = self._group_by_category(analyses)

        # 生成摘要
        high_priority = [a for a in analyses if a.screening.priority == "高"]
        summary = self._generate_summary(high_priority, analyses)

        # 竞品汇总
        competitor_summaries = self._build_competitor_summaries(analyses)

        # 综合建议
        recommendation = self._generate_recommendation(analyses, high_priority)

        # 下次监控日期
        next_date = report_date + timedelta(days=14)
        # 对齐到最近的周一
        while next_date.weekday() != 0:
            next_date += timedelta(days=1)

        # 通知列表
        if notification_recipients is None:
            notification_recipients = []

        # 保存来源健康度
        self._source_health = source_health or {}

        report = IntelligenceReport(
            report_date=report_date,
            report_period=report_period,
            total_items=total_items,
            important_items=important_items,
            summary=summary,
            intelligence_by_category=by_category,
            competitor_summary=competitor_summaries,
            recommendation=recommendation,
            next_monitoring_date=next_date,
            notification_sent_to=notification_recipients,
        )

        logger.info(
            f"JSON 报告生成: {total_items}条采集 → "
            f"{important_items}条重要 → "
            f"{sum(len(v) for v in by_category.values())}条深度分析"
        )

        return report

    def save(self, report: IntelligenceReport) -> str:
        """
        保存报告为 JSON 文件。

        Returns:
            保存的文件路径
        """
        filename = f"intelligence_report_{report.report_date}.json"
        filepath = self.reports_dir / filename

        # 转换为可序列化的字典
        report_dict = self._report_to_dict(report)

        filepath.write_text(
            json.dumps(report_dict, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info(f"报告已保存: {filepath}")
        return str(filepath)

    def _group_by_category(self, analyses: list[DeepAnalysis]) -> dict[str, list[DeepAnalysis]]:
        """按类别分组，组内按优先级排序"""
        priority_order = {"高": 0, "中": 1, "低": 2}

        grouped: dict[str, list[DeepAnalysis]] = {
            "竞品动态": [],
            "行业政策": [],
            "行业动态": [],
            "技术突破": [],
        }

        for analysis in analyses:
            cat = analysis.screening.category
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(analysis)

        # 组内排序
        for cat in grouped:
            grouped[cat].sort(
                key=lambda a: (
                    priority_order.get(a.screening.priority, 3),
                    -a.urgency_score,
                )
            )

        # 移除空分类
        return {k: v for k, v in grouped.items() if v}

    def _generate_summary(
        self,
        high_priority: list[DeepAnalysis],
        all_analyses: list[DeepAnalysis],
    ) -> str:
        """生成本期摘要"""
        parts = []

        if high_priority:
            parts.append(f"本期发现{len(high_priority)}条高优先级情报：")
            for a in high_priority[:3]:
                parts.append(f"「{a.title[:40]}」（{a.screening.category}）")
        else:
            # 找最重要的几条
            top = sorted(all_analyses, key=lambda a: a.urgency_score, reverse=True)[:2]
            if top:
                parts.append(f"本期无高优情报，最值得关注的是：")
                for a in top:
                    parts.append(f"「{a.title[:40]}」")
            else:
                parts.append("本期未发现重要的行业情报，市场较为平静。")

        return "；".join(parts) if len(parts) > 1 else parts[0]

    def _build_competitor_summaries(
        self, analyses: list[DeepAnalysis]
    ) -> list[CompetitorSummary]:
        """构建竞品动态汇总"""
        by_comp: dict[str, list[DeepAnalysis]] = {}
        competitor_names = self.company_context.get("main_competitors", [])

        for analysis in analyses:
            # 找出涉及的竞品
            entities = analysis.screening.key_entities
            comp = analysis.competitor
            for name in competitor_names:
                if name in entities or name in analysis.title:
                    comp = name
                    break

            if comp not in by_comp:
                by_comp[comp] = []
            by_comp[comp].append(analysis)

        summaries = []
        for comp_name in competitor_names:
            items = by_comp.get(comp_name, [])
            if items:
                high_count = sum(1 for a in items if a.screening.priority == "高")
                title_previews = [a.title[:40] for a in items[:3]]
                summary_text = "；".join(title_previews)
                if high_count > 0:
                    summary_text = f"⚠ 本期{len(items)}条动态（{high_count}条高优）。" + summary_text
                else:
                    summary_text = f"本期{len(items)}条动态。" + summary_text
            else:
                summary_text = "本期无重大动态"

            summaries.append(CompetitorSummary(
                name=comp_name,
                period_summary=summary_text,
                high_priority_count=sum(1 for a in items if a.screening.priority == "高"),
                total_items=len(items),
            ))

        return summaries

    def _generate_recommendation(
        self,
        analyses: list[DeepAnalysis],
        high_priority: list[DeepAnalysis],
    ) -> str:
        """生成综合建议"""
        if not analyses:
            return "本期未发现需要行动的情报。建议维持现有策略。"

        # 提取所有高紧急度的应对建议
        urgent = [a for a in analyses if a.urgency_score >= 7]
        if urgent:
            actions = []
            for a in urgent[:3]:
                resp_dims = set(r.dimension for r in a.our_response[:2])
                actions.append(f"针对「{a.title[:30]}」，需关注{'/'.join(resp_dims)}")
            return "建议本周内采取行动：" + "；".join(actions)

        if high_priority:
            return (
                f"建议关注{len(high_priority)}条高优情报，"
                "可将相关分析转发给产品和市场部门参考。"
            )

        return "建议持续关注行业动态，暂无紧急事项需要处理。"

    def _report_to_dict(self, report: IntelligenceReport) -> dict:
        """将报告转为可序列化字典（与需求文档输出格式对齐）"""
        def serialize_analysis(a: DeepAnalysis) -> dict:
            return {
                "priority": a.screening.priority,
                "competitor": a.competitor if a.screening.category == "竞品动态" else None,
                "event_type": a.screening.category,
                "policy_name": a.title if a.screening.category == "行业政策" else None,
                "title": a.title,
                "publish_date": str(a.publish_date) if a.publish_date else None,
                "source": a.source,
                "ai_summary": a.ai_summary,
                "impact_analysis": a.impact_analysis,
                "impact_type": a.impact_type,
                "our_response": [
                    {"dimension": r.dimension, "action": r.action}
                    for r in a.our_response
                ],
                "urgency_score": a.urgency_score,
                "related_pudow_products": a.related_pudow_products,
                "related_links": a.related_links,
                "attachments": a.attachments,
            }

        return {
            "report_date": str(report.report_date),
            "report_period": report.report_period,
            "total_items": report.total_items,
            "important_items": report.important_items,
            "summary": report.summary,
            "intelligence_by_category": {
                cat: [serialize_analysis(a) for a in items]
                for cat, items in report.intelligence_by_category.items()
            },
            "competitor_summary": {
                c.name: c.period_summary
                for c in report.competitor_summary
            },
            "recommendation": report.recommendation,
            "next_monitoring_date": str(report.next_monitoring_date),
            "notification_sent_to": report.notification_sent_to,
            "source_health": self._source_health,
        }
