"""
HTML 报告生成器
===============
使用 Jinja2 模板将 IntelligenceReport 渲染为 HTML 邮件报告。
"""

import json
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger

from ..models.schemas import IntelligenceReport


class HTMLReporter:
    """HTML 邮件报告生成器"""

    def __init__(self, templates_dir: Path):
        """
        Args:
            templates_dir: Jinja2 模板目录
        """
        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render(self, report: IntelligenceReport) -> str:
        """
        使用 Jinja2 模板渲染 HTML 报告。

        Args:
            report: 情报报告

        Returns:
            完整的 HTML 字符串
        """
        # 为模板准备数据（将 Pydantic 模型转为易访问的字典结构）
        template_data = self._prepare_template_data(report)

        template = self.env.get_template("report.html")
        html = template.render(report=template_data)
        logger.info(f"HTML 报告已渲染 ({len(html)} 字符)")
        return html

    def save(self, report: IntelligenceReport, output_dir: Path) -> Optional[str]:
        """
        保存 HTML 报告到文件。

        Args:
            report: 情报报告
            output_dir: 输出目录

        Returns:
            保存的文件路径，失败返回 None
        """
        try:
            html = self.render(report)
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = f"intelligence_report_{report.report_date}.html"
            filepath = output_dir / filename
            filepath.write_text(html, encoding="utf-8")
            logger.info(f"HTML 报告已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"HTML 报告保存失败: {e}")
            return None

    def render_pdf(self, report: IntelligenceReport) -> Optional[bytes]:
        """
        将报告渲染为 PDF（需要 pdfkit + wkhtmltopdf）。

        Args:
            report: 情报报告

        Returns:
            PDF 二进制数据，失败返回 None
        """
        try:
            import pdfkit
            html = self.render(report)
            pdf = pdfkit.from_string(html, False)
            logger.info(f"PDF 报告已生成 ({len(pdf)} 字节)")
            return pdf
        except ImportError:
            logger.warning("pdfkit 未安装，无法生成 PDF")
            return None
        except Exception as e:
            logger.error(f"PDF 生成失败: {e}")
            return None

    def _prepare_template_data(self, report: IntelligenceReport) -> dict:
        """
        准备模板数据，将 Pydantic 模型序列化为模板友好的格式。

        保留了 model_dump 以获取纯字典，同时确保 Jinja2 可以
        通过属性访问（如 report.report_date）和字典访问（如 report['report_date']）。
        """
        # 序列化以处理 date/datetime 等类型
        data = json.loads(
            report.model_dump_json()
        )

        # 确保 intelligence_by_category 中的条目可以被模板轻松遍历
        # 添加一些模板需要的计算属性
        for category, items in data.get("intelligence_by_category", {}).items():
            for item in items:
                # 从 screening 中提取 direct 字段（模板友好）
                screening = item.get("screening", {})
                if screening.get("item", {}).get("raw", {}):
                    raw = screening["item"]["raw"]
                    item["_source_name"] = raw.get("source_name", "")
                    item["_publish_date"] = raw.get("publish_date", "")
                    item["_url"] = raw.get("url", "")

        return data
