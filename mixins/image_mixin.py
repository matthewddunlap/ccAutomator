import os
import sys
import requests
from pathlib import Path
from urllib.parse import urljoin
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from gradio_client import Client, file as gradio_file

from automator_utils import (
    generate_safe_filename,
    get_image_mime_type_and_extension,
)

class ImageMixin:
    def _trim_art_url(self, art_url_to_apply):
        """
        Trims the art URL if it matches the local server host, making it relative.
        """
        if not art_url_to_apply:
            return art_url_to_apply
            
        url_to_paste = art_url_to_apply
        
        # If the image server and the app are on the same host, we might need to provide a relative path.
        if self.image_server_url and self.app_url:
            try:
                from urllib.parse import urlparse
                parsed_server_url = urlparse(self.image_server_url)
                parsed_app_url = urlparse(self.app_url)

                if parsed_server_url.netloc == parsed_app_url.netloc:
                    # The servers are on the same host, so we should use a relative path.
                    parsed_art_url = urlparse(art_url_to_apply)
                    path = parsed_art_url.path.lstrip('/')
                    
                    # Card Conjurer's local server has a special /local_art/ root
                    if path.startswith('local_art/'):
                        url_to_paste = path[len('local_art/'):]
                    else:
                        url_to_paste = path

                    print(f"   Trimming URL for same-host server. Pasting: {url_to_paste}")
            except ImportError:
                pass
        return url_to_paste

    def enable_autofit(self):
        """
        Ensures the 'Autofit when setting art' checkbox is enabled.
        """
        if not self.autofit_art:
            return

        print("   Ensuring Autofit is enabled...")
        try:
            # Navigate to Art tab first to ensure element is reachable
            self.art_tab.click()
            
            autofit_checkbox = self.wait.until(EC.presence_of_element_located((By.ID, 'art-update-autofit')))
            if not autofit_checkbox.is_selected():
                # Click the parent label, which is more reliable for custom checkboxes
                label_for_autofit = self.driver.find_element(By.XPATH, "//label[.//input[@id='art-update-autofit']]")
                label_for_autofit.click()
                print("   'Autofit when setting art' checkbox enabled.")
            else:
                print("   'Autofit when setting art' checkbox already enabled.")
        except Exception as e:
            print(f"   Warning: Could not set the autofit checkbox. {e}", file=sys.stderr)

    def _apply_custom_art(self, card_name, set_name, collector_number, art_url_to_apply: str):
        """
        Applies custom art to the card in Card Conjurer.
        """
        if not art_url_to_apply:
            return

        url_to_paste = self._trim_art_url(art_url_to_apply)
        print(f"   Applying custom art from: {url_to_paste}")

        try:
            # Navigate to the art tab and paste the URL
            self.art_tab.click()

            # Handle Autofit Checkbox
            self.enable_autofit()
            
            art_url_input_selector = "//h5[contains(text(), 'Choose/upload your art')]/following-sibling::div//input[@type='url']"
            art_url_input = self.wait.until(EC.presence_of_element_located((By.XPATH, art_url_input_selector)))
            
            art_url_input.clear()
            art_url_input.send_keys(url_to_paste)

            # Press Enter to submit the URL and trigger the art load.
            art_url_input.send_keys(Keys.RETURN)

            # Wait for the new art to load and the canvas to stabilize
            print("   Waiting for custom art to apply...")
            self.current_canvas_hash = self._wait_for_canvas_stabilization(self.current_canvas_hash)

        except requests.exceptions.RequestException as e:
            print(f"   Network error checking for custom art '{art_url_to_apply}': {e}", file=sys.stderr)

    def _upload_image(self, image_data, filename):
        """
        Uploads the given image data to the configured server endpoint
        using the HTTP PUT method.
        """
        # --- THE FIX: Use requests.put and send raw data ---
        
        # 1. Construct the full, final URL for the file, including the filename.
        #    A PUT request needs the complete destination URL.
        full_upload_url = os.path.join(self.image_server_url, self.upload_path.lstrip('/'), filename)
        
        print(f"   Uploading to {full_upload_url} (using PUT)...")
        
        # 2. Set the Content-Type header so the server knows it's a PNG image.
        headers = {'Content-Type': 'image/png'}
        
        # 3. Add the optional security secret if provided.
        if self.upload_secret:
            headers['X-Upload-Secret'] = self.upload_secret

        try:
            # 4. Use requests.put() and send the image_data directly in the 'data' parameter.
            #    We also use raise_for_status() to automatically catch bad responses (like 403 Forbidden).
            response = requests.put(full_upload_url, data=image_data, headers=headers, timeout=60)
            response.raise_for_status()  # This will raise an HTTPError for 4xx or 5xx responses.

            # If raise_for_status() doesn't raise a HTTP error, the upload was successful.
            print(f"   Upload successful.")

        except requests.exceptions.HTTPError as e:
            # This catches specific HTTP errors like 403 Forbidden, 405 Method Not Allowed, 500 Server Error, etc.
            print(f"   Error: Upload failed with status {e.response.status_code}.", file=sys.stderr)
            print(f"   Server Response: {e.response.text}", file=sys.stderr)
        except requests.exceptions.RequestException as e:
            # This catches network-level errors (e.g., DNS failure, connection refused).
            print(f"   Error: A network error occurred during upload: {e}", file=sys.stderr)

    def _upload_art_asset(self, image_data, sub_dir, filename):
        """
        Uploads an art asset to the configured server endpoint.
        """
        if not self.image_server_url:
            print("   Error: --image-server is not set. Cannot upload art asset.", file=sys.stderr)
            return

        # Construct the full URL for the art asset
        full_upload_url = urljoin(self.image_server_url, os.path.join(self.art_path, sub_dir, filename))
        
        print(f"   Uploading art asset to {full_upload_url} (using PUT)...")
        
        headers = {'Content-Type': 'image/png'} # Assuming PNG for now, can be improved
        if self.upload_secret:
            headers['X-Upload-Secret'] = self.upload_secret

        try:
            response = requests.put(full_upload_url, data=image_data, headers=headers, timeout=60)
            response.raise_for_status()
            print(f"   Upload successful.")
        except requests.exceptions.HTTPError as e:
            print(f"   Error: Upload failed with status {e.response.status_code}.", file=sys.stderr)
            print(f"   Server Response: {e.response.text}", file=sys.stderr)
        except requests.exceptions.RequestException as e:
            print(f"   Error: A network error occurred during upload: {e}", file=sys.stderr)

    def _save_or_upload_image(self, img_bytes: bytes, sub_dir: str, filename: str):
        """
        Saves the image locally or uploads it to the image server, depending on configuration.
        """
        if not img_bytes:
            print(f"   Error: No image bytes provided for '{filename}' in '{sub_dir}'. Cannot save empty image.", file=sys.stderr)
            return

        if self.download_dir: # Local save mode
            try:
                # The art path is relative to the download dir
                local_save_dir = Path(self.download_dir) / self.art_path.strip('/') / sub_dir.strip('/')
                local_save_dir.mkdir(parents=True, exist_ok=True)
                local_file_path = local_save_dir / filename
                with open(local_file_path, 'wb') as f:
                    f.write(img_bytes)
                print(f"   Saved image locally to: {local_file_path}")
            except Exception as e:
                print(f"   Error: Local save error for '{filename}': {e}", file=sys.stderr)

        elif self.image_server_url: # Upload mode
            self._upload_art_asset(img_bytes, sub_dir, filename)
        else:
            print(f"   Warning: No output destination configured for '{filename}'. Image not saved/uploaded.", file=sys.stderr)

    def _fetch_image_bytes(self, url: str, purpose: str = "generic") -> bytes:
        if not url: return None
        try:
            print(f"   Fetching image for {purpose} from: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            # No api_delay_seconds for now, as we are not hitting Scryfall API directly for every image fetch
            return response.content
        except requests.exceptions.RequestException as e:
            print(f"   Error: Failed to fetch image for {purpose} from {url}: {e}", file=sys.stderr)
            return None
            
    def _check_if_file_exists_on_server(self, public_url: str) -> bool:
        if not public_url: return False
        try:
            r = requests.head(public_url, timeout=15, allow_redirects=True)
            if r.status_code == 200: print(f"   Exists: {public_url}"); return True
            if r.status_code == 404: print(f"   Not found: {public_url}"); return False
            print(f"   Warning: Status {r.status_code} checking {public_url}. Assuming not existent.", file=sys.stderr); return False
        except Exception as e: print(f"   Error checking {public_url}: {e}. Assuming not existent.", file=sys.stderr); return False

    def _upscale_image_with_ilaria(self, original_art_path_for_upscaler: str, filename: str, mime: str, outscale: int) -> bytes:
        if not self.ilaria_url:
            print("   Error: Ilaria URL not set. Upscaling will be skipped.", file=sys.stderr)
            return None
        if not original_art_path_for_upscaler:
            print(f"   Error: No original art path for '{filename}'. Cannot upscale without a source image.", file=sys.stderr)
            return None

        img_bytes = None
        # If original_art_path_for_upscaler is a local path (e.g., from self.download_dir)
        if self.download_dir and original_art_path_for_upscaler.startswith(self.image_server_path.strip('/')):
            local_path = Path(self.download_dir) / original_art_path_for_upscaler
            print(f"   Upscaling: Reading original image from local path: {local_path}")
            try:
                with open(local_path, "rb") as f:
                    img_bytes = f.read()
            except FileNotFoundError:
                print(f"   Error: Upscaling failed: Original image not found at local path {local_path}", file=sys.stderr)
                return None
            except Exception as e:
                print(f"   Error: Upscaling failed: Could not read local file {local_path}: {e}", file=sys.stderr)
                return None
        else: # Assume it's a URL
            img_bytes = self._fetch_image_bytes(original_art_path_for_upscaler, "Upscaling with gradio_client")

        if not img_bytes:
            print(f"   Error: Failed to get image bytes from {original_art_path_for_upscaler}. Cannot upscale without image data.", file=sys.stderr)
            return None

        try:
            print(f"   Connecting to Ilaria Upscaler at {self.ilaria_url} via gradio_client.")
            client = Client(self.ilaria_url)

            # Create a temporary file for gradio_client
            temp_dir = Path('/tmp') # Using /tmp for temporary files
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_input_path = temp_dir / f"ilaria_input_{generate_safe_filename(filename)}"
            
            with open(temp_input_path, "wb") as f:
                f.write(img_bytes)

            print(f"   Upscaling {filename} using model '{self.upscaler_model}' via gradio_client.")
            result = client.predict(
                img=gradio_file(str(temp_input_path)), # Pass Path object or string
                model_name=self.upscaler_model,
                denoise_strength=0.5, # Hardcoded for now, can be made configurable
                face_enhance=False,   # Hardcoded for now, can be made configurable
                outscale=outscale,
                api_name="/realesrgan"
            )

            # Gradio client returns a path to the result file
            if isinstance(result, tuple):
                result_path = result[0]
            else:
                result_path = result

            print(f"   Upscaled image path: {result_path}")

            with open(result_path, "rb") as f:
                upscaled_bytes = f.read()
            
            # Clean up temporary files
            os.remove(temp_input_path)
            os.remove(result_path) # Gradio client creates a temp file, remove it

            return upscaled_bytes

        except Exception as e:
            print(f"   Error: Gradio upscaling error for '{filename}': {e}", file=sys.stderr)
            return None

    def _get_scryfall_art_crop_url(self, card_name: str, set_code: str, collector_number: str) -> tuple[str, str]:
        """
        Fetches the art_crop URL for a given card from the Scryfall API.
        """
        search_url = f"https://api.scryfall.com/cards/{set_code}/{collector_number}"
        print(f"   Fetching Scryfall data for '{card_name}' ({set_code}/{collector_number}) from: {search_url}")
        try:
            response = requests.get(search_url, timeout=10)
            response.raise_for_status()
            card_data = response.json()
            
            art_crop_url = ""
            if 'image_uris' in card_data and 'art_crop' in card_data['image_uris']:
                art_crop_url = card_data['image_uris']['art_crop']
            elif 'card_faces' in card_data and card_data['card_faces']:
                for face in card_data['card_faces']:
                    if 'image_uris' in face and 'art_crop' in face['image_uris']:
                        art_crop_url = face['image_uris']['art_crop']
                        break
            
            type_line = card_data.get('type_line', '')
            if art_crop_url:
                print(f"   Found art_crop URL: {art_crop_url}")
                return art_crop_url, type_line
            else:
                print(f"   Warning: No art_crop URL found for '{card_name}' ({set_code}/{collector_number}).", file=sys.stderr)
                return None, None
        except requests.exceptions.RequestException as e:
            print(f"   Error fetching Scryfall data for '{card_name}' ({set_code}/{collector_number}): {e}", file=sys.stderr)
            return None, None

    def _prepare_art_asset(self, card_name: str, set_code: str, collector_number: str, scryfall_data: dict = None) -> tuple[str, str]:
        """
        Prepares the art asset for a card, including fetching, upscaling, and saving/uploading.
        Returns the URL of the final art asset to be used in Card Conjurer.
        """
        print(f"   Preparing art asset for '{card_name}' ({set_code}/{collector_number})...")
        
        # 1. Get original art_crop URL and type_line
        if scryfall_data:
            # Use provided data to avoid re-fetching
            art_crop_url = ""
            if 'image_uris' in scryfall_data and 'art_crop' in scryfall_data['image_uris']:
                art_crop_url = scryfall_data['image_uris']['art_crop']
            elif 'card_faces' in scryfall_data and scryfall_data['card_faces']:
                for face in scryfall_data['card_faces']:
                    if 'image_uris' in face and 'art_crop' in face['image_uris']:
                        art_crop_url = face['image_uris']['art_crop']
                        break
            type_line = scryfall_data.get('type_line', '')
            if art_crop_url:
                print(f"   Using provided Scryfall art_crop URL: {art_crop_url}")
            else:
                print(f"   Warning: No art_crop URL found in provided data for '{card_name}'.", file=sys.stderr)
        else:
            # Fetch from Scryfall API
            art_crop_url, type_line = self._get_scryfall_art_crop_url(card_name, set_code, collector_number)

        if not art_crop_url:
            print(f"   Warning: Could not get Scryfall art_crop URL for '{card_name}'. Skipping art preparation.", file=sys.stderr)
            return None, None

        final_art_source_url = art_crop_url
        hosted_original_art_url = None
        hosted_upscaled_art_url = None
        original_art_bytes_for_pipeline = None
        original_image_mime_type = None
        
        _, initial_ext_guess = os.path.splitext(art_crop_url.split('?')[0])
        if not initial_ext_guess or initial_ext_guess.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            initial_ext_guess = ".jpg"
        original_image_actual_ext = initial_ext_guess.lower()
        
        sanitized_card_name = generate_safe_filename(card_name)
        set_code_sanitized = generate_safe_filename(set_code)
        collector_number_sanitized = generate_safe_filename(collector_number)

        # --- Art Processing Pipeline ---
        # 1. Check for existing original art on server/local
        if self.image_server_url or self.download_dir:
            possible_extensions = [original_image_actual_ext] + [ext for ext in ['.jpg', '.png', '.jpeg', '.webp', '.gif'] if ext != original_image_actual_ext]
            for ext_try in possible_extensions:
                base_filename_check = f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}{ext_try}"
                potential_url = urljoin(self.image_server_url, os.path.join(self.art_path, "original", base_filename_check)) if self.image_server_url else None
                
                if potential_url and self._check_if_file_exists_on_server(potential_url):
                    print(f"   Found existing original art on server: {potential_url}")
                    hosted_original_art_url = potential_url
                    # We don't fetch bytes here, just confirm existence. Bytes will be fetched if upscaling is needed.
                    break
                elif self.download_dir:
                    local_path_check = Path(self.download_dir) / self.art_path.strip('/') / "original" / base_filename_check
                    if local_path_check.exists():
                        print(f"   Found existing original art locally: {local_path_check}")
                        # Construct a URL that points to the local file, assuming image_server_url is configured
                        if self.image_server_url:
                            hosted_original_art_url = urljoin(self.image_server_url, os.path.join(self.art_path, "original", base_filename_check))
                        else:
                            # If no image_server_url, we can't provide a hosted URL, but we know it exists locally
                            hosted_original_art_url = str(local_path_check) # This will be a local file path, not a URL
                        break
        
        # 2. Fetch original art bytes if not already hosted or if upscaling is enabled
        if not hosted_original_art_url or self.upscale_art:
            original_art_bytes_for_pipeline = self._fetch_image_bytes(art_crop_url, "Scryfall original")
            if original_art_bytes_for_pipeline:
                mime, ext = get_image_mime_type_and_extension(original_art_bytes_for_pipeline)
                if ext: original_image_actual_ext = ext
                if mime: original_image_mime_type = mime
                
                # Save/upload original if not already hosted
                if not hosted_original_art_url:
                    filename_to_output = f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}{original_image_actual_ext}"
                    self._save_or_upload_image(original_art_bytes_for_pipeline, "original", filename_to_output)
                    if self.image_server_url:
                        hosted_original_art_url = urljoin(self.image_server_url, os.path.join(self.art_path, "original", filename_to_output))
                    elif self.download_dir:
                        hosted_original_art_url = str(Path(self.download_dir) / self.art_path.strip('/') / "original" / filename_to_output)
            else:
                print(f"   Error: Failed to fetch original art from Scryfall for '{card_name}'. Cannot proceed with art preparation.", file=sys.stderr)
                return None

        # 3. Upscale if requested and original bytes are available
        if self.upscale_art and original_art_bytes_for_pipeline and self.ilaria_url:
            upscaled_dir = f"{generate_safe_filename(self.upscaler_model)}-{self.upscaler_factor}x"
            upscaled_filename_check = f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}.png" # Upscaled output is typically PNG

            # Check if upscaled version already exists
            expected_upscaled_server_url = urljoin(self.image_server_url, os.path.join(self.art_path, upscaled_dir, upscaled_filename_check)) if self.image_server_url else None
            expected_upscaled_local_path = Path(self.download_dir) / self.art_path.strip('/') / upscaled_dir / upscaled_filename_check if self.download_dir else None

            if (expected_upscaled_server_url and self._check_if_file_exists_on_server(expected_upscaled_server_url)) or \
               (expected_upscaled_local_path and expected_upscaled_local_path.exists()):
                print(f"   Found existing upscaled art for '{card_name}'.")
                if self.image_server_url:
                    hosted_upscaled_art_url = expected_upscaled_server_url
                elif self.download_dir:
                    hosted_upscaled_art_url = str(expected_upscaled_local_path)
            else:
                # Determine the path/URL to the original art for the upscaler
                # If we saved locally, the upscaler can read from a local path
                original_art_path_for_upscaler = hosted_original_art_url if self.download_dir else art_crop_url
                
                upscaled_bytes = self._upscale_image_with_ilaria(original_art_path_for_upscaler, f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}", original_image_mime_type, self.upscaler_factor)
                if upscaled_bytes:
                    _, upscaled_ext = get_image_mime_type_and_extension(upscaled_bytes)
                    upscaled_filename = f"{sanitized_card_name}_{set_code_sanitized}_{collector_number_sanitized}{upscaled_ext or '.png'}"
                    self._save_or_upload_image(upscaled_bytes, upscaled_dir, upscaled_filename)
                    if self.image_server_url:
                        hosted_upscaled_art_url = urljoin(self.image_server_url, os.path.join(self.art_path, upscaled_dir, upscaled_filename))
                    elif self.download_dir:
                        hosted_upscaled_art_url = str(Path(self.download_dir) / self.art_path.strip('/') / upscaled_dir / upscaled_filename)
        
        # 4. Determine the final art source URL to return
        if hosted_upscaled_art_url:
            final_art_source_url = hosted_upscaled_art_url
            print(f"   Using upscaled art: {final_art_source_url}")
        elif hosted_original_art_url:
            final_art_source_url = hosted_original_art_url
            print(f"   Using original hosted art: {final_art_source_url}")
        else:
            final_art_source_url = art_crop_url
            print(f"   Using Scryfall art_crop URL: {final_art_source_url}")

        return final_art_source_url, type_line
