import json
import sys
import os
from seventh_generator import SeventhGenerator
from unittest.mock import MagicMock

# Mock gradio_client if needed (though seventh_generator handles it now)
if 'gradio_client' not in sys.modules:
    sys.modules['gradio_client'] = MagicMock()

def normalize_frame(frame):
    # Normalize frame data for comparison
    # We care about 'name', 'src', and 'masks'
    norm = {
        'name': frame.get('name'),
        'src': frame.get('src'),
        'masks': []
    }
    for mask in frame.get('masks', []):
        norm['masks'].append({
            'name': mask.get('name'),
            'src': mask.get('src')
        })
    return norm

def verify_samples():
    with open('samples.cardconjurer', 'r') as f:
        expected_cards = json.load(f)

    generator = SeventhGenerator(image_server_url="http://mtgproxy:4242")
    
    print(f"Verifying {len(expected_cards)} cards...")
    print("-" * 60)
    
    failures = 0
    
    for expected in expected_cards:
        key = expected['key']
        data = expected['data']
        set_code = data.get('infoSet')
        number = data.get('infoNumber')
        name = data.get('text', {}).get('title', {}).get('text')
        
        print(f"Checking {key}...")
        
        # Generate
        generated_card = generator.generate_card(name, set_code, number)
        if not generated_card:
            print(f"  FAILED: Could not generate card")
            failures += 1
            continue
            
        gen_data = generated_card['data']
        
        # Compare Frames
        exp_frames = [normalize_frame(f) for f in data.get('frames', [])]
        gen_frames = [normalize_frame(f) for f in gen_data.get('frames', [])]
        
        if exp_frames != gen_frames:
            print(f"  FAILED: Frames do not match")
            print(f"    Expected: {json.dumps(exp_frames, indent=2)}")
            print(f"    Got:      {json.dumps(gen_frames, indent=2)}")
            failures += 1
            continue
            
        # Compare Text (Title, Type, Rules, Mana, PT)
        text_fields = ['title', 'type', 'rules', 'mana', 'pt']
        text_mismatch = False
        for field in text_fields:
            exp_text = data.get('text', {}).get(field, {}).get('text', '')
            gen_text = gen_data.get('text', {}).get(field, {}).get('text', '')
            
            # Normalize text (ignore flavor text separator differences if any)
            # Scryfall might use different newlines or spacing
            if exp_text != gen_text:
                # Allow minor differences?
                # For now, strict check
                print(f"  FAILED: Text mismatch in '{field}'")
                print(f"    Expected: {exp_text!r}")
                print(f"    Got:      {gen_text!r}")
                text_mismatch = True
        
        if text_mismatch:
            failures += 1
            continue
            
        print("  SUCCESS")
        
    print("-" * 60)
    if failures == 0:
        print("All samples verified successfully!")
    else:
        print(f"Verification failed with {failures} errors.")

if __name__ == "__main__":
    verify_samples()
