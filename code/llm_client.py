"""
llm_client.py - LLM 调用模块
负责：
  1. 加载提示词模板
  2. 构造 prompt（双模式自动选择模板）
  3. 调用 DeepSeek API
  4. 返回结构化结果（补丁 + 修改前后对比）
"""
import re
from pathlib import Path
from typing import Optional

import httpx

import config


# ── 提示词加载 ─────────────────────────────────────

def _load_templates() -> dict:
    """解析 prompt_templates.txt，返回 {section_name: content} 字典"""
    templates = {}
    current_key = None
    current_lines = []

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
{一句话说明做了什么改动}
"""


def build_prompt(instruction: str, base_code: str, mode: str) -> str:
    """
    根据模式选择对应模板并填充变量。

    Args:
        instruction: 用户的自然语言需求/指令
        base_code:   基础草稿代码（模式一为检索结果，模式二为用户提供的代码）
        mode:        'retrieval_generation' 或 'direct_edit'
    """
    templates = get_templates()

    if mode == "retrieval_generation":
        template = templates.get("retrieval_mode_zh", "")
        prompt = template.format(base_code=base_code, instruction=instruction)
    else:
        template = templates.get("direct_edit_mode_zh", "")
        prompt = template.format(source_code=base_code, instruction=instruction)

    return prompt + _OUTPUT_FORMAT_INSTRUCTION


# ── API 调用 ───────────────────────────────────────

async def call_llm(prompt: str) -> str:
    """异步调用 DeepSeek API，返回模型原始输出文本"""
    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": config.LLM_TEMPERATURE,
    }
    async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
        resp = await client.post(config.DEEPSEEK_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


# ── 响应解析 ───────────────────────────────────────

def parse_llm_response(raw: str, base_code: str) -> dict:
    """
    从 LLM 输出中解析出结构化字段：
      - before_code: 修改前代码
      - after_code:  修改后代码
      - patch:       修改说明
      - raw:         原始输出（调试用）
    """
    def extract_block(label: str) -> Optional[str]:
        # 匹配 ### 修改前/后 下方的 ```python ... ``` 代码块
        pattern = rf"###\s*{label}\s*```(?:python)?\n(.*?)```"
        m = re.search(pattern, raw, re.DOTALL)
        return m.group(1).strip() if m else None

    before = extract_block("修改前") or base_code
    after  = extract_block("修改后")

    # 兜底：如果格式不对，尝试提取任意代码块作为 after
    if after is None:
        fallback = re.search(r"```(?:python)?\n(.*?)```", raw, re.DOTALL)
        after = fallback.group(1).strip() if fallback else raw.strip()

    # 提取修改说明
    note_match = re.search(r"###\s*修改说明\s*\n(.+)", raw)
    patch_note = note_match.group(1).strip() if note_match else ""

    return {
        "before_code": before,
        "after_code":  after,
        "patch":       patch_note,
        "raw":         raw,
    }
