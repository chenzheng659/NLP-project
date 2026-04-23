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
        
    def generate_path_data(self, instruction: str, generated_code: str) -> Dict:
        """
        从生成的无人机代码中提取路径数据
        这里模拟从代码中解析路径点，实际应解析真实的无人机指令
        """
        # 模拟路径生成 - 实际应该从生成的代码中解析真实的路径
        # 这只是示例，您需要根据实际的无人机指令格式进行解析
        sample_path = [
            {"x": 0, "y": 0, "z": 10, "yaw": 0, "action": "takeoff"},
            {"x": 20, "y": 5, "z": 15, "yaw": 45, "action": "move"},
            {"x": 40, "y": -10, "z": 20, "yaw": 90, "action": "inspect"},
            {"x": 60, "y": 0, "z": 10, "yaw": 180, "action": "move"},
            {"x": 60, "y": 0, "z": 0, "yaw": 180, "action": "land"},
        ]
        
        return {
            "mission_name": instruction[:50] + "...",
            "path": sample_path,
            "total_distance": 125.6,  # 计算总距离
            "estimated_time": 45,  # 估计时间(秒)
            "code_snippet": generated_code[:200] + "..." if len(generated_code) > 200 else generated_code
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