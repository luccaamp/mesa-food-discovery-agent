"""Download one pinned official local judge candidate, with SHA/size validation."""
import json
from pathlib import Path
from fetch_local_llm import download

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    pin = json.loads((ROOT / "configs/judge-candidate-qwen3-v1.json").read_text(encoding="utf-8"))
    download(f"https://huggingface.co/{pin['repository']}/resolve/{pin['revision']}/{pin['file']}",
             ROOT / "models/judge-qwen3-v1" / pin["file"], pin)
