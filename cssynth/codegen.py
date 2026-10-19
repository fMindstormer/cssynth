"""Turn a stack of shapes into short HTML/CSS.

The output targets CSSBattle's setup: a 400x300 frame and no doctype, so the
page renders in quirks mode, where lengths like `left:50` need no unit.

Golf passes:
  * shortest color spelling (named color, #rgb or #rrggbb)
  * one element per shape: `<b style=...>`, unclosed (fixed-position
    children still position against the viewport)
  * box-shadow grouping: a shape that is a translated (and, via spread,
    uniformly grown or shrunk) copy of another becomes a shadow of it,
    when the paint order allows it
  * properties shared by every element move into a single `b{...}` rule,
    placed in a `<style>` at the very end, left unclosed (the parser closes
    the element and the rule at end of input); families of alike elements
    (copies of one shape, turned or moved) can take their own tag and rule
  * a striped background becomes one hard-stop `linear-gradient`
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from .shapes import Gradient, H, Shape, W, coverage

NAMED = {
    "#ff0000": "red", "#d2b48c": "tan", "#ffd700": "gold", "#808080": "gray",
    "#000080": "navy", "#cd853f": "peru", "#ffc0cb": "pink", "#dda0dd": "plum",
    "#fffafa": "snow", "#008080": "teal", "#f0ffff": "azure", "#f5f5dc": "beige",
    "#a52a2a": "brown", "#ff7f50": "coral", "#f0e68c": "khaki", "#faf0e6": "linen",
    "#808000": "olive", "#f5deb3": "wheat", "#008000": "green", "#fffff0": "ivory",
    "#ffe4c4": "bisque", "#800000": "maroon", "#ffa500": "orange", "#da70d6": "orchid",
    "#800080": "purple", "#fa8072": "salmon", "#a0522d": "sienna", "#c0c0c0": "silver",
    "#ff6347": "tomato", "#ee82ee": "violet", "#4b0082": "indigo",
}


def color_css(rgb) -> str:
    h = "#%02x%02x%02x" % tuple(int(v) for v in rgb)
    opts = [h]
    if h[1] == h[2] and h[3] == h[4] and h[5] == h[6]:
        opts.append("#" + h[1] + h[3] + h[5])
    if h in NAMED:
        opts.append(NAMED[h])
    return min(opts, key=len)


def bgcolor_attr(rgb) -> str:
    h = "#%02x%02x%02x" % tuple(int(v) for v in rgb)
    opts = [h[1:]]                     # legacy color parsing accepts bare hex
    if h in NAMED:
        opts.append(NAMED[h])
    short = color_css(rgb)
    if short.startswith("#") and len(short) == 4:
        opts.append(short)
    return min(opts, key=len)


def num(v) -> str:
    v = round(float(v), 2)
    if v == int(v):
        return str(int(v))
    s = f"{v:g}"
    return s.replace("0.", ".", 1) if s.startswith(("0.", "-0.")) else s


def px(v) -> str:
    return "0" if float(v) == 0 else num(v) + "px"


# --------------------------------------------------------------------------
# Per-shape properties
# --------------------------------------------------------------------------

# Short tokens and their lengths in px (font-size is the default 16px).
_SHORT = [("1em", 16), ("2em", 32), ("3em", 48), ("4em", 64), ("5em", 80), ("6em", 96),
          ("7em", 112), ("8em", 128), ("9em", 144), ("2in", 192), ("3in", 288), ("9in", 864)]


def _radius_tokens(s: Shape, i: int) -> list[str]:
    """Spellings of corner i's radius that render identically, including
    over-large values that CSS scales back down to the same corner."""
    v = s.radii[i]
    toks = [px(v)]
    if s.w == s.h and (v * 100) % s.w == 0:
        toks.append(num(v * 100 / s.w) + "%")
    target = s.corner_radii()
    for tok, val in _SHORT:
        if val <= v:
            continue
        r = list(s.radii)
        r[i] = val
        got = s.copy(radii=tuple(r)).corner_radii()
        if all(abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6 for a, b in zip(got, target)):
            toks.append(tok)
            break
    return sorted(toks, key=len)


def radius_css(s: Shape) -> str | None:
    if s.ell:
        return "50%"
    r = s.radii
    if not any(r):
        return None
    opts = []
    if len(set(r)) == 1:
        opts.append(px(r[0]))
        if s.w == s.h and r[0] * 2 >= s.w:
            opts.append("50%")
        for tok, val in _SHORT:
            if val > r[0] and s.copy(radii=(val,) * 4).corner_radii() == s.corner_radii():
                opts.append(tok)
                break
    else:
        opts.append(" ".join(_radius_tokens(s, i)[0] if v else "0" for i, v in enumerate(r)))
    return min(opts, key=len)


def _coord(v, size) -> str:
    opts = [px(v)]
    if size and (v * 100) % size == 0:
        opts.append(num(v * 100 / size) + "%")
    return min(opts, key=len)


def shape_props(s: Shape, palette) -> list[tuple[str, str]]:
    x, y = s.pos()           # rotated boxes: the whole-pixel position Chromium uses
    p = [("left", num(x)), ("top", num(y)), ("width", num(s.w)),
         ("height", num(s.h)), ("background", color_css(palette[s.color]))]
    if s.poly:
        pts = ",".join(f"{_coord(a - s.x, s.w)} {_coord(b - s.y, s.h)}" for a, b in s.poly)
        p.append(("clip-path", f"polygon({pts})"))
        return p
    r = radius_css(s)
    if r:
        p.append(("border-radius", r))
    if s.rot % 360:
        p.append(("rotate", num(s.rot) + "deg"))
    return p


def decl_len(p, v) -> int:
    return len(p) + 1 + len(v)


# --------------------------------------------------------------------------
# Paint-order constraints and shadow groups
# --------------------------------------------------------------------------

def full_mask(s: Shape) -> np.ndarray:
    m = np.zeros((H, W), dtype=bool)
    x0, y0, c = coverage(s)
    if c is not None:
        m[y0:y0 + c.shape[0], x0:x0 + c.shape[1]] = c
    return m


def precedence(shapes) -> set[tuple[int, int]]:
    """(i, j): i must be painted below j (they overlap with different colors)."""
    masks = [full_mask(s) for s in shapes]
    edges = set()
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            if shapes[i].color != shapes[j].color and (masks[i] & masks[j]).any():
                edges.add((i, j))
    return edges


def shadow_of(anchor: Shape, s: Shape):
    """(dx, dy, spread) if s equals anchor's box-shadow with that offset."""
    if anchor.rot % 360 or s.rot % 360 or anchor.poly or s.poly:
        return None
    dw, dh = s.w - anchor.w, s.h - anchor.h
    if dw != dh or dw % 2:          # whole-pixel spreads only
        return None
    sp = dw / 2
    if anchor.ell != s.ell:
        return None
    # CSS bends a shadow's corner radius when the spread exceeds it (the spread
    # is scaled by 1 + (r - 1)^3, r = radius / spread), so a large spread
    # around a small ellipse is no longer an ellipse. Only exact cases group.
    if anchor.ell and sp > min(anchor.w, anchor.h) / 2:
        return None
    if not anchor.ell:
        for ra, rs in zip(anchor.radii, s.radii):
            if ra == 0:
                if rs != 0:
                    return None
            else:
                if sp > 0 and ra < sp:      # spec bends small radii; avoid
                    return None
                if abs(max(0, ra + sp) - rs) > 1e-6:
                    return None
    dx = s.x - anchor.x + sp
    dy = s.y - anchor.y + sp
    return dx, dy, sp


