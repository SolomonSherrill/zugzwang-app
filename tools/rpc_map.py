#!/usr/bin/env python3
"""Writes RPC_MAP.md: every sidecar RPC method, where it is handled and who calls it (TOKENS-2 B, item 9).

Stdlib only; reads source, never runs it.

    python3 tools/rpc_map.py            # (re)write RPC_MAP.md at the repository root
    python3 tools/rpc_map.py --check    # exit 1 if RPC_MAP.md is not what this would write (gate.sh)
    python3 tools/rpc_map.py --why user_move books   # the main.py chain by which a method reaches an item

Per method (an `rpc_<name>` method of a class in sidecar/main.py):
- handler: sidecar/main.py:<line> of its def;
- core: the zugzwang.* functions and methods it reaches, following self.<method>, self.<attr>.<method>
  and x.<method> (an attribute or local variable whose class is known from an assignment Cls(...), an
  annotation, or a helper's return annotation), module-level functions inside main.py, and a queue
  hand-off (self.<q>.put reaches the same class's methods that call self.<q>.get), transitively;
  zugzwang.config is left out (constants). Calls through untyped values are not seen;
- wrapper: the desktop/src file:line and name of each sidecar.request('<name>') call (api.ts's key
  in the api object, or the function or const around it);
- used by: the non-test desktop/src files that use that wrapper (api.<key>, or the name imported),
  as paths under desktop/src/lib/.
"""
from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = "sidecar/main.py"
SRC = "desktop/src"
OUT = "RPC_MAP.md"


