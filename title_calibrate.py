#!/usr/bin/env python3
"""
Title auto-fit CALIBRATOR.

Drives the live CardConjurer renderer, puts real card names in the Title bar
and real Scryfall mana costs in the Mana Cost bar, captures the canvas bitmap
and measures ACTUAL rendered pixels.  From that it:

  * solves the real width law  width = A*abs_font_px + B + C*kerning_px
  * measures each mana cost's real left-edge (its width on the bar)
  * reports the exact (fontsize, kerning) that just-fits vs. overflows for
    every name, and prints drop-in constants for autofit_title().

Run with a reachable CardConjurer instance:
    python title_calibrate.py --url http://mtgproxy:4242/
"""
import argparse, io, time, base64, json, re, os, sys
from collections import Counter
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from PIL import Image

MARGIN = 0  # safety: treat "fits" as name_right <= cost_left - MARGIN px

def make_driver(url, headless=True):
    o = Options()
    if headless: o.add_argument("--headless")
    o.add_argument("--incognito"); o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage"); o.add_argument("--window-size=1280,900")
    d = webdriver.Chrome(options=o)
    d.get(url); time.sleep(3)
    d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(1)
    return d

class R:
    def __init__(self, d, url): self.d = d; self.url = url
    def _ensure(self):
        # recover from a crashed tab by re-driving to the Text panel
        try:
            self.d.execute_script("return 1")
        except Exception:
            print("  [recover] tab died, re-driving...")
            try: self.d.quit()
            except Exception: pass
            self.d = make_driver(self.url)
            time.sleep(1)
    def set(self, name, value):
        self._ensure()
        self.d.find_element(By.XPATH, f"//h4[text()='{name}']").click(); time.sleep(0.35)
        ta = self.d.find_element(By.ID, "text-editor")
        self.d.execute_script("arguments[0].value=arguments[1];", ta, value)
        self.d.execute_script("arguments[0].dispatchEvent(new Event('input'));arguments[0].dispatchEvent(new Event('change'));", ta)
        time.sleep(0.15)
    def png(self):
        self._ensure()
        url=self.d.execute_script("return document.querySelector('canvas').toDataURL('image/png');")
        return Image.open(io.BytesIO(base64.b64decode(url.split(",",1)[1]))).convert("RGB")
    # name extent measured with the name rendered ALONE (no cost)
    def name_width(self, name, font, kern):
        if not name:
            return None
        self.set("Title", f"{{fontcolor#FF00FF}}{{fontsize{font}}}{{kerning{kern}}}{name}")
        self.set("Mana Cost", ""); self.set("Rules Text",""); time.sleep(0.9)
        img=self.png(); W,H=img.size; px=img.load()
        def is_mag(p): r,g,b=p; return r>150 and b>150 and g<150
        # union of magenta over the whole name-bar band -> robust to thin rows
        xs=[x for y in range(60,200) for x in range(0,W) if is_mag(px[x,y])]
        if not xs: return None
        lo,hi=min(xs),max(xs)
        return dict(n_left=lo, n_right=hi, w=(hi-lo))
    # cost left edge with the name EMPTY (no overlap ambiguity)
    def cost_span(self, cost):
        self.set("Title",""); self.set("Mana Cost", cost); self.set("Rules Text",""); time.sleep(0.9)
        img=self.png(); W,H=img.size; px=img.load()
        best=None
        for y in range(70,170):
            ink=[x for x in range(W) if px[x,y]!=(0,0,0)]
            if ink and (best is None or len(ink)>best[0]):
                best=(len(ink),y,min(ink),max(ink))
        if not best: return None
        return dict(c_left=best[2], c_right=best[3], c_w=(best[3]-best[2]), y=best[1])

