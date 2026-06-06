"""
数据模型定义
============
使用 Pydantic 定义情报系统所有数据模型，
涵盖从原始采集到最终报告的完整链路。
"""

from datetime import datetime, date
from typing import Optional, Any
from pydantic import BaseModel, Field


# ==================== 原始数据 ====================

class RawItem(BaseModel):
    """单条原始采集数据（来自爬虫）"""

    source_channel: str = Field(..., description="采集渠道: wechat / website / news")
    source_name: str = Field(..., description="来源名称，如'美的净水'、'今日头条'")
    title: str = Field(..., description="标题")
    url: str = Field(default="", description="原始链接")
    content: str = Field(default="", description="正文/摘要内容")
    publish_date: Optional[datetime] = Field(default=None, description="发布时间")
    raw_metadata: dict[str, Any] = Field(
        default_factory=dict, description="附加元数据（阅读数、作者等）"
    )


# ==================== 清洗后数据 ====================

class CleanedItem(BaseModel):
    """清洗后的数据条目"""

    raw: RawItem = Field(..., description="原始数据")
    content_hash: str = Field(default="", description="内容去重哈希")
    is_duplicate: bool = Field(default=False, description="是否为重复内容")
    duplicate_of: Optional[str] = Field(default=None, description="如果是重复，指向原始标题")

    @property
    def title(self) -> str:
        return self.raw.title

    @property
    def source_name(self) -> str:
        return self.raw.source_name


# ==================== AI分析结果 ====================

class ResponseAction(BaseModel):
    """应对策略建议"""

    dimension: str = Field(..., description="策略维度: 产品策略/营销策略/销售策略/技术研发/合规动作/公关动作")
    action: str = Field(..., description="具体行动建议")


class ScreeningResult(BaseModel):
    """AI 初筛结果"""

    item: CleanedItem = Field(..., description="被筛选的清洗条目")
    is_relevant: bool = Field(default=True, description="是否与净水器/朴道相关")
    category: str = Field(
        default="其他",
        description="情报分类: 竞品动态/行业政策/行业动态/技术突破/其他",
    )
    priority: str = Field(
        default="低",
        description="优先级: 高/中/低",
    )
    reason: str = Field(default="", description="判断依据")
    key_entities: list[str] = Field(default_factory=list, description="关键实体")

    @property
    def is_important(self) -> bool:
        """是否需要深度分析（相关 且 非低优先级）"""
        return self.is_relevant and self.priority != "低"


class DeepAnalysis(BaseModel):
    """AI 深度分析结果"""

    # 关联初筛结果
    screening: ScreeningResult = Field(..., description="对应的初筛结果")

    # 分析字段
    ai_summary: str = Field(default="", description="AI 提炼的核心内容（150字以内）")
    impact_analysis: str = Field(default="", description="对朴道的影响分析")
    impact_type: str = Field(
        default="中性",
        description="影响类型: 威胁/机会/中性",
    )
    our_response: list[ResponseAction] = Field(
        default_factory=list,
        description="建议的应对策略列表",
    )
    urgency_score: int = Field(
        default=5,
        ge=1,
        le=10,
        description="紧急程度评分 (1-10)",
    )
    related_pudow_products: list[str] = Field(
        default_factory=list,
        description="涉及到的朴道产品线",
    )

    # 附件
    related_links: list[str] = Field(default_factory=list, description="相关链接")
    attachments: list[str] = Field(default_factory=list, description="附件文件名")

    @property
    def competitor(self) -> str:
        """提取涉及的竞品名称"""
        return self.screening.item.raw.source_name

    @property
    def title(self) -> str:
        return self.screening.item.raw.title

    @property
    def publish_date(self) -> Optional[datetime]:
        return self.screening.item.raw.publish_date

    @property
    def source(self) -> str:
        raw = self.screening.item.raw
        return f"{raw.source_name}（{raw.source_channel}）"


class CompetitorSummary(BaseModel):
    """单竞品动态汇总"""

    name: str = Field(..., description="竞品名称")
    period_summary: str = Field(default="", description="本周期动态一句话总结")
    high_priority_count: int = Field(default=0, description="高优先级情报数")
    total_items: int = Field(default=0, description="总提及次数")


# ==================== 最终报告 ====================

class IntelligenceReport(BaseModel):
    """最终情报报告"""

    # 报告元信息
    report_date: date = Field(..., description="报告日期")
    report_period: str = Field(default="", description="报告覆盖时间段")
    total_items: int = Field(default=0, description="采集总条目数")
    important_items: int = Field(default=0, description="重要情报数（高+中优先级）")

    # 摘要
    summary: str = Field(default="", description="本期报告摘要")

    # 分类情报
    intelligence_by_category: dict[str, list[DeepAnalysis]] = Field(
        default_factory=dict,
        description="按类别组织的情报: 竞品动态/行业政策/行业动态/技术突破",
    )

    # 竞品汇总
    competitor_summary: list[CompetitorSummary] = Field(
        default_factory=list,
        description="各竞品本周期动态汇总",
    )

    # 综合建议
    recommendation: str = Field(default="", description="对朴道的综合建议")

    # 后续安排
    next_monitoring_date: date = Field(..., description="下次监控日期")

    # 通知
    notification_sent_to: list[str] = Field(default_factory=list, description="通知发送对象")

    # 附件清单
    generated_files: list[str] = Field(
        default_factory=list,
        description="本期生成的文件（JSON/HTML/PDF路径）",
    )


# ==================== 定时任务记录 ====================

class JobRecord(BaseModel):
    """每次执行的任务记录（用于数据库存储）"""

    job_id: str = Field(..., description="任务唯一ID")
    execution_time: datetime = Field(default_factory=datetime.now, description="执行时间")
    status: str = Field(default="running", description="执行状态: running/success/failed/partial")
    channels_succeeded: list[str] = Field(default_factory=list, description="成功采集的渠道")
    channels_failed: list[str] = Field(default_factory=list, description="失败的渠道")
    total_items_collected: int = Field(default=0, description="采集总数")
    important_items_found: int = Field(default=0, description="发现的重要情报数")
    report_generated: bool = Field(default=False, description="是否生成了报告")
    error_message: str = Field(default="", description="错误信息（如有）")
    duration_seconds: float = Field(default=0.0, description="执行耗时（秒）")


# ==================== 来源健康度 ====================

class SourceHealth(BaseModel):
    """单个采集源的健康状态"""

    name: str = Field(..., description="来源标识，如 website_midea / wechat / toutiao")
    status: str = Field(
        default="ok",
        description="ok / degraded / fallback_used / fallback_failed / needs_manual_refresh / empty",
    )
    strategy: str = Field(default="", description="实际使用的采集策略: requests / playwright / search_engine / cache")
    raw_count: int = Field(default=0, description="原始采集数量")
    error: Optional[str] = Field(default=None, description="错误信息（如有）")


class SourceHealthReport(BaseModel):
    """来源健康度汇总"""

    sources: list[SourceHealth] = Field(default_factory=list)
    summary: str = Field(default="", description="一句话健康度摘要")
