# src/drone/threejs_visualizer.py
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from src.config import DRONE_VISUALIZER_CONFIG
from .path_processor import PathProcessor

_DRONE_DIR = Path(__file__).parent

class DroneVisualizer:
    """无人机路径3D可视化器"""

    def __init__(self):
        templates_dir = _DRONE_DIR / "templates"
        self.templates = Jinja2Templates(directory=str(templates_dir))
        self.path_processor = PathProcessor()

    def generate_path_data(self, instruction: str, generated_code: str,
                           retrieved_item: Optional[dict] = None) -> Dict[str, Any]:
        """
        Parses real code, ensures coordinate alignment for the frontend,
        and falls back to samples if needed.
        """
        # Step 1: Parse real code using the now-fixed parser
        path = self.path_processor.parse_tello_code(generated_code)
        mission_name = instruction[:50]

        if not path:
            logging.warning("Code parsing failed. Falling back to sample data.")
            path = self._get_fallback_path()
            mission_name = f"回退样本 - {mission_name}"

        # Step 2: Ensure all required calculations are done
        total_distance = self.path_processor.calculate_path_length(path)
        estimated_time = total_distance / 1.5  # Rough estimation

        # Step 3: Return a clean data dictionary. The frontend will handle waypoints.
        return {
            "mission_name": mission_name,
            "path": path,
            "total_distance": round(total_distance, 2),
            "estimated_time": round(estimated_time, 2),
        }

    def _get_fallback_path(self) -> List[Dict]:
        """Provides a geometrically correct fallback path in meters."""
        return [
            {"x": 0, "y": 0, "z": 1, "yaw": 0, "action": "takeoff"},
            {"x": 5, "y": 0, "z": 1, "yaw": 0, "action": "move"},
            {"x": 5, "y": 5, "z": 1, "yaw": 90, "action": "move"},
            {"x": 5, "y": 5, "z": 0, "yaw": 90, "action": "land"},
        ]

    def render_visualization_page(self, path_data: Dict, request: Request) -> HTMLResponse:
        """Renders the HTML page, passing data to the Jinja2 template."""

        # The frontend's JS expects waypoints, so we generate them here.
        # The coordinate mapping (p.z as vertical) is handled in the JS itself.
        path_data["waypoints"] = self.path_processor.generate_waypoints(path_data["path"])

        # Dynamic camera and grid scaling logic remains the same
        max_dim = 10.0
        if path_data.get("path") and len(path_data["path"]) > 1:
            max_x = max(abs(p["x"]) for p in path_data["path"])
            max_y = max(abs(p["y"]) for p in path_data["path"])
            max_z = max(abs(p["z"]) for p in path_data["path"])
            max_dim = max(max_x, max_y, max_z, 5.0)

        config = DRONE_VISUALIZER_CONFIG.copy()
        config["camera_position"] = {"x": max_dim * 2.0, "y": max_dim * 1.5, "z": max_dim * 2.0}
        config["grid_size"] = int(max_dim * 3)

        template_context = {
            "path_data": path_data,
            **config
        }

        return self.templates.TemplateResponse(
            request=request, name="visualizer.html", context={"data": template_context}
        )
