import os
import sys
import zipfile
import shutil
import subprocess
from pathlib import Path

def make_universal(whl_path: str):
    whl_file = Path(whl_path)
    if not whl_file.exists():
        print(f"Error: {whl_file} not found.")
        return

    # 1. Extract the wheel
    extract_dir = whl_file.with_name(whl_file.stem + "_extracted")
    print(f"Extracting {whl_file.name} to {extract_dir.name}...")
    with zipfile.ZipFile(whl_file, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)

    # 2. Find the .pyx file
    pyx_files = list(extract_dir.rglob("_dp_core.pyx"))
    if not pyx_files:
        print("Error: Could not find _dp_core.pyx in the extracted wheel.")
        return
    
    pyx_file = pyx_files[0]
    # Path relative to the extract dir for setup.py
    # Using forward slashes for Cython compatibility
    rel_pyx = pyx_file.relative_to(extract_dir).as_posix()

    # 3. Create a temporary setup.py
    setup_py_path = extract_dir / "setup.py"
    setup_py_content = f"""
from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules = cythonize("{rel_pyx}")
)
"""
    setup_py_path.write_text(setup_py_content.strip(), encoding="utf-8")

    # 4. Compile the extension natively for the current OS
    print(f"Compiling Cython extension for {sys.platform}...")
    try:
        subprocess.check_call(
            [sys.executable, "setup.py", "build_ext", "--inplace"],
            cwd=str(extract_dir)
        )
    except subprocess.CalledProcessError:
        print("Error compiling Cython extension. Make sure you have C++ build tools installed.")
        return

    # 5. Clean up compilation artifacts (keep .so / .pyd / .dylib)
    for c_file in extract_dir.rglob("_dp_core.c"):
        c_file.unlink()
    build_dir = extract_dir / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    setup_py_path.unlink()

    # 6. Ensure WHEEL file is tagged as 
    dist_info = list(extract_dir.glob("*.dist-info"))
    if dist_info:
        wheel_file = dist_info[0] / "WHEEL"
        if wheel_file.exists():
            content = wheel_file.read_text(encoding="utf-8")
            new_lines = []
            tag_added = False
            for line in content.splitlines():
                if line.startswith("Tag:"):
                    # Only add the universal tag once, discard other tags
                    if not tag_added:
                        new_lines.append("Tag: py3-none-any")
                        tag_added = True
                else:
                    new_lines.append(line)
            wheel_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # 7. Package back into a new  wheel
    parts = whl_file.name.split("-")
    if len(parts) >= 3:    
        new_whl_name = f"{parts[0]}-{parts[1]}-py3-none-any.whl"
    else:
        new_whl_name = f"{whl_file.stem}.whl"
    
    new_whl_path = whl_file.with_name(new_whl_name)
    print(f"Packaging into {new_whl_name}...")
    
    # Zip the contents of extract_dir directly
    with zipfile.ZipFile(new_whl_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(extract_dir)
                zipf.write(file_path, arcname)

    # 8. Clean up extracted directory
    shutil.rmtree(extract_dir)
    print(f"Done! {new_whl_name} created successfully.")
    print(f"It contains both the original binaries and the newly compiled ones for {sys.platform}.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python make_universal_whl.py <path_to_original_whl>")
        sys.exit(1)
    make_universal(sys.argv[1])
