import json
import pickle
from pathlib import Path
from typing import List, Dict, Optional
import numpy as np
from loguru import logger

from config import settings


class IncidentMemory:
    _INDEX_FILE = "faiss.index"
    _META_FILE = "metadata.pkl"

    def __init__(self):
        self._index = None
        self._metadata: List[Dict] = []
        self._encoder = None

    def _get_encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(settings.EMBEDDING_MODEL)
        return self._encoder

    def _embed(self, texts: List[str]) -> np.ndarray:
        enc = self._get_encoder()
        embeddings = enc.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.astype(np.float32)

    def build_index(self, incidents_dir: str):
        import faiss

        path = Path(incidents_dir)
        incidents = []
        for f in sorted(path.glob("*.json")):
            try:
                incidents.append(json.loads(f.read_text()))
            except Exception as e:
                logger.warning(f"Skipping {f.name}: {e}")

        if not incidents:
            logger.error(f"No JSON files found in {incidents_dir}")
            return

        texts = [f"{inc['title']}: {inc['symptoms']}" for inc in incidents]
        embeddings = self._embed(texts)

        dim = embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)
        self._index.add(embeddings)
        self._metadata = incidents

        save_dir = Path(settings.FAISS_INDEX_PATH)
        save_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(save_dir / self._INDEX_FILE))
        with open(save_dir / self._META_FILE, "wb") as f:
            pickle.dump(self._metadata, f)

        logger.info(f"Indexed {len(incidents)} incidents → {save_dir}")

    def load_index(self) -> bool:
        import faiss

        save_dir = Path(settings.FAISS_INDEX_PATH)
        idx_path = save_dir / self._INDEX_FILE
        meta_path = save_dir / self._META_FILE

        if not idx_path.exists():
            logger.warning(f"FAISS index not found at {idx_path}. Run: make build-index")
            return False
        try:
            self._index = faiss.read_index(str(idx_path))
            with open(meta_path, "rb") as f:
                self._metadata = pickle.load(f)
            logger.info(f"Loaded FAISS index: {len(self._metadata)} incidents")
            return True
        except Exception as e:
            logger.error(f"Failed to load FAISS index: {e}")
            return False

    def retrieve_similar(self, description: str, k: int = 3) -> List[Dict]:
        if self._index is None:
            if not self.load_index():
                return []

        query = self._embed([description])
        k = min(k, len(self._metadata))
        scores, indices = self._index.search(query, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0:
                inc = dict(self._metadata[idx])
                inc["similarity_score"] = float(score)
                results.append(inc)
        return results
