#!/usr/bin/env python3
"""Learned motif proposals: label which proposals pay off, train a filter.

    python bench/proposals.py data --n 40 --out scratch/props.pkl    # 40 scenes per family
    python bench/proposals.py train scratch/props.pkl --model bench/proposal_model.json

At every step of the greedy search the motif library (search.best_motif)
offers compositions. The rule in the compiler takes the one that most
lowers J right after the step. That is myopic: a composition that wins its
step can still leave a worse result. Here each proposal is labeled by its
outcome instead. On scenes generated from the families (fresh seeds, never
the held-out ones), one search runs with no motifs; then, for each step
that had proposals, the search is rerun accepting one of them there and no
motif anywhere else. A proposal is good if that run's final J (after
refining and the clean-up) is lower.

A small classifier learns good proposals from features of the proposal
and the step. "train" reports how well it generalizes to families it was
not trained on (leave one family out) and saves a model for the compiler
to use as a policy (see learned_policy).
"""

import argparse
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
from cssynth import compiler, search  # noqa: E402
from cssynth.simplify import simplify  # noqa: E402

KINDS = ["seeded-mirror", "seeded-copies", "seeded-turns", "symmetric-mirror", "symmetric-turns", "nest"]
VARIANT = ((25,), 3, True, "flat", False, True)
MAX_POINTS, MAX_PER_POINT = 6, 3
FIRST_SEED = 1000            # scenes for learning; families.py uses 0.. for the dev split


def features(T, shapes, base, item):
    j, k, add, kind, total = item
    return [*(kind == x for x in KINDS), len(add), total / T.size, (j - base), (j - base) / max(base, 1),
            len(shapes), k == len(shapes), int(T.max()) + 1]


def run(arr, policy, gate=None):
    """Final J of one search variant with a motif policy."""
    search.MOTIF_POLICY, search.MOTIF_GATE = policy, gate
    min_gains, per_color, bbox, base, outlines, by_length = VARIANT
    out = search.decompose(arr, min_gains=min_gains, per_color=per_color, bbox_starts=bbox, base=base,
                           outlines=outlines, rho=compiler.RHO)
    pal, bg, T, stacks = out
    shapes = simplify(T, bg, pal, stacks[min_gains[0]], rho=compiler.RHO)
    return compiler._finish(arr, compiler.RHO, pal, bg, shapes)[0]


def label_scene(path):
    """The search runs once declining every proposal, which is the search
    without motifs, and records the steps that had any (by stack size, which
    grows every step). Each rerun looks for motifs only at its step and
    accepts the one it tests."""
    arr = np.asarray(Image.open(path).convert("RGB"))
    search.MOTIFS = {"nest", "symmetric", "seeded"}
    points = []

    def record(T, shapes, best, base, scored):
        if scored and len(points) < MAX_POINTS:
            points.append((len(shapes), [(features(T, shapes, base, it), it[0] - base)
                                         for it in scored[:MAX_PER_POINT]]))
        return None
    t = time.time()
    j0 = run(arr, record)
    rows = []
    for at, items in points:
        for i, (f, step_dj) in enumerate(items):
            def force(T, shapes, best, base, scored, i=i):
                return (scored[i][1], scored[i][2]) if i < len(scored) else None
            j = run(arr, force, gate=lambda shapes, at=at: len(shapes) == at)
            rows.append((f, j - j0, step_dj))
    return {"scene": Path(path).stem, "family": Path(path).stem.split("-")[0], "J_none": j0, "rows": rows,
            "seconds": round(time.time() - t, 1)}


def data(args):
    import families
    out_dir = Path(args.scenes)
    if not (out_dir / "cases.json").exists():
        families.build(out_dir, list(range(FIRST_SEED, FIRST_SEED + args.n)))
    paths = sorted(out_dir.glob("*.png"))
    with Pool(args.jobs) as p:
        res = p.map(label_scene, paths, chunksize=1)
    pickle.dump(res, open(args.out, "wb"))
    rows = [r for s in res for r in s["rows"]]
    good = sum(r[1] < -1e-9 for r in rows)
    print(f"{len(res)} scenes, {len(rows)} labeled proposals, {good} lower the final J")


def train(args):
    from sklearn.ensemble import GradientBoostingClassifier
    res = pickle.load(open(args.data, "rb"))
    fams = sorted({s["family"] for s in res})

    def xy(scenes):
        X = np.array([r[0] for s in scenes for r in s["rows"]], dtype=float)
        y = np.array([r[1] < -1e-9 for s in scenes for r in s["rows"]])
        step = np.array([r[2] < -1e-9 for s in scenes for r in s["rows"]])
        return X, y, step

    print(f"{'held-out family':16s} {'n':>5s} {'good':>5s}  {'learned acc':>11s} {'step rule acc':>13s} "
          f"{'learned prec':>12s} {'step prec':>9s}")
    for fam in fams:
        Xtr, ytr, _ = xy([s for s in res if s["family"] != fam])
        Xte, yte, step = xy([s for s in res if s["family"] == fam])
        if not len(Xte):
            continue
        clf = GradientBoostingClassifier(random_state=0).fit(Xtr, ytr)
        pred = clf.predict(Xte)
        prec = (pred & yte).sum() / max(pred.sum(), 1)
        sprec = (step & yte).sum() / max(step.sum(), 1)
        print(f"{fam:16s} {len(yte):5d} {yte.sum():5d}  {(pred == yte).mean():11.3f} {(step == yte).mean():13.3f} "
              f"{prec:12.3f} {sprec:9.3f}")
    X, y, _ = xy(res)
    clf = GradientBoostingClassifier(random_state=0).fit(X, y)
    pickle.dump(clf, open(args.model, "wb"))
    print(f"saved {args.model}")


def learned_policy(model_path):
    """A MOTIF_POLICY that takes the proposal the model rates most likely to
    lower the final J, if it rates it likely at all."""
    clf = pickle.load(open(model_path, "rb"))

    def policy(T, shapes, best, base, scored):
        if not scored:
            return None
        X = np.array([features(T, shapes, base, it) for it in scored], dtype=float)
        p = clf.predict_proba(X)[:, 1]
        i = int(p.argmax())
        return (scored[i][1], scored[i][2]) if p[i] > 0.5 else None
    return policy


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("data")
    d.add_argument("--n", type=int, default=40)
    d.add_argument("--scenes", default=str(ROOT / "bench" / "learn"))
    d.add_argument("--jobs", type=int, default=8)
    d.add_argument("--out", required=True)
    t = sub.add_parser("train")
    t.add_argument("data")
    t.add_argument("--model", required=True)
    args = ap.parse_args()
    {"data": data, "train": train}[args.cmd](args)


if __name__ == "__main__":
    main()
