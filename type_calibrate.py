#!/usr/bin/env python3
"""
Type-line auto-fit CALIBRATOR (mirrors title_calibrate.py).

Drives the live CardConjurer renderer and, for a SHORT sample type line (so it
never hits the row cap), sweeps a grid of ({fontsize}, {kerning}) tags, tints
the type magenta, waits for the canvas to settle and measures exact pixels.
From that it:

  * solves the real width law  width = A*{fontsize} + C*{kerning} + B
  * measures the {left} gain (px shifted per {left} unit)
  * measures the type-row right cap (very long type line)
  * measures the set-symbol left edge (so autofit can reserve its room)

and prints drop-in per-character constants for autofit_type() in
automator_utils.py (the same hand-transcription step as title_calibrate.py).

Run with a reachable CardConjurer instance:
    python type_calibrate.py --url http://mtgproxy:4242/
"""
import argparse, io, time, base64, json, os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select
from PIL import Image

MARGIN = 0  # safety: treat "fits" as type_right <= boundary - MARGIN px

TYPE_TOP, TYPE_BOT = 0.53, 0.66  # fraction of card height for the type band

def make_driver(url, headless=True):
    o = Options()
    if headless: o.add_argument("--headless")
    o.add_argument("--incognito"); o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage"); o.add_argument("--window-size=1280,900")
    d = webdriver.Chrome(options=o)
    d.get(url); time.sleep(3)
    try:
        d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.8)
    except Exception:
        pass
    return d


class R:
    def __init__(self, d, url): self.d = d; self.url = url
    def _ensure(self):
        try:
            self.d.execute_script("return 1")
        except Exception:
            print("  [recover] tab died, re-driving...")
            try: self.d.quit()
            except Exception: pass
            self.d = make_driver(self.url, headless=True)
            time.sleep(1)
    def png(self):
        self._ensure()
        url = self.d.execute_script("return document.querySelector('canvas').toDataURL('image/png');")
        return Image.open(io.BytesIO(base64.b64decode(url.split(",",1)[1]))).convert("RGB")
    def set_field(self, name, value):
        self._ensure()
        try:
            self.d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
        except Exception:
            pass
        self.d.find_element(By.XPATH, f"//h4[text()='{name}']").click(); time.sleep(0.3)
        ta = self.d.find_element(By.ID, "text-editor")
        self.d.execute_script("arguments[0].value=arguments[1];", ta, value)
        self.d.execute_script("arguments[0].dispatchEvent(new Event('input'));"
                              "arguments[0].dispatchEvent(new Event('change'));", ta)
        time.sleep(1.0)
    def set_frame(self, name):
        self.d.find_element(By.XPATH, "//h3[text()='Frame']").click(); time.sleep(0.5)
        try:
            Select(self.d.find_element(By.ID, "autoFrame")).select_by_value(name); time.sleep(1.0)
        except Exception as e:
            print(f"  frame select failed ({e}); continuing on current frame")
        try:
            self.d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.3)
        except Exception:
            pass
    def set_symbol(self, code, rarity, source):
        """Drive the 'Set Symbol' tab exactly like symbol_mixin.set_set_symbol()."""
        self.d.find_element(By.XPATH, "//h3[text()='Set Symbol']").click(); time.sleep(0.5)
        def setv(id, v):
            el = self.d.find_element(By.ID, id)
            self.d.execute_script("arguments[0].value=arguments[1];", el, v)
            self.d.execute_script("arguments[0].dispatchEvent(new Event('input'));", el)
        setv("set-symbol-code", code)
        try: setv("set-symbol-rarity", rarity)
        except Exception: pass
        try: setv("set-symbol-source", source)
        except Exception: pass
        self.d.execute_script("fetchSetSymbol();"); time.sleep(2.5)


def type_band(img):
    H = img.size[1]
    return int(H * TYPE_TOP), int(H * TYPE_BOT)


def magenta_extent(img):
    """(min_x, max_x) of strict-magenta pixels in the type band, else None."""
    px = img.load(); W, H = img.size
    lo, hi = type_band(img)
    xs = [x for y in range(lo, hi) for x in range(W)
          if px[x, y][0] > 180 and px[x, y][2] > 180 and px[x, y][1] < 80]
    return (min(xs), max(xs)) if xs else None


