@echo off
:: Sample vLLM (WSL Docker w/ enabled HW CUDA passthrough) launch command for main model. Runs up to 128 parallel requests on a pair of RTX 3090 (48GB total VRAM)
:: This automatically downloads the model on the first load.
:: vLLM strongly recommended for ResearchParsa initial classification/verification as it's optimized for heavy continuous batching. Tested >15x faster against llama.cpp (real world, in this very application)
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
	dbirks/Qwen3.8-27B-W4A16-AutoRound ^
	--safetensors-load-strategy prefetch ^
	--host 0.0.0.0 --port 8086 ^
	--max-num-seqs 128 ^
	--max-num-batched-tokens 2048 ^
	--enable-prefix-caching ^
	--language-model-only ^
	--tensor-parallel-size 2 ^
	--gpu-memory-utilization 0.94 ^
	--reasoning-parser qwen3 ^
	--max_model_len 262144 ^
	--disable_custom_all_reduce ^
	--kv_cache_dtype fp8_e4m3 ^
	--mamba-ssm-cache-dtype float16 ^
	--no-ray ^
    --compilation-config "{\"max_cudagraph_capture_size\":128,\"custom_ops\":[\"+rms_norm\",\"+silu_and_mul\"],\"cudagraph_mode\":\"FULL_AND_PIECEWISE\",\"cudagraph_capture_sizes\":[1,110,111,112,117,118,119,120,125,126,127,128]}"pause
pause

