import libcst as cst
import libcst.helpers as helpers

class ImportExtractor(cst.CSTVisitor):
    def __init__(self):
        self.imports = []
    def visit_Import(self, node: cst.Import) -> None:
        self.imports.append(node)
    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        self.imports.append(node)

patch = """
import os
import sys
from math import pi
"""
mod = cst.parse_module(patch)
extractor = ImportExtractor()
mod.visit(extractor)
print(len(extractor.imports))

class ClassMethodMerger(cst.CSTTransformer):
    def __init__(self, patch_class_node):
        self.patch_methods = {}
        for node in patch_class_node.body.body:
            if isinstance(node, cst.FunctionDef):
                self.patch_methods[node.name.value] = node

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.CSTNode:
        new_body = []
        existing_methods = set()
        
        for item in updated_node.body.body:
            if isinstance(item, cst.FunctionDef):
                name = item.name.value
                existing_methods.add(name)
                if name in self.patch_methods:
                    new_body.append(self.patch_methods[name])
                else:
                    new_body.append(item)
            else:
                new_body.append(item)
                
        # append new methods
        for name, method in self.patch_methods.items():
            if name not in existing_methods:
                new_body.append(method)
                
        new_indented_block = updated_node.body.with_changes(body=new_body)
        return updated_node.with_changes(body=new_indented_block)

base = """
class A:
    def foo(self):
        return 1
    def bar(self):
        return 2
"""
patch2 = """
class A:
    def foo(self):
        return 'new'
    def baz(self):
        return 3
"""

base_mod = cst.parse_module(base)
patch_mod2 = cst.parse_module(patch2)

patch_class = None
for node in patch_mod2.body:
    if isinstance(node, cst.ClassDef):
        patch_class = node

merger = ClassMethodMerger(patch_class)
merged = base_mod.visit(merger)
print(merged.code)

