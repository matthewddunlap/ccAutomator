import json
import requests
import time
import sys

def fetch_scryfall_data(set_code, collector_number):
    url = f"https://api.scryfall.com/cards/{set_code.lower()}/{collector_number}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching {set_code} #{collector_number}: {e}")
        return None

def analyze_frames():
    with open('seventh_edition_samples.json', 'r') as f:
        samples = json.load(f)

    print(f"{'Card Name':<30} | {'Colors':<10} | {'Type':<30} | {'Frames Used'}")
    print("-" * 120)

    for sample in samples:
        key = sample['key']
        data = sample['data']
        set_code = data.get('infoSet')
        number = data.get('infoNumber')
        
        if not set_code or not number:
            print(f"Skipping {key}: Missing set/number")
            continue

        scryfall_data = fetch_scryfall_data(set_code, number)
        if not scryfall_data:
            continue
            
        colors = scryfall_data.get('colors', [])
        if not colors and 'card_faces' in scryfall_data:
             colors = scryfall_data['card_faces'][0].get('colors', [])
             
        type_line = scryfall_data.get('type_line', '')
        
        frames = []
        for frame in data.get('frames', []):
            src = frame.get('src', '')
            # Extract meaningful part of src (e.g., 'regular/w.png')
            if 'seventh/' in src:
                short_src = src.split('seventh/')[-1]
                frames.append(short_src)
        
        print(f"{key[:30]:<30} | {','.join(colors):<10} | {type_line[:30]:<30} | {frames}")
        time.sleep(0.1) # Respect rate limits

if __name__ == "__main__":
    analyze_frames()
