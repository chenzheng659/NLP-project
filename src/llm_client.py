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
import textwrap
from pathlib import Path
from typing import Optional
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
        raise FileNotFoundError(
            f"提示词模板文件缺失: {config.PROMPT_TEMPLATE_PATH}，请确保该文件存在。"
        )
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

# 追加在每个模板末尾的输出格式要求
_OUTPUT_FORMAT_INSTRUCTION = """

---
**输出格式要求（必须严格遵守）：**

请按以下格式输出，不要输出其他内容：

### 修改后
```python
{修改后的代码}
```

### 修改说明
{一句话说明做了什么改动。如果无需修改，请填写"无需修改"。}

**重要提示**:
- 如果您只修改一个类中的某个方法，请在 `修改后` 的代码块中**仅提供这个类以及被修改的方法**，无需包含整个文件的所有代码。
- 如果您要新增一个函数或类，请在 `修改后` 的代码块中仅提供新增的完整代码。
- 只有当您要进行全局重构或修改多个独立的函数/类时，才需要提供完整的模块代码。
"""


def build_prompt(instruction: str, base_code: str, has_source_code: bool) -> str:
    """
    根据是否有源代码选择对应模板并填充变量。
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
    return ""


# ── 响应解析 ───────────────────────────────────────


def parse_llm_response(raw: str, base_code: str) -> ParsedResponse:
    """
    从 LLM 输出中解析出结构化字段。
    处理 <think> 标签干扰、"无需修改"的语义冲突、代码块缺失等问题。
    """
    raw_cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    no_change_keywords = ["无修改", "no changes needed", "无需修改", "不需要修改"]
    if base_code.strip() and any(k in raw_cleaned.lower() for k in no_change_keywords):
        return ParsedResponse(
            original_code=base_code,
            modified_code=base_code,
            explanation="无需修改",
            modified=False,
            raw=raw,
        )

    modified_code = None
    note_match = re.search(r"###\s*修改说明\s*\n(.+)", raw_cleaned, re.DOTALL)
    patch_note = note_match.group(1).strip() if note_match else "无"

    after_match = re.search(r"###\s*修改后\s*```(?:python)?\n(.*?)```", raw_cleaned, re.DOTALL)
    if after_match:
        modified_code = after_match.group(1).strip()
    else:
        fallback_blocks = re.findall(r"```(?:python)?\n(.*?)```", raw_cleaned, re.DOTALL)
        if fallback_blocks:
            modified_code = fallback_blocks[-1].strip()
        else:
            modified_code = raw_cleaned

    if modified_code is not None:
        modified_code = textwrap.dedent(modified_code).strip()

    # CRITICAL FIX: Ensure modified is True if the extracted code is different,
    # even if it's a fallback.
    is_modified = False
    if modified_code is not None:
        if base_code.strip() != modified_code.strip():
            is_modified = True

    final_modified_code = modified_code if is_modified else base_code

    return ParsedResponse(
        original_code=base_code,
        modified_code=final_modified_code,
        explanation=patch_note,
        modified=is_modified,
        raw=raw,
    )

