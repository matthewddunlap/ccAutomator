import argparse
import re
import sys
import os
import json
from pathlib import Path
from automator import CardConjurerAutomator
from cc_file_editor import CcFileEditor

def parse_card_file(filepath):
    """
    Parses the input file to extract card names and categories (e.g., from # Headers).
    Returns a list of dictionaries: [{'name': 'Card Name', 'category': 'CategoryName'}, ...]
    """
    cards = []
    current_category = 'deck' # Default category
    
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # Check for headers (lines starting with #)
                if line.startswith('#'):
                    # It's a header/category change, not just a comment
                    # Strip the # and whitespace to get category name
                    # e.g. "# Tokens" -> "tokens"
                    current_category = line.lstrip('#').strip().lower()
                    continue

                # Use regex to ignore leading numbers and capture the rest of the line.
                match = re.match(r'^\d+\s+(.*)', line)
                if match:
                    card_name = match.group(1).strip()
                    cards.append({'name': card_name, 'category': current_category})
                else:
                    # Assume the whole line is the card name if no number prefix
                    cards.append({'name': line, 'category': current_category})
                    
    except FileNotFoundError:
        print(f"Error: Input file not found at '{filepath}'", file=sys.stderr)
        sys.exit(1)
    return cards



class CustomArgumentParser(argparse.ArgumentParser):
    """
    Custom ArgumentParser that supports loading arguments from files with comment support.
    
    Usage: python script.py @config.conf
    
    Config file format:
    - One argument per line
    - Lines starting with # are comments
    - Inline comments (after #) are stripped
    - Blank lines are ignored
    """
    def convert_arg_line_to_args(self, arg_line):
        """
        Override to handle comments and blank lines in argument files.
        
        Args:
            arg_line: A single line from the argument file
            
        Returns:
            List of arguments parsed from the line (empty list if comment/blank)
        """
        # Strip whitespace
        arg_line = arg_line.strip()
        
        # Skip blank lines
        if not arg_line:
            return []
        
        # Skip comment lines (lines starting with #)
        if arg_line.startswith('#'):
            return []
        
        # Strip inline comments (everything after #)
        if '#' in arg_line:
            arg_line = arg_line.split('#', 1)[0].strip()
        
        # Skip if line became empty after stripping inline comment
        if not arg_line:
            return []
        
        # Return the argument as a single item
        # argparse expects each line to be one argument
        return [arg_line]

BASIC_LANDS = ['Plains', 'Island', 'Swamp', 'Mountain', 'Forest', 'Wastes']

def split_basic_lands(cards):
    """
    Split a list of cards into basic lands and non-basic cards.
    
    Args:
        cards: List of card dictionaries with 'name' and 'category' keys
    
    Returns:
        Tuple of (non_basic_cards, basic_land_types)
        - non_basic_cards: List of non-basic card dictionaries
        - basic_land_types: Set of unique basic land type names
    """
    non_basic = []
    basic_lands = set()
    
    for card in cards:
        card_name = card['name'] if isinstance(card, dict) else card
        if card_name in BASIC_LANDS:
            basic_lands.add(card_name)
        else:
            non_basic.append(card)
    
    return non_basic, basic_lands