def symbol_left_edge(img, min_x_frac=0.68):
    """Leftmost saturated (colored, non-gray, non-black) pixel in the type band
    past min_x_frac of the width -- i.e. the set symbol's left edge."""
    px = img.load(); W, H = img.size
    lo, hi = type_band(img)
    start = int(W * min_x_frac)
    best = None
    for y in range(lo, hi):
        for x in range(start, W):
            r, g, b = px[x, y]
            if (max(r, g, b) - min(r, g, b)) > 40 and (r + g + b) > 180:
                if best is None or x < best:
                    best = x
                break
    return best


def glyph_widths(r, glyphs, n=8):
    """Measure the rendered advance of each printable glyph in `glyphs`.

    Renders N copies of a single letter, tinted magenta, in the Type field and
    reads the pixel extent; the per-glyph advance is extent / N (at
    fontsize 0 / kerning 0 where the tags are consumed by the parser and only
    the glyphs are visible).  Repeating IDENTICAL letters gives identical
    inter-glyph gaps, so extent = N * advance -- no cross-glyph kerning to
    confound the fit, and no cross-character averaging as with per-class
    widths.  A ' ' (space) has no visible ink and is returned as None; the
    autofit falls back to its class-based space width in that case.

    Returns {glyph: advance_px} for glyphs that rendered, {} on failure.
    """
    out = {}
    SKIP = set(' {[]()<>/*"\'')          # markup / invisible chars that would be
                                          # parsed as tags or have no ink
    for g in glyphs:
        if not g.isprintable() or g in "\n\t " or g in SKIP:
            continue
        r.set_field("Type", "{fontsize0}{kerning0}{fontcolor#FF00FF}" + g * n)
        e = magenta_extent(r.png())
        adv = (e[1] - e[0]) / n if e else None
        if adv is not None and adv > 0:
            out[g] = adv
            print(f"  '{g}' x{n} extent={e} -> advance {adv:.2f} px")
        else:
            print(f"  '{g}' x{n} extent={e} -> (no ink, skipped)")
    return out