def shadow_entry(dx, dy, sp, color) -> str:
    parts = [px(dx), px(dy)]
    if sp:
        parts += ["0", px(sp)]
    return " ".join(parts + [color])


def _acyclic(n, edges, group_of) -> bool:
    nodes = set(group_of[i] for i in range(n))
    adj = {g: set() for g in nodes}
    for i, j in edges:
        a, b = group_of[i], group_of[j]
        if a != b:
            adj[a].add(b)
    state = {}

    def dfs(u):
        state[u] = 1
        for v in adj[u]:
            if state.get(v) == 1:
                return False
            if v not in state and not dfs(v):
                return False
        state[u] = 2
        return True

    return all(dfs(g) for g in nodes if g not in state)


def make_groups(shapes, palette, edges):
    n = len(shapes)
    group_of = list(range(n))           # group id = anchor index
    members: dict[int, list[tuple[int, tuple]]] = {}
    for k in range(n - 1, -1, -1):      # top to bottom: first seen is the anchor
        best, best_save = None, 0
        elem_cost = sum(decl_len(p, v) + 1 for p, v in shape_props(shapes[k], palette)) + 9
        for a in members.keys() | {i for i in range(k + 1, n) if group_of[i] == i}:
            if group_of[a] != a:
                continue
            sh = shadow_of(shapes[a], shapes[k])
            if sh is None:
                continue
            entry = shadow_entry(*sh, color_css(palette[shapes[k].color]))
            cost = len(entry) + 1 + (0 if members.get(a) else len("box-shadow:") + 3)
            save = elem_cost - cost
            if save <= best_save:
                continue
            trial = group_of.copy()
            trial[k] = a
            if _acyclic(n, edges, trial):
                best, best_save = (a, sh), save
        if best:
            a, sh = best
            group_of[k] = a
            members.setdefault(a, []).append((k, sh))
    return group_of, members


