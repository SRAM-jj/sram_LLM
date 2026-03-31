"""
LoRA 어댑터 병합 스크립트

파인튜닝 완료 후 어댑터를 베이스 모델에 병합해 완전한 모델을 생성.
병합된 모델은 GGUF 변환에 사용됨.

실행:
    python3 merge_adapter.py
"""

import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

BASE_MODEL  = os.getenv("BASE_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
ADAPTER_DIR = "./sram_adapter"
OUTPUT_DIR  = "./sram_model_merged"


def main():
    print(f"베이스 모델: {BASE_MODEL}")
    print(f"어댑터 경로: {ADAPTER_DIR}")
    print(f"출력 경로:   {OUTPUT_DIR}\n")

    print("모델 로드 중...")
    tokenizer = AutoTokenizer.from_pretrained(ADAPTER_DIR)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        device_map="cpu",  # 병합은 CPU에서 실행 (VRAM 절약)
    )

    print("어댑터 병합 중...")
    model = PeftModel.from_pretrained(model, ADAPTER_DIR)
    model = model.merge_and_unload()

    print(f"병합된 모델 저장 중: {OUTPUT_DIR}")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print(f"\n✅ 병합 완료. 저장: {OUTPUT_DIR}")
    print("\n다음 단계:")
    print("  1. GGUF 변환: python3 llama.cpp/convert_hf_to_gguf.py sram_model_merged/ --outtype f16 --outfile sram_model_f16.gguf")
    print("  2. 양자화:    llama-quantize sram_model_f16.gguf sram_model_q4.gguf Q4_K_M")
    print("  3. Ollama:    ollama create sram-ai -f Modelfile")


if __name__ == "__main__":
    main()
