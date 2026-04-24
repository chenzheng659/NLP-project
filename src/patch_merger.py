"""
patch_merger.py - 补丁合并模块
将 LLM 生成的修改后代码与基础草稿做智能 AST 对比和合并，
生成统一 diff 格式的对比文本，供前端展示。
"""
import difflib
import logging
import textwrap
from dataclasses import dataclass
import libcst as cst
import libcst.helpers as cst_helpers

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@dataclass
class MergeResult:
    final_code: str
    unified_diff: str
    merge_method: str
    modified: bool


def generate_diff(before_code: str, after_code: str, filename: str = "code.py") -> str:
    before_lines = before_code.splitlines(keepends=True)
    after_lines  = after_code.splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines, after_lines, fromfile=f"before/{filename}",
        tofile=f"after/{filename}", lineterm="",
    )
    return "\n".join(diff)


class AliasCollector(cst.CSTVisitor):
    def __init__(self):
        self.aliases: dict[str, str] = {}
        self.from_imports: dict[str, set[str]] = {}

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            try:
                module_name = cst_helpers.get_full_name_for_node(alias.name)
                as_name = alias.asname.name.value if alias.asname else module_name
                self.aliases[module_name] = as_name
            except Exception:
                pass

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        try:
            if node.module:
                module_name = cst_helpers.get_full_name_for_node(node.module)
                if module_name not in self.from_imports:
                    self.from_imports[module_name] = set()
                if isinstance(node.names, cst.ImportStar):
                     self.from_imports[module_name].add('*')
                else:
                    for name in node.names:
                        self.from_imports[module_name].add(name.name.value)
        except Exception:
            pass


class PatchAliasRewriter(cst.CSTTransformer):
    def __init__(self, alias_map: dict[str, str]):
        self.alias_map = alias_map

    def leave_Attribute(self, original_node: cst.Attribute, updated_node: cst.Attribute) -> cst.BaseExpression:
        try:
            module_path = cst_helpers.get_full_name_for_node(original_node.value)
            if module_path and module_path in self.alias_map:
                alias = self.alias_map[module_path]
                if alias != module_path:
                    return updated_node.with_changes(value=cst.Name(value=alias))
        except Exception:
            pass
        return updated_node


class MethodFinderAndWrapper(cst.CSTTransformer):
    def __init__(self, patch_method_node: cst.FunctionDef):
        self.patch_method_name = patch_method_node.name.value
        self.found_and_wrapped = False
        self.wrapper_class_name: str | None = None

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.CSTNode:
        for node in original_node.body.body:
            if isinstance(node, cst.FunctionDef) and node.name.value == self.patch_method_name:
                self.wrapper_class_name = original_node.name.value
                self.found_and_wrapped = True
                break
        return updated_node


def wrap_snippet(base_module: cst.Module, patch_code: str) -> str:
    try:
        patch_ast = cst.parse_statement(patch_code)
        if isinstance(patch_ast, cst.FunctionDef):
            params = patch_ast.params.params
            if params and params[0].name.value == 'self':
                finder = MethodFinderAndWrapper(patch_ast)
                base_module.visit(finder)
                if finder.found_and_wrapped and finder.wrapper_class_name:
                    return f"class {finder.wrapper_class_name}:\n{textwrap.indent(patch_code, '    ')}"
    except Exception:
        pass
    return patch_code


class ClassBodyMerger(cst.CSTTransformer):
    """
    Surgically merges methods into a class body. Replaces existing methods,
    and appends new ones at the end of the class. This visitor is designed
    to be shallow and will not recurse into nested blocks.
    """
    def __init__(self, patch_class_def: cst.ClassDef):
        self.patch_methods = {
            node.name.value: node
            for node in patch_class_def.body.body
            if isinstance(node, (cst.FunctionDef, cst.ClassDef))
        }

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.CSTNode:
        # One-to-one replacement of existing methods.
        if original_node.name.value in self.patch_methods:
            return self.patch_methods.pop(original_node.name.value)
        return updated_node

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.CSTNode:
        # This is the key fix: We are already in the context of the target class.
        # We perform the final append operation here, once, at the class level.
        # This prevents the bug of appending new methods into every nested block.

        # We need to construct a new body for the updated class definition.
        # Start with the existing nodes from the (potentially modified) class.
        new_body_content = list(updated_node.body.body)

        # Append any *new* methods from the patch that were not used as replacements.
        new_body_content.extend(self.patch_methods.values())

        # Create a new IndentedBlock with the final, complete body.
        new_body = updated_node.body.with_changes(body=new_body_content)

        # Return the class definition with the new body.
        return updated_node.with_changes(body=new_body)


class ASTMerger(cst.CSTTransformer):
    def __init__(self, patch_module: cst.Module):
        self.patch_items = {
            node.name.value: node for node in patch_module.body
            if isinstance(node, (cst.FunctionDef, cst.ClassDef))
        }

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.CSTNode:
        if original_node.name.value in self.patch_items:
            return self.patch_items.pop(original_node.name.value)
        return updated_node

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.CSTNode:
        class_name = original_node.name.value
        if class_name in self.patch_items:
            patch_class_def = self.patch_items.pop(class_name)
            if isinstance(patch_class_def, cst.ClassDef):
                # Instantiate our new, safer merger
                merger = ClassBodyMerger(patch_class_def)
                # Visit the original class node with it.
                return original_node.visit(merger)
        return updated_node


def merge_with_ast(base_code: str, patch_code: str) -> tuple[str, str]:
    try:
        base_module = cst.parse_module(base_code)
        wrapped_patch_code = wrap_snippet(base_module, patch_code)
        patch_module = cst.parse_module(wrapped_patch_code)

        alias_collector = AliasCollector()
        base_module.visit(alias_collector)
        rewritten_patch_module = patch_module.visit(PatchAliasRewriter(alias_collector.aliases))

        merger = ASTMerger(rewritten_patch_module)
        merged_module = base_module.visit(merger)

        final_body = list(merged_module.body) + list(merger.patch_items.values())
        final_module = merged_module.with_changes(body=final_body)

        logging.info("Successfully merged code using AST.")
        return final_module.code, "ast"

    except Exception as e:
        logging.error(f"Critical AST merging failed: {e}. FALLING BACK TO BASE CODE.", exc_info=True)
        return base_code, f"text_fallback: {type(e).__name__}: {e}"


def smart_merge(base_code: str, patch_code: str, use_ast: bool = True) -> MergeResult:
    if not base_code.strip():
        return MergeResult(final_code=patch_code, unified_diff=generate_diff("", patch_code), merge_method="text", modified=True)

    if base_code.strip() == patch_code.strip():
        return MergeResult(final_code=patch_code, unified_diff="", merge_method="text", modified=False)

    final_code, method = merge_with_ast(base_code, patch_code) if use_ast else (patch_code, "text")

    modified = base_code.strip() != final_code.strip()
    diff_text = generate_diff(base_code, final_code) if modified else ""

    return MergeResult(final_code=final_code, unified_diff=diff_text, merge_method=method, modified=modified)
