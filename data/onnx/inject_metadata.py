# Import the onnx library to manipulate ONNX models.
import onnx
# Import the Path class from pathlib for robust path handling.
from pathlib import Path

"""
ONNX Metadata Injector

When converting NVIDIA NeMo models to ONNX for use in Sherpa-ONNX, the raw ONNX file
often lacks the internal metadata (like vocab_size, subsampling_factor, etc.) required
by the Sherpa runtime to correctly decode the acoustic emissions into text tokens.

This script forcefully injects those missing key-value pairs directly into the ONNX binary.
"""

# ==============================================================================
# 1. Path Resolution
# ==============================================================================
# Resolve the directory where this script is located.
# Calculate the absolute path of the parent directory of this script.
PROJECT_ROOT = Path(__file__).resolve().parent

# Define the add_meta_data function that takes a filename and a dictionary of metadata.
def add_meta_data(filename: str, meta_data: dict):
    """
    Loads an ONNX model, safely merges new metadata into it, and saves it back to disk.
    
    Args:
        filename (str): The path to the ONNX file.
        meta_data (dict): A dictionary of key-value pairs to inject.
    """
    # Print a status message indicating the model is being loaded.
    print(f"Loading {filename}...")
    # Load the entire ONNX model into memory using the onnx pip package.
    # Read the ONNX binary file from disk and store it in the 'model' variable.
    model = onnx.load(filename)
    
    # Step 1: Preserve existing metadata.
    # We iterate through the model's existing properties and keep only those
    # that we are NOT explicitly overriding in our new meta_data dictionary.
    # Initialize an empty list to hold the properties we want to keep.
    existing_props = []
    # Loop through every existing metadata property in the loaded ONNX model.
    for prop in model.metadata_props:
        # Check if the key of the current property is NOT in our dictionary of new metadata.
        if prop.key not in meta_data:
            # If it's not being overridden, append it to our list of properties to preserve.
            existing_props.append(prop)
            
    # Step 2: Clear out the old properties completely.
    # Delete all existing metadata properties from the model.
    del model.metadata_props[:]
    
    # Step 3: Add back the preserved old properties.
    # Extend the now-empty metadata_props list with the properties we decided to preserve.
    model.metadata_props.extend(existing_props)
    
    # Step 4: Inject our new required properties.
    # We iterate over our dictionary, create a new property object, and assign key/value.
    # Loop through every key-value pair in our new metadata dictionary.
    for key, value in meta_data.items():
        # Create a new metadata property object and add it to the model.
        meta = model.metadata_props.add()
        # Set the key of the new property.
        meta.key = key
        # Set the value of the new property, ensuring it is converted to a string.
        meta.value = str(value)
        # Print a status message showing what metadata is being added.
        print(f"Adding metadata: {key} = {value}")
        
    # Step 5: Save the modified binary back to disk.
    # Print a status message indicating the model is being saved.
    print(f"Saving {filename}...")
    # Write the modified ONNX model object back to the disk at the same filename.
    onnx.save(model, filename)
    # Print a success message after saving.
    print(f"Successfully updated metadata for {filename}")

# Standard Python idiom to ensure the code block runs only if the script is executed directly.
if __name__ == "__main__":
    # ==============================================================================
    # 2. Metadata Definition
    # ==============================================================================
    # These are the absolute, non-negotiable metadata requirements for the 
    # Sherpa-ONNX OfflineRecognizer to successfully boot up a NeMo FastConformer model.
    # Define a dictionary containing the required key-value pairs.
    meta_data = {
        # Specifies the architecture so Sherpa knows how to build the decoding graph.
        # Set the model_type to indicate a CTC-based BPE encoder-decoder.
        "model_type": "EncDecCTCModelBPE", 
        
        # Audio normalization expectation.
        # Set normalize_type to per_feature, which the model expects.
        "normalize_type": "per_feature", 
        
        # FastConformer uses 1024 BPE subword tokens. The CTC blank token adds +1.
        # Set the total vocabulary size to 1025.
        "vocab_size": "1025",              
        # CTC blank token is always the final ID
        # Set the blank token ID to the last index (1024).
        "blank_id": "1024",                
        
        # Input features are 80-bin Mel spectrograms.
        # Set the feature dimension to 80.
        "feature_dim": "80",               
        
        # CRITICAL: FastConformer aggressively downsamples time by 8x. 
        # Without this, Sherpa will generate timestamps that are 8x longer than reality.
        # Set the subsampling factor to 8.
        "subsampling_factor": "8",         
        
        # Acoustic parameters required to feed raw audio to the model.
        # Set the expected audio sample rate to 16000 Hz.
        "sample_rate": "16000",
        # Set the FFT window size to 512.
        "n_fft": "512",
        # Set the window length for the STFT to 400.
        "win_length": "400",
        # Set the hop length for the STFT to 160.
        "hop_length": "160",
        
        # Optional attribution metadata.
        # Add an author name for the model.
        "model_author": "Yazin",
        # Add a version number for the model.
        "version": "1"
    }
    
    # Target the quantized ONNX model.
    # We assume the model is in the exact same directory as this script.
    # Construct the path to the ONNX model file.
    model_path = PROJECT_ROOT / "fastconformer_ar_ctc_q8.onnx"
    
    # Check if the ONNX model file exists at the constructed path.
    if not model_path.exists():
        # Print an error message if the model file is not found.
        print(f"Error: Could not find {model_path}. Make sure the ONNX file exists in the directory.")
    # Execute this block if the file does exist.
    else:
        # Execute the injection.
        # Call the add_meta_data function to perform the injection on the model.
        add_meta_data(str(model_path), meta_data)