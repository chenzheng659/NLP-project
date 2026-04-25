"""
llm_client.py - LLM 调用模块
负责：
  1. 加载提示词模板
  2. 构造 prompt（双模式自动选择模板）
  3. 调用 DeepSeek API
  4. 返回结构化结果（补丁 + 修改前后对比）
"""

import re
import asyncio
import json
import textwrap
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass

import httpx

from . import config


@dataclass
class ParsedResponse:
    original_code: str
    modified_code: str
    explanation: str
    modified: bool
    raw: str
    waypoints: Optional[List[Dict[str, Any]]] = None


# ── 常量定义 ────────────────────────────────────────
DRONE_KEYWORDS: Tuple[str, ...] = (
    "无人机", "drone", "飞行", "航点", "路径规划",
    "任务规划", "起飞", "降落", "航迹", "航线", "uav"
)

NO_CHANGE_KEYWORDS: Tuple[str, ...] = (
    "无修改", "no changes needed", "无需修改", "不需要修改"
)


# ── 提示词加载 ─────────────────────────────────────
def _load_templates() -> Dict[str, str]:
    """解析 prompt_templates.txt，返回 {section_name: content} 字典"""
    templates = {}
    current_key: Optional[str] = None
    current_lines: List[str] = []

    try:
        with open(config.PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.rstrip("\n")
                match = re.match(r"^\[(\w+)\]$", stripped.strip())
                if match:
                    if current_key:
                        templates[current_key] = "\n".join(current_lines).strip()
                    current_key = match.group(1)
                    current_lines = []
                elif current_key is not None:
                    current_lines.append(stripped)

        if current_key:
            templates[current_key] = "\n".join(current_lines).strip()

    except FileNotFoundError:
        raise FileNotFoundError(
            f"提示词模板文件缺失: {config.PROMPT_TEMPLATE_PATH}，请确保该文件存在。"
        )
    except Exception as e:
        raise RuntimeError(f"读取提示词模板文件时发生错误: {e}")

    return templates


_templates: Optional[Dict[str, str]] = None


def get_templates() -> Dict[str, str]:
    global _templates
    if _templates is None:
        _templates = _load_templates()
    return _templates


# ── Prompt 构造 ────────────────────────────────────
def build_prompt(instruction: str, base_code: str, has_source_code: bool) -> str:
    """
    根据是否有源代码选择对应模板并填充变量。
    如果指令涉及无人机飞行，自动追加路径数据输出要求。
    """
    templates = get_templates()

    if not has_source_code:
        template = templates.get("retrieval_mode_zh", "")
        prompt = template.format(base_code=base_code, instruction=instruction)
    else:
        template = templates.get("direct_edit_mode_zh", "")
        prompt = template.format(source_code=base_code, instruction=instruction)

    # ── 如果是无人机指令，追加路径数据输出要求 ──────
    if any(kw in instruction.lower() for kw in DRONE_KEYWORDS):
        drone_path_instruction = textwrap.dedent("""
        额外要求（无人机路径数据）

        请在上面的“修改后”代码块中包含生成航点数据的逻辑，并在代码末尾以注释形式提供飞行路点数据，格式如下：

        PATH_START
        [{"x": 0, "y": 0, "z": 5, "yaw": 0, "action": "takeoff"},
        {"x": 20, "y": 10, "z": 15, "yaw": 30, "action": "navigate"},
        ...]
        PATH_END

        注意事项：
        - 每个路点必须包含 x, y, z, yaw, action 五个字段。
        - 路点顺序应与代码中的飞行指令顺序完全一致。
        - 不要省略任何路点，也不要添加额外的注释或说明。
        - 如果代码中已经生成了航点列表（如返回列表或打印），请将同样的数据用 # PATH_START/# PATH_END 括起来。
        """)
        prompt += drone_path_instruction

    return prompt


# ── API 调用 ───────────────────────────────────────
async def call_llm(prompt: str) -> str:
    """异步调用 DeepSeek API，带重试机制"""
    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": config.LLM_TEMPERATURE,
    }

    max_retries = 2
    delay = 1.0

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
                resp = await client.post(
                    config.DEEPSEEK_API_URL, json=payload, headers=headers
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPError as e:
            if attempt == max_retries:
                raise RuntimeError(f"调用 LLM 失败，已重试 {max_retries} 次: {e}")
            await asyncio.sleep(delay)
        except Exception as e:
            if attempt == max_retries:
                raise RuntimeError(f"调用 LLM 发生未知错误: {e}")
            await asyncio.sleep(delay)
    return ""  # 实际上不会执行到这里


# ── 辅助函数 ───────────────────────────────────────
def _extract_code_block(label: str, raw_text: str) -> Optional[str]:
    """从 LLM 响应中提取指定标签（修改前/后）下的 Python 代码块"""
    pattern = rf"###\s*{label}\s*```(?:python)?\n(.*?)```"
    match = re.search(pattern, raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _has_no_change_indicator(raw_text: str) -> bool:
    """检测响应中是否包含表示无需修改的关键字"""
    return any(kw in raw_text.lower() for kw in NO_CHANGE_KEYWORDS)


def _extract_waypoints_simple(text: str) -> Optional[List[Dict[str, Any]]]:
    """
    从文本中提取 # PATH_START ... # PATH_END 之间的航点列表。
    使用字符串查找，避免正则表达式的跨行匹配问题。
    """
    start_marker = "# PATH_START"
    start_idx = text.find(start_marker)
    if start_idx == -1:
        start_marker = "PATH_START"
        start_idx = text.find(start_marker)
    if start_idx == -1:
        return None

    end_marker = "# PATH_END"
    end_idx = text.find(end_marker, start_idx + len(start_marker))
    if end_idx == -1:
        end_marker = "PATH_END"
        end_idx = text.find(end_marker, start_idx + len(start_marker))
    if end_idx == -1:
        return None

    json_str = text[start_idx + len(start_marker):end_idx].strip()
    # 去除每行开头的 '#' 注释符
    json_str = re.sub(r'^\s*#\s*', '', json_str, flags=re.MULTILINE)

    try:
        waypoints = json.loads(json_str)
        if isinstance(waypoints, list):
            return waypoints
    except Exception as e:
        print(f"[_extract_waypoints_simple] JSON 解析失败: {e}\n部分内容: {json_str[:200]}")
    return None


# ── 响应解析 ───────────────────────────────────────
def parse_llm_response(raw: str, base_code: str) -> ParsedResponse:
    """
    从 LLM 输出中解析出结构化字段。
    处理 <think> 标签干扰、"无需修改"的语义冲突等问题。
    使用简单字符串查找提取航点。
    """
    # 1. 剔除 <think> 标签
    raw_cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # 2. 提取航点（使用简单字符串查找）
    waypoints = _extract_waypoints_simple(raw_cleaned)
    if waypoints is None:
        # 再尝试从原始 raw 中提取（未清理的版本）
        waypoints = _extract_waypoints_simple(raw)

    # 3. 检测"无修改"关键字兜底
    if base_code.strip() and _has_no_change_indicator(raw_cleaned):
        return ParsedResponse(
            original_code=base_code,
            modified_code=base_code,
            explanation="无需修改",
            modified=False,
            raw=raw,
            waypoints=waypoints,
        )

    # 4. 提取修改前后代码块
    before = _extract_code_block("修改前", raw_cleaned) or base_code
    after = _extract_code_block("修改后", raw_cleaned)

    # 提取修改说明
    note_match = re.search(r"###\s*修改说明\s*\n(.+)", raw_cleaned, re.DOTALL)
    patch_note = note_match.group(1).strip() if note_match else ""

    # 5. 兜底：如果格式不对（例如模型只输出了一个代码块），提取最后那个代码块作为 after
    if after is None:
        fallback_blocks = re.findall(r"```(?:python)?\n(.*?)```", raw_cleaned, re.DOTALL)
        if fallback_blocks:
            after = fallback_blocks[-1].strip()
        else:
            after = raw_cleaned.strip()

    # 6. 最终检查：如果 after 为空或与 before 完全相同，则视为无修改
    if not after.strip() or after.strip() == before.strip():
        return ParsedResponse(
            original_code=base_code,
            modified_code=base_code,
            explanation=patch_note or "未检测到有效修改",
            modified=False,
            raw=raw,
            waypoints=waypoints,
        )

    # 7. 比较是否实际发生了修改（与 base_code 比较）
    is_modified = after.strip() != base_code.strip()

    return ParsedResponse(
        original_code=before,
        modified_code=after if is_modified else base_code,
        explanation=patch_note,
        modified=is_modified,
        raw=raw_cleaned,
        waypoints=waypoints,
    )