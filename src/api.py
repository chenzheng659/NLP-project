"""
api.py - FastAPI 入口
暴露 /generate 端点，接收请求并调用工作流引擎。
"""
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import traceback
import hashlib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.drone.threejs_visualizer import DroneVisualizer
from src.drone.path_processor import PathProcessor
from src.retriever import get_retriever
from src.workflow  import run_workflow

class GenerateRequest(BaseModel):
    instruction: str = Field(..., description="自然语言需求或编辑指令")
    source_code: Optional[str] = Field(None)

class GenerateResponse(BaseModel):
    mode:               str
    retrieved_code:     Optional[str]
    before_code:        str
    after_code:         str
    diff:               str
    changed:            bool
    patch_note:         str
    merge_method:       str
    is_drone_related:   bool = False
    visualization_url:  Optional[str] = None
    mission_id:         Optional[str] = None

_path_data_cache: dict = {}
_DRONE_CATEGORIES = {"mission", "control", "tuning", "planning"}
_DRONE_KEYWORDS = ["无人机", "飞行", "路径", "起飞", "降落", "悬停", "drone", "uav"]

_drone_available = True
try:
    drone_visualizer = DroneVisualizer()
except Exception as e:
    print(f"[ERROR] Failed to initialize DroneVisualizer: {e}")
    _drone_available = False

def _is_drone_instruction(instruction: str) -> bool:
    return any(kw in instruction.lower() for kw in _DRONE_KEYWORDS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    get_retriever()
    yield

app = FastAPI(title="混合代码生成助手API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
if _drone_available:
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "drone" / "static"), name="static")

@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    result = await run_workflow(req.instruction, req.source_code)

    retrieved_item = result.get("retrieved_item")
    category = (retrieved_item.get("category", "") if retrieved_item else "").lower()
    is_drone_related = (category in _DRONE_CATEGORIES) or _is_drone_instruction(req.instruction)

    visualization_url, mission_id = None, None
    if is_drone_related and _drone_available:
        mission_id = hashlib.md5(f"{req.instruction}{result.get('after_code', '')}".encode()).hexdigest()[:12]
        path_data = drone_visualizer.generate_path_data(
            instruction=req.instruction,
            generated_code=result.get("after_code", ""),
            retrieved_item=retrieved_item
        )
        if path_data.get("path"):
             _path_data_cache[mission_id] = path_data
             visualization_url = f"/visualizer?mission_id={mission_id}"

    final_result = {**result, "is_drone_related": is_drone_related, "visualization_url": visualization_url, "mission_id": mission_id}
    return GenerateResponse(**final_result)

@app.get("/visualizer", response_class=HTMLResponse)
async def get_visualizer_page(request: Request, mission_id: Optional[str] = None):
    if not _drone_available:
        raise HTTPException(status_code=503, detail="无人机可视化模块不可用")

    path_data = _path_data_cache.get(mission_id)
    if not path_data:
        path_data = drone_visualizer.generate_path_data(instruction="默认演示任务", generated_code="")

    return drone_visualizer.render_visualization_page(path_data, request)

@app.head("/visualizer")
async def head_visualizer():
    """Handles HEAD requests for the visualizer to prevent 405 errors."""
    return Response(status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok", "drone_module": "available" if _drone_available else "unavailable"}