SHADOW_OVERHEAD = len("box-shadow:") + 1 + 2     # property, separator, quotes


def element_cost(s: Shape, palette) -> int:
    """Characters of `<b style=...>` for a shape on its own (no shared rule)."""
    e = dict(shape_props(s, palette))
    return len("<b style=>") + min(len(_style(d)) for d in size_encodings(e))


def make_groups_exact(shapes, palette, edges, time_limit=10.0):
    """Choose shadow groups and a paint order together, minimizing characters,
    with CP-SAT. Returns (group_of, members, optimal?) or None if no solution.

    Every shape is an element or a shadow of one compatible element. Each
    shape gets a paint position t; a shadow shares its anchor's t. For every
    pair that must stay in order (i below j), t[i] < t[j] unless both are in
    the same group, which rules out cycles between groups, so a valid paint
    order always exists. Within a group the shadow list can follow any order,
    but a shadow is always drawn below its anchor."""
    from ortools.sat.python import cp_model

    n = len(shapes)
    m = cp_model.CpModel()
    comp = {}                                   # (member, anchor) -> (dx, dy, spread)
    for a in range(n):
        for k in range(n):
            if a != k and (a, k) not in edges:  # a below k: k can't be a's shadow
                sh = shadow_of(shapes[a], shapes[k])
                if sh is not None:
                    comp[(k, a)] = sh
    if not comp:
        return None
    y = [m.NewBoolVar(f"y{i}") for i in range(n)]
    x = {key: m.NewBoolVar(f"x{key[0]}_{key[1]}") for key in comp}
    z = [m.NewBoolVar(f"z{i}") for i in range(n)]
    t = [m.NewIntVar(0, n - 1, f"t{i}") for i in range(n)]
    for k in range(n):
        m.AddExactlyOne([y[k]] + [x[(k, a)] for a in range(n) if (k, a) in x])
    for (k, a), v in x.items():
        m.AddImplication(v, y[a])
        m.AddImplication(v, z[a])
        m.Add(t[k] == t[a]).OnlyEnforceIf(v)
    for a in range(n):
        m.AddImplication(z[a], y[a])
    for i, j in edges:
        m.Add(t[i] <= t[j])
        same = []
        if (i, j) in x:
            same.append(x[(i, j)])
        if (j, i) in x:
            same.append(x[(j, i)])
        for a in range(n):
            if (i, a) in x and (j, a) in x:
                w = m.NewBoolVar(f"w{i}_{j}_{a}")
                m.AddImplication(w, x[(i, a)])
                m.AddImplication(w, x[(j, a)])
                same.append(w)
        if same:
            s_ij = m.NewBoolVar(f"s{i}_{j}")
            m.AddBoolOr(same).OnlyEnforceIf(s_ij)
            m.Add(t[i] + 1 <= t[j]).OnlyEnforceIf(s_ij.Not())
        else:
            m.Add(t[i] + 1 <= t[j])
    cost = [element_cost(sh, palette) * y[i] for i, sh in enumerate(shapes)]
    for (k, a), v in x.items():
        entry = shadow_entry(*comp[(k, a)], color_css(palette[shapes[k].color]))
        cost.append((len(entry) + 1) * v)
    cost += [SHADOW_OVERHEAD * z[a] for a in range(n)]
    m.Minimize(sum(cost))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 1
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    group_of = list(range(n))
    members: dict[int, list[tuple[int, tuple]]] = {}
    for (k, a), v in x.items():
        if solver.Value(v):
            group_of[k] = a
            members.setdefault(a, []).append((k, comp[(k, a)]))
    return group_of, members, status == cp_model.OPTIMAL


