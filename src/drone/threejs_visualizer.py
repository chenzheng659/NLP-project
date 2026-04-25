import json
import re
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from src.config import DRONE_VISUALIZER_CONFIG

_DRONE_DIR = Path(__file__).parent

class DroneVisualizer:
    """无人机路径 3D 可视化器"""

    def __init__(self):
        templates_dir = _DRONE_DIR / "templates"
        print(f"模板目录: {templates_dir.absolute()}")
        if not templates_dir.exists():
            raise FileNotFoundError(f"模板目录不存在: {templates_dir}")
        self.templates = Jinja2Templates(directory=str(templates_dir))
        self.static_dir = _DRONE_DIR / "static"

    # ── 从生成代码中提取路径数据 ──────────────────────
    def _extract_path_from_code(self, llm_raw: str) -> Optional[List[dict]]:
        """
        尝试从生成的代码文本中提取飞行路径点列表。
        策略顺序：
          1. 查找约定的 # PATH_START ... # PATH_END 注释块
          2. 解析常见的移动指令（如 move_to）
        返回 None 表示提取失败。
        """
        if not llm_raw:
            return None

        # 策略 1：注释块中直接嵌入路径 JSON
        path = self._extract_from_comment_block(llm_raw)
        if path:
            return path

        # 策略 2：解析移动指令
        return self._extract_from_move_commands(llm_raw)

    def _extract_from_comment_block(self, code: str) -> Optional[List[dict]]:
        """
        从代码中提取 # PATH_START ... # PATH_END 块中的 JSON 数组。
        使用字符串查找方法，彻底避免正则表达式的跨行匹配问题。
        """
        # 查找开始标记（可能带 # 或不带）
        start_marker = "# PATH_START"
        start_idx = code.find(start_marker)
        if start_idx == -1:
            start_marker = "PATH_START"
            start_idx = code.find(start_marker)
        if start_idx == -1:
            return None

        # 查找结束标记
        end_marker = "# PATH_END"
        end_idx = code.find(end_marker, start_idx + len(start_marker))
        if end_idx == -1:
            end_marker = "PATH_END"
            end_idx = code.find(end_marker, start_idx + len(start_marker))
        if end_idx == -1:
            return None

        # 提取 JSON 字符串
        json_str = code[start_idx + len(start_marker):end_idx].strip()

        # 去除每行开头的 '#' 注释符（模型可能在每行前加 #）
        json_str = re.sub(r'^\s*#\s*', '', json_str, flags=re.MULTILINE)

        # 尝试解析 JSON
        try:
            waypoints = json.loads(json_str)
            if isinstance(waypoints, list):
                print(f"[DroneVisualizer] 成功提取 {len(waypoints)} 个航点")
                return waypoints
        except json.JSONDecodeError as e:
            print(f"[DroneVisualizer] JSON 解析失败: {e}")
            print(f"提取的 JSON 字符串前 200 字符: {json_str[:200]}")
        return None

    def _extract_from_move_commands(self, code: str) -> Optional[List[dict]]:
        """
        匹配形如 drone.move_to(x, y, z, yaw=...) 的指令，并自动补全
        takeoff / land 点。
        """
        moves = []
        pattern = r'\.move_to\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*(?:,\s*yaw\s*=\s*([-\d.]+)\s*)?\)'
        for m in re.finditer(pattern, code):
            x, y, z, yaw = m.groups()
            moves.append({
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "yaw": float(yaw) if yaw else 0,
                "action": "navigate"
            })

        if not moves:
            return None

        if 'takeoff' in code.lower():
            moves.insert(0, {"x": 0, "y": 0, "z": 5, "yaw": 0, "action": "takeoff"})

        if 'land' in code.lower() and moves:
            last = moves[-1]
            moves.append({"x": last['x'], "y": last['y'], "z": 0, "yaw": last['yaw'],
                           "action": "land"})

        return moves

    # ── 生成路径数据（优先使用外部传入的航点）────────────────
    def generate_path_data(self, instruction: str, generated_code: str,
                           retrieved_item: dict = None,
                           pre_extracted_waypoints: Optional[List[Dict]] = None) -> dict:
        """
        根据生成的代码或检索到的元数据生成可视化路径数据。
        优先使用 pre_extracted_waypoints（由 LLM 直接解析出的航点列表）；
        否则尝试从 generated_code 中动态提取飞行路径；
        提取失败时回退到基于 category 的预设路径。
        """
        from .path_processor import PathProcessor
        pp = PathProcessor()

        # ---------- 优先使用外部传入的航点 ----------
        if pre_extracted_waypoints and isinstance(pre_extracted_waypoints, list) and len(pre_extracted_waypoints) > 0:
            path = pre_extracted_waypoints
            category = ""
            func_name = ""
            if retrieved_item:
                category = retrieved_item.get("category", "").lower()
                func_name = retrieved_item.get("function_name", "")
            mission_name = instruction[:50] + ("..." if len(instruction) > 50 else "")
            return {
                "mission_name": mission_name,
                "function_name": func_name,
                "category": category,
                "path": path,
                "waypoints": path,
                "total_distance": pp.calculate_path_length(path),
                "estimated_time": len(path) * 5,
                "code_snippet": generated_code[:200] + "..." if generated_code else "",
            }

        # ---------- 尝试从代码中提取真实路径 ----------
        dynamic_path = self._extract_path_from_code(generated_code) if generated_code else None

        if dynamic_path:
            path = dynamic_path
            category = ""
            func_name = ""
            if retrieved_item:
                category = retrieved_item.get("category", "").lower()
                func_name = retrieved_item.get("function_name", "")
            mission_name = instruction[:50] + ("..." if len(instruction) > 50 else "")
        else:
            # ---------- 提取失败，回退到预设路径 ----------
            category = ""
            func_name = ""
            if retrieved_item:
                category = retrieved_item.get("category", "").lower()
                func_name = retrieved_item.get("function_name", "")

            if category in ("mission",):
                path = [
                    {"x": 0, "y": 0, "z": 5, "yaw": 0, "action": "takeoff"},
                    {"x": 20, "y": 0, "z": 20, "yaw": 0, "action": "climb"},
                    {"x": 40, "y": 10, "z": 20, "yaw": 30, "action": "navigate"},
                    {"x": 60, "y": 20, "z": 25, "yaw": 45, "action": "inspect"},
                    {"x": 80, "y": 10, "z": 20, "yaw": 60, "action": "navigate"},
                    {"x": 100, "y": 0, "z": 20, "yaw": 90, "action": "patrol"},
                    {"x": 100, "y": -20, "z": 15, "yaw": 180, "action": "return"},
                    {"x": 50, "y": -10, "z": 10, "yaw": 270, "action": "return"},
                    {"x": 0, "y": 0, "z": 5, "yaw": 0, "action": "land"},
                ]
                mission_name = f"任务规划演示 — {func_name}" if func_name else "无人机任务规划演示"
            elif category in ("control", "tuning"):
                path = [
                    {"x": 0, "y": 0, "z": 0, "yaw": 0, "action": "takeoff"},
                    {"x": 0, "y": 0, "z": 15, "yaw": 0, "action": "hover"},
                    {"x": 5, "y": 0, "z": 16, "yaw": 0, "action": "correct"},
                    {"x": -3, "y": 0, "z": 15, "yaw": 0, "action": "correct"},
                    {"x": 2, "y": 0, "z": 15, "yaw": 0, "action": "correct"},
                    {"x": 0, "y": 0, "z": 15, "yaw": 0, "action": "stable"},
                    {"x": 0, "y": 0, "z": 0, "yaw": 0, "action": "land"},
                ]
                mission_name = f"控制器演示 — {func_name}" if func_name else "无人机控制演示"
            elif category in ("planning",):
                path = [
                    {"x": 0, "y": 0, "z": 10, "yaw": 0, "action": "start"},
                    {"x": 15, "y": 5, "z": 12, "yaw": 20, "action": "plan"},
                    {"x": 30, "y": -5, "z": 15, "yaw": 45, "action": "avoid"},
                    {"x": 45, "y": 0, "z": 15, "yaw": 0, "action": "plan"},
                    {"x": 60, "y": 10, "z": 12, "yaw": -20, "action": "plan"},
                    {"x": 80, "y": 0, "z": 10, "yaw": 0, "action": "goal"},
                ]
                mission_name = f"路径规划演示 — {func_name}" if func_name else "无人机路径规划演示"
            else:
                path = [
                    {"x": 0, "y": 0, "z": 10, "yaw": 0, "action": "takeoff"},
                    {"x": 20, "y": 5, "z": 15, "yaw": 45, "action": "move"},
                    {"x": 40, "y": -10, "z": 20, "yaw": 90, "action": "inspect"},
                    {"x": 60, "y": 0, "z": 10, "yaw": 180, "action": "move"},
                    {"x": 60, "y": 0, "z": 0, "yaw": 180, "action": "land"},
                ]
                mission_name = instruction[:50] + ("..." if len(instruction) > 50 else "")

        return {
            "mission_name": mission_name,
            "function_name": func_name,
            "category": category,
            "path": path,
            "waypoints": path,
            "total_distance": pp.calculate_path_length(path),
            "estimated_time": len(path) * 8 if not dynamic_path else len(path) * 5,
            "code_snippet": generated_code[:200] + "..." if len(generated_code) > 200 else generated_code,
        }

    # ── 渲染可视化页面，传递 waypoints_json ──────────────
    def render_visualization_page(self, path_data: Dict, request: Request = None) -> HTMLResponse:
        """渲染包含 Three.js 可视化的 HTML 页面，将 waypoints 序列化为 JSON 传给前端"""
        waypoints = path_data.get("waypoints", path_data.get("path", []))
        waypoints_json = json.dumps(waypoints) if waypoints else "[]"

        template_data = {
            "mission_name": path_data.get("mission_name", ""),
            "path_data": path_data,
            "waypoints_json": waypoints_json,
            "threejs_version": DRONE_VISUALIZER_CONFIG["threejs_version"],
            "path_color": DRONE_VISUALIZER_CONFIG["path_color"],
            "grid_size": DRONE_VISUALIZER_CONFIG["grid_size"],
            "camera_position": DRONE_VISUALIZER_CONFIG["camera_position"],
            "animation_speed": DRONE_VISUALIZER_CONFIG["animation_speed"],
            "model_url": "/static/buster_drone.glb",
        }
        return self.templates.TemplateResponse(
            request=request,
            name="visualizer.html",
            context={"data": template_data}
        )

    def get_static_path(self, filename: str) -> str:
        """获取静态文件路径"""
        return str(self.static_dir / filename)