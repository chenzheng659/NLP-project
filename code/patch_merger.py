"""
patch_merger.py - 补丁合并模块
将 LLM 生成的修改后代码与基础草稿做对比，
生成统一 diff 格式的对比文本，供前端展示。
"""
import difflib
from typing import Optional


def generate_diff(before_code: str, after_code: str, filename: str = "code.py") -> str:
    """
    生成 unified diff 格式的修改前后对比文本。

    Args:
        before_code: 修改前的代码
        after_code:  修改后的代码
        filename:    显示在 diff 头部的文件名

    Returns:
        unified diff 字符串
    """
    before_lines = before_code.splitlines(keepends=True)
    after_lines  = after_code.splitlines(keepends=True)

    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"before/{filename}",
        tofile=f"after/{filename}",
        lineterm="",
    )
    return "\n".join(diff)


def is_no_change(patch_note: str, before: str, after: str) -> bool:
    """判断 LLM 是否认为无需修改"""
    no_change_keywords = ("无修改", "no changes needed", "无需修改", "不需要修改")
    if any(k in patch_note.lower() for k in no_change_keywords):
        return True
    # 代码内容完全一致也视为无修改
    return before.strip() == after.strip()


def merge(before_code: str, after_code: str, patch_note: str) -> dict:
    """
    整合修改结果，返回前端所需的完整对比数据。

    Returns:
        {
            "final_code": 最终代码,
            "diff":       unified diff 字符串,
            "changed":    是否有实际修改,
            "patch_note": 修改说明,
        }
    """
    changed = not is_no_change(patch_note, before_code, after_code)
    final_code = after_code if changed else before_code
    diff_text  = generate_diff(before_code, final_code) if changed else ""

    return {
        "final_code": final_code,
        "diff":       diff_text,
        "changed":    changed,
        "patch_note": patch_note,
    }
