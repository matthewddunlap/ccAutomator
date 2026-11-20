#!/usr/bin/env python3
"""
deck_reminder_report.py -- cross-check a decklist against Scryfall data and
report which cards carry the keyword abilities listed in reminder_map.json
(the same map --inject-reminder-text normalizes from).

Card data is resolved from the LOCAL Scryfall cache first (scryfall_cache.db);
cards not found there fall back to the Scryfall API (disable with --no-api).

Detection uses Scryfall's canonical `keywords` field (so Ward shows up even
though its text is just "Ward {2}"); cards without that field fall back to a
rules-text scan with the same detection rules as the injector.

Examples:
    python3 deck_reminder_report.py decks/mydeck.txt
    python3 deck_reminder_report.py decks/mydeck.txt --mapped-only
    python3 deck_reminder_report.py decks/mydeck.txt --no-api
    python3 deck_reminder_report.py decks/mydeck.txt --map my_map.json
    python3 deck_reminder_report.py decks/mydeck.txt --tokens
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automator_utils import (
    inject_ability_reminders,
    load_reminder_map,
    normalize_card_name,
    parse_card_file,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def open_cache(db_path):
    """Open the cache read-only; None when the file is absent/unusable."""
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.execute("SELECT 1 FROM cards LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def find_in_cache(con, name):
    """
    (card_data, 'cache') or (None, None).  Tries the exact lowercase name
    first, then a normalized (accent/case/whitespace-insensitive) scan.
    """
    row = con.execute("SELECT data FROM cards WHERE name = ? LIMIT 1",
                      (name.lower(),)).fetchone()
    if row:
        return json.loads(row[0]), 'cache'

    target = normalize_card_name(name)
    for (cache_name,) in con.execute("SELECT DISTINCT name FROM cards"):
        if normalize_card_name(cache_name) == target:
            row = con.execute("SELECT data FROM cards WHERE name = ? LIMIT 1",
                              (cache_name,)).fetchone()
            if row:
                return json.loads(row[0]), 'cache'
    return None, None


def find_in_api(name):
    """(card_data, 'api') or (None, None).  Lazy import keeps --no-api offline."""
    try:
        from scryfall_utils import ScryfallAPI, ScryfallAPIException
    except ImportError:
        print(f"   [api] scryfall_utils unavailable; cannot look up '{name}'",
              file=sys.stderr)
        return None, None
    try:
        results = ScryfallAPI().search_cards(f'name:"{name}"', unique="prints")
    except ScryfallAPIException as e:
        print(f"   [api] lookup failed for '{name}': {e}", file=sys.stderr)
        return None, None
    if results:
        return results[0], 'api'
    return None, None


def card_abilities(card_data, reminder_map):
    """
    List of mapped abilities the card has, in map order.
    Prefers the canonical keywords field; falls back to a rules-text scan
    (same detection as the injector).
    """
    abilities = []
    keywords = card_data.get('keywords') or []
    if keywords:
        for kw in keywords:
            kl = kw.lower()
            for key in reminder_map:
                # exact ('flying') or parameterized ('ward {2}' -> 'ward')
                if kl == key or kl.startswith(key + ' '):
                    if key not in abilities:
                        abilities.append(key)
        if abilities:
            return [k for k in reminder_map if k in abilities]

    oracle_text = card_data.get('oracle_text') or ''
    if oracle_text:
        _, abilities = inject_ability_reminders(oracle_text, reminder_map)
    return [k for k in reminder_map if k in abilities]


def find_token_for_card(card_data, con, use_api):
    """
    Given a card's Scryfall data, find the corresponding token cards it produces.
    Returns a dict of {token_type: [token_names]} or None if no tokens found.

    Token types are determined from the card's type_line (e.g., 'Token Creature', 'Token').
    """
    if not card_data:
        return None

    # Check if this card has related tokens in all_parts
    all_parts = card_data.get('all_parts', [])
    token_names = []

    for part in all_parts:
        if part.get('component') == 'token':
            token_names.append(part.get('name'))

    # If no tokens in all_parts, search the cache for tokens with this name as a subtype
    if not token_names:
        card_name = card_data.get('name', '')
        # Extract subtypes from type_line (e.g., "Legendary Creature - Human Warrior" -> ['Human', 'Warrior'])
        type_line = card_data.get('type_line', '')
        subtypes = []
        if ' - ' in type_line:
            subtype_str = type_line.split(' - ')[1]
            subtypes = subtype_str.split()

        if subtypes:
            # Look for tokens that match any of these subtypes
            token_types = set()
            for subtype in subtypes:
                token_types.add(subtype)

            # Search cache for tokens matching these types
            for token_type in token_types:
                token_query = f"%Token%{token_type}%"
                try:
                    rows = con.execute(
                        "SELECT data FROM cards WHERE name LIKE ? AND data LIKE '%Token%' LIMIT 10",
                        (f'%{token_type}%',)
                    ).fetchall()
                    for row in rows:
                        try:
                            data = json.loads(row[0])
                            if data.get('type_line', '').startswith('Token'):
                                # Extract token subtype from type_line
                                token_type_line = data.get('type_line', '')
                                if ' - ' in token_type_line:
                                    actual_subtype = token_type_line.split(' - ')[1].strip()
                                    if actual_subtype.lower() == token_type.lower():
                                        token_names.append(data.get('name'))
                                else:
                                    token_names.append(data.get('name'))
                        except:
                            pass
                except:
                    pass

    if not token_names:
        return None

    return {'Token': token_names}


def analyze_tokens(card_results, con, use_api):
    """
    Analyze a decklist's cards to find what tokens they need.
    Returns a dict of {token_name: [(card_name, count), ...]}
    """
    tokens_needed = {}

    for name, count, category, abilities, source in card_results:
        if source is None:
            # Card wasn't resolved, skip
            continue

        card_data, _ = source if isinstance(source, tuple) else (None, None)

        # Re-fetch card data if needed
        if not card_data:
            if con is not None:
                card_data, _ = find_in_cache(con, name)
            if not card_data:
                if use_api:
                    card_data, _ = find_in_api(name)
                else:
                    continue

        # Find tokens this card produces
        tokens = find_token_for_card(card_data, con, use_api)
        if tokens:
            for token_type, token_names in tokens.items():
                for token_name in token_names:
                    # Group by specific token name
                    key = token_name
                    if key not in tokens_needed:
                        tokens_needed[key] = []
                    tokens_needed[key].append((name, count))

    return tokens_needed


def main():
    parser = argparse.ArgumentParser(
        description="List the cards in a decklist that carry the keyword "
                    "abilities from reminder_map.json.")
    parser.add_argument("decklist", help="decklist file (one card per line, optional count prefix)")
    parser.add_argument("--map", default=None,
                        help="ability -> reminder JSON map (default: reminder_map.json next to this script)")
    parser.add_argument("--cache", default=None,
                        help="Scryfall cache DB (default: scryfall_cache.db next to this script)")
    parser.add_argument("--no-api", action="store_true",
                        help="do not fall back to the Scryfall API for cards missing from the cache")
    parser.add_argument("--mapped-only", action="store_true",
                        help="only show cards that carry at least one mapped ability")
    parser.add_argument("--tokens", action="store_true",
                        help="analyze decklist for token requirements")
    args = parser.parse_args()

    reminder_map = load_reminder_map(args.map)
    if not reminder_map:
        print("Error: reminder map is empty or unreadable -- nothing to match.", file=sys.stderr)
        sys.exit(1)

    cards = parse_card_file(args.decklist)
    unique = {}  # name -> entry, first occurrence wins (decklist order kept)
    for c in cards:
        unique.setdefault(c['name'], c)

    db_path = args.cache or os.path.join(HERE, 'scryfall_cache.db')
    con = open_cache(db_path)
    if con is None and not args.no_api:
        print(f"Note: cache '{os.path.basename(db_path)}' not usable; "
              "using the Scryfall API for every card.", file=sys.stderr)

    results = []  # (name, count, category, abilities, source)
    for name, c in unique.items():
        data, source = (None, None)
        if con is not None:
            data, source = find_in_cache(con, name)
        if data is None and not args.no_api:
            data, source = find_in_api(name)
        abilities = card_abilities(data, reminder_map) if data else []
        results.append((name, c.get('count', 1), c.get('category', 'deck'),
                        abilities, source))
    if con is not None:
        con.close()

    # Store the db_path for token analysis
    db_path_for_tokens = db_path if con is not None else None

    # ---- Report -------------------------------------------------------------
    map_path = args.map or os.path.join(HERE, 'reminder_map.json')
    print(f"Deck:   {os.path.basename(args.decklist)} — {len(unique)} unique card(s)")
    print(f"Map:    {os.path.basename(map_path)} — {len(reminder_map)} "
          f"abilities ({', '.join(reminder_map)})")
    src = f"cache {os.path.basename(db_path)}" if con is not None else "no cache"
    print(f"Source: {src}; API fallback {'off' if args.no_api else 'on'}")
    print()

    shown = [r for r in results if r[3] or not args.mapped_only]
    width = max(len(n) + (4 if cnt > 1 else 0) for n, cnt, _, _, _ in shown) \
        if shown else 0
    for name, count, category, abilities, source in shown:
        label = f"{name} (x{count})" if count > 1 else name
        suffix = f"  [{category}]" if category and category != 'deck' else ""
        if abilities:
            print(f"  {label:<{width}}  {', '.join(abilities)}{suffix}")
        elif not args.mapped_only:
            mark = f"  [{source}]" if source else "  (unresolved)"
            print(f"  {label:<{width}}  -{mark}")

    mapped = [r for r in results if r[3]]
    unresolved = [r[0] for r in results if r[4] is None]
    print()
    print(f"Cards with mapped abilities: {len(mapped)}/{len(unique)}")
    if mapped:
        counts = {}
        for _, _, _, abilities, _ in mapped:
            for a in abilities:
                counts[a] = counts.get(a, 0) + 1
        print("Per ability:")
        for a in reminder_map:
            if a in counts:
                print(f"  {a:<14} {counts[a]}")

    # ---- Token Analysis (optional) ------------------------------------------
    if args.tokens:
        print()
        print("=== Token Analysis ===")
        # Reopen cache for token analysis if it was closed
        token_con = open_cache(db_path_for_tokens) if db_path_for_tokens else None
        if token_con is None and not args.no_api:
            print(f"Note: cache not usable; using API for token lookups.", file=sys.stderr)
        tokens_needed = analyze_tokens(results, token_con, args.no_api)
        if token_con is not None:
            token_con.close()
        if tokens_needed:
            print("Tokens needed:")
            for token_name, cards in sorted(tokens_needed.items()):
                print(f"  {token_name}:")
                for card_name, card_count in cards:
                    print(f"    {card_name} (x{card_count})")
        else:
            print("No tokens needed.")

    if unresolved:
        print(f"Unresolved (not in cache or API): {', '.join(unresolved)}")


if __name__ == "__main__":
    main()
