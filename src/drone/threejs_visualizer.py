# src/drone/threejs_visualizer.py
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from src.config import DRONE_VISUALIZER_CONFIG

_DRONE_DIR = Path(__file__).parent

class DroneVisualizer:
    """无人机路径3D可视化器"""
    
    def __init__(self):
        templates_dir = _DRONE_DIR / "templates"
        print(f"模板目录: {templates_dir.absolute()}")
        if not templates_dir.exists():
            raise FileNotFoundError(f"模板目录不存在: {templates_dir}")
        self.templates = Jinja2Templates(directory=str(templates_dir))
        self.static_dir = _DRONE_DIR / "static"
        
    def generate_path_data(self, instruction: str, generated_code: str,
                           retrieved_item: dict = None) -> dict:
        """
        根据检索到的代码条目或生成的代码推断可视化路径数据。

        优先使用 retrieved_item 的 category 字段生成语义化路径；
        若无元数据则回退到通用演示路径。
        """
        category = ""
        func_name = ""
        if retrieved_item:
            category = retrieved_item.get("category", "").lower()
            func_name = retrieved_item.get("function_name", "")

        # 根据代码分类生成不同的演示飞行路径
        if category in ("mission",):
            path = [
                {"x": 0,   "y": 0,   "z": 5,  "yaw": 0,   "action": "takeoff"},
                {"x": 20,  "y": 0,   "z": 20, "yaw": 0,   "action": "climb"},
                {"x": 40,  "y": 10,  "z": 20, "yaw": 30,  "action": "navigate"},
                {"x": 60,  "y": 20,  "z": 25, "yaw": 45,  "action": "inspect"},
                {"x": 80,  "y": 10,  "z": 20, "yaw": 60,  "action": "navigate"},
                {"x": 100, "y": 0,   "z": 20, "yaw": 90,  "action": "patrol"},
                {"x": 100, "y": -20, "z": 15, "yaw": 180, "action": "return"},
                {"x": 50,  "y": -10, "z": 10, "yaw": 270, "action": "return"},
                {"x": 0,   "y": 0,   "z": 5,  "yaw": 0,   "action": "land"},
            ]
            mission_name = f"任务规划演示 — {func_name}" if func_name else "无人机任务规划演示"
        elif category in ("control", "tuning"):
            path = [
                {"x": 0,  "y": 0,  "z": 0,  "yaw": 0, "action": "takeoff"},
                {"x": 0,  "y": 0,  "z": 15, "yaw": 0, "action": "hover"},
                {"x": 5,  "y": 0,  "z": 16, "yaw": 0, "action": "correct"},
                {"x": -3, "y": 0,  "z": 15, "yaw": 0, "action": "correct"},
                {"x": 2,  "y": 0,  "z": 15, "yaw": 0, "action": "correct"},
                {"x": 0,  "y": 0,  "z": 15, "yaw": 0, "action": "stable"},
                {"x": 0,  "y": 0,  "z": 0,  "yaw": 0, "action": "land"},
            ]
            mission_name = f"控制器演示 — {func_name}" if func_name else "无人机控制演示"
        elif category in ("planning",):
            path = [
                {"x": 0,   "y": 0,   "z": 10, "yaw": 0,   "action": "start"},
                {"x": 15,  "y": 5,   "z": 12, "yaw": 20,  "action": "plan"},
                {"x": 30,  "y": -5,  "z": 15, "yaw": 45,  "action": "avoid"},
                {"x": 45,  "y": 0,   "z": 15, "yaw": 0,   "action": "plan"},
                {"x": 60,  "y": 10,  "z": 12, "yaw": -20, "action": "plan"},
                {"x": 80,  "y": 0,   "z": 10, "yaw": 0,   "action": "goal"},
            ]
            mission_name = f"路径规划演示 — {func_name}" if func_name else "无人机路径规划演示"
        else:
            path = [
                {"x": 0,  "y": 0,  "z": 10, "yaw": 0,   "action": "takeoff"},
                {"x": 20, "y": 5,  "z": 15, "yaw": 45,  "action": "move"},
                {"x": 40, "y": -10,"z": 20, "yaw": 90,  "action": "inspect"},
                {"x": 60, "y": 0,  "z": 10, "yaw": 180, "action": "move"},
                {"x": 60, "y": 0,  "z": 0,  "yaw": 180, "action": "land"},
            ]
            mission_name = instruction[:50] + ("..." if len(instruction) > 50 else "")

        from .path_processor import PathProcessor
        pp = PathProcessor()
        return {
            "mission_name": mission_name,
            "function_name": func_name,
            "category": category,
            "path": path,
            "total_distance": pp.calculate_path_length(path),
            "estimated_time": len(path) * 8,
            "code_snippet": generated_code[:200] + "..." if len(generated_code) > 200 else generated_code,
        }
    
    def render_visualization_page(self, path_data: Dict, request: Request = None) -> HTMLResponse:
        """渲染包含Three.js可视化的HTML页面"""
        template_data = {
            "mission_name": path_data.get("mission_name", ""),
            "path_data": path_data,
            "threejs_version": DRONE_VISUALIZER_CONFIG["threejs_version"],
            "path_color": DRONE_VISUALIZER_CONFIG["path_color"],
            "grid_size": DRONE_VISUALIZER_CONFIG["grid_size"],
            "camera_position": DRONE_VISUALIZER_CONFIG["camera_position"],
            "animation_speed": DRONE_VISUALIZER_CONFIG["animation_speed"],
        }
        
        return self.templates.TemplateResponse(
            request=request,
            name="visualizer.html",
            context={"data": template_data}
        )
    
    def get_static_path(self, filename: str) -> str:
        """获取静态文件路径"""
        return str(self.static_dir / filename)