def main():
    """
    Main entry point for the script. Parses arguments and orchestrates the automation.
    """
    parser = CustomArgumentParser(
        description="Automate card creation in Card Conjurer using Selenium.\n\n"
                    "Arguments can be loaded from configuration files using @filename syntax.\n"
                    "Multiple config files can be specified and will be processed in order.\n"
                    "Command-line arguments override config file settings.\n\n"
                    "Example: python ccAutomator.py @my.conf cards.txt\n"
                    "Example: python ccAutomator.py @base.conf @custom.conf --frame Modern cards.txt",
        formatter_class=argparse.RawTextHelpFormatter,
        fromfile_prefix_chars='@'
    )
    parser.add_argument(
        '--url',
        help="The URL for the Card Conjurer web app. Required for 'selenium' and 'cc-file' modes."
    )
    parser.add_argument(
        'input_file',
        nargs='?',
        help="The input file containing card names (for 'selenium' mode) or the .cardconjurer file (for 'cc-file' or 'edit' mode)."
    )
    parser.add_argument(
        '--frame',
        help="The name of the frame to select from the dropdown (e.g., 'Seventh'). Required for 'selenium' and 'cc-file' modes."
    )

    # --- START OF MODIFIED ARGUMENTS ---
    # Legacy arguments (mutually exclusive with granular arguments)
    legacy_group = parser.add_argument_group('Legacy Filtering Options')
    legacy_group.add_argument(
        '--include-set',
        help="Whitelist of sets to capture (applies to ALL cards). Cannot be used with granular filters."
    )
    legacy_group.add_argument(
        '--exclude-set',
        help="Blacklist of sets to ignore (applies to ALL cards). Cannot be used with granular filters."
    )

    # Granular arguments
    granular_group = parser.add_argument_group('Granular Filtering Options')
    granular_group.add_argument(
        '--spells-include-set',
        help="Whitelist of sets for SPELLS (non-basic lands)."
    )
    granular_group.add_argument(
        '--spells-exclude-set',
        help="Blacklist of sets for SPELLS (non-basic lands)."
    )
    granular_group.add_argument(
        '--basic-land-include-set',
        help="Whitelist of sets for BASIC LANDS."
    )
    granular_group.add_argument(
        '--basic-land-exclude-set',
        help="Blacklist of sets for BASIC LANDS."
    )
    # --- END OF MODIFIED ARGUMENTS ---
    parser.add_argument(
        '--set-selection',
        default='earliest',
        choices=['latest', 'earliest', 'random', 'all'],
        help="Determines the final capture logic after filtering:\n"
             "For '--card-selection cardconjurer':\n"
             "  'all': Capture every print that survives the filters.\n"
             "  'latest'/'earliest'/'random': Pick a representative print, then capture all prints from its set.\n"
             "For '--card-selection scryfall':\n"
             "  'all': Capture all unique art prints from Scryfall that survive filters.\n"
             "  'latest'/'earliest'/'random': Pick a single print (latest/earliest/random) matching unique Scryfall art.\n"
             "(defaults to 'earliest')"
    )
    parser.add_argument(
        '--card-selection',
        choices=['scryfall', 'cardconjurer'],
        help="Determines the source for card versions. Required for 'selenium' mode."
    )
    parser.add_argument(
        '--no-match-selection',
        default='earliest',
        choices=['skip', 'latest', 'earliest', 'random', 'all'],
        help="Defines the behavior when a Scryfall query (with or without filters) fails to find a match.\n"
             "'skip': Skip the card entirely.\n"
             "'latest'/'earliest'/'random'/'all': Apply this strategy to the available Card Conjurer prints as a fallback.\n"
             "(defaults to 'earliest')"
    )
    parser.add_argument(
        '--render-delay',
        type=float,
        default=1.5,
        help="Seconds to wait after selecting a print before capturing. (default: 1.5)"
    )
    parser.add_argument(
        '--prime-file',
        help="Optional: A plain text file with card names to prime the renderer before capture."
    )
    parser.add_argument(
        '--no-headless',
        action='store_true',
        help="Run the browser in non-headless mode for debugging purposes."
    )

    parser.add_argument(
        '--white-border',
        action='store_true',
        help="Apply the white border to the card frame."
    )

    parser.add_argument(
        '--black-border',
        action='store_true',
        help="Remove the white border (if present) to revert to black border."
    )

    # Power/Toughness Arguments
    parser.add_argument(
        '--pt-bold',
        action='store_true',
        help="Wrap the Power/Toughness text in {bold} tags."
    )

    parser.add_argument(
        '--pt-font-size',
        type=int,
        metavar='NUM',
        help="Add a {fontsize#} tag to the Power/Toughness text."
    )

    parser.add_argument(
        '--pt-kerning',
        type=int,
        metavar='NUM',
        help="Add a {kerning#} tag to the Power/Toughness text."
    )
    parser.add_argument(
        '--pt-shadow',
        type=int,
        metavar='NUM',
        help="Add a {shadow#} tag to the Power/Toughness text."
    )

    parser.add_argument(
        '--pt-up',
        type=int,
        metavar='NUM',
        help="Add a {up#} tag to the Power/Toughness text."
    )

    # Title Arguments
    parser.add_argument(
        '--title-font-size', type=int, metavar='NUM', help="Add a {fontsize#} tag to the Title text.")
    parser.add_argument(
        '--title-shadow', type=int, metavar='NUM', help="Add a {shadow#} tag to the Title text.")
    parser.add_argument(
        '--title-kerning', type=int, metavar='NUM', help="Add a {kerning#} tag to the Title text.")
    parser.add_argument(
        '--title-left', type=int, metavar='NUM', help="Add a {left#} tag to the Title text.")
    parser.add_argument(
        '--title-up', type=int, metavar='NUM', help="Add a {up#} tag to the Title text.")

    # Type Line Arguments
    parser.add_argument(
        '--type-font-size', type=int, metavar='NUM', help="Add a {fontsize#} tag to the Type text.")
    parser.add_argument(
        '--type-shadow', type=int, metavar='NUM', help="Add a {shadow#} tag to the Type text.")
    parser.add_argument(
        '--type-kerning', type=int, metavar='NUM', help="Add a {kerning#} tag to the Type text.")
    parser.add_argument(
        '--type-left', type=int, metavar='NUM', help="Add a {left#} tag to the Type text.")

    parser.add_argument(
        '--auto-fit-type',
        action='store_true',
        help="Automatically adjust Type line font size based on character count thresholds."
    )

    parser.add_argument(
        '--flavor-font',
        type=int,
        metavar='NUM',
        help="If rules text contains {flavor}, inserts a {fontsize#} tag immediately after it."
    )

    parser.add_argument(
        '--rules-down',
        type=int,
        metavar='NUM',
        help="Add a {down#} tag to the Rules text."
    )

    parser.add_argument(
        '--rules-bounds-y',
        type=int,
        metavar='NUM',
        help="Adjust the Y position of the rules text box by this amount."
    )

    parser.add_argument(
        '--rules-bounds-height',
        type=int,
        metavar='NUM',
        help="Adjust the height of the rules text box by this amount."
    )

    parser.add_argument(
        '--hide-reminder-text',
        action='store_true',
        help="Check the 'Hide reminder text' checkbox."
    )

    parser.add_argument(
        '--image-server',
        help="The base URL of the web server where custom art is stored (e.g., 'http://mtgproxy:4242')."
    )
    parser.add_argument(
        '--image-server-path',
        help="The path on the image server where the art files are located (e.g., '/local_art/upscaled/')."
    )
    parser.add_argument(
        '--art-path',
        default='/local_art/art/',
        help="The base path on the image server for art assets (default: '/local_art/art/')."
    )

    parser.add_argument(
        '--autofit-art',
        action='store_true',
        help="Check the 'Autofit when setting art' checkbox before applying custom art."
    )

    parser.add_argument(
        '--upscale-art',
        action='store_true',
        help="Enable Ilaria upscaling for custom art."
    )
    parser.add_argument(
        '--ilaria-url',
        help="The URL for the Ilaria upscaling service (e.g., 'https://matthewddunlap-ilaria.hf.space/')."
    )
    parser.add_argument(
        '--upscaler-model',
        default='RealESRGAN_x2plus',
        help="The specific model to use for Ilaria upscaling (default: 'RealESRGAN_x2plus')."
    )
    parser.add_argument(
        '--upscaler-factor',
        type=int,
        default=4,
        help="The factor by which to upscale the image (default: 4)."
    )

    # --- START OF MODIFIED ARGUMENTS ---
    # Create a mutually exclusive group for the output destination (optional in parser, enforced manually)
    output_group = parser.add_mutually_exclusive_group()
    
    output_group.add_argument(
        '--output-dir',
        help="Directory to save the card images locally."
    )
    output_group.add_argument(
        '--upload-path',
        help="If specified, uploads the final PNG to this path on the --image-server (e.g., '/upload')."
    )
    
    parser.add_argument(
        '--upload-secret',
        help="Optional: A secret key sent in the 'X-Upload-Secret' header for authentication."
    )
    parser.add_argument(
        '--scryfall-filter',
        help="Optional: Arbitrary Scryfall query filters to append to the base query (e.g., 'lang:en' or 'is:fullart')."
    )
    
    parser.add_argument(
        '--save-cc-file',
        action='store_true',
        help="Save the Card Conjurer project file (.cardconjurer) containing all processed cards."
    )

    parser.add_argument(
        '--no-close',
        action='store_true',
        help="Keep the browser open after processing is complete (for debugging)."
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help="Enable verbose debug logging."
    )

    parser.add_argument(
        '--card-builder',
        choices=['selenium', 'cc-file', 'edit', 'combo'],
        default='selenium',
        help="Choose the card building method."
    )
    
    parser.add_argument(
        '--full-art-basic-land',
        action='store_true',
        help="Generate full-art basic lands instead of using Card Conjurer's default basic lands. "
             "When enabled, basic lands in the deck will be processed separately using a custom template."
    )
    # --- END OF MODIFIED ARGUMENTS ---

    overwrite_group = parser.add_argument_group('Overwrite Options')
    overwrite_group.add_argument(
        '--overwrite',
        action='store_true',
        help="If a file with the same name exists on the server, overwrite it. Default is to skip."
    )
    overwrite_group.add_argument(
        '--overwrite-older-than',
        type=str,
        metavar='TIME',
        help="Overwrite if the server file is OLDER than the given timestamp (yyyy-mm-dd-hh-mm-ss) or relative time (e.g., 5m, 2h)."
    )
    overwrite_group.add_argument(
        '--overwrite-newer-than',
        type=str,
        metavar='TIME',
        help="Overwrite if the server file is NEWER than the given timestamp (yyyy-mm-dd-hh-mm-ss) or relative time (e.g., 5m, 2h)."
    )

    # --- Land Generation Arguments ---
    parser.add_argument('--generate-lands', action='store_true', help="Generate full-art basic lands from a template.")
    parser.add_argument('--land-types', type=str, help="Comma-separated list of land types (e.g., 'Mountain,Island') for generation.")
    parser.add_argument('--template', type=str, help="Path to the template .cardconjurer file for land generation.")

    args = parser.parse_args()

    # --- Land Generation Mode ---
    if args.generate_lands:
        if not args.land_types or not args.template:
            parser.error("--generate-lands requires --land-types and --template.")
        
        from land_generator import generate_lands
        output_file = args.output_dir if args.output_dir else "generated_lands.cardconjurer"
        # If output_dir is a directory, join with default filename, else treat as filename
        if os.path.isdir(output_file):
            output_file = os.path.join(output_file, "generated_lands.cardconjurer")
            
        image_server = args.image_server if args.image_server else "http://mtgproxy:4242"
        generate_lands(args.template, args.land_types, output_file, image_server)
        sys.exit(0)

    # --- Manual Validation based on Mode ---
    if args.card_builder == 'selenium':
        if not args.url:
            parser.error("--url is required for 'selenium' mode.")
        if not args.card_selection:
            parser.error("--card-selection is required for 'selenium' mode.")
        if not args.frame:
            parser.error("--frame is required for 'selenium' mode.")
        if not (args.output_dir or args.upload_path):
            parser.error("One of --output-dir or --upload-path is required for 'selenium' mode.")
            
    elif args.card_builder == 'cc-file':
        if not args.url:
            parser.error("--url is required for 'cc-file' mode.")
        # Frame is optional for cc-file (defaults to what's in the file)
        if not (args.output_dir or args.upload_path):
            parser.error("One of --output-dir or --upload-path is required for 'cc-file' mode.")
            
    # 'edit' mode does not require frame, card-selection, or output options (it saves to file)

    # --- Validation ---
    if args.overwrite_older_than and args.overwrite_newer_than:
        parser.error("Cannot use --overwrite-older-than and --overwrite-newer-than together.")

    if args.upload_path and not args.image_server:
        parser.error("--upload-path requires --image-server to be set.")

    if args.upload_secret and not args.upload_path:
        parser.error("--upload-secret is only valid when using --upload-path.")

    # Check for mutual exclusivity between legacy and granular filters
    has_legacy = args.include_set or args.exclude_set
    has_granular = (args.spells_include_set or args.spells_exclude_set or 
                    args.basic_land_include_set or args.basic_land_exclude_set)

    if has_legacy and has_granular:
        parser.error("Cannot mix legacy filters (--include-set/--exclude-set) with granular filters "
                     "(--spells-*-set/--basic-land-*-set). Please use one or the other.")

    # Determine if we are in local save mode or upload mode
    save_locally = True if args.output_dir else False

    # Handle 'edit' mode separately as it doesn't require the browser
    if args.card_builder == 'edit':
        print(f"--- Starting Edit Mode for '{args.input_file}' ---")
        
        editor = CcFileEditor(args.input_file)
        editor.apply_edits(
            title_kerning=args.title_kerning,
            title_font_size=args.title_font_size,
            title_shadow=args.title_shadow,
            title_left=args.title_left,
            title_up=args.title_up,
            type_kerning=args.type_kerning,
            type_font_size=args.type_font_size,
            type_shadow=args.type_shadow,
            type_left=args.type_left,
            pt_kerning=args.pt_kerning,
            pt_font_size=args.pt_font_size,
            pt_shadow=args.pt_shadow,
            pt_bold=args.pt_bold,
            pt_up=args.pt_up,
            flavor_font=args.flavor_font,
            rules_down=args.rules_down,
            white_border=args.white_border,
            black_border=args.black_border,
            auto_fit_type=args.auto_fit_type
        )
        
        # Determine output filename
        input_path = Path(args.input_file)
        output_filename = f"{input_path.stem}_edited.cardconjurer"
        output_path = os.path.abspath(output_filename)
        
        editor.save(output_path)
        sys.exit(0)



    # For Selenium modes, we need to parse the input file ONLY if it's 'selenium' mode
    cards_to_process = []
    basic_land_types = set()
    
    if args.card_builder in ['selenium', 'combo']:
        all_cards = parse_card_file(args.input_file)
        if not all_cards:
            print("No valid card names found in the input file to process. Exiting.", file=sys.stderr)
            sys.exit(1)
        
        # Split basic lands if full-art mode is enabled
        if args.full_art_basic_land and args.card_builder == 'selenium':
            cards_to_process, basic_land_types = split_basic_lands(all_cards)
            print(f"Full-art basic land mode enabled:")
            print(f"  - {len(cards_to_process)} non-basic cards to process via Selenium")
            print(f"  - {len(basic_land_types)} unique basic land types: {', '.join(sorted(basic_land_types))}")
        else:
            cards_to_process = all_cards
            print(f"Found {len(cards_to_process)} cards to process for capture.")
    elif args.card_builder == 'cc-file':
        print(f"Mode 'cc-file': Will render project file '{args.input_file}'.")

    if args.card_builder == 'combo':
        print("--- Starting Combo Mode (Selenium Prep -> JSON Edit -> Render) ---")
        
        try:
            # --- Phase 1: Selenium Prep ---
            print("\n--- Phase 1: Selenium Preparation ---")
            input_path_obj = Path(args.input_file)
            temp_project_file = f"{input_path_obj.stem}.cardconjurer"
            
            with CardConjurerAutomator(
                url=args.url,
                download_dir=args.output_dir if args.output_dir else '.',
                headless=not args.no_headless,
                include_sets=args.include_set,
                exclude_sets=args.exclude_set,
                spells_include_sets=args.spells_include_set,
                spells_exclude_sets=args.spells_exclude_set,
                basic_land_include_sets=args.basic_land_include_set,
                basic_land_exclude_sets=args.basic_land_exclude_set,
                card_selection_strategy=args.card_selection,
                set_selection_strategy=args.set_selection,
                no_match_selection=args.no_match_selection,
                render_delay=args.render_delay,
                white_border=False, # Applied in Phase 2/3
                image_server=args.image_server,
                image_server_path=args.image_server_path,
                art_path=args.art_path,
                autofit_art=args.autofit_art,
                upscale_art=args.upscale_art,
                ilaria_url=args.ilaria_url,
                upscaler_model=args.upscaler_model,
                upscaler_factor=args.upscaler_factor,
                upload_path=args.upload_path,
                upload_secret=args.upload_secret,
                scryfall_filter=args.scryfall_filter,
                rules_bounds_y=args.rules_bounds_y,
                rules_bounds_height=args.rules_bounds_height,
                hide_reminder_text=args.hide_reminder_text,
                title_up=args.title_up,
                save_cc_file=True, # Force save for combo mode
                overwrite=args.overwrite,
                overwrite_older_than=args.overwrite_older_than,
                overwrite_newer_than=args.overwrite_newer_than,
                debug=args.debug,
                auto_fit_type=args.auto_fit_type
            ) as automator:
                
                # Clear any existing saved cards to start fresh
                automator.clear_saved_cards()
                
                # Apply global settings
                automator.enable_autofit()
                automator.set_frame(args.frame, wait=False)
                automator.apply_rules_text_bounds_mods()
                automator.apply_hide_reminder_text()
                
                if args.prime_file:
                    prime_cards = parse_card_file(args.prime_file)
                    print(f"--- Starting Renderer Priming with {len(prime_cards)} cards ---")
                    for i, card_data in enumerate(prime_cards):
                        card_name = card_data['name']
                        print(f"Priming card {i+1}/{len(prime_cards)}: '{card_name}'")
                        automator.process_and_capture_card(card_name, is_priming=True)
                    print("--- Renderer Priming Complete ---\n")

                print("--- Starting Main Card Processing (Preparation Only) ---")
                for i, card_data in enumerate(cards_to_process):
                    card_name = card_data['name']
                    category = card_data['category']
                    print(f"--- Processing card {i+1}/{len(cards_to_process)} ---")
                    automator.process_and_capture_card(card_name, category=category, prepare_only=True)
                
                # Download the prepared project file
                automator.download_saved_cards(temp_project_file)
                print("--- Phase 1 Complete: Project file prepared. ---")
                
            # --- Phase 2: JSON Edit ---
            print("\n--- Phase 2: JSON Editing ---")
            prep_file_path = os.path.join(args.output_dir if args.output_dir else '.', temp_project_file)
            edited_project_file = temp_project_file.replace('.cardconjurer', '_edited.cardconjurer')
            
            editor = CcFileEditor(prep_file_path)
            editor.apply_edits(
                pt_bold=args.pt_bold,
                pt_shadow=args.pt_shadow,
                pt_font_size=args.pt_font_size,
                pt_kerning=args.pt_kerning,
                pt_up=args.pt_up,
                title_font_size=args.title_font_size,
                title_shadow=args.title_shadow,
                title_kerning=args.title_kerning,
                title_left=args.title_left,
                title_up=args.title_up,
                type_font_size=args.type_font_size,
                type_shadow=args.type_shadow,
                type_kerning=args.type_kerning,
                type_left=args.type_left,
                flavor_font=args.flavor_font,
                rules_down=args.rules_down,
                white_border=args.white_border,
                black_border=args.black_border,
                auto_fit_type=args.auto_fit_type
            )
            editor.save(os.path.join(args.output_dir if args.output_dir else '.', edited_project_file))
            print(f"--- Phase 2 Complete: Edited file saved to {edited_project_file} ---")

            # --- Phase 3: Render ---
            print("\n--- Phase 3: Rendering ---")
            with CardConjurerAutomator(
                url=args.url,
                download_dir=args.output_dir if args.output_dir else '.',
                headless=not args.no_headless,
                render_delay=args.render_delay,
                image_server=args.image_server,
                image_server_path=args.image_server_path,
                upload_path=args.upload_path,
                upload_secret=args.upload_secret,
                rules_bounds_y=args.rules_bounds_y,
                rules_bounds_height=args.rules_bounds_height,
                hide_reminder_text=args.hide_reminder_text,
                overwrite=args.overwrite,
                overwrite_older_than=args.overwrite_older_than,
                overwrite_newer_than=args.overwrite_newer_than,
                debug=args.debug,
                title_up=None,
                auto_fit_type=False # Disable auto-fit in Phase 3 as it's handled in Phase 2
            ) as automator:
                 edited_file_full_path = os.path.join(args.output_dir if args.output_dir else '.', edited_project_file)
                 
                 prime_card_names_phase3 = []
                 if args.prime_file:
                     # Parse prime file again, extracting just names for render_project_file
                     prime_cards_data = parse_card_file(args.prime_file)
                     prime_card_names_phase3 = [c['name'] for c in prime_cards_data]
                     
                 automator.render_project_file(edited_file_full_path, frame_name=args.frame, prime_card_names=prime_card_names_phase3)
                 
            print("--- Combo Mode Complete ---")
            
            if args.no_close:
                print("\n--- Execution Paused (--no-close) ---")
                input("Press Enter to close the browser and exit...")
                
        except Exception as e:
            print(f"\nA critical error occurred during combo mode: {e}", file=sys.stderr)
        sys.exit(0)

    try:
        # Debug: Print the value of auto_fit_type
        print(f"DEBUG: args.auto_fit_type = {getattr(args, 'auto_fit_type', 'MISSING')}")
        print(f"DEBUG: args.image_server = {getattr(args, 'image_server', 'MISSING')}")

        with CardConjurerAutomator(
            url=args.url,
            # Pass the output directory, which might be None if uploading
            download_dir=args.output_dir,
            headless=not args.no_headless,
            include_sets=args.include_set,
            exclude_sets=args.exclude_set,
            spells_include_sets=args.spells_include_set,
            spells_exclude_sets=args.spells_exclude_set,
            basic_land_include_sets=args.basic_land_include_set,
            basic_land_exclude_sets=args.basic_land_exclude_set,
            card_selection_strategy=args.card_selection,
            set_selection_strategy=args.set_selection,
            no_match_selection=args.no_match_selection,
            render_delay=args.render_delay,
            white_border=args.white_border,
            pt_bold=args.pt_bold,
            pt_shadow=args.pt_shadow,
            pt_font_size=args.pt_font_size,
            pt_kerning=args.pt_kerning,
            pt_up=args.pt_up,
            title_font_size=args.title_font_size,
            title_shadow=args.title_shadow,
            title_kerning=args.title_kerning,
            title_left=args.title_left,
            title_up=args.title_up,
            type_font_size=args.type_font_size,
            type_shadow=args.type_shadow,
            type_kerning=args.type_kerning,
            type_left=args.type_left,
            flavor_font=args.flavor_font,
            rules_down=args.rules_down,
            rules_bounds_y=args.rules_bounds_y,
            rules_bounds_height=args.rules_bounds_height,
            hide_reminder_text=args.hide_reminder_text,
            image_server=args.image_server,
            image_server_path=args.image_server_path,
            art_path=args.art_path,
            autofit_art=args.autofit_art,
            upscale_art=args.upscale_art,
            ilaria_url=args.ilaria_url,
            upscaler_model=args.upscaler_model,
            upscaler_factor=args.upscaler_factor,
            upload_path=args.upload_path,
            upload_secret=args.upload_secret,
            scryfall_filter=args.scryfall_filter,
            save_cc_file=args.save_cc_file,
            overwrite=args.overwrite,
            overwrite_older_than=args.overwrite_older_than,
            overwrite_newer_than=args.overwrite_newer_than,
            debug=args.debug,
            auto_fit_type=args.auto_fit_type
        ) as automator:
            
            # Only apply these mods in selenium mode.
            # For cc-file, render_project_file handles setting the frame and applying mods per card.
            if args.card_builder == 'selenium':
                automator.set_frame(args.frame, wait=False)
                automator.apply_rules_text_bounds_mods()
                automator.apply_hide_reminder_text()

            if args.prime_file and args.card_builder == 'selenium':
                prime_cards = parse_card_file(args.prime_file)
                if prime_cards:
                    print(f"\n--- Starting Renderer Priming with {len(prime_cards)} cards ---")
                    for i, card_data in enumerate(prime_cards, 1):
                        card_name = card_data['name']
                        print(f"Priming card {i}/{len(prime_cards)}: '{card_name}'")
                        automator.process_and_capture_card(card_name, is_priming=True)
                    print("--- Renderer Priming Complete ---")
                else:
                    print(f"Warning: Prime file '{args.prime_file}' was provided but contained no valid card names.", file=sys.stderr)

            print("\n--- Starting Main Card Processing ---")
            # --- Main Processing Loop ---
            if args.card_builder == 'selenium':
                for i, card_data in enumerate(cards_to_process, 1):
                    card_name = card_data['name']
                    category = card_data['category']
                    print(f"--- Processing card {i}/{len(cards_to_process)} ---")
                    automator.process_and_capture_card(card_name, category=category)
            
            elif args.card_builder == 'cc-file':
                print(f"\n--- Starting CC File Render Mode ---")
                
                prime_card_names_ccfile = []
                if args.prime_file:
                    prime_card_names_ccfile = parse_card_file(args.prime_file)

                # Render
                automator.render_project_file(args.input_file, frame_name=args.frame, prime_card_names=prime_card_names_ccfile)

            if args.save_cc_file and args.card_builder == 'selenium':
                # In JSON mode, we already generated the file, but maybe the user wants the *final* state
                # after rendering (which might have minor diffs). 
                # But usually JSON mode implies we have the file.
                # However, let's keep this logic for Selenium mode primarily.
                print("\n--- Saving Card Conjurer Project File ---")
                # Derive output filename from input filename
                input_path = Path(args.input_file)
                output_filename = f"{input_path.stem}.cardconjurer"
                automator.download_saved_cards(output_filename)

        # Phase 2: Generate and render full-art basic lands (if enabled)
        if args.full_art_basic_land and args.card_builder == 'selenium' and basic_land_types:
            print("\n" + "="*60)
            print("PHASE 2: Full-Art Basic Land Generation")
            print("="*60)
            
            # Generate the full-art lands JSON
            from land_generator import generate_fullart_lands
            
            temp_lands_file = Path(args.output_dir if args.output_dir else '.') / '_temp_fullart_lands.cardconjurer'
            
            print(f"\nGenerating full-art lands for: {', '.join(sorted(basic_land_types))}")
            
            try:
                # Use basic land specific filters if provided, otherwise fall back to general filters
                include_sets_arg = args.basic_land_include_set if args.basic_land_include_set else args.include_set
                exclude_sets_arg = args.basic_land_exclude_set if args.basic_land_exclude_set else args.exclude_set
                
                # Parse set lists using helper
                from automator_utils import parse_set_list
                include_sets = list(parse_set_list(include_sets_arg))
                exclude_sets = list(parse_set_list(exclude_sets_arg))

                generate_fullart_lands(
                    land_types=list(basic_land_types),
                    template_path='templates/full_art_basic_lands.cardconjurer',
                    output_path=str(temp_lands_file),
                    image_server_url=args.image_server if args.image_server else 'http://172.17.1.216:4242',
                    include_sets=include_sets,
                    exclude_sets=exclude_sets,
                    set_selection=args.set_selection,
                    scryfall_filter=args.scryfall_filter,
                    # Image processing args
                    image_server_path=args.image_server_path,
                    art_path=args.art_path,
                    upscale_art=args.upscale_art,
                    ilaria_url=args.ilaria_url,
                    upscaler_model=args.upscaler_model,
                    upscaler_factor=args.upscaler_factor,
                    upload_path=args.upload_path,
                    upload_secret=args.upload_secret,
                    download_dir=args.output_dir if args.output_dir else '.',
                    white_border=args.white_border
                )
                
                # Relaunch browser to render the full-art lands
                print("\n--- Relaunching browser for full-art land rendering ---")
                
                with CardConjurerAutomator(
                    url=args.url,
                    download_dir=args.output_dir if args.output_dir else '.',
                    headless=not args.no_headless,
                    white_border=False, # Disable Selenium white border as it's applied in JSON for full-art lands
                    pt_bold=False, # Disable P/T mods for basic lands
                    pt_font_size=None,
                    pt_kerning=None,
                    pt_up=None,
                    pt_shadow=None,
                    title_font_size=args.title_font_size,
                    title_shadow=args.title_shadow,
                    title_kerning=args.title_kerning,
                    title_left=args.title_left,
                    title_up=args.title_up,
                    type_font_size=None, # Disable Type mods for basic lands
                    type_shadow=None,
                    type_kerning=None,
                    type_left=None,
                    flavor_font=args.flavor_font,
                    rules_down=args.rules_down,
                    image_server=args.image_server,
                    image_server_path=args.image_server_path,
                    art_path=args.art_path,
                    autofit_art=args.autofit_art,
                    upscale_art=args.upscale_art,
                    ilaria_url=args.ilaria_url,
                    upscaler_model=args.upscaler_model,
                    upscaler_factor=args.upscaler_factor,
                    upload_path=args.upload_path,
                    upload_secret=args.upload_secret,
                    scryfall_filter=args.scryfall_filter,
                    save_cc_file=args.save_cc_file,
                    overwrite=args.overwrite,
                    overwrite_older_than=args.overwrite_older_than,
                    overwrite_newer_than=args.overwrite_newer_than,
                    debug=args.debug,
                    auto_fit_type=False # Disable auto-fit for full-art lands to prevent crashes
                ) as lands_automator:
                    # Render the full-art lands (skip frame selection - template has frames)
                    print(f"\n--- Rendering full-art basic lands from {temp_lands_file} ---")
                    lands_automator.render_project_file(str(temp_lands_file), frame_name=None, prime_card_names=[])
                
                # Clean up temp file unless --save-cc-file is set
                if not args.save_cc_file and temp_lands_file.exists():
                    temp_lands_file.unlink()
                    print(f"Cleaned up temporary file: {temp_lands_file}")
                elif args.save_cc_file:
                    # Rename to permanent file
                    final_name = Path(args.output_dir if args.output_dir else '.') / f"{Path(args.input_file).stem}_fullart_lands.cardconjurer"
                    temp_lands_file.rename(final_name)
                    print(f"Saved full-art lands project file: {final_name}")
                    
            except Exception as e:
                print(f"\nError during full-art land generation: {e}", file=sys.stderr)
                if temp_lands_file.exists():
                    temp_lands_file.unlink()
                raise

            if args.no_close:
                print("\n--- Execution Paused (--no-close) ---")
                input("Press Enter to close the browser and exit...")

    except Exception as e:
        print(f"\nA critical error occurred during automation: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nAutomation complete.")

if __name__ == "__main__":
    main()
