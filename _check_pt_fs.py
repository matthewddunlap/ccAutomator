#!/usr/bin/env python3
"""Settle whether the P/T glyph-width model is correct at the user's real
{fontsize45}.  For "1234" (no slash, clean) and "12/12" measure the RENDERED
natural ink width at fs=45 (wide box) and fs=20, and compare to the model
(base + slope*fs, sum over chars, kerning 0).  If the model matches at BOTH fs,
its interpretation of {fontsize} is right and it will be correct at fs=45.
Run: .venv/bin/python _check_pt_fs.py
"""
import json, os, time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from type_calibrate import make_driver, R
from automator_utils import autofit_pt, _load_pt_calib

URL = "http://mtgproxy:4242/"
CAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pt_calib.json")


def band(r):
    g = r.d.execute_script("""
        var cv=document.querySelector('canvas'); var t=card.text.pt;
        var H=cv.height; m=0.02*H;
        return [Math.floor(Math.max(0,t.y*H-m)), Math.floor(Math.min(H,(t.y+t.height)*H+m))];
    """)
    return tuple(int(x) for x in g)


def extent(r, band):
    img = r.png(); px = img.load(); W, H = img.size
    lo, hi = int(band[0]), int(min(band[1], H))
    xs = [x for y in range(lo, hi) for x in range(W)
          if px[x, y][0] > 180 and px[x, y][2] > 180 and px[x, y][1] < 80]
    return (min(xs), max(xs)) if xs else None


def w_of(r, band):
    e = extent(r, band); return (e[1]-e[0]) if e else None


def setdu(r, w, x):
    d = r.d
    d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
    d.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
    d.find_element(By.XPATH, "//button[contains(text(),'Edit Bounds')]").click(); time.sleep(0.4)
    def sv(id, v):
        i = d.find_element(By.ID, id); i.clear(); i.send_keys(str(v)); i.send_keys(Keys.RETURN); time.sleep(0.3)
    sv("textbox-editor-width", w); sv("textbox-editor-x", max(0, x - w))
    d.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click(); time.sleep(1.0)


def model(cal, txt, fs, kern=0):
    gl = {k: (v["base"], v["slope"]) for k, v in cal["glyphs"].items()}
    tot = sum(gl[c][0] + gl[c][1] * fs for c in txt)
    tot += kern * cal.get("kern_per_gap", 0.0) * max(0, len(txt) - 1)
    return tot


def main():
    cal = _load_pt_calib()
    print(f"model px_per_du={cal['px_per_du']}  base_box_du={cal['base_box_du']}  "
          f"kern_per_gap={cal.get('kern_per_gap')}")
    r = R(make_driver(URL, headless=True), URL)
    r.set_frame("Seventh")
    b = band(r)
    # open the base box once to know its du/x, then leave box wide (8x) for full size
    d = r.d
    d.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
    d.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
    d.find_element(By.XPATH, "//button[contains(text(),'Edit Bounds')]").click(); time.sleep(0.4)
    bx_w = int(d.find_element(By.ID, "textbox-editor-width").get_attribute("value") or 0)
    bx_x = int(d.find_element(By.ID, "textbox-editor-x").get_attribute("value") or 0)
    d.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click(); time.sleep(0.6)
    setdu(r, bx_w * 8, bx_x)    # wide box -> no scale-fit (natural size)
    print(f"base box {bx_w}du/{bx_x} ; set wide {bx_w*8}du for natural-size measurement\n")

    TAG = "{shadow6}{fontcolor#FF00FF}"
    for fs in [15, 20, 30, 45, 60]:
        for t in ["1234", "12/12", "2/1", "3/4"]:
            r.set_field("Power/Toughness", f"{{fontsize{fs}}}{TAG}{t}"); time.sleep(0.8)
            m = model(cal, t, fs)
            w = w_of(r, b)
            if w is not None and m:
                print(f"  fs={fs:>3} '{t:6}'  model={m:6.1f}px  measured={w:4}px  "
                      f"err={w-m:+6.1f}px {'OK' if abs(w-m)<=12 else '*** MISMATCH ***'}")
    r.d.quit(); print("\nDONE")

if __name__ == "__main__":
    main()
