"""Freeze the e2e_003 embedding space — local model, zero API calls.

    python experiments/e2e_003/embed.py

Encodes the 55 v8 memory records and all 48 task texts (40 v8 + 8 Chinese
probes) with the frozen model (paraphrase-multilingual-MiniLM-L12-v2) and
writes embeddings.npz + embeddings.json (model provenance + input hashes).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

# HuggingFace is unreachable from this network; the community mirror serves the
# identical model files by sha256. Recorded in embeddings.json provenance.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "e2e_002"
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    from sentence_transformers import SentenceTransformer

    records = [json.loads(line) for line in
               (BASE / "memory" / "records.jsonl").read_text().splitlines()
               if line.strip()]
    task_dirs = sorted(p for p in (BASE / "tasks").iterdir() if p.is_dir())
    probe_dirs = sorted(p for p in (ROOT / "probe_tasks").iterdir() if p.is_dir())

    record_ids = [r["record_id"] for r in records]
    record_texts = [r["text"] for r in records]
    task_ids = [p.name for p in task_dirs + probe_dirs]
    task_texts = [(p / "task.md").read_text(encoding="utf-8")
                  for p in task_dirs + probe_dirs]

    model = SentenceTransformer(MODEL, model_kwargs={"use_safetensors": True})
    rec_vecs = model.encode(record_texts, normalize_embeddings=True)
    task_vecs = model.encode(task_texts, normalize_embeddings=True)

    np.savez(ROOT / "embeddings.npz",
             record_ids=np.array(record_ids),
             record_vecs=rec_vecs,
             task_ids=np.array(task_ids),
             task_vecs=task_vecs)
    meta = {
        "model": MODEL,
        "st_version": __import__("sentence_transformers").__version__,
        "normalized": True,
        "records_sha256": sha256(BASE / "memory" / "records.jsonl"),
        "n_records": len(record_ids),
        "n_tasks": len(task_ids),
        "task_ids": task_ids,
        "hf_endpoint": os.environ.get("HF_ENDPOINT", "https://huggingface.co"),
    }
    (ROOT / "embeddings.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"embedded {len(record_ids)} records + {len(task_ids)} tasks "
          f"with {MODEL} (st {meta['st_version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
