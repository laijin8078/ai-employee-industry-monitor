"""报告生成模块"""
from .json_reporter import JSONReporter
from .html_reporter import HTMLReporter

__all__ = ["JSONReporter", "HTMLReporter"]
