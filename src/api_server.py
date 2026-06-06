"""API 服务器 - 为前端提供 REST API 接口"""
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.config.settings import get_settings

app = FastAPI(title="竞品与行业动态情报系统 API", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

settings = get_settings()
data_dir = Path(settings.reports_dir)
config_dir = Path(__file__).resolve().parent.parent / "config"

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

@app.post("/api/execute")
async def execute_collection(background_tasks: BackgroundTasks):
    def run_pipeline():
        try:
            from src.main import IntelligencePipeline
            pipeline = IntelligencePipeline(mock_mode=False)
            pipeline.run()
        except Exception as e:
            print(f"Pipeline error: {e}")

    background_tasks.add_task(run_pipeline)
    return {"status": "started", "message": "Collection started"}

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
    # Read existing config
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

@app.get("/api/settings")
async def get_settings_endpoint():
    return {"execution_schedule": "每两周周一 09:00", "email_enabled": True, "email_address": "", "wechat_enabled": False, "alert_level": "medium"}

@app.post("/api/settings")
async def update_settings(settings_data: Dict[str, Any]):
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api_server:app", host="0.0.0.0", port=8000, reload=True)
