import argparse
import re
import sys
import os
import json
from pathlib import Path
from automator import CardConjurerAutomator
from cc_file_editor import CcFileEditor
from automator_utils import (
    parse_card_file,
    split_basic_lands,
    apply_set_filters,
    build_scryfall_query,
    save_cardconjurer_file,
    BASIC_LAND_NAMES,
    DEFAULT_UPSCALER_MODEL,
    parse_set_list
)
import land_generator

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
    parser.add_argument(
        '--prime-frame',
        help="The name of the frame to select ONLY during priming (e.g., 'Seventh'). Useful for cc-file mode where main frame is baked in."
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
        '--pt-left',
        type=int,
        metavar='NUM',
        help="Add a {left#} tag to the Power/Toughness."
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
        '--rules-bounds-x',
        type=int,
        metavar='NUM',
        help="Adjust the X position of the rules text box by this amount."
    )

    parser.add_argument(
        '--rules-bounds-width',
        type=int,
        metavar='NUM',
        help="Adjust the width of the rules text box by this amount."
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
        choices=['selenium', 'cc-file', 'edit', 'combo', 'json'],
        default='selenium',
        help="Choose the card building method. 'json' generates .cardconjurer files directly without Selenium."
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

    # New arguments added here
    parser.add_argument('--flavor-font-size', type=int, help='Font size for flavor text')

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
    
    elif args.card_builder == 'json':
        if not args.input_file:
            parser.error("input_file is required for 'json' mode.")
        if not args.output_dir:
            # Default to downloads if not specified
            args.output_dir = 'downloads'
            
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
            pt_left=args.pt_left,
            pt_up=args.pt_up,
            pt_font_size=args.pt_font_size,
            pt_shadow=args.pt_shadow,
            pt_bold=args.pt_bold,

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

    # Handle 'json' mode - generate .cardconjurer files directly
    if args.card_builder == 'json':
        print(f"--- Starting JSON Mode for '{args.input_file}' ---")
        
        # Parse deck list
        all_cards = parse_card_file(args.input_file)
        if not all_cards:
            print("No valid card names found in the input file. Exiting.", file=sys.stderr)
            sys.exit(1)
            
        full_art_lands = []
        if args.full_art_basic_land:
            print("--- Full-Art Basic Land Mode Enabled ---")
            # Identify basic lands
            basic_land_cards = [c for c in all_cards if c['name'] in BASIC_LAND_NAMES]
            non_basic_cards = [c for c in all_cards if c['name'] not in BASIC_LAND_NAMES]
            
            if basic_land_cards:
                unique_land_types = sorted(list(set(c['name'] for c in basic_land_cards)))
                print(f"Found basic lands: {', '.join(unique_land_types)}")
                print("Generating full-art basic lands separately...")
                
                try:
                    full_art_lands = land_generator.generate_fullart_lands(
                        land_types=unique_land_types,
                        template_path='templates/full_art_basic_lands.cardconjurer',
                        output_path=None, # Return list instead of saving
                        set_selection=args.set_selection if args.set_selection else 'all',
                        include_sets=list(parse_set_list(args.basic_land_include_set if args.basic_land_include_set else args.include_set)),
                        exclude_sets=list(parse_set_list(args.basic_land_exclude_set if args.basic_land_exclude_set else args.exclude_set)),
                        scryfall_filter=args.scryfall_filter,
                        image_server_url=args.image_server if args.image_server else "http://mtgproxy:4242",
                        image_server_path=args.image_server_path,
                        art_path=args.art_path,
                        upscale_art=args.upscale_art,
                        ilaria_url=args.ilaria_url,
                        upscaler_model=args.upscaler_model,
                        upscaler_factor=args.upscaler_factor,
                        white_border=args.white_border,
                        # Text formatting args
                        pt_font_size=args.pt_font_size, pt_kerning=args.pt_kerning, pt_up=args.pt_up, pt_left=args.pt_left, pt_bold=args.pt_bold, pt_shadow=args.pt_shadow,
                        title_font_size=args.title_font_size, title_shadow=args.title_shadow, title_kerning=args.title_kerning, title_left=args.title_left, title_up=args.title_up,
                        type_font_size=args.type_font_size, type_shadow=args.type_shadow, type_kerning=args.type_kerning, type_left=args.type_left,
                        flavor_font=args.flavor_font, rules_down=args.rules_down
                    )
                    print(f"Generated {len(full_art_lands)} full-art basic land cards.")
                except Exception as e:
                    print(f"Error generating full-art lands: {e}", file=sys.stderr)
                
                # Update all_cards to only include non-basics for the main generator
                all_cards = non_basic_cards
            else:
                print("No basic lands found in deck list.")
        
        # Group cards by section
        from collections import defaultdict
        cards_by_section = defaultdict(list)
        for card in all_cards:
            cards_by_section[card['category']].append(card)
        
        # Initialize generator
        from seventh_generator import SeventhGenerator
        generator = SeventhGenerator(
            image_server_url=args.image_server if args.image_server else "http://mtgproxy:4242",
            download_dir=args.download_dir if hasattr(args, 'download_dir') else 'downloads',
            upload_secret=args.upload_secret,
            art_path=args.art_path,
            upscaler_model=args.upscaler_model if args.upscaler_model else DEFAULT_UPSCALER_MODEL
        )
        generator.upscale_art = args.upscale_art if args.upscale_art else False
        generator.ilaria_url = args.ilaria_url if args.ilaria_url else None
        
        # Map legacy filters to granular filters if needed
        spells_include = args.spells_include_set if args.spells_include_set else args.include_set
        spells_exclude = args.spells_exclude_set if args.spells_exclude_set else args.exclude_set
        land_include = args.basic_land_include_set if args.basic_land_include_set else args.include_set
        land_exclude = args.basic_land_exclude_set if args.basic_land_exclude_set else args.exclude_set
        
        # Process each section
        generated_cards = list(full_art_lands) # Start with full art lands
        total_cards = len(all_cards) + len(full_art_lands)
        failed_cards = []
        
        for section, section_cards in cards_by_section.items():
            print(f"\nProcessing section: {section} ({len(section_cards)} cards)")
            
            for card in section_cards:
                card_name = card['name']
                set_code = card.get('set')
                try:
                    # Generate card with section-specific filtering
                    card_json = generator.generate_card(
                        card_name=card_name,
                        section=section,
                        set_code=set_code,
                        scryfall_filter=args.scryfall_filter,
                        spells_include_set=spells_include,
                        spells_exclude_set=spells_exclude,
                        basic_land_include_set=land_include,
                        basic_land_exclude_set=land_exclude,
                        # Text modifications
                        title_font_size=args.title_font_size,
                        title_shadow=args.title_shadow,
                        title_kerning=args.title_kerning,
                        title_left=args.title_left,
                        title_up=args.title_up,
                        type_font_size=args.type_font_size,
                        type_shadow=args.type_shadow,
                        type_kerning=args.type_kerning,
                        type_left=args.type_left,
                        pt_font_size=args.pt_font_size,
                        pt_shadow=args.pt_shadow,
                        pt_kerning=args.pt_kerning,
                        pt_up=args.pt_up,
                        pt_left=args.pt_left,
                        pt_bold=args.pt_bold,
                        flavor_font_size=args.flavor_font_size,
                        white_border=args.white_border,
                        auto_fit_type=args.auto_fit_type,
                        image_server_url=args.image_server if args.image_server else "http://mtgproxy:4242"
                    )
                    
                    if card_json:
                        generated_cards.append(card_json)
                        print(f"  ✓ {card_name}")
                    else:
                        failed_cards.append(card_name)
                        print(f"  ✗ {card_name} (generation failed)")
                        
                except Exception as e:
                    failed_cards.append(card_name)
                    print(f"  ✗ {card_name}: {e}")
        
        # Save output file
        deck_name = Path(args.input_file).stem
        output_path = save_cardconjurer_file(
            generated_cards,
            deck_name,
            args.output_dir
        )
        
        # Summary
        print(f"\n{'='*60}")
        print(f"Generated {len(generated_cards)}/{total_cards} cards")
        if failed_cards:
            print(f"Failed cards ({len(failed_cards)}): {', '.join(failed_cards)}")
        print(f"Output: {output_path}")
        print(f"{'='*60}")
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
                rules_bounds_x=args.rules_bounds_x,
                rules_bounds_width=args.rules_bounds_width,
                pt_left=args.pt_left,
                pt_up=args.pt_up,
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
                        set_code = card_data.get('set')
                        print(f"Priming card {i+1}/{len(prime_cards)}: '{card_name}'{' (set: ' + set_code + ')' if set_code else ''}")
                        automator.process_and_capture_card(card_name, is_priming=True, set_code=set_code)
                    print("--- Renderer Priming Complete ---\n")

                print("--- Starting Main Card Processing (Preparation Only) ---")
                for i, card_data in enumerate(cards_to_process):
                    card_name = card_data['name']
                    category = card_data['category']
                    set_code = card_data.get('set')
                    print(f"--- Processing card {i+1}/{len(cards_to_process)} ---")
                    automator.process_and_capture_card(card_name, category=category, prepare_only=True, set_code=set_code)
                
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
                pt_left=args.pt_left,
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
            pt_left=args.pt_left,
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
            rules_bounds_x=args.rules_bounds_x,
            rules_bounds_width=args.rules_bounds_width,
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
            
            # Generate the full-art lands TEMPLATE (if needed)
            temp_lands_file = None
            if args.full_art_basic_land and basic_land_types:
                from land_generator import generate_template_project
                temp_lands_file = Path(args.output_dir if args.output_dir else '.') / '_temp_fullart_template.cardconjurer'
                print(f"\nGenerating full-art lands template...")
                generate_template_project(
                    template_path='templates/full_art_basic_lands.cardconjurer',
                    output_path=str(temp_lands_file)
                )
            
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
                        set_code = card_data.get('set')
                        print(f"Priming card {i}/{len(prime_cards)}: '{card_name}'{' (set: ' + set_code + ')' if set_code else ''}")
                        automator.process_and_capture_card(card_name, is_priming=True, set_code=set_code)
                    print("--- Renderer Priming Complete ---")
                else:
                    print(f"Warning: Prime file '{args.prime_file}' was provided but contained no valid card names.", file=sys.stderr)

            # --- Full-Art Basic Land Generation (Single Session) ---
            # Full-Art Basic Land Generation moved to end of workflow


            print("\n--- Starting Main Card Processing ---")
            # --- Main Processing Loop ---
            success_count = 0
            skipped_count = 0
            error_count = 0
            error_list = []

            if args.card_builder == 'selenium':
                from scryfall_cache import ScryfallCache
                cache = ScryfallCache()
                
                for i, card_data in enumerate(cards_to_process, 1):
                    card_name = card_data['name']
                    category = card_data['category']
                    set_code = card_data.get('set')
                    
                    # Pre-emptive Skip Check via Local Cache
                    if not args.overwrite:
                        local_card = cache.get_card(card_name, set_code=set_code)
                        if local_card:
                            from automator_utils import generate_safe_filename
                            safe_card = generate_safe_filename(local_card.get('name', card_name))
                            safe_set = generate_safe_filename(local_card.get('set', set_code)) if local_card.get('set') else 'unknown-set'
                            safe_num = generate_safe_filename(local_card.get('collector_number')) if local_card.get('collector_number') else 'no-num'
                            potential_filename = f"{safe_card}_{safe_set}_{safe_num}.png"
                            
                            if automator.should_skip_file(potential_filename):
                                print(f"--- Processing card {i}/{len(cards_to_process)} ---")
                                print(f"   Pre-emptive skip: '{potential_filename}' already exists.")
                                skipped_count += 1
                                continue

                    print(f"--- Processing card {i}/{len(cards_to_process)} ---")
                    try:
                        res = automator.process_and_capture_card(card_name, category=category, set_code=set_code)
                        if res['captured'] > 0:
                            success_count += 1
                        if res['skipped'] > 0 and res['captured'] == 0:
                            # If all selected prints were skipped, count as skipped card
                            skipped_count += 1
                        elif res['skipped'] > 0:
                            # Partial success? Still count as success for the main card
                            pass
                    except Exception as e:
                        print(f"   Error processing '{card_name}': {e}", file=sys.stderr)
                        error_count += 1
                        error_list.append(f"1 {card_name}{'|' + set_code if set_code else ''}")

            # --- Full-Art Basic Land Generation (Single Session) ---
            # Moved to end of workflow to prevent template masks from affecting main cards
            if args.full_art_basic_land and args.card_builder == 'selenium' and basic_land_types and temp_lands_file:
                print("\n" + "="*60)
                print("PHASE: Full-Art Basic Land Generation")
                print("="*60)
                
                # Explicitly disable the frame as requested by the user to ensure a clean slate
                try:
                    print("Disabling frame before full-art generation...")
                    automator.set_frame('false', wait=True)
                except Exception as e:
                    print(f"Warning: Could not disable frame (value='false'): {e}")

                try:
                    from scryfall_utils import ScryfallAPI
                    
                    # Load the template project
                    print(f"\n--- Loading template project from {temp_lands_file} ---")
                    automator.load_project_file(str(temp_lands_file))
                    
                    # Query Scryfall for specific lands to build
                    scryfall = ScryfallAPI()
                    
                    # Use basic land specific filters if provided, otherwise fall back to general filters
                    include_sets_arg = args.basic_land_include_set if args.basic_land_include_set else args.include_set
                    exclude_sets_arg = args.basic_land_exclude_set if args.basic_land_exclude_set else args.exclude_set
                    
                    include_sets = list(parse_set_list(include_sets_arg))
                    exclude_sets = list(parse_set_list(exclude_sets_arg))
                    
                    for land_type in basic_land_types:
                        print(f"\nProcessing {land_type}...")
                        
                        # Build Scryfall query
                        query_parts = [f'!"{land_type}"', 'type:land', 'type:basic', 'is:fullart', 'unique:prints']
                        if args.scryfall_filter:
                            query_parts.append(args.scryfall_filter)
                        
                        query = ' '.join(query_parts)
                        print(f"   Scryfall query: {query}")
                        cards = scryfall.search_cards(query)
                        
                        if not cards:
                            print(f"   No full-art {land_type}s found.")
                            continue
                            
                        # Filter sets
                        if include_sets:
                            include_lower = [s.lower() for s in include_sets]
                            cards = [c for c in cards if c.get('set', '').lower() in include_lower]
                        if exclude_sets:
                            exclude_lower = [s.lower() for s in exclude_sets]
                            cards = [c for c in cards if c.get('set', '').lower() not in exclude_lower]
                            
                        if not cards:
                            print(f"   No {land_type}s remaining after filtering.")
                            continue
                            
                        # Selection logic
                        selected_cards = []
                        if args.set_selection == 'all':
                            selected_cards = cards
                        elif args.set_selection == 'latest':
                            sorted_cards = sorted(cards, key=lambda c: c.get('released_at', ''), reverse=True)
                            selected_cards = [sorted_cards[0]] if sorted_cards else []
                        elif args.set_selection == 'earliest':
                            sorted_cards = sorted(cards, key=lambda c: c.get('released_at', ''))
                            selected_cards = [sorted_cards[0]] if sorted_cards else []
                        elif args.set_selection == 'random':
                            import random
                            selected_cards = [random.choice(cards)] if cards else []
                            
                        print(f"   Selected {len(selected_cards)} prints for {land_type}.")
                        
                        for card in selected_cards:
                            set_code = card.get('set', 'unk').upper()
                            collector_number = card.get('collector_number', '0')
                            card_name = land_type
                            
                            print(f"   Building {card_name} ({set_code} #{collector_number})...")
                            
                            # 1. Load the placeholder card
                            placeholder_name = f"fullArt-{land_type}"
                            try:
                                automator.load_saved_card(placeholder_name)
                            except Exception as e:
                                print(f"      Error loading placeholder '{placeholder_name}': {e}")
                                continue
                                
                            # 1.5 Force a new unique ID to prevent overwriting the placeholder when saving
                            # We check against existing saved cards to ensure no collisions, addressing the user's concern.
                            automator.driver.execute_script("""
                                if (window.card) {
                                    var savedCards = JSON.parse(localStorage.getItem('cardConjurerSavedCards') || '[]');
                                    var existingIds = new Set(savedCards.map(c => c.id));
                                    var newId;
                                    do {
                                        newId = Date.now().toString() + Math.random().toString();
                                    } while (existingIds.has(newId));
                                    card.id = newId;
                                }
                            """)

                            # 2. Process and Capture (Set Art, Text, Save)
                            # A. Prepare Art
                            final_art_url, type_line, _, _ = automator._prepare_art_asset(card_name, set_code, collector_number, scryfall_data=card)
                            
                            if final_art_url:
                                automator._apply_custom_art(card_name, set_code, collector_number, final_art_url)
                            
                            # B. Apply Text Mods
                            automator._apply_text_mods("Title", args.title_font_size, args.title_shadow, args.title_kerning, args.title_left)
                            # ... apply other mods ...
                            
                            # Apply White Border if enabled
                            if args.white_border:
                                automator.apply_white_border()
                            
                            # C. Save to Browser Storage
                            # We want to save it as "Mountain (SET #CN)"
                            automator._save_card_to_browser_storage(card_name, set_code, collector_number)
                            
                            # Capture Image
                            # Use the standard filename generation method to ensure consistency (e.g. snake_case)
                            output_filename = automator._generate_final_filename(card_name, set_code, collector_number)
                            automator.capture_card(output_filename)
                            
                            # Upload if needed
                            if args.upload_path:
                                # ... upload logic ...
                                pass

                except Exception as e:
                    print(f"\nError during full-art land generation: {e}", file=sys.stderr)
                finally:
                    # Clean up temp file
                    if temp_lands_file and temp_lands_file.exists():
                        temp_lands_file.unlink()
                        print(f"Cleaned up temporary file: {temp_lands_file}")
            
            elif args.card_builder == 'cc-file':
                print(f"\n--- Starting CC File Render Mode ---")
                
                prime_card_names_ccfile = []
                if args.prime_file:
                    prime_cards = parse_card_file(args.prime_file)
                    prime_card_names_ccfile = [c['name'] for c in prime_cards]

                # Render
                automator.render_project_file(
                    args.input_file, 
                    frame_name=args.frame, 
                    prime_card_names=prime_card_names_ccfile,
                    prime_frame_name=args.prime_frame
                )

            # --- Final Summary ---
            print("\n--- Summary ---")
            print(f"Success: {success_count}")
            print(f"Skipped: {skipped_count}")
            print(f"Error: {error_count}")
            
            if error_list:
                print("\n--- Summary of Errors ---")
                for err in error_list:
                    print(err)

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



            if args.no_close:
                print("\n--- Execution Paused (--no-close) ---")
                input("Press Enter to close the browser and exit...")

    except Exception as e:
        print(f"\nA critical error occurred during automation: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nAutomation complete.")

if __name__ == "__main__":
    main()
