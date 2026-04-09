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
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx

import config


@dataclass
class ParsedResponse:
    original_code: str
    modified_code: str
    explanation: str
    modified: bool
    raw: str


# ── 提示词加载 ─────────────────────────────────────

def _load_templates() -> dict:
    """解析 prompt_templates.txt，返回 {section_name: content} 字典"""
    templates = {}
    current_key = None
    current_lines = []

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
        raise FileNotFoundError(f"提示词模板文件缺失: {config.PROMPT_TEMPLATE_PATH}，请确保该文件存在。")
    except Exception as e:
        raise RuntimeError(f"读取提示词模板文件时发生错误: {e}")

    return templates


_templates: Optional[dict] = None


def get_templates() -> dict:
    global _templates
    if _templates is None:
        _templates = _load_templates()
    return _templates


# ── Prompt 构造 ────────────────────────────────────

# 追加在每个模板末尾的输出格式要求，要求 LLM 输出修改前后对比
_OUTPUT_FORMAT_INSTRUCTION = """

---
**输出格式要求（必须严格遵守）：**

请按以下格式输出，不要输出其他内容：

### 修改前
```python
{原始代码或基础草稿}
```

### 修改后
```python
{修改后的完整代码}
```

### 修改说明
{一句话说明做了什么改动。如果无需修改，请填写"无需修改"，并在上述两部分中均输出完整的原始代码。}
"""


def build_prompt(instruction: str, base_code: str, has_source_code: bool) -> str:
    """
    根据是否有源代码选择对应模板并填充变量。

    Args:
        instruction: 用户的自然语言需求/指令
        base_code:   基础草稿代码（无源码时为检索结果，有源码时为用户提供的代码）
        has_source_code: 布尔值，用于选择直接编辑模式（True）或检索生成模式（False）
    """
    templates = get_templates()

    if not has_source_code:
        template = templates.get("retrieval_mode_zh", "")
        prompt = template.format(base_code=base_code, instruction=instruction)
    else:
        template = templates.get("direct_edit_mode_zh", "")
        prompt = template.format(source_code=base_code, instruction=instruction)

    return prompt + _OUTPUT_FORMAT_INSTRUCTION


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
                resp = await client.post(config.DEEPSEEK_API_URL, json=payload, headers=headers)
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
    return ""


# ── 响应解析 ───────────────────────────────────────

def parse_llm_response(raw: str, base_code: str) -> ParsedResponse:
    """
    从 LLM 输出中解析出结构化字段。
    处理 <think> 标签干扰、"无需修改"的语义冲突等问题。
    """
    # 1. 剔除 <think> 标签，防止推理过程干扰
    raw_cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    
    # 2. 检测"无修改"关键字兜底
    no_change_keywords = ["无修改", "no changes needed", "无需修改", "不需要修改"]
    if any(k in raw_cleaned.lower() for k in no_change_keywords):
        return ParsedResponse(
            original_code=base_code,
            modified_code=base_code,
            explanation="无需修改",
            modified=False,
            raw=raw
        )

    def extract_block(label: str) -> Optional[str]:
        # 匹配 ### 修改前/后 下方的 ```python ... ``` 代码块
        pattern = rf"###\s*{label}\s*```(?:python)?\n(.*?)```"
        m = re.search(pattern, raw_cleaned, re.DOTALL)
        return m.group(1).strip() if m else None

    before = extract_block("修改前") or base_code
    after  = extract_block("修改后")

    # 提取修改说明
    note_match = re.search(r"###\s*修改说明\s*\n(.+)", raw_cleaned)
    patch_note = note_match.group(1).strip() if note_match else ""

    # 兜底：如果格式不对（例如模型只输出了一个代码块），提取最后那个代码块作为 after
    if after is None:
        fallback_blocks = re.findall(r"```(?:python)?\n(.*?)```", raw_cleaned, re.DOTALL)
        if fallback_blocks:
            after = fallback_blocks[-1].strip()
        else:
            after = raw_cleaned.strip()

    # 最后再检查一遍内容是否实际发生了修改
    is_modified = after.strip() != before.strip() and after.strip() != base_code.strip()

    return ParsedResponse(
        original_code=before,
        modified_code=after if is_modified else base_code,
        explanation=patch_note,
        modified=is_modified,
        raw=raw
    )