def paint_order(n, edges, group_of) -> list[int]:
    groups = sorted(set(group_of))
    adj = {g: set() for g in groups}
    indeg = {g: 0 for g in groups}
    for i, j in edges:
        a, b = group_of[i], group_of[j]
        if a != b and b not in adj[a]:
            adj[a].add(b)
            indeg[b] += 1
    key = {g: min(i for i in range(n) if group_of[i] == g) for g in groups}
    ready = sorted([g for g in groups if indeg[g] == 0], key=key.get)
    out = []
    while ready:
        g = ready.pop(0)
        out.append(g)
        for b in adj[g]:
            indeg[b] -= 1
            if indeg[b] == 0:
                ready.append(b)
        ready.sort(key=key.get)
    assert len(out) == len(groups), "paint-order cycle"
    return out


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def _style(decls) -> str:
    items = decls.items() if isinstance(decls, dict) else decls
    s = ";".join(f"{p}:{v}" for p, v in items)
    return f'"{s}"' if (" " in s or ">" in s) else s


def size_encodings(e: dict) -> list[dict]:
    """Equivalent ways to give an element its position and size.
    In quirks mode `padding` takes unitless lengths (even two of them), so an
    empty box sized by padding is often shorter than width + height. `inset`
    needs units but replaces all four of left/top/width/height."""
    out = [e]
    w, h = float(e["width"]), float(e["height"])
    if w % 2 == 0 and h % 2 == 0:
        pad = num(h / 2) if w == h else f"{num(h / 2)} {num(w / 2)}"
        d = {k: v for k, v in e.items() if k not in ("width", "height")}
        out.append(_insert_after(d, "top", ("padding", pad)))
    x, y = float(e["left"]), float(e["top"])
    right, bottom = W - x - w, H - y - h
    d = {k: v for k, v in e.items() if k not in ("left", "top", "width", "height")}
    out.append({"inset": " ".join(px(v) for v in (y, right, bottom, x)), **d})
    return out


def _insert_after(d: dict, key: str, item) -> dict:
    out = {}
    for k, v in d.items():
        out[k] = v
        if k == key:
            out[item[0]] = item[1]
    return out


# Transforms and clip-path apply to an element's descendants too (a transform
# also makes it their containing block), so such elements are closed at once
# unless nothing follows.
def _tag(decls: dict, e: dict, last: bool, name: str = "b") -> str:
    st = _style(decls)
    t = f"<{name}>" if not st else f"<{name} style={st}>"
    closes = "rotate" in e or "scale" in e or "clip-path" in e
    return t + (f"</{name}>" if closes and not last else "")


SHAREABLE = ["width", "height", "padding", "background", "border-radius", "left", "top", "rotate",
             "clip-path", "scale"]