def _imports(tree):
    """name -> dotted target for every zugzwang import anywhere in the module (function-local ones too)."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("zugzwang"):
            for a in node.names:
                names[a.asname or a.name] = node.module + "." + a.name
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("zugzwang"):
                    names[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
    return {k: v for k, v in names.items() if not v.startswith("zugzwang.config")}


class Model:
    def __init__(self, src):
        self.tree = ast.parse(src)
        self.imports = _imports(self.tree)
        self.classes = {}      # class name -> {method name -> FunctionDef}
        self.attrs = {}        # class name -> {attr -> ("local", cls) | ("core", dotted)}
        self.functions = {}    # module-level function name -> FunctionDef
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef):
                self.classes[node.name] = {f.name: f for f in node.body
                                           if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
        self.returns = {}      # (class or None, function) -> kind of its return annotation
        for cname, methods in self.classes.items():
            amap = self.attrs.setdefault(cname, {})
            for f in methods.values():
                self.returns[(cname, f.name)] = self._ann_kind(f.returns)
                for n in ast.walk(f):
                    if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Name)):
                        kind = self._kind(n.value.func.id)
                        if kind is None:
                            continue
                        for t in n.targets:
                            if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                                    and t.value.id == "self"):
                                amap[t.attr] = kind
                    elif (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Attribute)
                          and isinstance(n.target.value, ast.Name) and n.target.value.id == "self"):
                        kind = self._ann_kind(n.annotation)
                        if kind is not None:
                            amap.setdefault(n.target.attr, kind)
        for name, f in self.functions.items():
            self.returns[(None, name)] = self._ann_kind(f.returns)

    def _ann_kind(self, ann):
        """The kind of an annotation naming one class: X, X | None, Optional[X], or the string forms."""
        if ann is None:
            return None
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            try:
                ann = ast.parse(ann.value, mode="eval").body
            except SyntaxError:
                return None
        if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
            for side in (ann.left, ann.right):
                k = self._ann_kind(side)
                if k is not None:
                    return k
            return None
        if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) and ann.value.id == "Optional":
            return self._ann_kind(ann.slice)
        if isinstance(ann, ast.Name):
            return self._kind(ann.id)
        return None

    def _expr_kind(self, c, e, local):
        """The kind of an expression's value: a local variable, self.attr, Cls(...), self.meth(...), f(...)."""
        if isinstance(e, ast.Name):
            return local.get(e.id)
        if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "self" and c:
            return self._attr_kind(c, e.attr)
        if isinstance(e, ast.Call):
            fn = e.func
            if isinstance(fn, ast.Name):
                return self._kind(fn.id) or self.returns.get((None, fn.id))
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "self" and c:
                return self.returns.get((c, fn.attr))
        return None

    def _kind(self, name):
        """A class's kind: one defined in main.py, or an imported zugzwang name that is a class
        (CapWords, as the codebase names them); None for a function, whose result is not followed."""
        if name in self.classes:
            return ("local", name)
        if name in self.imports and self.imports[name].rsplit(".", 1)[-1][:1].isupper():
            return ("core", self.imports[name])
        return None

    @staticmethod
    def _short(dotted):
        return dotted[len("zugzwang."):] if dotted.startswith("zugzwang.") else dotted

    def _attr_kind(self, cname, attr):
        kind = self.attrs.get(cname, {}).get(attr)
        if kind is None:
            for c in sorted(self.attrs):
                if attr in self.attrs[c]:
                    return self.attrs[c][attr]
        return kind

    def reach(self, cname, fname, why=None):
        """The core callables reachable from cname.fname (cname None: a module-level function).
        why: a dict filled with core item -> the chain of main.py functions that reaches it."""
        seen, core = set(), set()
        parent = {(cname, fname): None}
        stack = [(cname, fname)]

        class _Stack(list):
            def append(s, k):
                parent.setdefault(k, cur[0])
                list.append(s, k)

        class _Core(set):
            def add(s, item):
                if why is not None and item not in why:
                    chain, k = [], cur[0]
                    while k is not None:
                        chain.append("%s.%s" % k if k[0] else k[1])
                        k = parent.get(k)
                    why[item] = " <- ".join(chain)
                set.add(s, item)

        stack, core, cur = _Stack(stack), _Core(), [None]
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            cur[0] = key
            c, f = key
            node = self.classes.get(c, {}).get(f) if c else self.functions.get(f)
            if node is None:
                continue
            local = {}
            for n in ast.walk(node):
                if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    kind = self._expr_kind(c, n.value, local)
                    for t in targets:
                        if isinstance(t, ast.Name) and kind is not None:
                            local[t.id] = kind
                elif isinstance(n, ast.withitem) and isinstance(n.optional_vars, ast.Name):
                    kind = self._expr_kind(c, n.context_expr, local)
                    if kind is not None:
                        local[n.optional_vars.id] = kind
            queues = set()
            for n in ast.walk(node):
                # main.py-internal references, called or not (a thread target is a reference)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" and c:
                    if n.attr in self.classes.get(c, {}):
                        stack.append((c, n.attr))
                elif isinstance(n, ast.Name) and n.id in self.functions:
                    stack.append((None, n.id))
                elif isinstance(n, ast.Name) and n.id in self.classes:
                    stack.append((n.id, "__init__"))
                if not isinstance(n, ast.Call):
                    continue
                fn = n.func
                if isinstance(fn, ast.Name) and fn.id in self.imports:
                    core.add(self._short(self.imports[fn.id]))
                elif isinstance(fn, ast.Attribute):
                    v = fn.value
                    if (fn.attr in ("put", "put_nowait") and isinstance(v, ast.Attribute)
                            and isinstance(v.value, ast.Name) and v.value.id == "self" and c):
                        queues.add(v.attr)                                       # work handed to a thread
                    if isinstance(v, ast.Name) and v.id in local:                 # x.meth, x of a known kind
                        kind = local[v.id]
                        if kind[0] == "core":
                            core.add(self._short(kind[1]) + "." + fn.attr)
                        else:
                            stack.append((kind[1], fn.attr))
                    elif isinstance(v, ast.Name) and v.id in self.imports:        # module.func / Class.meth
                        core.add(self._short(self.imports[v.id]) + "." + fn.attr)
                    elif (isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name)
                          and v.value.id == "self" and c):                       # self.attr.meth
                        kind = self._attr_kind(c, v.attr)
                        if kind and kind[0] == "core":
                            core.add(self._short(kind[1]) + "." + fn.attr)
                        elif kind and kind[0] == "local":
                            stack.append((kind[1], fn.attr))
            # a queue put: the methods of this class that take from that queue do the work (not in the
            # dispatcher itself, whose queue feeds its main loop: what post_call runs is followed as a
            # reference already)
            if any(m.startswith("rpc_") for m in self.classes.get(c, {})):
                queues = set()
            for q in sorted(queues):
                for mname, m in self.classes.get(c, {}).items():
                    for n in ast.walk(m):
                        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                                and n.func.attr in ("get", "get_nowait")
                                and isinstance(n.func.value, ast.Attribute)
                                and n.func.value.attr == q):
                            stack.append((c, mname))
                            break
        return sorted(core)


def handlers(model):
    out = {}
    for cname, methods in model.classes.items():
        for name, f in methods.items():
            if name.startswith("rpc_"):
                out[name[4:]] = (cname, name, f.lineno)
    return out


REQ = re.compile(r"\.request(?:<[\s\S]*?>)?\(\s*'([a-z_0-9]+)'")
KEY = re.compile(r"^  (\w+)(?:\??:| *\()")
TOP = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|const\s+(\w+)|let\s+(\w+))")


def ts_files():
    out = []
    for d, _, fs in os.walk(os.path.join(ROOT, SRC)):
        for f in fs:
            if f.endswith((".ts", ".svelte")) and ".test." not in f:
                out.append(os.path.relpath(os.path.join(d, f), ROOT))
    return sorted(out)


