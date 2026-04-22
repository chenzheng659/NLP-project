"""
api.py - FastAPI 入口
暴露 /generate 端点，接收请求并调用工作流引擎。
"""
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
"1"
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
"1"
from drone_visualizer import DroneVisualizer, PathProcessor

from src.retriever import get_retriever
from src.workflow  import run_workflow

class GenerateRequest(BaseModel):
    instruction: str = Field(..., description="自然语言需求或编辑指令")
    source_code: Optional[str] = Field(None)

class GenerateResponse(BaseModel):
    mode:           str            
    retrieved_code: Optional[str]  
    before_code:    str            
    after_code:     str            
    diff:           str            
    changed:        bool           
    patch_note:     str            
    merge_method:   str            

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("预热检索模型...")
    get_retriever()
    print("服务就绪，等待请求。")
    yield
    print("服务关闭。")

app = FastAPI(lifespan=lifespan)
app = FastAPI(title="混合代码生成助手API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
"1"
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "drone_visualizer" / "static"), name="static")
drone_visualizer = DroneVisualizer()
path_processor = PathProcessor()

@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    try:
        result = await run_workflow(req.instruction, req.source_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return GenerateResponse(
        mode=result["mode"],
        retrieved_code=result["retrieved_code"],
        before_code=result["before_code"],
        after_code=result["after_code"],
        diff=result["diff"],
        changed=result["changed"],
        patch_note=result["patch_note"],
        merge_method=result["merge_method"],
    )

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/visualizer", response_class=HTMLResponse)
async def get_visualizer_page(request: Request, mission_id: Optional[str] = None):
    """获取无人机可视化主页面"""
    try:
        # 从session或数据库获取路径数据，这里使用示例数据
        sample_path = [
            {"x": 0, "y": 0, "z": 10, "yaw": 0, "action": "takeoff"},
            {"x": 20, "y": 5, "z": 15, "yaw": 45, "action": "move"},
            {"x": 40, "y": -10, "z": 20, "yaw": 90, "action": "inspect"},
            {"x": 60, "y": 0, "z": 10, "yaw": 180, "action": "move"},
            {"x": 60, "y": 0, "z": 0, "yaw": 180, "action": "land"},
        ]
        
        path_data = {
            "mission_name": "无人机自主巡查任务" if not mission_id else f"任务-{mission_id}",
            "path": sample_path,
            "total_distance": path_processor.calculate_path_length(sample_path),
            "estimated_time": 45,
            "waypoints": path_processor.generate_waypoints(sample_path, 50)
        }
        
        return drone_visualizer.render_visualization_page(path_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"可视化页面生成失败: {str(e)}")

@app.post("/api/generate_and_visualize")
async def generate_and_visualize(request: GenerateRequest):
    """生成代码并返回可视化数据（一步完成）"""
    try:
        # 1. 调用原有的工作流生成代码
        result = await workflow_engine.run_workflow(request.instruction, request.source_code)
        
        # 2. 生成可视化数据
        path_data = drone_visualizer.generate_path_data(
            request.instruction, 
            result.get("final_code", "")
        )
        
        # 3. 合并结果
        return {
            "status": "success",
            "message": "代码生成与可视化数据准备完成",
            "code_generation": result,
            "visualization": {
                "path_data": path_data,
                "visualizer_url": f"/visualizer?mission_id={hash(request.instruction)}",
                "has_visualization": True
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成与可视化失败: {str(e)}")

@app.get("/api/visualization_data")
async def get_visualization_data(mission_id: str):
    """获取特定任务的路径数据（API接口）"""
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
