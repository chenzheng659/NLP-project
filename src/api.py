"""
api.py - FastAPI 入口
暴露 /generate 端点，接收请求并调用工作流引擎。
"""
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
"1"
import traceback
from fastapi.responses import Response
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
from pathlib import Path
from typing import Optional
import json

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.drone import DroneVisualizer, PathProcessor
    _drone_available = True
except Exception as _drone_import_err:
    _drone_available = False
    DroneVisualizer = None
    PathProcessor = None
    print(f"[警告] 无人机可视化模块加载失败，相关端点将返回 503。原因：{_drone_import_err}")

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
    # 无人机可视化相关（仅当检索到无人机类别代码时填充）
    is_drone_related:   bool = False
    visualization_url:  Optional[str] = None
    mission_id:         Optional[str] = None

# 内存缓存：存储每次请求生成的路径数据，key = mission_id
_path_data_cache: dict = {}

# 无人机相关类别标签集合
_DRONE_CATEGORIES = {"mission", "control", "tuning", "planning"}

# 用于指令文本关键词检测的无人机相关词列表（小写，模糊匹配，用于检索降级时仍能触发可视化）
_DRONE_KEYWORDS = [
    "无人机", "飞行", "路径规划", "避障", "躲避障碍", "起飞", "降落", "悬停",
    "飞控", "航线", "巡视", "巡检", "导航", "drone", "uav", "waypoint",
    "obstacle", "avoidance", "autopilot",
]


def _is_drone_instruction(instruction: str) -> bool:
    """基于关键词判断指令是否与无人机相关，用于检索降级时仍能触发可视化。

    采用大小写不敏感的子串匹配（启发式兜底），可能存在误报，
    建议仅在 retrieved_item 为空时作为降级检测手段使用。
    """
    text = instruction.lower()
    return any(kw in text for kw in _DRONE_KEYWORDS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("预热检索模型...")
    get_retriever()
    print("服务就绪，等待请求。")
    yield
    print("服务关闭。")

app = FastAPI(title="混合代码生成助手API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
if _drone_available:
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "drone" / "static"), name="static")
    drone_visualizer = DroneVisualizer()
    path_processor = PathProcessor()
else:
    drone_visualizer = None
    path_processor = None

@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    try:
        result = await run_workflow(req.instruction, req.source_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 判断是否为无人机相关代码
    retrieved_item = result.get("retrieved_item")
    category = (retrieved_item.get("category", "") if retrieved_item else "").lower()
    is_drone_related = (category in _DRONE_CATEGORIES) or _is_drone_instruction(req.instruction)

    visualization_url = None
    mission_id = None

    if is_drone_related and _drone_available and drone_visualizer:
        import hashlib
        mission_id = hashlib.md5(
            f"{req.instruction}{result.get('after_code', '')}".encode()
        ).hexdigest()[:12]

        # 获取 LLM 直接解析出的航点（如果有）
        pre_waypoints = result.get("waypoints")

        # 生成路径数据（优先使用预提取航点）
        path_data = drone_visualizer.generate_path_data(
            instruction=req.instruction,
            generated_code=result.get("after_code", ""),
            retrieved_item=retrieved_item,
            pre_extracted_waypoints=pre_waypoints,
        )
        path_data["mission_name"] = path_data.get("mission_name") or req.instruction[:50]

        # 如果没有预提取航点，则进行插值以生成平滑路径供前端动画
        if not pre_waypoints:
            # 注意：generate_path_data 返回的 path 是原始稀疏点，需要插值
            path_data["waypoints"] = path_processor.generate_waypoints(path_data["path"], 80)
        else:
            # 已有预提取航点，直接用（不再插值）
            path_data["waypoints"] = pre_waypoints

        _path_data_cache[mission_id] = path_data
        visualization_url = f"/visualizer?mission_id={mission_id}"

    return GenerateResponse(
        mode=result["mode"],
        retrieved_code=result["retrieved_code"],
        before_code=result["before_code"],
        after_code=result["after_code"],
        diff=result["diff"],
        changed=result["changed"],
        patch_note=result["patch_note"],
        merge_method=result["merge_method"],
        is_drone_related=is_drone_related,
        visualization_url=visualization_url,
        mission_id=mission_id,
    )

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/visualizer", response_class=HTMLResponse)
async def get_visualizer_page(request: Request, mission_id: Optional[str] = None):
    """获取无人机可视化主页面"""
    if not _drone_available:
        raise HTTPException(status_code=503, detail="无人机可视化模块不可用")
    try:
        # 优先使用缓存的路径数据（来自 /generate 接口的结果）
        if mission_id and mission_id in _path_data_cache:
            path_data = _path_data_cache[mission_id]
        else:
            # 回退到示例数据
            sample_path = [
                {"x": 0,  "y": 0,   "z": 10, "yaw": 0,   "action": "takeoff"},
                {"x": 20, "y": 5,   "z": 15, "yaw": 45,  "action": "move"},
                {"x": 40, "y": -10, "z": 20, "yaw": 90,  "action": "inspect"},
                {"x": 60, "y": 0,   "z": 10, "yaw": 180, "action": "move"},
                {"x": 60, "y": 0,   "z": 0,  "yaw": 180, "action": "land"},
            ]
            path_data = {
                "mission_name": "无人机自主巡查任务" if not mission_id else f"任务-{mission_id}",
                "path": sample_path,
                "total_distance": path_processor.calculate_path_length(sample_path),
                "estimated_time": 45,
                "waypoints": path_processor.generate_waypoints(sample_path, 50),
            }

        return drone_visualizer.render_visualization_page(path_data, request)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"可视化页面生成失败: {str(e)}")

