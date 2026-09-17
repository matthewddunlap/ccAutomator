#!/usr/bin/env python3
"""Ground-truth cross-check of the P/T width model.

Measures the REAL rendered ink width of actual P/T strings at the user's exact
tags ({fontsize45}{kerning7}), with the box at the base width and at an
overkill wide width, plus the rendered CAP (box du -> px).  Prints the model's
prediction (from pt_calib.json) next to each so any mismatch is obvious.

Run:  .venv/bin/python _check_pt_model.py
"""
import json, os, time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from type_calibrate import make_driver, R

URL = "http://mtgproxy:4242/"
CAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pt_calib.json")
TAG = "{fontsize45}{kerning7}{fontcolor#FF00FF}"   # the user's real tags
TARGETS = ["2/1", "3/4", "8/8", "12/12"]


def band(r):
    g = r.d.execute_script("""
        var cv=document.querySelector('canvas');
        var t=card.text.pt;
        var H=cv.height; m=0.02*H;
        return [Math.max(0,Math.floor(t.y*H)-m), Math.min(H,Math.floor((t.y+t.height)*H)+m)];
    """)
    return tuple(g)


def extent(r, band):
    img = r.png(); px = img.load(); W, H = img.size
    lo, hi = band
    lo, hi = int(lo), min(int(hi), H)
    xs = [x for y in range(lo, hi) for x in range(W)
          if px[x, y][0] > 180 and px[x, y][2] > 180 and px[x, y][1] < 80]
    return (min(xs), max(xs)) if xs else None


def dialog(r):
    d = r.d
    d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
    d.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
    d.find_element(By.XPATH, "//button[contains(text(),'Edit Bounds')]").click(); time.sleep(0.4)
    gw = int(d.find_element(By.ID, "textbox-editor-width").get_attribute("value") or 0)
    gx = int(d.find_element(By.ID, "textbox-editor-x").get_attribute("value") or 0)
    d.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click(); time.sleep(0.8)
    return gw, gx


def setdu(r, w, x):
    d = r.d
    d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
    d.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
    d.find_element(By.XPATH, "//button[contains(text(),'Edit Bounds')]").click(); time.sleep(0.4)
    def sv(id, v):
        i = d.find_element(By.ID, id); i.clear(); i.send_keys(str(v)); i.send_keys(Keys.RETURN); time.sleep(0.3)
    sv("textbox-editor-width", max(w, 1)); sv("textbox-editor-x", max(0, x - (w - 1)))
    d.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click(); time.sleep(1.2)


def model_width(cal, txt, fs, kern):
    gl = cal.get("glyphs", {})
    kb = cal.get("kern_per_gap", 0.0)
    tot = 0.0
    ok = True
    for ch in txt:
        if ch not in gl:
            return None
        tot += gl[ch]["base"] + gl[ch].get("slope", 0) * fs
    tot += kern * kb * max(0, len(txt) - 1)
    return tot


def main():
    with open(CAL) as f:
        cal = json.load(f)
    print(f"calib: px_per_du={cal['px_per_du']}  base_box_du={cal['base_box_du']}  "
          f"kern_per_gap={cal.get('kern_per_gap')}")
    print(f"glyphs: " + "  ".join(f"'{k}':({v['base']:.2f},{v['slope']:.3f})"
                                  for k, v in cal["glyphs"].items()))
    r = R(make_driver(URL, headless=True), URL)
    r.set_frame("Seventh")
    b = band(r)
    base_du, base_x = dialog(r)
    print(f"base box = {base_du}du  base_x={base_x}  preview W={r.png().size[0]}")

    # measure base box capacity in preview px
    geo = r.d.execute_script("""
        var cv=document.querySelector('canvas'); var t=card.text.pt;
        return {W:cv.width, w:t.width};
    """)
    base_px = int(geo["w"] * geo["W"])
    print(f"base box = {base_du}du = {base_px}px (preview)")
    print(f"=> calibrated px_per_du = {cal['px_per_du']}   live px_per_du = {base_px/base_du:.4f}\n")

    wide_du = int(base_du * 8)
    for t in TARGETS:
        m = model_width(cal, t, 45, 7)
        # rendered at base box (may be scale-fit / capped)
        r.set_field("Power/Toughness", TAG + t); time.sleep(0.8)
        eb = extent(r, b)
        base_cap_px = cal["px_per_du"] * base_du + cal.get("du_offset", 0)
        cap_at_base = "CAPPED(natural>=box)" if (eb and base_px and (eb[1]-eb[0]) >= base_px*0.95) else "fits"
        # rendered at overkill-wide box (full natural size)
        setdu(r, wide_du, base_x)
        r.set_field("Power/Toughness", TAG + t); time.sleep(0.8)
        ew = extent(r, b)
        nat = (ew[1]-ew[0]) if ew else None
        print(f"  '{t}':  model@fs45,k7={m:.0f}px   measured-base={eb and eb[1]-eb[0] if eb else None}px[{cap_at_base}]   "
              f"measured-natural={nat}px   "
              f"err={'+' if (nat and m and nat-m>0) else ''}{(nat-m):.0f}px" if (nat and m) else f"  '{t}':  model={m}  nat={nat}  (miss)")
    r.d.quit()
    print("\nDONE")

if __name__ == "__main__":
    main()
