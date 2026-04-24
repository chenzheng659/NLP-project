import sys
import os
import pytest

# 将 code 目录加入 PYTHONPATH 使得测试能够正常引入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../code')))

from patch_merger import smart_merge, MergeResult

def test_ast_merge_normal():
    base_code = """
def func_a():
    return 1

def func_b():
    return 2
"""
    patch_code = """
def func_a():
    return 10
"""
    res = smart_merge(base_code, patch_code, use_ast=True)
    
    assert isinstance(res, MergeResult)
    assert res.merge_method == "ast"
    assert res.modified is True
    # 期望 AST 替换后，func_a 变为了返回 10，而 func_b 原样保留
    assert "return 10" in res.final_code
    assert "def func_b():" in res.final_code
    assert "return 2" in res.final_code
    assert res.unified_diff != ""


def test_ast_merge_fallback():
    base_code = "def foo():\n    return 1"
    # 故意给出语法错误的 Python 代码，导致 libcst 解析失败
    patch_code = "def foo():\n    return 10\n!!!invalid syntax+++"
    
    res = smart_merge(base_code, patch_code, use_ast=True)
    
    # 降级到 text 模式，直接全量替换为 patch_code
    assert res.merge_method == "text"
    assert res.final_code == patch_code
    assert res.modified is True


def test_base_code_empty():
    base_code = "   \n"
    patch_code = "def new_func():\n    pass"
    
    res = smart_merge(base_code, patch_code, use_ast=True)
    
    # 因为没有原始代码，会退化到 text 模式全量返回 patch
    assert res.merge_method == "text"
    assert res.modified is True
    assert res.final_code == patch_code
    assert res.unified_diff != ""


def test_same_code():
    base_code = "def foo():\n    return 1"
    patch_code = "def foo():\n    return 1\n  "
    
    res = smart_merge(base_code, patch_code, use_ast=True)
    
    assert res.merge_method == "text"
    assert res.modified is False
    assert res.final_code == patch_code
    assert res.unified_diff == ""
