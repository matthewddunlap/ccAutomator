import time
import hashlib
import json
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .image_mixin import UploadError

class CanvasMixin:
    STABILIZE_TIMEOUT = 20
    STABILITY_INTERVAL = 0.1
    STABILITY_CHECKS = 3
    # Frame value most recently applied via set_frame (None before the first
    # call).  Lets set_frame_color re-verify the picker pack even when the
    # caller skipped set_frame (spell cards: set_frame runs at startup only).
    _last_set_frame = None
    def _get_canvas_data_url(self):
        # Use a cached selector if available to speed up subsequent calls
        if hasattr(self, '_cached_canvas_selector'):
            js_script = f"""
                const canvas = document.querySelector('{self._cached_canvas_selector}');
                if (canvas && canvas.width > 0 && canvas.height > 0) {{
                    try {{ return canvas.toDataURL('image/png'); }} catch (e) {{ return 'error: ' + e.message; }}
                }}
                return null;
            """
            return self.driver.execute_script(js_script)

        # Fallback: Find the valid selector and cache it
        js_script = """
            const selectors = ['#mainCanvas', '#card-canvas', '#canvas', 'canvas'];
            for (let selector of selectors) {
                const canvas = document.querySelector(selector);
                if (canvas && canvas.width > 0 && canvas.height > 0) {
                    return { selector: selector, dataUrl: canvas.toDataURL('image/png') };
                }
            }
            return null;
        """
        result = self.driver.execute_script(js_script)
        if result and isinstance(result, dict):
            self._cached_canvas_selector = result['selector']
            return result['dataUrl']
        return None

    def _get_canvas_hash(self):
        """
        Computes a hash of the canvas content directly in the browser.
        Returns a tuple (hash_string, selector_used) or (None, None).
        """
        # Use a cached selector if available
        selector_part = ""
        if hasattr(self, '_cached_canvas_selector'):
             selector_part = f"const canvas = document.querySelector('{self._cached_canvas_selector}');"
             # If we have a cached selector, we assume it's correct. 
             # If it fails (e.g. page reload), we might need to invalidate it, but for now assume persistence.
        else:
             selector_part = """
                const selectors = ['#mainCanvas', '#card-canvas', '#canvas', 'canvas'];
                let canvas = null;
                let usedSelector = null;
                for (let selector of selectors) {
                    canvas = document.querySelector(selector);
                    if (canvas && canvas.width > 0 && canvas.height > 0) {
                        usedSelector = selector;
                        break; 
                    }
                }
             """

        js_script = f"""
            {selector_part}
            if (canvas && canvas.width > 0 && canvas.height > 0) {{
                try {{
                    var dataUrl = canvas.toDataURL('image/png');
                    var hash = 0, i, chr;
                    if (dataUrl.length === 0) return null;
                    for (i = 0; i < dataUrl.length; i++) {{
                        chr   = dataUrl.charCodeAt(i);
                        hash  = ((hash << 5) - hash) + chr;
                        hash |= 0; // Convert to 32bit integer
                    }}
                    // Return object with hash and selector (if we found a new one)
                    return {{ 'hash': hash.toString(), 'selector': (typeof usedSelector !== 'undefined' ? usedSelector : null) }};
                }} catch (e) {{ return {{ 'error': e.message }}; }}
            }}
            return null;
        """
        result = self.driver.execute_script(js_script)
        
        if result and isinstance(result, dict):
            if 'error' in result:
                if getattr(self, 'debug', False):
                    print(f"   [Debug] Canvas JS Error: {result['error']}")
                return None, None
            
            # Cache the selector if we got one back and haven't cached it yet
            if result.get('selector') and not hasattr(self, '_cached_canvas_selector'):
                self._cached_canvas_selector = result['selector']
                if getattr(self, 'debug', False):
                    print(f"   [Debug] Cached canvas selector: {self._cached_canvas_selector}")
            
            return result.get('hash'), self._cached_canvas_selector if hasattr(self, '_cached_canvas_selector') else result.get('selector')
            
        return None, None

    def _get_canvas_probe_hash(self):
        """
        Cheap content probe for high-frequency polling (see ``_wait_for_render``).

        ``_get_canvas_hash`` calls ``toDataURL('image/png')`` on the full
        2010x2814 card canvas and then runs a JS hash loop over the whole
        multi-megabyte base64 string.  At ~10 polls/second that allocates
        and GCs tens of MB and measurably slows the very browser we are
        waiting on (observed in live A/B: single reads ballooning to 6-8s,
        so the wait "cap" was never actually a cap).  This variant
        downsamples the canvas onto a small cached offscreen canvas (64px
        wide) and hashes that instead -- a few KB of data, cheap enough to
        poll at 10Hz without pressure.  Any real repaint (art, frame, text,
        symbol) shifts the probe, so it is a valid "did the render change"
        signal for polling; the full-res hash is still the final gate
        before capture.
        Returns a hash string, or None if the canvas isn't available.
        """
        if hasattr(self, '_cached_canvas_selector'):
            selector_part = f"const canvas = document.querySelector('{self._cached_canvas_selector}');"
        else:
            selector_part = """
                const selectors = ['#mainCanvas', '#card-canvas', '#canvas', 'canvas'];
                let canvas = null;
                for (let selector of selectors) {
                    canvas = document.querySelector(selector);
                    if (canvas && canvas.width > 0 && canvas.height > 0) break;
                    canvas = null;
                }
            """

        js_script = f"""
            {selector_part}
            if (canvas && canvas.width > 0 && canvas.height > 0) {{
                try {{
                    // Cache the offscreen probe canvas on window; a page
                    // reload wipes it and the next call recreates it.
                    var p = (typeof window.__ccProbe === 'object') ? window.__ccProbe : null;
                    if (!p || !p.ctx) {{
                        p = {{ cv: document.createElement('canvas'), ctx: null }};
                        p.cv.width = 64;
                        p.cv.height = 90;
                        p.ctx = p.cv.getContext('2d');
                        window.__ccProbe = p;
                    }}
                    p.ctx.drawImage(canvas, 0, 0, p.cv.width, p.cv.height);
                    var dataUrl = p.cv.toDataURL('image/png');
                    var hash = 0, i, chr;
                    for (i = 0; i < dataUrl.length; i++) {{
                        chr  = dataUrl.charCodeAt(i);
                        hash = ((hash << 5) - hash) + chr;
                        hash |= 0; // 32bit
                    }}
                    return hash.toString();
                }} catch (e) {{ return null; }}
            }}
            return null;
        """
        return self.driver.execute_script(js_script)

    def _wait_for_canvas_stabilization(self, initial_hash, wait_for_change=True, timeout=None, probe=False):
        """
        Poll until the canvas hash is stable (STABILITY_CHECKS consecutive
        equal reads), returning the final hash, or None on timeout.

        probe=True polls the cheap downsampled ``_get_canvas_probe_hash``
        (for high-frequency waits like ``_wait_for_render``); probe=False
        (default) keeps the full-res ``_get_canvas_hash`` used by the
        one-off gates (frame apply, art apply, priming, pre-capture).
        """
        def read_hash():
            if probe:
                return self._get_canvas_probe_hash()
            current_hash, _ = self._get_canvas_hash()
            return current_hash

        if timeout is None:
            timeout = self.STABILIZE_TIMEOUT
        start_time = time.time()
        last_hash, stable_count = None, 0

        # If we don't have an initial hash but are asked to wait for change,
        # we must get one.
        if initial_hash is None and wait_for_change:
            initial_hash = read_hash()

        while time.time() - start_time < timeout:
            current_hash = read_hash()
            
            if not current_hash:
                if getattr(self, 'debug', False):
                    elapsed = time.time() - start_time
                    print(f"   [Debug] Wait: {elapsed:.2f}s | Hash: None (Canvas not ready)")
                time.sleep(self.STABILITY_INTERVAL); continue
            
            # If waiting for change, ensure we have moved away from initial state
            if wait_for_change and initial_hash and current_hash == initial_hash:
                time.sleep(self.STABILITY_INTERVAL); continue
                
            # Stability Check
            if current_hash == last_hash: 
                stable_count += 1
            else: 
                last_hash = current_hash; stable_count = 1
                
            if stable_count >= self.STABILITY_CHECKS:
                return current_hash
            
            if getattr(self, 'debug', False):
                elapsed = time.time() - start_time
                print(f"   [Debug] Wait: {elapsed:.2f}s | Hash: {current_hash} | Stable: {stable_count} | Change: {wait_for_change}")
            
            time.sleep(self.STABILITY_INTERVAL)
        
        if wait_for_change:
            print("Warning: Timeout waiting for canvas to stabilize (change detected: False).", file=sys.stderr)
        else:
            print("Warning: Timeout waiting for canvas to stabilize (steady state).", file=sys.stderr)
        return None

    def _wait_for_render(self, timeout=None):
        """
        State-based wait for the card canvas to settle after a DOM change —
        the drop-in replacement for the old blind ``time.sleep(render_delay)``.

        ``render_delay`` is now a CAP, not a floor: poll the cheap
        downsampled canvas probe (``_get_canvas_probe_hash``) and return as
        soon as it is stable (3 consecutive equal reads, ≈0.3s), waiting out
        the cap only if the render is still in flight.  The probe -- not the
        full-res hash -- is what makes the cap honest: a full-canvas read
        allocates a multi-MB string and can take seconds, which would blow
        the cap on the very first poll.
        timeout=None → cap = self.render_delay; cap<=0 (or render_delay=0) →
        no wait at all.  Never raises: on cap expiry it warns and continues,
        the same risk profile as the old fixed sleep (which also "failed"
        whenever the render took longer than the delay).

        Note: the probe hash is a different basis than ``current_canvas_hash``
        (full-res), so it is deliberately NOT written back here -- the one-off
        gates that compare against ``current_canvas_hash`` keep full-res
        semantics.
        """
        cap = timeout if timeout is not None else self.render_delay
        if not cap or cap <= 0:
            return
        if self._wait_for_canvas_stabilization(
                self.current_canvas_hash, wait_for_change=False,
                timeout=cap, probe=True) is None:
            print(f"   Warning: canvas had not settled after {cap:.1f}s; proceeding.", file=sys.stderr)

    # Where each auto-frame pack's picker thumbnails live.  The frame-picker
    # rebuild race (see _wait_frame_picker_ready) needs a pack-specific
    # thumbnail src to tell "the new pack's picker is live" from "the old
    # pack's picker is still up".  Keyed by #autoFrame dropdown value.
    _FRAME_PACK_THUMB_SRC = {
        "FullArtNew": "/img/frames/m15/new/fullart/",
        "Seventh": "/img/frames/seventh/regular/",
        "seventhTextless": "/img/frames/seventh/textless/",
        "TokenTextless-1": "/img/frames/token/textless/",
    }

    def _frame_picker_srcs(self):
        """Return the list of src attributes currently in #frame-picker."""
        try:
            return self.driver.execute_script(
                "return Array.from(document.querySelectorAll('#frame-picker img'))"
                ".map(function (i) { return i.getAttribute('src'); }) || [];")
        except Exception:
            return []

    def _wait_frame_picker_ready(self, frame_value, timeout=15.0):
        """Block until #frame-picker shows thumbnails of `frame_value`'s pack.

        WHY: selecting a new value in the app's #autoFrame dropdown fires
        setAutoFrame() -> autoFrame(), which ends with
        loadScript('/js/frames/pack<Frame>.js') -- an ASYNC script fetch.
        Only when that script executes does loadFramePack() rebuild the
        picker with the new pack's thumbnails (and 'Load Frame Version'
        re-fit the art).  Until then the picker still shows the PREVIOUS
        pack's thumbnails.

        Any caller that clicks picker thumbnails right after set_frame()
        (set_frame_color's color/land/PT thumbs) would therefore race the
        pack fetch: the selector (e.g. //img[contains(@src, '/bThumb.png')])
        matches BOTH packs' black thumb, so a slow fetch silently clicks
        the OLD frame's pieces.  Observed production symptom: tokens
        rendered Seventh frame graphics under art auto-fit to FullArtNew's
        portrait window (the loadFrameVersion art refit had landed, the
        color-thumb clicks had not).

        Wait is bounded; on timeout we proceed (same risk profile as the
        old blind wait) and report.  Cheap JS poll, no canvas reads.
        """
        marker = self._FRAME_PACK_THUMB_SRC.get(frame_value)
        if not marker:
            return  # Unknown pack: nothing pack-specific to wait on.
        start = time.time()
        while time.time() - start < timeout:
            srcs = self._frame_picker_srcs()
            if srcs and any(marker in (s or "") for s in srcs):
                # Picker rebuilt; give loadFramePack's trailing
                # '#frame-picker'.children[0].click() + loadFrameVersion
                # click a beat to finish (they are synchronous with the
                # pack script's execution, which we have now observed).
                return True
            time.sleep(0.1)
        print(f"   Warning: frame picker did not show '{frame_value}' thumbnails "
              f"within {timeout:.0f}s; proceeding (color step may race the pack load).",
              file=sys.stderr)
        return False

    def set_frame(self, frame_value, wait=True):
        try:
            art_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[3]')))
            art_tab.click()
            frame_dropdown = self.wait.until(EC.presence_of_element_located((By.ID, 'autoFrame')))

            select = Select(frame_dropdown)
            current_val = select.first_selected_option.get_attribute("value")

            # A previous seventhTextless token may have left the dropdown at
            # 'false' (autoFrame neutralized so its debounced timer could not
            # clobber the textless frame).  Restore selection from the DOM
            # state, not from _last_set_frame, or this early-return would
            # skip the rebuild and the next spell would keep token framing.
            if current_val == 'false':
                print("   Re-enabling autoFrame after seventhTextless token frame.")
            elif current_val == frame_value:
                print(f"   Frame already set to '{frame_value}'. Skipping update.")
                return

            select.select_by_value(frame_value)
            print(f"Successfully set frame by value to '{frame_value}'.")
            self._last_set_frame = frame_value

            # The dropdown change triggers an ASYNC frame-pack script fetch;
            # the picker (and the frame version's art refit) only reflect the
            # new pack once that script executes.  Block on the picker before
            # any caller clicks picker thumbnails (set_frame_color) or reads
            # frame-default geometry -- otherwise those clicks can land on the
            # previous pack's thumbs (see _wait_frame_picker_ready).
            self._wait_frame_picker_ready(frame_value)

            # A different frame can have a different default P/T box, so the
            # cached frame-default geometry (TextMixin._pt_base) and the "box at
            # home" state are stale: drop them so the next card re-reads the
            # default.  (No-op when the frame was already set, above.)
            if hasattr(self, "_reset_pt_box_state"):
                self._reset_pt_box_state()

            if wait:
                print("Waiting for frame to apply...")
                self.current_canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash, wait_for_change=False)
        except (TimeoutException, NoSuchElementException) as e:
            print(f"Error setting frame: {e}", file=sys.stderr)
            raise

    # Text-box layout of the app's "Textless Seventh" frame version
    # (packSeventhTextless.js, loadFrameVersion.onclick).  Applying
    # seventhTextless via JS (see apply_seventh_textless_frame) must mirror
    # this exactly: the pack's own onclick path is not reachable because
    # #autoFrame has no seventhTextless entry, so this module drives the
    # same pack script + version + art/text geometry directly.
    SEVENTH_TEXTLESS_TEXT = {
        "mana": {"name": "Mana Cost", "text": "", "x": 0.108, "y": 0.0486,
                 "width": 0.8147, "height": 72 / 2100, "oneLine": True,
                 "size": 72 / 1638, "align": "right", "manaCost": True,
                 "manaSpacing": 0},
        "title": {"name": "Title", "text": "", "x": 0.108, "y": 0.0448,
                  "width": 0.784, "height": 0.0405, "oneLine": True,
                  "font": "goudymedieval", "size": 0.0405, "color": "white",
                  "shadowX": 0.002, "shadowY": 0.0015},
        "rules": {"name": "Rules Text", "text": "", "x": 0.128, "y": 0.6429,
                  "width": 0.744, "height": 0.2381, "size": 0.0358,
                  "color": "white", "shadowX": 0.0014, "shadowY": 0.001},
        "pt": {"name": "Power/Toughness", "text": "", "x": 0.8, "y": 0.8981,
               "width": 0.1367, "height": 0.0453, "size": 0.0453,
               "oneLine": True, "align": "center", "color": "white",
               "shadowX": 0.002, "shadowY": 0.0015},
    }

    def apply_seventh_textless_frame(self, color_code='B'):
        """Switch the live card to the app's 'Textless Seventh' frame
        (seventhTextless) in `color_code` (W/U/B/R/G/M/A/L).

        This is the frame family the --full-art-basic-land path uses
        (version 'seventhTextless', one full-card textured frame asset
        seventhTextlessFrame{letter}.png, portrait art window 0.768x0.7772,
        no title plaque / no translucent type bar) -- the look the user
        wants tokens to match.  #autoFrame has NO seventhTextless entry,
        so set_frame() cannot select it; instead this drives the pack the
        way the app's own frame-search + 'Load Frame Version' path does:

          1. loadScript('/js/frames/packSeventhTextless.js') repopulates
             availableFrames + the picker (loadFramePack()).
          2. The pack's #loadFrameVersion.onclick is then invoked to set
             card.version='seventhTextless', reset irregularities, refit
             art to the portrait window (autoFitArt) and load the frame's
             text-box layout (loadTextOptions).

        Both steps are asynchronous (script exec + image loads); callers
        should follow with _wait_frame_picker_ready('seventhTextless')
        (done here) and the standard canvas stabilization before capture.
        Returns True on success, False on failure (caller keeps the deck
        frame).
        """
        try:
            self.driver.execute_script(
                "loadScript('/js/frames/packSeventhTextless.js');")
            if not self._wait_frame_picker_ready('seventhTextless', timeout=15.0):
                print("   Warning: SeventhTextless picker did not load.", file=sys.stderr)
                return False

            # Disable the dropdown BEFORE installing the textless frame.
            # Every text edit (mana clear, title/PT mods) schedules the app's
            # debounced autoFrame() (~500ms), which reads #autoFrame and
            # REBUILDS card.frames from that frame's builder.  The dropdown
            # still reads the deck frame here, so a pending timer would fire
            # mid-apply and paint deck-frame pieces over the textless frame.
            # 'false' makes autoFrame() a no-op; set_frame(deck_frame) at
            # restore re-enables it (its value differs -> full re-select).
            self.driver.execute_script(
                "document.querySelector('#autoFrame').value = 'false'; setAutoFrame();")

            letter = str(color_code).upper() or 'B'
            valid = ('W', 'U', 'B', 'R', 'G', 'M', 'A', 'L')
            if letter not in valid:
                print(f"   Warning: no SeventhTextless frame for color '{color_code}'; using black.",
                      file=sys.stderr)
                letter = 'B'
            src = f"/img/frames/seventh/textless/seventhTextlessFrame{letter}.png"

            # Invoke the pack's own load handler: sets version, resets
            # irregularities, autofits art to the portrait bounds and
            # loads the textless text layout.  done async -> await it.
            result = self.driver.execute_async_script(r"""
                var done = arguments[arguments.length - 1];
                var btn = document.querySelector('#loadFrameVersion');
                if (!btn || !btn.onclick) { done('no-handler'); return; }
                // The onclick is async; resolve after it settles.
                var p = btn.onclick();
                if (p && typeof p.then === 'function') {
                    p.then(function () { done('loaded'); },
                           function (e) { done('error: ' + e); });
                } else { done('loaded-sync'); }
            """)
            if result not in ('loaded', 'loaded-sync'):
                print(f"   Warning: SeventhTextless load handler returned '{result}'.",
                      file=sys.stderr)
                return False

            # The pack's onclick loads the LAND frame ('Land Frame',
            # seventhTextlessFrameL.png) via loadFramePack()'s first-thumb
            # click.  Swap the frame stack to the requested color: single
            # full-card frame entry, no masks (same shape the land JSON
            # path writes into land.cardconjurer).  Also re-add a Type text
            # box at the bottom-left (opposite the P/T): the textless layout
            # has no Type box, but the deck frame's Type text (with its
            # tags) is preserved in the app's savedTextContents when the
            # pack's loadTextOptions replaced the layout -- restore it so
            # e.g. 'Token Creature — Serf' renders on the bottom border.
            self.driver.execute_script(r"""
                var src = arguments[0];
                var f = {name: 'Color Frame', src: src, masks: []};
                var img = new Image();
                img.crossOrigin = 'anonymous';
                img.onload = drawFrames;
                img.src = fixUri(src);
                f.image = img;
                card.frames = [f];
                // Type line: bottom-left, mirroring the P/T row geometry.
                // Goudymedieval + white + shadow matches the title's
                // on-border styling.
                var savedType = (typeof savedTextContents !== 'undefined'
                                 && savedTextContents['type'])
                                ? savedTextContents['type'] : '';
                card.text.type = {name: 'Type', text: savedType,
                                  x: 0.108, y: 0.8981, width: 0.64,
                                  height: 0.0453, oneLine: true,
                                  font: 'goudymedieval', size: 0.0453,
                                  color: 'white', shadowX: 0.002,
                                  shadowY: 0.0015};
                drawTextBuffer();
                drawFrames();
            """, src)

            # Text layout was replaced by the pack's loadTextOptions; card.text
            # is fresh, so the automator's text mods apply to the new boxes.
            self._last_set_frame = 'seventhTextless'
            if hasattr(self, "_reset_pt_box_state"):
                self._reset_pt_box_state()
            print(f"   SeventhTextless frame applied ({letter}).")
            return True
        except Exception as e:
            print(f"   Warning: apply_seventh_textless_frame failed: {e}", file=sys.stderr)
            return False

    # The app's own "White Border" frame entry (captured from availableFrames):
    # full-card white.png masked to the outer card boundary by border.svg, so it
    # is independent of the underlying frame family.  Frames whose picker does
    # not expose a whiteThumb (e.g. FullArtNew, the default token frame) get
    # this injected via _apply_white_border_injection instead.
    _WHITE_BORDER_FRAME = {
        "name": "White Border",
        "src": "/img/frames/white.png",
        "noDefaultMask": True,
        "masks": [{"src": "/img/frames/seventh/regular/border.svg", "name": "Border"}],
    }

    def _apply_white_border_injection(self):
        """Add the White Border frame to card.frames directly, for frames
        whose picker has no whiteThumb (FullArtNew, used for tokens via
        --token-frame).

        Mirrors what the picker double-click does: the app's drawFrames()
        skips any frame entry without a pre-loaded .image object, so the
        frame and its mask image are built the way addFrame() does, and
        drawFrames() runs once both are loaded.  Idempotent (a card already
        carrying the frame is reported, not duplicated).  Raises
        UploadError on a load failure so the caller counts the card,
        matching the thumbnail path.
        """
        print("   No white-border thumbnail in this frame's picker; injecting the White Border frame via JS.")
        result = self.driver.execute_async_script(r"""
            var done = arguments[arguments.length - 1];
            if (card.frames.some(function (x) { return x.name === 'White Border'; })) { done('already'); return; }
            var f = arguments[0];
            f.masks.forEach(function (item) {
                item.image = new Image();
                item.image.crossOrigin = 'anonymous';
                item.image.src = fixUri(item.src);
                item.image.onload = drawFrames;
                item.image.onerror = function () { done('mask load failed: ' + item.src); };
            });
            f.image = new Image();
            f.image.crossOrigin = 'anonymous';
            f.image.src = fixUri(f.src);
            f.image.onload = function () {
                card.frames.unshift(f);
                drawFrames();
                done('injected');
            };
            f.image.onerror = function () { done('frame load failed: ' + f.src); };
        """, json.loads(json.dumps(self._WHITE_BORDER_FRAME)))
        if result not in ('injected', 'already'):
            raise UploadError(f"White border injection failed: {result}")

    def apply_white_border(self):
        """
        Applies the white border by finding the correct thumbnail and double-clicking
        it using a more robust JavaScript-based approach.  Frames whose picker
        has no whiteThumb (FullArtNew, the default token frame) fall back to
        injecting the White Border frame directly (_apply_white_border_injection).
        """
        print("Applying white border...")
        try:
            # 1. Navigate to the Frame tab
            frame_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Frame']")))
            frame_tab.click()

            # 2. Define the reliable selector for the white border thumbnail
            white_border_selector = "//div[@id='frame-picker']//img[contains(@src, '/whiteThumb.png')]"
            
            print("Searching for the white border thumbnail...")
            
            # 3. Wait for the element to be clickable, not just present. This is a stronger check.
            #    Short timeout: its ABSENCE is the expected state on frames like
            #    FullArtNew (no white-border picker option) -- that signals the
            #    JS-injection fallback rather than a failure.
            try:
                # Shorter timeout than self.wait: the thumbnail's absence is
                # expected on frames without a white-border picker option.
                short_wait = WebDriverWait(self.driver, 3)
                white_border_thumb = short_wait.until(
                    EC.element_to_be_clickable((By.XPATH, white_border_selector))
                )
            except TimeoutException:
                self._apply_white_border_injection()
                self._wait_for_render()
                print("   White border applied (injected).")
                return

            # 4. Use JavaScript to scroll the element into view. This prevents issues where the element is off-screen.
            print("Scrolling thumbnail into view...")
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", white_border_thumb)
            time.sleep(0.5) # A brief pause to ensure scrolling is complete

            # 5. Use two consecutive JavaScript clicks to simulate a double-click.
            #    This is often more reliable than ActionChains for triggering JS event listeners.
            print("Found thumbnail. Attempting double JavaScript click...")
            self.driver.execute_script("arguments[0].click();", white_border_thumb)
            self.driver.execute_script("arguments[0].click();", white_border_thumb)

            # State-based wait: return as soon as the canvas has settled
            # (old code used a blind render_delay sleep here).
            self._wait_for_render()
            print("   White border applied.")

        except Exception as e:
            print(f"An unexpected error occurred while applying the white border: {e}", file=sys.stderr)
            raise

    def apply_mask(self, frame_suffix, mask_names, right_half=False):
        """
        Applies specific masks from a given frame group.
        1. Single-clicks the frame (by suffix) to load its masks.
        2. Double-clicks each mask in the mask picker matching the mask_names.
        3. If right_half is True, also clicks the 'Right Half' button for each mask.
        """
        print(f"   Applying masks {mask_names} from frame '{frame_suffix}' (Right Half: {right_half})...")
        try:
            # 1. Find the frame thumbnail
            thumb_selector = f"//div[@id='frame-picker']//img[contains(@src, '/{frame_suffix}')]"
            thumb = self.wait.until(EC.element_to_be_clickable((By.XPATH, thumb_selector)))
            
            # 2. Single Click to load masks (do NOT double click)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", thumb)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", thumb)
            time.sleep(0.5) # Wait for mask picker to populate
            
            # 3. Apply each mask
            for mask_name in mask_names:
                # Map mask names to src substrings (Thumbnails are .png)
                mask_src_map = {
                    'Pinline': 'pinlineThumb.png',
                    'Rules': 'rulesThumb.png',
                    'Textbox Pinline': 'trimThumb.png',
                    'Right Half': 'maskRightHalf.png',
                    'Frame': 'frameThumb.png',
                    'Border': 'borderThumb.png'
                }
                
                target_src = mask_src_map.get(mask_name, mask_name.lower())
                
                # Find mask in picker
                mask_selector = f"//div[@id='mask-picker']//img[contains(@src, '{target_src}')]"
                mask_thumb = self.wait.until(EC.element_to_be_clickable((By.XPATH, mask_selector)))
                
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", mask_thumb)

                if right_half:
                    # Single click to select, then click "Right Half" button
                    self.driver.execute_script("arguments[0].click();", mask_thumb)
                    time.sleep(0.2)
                    right_half_btn = self.wait.until(EC.element_to_be_clickable((By.ID, "addToRightHalf")))
                    self.driver.execute_script("arguments[0].click();", right_half_btn)
                    print(f"      Applied mask: {mask_name} (Right Half)")
                else:
                    # Double click to apply normally (Left Half / Full)
                    self.driver.execute_script("arguments[0].click();", mask_thumb)
                    self.driver.execute_script("arguments[0].click();", mask_thumb)
                    print(f"      Applied mask: {mask_name}")
                
                time.sleep(0.2)
                
        except Exception as e:
            print(f"   Error applying masks: {e}", file=sys.stderr)

    def set_frame_color(self, colors, type_line=None, mana_cost=None):
        """
        Sets the frame color based on the card's colors and type line.
        Prioritizes 'Artifact' and 'Land' type lines to use specialized base frames.
        For Colored Artifacts and Lands, applies masks from colored Land frames.
        """
        # For lands, we filter colors to only include colored mana (WUBRG) for frame determination
        is_land = type_line and "Land" in type_line
        if is_land:
            colors = [c for c in colors if c in 'WUBRG']
            # Standard sorting for land colors
            wubrg_order = {'W': 0, 'U': 1, 'B': 2, 'R': 3, 'G': 4}
            colors.sort(key=lambda x: wubrg_order.get(x, 99))

        print(f"   Setting frame color for colors: {colors}, type_line: {type_line}...")
        
        target_thumb_suffix = "cThumb.png" # Default to colorless
        is_colored_artifact = False
        is_colored_land = False
        
        # 1. Navigate to the Frame tab
        frame_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Frame']")))
        frame_tab.click()

        if type_line and "Artifact" in type_line:
            target_thumb_suffix = "aThumb.png"
            if colors:
                is_colored_artifact = True
        elif type_line and "Land" in type_line:
            target_thumb_suffix = "lThumb.png"
            if colors:
                is_colored_land = True
        elif not colors:
            # Colorless non-artifact (e.g. Eldrazi)
            target_thumb_suffix = "cThumb.png"
        elif len(colors) > 1:
            target_thumb_suffix = "mThumb.png"
        else:
            # Single color mapping for spells
            color_map = {
                'W': 'wThumb.png',
                'U': 'uThumb.png',
                'B': 'bThumb.png',
                'R': 'rThumb.png',
                'G': 'gThumb.png'
            }
            target_thumb_suffix = color_map.get(colors[0], "cThumb.png")

        try:
            # 0. Verify the picker actually belongs to the current frame pack.
            #    Thumb srcs like 'bThumb.png' exist in EVERY pack's picker, so
            #    if a frame-pack fetch (kicked by the #autoFrame dropdown, or
            #    by the app's own debounced autoFrame() after text edits) is
            #    still in flight, these clicks would apply the WRONG pack's
            #    frame pieces.  See _wait_frame_picker_ready.
            active_frame = getattr(self, "_last_set_frame", None)
            if active_frame:
                self._wait_frame_picker_ready(active_frame)

            # 1. Find the thumbnail (Base Frame)
            thumb_selector = f"//div[@id='frame-picker']//img[contains(@src, '/{target_thumb_suffix}')]"
            thumb = self.wait.until(EC.element_to_be_clickable((By.XPATH, thumb_selector)))
            
            # 2. Scroll and Click
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", thumb)
            time.sleep(0.5)
            
            # Double click to be safe (Sets the Base Frame)
            self.driver.execute_script("arguments[0].click();", thumb)
            self.driver.execute_script("arguments[0].click();", thumb)
            
            print(f"   Applied base frame using '{target_thumb_suffix}'.")
            
            # 3. Handle Colored Artifacts and Lands (Apply Masks AFTER Base Frame)
            if is_colored_artifact or is_colored_land:
                print(f"   [Colored {'Land' if is_colored_land else 'Artifact'}] Applying colored masks for {colors}...")
                
                # Helper to map color char to Land frame suffix
                def get_land_suffix(color_char):
                    return {
                        'W': 'wlThumb.png',
                        'U': 'ulThumb.png',
                        'B': 'blThumb.png',
                        'R': 'rlThumb.png',
                        'G': 'glThumb.png'
                    }.get(color_char, "cThumb.png")

                # Masks to apply
                # Lands want Pinline, Textbox Pinline, AND Rules (border)
                # Artifacts usually only want Pinlines
                target_masks = ['Pinline', 'Textbox Pinline']
                if is_colored_land:
                    target_masks.append('Rules')
                    print(f"      Including 'Rules' mask for colored Land.")

                # Parse mana_cost or colors to determine color order
                ordered_colors = []
                if mana_cost:
                    # Extract all letters from mana cost (e.g. {1}{B}{R} -> BR)
                    cost_colors = [c for c in mana_cost if c in 'WUBRG']
                    # Deduplicate while preserving order
                    seen = set()
                    ordered_colors = [x for x in cost_colors if not (x in seen or seen.add(x))]
                
                # Fallback if mana_cost didn't give us info (common for lands)
                if not ordered_colors:
                    ordered_colors = colors

                if len(ordered_colors) == 1:
                    # Single Color
                    mask_source_suffix = get_land_suffix(ordered_colors[0])
                    self.apply_mask(mask_source_suffix, target_masks)
                
                elif len(ordered_colors) == 2:
                    # Dual Color (Split Masks)
                    color1 = ordered_colors[0]
                    color2 = ordered_colors[1]
                    
                    print(f"   [Dual {'Land' if is_colored_land else 'Artifact'}] Split Masks: {color1} (Left) / {color2} (Right)")
                    
                    # Apply Left Half (Normal)
                    suffix1 = get_land_suffix(color1)
                    self.apply_mask(suffix1, target_masks, right_half=False)
                    
                    # Apply Right Half
                    suffix2 = get_land_suffix(color2)
                    self.apply_mask(suffix2, target_masks, right_half=True)
                    
                else:
                    # 3+ Colors (Gold)
                    print(f"   [Multi {'Land' if is_colored_land else 'Artifact'}] 3+ Colors: Using Gold Land Frame as mask source")
                    self.apply_mask("lThumb.png", target_masks)

            self._wait_for_render()
            
        except Exception as e:
            print(f"   Error setting frame color: {e}", file=sys.stderr)
            # Debug: print available thumbs
            try:
                images = self.driver.find_elements(By.XPATH, "//div[@id='frame-picker']//img")
                srcs = [img.get_attribute('src') for img in images]
                print(f"      Available thumbnails: {srcs}", file=sys.stderr)
            except:
                pass
