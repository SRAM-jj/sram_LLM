#!/bin/bash
# S.RAM! LLM 파인튜닝 스크립트 (MLX / MacBook M4)
# 사용 모델: Llama 3.2 3B Instruct (4bit quantized)

set -e

MODEL="mlx-community/Llama-3.2-3B-Instruct-4bit"
DATA_DIR="./training_data"
ADAPTER_DIR="./adapters"
FUSED_DIR="./sram_model"

echo "===================================="
echo "  S.RAM! LLM 파인튜닝 시작"
echo "===================================="

# 1. 가상환경 활성화
source venv/bin/activate

# 2. mlx-lm 설치
echo "[1/4] mlx-lm 설치 중..."
pip install mlx-lm -q

# 3. 훈련 데이터 생성
echo "[2/4] 훈련 데이터 생성 중..."
python prepare_training_data.py

# 4. LoRA 파인튜닝
echo "[3/4] LoRA 파인튜닝 시작..."
echo "      모델: $MODEL"
echo "      데이터: $DATA_DIR"
echo "      반복: 1000 iters (약 10~30분 소요)"
mlx_lm.lora \
    --model $MODEL \
    --train \
    --data $DATA_DIR \
    --iters 1000 \
    --batch-size 4 \
    --num-layers 8 \
    --adapter-path $ADAPTER_DIR

# 5. 어댑터 병합 (fuse)
echo "[4/4] 어댑터 병합 중..."
mlx_lm.fuse \
    --model $MODEL \
    --adapter-path $ADAPTER_DIR \
    --save-path $FUSED_DIR

echo ""
echo "===================================="
echo "  파인튜닝 완료!"
echo "  모델 저장 위치: $FUSED_DIR"
echo "===================================="
echo ""
echo "다음 단계: Ollama에 등록하려면 아래 명령 실행"
echo "  ollama create sram-ai -f Modelfile"