def gradient_css(g: Gradient, palette) -> str:
    L = g.length()

    def pos(e, tol=0.3):
        opts = [px(e)]
        v = round(e / L * 100, 2)
        if abs(v * L / 100 - e) < tol:
            opts.append(num(v) + "%")
        return min(opts, key=len)

    # Color i runs from where boundary i-1's ramp ends to where boundary i's
    # begins; a hard boundary starts the next color at "0", which clamps to
    # the previous stop. Soft ends are placed exactly.
    n = len(g.stops)
    soft = g.soft or (0,) * (n - 1)
    parts = []
    for i, (c, e) in enumerate(g.stops):
        p = [color_css(palette[c])]
        if i > 0:
            w = soft[i - 1]
            p.append(pos(g.stops[i - 1][1] + w / 2, 0.01) if w else "0")
        if i < n - 1:
            w = soft[i]
            p.append(pos(e - w / 2, 0.01) if w else pos(e))
        parts.append(" ".join(p))
    head = "" if abs(g.angle - 180) < 1e-9 else num(g.angle) + "deg,"
    return f"linear-gradient({head}{','.join(parts)})"


def body_options(palette, bg) -> list[tuple[str, str]]:
    """Ways to paint the background: (tag before the elements, rule for the
    trailing style). Exactly one of the two is non-empty."""
    if isinstance(bg, Gradient):
        g = gradient_css(bg, palette)
        return [(f'<body style="background:{g}">', ""), ("", f"body{{background:{g}}}")]
    return [(f"<body bgcolor={bgcolor_attr(palette[bg])}>", ""),
            ("", f"body{{background:{color_css(palette[bg])}}}")]


# Tags that draw nothing of their own, so a group of elements can share one
# rule: copies of a shape at different angles or positions share their size,
# corners and color under one tag while the rest stay <b>.
TAGS = ("b", "i", "u", "s")


def _shared(elements: list[dict]) -> dict:
    """position:fixed plus every property all these elements have, set to its
    most common value when at least two of them use it."""
    shared = {"position": "fixed"}
    common = set.intersection(*(set(e) for e in elements))
    for p in SHAREABLE:
        if p not in common:
            continue
        v, k = Counter(e[p] for e in elements).most_common(1)[0]
        if k >= 2:
            shared[p] = v
    return shared


def assemble(body_opts, elements: list[dict], tags=None) -> str:
    """tags: the tag name of each element (default all <b>)."""
    n = len(elements)
    outs = []
    if n == 0:
        for tag, rule in body_opts:
            outs.append(tag if tag else "<style>" + rule[:-1])
        return min(outs, key=len)
    tags = tags or ["b"] * n
    # Option A: inline everything.
    inline = "".join(_tag({"position": "fixed", **e}, e, i == n - 1)
                     for i, e in enumerate(elements))
    # Option B: one rule per tag with position:fixed and what its elements
    # share. The style element goes last and stays unclosed, and so does its
    # last rule.
    used = [t for t in TAGS if t in tags]
    shared = {t: _shared([e for e, t2 in zip(elements, tags) if t2 == t]) for t in used}
    rules = "".join(t + "{" + ";".join(f"{p}:{v}" for p, v in shared[t].items()) + "}" for t in used)
    with_rule = "".join(
        _tag({p: v for p, v in e.items() if shared[t].get(p) != v}, e, i == n - 1, t)
        for i, (e, t) in enumerate(zip(elements, tags)))
    for tag, rule in body_opts:
        if tag:
            if len(used) == 1:
                outs.append(tag + inline)
            outs.append(tag + with_rule + "<style>" + rules[:-1])
        else:
            outs.append(with_rule + "<style>" + rule + rules[:-1])
    return min(outs, key=len)


_FAMILY_KEYS = (("width", "height", "padding", "border-radius", "background"),
                ("width", "height", "padding", "border-radius"),
                ("width", "height", "padding"), ("background",),
                ("width", "height", "clip-path", "background"), ("width", "height", "clip-path"))


def tag_options(elements: list[dict]):
    """Tag assignments worth trying: everything <b>, and for several notions
    of "same shape", the largest families of alike elements moved to their
    own tags, in every combination."""
    yield None
    seen = set()
    for keys in _FAMILY_KEYS:
        fams = {}
        for i, e in enumerate(elements):
            k = tuple(e.get(p) for p in keys)
            if any(v is not None for v in k):
                fams.setdefault(k, []).append(i)
        big = sorted((f for f in fams.values() if len(f) >= 2), key=len, reverse=True)[:len(TAGS) - 1]
        for mask in range(1, 1 << len(big)):
            tags = ["b"] * len(elements)
            for j, f in enumerate(big):
                if mask >> j & 1:
                    for i in f:
                        tags[i] = TAGS[1 + j]
            if tuple(tags) not in seen:
                seen.add(tuple(tags))
                yield tags