def lstsq3(pts):
    """Solve width = a*fs + c*kern + b for points [(fs, kern, width)]."""
    A = [[p[0], p[1], 1.0] for p in pts]; Y = [float(p[2]) for p in pts]; n = len(pts)
    M = [[sum(A[i][j]*A[i][m] for i in range(n)) for m in range(3)] for j in range(3)]
    b = [sum(A[i][j]*Y[i] for i in range(n)) for j in range(3)]
    for c in range(3):
        r = max(range(c, 3), key=lambda rr: abs(M[rr][c]))
        M[c], M[r] = M[r], M[c]; b[c], b[r] = b[r], b[c]
        for rr in range(3):
            if rr != c and M[rr][c]:
                f = M[rr][c] / M[c][c]
                M[rr] = [M[rr][i] - f*M[c][i] for i in range(3)]
                b[rr] -= f * b[c][c]
    return [b[i]/M[i][i] for i in range(3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://mtgproxy:4242/")
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--frame", default="Seventh")
    ap.add_argument("--sample", default="Dragon Wizard",
                    help="Short sample type line that never hits the row cap.")
    ap.add_argument("--out", default="type_calib.json")
    a = ap.parse_args()

    r = R(make_driver(a.url, headless=not a.no_headless), a.url)
    r.set_frame(a.frame)
    W, H = r.png().size
    print(f"canvas {W}x{H}  frame='{a.frame}'  sample={a.sample!r}")

    SAMPLE = a.sample
    N = len(SAMPLE)
    FONTS = [-8, -4, 0, 4, 8]
    KERNS = [-4, 0, 4, 8]

    # --- 1. Width law (short sample, never capped) ---
    print("\n=== type width law ===")
    pts = []
    for f in FONTS:
        for k in KERNS:
            r.set_field("Type", f"{{fontsize{f}}}{{kerning{k}}}{{fontcolor#FF00FF}}{SAMPLE}")
            e = magenta_extent(r.png())
            if e:
                pts.append((f, k, e[1]-e[0]))
                print(f"  fs={f:>3} kern={k:>3}  left={e[0]:>4} width={e[1]-e[0]:>4}")
            else:
                print(f"  fs={f:>3} kern={k:>3}  (no magenta detected)")
    if len(pts) < 3:
        print("  too few points; widening the sweep would help but skipping fit.")
        a_fs = c_kern = b0 = 0.0
    else:
        a_fs, c_kern, b0 = lstsq3(pts)
    print(f"  FIT ({len(pts)} pts)  width = {a_fs:.3f}*fs {c_kern:+.3f}*kern {b0:.2f}")
    print(f"  per-char (N={N}): base={b0/N:.4f} fs={a_fs/N:.4f} kern={c_kern/N:.4f}")

    # origin (left edge at default tags)
    r.set_field("Type", f"{{fontsize0}}{{kerning0}}{{fontcolor#FF00FF}}{SAMPLE}")
    e0 = magenta_extent(r.png())
    origin = e0[0] if e0 else None

    # --- 2. {left} gain (px shifted per {left} unit) ---
    r.set_field("Type", f"{{fontsize0}}{{kerning0}}{{fontcolor#FF00FF}}{SAMPLE}")
    l0 = magenta_extent(r.png())[0]
    r.set_field("Type", f"{{fontsize0}}{{kerning0}}{{left40}}{{fontcolor#FF00FF}}{SAMPLE}")
    l40 = magenta_extent(r.png())[0]
    left_gain = (l0 - l40) / 40.0
    print(f"\n=== left gain ===\n  left0={l0} left40={l40} gain={left_gain:.4f} px/unit")

    # --- 3. Type-row right cap (very long type) ---
    r.set_field("Type", "{fontsize0}{kerning0}{fontcolor#FF00FF}"
                + "Legendary Creature - Dragon, Wizard, Cleric, Human, Beast")
    ec = magenta_extent(r.png())
    row_cap = ec[1] if ec else None
    print(f"\n=== type-row right cap ===\n  very-long-type right = {row_cap}  (extent={ec})")

    # --- 4. Set-symbol left edge (drive the real Set Symbol tab) ---
    sym_left = None
    print("\n=== set symbol left edge ===")
    for cfg in [("uds", "r", "hexproof"), ("mtg", "u", "hexproof"),
                ("ecc", "r", "cardconjurer"), ("mtg", "u", "cardconjurer")]:
        code, rar, src = cfg
        r.set_field("Type", "{fontcolor#FF00FF}Elf")
        try:
            r.set_symbol(code, rar, src)
        except Exception as ex:
            print(f"  {code:4}/{rar:1}/{src:12} fetch-fail ({ex})")
            continue
        sl = symbol_left_edge(r.png())
        print(f"  code={code:4} rarity={rar}  src={src:12}  symbol_left={sl}")
        if sl is not None and (sym_left is None or sl < sym_left):
            sym_left = sl

    # --- 5. Per-glyph base advances (emit type_glyphs.json for autofit_type) ---
    print("\n=== per-glyph advances ===")
    GLYPHS = (list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
              + list("abcdefghijklmnopqrstuvwxyz")
              + list("0123456789")
              + ["-", "\u2014", ",", "(", ")", "/"])
    glyph_table = glyph_widths(r, sorted(set(GLYPHS)))
    print(f"  measured {len(glyph_table)} glyph advances")

    # Write the per-glyph advance table (autofit_type loads this at runtime so
    # it can SUM a given type line's widths instead of using per-class averages).
    table_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "type_glyphs.json")
    with open(table_path, "w") as f:
        json.dump(glyph_table, f, indent=2)
    print(f"  wrote {table_path}")

    out = dict(
        frame=a.frame, sample=SAMPLE, chars=N, canvas=[W, H],
        law=dict(fs=a_fs, kern=c_kern, base=b0,
                 per_char=dict(base=b0/N, fs=a_fs/N, kern=c_kern/N)),
        origin=origin,
        left_gain=left_gain,
        row_cap=row_cap,
        set_symbol_left=sym_left,
        glyph_table=glyph_table,
        pts=[[f, k, w] for (f, k, w) in pts],
    )
    with open(a.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  wrote {a.out}")
    r.d.quit()


if __name__ == "__main__":
    main()
