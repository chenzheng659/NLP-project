"""
workflow.py - 工作流引擎（核心）
自动判断输入模式，串联检索 → LLM → 合并三个模块。

模式一（仅自然语言）：检索基础草稿 → 生成补丁 → 合并
模式二（代码 + 指令）：直接使用用户代码 → 生成补丁 → 合并
"""
from typing import Optional

from .retriever   import search_code
from .llm_client  import build_prompt, call_llm, parse_llm_response
from .patch_merger import smart_merge


def detect_mode(instruction: str, source_code: Optional[str]) -> str:
    """
    判断输入模式。
    规则：source_code 有实际内容 → 模式二，否则 → 模式一
    """
    if source_code and source_code.strip():
        return "direct_edit"
    return "retrieval_generation"


async def run_workflow(instruction: str, source_code: Optional[str]) -> dict:
    """
    主工作流入口。

    Args:
        instruction: 用户自然语言需求/指令
        source_code: 用户提供的原始代码（可为 None 或空字符串）

    Returns:
        {
            "mode":           使用的模式
            "retrieved_code": 模式一检索到的草稿（模式二为 None）
            "before_code":    修改前代码
            "after_code":     修改后代码（= final_code）
            "final_code":     最终输出代码
            "diff":           unified diff 对比文本
            "changed":        是否有实际修改
            "patch_note":     修改说明
            "llm_raw":        LLM 原始输出（调试用）
        }
    """
    mode = detect_mode(instruction, source_code)
    retrieved_code = None
    has_source_code = mode == "direct_edit"

    # ── Step 1: 确定基础草稿 ──────────────────────────
    if mode == "retrieval_generation":
        print(f"[模式一] 检索生成 | 指令: {instruction[:60]}...")
        retrieved_code = search_code(instruction)

        if retrieved_code:
            print(f"  → 检索命中，使用检索代码作为草稿")
            base_code = retrieved_code
        else:
            # 降级：无匹配，让 LLM 从头生成，base_code 置空
            print(f"  → 未检索到匹配，降级为纯生成")
            base_code = ""
    else:
        print(f"[模式二] 直接编辑 | 指令: {instruction[:60]}...")
        base_code = source_code.strip()

    # ── Step 2: 构造 Prompt 并调用 LLM ───────────────
    prompt = build_prompt(instruction, base_code, has_source_code)
    llm_raw = await call_llm(prompt)

    # ── Step 3: 解析 LLM 输出 ─────────────────────────
    parsed = parse_llm_response(llm_raw, base_code)

    # ── Step 4: 合并，生成 diff ───────────────────────
    merge_result = smart_merge(
        base_code=parsed.original_code,
        patch_code=parsed.modified_code,
        use_ast=True
    )

    # 尊重解析结果的修改标记
    # 这里我们结合了两边的判断。如果大模型输出"无需修改"，parsed.modified 为 False
    changed = merge_result.modified and parsed.modified

    return {
        "mode":           mode,
        "retrieved_code": retrieved_code,
        "before_code":    parsed.original_code,
        "after_code":     merge_result.final_code,
        "final_code":     merge_result.final_code,
        "diff":           merge_result.unified_diff,
        "changed":        changed,
        "patch_note":     parsed.explanation,
        "merge_method":   merge_result.merge_method,
        "llm_raw":        parsed.raw,
    }