def wrappers(files, texts):
    """method -> [(file, line, wrapper name)]"""
    out = {}
    for path in files:
        text = texts[path]
        lines = text.split("\n")
        for m in REQ.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            name = None
            for i in range(line - 1, -1, -1):
                k = KEY.match(lines[i])
                if k:
                    name = k.group(1)
                    break
                t = TOP.match(lines[i])
                if t:
                    name = next(g for g in t.groups() if g)
                    break
            out.setdefault(m.group(1), []).append((path, line, name or "?"))
    return out


def rel(path):
    lib = SRC + "/lib/"
    return path[len(lib):] if path.startswith(lib) else os.path.relpath(path, SRC)


def users(name, files, texts):
    """Non-test files using the wrapper: api.<name> anywhere, or <name> imported."""
    use = re.compile(r"\bapi\s*\.\s*" + re.escape(name) + r"\b")
    imp = re.compile(r"import\s*\{[^}]*\b" + re.escape(name) + r"\b[^}]*\}\s*from")
    return sorted(p for p in files if use.search(texts[p]) or imp.search(texts[p]))


def build():
    with open(os.path.join(ROOT, MAIN_PY), encoding="utf-8") as fh:
        model = Model(fh.read())
    hs = handlers(model)
    files = ts_files()
    texts = {}
    for p in files:
        with open(os.path.join(ROOT, p), encoding="utf-8") as fh:
            texts[p] = fh.read()
    ws = wrappers(files, texts)
    api_lines = texts.get(SRC + "/lib/api.ts", "").split("\n")

    def api_keys_using(helper):
        """api object keys whose body calls a helper defined in api.ts (const sendUserMove = ...)."""
        keys = []
        for i, l in enumerate(api_lines):
            if re.search(r"\b" + re.escape(helper) + r"\(", l) and not TOP.match(l):
                for j in range(i, -1, -1):
                    k = KEY.match(api_lines[j])
                    if k:
                        keys.append(k.group(1))
                        break
        return keys

    rows = []
    for method in sorted(set(hs) | set(ws)):
        h = hs.get(method)
        if h:
            core = model.reach(h[0], h[1])
            hcell = "%s:%d" % (MAIN_PY, h[2])
        else:
            core, hcell = [], "**none** (no rpc_%s)" % method
        wcells, ucells = [], set()
        for path, line, name in ws.get(method, []):
            names = [name]
            if path.endswith("/api.ts"):
                names += api_keys_using(name)
            wcells.append("%s %s:%d" % ("/".join(names), rel(path), line))
            for n in names:
                ucells.update(rel(u) for u in users(n, files, texts) if u != path)
        rows.append("| %s | %s | %s | %s | %s |" % (
            method, hcell, ", ".join(core) or "—",
            "; ".join(wcells) or "**none**", ", ".join(sorted(ucells)) or "—"))
    no_wrapper = [m for m in sorted(hs) if m not in ws]
    no_handler = [m for m in sorted(ws) if m not in hs]
    head = [
        "# RPC map — generated, do not edit",
        "",
        "Written by `tools/rpc_map.py` (TOKENS-2 B, FIXPLAN `TOKENS-2`). `tools/gate.sh` fails when this file is",
        "not what the script writes: after changing `sidecar/main.py` or a `sidecar.request` call, run",
        "`python3 tools/rpc_map.py` and commit the result. One row per RPC method: the handler (`rpc_<method>`",
        "in `sidecar/main.py`), the `zugzwang.*` functions it reaches (following `self.` helpers and the runner",
        "classes inside `main.py`; `config` left out), its wrapper in `desktop/src` (name, file:line, paths under",
        "`desktop/src/lib/`), and the non-test files that use the wrapper.",
        "",
        "%d methods handled. Without a frontend wrapper (%d): %s. Requested with no handler (%d): %s." % (
            len(hs), len(no_wrapper), ", ".join(no_wrapper) or "none",
            len(no_handler), ", ".join(no_handler) or "none"),
        "",
        "| method | handler | core | wrapper | used by |",
        "|---|---|---|---|---|",
    ]
    return "\n".join(head + rows) + "\n"


def main(argv):
    if argv[:1] == ["--why"] and len(argv) == 3:       # --why METHOD CORE_ITEM: the chain that reaches it
        with open(os.path.join(ROOT, MAIN_PY), encoding="utf-8") as fh:
            model = Model(fh.read())
        c, f, _ = handlers(model)[argv[1]]
        why = {}
        model.reach(c, f, why)
        for item, chain in sorted(why.items()):
            if argv[2] in item:
                print("%s: %s" % (item, chain))
        return 0
    text = build()
    path = os.path.join(ROOT, OUT)
    if "--check" in argv:
        cur = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                cur = fh.read()
        n = text.count("\n| ") - 1
        if cur != text:
            print("RPC_MAP.md is stale (%d methods): run python3 tools/rpc_map.py and commit it" % n)
            return 1
        print("RPC_MAP.md up to date (%d methods)" % n)
        return 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
