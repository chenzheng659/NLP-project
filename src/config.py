"""
config.py - 全局配置管理
所有可调参数集中在此，方便统一修改
"""

import os
from pathlib import Path

# ── 路径 ──────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent / "data"
DATASET_PATH = str(BASE_DIR / "code.json")
PROMPT_TEMPLATE_PATH = str(BASE_DIR / "prompt_templates.txt")

# ── LLM API ───────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-ffe8e439a464450b9843a4faaa377594")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-coder"
LLM_TEMPERATURE = 0.2  # 低温保证代码稳定性
LLM_TIMEOUT = 60.0  # 请求超时秒数

# ── 检索参数 ──────────────────────────────────────
EMBED_MODEL_NAME = "BAAI/bge-base-zh-v1.5"
RERANK_MODEL_NAME = "BAAI/bge-reranker-base"
RECALL_K = 5  # 第一阶段向量召回数量
RERANK_THRESHOLD = 0.8  # 重排分数阈值，低于此值降级为纯生成

DRONE_VISUALIZER_CONFIG = {
    "enable_visualization": True,
    "threejs_version": "r158",  # Three.js版本
    "default_drone_model": "static/models/drone.glb",
    "path_color": 0x00ff00,  # 路径线颜色（绿色）
    "grid_size": 100,  # 3D网格大小
    "camera_position": {"x": 50, "y": 50, "z": 50},
    "animation_speed": 1.0,  # 动画速度倍数
}

API_PREFIX = "/api"
VISUALIZER_PREFIX = "/visualizer"