# FastConformer Integration Guide for QuranCaption

This folder contains the files necessary to integrate your custom FastConformer AI Segmenting pipeline into the QuranCaption desktop application.

## Method 1: Drop-in Replacement (No Recompilation Required)
If you don't want to recompile QuranCaption, you can simply hijack the existing "Surah Splitter" option. 

1. Go to your installed QuranCaption `python` directory (or inside `src-tauri/python` if running from source).
2. Backup the original `local_surah_splitter_segmenter.py` and `surah_splitter_requirements.txt`.
3. Rename `local_fastconformer_segmenter.py` to `local_surah_splitter_segmenter.py` and place it in the `python` directory.
4. Rename `fastconformer_requirements.txt` to `surah_splitter_requirements.txt` and place it in the `python` directory.
5. Place your entire `src`, `data`, and `qua_sdk` (if local) next to the scripts, or ensure the `PROJECT_ROOT` path in the script points to this workspace.
6. When you click **"Surah Splitter"** in QuranCaption, it will now run your FastConformer pipeline with CPU/GPU support and a working progress bar!

## Method 2: Native Integration (Requires Node.js and Rust)
If you are developing QuranCaption from source and want to add a brand new option natively:

1. **Add to `LocalSegmentationEngine` (Rust)**
   In `src-tauri/src/segmentation/types.rs`, add:
   ```rust
   pub enum LocalSegmentationEngine {
       // ... existing options
       FastConformer,
   }
   
   impl LocalSegmentationEngine {
       pub fn from_raw(raw: &str) -> Result<Self, String> {
           match raw {
               // ... existing options
               "fast_conformer" | "fastconformer" => Ok(Self::FastConformer),
               // ...
           }
       }
       
       pub fn requirements_relative_path(&self) -> &'static str {
           match self {
               // ...
               Self::FastConformer => "python/fastconformer_requirements.txt",
           }
       }
       
       pub fn script_relative_path(&self) -> &'static str {
           match self {
               // ...
               Self::FastConformer => "python/local_fastconformer_segmenter.py",
           }
       }
       
       pub fn required_import_modules(&self) -> &'static [&'static str] {
           match self {
               // ...
               Self::FastConformer => &["numpy", "librosa", "pyloudnorm", "sherpa_onnx", "qua_sdk"],
           }
       }
   }
   ```

2. **Frontend UI Update (Svelte)**
   Add the option to your locale files (e.g. `src/lib/i18n/en/index.ts`) and your engine selection dropdown component (`src/lib/components/forms/engine-selection.svelte`). Use the id `"fast_conformer"`.

3. Place `local_fastconformer_segmenter.py` and `fastconformer_requirements.txt` inside the `src-tauri/python/` directory. Also copy your pipeline files there.

4. Build the app using `npm run tauri build`.