# How a polygon can reuse another's clip-path: (flip x, flip y, CSS scale).
FLIPS = ((False, False, None), (True, False, "-1 1"), (False, True, "1 -1"), (True, True, "-1"))


def _same_polygon(p, q) -> bool:
    """Same vertices in the same cyclic order, either direction."""
    if len(p) != len(q) or set(p) != set(q):
        return False
    n = len(p)
    k = q.index(p[0])
    return (all(p[i] == q[(k + i) % n] for i in range(n))
            or all(p[i] == q[(k - i) % n] for i in range(n)))


def reused_clip(a: Shape, b: Shape):
    """The CSS scale (or "" for none) that draws polygon b as polygon a's
    clip-path, mirrored within the same-size box, or None."""
    if not (a.poly and b.poly) or (a.w, a.h) != (b.w, b.h) or len(a.poly) != len(b.poly):
        return None
    rel = tuple((x - b.x, y - b.y) for x, y in b.poly)
    for fx, fy, scale in FLIPS:
        f = a.flipped(fx, fy)
        if _same_polygon(tuple((x - f.x, y - f.y) for x, y in f.poly), rel):
            return scale or ""
    return None


def _elements(shapes, palette, edges, group_of, members):
    order = paint_order(len(shapes), edges, group_of)
    elements = []
    clips = []                       # (shape, its clip-path) emitted so far
    for a in order:
        props = shape_props(shapes[a], palette)
        if shapes[a].poly:
            # a copy or mirror of an earlier polygon takes that polygon's
            # clip-path (and a flip), so a rule can share it
            for prev, clip in clips:
                scale = reused_clip(prev, shapes[a])
                if scale is not None:
                    props = [(p, clip if p == "clip-path" else v) for p, v in props]
                    if scale:
                        props.append(("scale", scale))
                    break
            else:
                clips.append((shapes[a], dict(props)["clip-path"]))
        sh = sorted(members.get(a, []), key=lambda t: -t[0])  # topmost shadow first
        if sh:
            props.append(("box-shadow", ",".join(
                shadow_entry(*m[1], color_css(palette[shapes[m[0]].color])) for m in sh)))
        elements.append(dict(props))
    return elements


def _code(body_opts, elements) -> str:
    if not elements:
        return assemble(body_opts, [])
    per_element = [min(size_encodings(e), key=lambda d: len(_style(d))) for e in elements]
    return min((assemble(body_opts, els, tags) for els in (per_element, elements)
                for tags in tag_options(els)), key=len)


def emit(palette, bg, shapes, grouping="best", edges=None) -> tuple[str, dict]:
    """grouping: "greedy", "exact" or "best" (both, keep the shorter code).
    edges: precomputed paint-order constraints (see precedence)."""
    if edges is None:
        edges = precedence(shapes)
    body_opts = body_options(palette, bg)
    results = {}
    if grouping in ("greedy", "best"):
        g = make_groups(shapes, palette, edges)
        results["greedy"] = (_code(body_opts, _elements(shapes, palette, edges, *g)), g, None)
    if grouping in ("exact", "best"):
        ex = make_groups_exact(shapes, palette, edges)
        if ex is not None:
            g = ex[:2]
            results["exact"] = (_code(body_opts, _elements(shapes, palette, edges, *g)), g, ex[2])
        elif grouping == "exact":
            g = (list(range(len(shapes))), {})
            results["exact"] = (_code(body_opts, _elements(shapes, palette, edges, *g)), g, None)
    name = min(results, key=lambda k: (len(results[k][0]), k != "exact"))
    code, (group_of, members), optimal = results[name]
    info = {"elements": len(set(group_of)), "shadows": sum(len(v) for v in members.values()),
            "shapes": len(shapes), "grouping": name,
            **{f"{k}_chars": len(v[0]) for k, v in results.items()}}
    if optimal is not None:
        info["exact_optimal"] = optimal
    return code, info
