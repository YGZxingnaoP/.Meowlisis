import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"  # 国内镜像


from huggingface_hub import snapshot_download

base_dir = os.path.dirname(os.path.abspath(__file__))

models = {
    "BAAI/bge-small-zh-v1.5": os.path.join(base_dir, "mem0model-small"),
    "BAAI/bge-large-zh-v1.5": os.path.join(base_dir, "mem0model-large"),   # 改为中文大模型
}

for model_id, local_dir in models.items():
    print(f"Downloading {model_id} to {local_dir} ...")
    os.makedirs(local_dir, exist_ok=True)
    snapshot_download(
        repo_id=model_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    print(f"Finished {model_id}")