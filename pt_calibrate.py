#!/usr/bin/env python3
"""
P/T box auto-fit CALIBRATOR (mirrors type_calibrate.py).

Drives the live CardConjurer renderer ONCE and measures what the runtime
`autofit_pt()` (automator_utils.py) needs, so that at card time it is PURE MATH
(read the P/T value, compute the box size, set it -- NO magenta, NO binary
search, NO per-card re-render at runtime):

  (1) BOX LAW        box width in DIALOG UNITS -> box width in PREVIEW px.
                     CardConjurer scale-fits a P/T that is wider than its box,
                     so the box must be at least as wide (px) as the P/T's
                     natural width for the user's {fontsize} to be honored.
  (2) GLYPH LAW      each P/T glyph (0-9, '/') measured at fontsize
                     -6,-3,0,3,6 (kerning 0) with the box wide enough to be
                     uncapped; fit to width = base + slope*fontsize.
  (3) KERNING        uniform per-gap px added per {kerning} unit.

Everything is in PREVIEW-canvas px (the first <canvas> in the DOM, ~1005 wide)
-- the SAME space the type/title autofits use -- so the numbers are directly
comparable with _SET_SYMBOL_LEFT / _TYPE_ROW_RIGHT.

All is written to pt_calib.json.  Re-run after any frame/font change.

    python pt_calibrate.py --url http://mtgproxy:4242/
"""
import argparse, json, os, sys, time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from type_calibrate import make_driver, R

GLYPHS = list("0123456789/")
# Sample the fontsize LAW over the range the P/T is ACTUALLY used at (my.conf
# runs {fontsize45}).  A wide-bracketed sweep (0..60) brackets the real value
# so the linear fit is accurate THERE, not just near fs=0.  The user's own
# {fontsize} just has to fall in the measured span for a clean reading.
FS_VALUES = [0, 20, 45, 60]
REPEAT = 8          # homogeneous run length when measuring a single glyph
SAMPLE = "12/34"    # a wide sample for the natural-vs-capacity sanity


def _pt_band(r):
    """(y0,y1) PREVIEW-canvas-px band covering the P/T box (+ ascender/shadow).
    Uses the first <canvas> in the DOM (the preview, ~1407 tall) -- the SAME
    surface r.png() (and _pt_extent) read -- NOT the native cardCanvas."""
    g = r.d.execute_script("""
        var cv=document.querySelector('canvas');
        if(!cv||!cv.width) return null;
        if(typeof card==='undefined'||!card||!card.text||!card.text.pt) return null;
        var t=card.text.pt;
        var H=cv.height;
        m=0.02*H;
        return [Math.max(0,Math.floor(t.y*H)-m), Math.min(H,Math.floor((t.y+t.height)*H)+m)];
    """)
    return tuple(g) if g else None


def _pt_extent(r, band):
    """(min_x,max_x) of strict-magenta ink in the P/T band, else None (preview px)."""
    img = r.png(); px = img.load(); W, H = img.size
    lo, hi = int(band[0]), int(band[1])
    xs = [x for y in range(lo, min(hi, H)) for x in range(W)
          if px[x, y][0] > 180 and px[x, y][2] > 180 and px[x, y][1] < 80]
    return (min(xs), max(xs)) if xs else None


def _pt_box_du_and_px(r):
    """Read the P/T box width (dialog units, from the Edit Bounds dialog) and its
    width in PREVIEW px (card.text.pt.width * preview canvas width)."""
    d = r.d
    d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
    d.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
    d.find_element(By.XPATH, "//button[contains(text(),'Edit Bounds')]").click()
    time.sleep(0.4)
    gw = int(d.find_element(By.ID, "textbox-editor-width").get_attribute("value") or 0)
    gx = int(d.find_element(By.ID, "textbox-editor-x").get_attribute("value") or 0)
    geo = d.execute_script("""
        if(typeof card==='undefined'||!card||!card.text||!card.text.pt) return null;
        var cv=document.querySelector('canvas');
        var t=card.text.pt;
        return {W: cv.width, w: t.width, x: t.x};
    """)
    d.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click(); time.sleep(1.0)
    px_w = int(geo["w"] * geo["W"]) if geo else None
    return gw, gx, px_w


def _set_pt_box(r, base_du, base_x, target_du):
    """Set the P/T box width to `target_du` (dialog units) holding the RIGHT edge
    (shift x left by the added width).  `base_du`/`base_x` are the original box."""
    d = r.d
    d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
    d.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
    d.find_element(By.XPATH, "//button[contains(text(),'Edit Bounds')]").click()
    time.sleep(0.4)
    def sv(id, val):
        inp = d.find_element(By.ID, id); inp.clear()
        inp.send_keys(str(int(val))); inp.send_keys(Keys.RETURN); time.sleep(0.3)
    sv("textbox-editor-width", max(target_du, base_du))
    sv("textbox-editor-x", max(0, base_x - (max(target_du, base_du) - base_du)))
    d.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click(); time.sleep(1.2)


