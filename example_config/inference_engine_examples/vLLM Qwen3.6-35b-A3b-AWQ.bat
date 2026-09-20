@echo off
:: Sample vLLM (WSL Docker w/ enabled HW CUDA passthrough) launch command for screening model. Runs up to 128 parallel requests on a pair of RTX 3090 (48GB total VRAM)
:: This automatically downloads the model on the first load.
:: Keep machine mostly unnattended during vLLM inference via WSL, or have a separate GPU/iGPU for display on the host, otherwise performance will go straight down to zero during interaction due to context shift between VM and host.
:: This is set up for headless (or iGPU display). Reduce --gpu-memory-utilization if the same GPU runs vLLM and a display.

:: 1.  Start Docker Desktop if it isn’t running yet
tasklist /FI "IMAGENAME eq Docker Desktop.exe" 2>NUL | find /I "Docker Desktop.exe" >NUL
if errorlevel 1 (
    echo Starting Docker Desktop ...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
)

:: 2.  Wait until the Linux engine answers
:wait_engine
echo Waiting for Docker engine ...
docker version >NUL 2>&1
if errorlevel 1 (
    timeout /t 3 >NUL
    goto :wait_engine
)

docker run --rm -it --gpus all ^
  -e ENABLE_PREFIX_CACHING=1 ^
  -e HF_HUB_OFFLINE=0 ^
  -v /mnt/host/d/AI/weights/vLLM/HuggingFaceCache:/root/.cache/huggingface ^
  -p 127.0.0.1:8086:8086 --ipc=host ^
    vllm/vllm-openai:v0.28.0-x86_64-cu129-ubuntu2404 ^
    cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit ^
    --host 0.0.0.0 --port 8086 ^
    --max-num-seqs 128 ^
    --max-num-batched-tokens 4096 ^
    --enable-prefix-caching ^
    --enable-expert-parallel ^
    --language-model-only ^
    --pipeline-parallel-size 2 ^
    --gpu-memory-utilization 0.94 ^
    --reasoning-parser qwen3 ^
    --max_model_len 81920 ^
    --no-ray ^
    --disable_custom_all_reduce ^
    --compilation-config "{\"cudagraph_mode\":\"FULL_AND_PIECEWISE\"}"
pause