def title_magenta_extent(img):
    """(min_x, max_x) of magenta ink in the name-bar band, else None."""
    W, H = img.size; px = img.load()
    def is_mag(p): r,g,b=p; return r>150 and b>150 and g<150
    xs=[x for y in range(60,200) for x in range(W) if is_mag(px[x,y])]
    return (min(xs), max(xs)) if xs else None
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--url", default="http://mtgproxy:4242/")
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--out", default="title_calib.json")
    a=ap.parse_args()

    r=R(make_driver(a.url, headless=not a.no_headless), a.url)
    NAMES=["Rofellos, Llanowar Emissary"]
    COSTS=["{W}{W}","{2}{W}","{X}{X}{2}{W}","{W}{U}{B}{R}{G}"]
    FONTS=[-15,-5,5,15]   # --title-font-size values to sweep
    KERNS=[-4,4,12]       # --title-kerning values to sweep

    print("=== per-cost span (name empty) ===")
    cost_info={}
    for c in COSTS:
        s=r.cost_span(c); cost_info[c]=s
        print(f"  {c:16} left={s['c_left']} right={s['c_right']} width={s['c_w']}" if s else f"  {c:16} NOT MEASURED")

    print("\n=== name width grid (name alone) ===")
    data={}
    for name in NAMES:
        data[name]={}
        for k in KERNS:
            for f in FONTS:
                w=r.name_width(name,f,k)
                data[name][(f,k)]=w
        # table
        print(f"\n  name='{name}'  (n_left ~ {data[name][(0,0)]['n_left'] if (0,0) in data[name] else 'n/a'})")
        hdr="font\\kern " + " ".join(f"{k:>7}" for k in KERNS)
        print("  "+hdr)
        for f in FONTS:
            row=f"{f:10}"+" ".join(f"{(data[name][(f,k)]['w'] if data[name][(f,k)] else ' . '):>7}" for k in KERNS)
            print("  "+row)

    # Solve the width law  width = a*fontsize + c*kerning + b  via least squares
    # over the cells that are NOT capped by the title box, for one name.
    def fit_law(grid):
        cells = [(f, k, w['w']) for (f, k), w in grid.items() if w['w'] < 818]  # skip capped
        n = len(cells)
        M = [[sum(cells[i][j] * cells[i][m] for i in range(n)) for m in range(3)] for j in range(3)]
        b = [sum(cells[i][j] * cells[i][2] for i in range(n)) for j in range(3)]
        M = [[1.0 * x for x in row] for row in M]
        A = [[x[0], x[1], 1.0] for x in cells]
        M = [[sum(A[i][j] * A[i][m] for i in range(n)) for m in range(3)] for j in range(3)]
        b = [sum(A[i][j] * cells[i][2] for i in range(n)) for j in range(3)]
        for col in range(3):
            p = max(range(col, 3), key=lambda r: abs(M[r][col])); M[col], M[p] = M[p], M[col]; b[col], b[p] = b[p], b[col]
            for r in range(3):
                if r != col and abs(M[r][col]) > 1e-12:
                    f_ = M[r][col] / M[col][col]
                    M[r] = [M[r][c] - f_ * M[col][c] for c in range(3)]; b[r] -= f_ * b[col]
        sol = [b[i] / M[i][i] for i in range(3)]
        return sol[0], sol[1], sol[2], n

    a_coef, c_coef, b0, npts = fit_law(data[NAMES[0]])
    name0 = NAMES[0]
    print(f"\n  FIT (excl. capped cells, {npts} pts)  width = {a_coef:.2f}*fontsize + {c_coef:.2f}*kerning + {b0:.0f}")
    per_char = len(name0)
    print(f"  name chars = {per_char}  -> per-char base={b0/per_char:.3f} "
          f"fs={a_coef/per_char:.4f} kern={c_coef/per_char:.4f}")

    # name origin (where the default, left=0 name starts)
    no = next((w['n_left'] for w in data[NAMES[0]].values() if w), None)
    print(f"  name origin (left px) = {no}")

    # Best (largest fontsize, then largest kerning) that fits per cost
    def best_fit(usable):
        cands = [(f, k, w['w']) for (f, k), w in data[NAMES[0]].items() if w['w'] <= usable]
        if not cands:
            return None
        return max(cands, key=lambda t: (t[0], t[1]))
    print("\n=== BEST-FIT per cost (name must start before cost_left) ===")
    fits = {}
    for c in COSTS:
        s = cost_info.get(c)
        if not s or no is None:
            continue
        usable = s['c_left'] - no - 8
        b = best_fit(usable)
        fits[c] = dict(usable=usable, best=list(b) if b else None)
        if b:
            print(f"  {c:16} cost_left={s['c_left']:4}  usable={usable:5}  fits up to fs={b[0]}, kern={b[1]} (w={b[2]})")
        else:
            print(f"  {c:16} cost_left={s['c_left']:4}  usable={usable:5}  NO grid point fits (needs fs<= floor)")
    # --- per-glyph advance table (emit title_glyphs.json for autofit_title) ---
    print("\n=== per-glyph advance table (title font) ===")
    from glyph_measure import measure_glyph_table, measure_uniform_kern, write_table
    def set_title(text):
        r.set("Title", text)
        r.set("Mana Cost", ""); r.set("Rules Text",""); time.sleep(0.6)
    glyph_table = measure_glyph_table(set_title, r.png, title_magenta_extent)
    glyph_table["kern_per_gap"] = measure_uniform_kern(
        set_title, r.png, title_magenta_extent, "Rofellos, Llanowar Emissary")
    print(f"  measured {len(glyph_table['glyphs'])} glyph advances")
    table_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "title_glyphs.json")
    write_table(glyph_table, table_path)

    out = dict(
        law=dict(fontsize=a_coef, kerning=c_coef, base=b0),
        name_chars=len(name0),
        char_w_base=b0 / len(name0),
        char_w_font=a_coef / len(name0),
        char_w_kern=c_coef / len(name0),
        name_origin=no,
        cost={c: (cost_info[c]['c_left'] if cost_info[c] else None) for c in COSTS},
        fits=fits,
    )
    with open(a.out, "w") as f: json.dump(out, f, indent=2)
    print(f"\n  wrote {a.out}")
    r.d.quit()

if __name__=="__main__":
    main()
