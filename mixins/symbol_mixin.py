import time
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

# Card Conjurer normalises the rarity input via four .replace() calls
# (uncommon->u, common->c, rare->r, mythic->m) and falls back to 'c'.
# We can send either the long or short form here; hexproof requires the
# short form.
RARITY_CODE_MAP = {
    'common':   'c',
    'uncommon': 'u',
    'rare':     'r',
    'mythic':   'm',
    'special':  'r',     # promo/bonus prints: render as rare
    'bonus':    'm',
}


def _rarity_to_value(scryfall_rarity):
    if not scryfall_rarity:
        return 'c'
    return RARITY_CODE_MAP.get(str(scryfall_rarity).strip().lower(), 'c')


class SymbolMixin:
    """
    Mixin for handling interactions with the 'Set Symbol' tab in Card Conjurer.
    """

    def get_symbol_geometry(self):
        """
        Read the CURRENT card's set-symbol geometry from the app's `card` global.

        Card Conjurer keeps the active card as a JS object `card` (e.g. the
        block at `ccAutomator.py` that sets `card.id` proves the object exists).
        It carries the same fields as the .cardconjurer project files:
        `setSymbolX` / `setSymbolZoom` (normalized 0-1) and `setSymbolSource`.

        Returns:
            dict with keys 'x', 'zoom', 'source' (any may be None), or None if
            the app exposes no `card` object / it has no set symbol.
        """
        try:
            return self.driver.execute_script("""
                if (typeof card === 'undefined' || !card) { return null; }
                return {
                    'x':      card.setSymbolX,
                    'zoom':   card.setSymbolZoom,
                    'source': card.setSymbolSource || null
                };
            """)
        except Exception as e:
            print(f"      Could not read symbol geometry: {e}", file=sys.stderr)
            return None

    def set_set_symbol(self, set_code, rarity=None, source=None):
        """
        Configure the Set Symbol tab and trigger a fetch.

        Card Conjurer's `fetchSetSymbol()` reads three fields from the DOM:
          * `#set-symbol-code`     -- set code
          * `#set-symbol-rarity`   -- 'uncommon'/'rare'/'mythic'/'common' or c/u/r/m
          * `#set-symbol-source`   -- 'cardconjurer' | 'gatherer' | 'hexproof'
        and then composes a URL for that combination.  Historically this mixin
        only set the code and let rarity + source stay at whatever the app
        had from a previous card, so promo/commander sets (TRK, ECC, EOC, ...)
        landed on the 'cardconjurer' source which has no asset for them --
        producing an un-colourised or absent symbol.

        Args:
            set_code: Scryfall set code of the print, e.g. 'ecc'.  Case-insensitive.
            rarity:   Scryfall rarity string of the print ('common', 'uncommon',
                      'rare', 'mythic', 'special', 'bonus').  Omit to leave the
                      tab's current rarity alone (default behaviour: 'common').
            source:   One of 'cardconjurer', 'gatherer', 'hexproof'.
                      Omit to leave the tab's current source alone.
                      'cardconjurer' (the usual choice) uses Card Conjurer's
                      built-in asset set.
                      'hexproof' (https://api.hexproof.io) covers every official
                      set including promos (TRK, ECC, EOC, ...) and returns
                      Access-Control-Allow-Origin: * (which the app requires,
                      since it sets image.crossOrigin='anonymous' before drawing
                      the symbol to cardCanvas -- without it, an external host
                      that doesn't send CORS headers would taint the canvas and
                      break capture).
        """
        if not set_code:
            return

        set_code_lc = str(set_code).lower()
        print(f"   Setting Set Symbol: code='{set_code_lc}' "
              f"rarity={rarity or '<keep>'} source={source or '<keep>'}")

        try:
            self.symbol_tab.click()

            code_input = self.wait.until(
                EC.visibility_of_element_located((By.ID, 'set-symbol-code')))
            rarity_input = self.wait.until(
                EC.presence_of_element_located((By.ID, 'set-symbol-rarity')))
            if source is not None:
                source_input = self.wait.until(
                    EC.presence_of_element_located((By.ID, 'set-symbol-source')))

            def set_value(el, value):
                # Assigning .value directly is more reliable than send_keys
                # because it doesn't depend on focus / hidden inputs and works
                # for both <input> and <select>.
                self.driver.execute_script(
                    "arguments[0].value = arguments[1];", el, value)
                self.driver.execute_script(
                    "arguments[0].dispatchEvent(new Event('input'))", el)

            set_value(code_input, set_code_lc)
            if rarity is not None:
                set_value(rarity_input, _rarity_to_value(rarity))
            if source is not None:
                # <select> -- setting .value selects the option.  Do NOT
                # dispatch 'change' here: fetchSetSymbol() already reads the
                # current value of all three fields at call time, so a
                # premature change event just wastes an extra round-trip.
                self.driver.execute_script(
                    "arguments[0].value = arguments[1];", source_input, source)

            # Trigger the reload with the app's own handler so we get
            # exactly the same behaviour a user would get by pressing a
            # field manually.
            self.driver.execute_script("fetchSetSymbol();")
            print(f"      Set symbol code '{set_code_lc}' / "
                  f"rarity={_rarity_to_value(rarity) if rarity else rarity_input.get_attribute('value')} "
                  f"/ source={source or '(unchanged)'} fetched.")

            # Wait for the symbol image to load and the cardCanvas to
            # settle with the new symbol drawn.
            time.sleep(self.render_delay)

            # Verify the asset actually loaded.  fetchSetSymbol() is async,
            # so a 404'd / stale symbol used to render silently without its
            # set symbol and still count as success (H2).
            self._verify_symbol_loaded(set_code_lc, rarity, source)

        except Exception as e:
            print(f"      Error setting set symbol: {e}", file=sys.stderr)

    def _verify_symbol_loaded(self, set_code, rarity=None, source=None):
        """
        Check that the set symbol actually made it onto the card.

        Two failure modes after fetchSetSymbol():
          * 'stale'/'none' -- the app's `card.setSymbolSource` doesn't point
            at THIS card's asset (the fetch failed, or it never ran and the
            previous card's URL is still there).  For the 'cardconjurer'
            source we know the exact asset pattern
            (/img/setSymbols/official/{set}-{c|u|r|m}.svg) so a mismatch is
            definitive.
          * 'failed' -- the URL looks right but the asset itself 404s or is
            blocked by CORS.  We load it in-page with crossOrigin='anonymous'
            (the same way the app draws it to cardCanvas) so we see the same
            result the app sees.

        A failure prints a stderr warning and bumps self.symbol_failures
        (counted in the run summary) but does NOT abort -- the card is still
        produced, just without its set symbol.
        """
        expected = None
        if (source or '').lower() == 'cardconjurer' and rarity is not None:
            expected = f"{set_code}-{_rarity_to_value(rarity)}.svg"

        try:
            result = self.driver.execute_script("""
                var url = (typeof card !== 'undefined' && card && card.setSymbolSource)
                          ? card.setSymbolSource : '';
                var expected = arguments[0] || null;
                // 1) Does the recorded asset belong to THIS card?
                if (expected && url.indexOf(expected) === -1) { return 'stale'; }
                if (!url) { return 'none'; }
                // 2) Does the recorded asset actually load (CORS-aware)?
                return new Promise(function (resolve) {
                    var im = new Image();
                    im.crossOrigin = 'anonymous';
                    var done = false;
                    var finish = function (ok) {
                        if (!done) { done = true; resolve(ok ? 'ok' : 'failed'); }
                    };
                    im.onload = function () { finish(true); };
                    im.onerror = function () { finish(false); };
                    im.src = url;
                    setTimeout(function () {
                        finish(im.complete && im.naturalWidth > 0);
                    }, 10000);
                });
            """, expected)
        except Exception as e:
            print(f"      Could not verify set symbol load: {e}", file=sys.stderr)
            return  # unverifiable -- don't count against the run

        if result == 'ok':
            return

        self.symbol_failures += 1
        if result == 'stale':
            print(f"      WARNING: set symbol for set '{set_code}' was not applied "
                  f"(app's recorded symbol doesn't match the expected asset "
                  f"'{expected}'). The card will render WITHOUT its set symbol.",
                  file=sys.stderr)
        elif result == 'none':
            print(f"      WARNING: no set symbol recorded on the card for set "
                  f"'{set_code}' (app has no asset for this set/rarity?). "
                  f"The card will render WITHOUT its set symbol.", file=sys.stderr)
        else:
            print(f"      WARNING: set symbol asset for set '{set_code}' failed to "
                  f"load (404 or blocked by CORS). The card will render WITHOUT "
                  f"its set symbol.", file=sys.stderr)
