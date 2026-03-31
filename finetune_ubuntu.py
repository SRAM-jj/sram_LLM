"""
S.RAM! LLM 파인튜닝 스크립트 (Ubuntu RTX 4070)

사전 준비:
    pip install transformers datasets peft trl torch accelerate bitsandbytes

HuggingFace 토큰 필요 (Llama 3.1 라이선스 동의 후 발급):
    huggingface-cli login

실행:
    python3 finetune_ubuntu.py

완료 후 흐름:
    어댑터 저장 (sram_adapter/) → 모델 병합 → GGUF 변환 → Ollama 등록
"""

import json
import os
import torch
from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig

# ── 설정 ──────────────────────────────────────────────────────
BASE_MODEL  = os.getenv("BASE_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
TRAIN_FILE  = "./training_data/train.jsonl"
VALID_FILE  = "./training_data/valid.jsonl"
OUTPUT_DIR  = "./sram_adapter"


# ── 데이터 로드 ───────────────────────────────────────────────
def load_jsonl(path):
    data = []
    with open(path) as f:
        for line in f:
            data.append(json.loads(line))
    return data


def main():
    print(f"베이스 모델: {BASE_MODEL}")
    print(f"훈련 데이터: {TRAIN_FILE}")
    print(f"출력 경로:   {OUTPUT_DIR}\n")

    # ── 토크나이저 ────────────────────────────────────────────
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ── 4bit 양자화 (QLoRA) ───────────────────────────────────
    # RTX 4070 VRAM 12GB 기준 — 4bit 양자화로 메모리 절약
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    # ── 모델 로드 ─────────────────────────────────────────────
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.float16,
    )
    model.config.use_cache = False

    # ── LoRA 설정 ─────────────────────────────────────────────
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    # ── 데이터셋 ──────────────────────────────────────────────
    train_dataset = Dataset.from_list(load_jsonl(TRAIN_FILE))
    valid_dataset = Dataset.from_list(load_jsonl(VALID_FILE))
    print(f"훈련 샘플: {len(train_dataset)}개")
    print(f"검증 샘플: {len(valid_dataset)}개\n")

    # ── 학습 설정 ─────────────────────────────────────────────
    training_args = SFTConfig(
        output_dir=OUTPUT_DIR,
        num_train_epochs=3,
        per_device_train_batch_size=4,
        per_device_eval_batch_size=4,
        gradient_accumulation_steps=2,
        learning_rate=2e-4,
        fp16=True,
        logging_steps=50,
        eval_strategy="steps",
        eval_steps=200,
        save_strategy="steps",
        save_steps=200,
        save_total_limit=2,
        load_best_model_at_end=True,
        warmup_ratio=0.05,
        max_seq_length=512,
    )

    # ── 학습 실행 ─────────────────────────────────────────────
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=valid_dataset,
        peft_config=lora_config,
        processing_class=tokenizer,
    )

    print("파인튜닝 시작...")
    trainer.train()
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print(f"\n✅ 파인튜닝 완료. 어댑터 저장: {OUTPUT_DIR}")
    print("\n다음 단계:")
    print("  1. 어댑터 병합:  python3 merge_adapter.py")
    print("  2. GGUF 변환:    python3 llama.cpp/convert_hf_to_gguf.py sram_model_merged/ --outtype f16")
    print("  3. 양자화:       llama-quantize sram_model_f16.gguf sram_model_q4.gguf Q4_K_M")
    print("  4. Ollama 등록:  ollama create sram-ai -f Modelfile")


if __name__ == "__main__":
    main()
