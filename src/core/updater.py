import os
import sys
import json
import urllib.request
import urllib.error
import zipfile
import shutil
import tempfile
from pathlib import Path

def check_and_update(app_path: Path, log_callback=print):
    """
    Advanced Auto-Update mechanism using GitHub Releases API.
    Checks the local version.json against the latest GitHub Release tag.
    Downloads and extracts the .zip release if an update is found.
    """
    try:
        version_file = app_path / "version.json"
        local_version = "v0.0.0"
        
        if version_file.exists():
            try:
                with open(version_file, "r") as f:
                    local_version = json.load(f).get("version", "v0.0.0")
            except Exception:
                pass

        api_url = "https://api.github.com/repos/Iam-Muslim/QuranReciteToText/releases/latest"
        
        req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                release_data = json.loads(response.read().decode('utf-8'))
                latest_version = release_data.get("tag_name", local_version)
                zipball_url = release_data.get("zipball_url")
                
                if latest_version != local_version and zipball_url:
                    log_callback(f"[*] Auto-Updater: Found new version {latest_version} (Current: {local_version})")
                    log_callback(f"[*] Downloading update...")
                    
                    with tempfile.TemporaryDirectory() as tmpdir:
                        tmp_dir_path = Path(tmpdir)
                        zip_path = tmp_dir_path / "update.zip"
                        
                        req_zip = urllib.request.Request(zipball_url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req_zip, timeout=60) as r_zip, open(zip_path, 'wb') as f:
                            shutil.copyfileobj(r_zip, f)
                                    
                        extract_path = tmp_dir_path / "extracted"
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                            zip_ref.extractall(extract_path)
                            
                        extracted_folders = [f for f in extract_path.iterdir() if f.is_dir()]
                        if extracted_folders:
                            repo_folder = extracted_folders[0]
                            
                            # Overwrite current project directory
                            shutil.copytree(repo_folder, app_path, dirs_exist_ok=True)
                            
                            with open(version_file, "w") as f:
                                json.dump({"version": latest_version}, f)
                                
                            # Auto-sync dependencies (e.g. if qua_sdk was updated in vendor/ and requirements.txt)
                            req_path = app_path / "requirements.txt"
                            if req_path.exists():
                                log_callback(f"[*] Syncing dependencies...")
                                import subprocess
                                try:
                                    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_path)])
                                except Exception as e:
                                    log_callback(f"[*] Warning: Dependency sync failed: {e}")

                            log_callback(f"[*] Update complete! Restarting script...")
                            # Restart the script
                            os.execv(sys.executable, ['python'] + sys.argv)
    except urllib.error.URLError:
        log_callback("[*] Auto-update check bypassed (Offline or network timeout).")
    except Exception as e:
        # Ignore other network errors or permission issues
        log_callback(f"[*] Auto-update check bypassed (Error: {e})")
        pass
