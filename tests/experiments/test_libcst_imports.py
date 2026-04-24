import libcst as cst
import libcst.helpers as helpers

def get_import_signature(node):
    sigs = set()
    if isinstance(node, cst.Import):
        for alias in node.names:
            name = helpers.get_full_name_for_node(alias.name)
            asname = alias.asname.name.value if alias.asname else None
            sigs.add(("import", name, asname))
    elif isinstance(node, cst.ImportFrom):
        mod = helpers.get_full_name_for_node(node.module) if node.module else ""
        level = len(node.relative) if node.relative else 0
        if isinstance(node.names, cst.ImportStar):
            sigs.add(("from", mod, level, "*", None))
        else:
            for alias in node.names:
                name = helpers.get_full_name_for_node(alias.name)
                asname = alias.asname.name.value if alias.asname else None
                sigs.add(("from", mod, level, name, asname))
    return sigs

base = """
import os
from typing import List
"""
patch = """
import sys
import os as myos
from typing import List, Optional
"""

b_mod = cst.parse_module(base)
p_mod = cst.parse_module(patch)

b_sigs = set()
for n in b_mod.body:
    if isinstance(n, (cst.Import, cst.ImportFrom)):
        b_sigs.update(get_import_signature(n))

print("Base:", b_sigs)

new_imports = []
for n in p_mod.body:
    if isinstance(n, (cst.Import, cst.ImportFrom)):
        n_sigs = get_import_signature(n)
        if not n_sigs.issubset(b_sigs):
            # To be precise, if the entire node is new, we append the node. 
            # Or we could just append the patch node.
            new_imports.append(n)

print("New Imports:", len(new_imports))
