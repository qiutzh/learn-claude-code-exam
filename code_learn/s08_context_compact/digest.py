import ast
import pathlib

def digest(path, tag):
    src = pathlib.Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    print("=" * 70)
    print(tag, str(path))
    print("=" * 70)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef):
            doc = ast.get_docstring(n) or ""
            doc = " ".join(doc.split())[:160]
            print(f"L{n.lineno} def {n.name}: {doc}")
        elif isinstance(n, ast.ClassDef):
            doc = ast.get_docstring(n) or ""
            doc = " ".join(doc.split())[:160]
            print(f"L{n.lineno} class {n.name}: {doc}")
            for m in n.body:
                if isinstance(m, ast.FunctionDef):
                    d = ast.get_docstring(m) or ""
                    d = " ".join(d.split())[:160]
                    print(f"  L{m.lineno} def {m.name}: {d}")

digest(r"..\..\code_official\s08_context_compact\code.py", "S08")
digest(r"..\..\code_official\s09_memory\code.py", "S09")