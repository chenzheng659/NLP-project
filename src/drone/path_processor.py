# src/drone_visualizer/path_processor.py
import math
from typing import List, Dict, Tuple
import numpy as np

class PathProcessor:
    """处理无人机路径数据的工具类"""
    
    @staticmethod
    def calculate_path_length(path: List[Dict]) -> float:
        """计算路径总长度"""
        total = 0.0
        for i in range(len(path) - 1):
            p1 = path[i]
            p2 = path[i + 1]
            distance = math.sqrt(
                (p2["x"] - p1["x"])**2 + 
                (p2["y"] - p1["y"])**2 + 
                (p2["z"] - p1["z"])**2
            )
            total += distance
        return total
    
    @staticmethod
    def smooth_path(path: List[Dict], alpha: float = 0.5) -> List[Dict]:
        """使用简单平滑算法处理路径点"""
        if len(path) <= 2:
            return path
            
        smoothed = []
        for i in range(len(path)):
            if i == 0 or i == len(path) - 1:
                smoothed.append(path[i])
            else:
                smoothed_point = {
                    "x": alpha * path[i]["x"] + (1 - alpha) * 0.5 * (path[i-1]["x"] + path[i+1]["x"]),
                    "y": alpha * path[i]["y"] + (1 - alpha) * 0.5 * (path[i-1]["y"] + path[i+1]["y"]),
                    "z": alpha * path[i]["z"] + (1 - alpha) * 0.5 * (path[i-1]["z"] + path[i+1]["z"]),
                    "yaw": path[i]["yaw"],
                    "action": path[i]["action"]
                }
                smoothed.append(smoothed_point)
        return smoothed
    
    @staticmethod
    def generate_waypoints(path: List[Dict], num_points: int = 100) -> List[Dict]:
        """在路径点之间生成插值点，用于平滑动画"""
        if len(path) < 2:
            return path
            
        waypoints = []
        total_segments = len(path) - 1
        points_per_segment = num_points // total_segments
        
        for i in range(total_segments):
            p1 = path[i]
            p2 = path[i + 1]
            
            for j in range(points_per_segment):
                t = j / points_per_segment
                waypoint = {
                    "x": p1["x"] + t * (p2["x"] - p1["x"]),
                    "y": p1["y"] + t * (p2["y"] - p1["y"]),
                    "z": p1["z"] + t * (p2["z"] - p1["z"]),
                    "yaw": p1["yaw"] + t * (p2["yaw"] - p1["yaw"]),
                    "action": p1["action"] if t < 0.5 else p2["action"]
                }
                waypoints.append(waypoint)
        
        return waypoints