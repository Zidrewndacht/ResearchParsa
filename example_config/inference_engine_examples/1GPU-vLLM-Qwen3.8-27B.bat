docker run --rm -it --gpus 1 ^
  -e ENABLE_PREFIX_CACHING=1 ^
  -e HF_HUB_OFFLINE=1 ^
  -v vllm-model-weights:/root/.cache/huggingface ^
  -v vllm-compile-cache:/root/.cache/vllm ^
  -p 127.0.0.1:8086:8086 --ipc=host ^
  vllm/vllm-openai:v0.28.0-x86_64-cu129-ubuntu2404 ^
	dbirks/Qwen3.8-27B-W4A16-AutoRound ^
	--host 0.0.0.0 --port 8086 ^
	--max-num-seqs 24 ^
	--max-num-batched-tokens 2048 ^
	--enable-prefix-caching ^
	--language-model-only ^
	--gpu-memory-utilization 0.948 ^
	--reasoning-parser qwen3 ^
	--max_model_len 131072 ^
	--tensor-parallel-size 1 ^
	--mamba-ssm-cache-dtype float16 ^
	--no-ray ^
	--disable_custom_all_reduce ^
	--kv_cache_dtype fp8_e4m3 ^
	--compilation-config "{\"max_cudagraph_capture_size\":24,\"custom_ops\":[\"+silu_and_mul\"],\"cudagraph_mode\":\"FULL_AND_PIECEWISE\",\"cudagraph_capture_sizes\":[1,4,8,16,24]}" ^
	--no-ray
pause