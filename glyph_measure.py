#!/usr/bin/env python3
"""
Shared per-character width measurement for title_calibrate.py and
type_calibrate.py.

The autofit width model is  width(text) = sum over characters w(ch)  where
w(ch) is a per-character pixel width.  For a glyph g we measure w(g) by
rendering a homogeneous run of n copies and dividing the ink extent by n:

    w(g) = extent(g x n) / n        (same as the old type_glyphs.json model,
                                     which tracks the renderer to within ~2px)

w(g) is then measured at fontsize -6,-3,0,3,6 (kerning 0) and least-squares
fit to

    w(g, fs) = base + slope * fs

so the autofit can evaluate a card's exact (fontsize, kerning) rather than
assume a single per-character base.  The max residual is reported to flag a
glyph that is clearly non-linear across the sweep (would need more sample
points).  Kerning is a separate UNIFORM field-wide coefficient (assumed equal
per character), measured once per field and stored alongside.

Space has no ink, so w(' ') is derived from an anchor letter A:
    extent("A A") = 2*w(A) + w(space)   ->   w(space) = extent("A A") - 2*w(A)

Returned table:
{
  "kern_per_gap": px added per gap (between adjacent chars) per {kerning} unit
                  (uniform across the field),
  "glyphs": {glyph: {"base": px, "slope": px per fontsize unit,
                     "residual": max |fit - measured| px,
                     "pts": [[fontsize, width_px], ...]}, ...},
}
"""

FS_VALUES = [-6, -3, 0, 3, 6]

# Letters + the common type/name symbols.  NOT the full ASCII block.
#  ',' '-' em-dash are in today's type_glyphs.json;  '"' "'" '`' '.' are the
#  additions.  Space is measured separately (no ink); markup {} <> [] are not
#  included because the renderer parses them as tags.
GLYPHS = (list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
          + list("abcdefghijklmnopqrstuvwxyz")
          + list("0123456789")
          + ["\u2014", "-", ",", ".", "'", "\"", "`"])

ANCHOR = "A"          # anchor letter used to derive the space width


def fit_line(pts):
    """Least-squares fit y = base + slope*x for points [(x, y)].
    Returns (base, slope, max_abs_residual)."""
    n = len(pts)
    if n == 1:
        return pts[0][1], 0.0, 0.0
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    den = n * sxx - sx * sx
    if den == 0:
        base = sy / n
        return base, 0.0, max(abs(p[1] - base) for p in pts)
    slope = (n * sxy - sx * sy) / den
    base = (sy - slope * sx) / n
    resid = max(abs((base + slope * p[0]) - p[1]) for p in pts)
    return base, slope, resid


def _extent_px(extent, take_img):
    e = extent(take_img())
    return (e[1] - e[0]) if e else None


def measure_glyph_table(set_field, take_img, extent,
                        fs_values=FS_VALUES, n=8, anchor=ANCHOR):
    """Drive the renderer and measure per-character widths at each fontsize.

    Args:
      set_field(text): set the field to `text` VERBATIM.
      take_img():  return the current canvas image (PIL, RGB).
      extent(img): return (min_x, max_x) of the magenta ink, else None.

    Returns the table dict documented in the module docstring.
    """
    visible = [g for g in dict.fromkeys(GLYPHS) if g != " "]
    width = {g: {} for g in visible}     # g -> {fs: per-char width px}
    width[" "] = {}

    def tag_of(fs):
        return f"{{fontsize{fs}}}{{kerning0}}{{fontcolor#FF00FF}}"

    for fs in fs_values:
        tag = tag_of(fs)
        for g in visible:
            set_field(tag + g * n)
            e = _extent_px(extent, take_img)
            width[g][fs] = e / n if e is not None else None
            print(f"  '{g}' fs={fs:>2}  extent={e}  w/char={width[g][fs]}")
        # space width from the anchor: extent("A A") = 2*w(A) + w(space)
        if anchor in width:
            set_field(tag + f"{anchor} {anchor}")
            e_aa = _extent_px(extent, take_img)
            wa = width[anchor].get(fs)
            if e_aa is not None and wa is not None:
                ws = e_aa - 2 * wa
                width[" "][fs] = ws if ws > 0 else None
                print(f"  ' '  fs={fs:>2}  extent('A A')={e_aa}  "
                      f"w(A)={wa:.2f}  space={ws:.2f}")
            else:
                width[" "][fs] = None
        else:
            width[" "][fs] = None
            print(f"  ' '  fs={fs:>2}  (anchor '{anchor}' not in set)")

    table_glyphs = {}
    for g in visible + [" "]:
        pts = [(fs, width[g][fs]) for fs in fs_values if width[g][fs] is not None]
        if not pts:
            continue
        base, slope, resid = fit_line(pts)
        flag = "   NON-LINEAR (residual>1.5px; add sample points)" if resid > 1.5 else ""
        print(f"  FIT  '{g}'  base={base:.2f}  slope={slope:.4f} px/fs"
              f"  maxresid={resid:.2f}{flag}")
        table_glyphs[g] = {"base": round(base, 4), "slope": round(slope, 4),
                           "residual": round(resid, 4),
                           "pts": [[fs, round(width[g][fs], 4)] for fs in width[g]
                                   if width[g][fs] is not None]}
    return {"glyphs": table_glyphs}


def measure_uniform_kern(set_field, take_img, extent, sample, kern=4):
    """Measure the field-wide kerning coefficient: px added PER GAP (between
    adjacent glyphs) per {kerning} unit.  Kerning is assumed UNIFORM (the same
    px/gap on every adjacent pair), so it is one field-wide number:

        width_kern = kern * kern_per_gap * (len(sample) - 1)

    We measure the slope directly (kerning 0 vs kerning `kern`) and divide by
    (kern * (n-1)) so that the returned value plugs exactly into that formula.

    Returns px-per-gap-per-kerning-unit, or 0.0 on failure.
    """
    if not sample or len(sample) < 2:
        return 0.0
    set_field(f"{{kerning0}}{{fontcolor#FF00FF}}{sample}")
    w0 = _extent_px(extent, take_img)
    set_field(f"{{kerning{kern}}}{{fontcolor#FF00FF}}{sample}")
    wk = _extent_px(extent, take_img)
    if w0 is None or wk is None:
        print(f"  [kern] could not measure ('{sample}' w0={w0} wk={wk})")
        return 0.0
    n_gaps = len(sample) - 1
    per_gap = (wk - w0) / kern / n_gaps
    print(f"  [kern] sample={sample!r} gaps={n_gaps} w0={w0:.2f} wk={wk:.2f}"
          f"  -> {per_gap:.4f} px/gap/kerning-unit")
    return round(per_gap, 4)


def write_table(table, path):
    import json
    with open(path, "w") as f:
        json.dump(table, f, indent=2)
    print(f"  wrote {path}  ({len(table.get('glyphs', {}))} glyphs)")