@app.post("/api/generate_and_visualize")
async def generate_and_visualize(request: GenerateRequest):
    """生成代码并返回可视化数据（一步完成）"""
    if not _drone_available:
        raise HTTPException(status_code=503, detail="无人机可视化模块不可用")
    try:
        # 1. 调用原有的工作流生成代码
        result = await run_workflow(request.instruction, request.source_code)

        # 2. 生成可视化数据（利用检索条目元数据）
        retrieved_item = result.get("retrieved_item")
        path_data = drone_visualizer.generate_path_data(
            request.instruction,
            result.get("after_code", ""),
            retrieved_item=retrieved_item,
        )

        # 3. 合并结果
        return {
            "status": "success",
            "message": "代码生成与可视化数据准备完成",
            "code_generation": result,
            "visualization": {
                "path_data": path_data,
                "visualizer_url": f"/visualizer?mission_id={abs(hash(request.instruction))}",
                "has_visualization": True
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成与可视化失败: {str(e)}")

@app.head("/visualizer")
async def head_visualizer():
    # 仅返回响应头，不返回HTML内容
    return Response(status_code=200)

@app.get("/api/visualization_data")
async def get_visualization_data(mission_id: str):
    """获取特定任务的路径数据（API接口）"""
    if not _drone_available:
        raise HTTPException(status_code=503, detail="无人机可视化模块不可用")
    # 这里应该从数据库或缓存中获取真实数据
    # 现在返回示例数据
    sample_path = [
        {"x": 0, "y": 0, "z": 10, "yaw": 0, "action": "takeoff"},
        {"x": 20, "y": 5, "z": 15, "yaw": 45, "action": "move"},
        {"x": 40, "y": -10, "z": 20, "yaw": 90, "action": "inspect"},
        {"x": 60, "y": 0, "z": 10, "yaw": 180, "action": "move"},
        {"x": 60, "y": 0, "z": 0, "yaw": 180, "action": "land"},
    ]
    
    return {
        "mission_id": mission_id,
        "path": sample_path,
        "waypoints": path_processor.generate_waypoints(sample_path),
        "statistics": {
            "total_distance": path_processor.calculate_path_length(sample_path),
            "waypoint_count": len(sample_path),
            "max_altitude": max(p["z"] for p in sample_path)
        }
    }
