#!/usr/bin/env python3
"""FINAL live verification of TextMixin.apply_auto_fit_pt() (calibration-model
method) for 2/1 and 3/4 and 8/8 (expect: left alone), 12/12 and 50/50
(expect: box widened to preserve the large {fontsize}).

The automator drives it via self.pt_font_size / self.pt_kerning (the values from
--pt-font-size / --pt-kerning), so we set those on the test object too so the
numbers match a real card.  This replaces the old magenta + per-card
binary-search path the user complained about: at card time it is now PURE MATH
against pt_calib.json.
"""
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from type_calibrate import make_driver
from mixins.text_mixin import TextMixin

drv = make_driver("http://mtgproxy:4242/", headless=True)

class Obj(TextMixin):
    driver = drv
    render_delay = 1.0
    # the user's real --pt-* values:
    pt_font_size = 45
    pt_kerning = 7
    def __init__(self):
        self.wait = WebDriverWait(drv, 15)
        self.text_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Text']")))
    def force_frame(self, name):
        drv.find_element(By.XPATH, "//h3[text()='Frame']").click(); time.sleep(0.5)
        try:
            Select(drv.find_element(By.ID, "autoFrame")).select_by_value(name); time.sleep(1.0)
        except Exception as e:
            print("   frame select failed:", e)
        drv.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.3)
    def set_pt_text(self, t):
        """Set the live P/T field (simulating what _apply_text_mods would apply)."""
        drv.find_element(By.XPATH, "//h3[text()='Text']").click(); time.sleep(0.2)
        drv.find_element(By.XPATH, "//h4[text()='Power/Toughness']").click(); time.sleep(0.3)
        ta = drv.find_element(By.ID, "text-editor")
        drv.execute_script("arguments[0].value=arguments[1];", ta, t)
        drv.execute_script("arguments[0].dispatchEvent(new Event('input'));"
                           "arguments[0].dispatchEvent(new Event('change'));", ta)
        time.sleep(0.6)
    def box(self):
        b = self._open_pt_dialog()
        try:
            drv.find_element(By.CSS_SELECTOR, "h2.textbox-editor-close").click(); time.sleep(0.3)
        except Exception:
            pass
        return b

o = Obj()
NARROW = ["2/1", "3/4", "8/8"]
WIDE   = ["12/12", "50/50", "30/30"]
for pt in NARROW + WIDE:
    o.force_frame("Seventh")          # resets to frame-default box each iteration
    o.set_pt_text(f"{{fontsize45}}{{shadow6}}{{kerning7}}{pt}")
    w0, x0 = o.box()
    print(f"\n=== '{pt}' @ fontsize45 kerning7 | ORIGINAL box: width={w0} x={x0} (dialog units) ===")
    o.apply_auto_fit_pt()
    w1, x1 = o.box()
    expect = "WIDENED" if pt in WIDE else "left alone"
    status = "OK" if (w1 > w0) == (pt in WIDE) else "*** MISMATCH ***"
    print(f"    => box now: width={w1} x={x1} (delta width={w1-w0:+d}, x={x1-x0:+d})  [{expect}] {status}")
drv.quit()
print("\nDONE")
