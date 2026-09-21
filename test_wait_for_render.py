"""Timing/behavior tests for _wait_for_render (perf #3), stub driver, no browser.

Run: .venv/bin/python test_wait_for_render.py
"""
import sys, os, time, inspect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mixins.canvas_mixin import CanvasMixin

class StubDriver:
    """Emulates the browser for both hash paths.

    Probe JS (contains '__ccProbe') returns a plain hash string, like
    _get_canvas_probe_hash expects.  Full-res JS returns the
    {hash, selector} dict _get_canvas_hash expects.
    """
    def __init__(self, mode):
        self.mode = mode  # 'stable' | 'changing'
        self.n = 0
        self.saw_probe = False
        self.saw_fullres = False
    def execute_script(self, js):
        self.n += 1
        if '__ccProbe' in js:
            self.saw_probe = True
            if self.mode == 'stable':
                return 'p-abc'
            return f'p-h{self.n}'
        if 'toDataURL' in js:
            self.saw_fullres = True
            if self.mode == 'stable':
                return {'hash': 'abc', 'selector': '#canvas'}
            return {'hash': f'h{self.n}', 'selector': '#canvas'}
        return None

class T(CanvasMixin):
    def __init__(self, mode, render_delay):
        self.driver = StubDriver(mode)
        self.render_delay = render_delay
        self.current_canvas_hash = None
        self.debug = False

passed = failed = 0
def check(name, cond, info=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS {name} {info}")
    else:
        failed += 1; print(f"  FAIL {name} {info}")

# 1. Stable canvas: returns in well under the old blind 1.5s sleep
t = T('stable', 1.5)
start = time.time(); t._wait_for_render(); elapsed = time.time() - start
check("stable canvas fast (<1.0s)", elapsed < 1.0, f"({elapsed:.2f}s)")
check("uses cheap probe (no full-res toDataURL)",
      t.driver.saw_probe and not t.driver.saw_fullres)
check("full-res current_canvas_hash NOT clobbered by probe hash",
      t.current_canvas_hash is None)

# 2. render_delay=0 → no wait, zero driver calls (old behavior: sleep(0))
t = T('stable', 0)
calls_before = t.driver.n
start = time.time(); t._wait_for_render(); elapsed = time.time() - start
check("render_delay=0 skips", elapsed < 0.1 and t.driver.n == calls_before,
      f"({elapsed:.2f}s, +{t.driver.n - calls_before} calls)")

# 3. Explicit timeout cap honored: changing canvas waits out the cap, then continues
t = T('changing', 1.5)
start = time.time(); t._wait_for_render(timeout=0.5); elapsed = time.time() - start
check("changing canvas waits out cap (~0.5s, not 1.5s)", 0.4 <= elapsed < 1.2, f"({elapsed:.2f}s)")

# 4. Default cap = render_delay: changing canvas with cap 0.8
t = T('changing', 0.8)
start = time.time(); t._wait_for_render(); elapsed = time.time() - start
check("default cap = render_delay (~0.8s)", 0.7 <= elapsed < 1.4, f"({elapsed:.2f}s)")

# 5. Back-compat: direct stabilizer call defaults to the FULL-RES hash
#    (probe=False) so the pre-capture / art-apply / priming gates are unchanged.
t = T('stable', 1.5)
result = t._wait_for_canvas_stabilization(None, wait_for_change=False, timeout=2)
check("stabilizer default is full-res path",
      result == 'abc' and t.driver.saw_fullres and not t.driver.saw_probe)

# 6. probe=True is explicit and accepted
sig = inspect.signature(CanvasMixin._wait_for_canvas_stabilization)
check("stabilizer has timeout + probe params",
      'timeout' in sig.parameters and 'probe' in sig.parameters)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
