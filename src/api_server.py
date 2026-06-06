"""API 服务器 - 为前端提供 REST API 接口"""
import json
import queue
import threading
import uuid
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from loguru import logger

from src.config.settings import get_settings

app = FastAPI(title="竞品与行业动态情报系统 API", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

settings = get_settings()
data_dir = Path(settings.reports_dir)
config_dir = Path(__file__).resolve().parent.parent / "config"


# ============ 采集日志管理 ============

class JobLogManager:
    """管理采集任务的实时日志"""

    def __init__(self):
        self._queues: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()
        self._cancelled: set = set()  # 被取消的 job_id 集合

    def create_job(self, job_id: str):
        with self._lock:
            self._queues[job_id] = queue.Queue()

    def emit(self, job_id: str, level: str, message: str, step: str = "", source: str = "", status: str = ""):
        """发送一条日志事件"""
        with self._lock:
            q = self._queues.get(job_id)
        if q:
            q.put({
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "message": message,
                "step": step,
                "source": source,
                "status": status,
            })

    def get_queue(self, job_id: str):
        with self._lock:
            return self._queues.get(job_id)

    def remove_job(self, job_id: str):
        with self._lock:
            self._queues.pop(job_id, None)
            self._cancelled.discard(job_id)

    def cancel_job(self, job_id: str):
        """标记任务为已取消"""
        with self._lock:
            self._cancelled.add(job_id)
        self.emit(job_id, "warning", "⚠️ 用户请求中断采集...", step="取消", status="cancelling")

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled


job_log_manager = JobLogManager()


# ============ 日志拦截 ============

class PipelineLogSink:
    """将 loguru 日志转发到 JobLogManager"""

    def __init__(self, job_id: str, manager: JobLogManager):
        self.job_id = job_id
        self.manager = manager
        self._handler_id = None

    def start(self):
        def sink(message):
            record = message.record
            self.manager.emit(
                self.job_id,
                level=record["level"].name,
                message=record["message"],
                step="采集流水线",
            )
        self._handler_id = logger.add(sink, level="INFO", format="{message}")

    def stop(self):
        if self._handler_id is not None:
            logger.remove(self._handler_id)
            self._handler_id = None


# ============ 数据转换 ============

def transform_report(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    items = []
    item_id = 0
    for category, items_list in raw_data.get("intelligence_by_category", {}).items():
        for item in items_list:
            items.append({
                "id": f"item_{item_id}",
                "title": item.get("title", ""),
                "category": item.get("event_type", category),
                "summary": item.get("ai_summary", ""),
                "impact": item.get("impact_analysis", ""),
                "strategy": "\n".join([f"[{s.get('dimension','')}] {s.get('action','')}" for s in item.get("our_response", [])]),
                "priority": item.get("priority", "低"),
                "source": item.get("source", "")
            })
            item_id += 1

    return {
        "id": raw_data.get("report_date", ""),
        "date": raw_data.get("report_date", ""),
        "summary": raw_data.get("summary", ""),
        "items": items,
        "competitor_summary": raw_data.get("competitor_summary", {}),
        "recommendations": raw_data.get("recommendation", "")
    }


# ============ API 端点 ============

@app.get("/")
async def root():
    return {"status": "ok", "message": "API Server is running"}


@app.get("/api/reports")
async def get_reports():
    data_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for file in sorted(data_dir.glob("intelligence_report_*.json"), reverse=True):
        with open(file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            total = sum(len(v) for v in data.get("intelligence_by_category", {}).values())
            reports.append({"id": file.stem, "date": data.get("report_date", ""), "total_count": total, "status": "completed"})
    return reports


@app.get("/api/reports/latest")
async def get_latest_report():
    files = sorted(data_dir.glob("intelligence_report_*.json"), reverse=True)
    if not files:
        return {"date": datetime.now().strftime("%Y-%m-%d"), "summary": "暂无报告数据", "totalCount": 0, "category_counts": {}}

    with open(files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)
        transformed = transform_report(data)

        category_counts = {}
        for item in transformed.get("items", []):
            cat = item.get("category", "未分类")
            category_counts[cat] = category_counts.get(cat, 0) + 1

        return {
            "id": transformed["id"],
            "date": transformed["date"],
            "summary": transformed["summary"][:300],
            "totalCount": len(transformed.get("items", [])),
            "category_counts": category_counts
        }


@app.get("/api/reports/{report_id}")
async def get_report_detail(report_id: str):
    report_file = data_dir / f"{report_id}.json"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    with open(report_file, 'r', encoding='utf-8') as f:
        return transform_report(json.load(f))


@app.delete("/api/reports/{report_id}")
async def delete_report(report_id: str):
    report_file = data_dir / f"{report_id}.json"
    if report_file.exists():
        report_file.unlink()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Report not found")


@app.get("/api/reports/{report_id}/download")
async def download_report(report_id: str):
    report_file = data_dir / f"{report_id}.json"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(report_file, filename=f"{report_id}.json")


# ============ 采集执行（带日志流） ============

def _get_db():
    """获取数据库连接（用于 API 查询）"""
    from src.storage.database import IntelligenceDB
    return IntelligenceDB(settings.db_path)


@app.post("/api/execute")
async def execute_collection(background_tasks: BackgroundTasks):
    """启动采集任务。若已有 running 任务则返回现有任务，防止重复启动。"""
    # 1. 标记超时任务
    db = _get_db()
    db.mark_stale_jobs_as_timeout(timeout_minutes=10)

    # 2. 检查是否已有活跃任务
    active_jobs = db.get_active_jobs()
    db.close()

    if active_jobs:
        existing = active_jobs[0]
        logger.info(f"已有运行中任务 {existing['job_id']}，拒绝重复启动")
        # 确保日志队列存在（可能因服务重启丢失）
        if not job_log_manager.get_queue(existing["job_id"]):
            job_log_manager.create_job(existing["job_id"])
        return {
            "status": "already_running",
            "job_id": existing["job_id"],
            "message": f"已有运行中的采集任务（{existing['execution_time']} 启动），请等待完成"
        }

    # 3. 创建新任务
    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    job_log_manager.create_job(job_id)

    def run_pipeline():
        log_sink = PipelineLogSink(job_id, job_log_manager)
        log_sink.start()
        try:
            job_log_manager.emit(job_id, "info", "🚀 情报采集系统启动中...", step="初始化", status="running")
            job_log_manager.emit(job_id, "info", f"任务ID: {job_id}", step="初始化", status="running")

            # 读取配置获取监控范围
            config_file = config_dir / "monitor_config.json"
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                scope = cfg.get("monitor_scope", {})
                wechat_list = scope.get("competitor_wechat", [])
                website_list = scope.get("competitor_websites", [])
                keywords = scope.get("industry_keywords", [])

                job_log_manager.emit(job_id, "info",
                    f"监控范围: {len(wechat_list)}个公众号 + {len(website_list)}个网站 + {len(keywords)}个关键词",
                    step="初始化", status="running")

                for w in wechat_list:
                    name = w if isinstance(w, str) else w.get("name", str(w))
                    job_log_manager.emit(job_id, "info", f"  📱 公众号: {name}", step="初始化", source=name, status="pending")
                for ws in website_list:
                    name = ws.get("name", "") if isinstance(ws, dict) else str(ws)
                    url = ws.get("url", "") if isinstance(ws, dict) else ""
                    job_log_manager.emit(job_id, "info", f"  🌐 网站: {name} ({url})", step="初始化", source=name, status="pending")

            from src.main import IntelligencePipeline

            job_log_manager.emit(job_id, "info", "📡 开始并行采集（3个渠道）...", step="采集", status="running")

            pipeline = IntelligencePipeline(
                mock_mode=False,
                job_id_override=job_id,
                log_callback=lambda level, msg, step="", source="", status="": job_log_manager.emit(
                    job_id, level, msg, step=step, source=source, status=status
                ),
                cancel_check=lambda: job_log_manager.is_cancelled(job_id),
            )
            result = pipeline.run()

            # 汇总结果
            final_status = result.get("status", "failed")
            if final_status == "success":
                job_log_manager.emit(job_id, "success",
                    f"🎉 采集完成！共{result.get('total_collected',0)}条 → 清洗{result.get('cleaned',0)}条 → 深度分析{result.get('deep_analyzed',0)}条",
                    step="完成", status="success")
            elif final_status == "partial":
                failed_list = result.get('channels_failed', [])
                succeeded_list = result.get('channels_succeeded', [])
                job_log_manager.emit(job_id, "warning",
                    f"⚠️ 部分采集完成！成功渠道: {', '.join(succeeded_list)}；失败渠道: {', '.join(failed_list)}",
                    step="完成", status="partial")
            elif final_status == "empty":
                job_log_manager.emit(job_id, "warning",
                    f"⚠ 所有渠道采集均为空！失败渠道: {', '.join(result.get('failed_channels', []))}",
                    step="完成", status="failed")
            else:
                job_log_manager.emit(job_id, "error",
                    f"❌ 采集失败: {result.get('error', '未知错误')}",
                    step="完成", status="failed")

            job_log_manager.emit(job_id, "info",
                f"⏱ 总耗时: {result.get('duration_seconds',0)}秒",
                step="完成", status=final_status)

        except Exception as e:
            job_log_manager.emit(job_id, "error", f"❌ 流水线异常: {str(e)}", step="错误", status="failed")
            logger.exception(f"Pipeline error: {e}")
        finally:
            log_sink.stop()
            threading.Timer(30.0, job_log_manager.remove_job, args=[job_id]).start()

    background_tasks.add_task(run_pipeline)
    return {"status": "started", "job_id": job_id, "message": "Collection started"}


@app.get("/api/execute/{job_id}/stream")
async def stream_logs(job_id: str, request: Request):
    """SSE 端点：实时推送采集日志"""
    q = job_log_manager.get_queue(job_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found or already cleaned up")

    async def event_generator():
        try:
            while True:
                # 检查客户端是否断开
                if await request.is_disconnected():
                    break

                try:
                    # 非阻塞地从队列获取日志
                    entry = await asyncio.to_thread(q.get, timeout=1.0)
                    data = json.dumps(entry, ensure_ascii=False)
                    yield f"data: {data}\n\n"

                    # 如果收到完成信号，结束流
                    if entry.get("status") in ("success", "partial", "failed", "timeout") and entry.get("step") == "完成":
                        # 再等几秒看是否有后续日志
                        await asyncio.sleep(2)
                        # 排空剩余消息
                        while True:
                            try:
                                extra = q.get_nowait()
                                edata = json.dumps(extra, ensure_ascii=False)
                                yield f"data: {edata}\n\n"
                            except queue.Empty:
                                break
                        break

                except queue.Empty:
                    # 超时，发送心跳
                    yield f": heartbeat\n\n"

        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============ 取消采集 ============

@app.post("/api/execute/{job_id}/cancel")
async def cancel_job(job_id: str):
    """取消正在运行的采集任务 — 立即更新 DB + 内存标记"""
    job_log_manager.cancel_job(job_id)
    # 立即更新数据库状态，防止前端在取消后短暂窗口内检测到 running 而重连
    try:
        db = _get_db()
        db.update_job(job_id, status="failed", error_message="用户手动中断")
        db.close()
    except Exception as e:
        logger.warning(f"取消时更新DB失败（任务可能尚未入库）: {e}")
    return {"status": "cancelling", "job_id": job_id, "message": "Cancel signal sent"}


# ============ 任务历史 ============

def _serialize_job(j: dict) -> dict:
    """将数据库行转为 API 响应格式"""
    succeeded = json.loads(j.get("channels_succeeded", "[]")) if isinstance(j.get("channels_succeeded"), str) else j.get("channels_succeeded", [])
    failed = json.loads(j.get("channels_failed", "[]")) if isinstance(j.get("channels_failed"), str) else j.get("channels_failed", [])
    return {
        "job_id": j.get("job_id"),
        "execution_time": j.get("execution_time", ""),
        "status": j.get("status", ""),
        "channels_succeeded": succeeded,
        "channels_failed": failed,
        "total_items_collected": j.get("total_items_collected", 0),
        "important_items_found": j.get("important_items_found", 0),
        "report_generated": bool(j.get("report_generated", 0)),
        "error_message": j.get("error_message", ""),
        "duration_seconds": j.get("duration_seconds", 0),
        "current_stage": j.get("current_stage", ""),
        "last_heartbeat": j.get("last_heartbeat", ""),
    }


@app.get("/api/jobs")
async def get_jobs():
    """获取历史采集任务列表（自动标记超时任务）。支持 ?active_only=true 仅返回活跃任务。"""
    try:
        from src.storage.database import IntelligenceDB
        db = IntelligenceDB(settings.db_path)
        # 先标记超时任务
        db.mark_stale_jobs_as_timeout(timeout_minutes=10)

        active_only = False  # 由 query param 控制，这里简化处理
        if active_only:
            jobs = db.get_active_jobs()
        else:
            jobs = db.get_recent_jobs(limit=50)
        db.close()

        return [_serialize_job(j) for j in jobs]
    except Exception as e:
        logger.error(f"Failed to fetch jobs: {e}")
        return []


@app.get("/api/jobs/active")
async def get_active_job():
    """获取当前活跃（运行中）任务"""
    try:
        from src.storage.database import IntelligenceDB
        db = IntelligenceDB(settings.db_path)
        db.mark_stale_jobs_as_timeout(timeout_minutes=10)
        active = db.get_active_jobs()
        db.close()
        if active:
            return {"has_active": True, "job": _serialize_job(active[0])}
        return {"has_active": False, "job": None}
    except Exception as e:
        logger.error(f"Failed to fetch active job: {e}")
        return {"has_active": False, "job": None, "error": str(e)}
    """获取历史采集任务列表（自动标记超时任务）"""
    try:
        db = _get_db()
        # 先标记超时任务
        db.mark_stale_jobs_as_timeout(timeout_minutes=10)
        jobs = db.get_recent_jobs(limit=50)
        db.close()

        return [_serialize_job(j) for j in jobs]
    except Exception as e:
        logger.error(f"Failed to fetch jobs: {e}")
        return []


# ============ 配置相关 ============

@app.get("/api/config")
async def get_config():
    config_file = config_dir / "monitor_config.json"
    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        scope = config.get("monitor_scope", {})
    else:
        scope = {}

    return {
        "competitor_wechat": [{"id": str(i), "name": n, "status": "正常"} for i, n in enumerate(scope.get("competitor_wechat", []))],
        "competitor_websites": [{"id": str(i), "name": w.get("name",""), "url": w.get("url",""), "status": "正常"} for i, w in enumerate(scope.get("competitor_websites", []))],
        "industry_keywords": scope.get("industry_keywords", []),
        "news_sources": scope.get("news_sources", [])
    }


@app.post("/api/config")
async def update_config(config: Dict[str, Any]):
    config_file = config_dir / "monitor_config.json"
    existing = {}
    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            existing = json.load(f)

    existing["monitor_scope"] = {
        "competitor_wechat": [w["name"] if isinstance(w, dict) else w for w in config.get("competitor_wechat", [])],
        "competitor_websites": config.get("competitor_websites", []),
        "industry_keywords": config.get("industry_keywords", []),
        "news_sources": config.get("news_sources", [])
    }

    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return {"status": "success"}


# ============ 系统设置（持久化） ============

DEFAULT_SETTINGS = {
    "execution_schedule": "每两周周一 09:00",
    "email_enabled": True,
    "email_address": "",
    "wechat_enabled": False,
    "wechat_webhook": "",
    "alert_level": "medium",
}

_settings_file = config_dir / "app_settings.json"


def _load_settings() -> dict:
    """从文件加载设置，文件不存在时返回默认值"""
    if _settings_file.exists():
        try:
            with open(_settings_file, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            # 合并默认值（兼容新增字段）
            merged = {**DEFAULT_SETTINGS, **saved}
            return merged
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def _save_settings(data: dict):
    """持久化设置到文件"""
    _settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(_settings_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.get("/api/settings")
async def get_settings_endpoint():
    return _load_settings()


@app.post("/api/settings")
async def update_settings(settings_data: Dict[str, Any]):
    current = _load_settings()
    current.update(settings_data)
    _save_settings(current)
    return {"status": "success"}


@app.post("/api/settings/reset")
async def reset_settings():
    _save_settings(dict(DEFAULT_SETTINGS))
    return {"status": "success", "settings": dict(DEFAULT_SETTINGS)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api_server:app", host="0.0.0.0", port=8000, reload=True)