def fit_line(pts):
    """Least-squares y = base + slope*x; returns (base, slope, max_residual)."""
    n = len(pts)
    if n == 1:
        return pts[0][1], 0.0, 0.0
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts); sxy = sum(p[0] * p[1] for p in pts)
    den = n * sxx - sx * sx
    if den == 0:
        base = sy / n
        return base, 0.0, max(abs(p[1] - base) for p in pts)
    slope = (n * sxy - sx * sy) / den
    base = (sy - slope * sx) / n
    resid = max(abs((base + slope * p[0]) - p[1]) for p in pts)
    return base, slope, resid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://mtgproxy:4242/")
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--frame", default="Seventh")
    ap.add_argument("--out", default="pt_calib.json")
    a = ap.parse_args()

    r = R(make_driver(a.url, headless=not a.no_headless), a.url)
    r.set_frame(a.frame)
    PREW, _ = r.png().size
    band = _pt_band(r)
    if band is None:
        print("  FAIL: no P/T box (card.text.pt) for frame %r" % a.frame, file=sys.stderr)
        r.d.quit(); return
    print(f"preview canvas {PREW}px wide  frame='{a.frame}'  P/T band={band}")

    def set_pt(fs, kern, text):
        r.set_field("Power/Toughness",
                    f"{{fontsize{fs}}}{{kerning{k}}}{{fontcolor#FF00FF}}{text}")

    # ---- 0. Original box as the base (dialog units + preview px) ----------
    base_du, base_x, base_px = _pt_box_du_and_px(r)
    print(f"\nbase P/T box = {base_du}du ~= {base_px}px (preview)")
    if not base_du or not base_px:
        print("  FAIL: could not read the P/T box width.", file=sys.stderr)
        r.d.quit(); return

    # ---- 1. BOX LAW: du -> preview px (capacity) --------------------------
    print("\n=== box law (du -> preview px) ===")
    px_by_du = []
    for target in [2.0, 3.0, 4.0, 6.0]:
        du = int(base_du * target)
        _set_pt_box(r, base_du, base_x, du)
        _, _, pxw = _pt_box_du_and_px(r)
        if pxw:
            px_by_du.append((du, pxw))
            print(f"  {du}du -> {pxw}px   (px/du {pxw/du:.4f})")
    (du1, p1), (du2, p2) = px_by_du[0], px_by_du[-1]
    k = (p2 - p1) / (du2 - du1) if du2 != du1 else (p1 / du1 or 0.0)
    c = p1 - k * du1
    print(f"  FIT  box_px = {k:.4f}*du {c:+.2f}    (px_per_du={k:.4f})")

    # ---- 2. GLYPH WIDTH LAW, box wide enough to be uncapped --------------
    # Digits 0-9 are measured as a homogeneous run: width('g'*n) / n.
    # '/' alone sometimes renders as zero ink (CardConjurer treats a lone
    # slash oddly), so we derive w('/') from the pair:
    #     width("11")  = 2 * w('1')
    #     width("1/1") = 2 * w('1') + w('/')         (single gap)
    #     ->  w('/') = width("1/1") - 2 * w('1')
    uncapped_du = int(base_du * 6)
    _set_pt_box(r, base_du, base_x, uncapped_du)
    time.sleep(1.2)
    print(f"\n=== per-glyph width law (P/T font, box={uncapped_du}du uncapped) ===")
    width = {g: {} for g in GLYPHS}
    for fs in FS_VALUES:
        # digits: homogeneous run
        for g in "0123456789":
            set_pt(fs, 0, g * REPEAT)
            e = _pt_extent(r, band)
            width[g][fs] = (e[1] - e[0]) / REPEAT if e else None
            print(f"  '{g}' fs={fs:>2}  w/char={width[g][fs]}")
        # slash: paired with '1'.  extent("1/1") - extent("11") == slash
        # advance (the two '1's contribute identically to both inks, so their
        # bearing cancels).  NO halving -- the diff isolates the slash alone.
        # (Verify: extent("11") = adv1 + w1_ink; extent("1/1") = adv1 + adv_slash
        #  + w1_ink;  difference = adv_slash.)
        set_pt(fs, 0, "11");   e11  = _pt_extent(r, band)
        set_pt(fs, 0, "1/1");  e1l1 = _pt_extent(r, band)
        if e11 and e1l1:
            w_slash = (e1l1[1] - e1l1[0]) - (e11[1] - e11[0])
            width['/'][fs] = w_slash
            print(f"  '/' fs={fs:>2}  width('11')={e11[1]-e11[0]:>5}  "
                  f"width('1/1')={e1l1[1]-e1l1[0]:>5}  w/char={w_slash:.4f}")
        else:
            width['/'][fs] = None
            print(f"  '/' fs={fs:>2}  (could not measure via pair)")
    glyphs = {}
    for g in GLYPHS:
        pts = [(fs, width[g][fs]) for fs in FS_VALUES if width[g][fs] is not None]
        if not pts:
            print(f"  SKIP '{g}' (no measurements)")
            continue
        b, s, res = fit_line(pts)
        flag = "   NON-LINEAR (residual>1.5px)" if res > 1.5 else ""
        print(f"  FIT '{g}'  base={b:.2f}  slope={s:.4f}  maxresid={res:.2f}{flag}")
        glyphs[g] = {"base": round(b, 4), "slope": round(s, 4), "residual": round(res, 4)}

    # ---- KERNING (per-gap, uniform) ---------------------------------------
    # CardConjurer's {kerning} is a per-gap nudge that SCALES WITH FONT SIZE --
    # at fs=0 it is ~0 (confirmed by the earlier run), at the real fontsize it
    # is a positive px/gap.  Measure it AT a real fontsize so the runtime
    # formula  width = sum(base+slope*fs) + kern * kern_per_gap * (n-1)
    # is correct there.  We use a 3-glyph run "111" (2 gaps) for stability.
    KERN_FS = max(FS_VALUES)          # measure at the largest sampled fs
    KERN_STEP = 4                     # {kerning} unit to step by
    def w_of(text): 
        e = _pt_extent(r, band); return (e[1]-e[0]) if e else None
    # reset box to uncapped (may have been left at an earlier width)
    set_pt(KERN_FS, 0, "111"); wk0 = w_of("111")
    set_pt(KERN_FS, KERN_STEP, "111"); wk4 = w_of("111")
    kpg = 0.0
    if wk0 is not None and wk4 is not None:
        kpg = (wk4 - wk0) / KERN_STEP / 2      # 2 gaps in "111"
    print(f"\n=== kerning@fs{KERN_FS} ===  '111'@k0={wk0}  @k{KERN_STEP}={wk4}  "
          f"-> per_gap={kpg:.4f} px/gap/kerning-unit")

    # ---- CROSS-CHECK: additive model vs real strings at the real fs -------
    # Predict width(P/T) = per-char (fs0 base + fs-scale) from the per-glyph
    # table, at TWO real P/T strings of different glyph mixes, and compare to
    # the measured full-string extent.  This validates additivity AND the
    # (halved) slash term in one shot.
    CHECKS = ["3/4", "12/12"]
    def predict(text):
        tot = 0.0
        for ch in text:
            entry = width.get(ch) or {}
            b = entry.get(FS_VALUES[0])
            s = (entry.get(fs) for fs in FS_VALUES if entry.get(fs) is not None)
            # just read the fs0 base + fs-scaled width from the table if present:
            if ch in glyphs:
                tot += glyphs[ch]["base"] + glyphs[ch]["slope"] * 0
        return tot
    print(f"\n=== cross-check (model vs measured, at fontsize {KERN_FS}) ===")
    # build the same model the runtime uses from the glyph table
    for t in CHECKS:
        set_pt(KERN_FS, 0, t); m = w_of(t)
        if m is None:
            continue
        tot = 0.0
        ok = True
        for ch in t:
            if ch in glyphs:
                # width at this fs from the per-char table (fs-scaled):
                # approximate using fs-linear: base + slope*fs
                tot += glyphs[ch]["base"] + glyphs[ch]["slope"] * KERN_FS
            else:
                tot = 0.0; ok = False
        if ok:
            print(f"  '{t}'  predicted={tot:6.1f}px  measured={m:6}px   "
                  f"err={m-tot:+5.1f}px")

    # ---- 4. Sanity --------------------------------------------------------
    nat0 = sum(glyphs.get(c, {}).get("base", 0.0) for c in SAMPLE)
    cap0 = k * base_du + c
    print(f"\n=== sanity ===  '{SAMPLE}' natural@fs0 ~{nat0:.0f}px vs base-box "
          f"capacity {cap0:.0f}px  -> needs ~{(nat0 - c) / k:.0f}du "
          f"(base {base_du}du)")

    out = {
        "frame": a.frame, "preview_w": PREW, "base_box_du": base_du,
        "base_box_px": base_px, "px_per_du": round(k, 5), "du_offset": round(c, 3),
        "glyphs": glyphs, "kern_per_gap": round(kpg, 4), "fit": px_by_du,
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), a.out)
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  wrote {a.out}")
    r.d.quit()


if __name__ == "__main__":
    main()
