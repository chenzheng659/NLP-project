# src/drone/path_processor.py
import math
import re
from typing import List, Dict

class PathProcessor:
    """
    V8: Bulletproof, State-Machine Parser.
    Processes drone path data and parses DJITelloPy code with high accuracy.
    """

    @staticmethod
    def parse_tello_code(code: str) -> List[Dict]:
        path = []
        # State variables for the drone
        x, y, z, yaw = 0.0, 0.0, 0.0, 0.0
        has_taken_off = False

        # --- Mutually Exclusive Regex Commands ---
        # This prevents accidental partial matches between commands.
        COMMANDS = {
            'takeoff': re.compile(r"tello\s*\.\s*takeoff\s*\(\s*\)"),
            'land': re.compile(r"tello\s*\.\s*land\s*\(\s*\)"),
            'up': re.compile(r"tello\s*\.\s*move_up\s*\(\s*(?:\w+\=)?(\d+)\s*\)"),
            'down': re.compile(r"tello\s*\.\s*move_down\s*\(\s*(?:\w+\=)?(\d+)\s*\)"),
            'left': re.compile(r"tello\s*\.\s*move_left\s*\(\s*(?:\w+\=)?(\d+)\s*\)"),
            'right': re.compile(r"tello\s*\.\s*move_right\s*\(\s*(?:\w+\=)?(\d+)\s*\)"),
            'forward': re.compile(r"tello\s*\.\s*move_forward\s*\(\s*(?:\w+\=)?(\d+)\s*\)"),
            'back': re.compile(r"tello\s*\.\s*move_back\s*\(\s*(?:\w+\=)?(\d+)\s*\)"),
            'rot_cw': re.compile(r"tello\s*\.\s*rotate_clockwise\s*\(\s*(?:\w+\=)?(\d+)\s*\)"),
            'rot_ccw': re.compile(r"tello\s*\.\s*rotate_counter_clockwise\s*\(\s*(?:\w+\=)?(\d+)\s*\)"),
        }

        path.append({"x": x, "y": y, "z": z, "yaw": yaw, "action": "standby"})

        for line in code.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            for action, pattern in COMMANDS.items():
                match = pattern.search(line)
                if not match:
                    continue

                # --- State Update Logic ---
                if action == 'takeoff' and not has_taken_off:
                    z = 1.0  # Takeoff to 1 meter
                    has_taken_off = True
                elif action == 'land' and has_taken_off:
                    z = 0.0
                    has_taken_off = False
                elif has_taken_off:
                    val_cm = int(match.group(1)) if match.groups() else 0
                    val_m = val_cm / 100.0
                    rad_yaw = math.radians(yaw)

                    if action == 'up': z += val_m
                    elif action == 'down': z -= val_m
                    elif action == 'forward':
                        x += val_m * math.cos(rad_yaw)
                        y += val_m * math.sin(rad_yaw)
                    elif action == 'back':
                        x -= val_m * math.cos(rad_yaw)
                        y -= val_m * math.sin(rad_yaw)
                    elif action == 'left':
                        x += val_m * math.cos(rad_yaw + math.pi / 2)
                        y += val_m * math.sin(rad_yaw + math.pi / 2)
                    elif action == 'right':
                        x += val_m * math.cos(rad_yaw - math.pi / 2)
                        y += val_m * math.sin(rad_yaw - math.pi / 2)
                    elif action == 'rot_cw':
                        yaw += val_cm # Rotation is in degrees
                    elif action == 'rot_ccw':
                        yaw -= val_cm

                # Append a new point reflecting the state AFTER the command
                path.append({"x": round(x, 2), "y": round(y, 2), "z": round(z, 2), "yaw": yaw % 360, "action": action})
                break # Move to the next line

        return path if len(path) > 1 else []

    @staticmethod
    def calculate_path_length(path: List[Dict]) -> float:
        total = 0.0
        for i in range(len(path) - 1):
            p1, p2 = path[i], path[i+1]
            total += math.sqrt((p2["x"] - p1["x"])**2 + (p2["y"] - p1["y"])**2 + (p2["z"] - p1["z"])**2)
        return round(total, 2)

    @staticmethod
    def generate_waypoints(path: List[Dict], num_points: int = 200) -> List[Dict]:
        if len(path) < 2: return path
        waypoints = []
        total_segments = len(path) - 1
        points_per_segment = max(1, num_points // total_segments)
        for i in range(total_segments):
            p1, p2 = path[i], path[i+1]
            for j in range(points_per_segment):
                t = j / points_per_segment
                waypoints.append({
                    "x": p1["x"] + t * (p2["x"] - p1["x"]),
                    "y": p1["y"] + t * (p2["y"] - p1["y"]),
                    "z": p1["z"] + t * (p2["z"] - p1["z"]),
                    "yaw": p1["yaw"] + t * (p2["yaw"] - p1["yaw"]),
                    "action": p1["action"]
                })
        waypoints.append(path[-1])
        return waypoints
