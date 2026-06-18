#!/usr/bin/env python3
'''Convert BAAI/bge-small-zh-v1.5 to ONNX format for lightweight embedding.
Run this script ONCE before packaging. Requires: pip install transformers torch optimum[onnxruntime]

Output:
  models/model.onnx       - ONNX model file
  models/tokenizer.json   - HuggingFace tokenizers file
'''

import os
import sys

MODEL_NAME = 'BAAI/bge-small-zh-v1.5'
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')

def main():
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from transformers import AutoTokenizer
    except ImportError:
        print('Missing dependencies. Install with:')
        print('  pip install optimum[onnxruntime] transformers')
        sys.exit(1)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print(f'Downloading and converting {MODEL_NAME} to ONNX...')
    
    # Export model to ONNX
    model = ORTModelForFeatureExtraction.from_pretrained(MODEL_NAME, export=True)
    model.save_pretrained(OUTPUT_DIR)
    
    # Save tokenizer
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    tokenizer.save_pretrained(OUTPUT_DIR)
    
    # Verify output
    files = os.listdir(OUTPUT_DIR)
    print(f'\nConversion complete! Files saved to {OUTPUT_DIR}:')
    for f in sorted(files):
        size = os.path.getsize(os.path.join(OUTPUT_DIR, f))
        print(f'  {f} ({size // 1024} KB)')
    
    has_onnx = any(f.endswith('.onnx') for f in files)
    has_tok = 'tokenizer.json' in files
    if has_onnx and has_tok:
        print('\nReady for packaging!')
    else:
        print('\nWARNING: Missing required files. Check the output.')

if __name__ == '__main__':
    main()
