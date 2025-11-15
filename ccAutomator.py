import argparse
import re
import sys
from automator import CardConjurerAutomator

def parse_card_file(filepath):
    """
    Parses the input file to extract card names, ignoring the leading numbers.
    """
    card_names = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Use regex to ignore leading numbers and capture the rest of the line.
                match = re.match(r'^\d+\s+(.*)', line)
                if match:
                    card_names.append(match.group(1).strip())
    except FileNotFoundError:
        print(f"Error: Input file not found at '{filepath}'", file=sys.stderr)
        sys.exit(1)
    return card_names

def main():
    """
    Main entry point for the script. Parses arguments and orchestrates the automation.
    """
    parser = argparse.ArgumentParser(
        description="Automate card creation in Card Conjurer using Selenium.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--url',
        required=True,
        help="The URL for the Card Conjurer web app."
    )
    parser.add_argument(
        '--frame',
        required=True,
        help="The name of the frame to select from the dropdown (e.g., 'Seventh')."
    )

    parser.add_argument(
        '--print-selection',
        default='earliest',
        choices=['latest', 'earliest', 'random'],
        help="Which print to select for a card:\n"
             "'latest': First print in the list (most recent).\n"
             "'earliest': Last print in the list (oldest).\n"
             "'random': A random print from the matching list.\n"
             "(defaults to 'earliest')"
    )

    parser.add_argument(
        'input_file',
        help="A plain text file with a list of card names to process and capture.\n"
             "Format: <number> <Card Name>\n"
             "Example:\n"
             "1 Hidden Necropolis\n"
             "1 Star Charter"
    )
    parser.add_argument(
        '--prime-file',
        help="Optional: A plain text file with card names to prime the renderer before capture."
    )
    parser.add_argument(
        '--output-dir',
        default='output_images',
        help="Directory to save the card images. Defaults to 'output_images'."
    )
    parser.add_argument(
        '--no-headless',
        action='store_true',
        help="Run the browser in non-headless mode for debugging purposes."
    )

    args = parser.parse_args()

    card_names_to_process = parse_card_file(args.input_file)
    if not card_names_to_process:
        print("No valid card names found in the input file to process. Exiting.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(card_names_to_process)} cards to process for capture.")

    try:
        # Use a context manager to ensure the browser is closed properly
        with CardConjurerAutomator(url=args.url, download_dir=args.output_dir, headless=not args.no_headless, print_selection_strategy=args.print_selection) as automator:
            # 1. Set the desired frame style
            automator.set_frame(args.frame)

            # 2. (New) Run the priming step if a prime file is provided
            if args.prime_file:
                prime_card_names = parse_card_file(args.prime_file)
                if prime_card_names:
                    automator.prime_renderer(prime_card_names)
                else:
                    print(f"Warning: Prime file '{args.prime_file}' was provided but contained no valid card names.", file=sys.stderr)

            # 3. Process each card from the main input file
            print("\n--- Starting Main Card Processing ---")
            for i, card_name in enumerate(card_names_to_process, 1):
                print(f"--- Processing card {i}/{len(card_names_to_process)} ---")
                automator.import_and_save_card(card_name)

    except Exception as e:
        print(f"\nA critical error occurred during automation: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nAutomation complete.")

if __name__ == "__main__":
    main()
