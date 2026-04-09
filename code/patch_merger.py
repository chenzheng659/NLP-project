"""
patch_merger.py - 补丁合并模块
将 LLM 生成的修改后代码与基础草稿做智能 AST 对比和合并，
生成统一 diff 格式的对比文本，供前端展示。
"""
import difflib
from dataclasses import dataclass
import libcst as cst


@dataclass
class MergeResult:
    final_code: str
    unified_diff: str
    merge_method: str
    modified: bool


def generate_diff(before_code: str, after_code: str, filename: str = "code.py") -> str:
    """
    生成 unified diff 格式的修改前后对比文本。
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


class ASTMerger(cst.CSTTransformer):
    """
    遍历基础代码的 AST，如果遇到与 patch_module 同名的函数或类，
    则用 patch_module 中的节点将其替换。
    """
    def __init__(self, patch_module: cst.Module):
        self.patch_funcs = {
            node.name.value: node
            for node in patch_module.body
            if isinstance(node, cst.FunctionDef)
        }
        self.patch_classes = {
            node.name.value: node
            for node in patch_module.body
            if isinstance(node, cst.ClassDef)
        }

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.CSTNode:
        name = original_node.name.value
        if name in self.patch_funcs:
            return self.patch_funcs[name]
        return updated_node

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.CSTNode:
        name = original_node.name.value
        if name in self.patch_classes:
            return self.patch_classes[name]
        return updated_node


def merge_with_ast(base_code: str, patch_code: str) -> str:
    """
    使用 libcst 在 AST 层面合并代码：
    - 用 patch_code 中修改过的函数体/类替换 base_code 中对应的旧节点
    - 将 patch_code 中新增的函数/类追加到文件末尾
    如果解析失败，自动回退到纯文本模式，返回 patch_code。
    """
    try:
        base_module = cst.parse_module(base_code)
        patch_module = cst.parse_module(patch_code)

        # 1. 替换已经存在的函数或类
        merger = ASTMerger(patch_module)
        merged_module = base_module.visit(merger)

        # 2. 识别并追加新增的函数或类
        existing_funcs = {node.name.value for node in base_module.body if isinstance(node, cst.FunctionDef)}
        existing_classes = {node.name.value for node in base_module.body if isinstance(node, cst.ClassDef)}

        new_body = list(merged_module.body)
        for node in patch_module.body:
            if isinstance(node, cst.FunctionDef) and node.name.value not in existing_funcs:
                new_body.append(node)
            elif isinstance(node, cst.ClassDef) and node.name.value not in existing_classes:
                new_body.append(node)

        final_module = merged_module.with_changes(body=new_body)
        return final_module.code, "ast"
    except Exception:
        # 兜底：如果任何一方语法有误导致 libcst 无法解析，回退到整体覆盖模式
        return patch_code, "text"


def smart_merge(base_code: str, patch_code: str, use_ast: bool = True) -> MergeResult:
    """
    智能合并函数。对外暴露的唯一接口。

    Args:
        base_code: 原始基础草稿代码
        patch_code: LLM 生成的补丁或修改后的代码
        use_ast: 是否尝试启用 AST 级别合并

    Returns:
        MergeResult: 包含合并结果及对比文本的 DataClass
    """
    # 边缘情况 1：base_code 为空（全新生成模式）
    if not base_code.strip():
        diff_text = generate_diff("", patch_code)
        return MergeResult(
            final_code=patch_code,
            unified_diff=diff_text,
            merge_method="text",
            modified=True
        )

    # 边缘情况 2：如果代码完全一致，直接标记为无修改
    if base_code.strip() == patch_code.strip():
        return MergeResult(
            final_code=patch_code,
            unified_diff="",
            merge_method="text",
            modified=False
        )

    # 主体合并逻辑
    if use_ast:
        final_code, method = merge_with_ast(base_code, patch_code)
    else:
        final_code = patch_code
        method = "text"

    # 再次检查最终合成的内容是否真的发生了变化
    modified = base_code.strip() != final_code.strip()
    diff_text = generate_diff(base_code, final_code) if modified else ""

    return MergeResult(
        final_code=final_code,
        unified_diff=diff_text,
        merge_method=method,
        modified=modified
    )
