"""Plan-view maps of a feature tree (tree.py JSON): top pockets by floor height,
bottom pockets by ceiling height, through-holes outlined.

usage: py -3.12 tools/feat/plot_tree.py <tree.json> <out.png>
"""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon as Patch
from matplotlib.path import Path
from matplotlib.patches import PathPatch


def path_of(ft):
    rings = [ft["profile"]["outer"]] + ft["profile"]["islands"]
    verts, codes = [], []
    for r in rings:
        verts += r + [r[0]]
        codes += [Path.MOVETO] + [Path.LINETO] * (len(r) - 1) + [Path.CLOSEPOLY]
    return Path(verts, codes)


def main(src, out):
    t = json.load(open(src))
    feats = t["features"]
    stock = [f for f in feats if f["type"] == "stock"]
    fig, axes = plt.subplots(2, 1, figsize=(16, 9))
    for ax, side, key, label in ((axes[0], "top", "z_from", "top pockets: floor height Z (mm)"),
                                 (axes[1], "bottom", "z_to", "bottom pockets: ceiling height Z (mm)")):
        fs = sorted((f for f in feats if f["type"].startswith(side)), key=lambda f: f["depth"], reverse=True)
        norm = matplotlib.colors.Normalize(t["z_bot"], t["z_top"])
        cmap = matplotlib.colormaps["viridis"]
        for s in stock:
            ax.add_patch(PathPatch(path_of(s), fc="0.92", ec="0.3", lw=0.8))
        # deeper nodes drawn last so nested pockets stay visible
        for f in sorted(fs, key=lambda f: f[key], reverse=(side == "top")):
            ax.add_patch(PathPatch(path_of(f), fc=cmap(norm(f[key])), ec="k", lw=0.25, alpha=0.9))
        for f in feats:
            if f["type"] == "through_hole":
                ax.add_patch(PathPatch(path_of(f), fc="white", ec="red", lw=0.8))
        ax.autoscale_view()
        ax.set_aspect("equal")
        ax.set_title(f"{label}  ({len(fs)} features; red = through-holes)")
        fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, fraction=0.02, label="Z (mm)")
    fig.tight_layout()
    fig.savefig(out, dpi=110)


if __name__ == "__main__":
    main(*sys.argv[1:3])
