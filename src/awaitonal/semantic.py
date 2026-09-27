"""Optional real sentence-embedding backend. No imports or downloads on hook paths.

Positive anchors compete using cosine similarity. Class score blends the final
context with the strongest selected context. Attention requires an absolute score,
a margin over the runner-up, AND a margin over labeled negative anchors. Everything
uncertain retains an unknown outcome with a neutral cue. These values are not calibrated probabilities.
"""
import json
from dataclasses import replace
from pathlib import Path
import tomllib

from .classify import RulesClassifier, explicit_result, result
from .text import assistant_prose, select_chunks
from .types import Event, MODEL_STATES, controls_for, map_controls

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
PACKAGE = Path(__file__).parent


def _sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Semantic mode requires the optional dependencies: uv sync --extra semantic") from exc
    return SentenceTransformer


def setup_model(model_path: str | Path) -> None:
    """Explicit network-enabled setup; normal classification never calls this."""
    path = Path(model_path).expanduser().resolve()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"Model destination must be absent or empty: {path}")
    model = _sentence_transformer()(MODEL_ID, device="cpu", trust_remote_code=False)
    path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(path))
    (path / "awaitonal-model.json").write_text(json.dumps({"model": MODEL_ID, "license": "Apache-2.0"}) + "\n")


class SemanticClassifier:
    """Load weights and anchor embeddings once; reuse this object in the service."""
    def __init__(self, model_path: str | Path, threshold: float = 0.5,
                 config_path: str | Path | None = None):
        map_controls(controls_for("done"), threshold)
        self.threshold = threshold
        self.routing_rules = RulesClassifier(threshold)
        path = Path(model_path).expanduser().resolve()
        if not path.is_dir() or not (path / "modules.json").is_file():
            raise RuntimeError(f"No local sentence model at {path}. Run awaitonal model-setup --model-dir PATH explicitly.")
        config_file = Path(config_path) if config_path else PACKAGE / "semantic.toml"
        with config_file.open("rb") as stream:
            self.config = tomllib.load(stream)
        cfg = self.config
        for name in ("conclusion_weight", "best_anchor_weight", "minimum_similarity", "minimum_margin",
                     "attention_similarity", "attention_margin", "contrast_margin"):
            value = cfg[name]
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if type(cfg["max_chunks"]) is not int or not 2 <= cfg["max_chunks"] <= 32:
            raise ValueError("max_chunks must be in [2, 32]")
        if type(cfg["token_budget"]) is not int or not 16 <= cfg["token_budget"] <= 1024:
            raise ValueError("token_budget must be in [16, 1024]")
        anchor_path = config_file.parent / cfg["anchors"]
        self.anchors = json.loads(anchor_path.read_text())
        texts, self.anchor_slices = [], {}
        for state in MODEL_STATES:
            self.anchor_slices[state] = {}
            for kind in ("positive", "negative"):
                entries = self.anchors[state][kind]
                if not isinstance(entries, list) or len(entries) < 2 or not all(isinstance(x, str) and x.strip() for x in entries):
                    raise ValueError(f"{state}.{kind} requires at least two nonempty anchor strings")
                start = len(texts)
                texts.extend(entries)
                self.anchor_slices[state][kind] = slice(start, len(texts))
        # A resolved filesystem path + local_files_only applies to tokenizer,
        # transformer and module loading. No fallback to a remote model name.
        self.model = _sentence_transformer()(str(path), device="cpu", local_files_only=True,
                                            trust_remote_code=False)
        self.model.eval()
        self.token_budget = min(cfg["token_budget"], int(self.model.max_seq_length) -
                                self.model.tokenizer.num_special_tokens_to_add(pair=False))
        if self.token_budget < 16:
            raise ValueError("Model context window is too small")
        self.anchor_embeddings = self.model.encode(texts, normalize_embeddings=True,
                                                   convert_to_numpy=True, show_progress_bar=False)

    def classify(self, event: Event):
        if not isinstance(event, Event) or event.kind != "notification":
            return None
        if event.explicit_state is not None:
            return explicit_result(event, self.threshold)
        prose = assistant_prose(event.text, link_types=True)
        if not prose:
            return None
        # The encoder only has four outcome anchors. Explicit delivery and
        # handoff language uses the same routing in both backends, so sign-in
        # and review requests are not lost to an embedding similarity cutoff.
        routed = self.routing_rules.classify(event)
        if routed and (routed.delivery_kind != "unknown" or routed.expectancy != "none"
                       or routed.state in ("done", "rejected", "caveats") or routed.activity == "in-flight"
                       or routed.diagnostics.get("activity_evidence") == "empty-background-registry"):
            return replace(routed, diagnostics={**routed.diagnostics, "backend": "rules-routing",
                                               "requested_backend": "sentence-transformers"})
        import numpy as np
        chunks, diagnostics = select_chunks(prose, self.model.tokenizer, self.token_budget,
                                             self.config["max_chunks"])
        if not chunks:
            return None
        embeddings = self.model.encode([chunk.text for chunk in chunks], normalize_embeddings=True,
                                       convert_to_numpy=True, show_progress_bar=False)
        cosine = np.asarray(embeddings) @ np.asarray(self.anchor_embeddings).T
        if not np.isfinite(cosine).all():
            raise RuntimeError("Encoder returned nonfinite similarities")
        final_index = max(range(len(chunks)), key=lambda index: chunks[index].end)
        cfg = self.config
        positive, negative = {}, {}
        for state in MODEL_STATES:
            pos = cosine[:, self.anchor_slices[state]["positive"]]
            neg = cosine[:, self.anchor_slices[state]["negative"]]
            top = np.sort(pos, axis=1)[:, -min(3, pos.shape[1]):]
            chunk_scores = cfg["best_anchor_weight"] * top[:, -1] + (1 - cfg["best_anchor_weight"]) * top.mean(axis=1)
            positive[state] = float(cfg["conclusion_weight"] * chunk_scores[final_index] +
                                    (1 - cfg["conclusion_weight"]) * chunk_scores.max())
            negative[state] = float(cfg["conclusion_weight"] * neg[final_index].max() +
                                    (1 - cfg["conclusion_weight"]) * neg.max())
        ranked = sorted(MODEL_STATES, key=lambda state: positive[state], reverse=True)
        winner, runner = ranked[:2]
        attention = winner in ("needs-you", "rejected")
        required_similarity = cfg["attention_similarity"] if attention else cfg["minimum_similarity"]
        required_margin = cfg["attention_margin"] if attention else cfg["minimum_margin"]
        margin = positive[winner] - positive[runner]
        contrast = positive[winner] - negative[winner]
        accepted = (positive[winner] >= required_similarity and margin >= required_margin and
                    (not attention or contrast >= cfg["contrast_margin"]))
        state = winner if accepted else "unknown"
        diagnostics.update({"backend": "sentence-transformers", "model": MODEL_ID,
                            "scores": {k: round(v, 6) for k, v in positive.items()},
                            "contrast_scores": {k: round(v, 6) for k, v in negative.items()},
                            "candidate": winner, "margin": round(margin, 6),
                            "contrast_margin": round(contrast, 6), "accepted": accepted,
                            "required_similarity": required_similarity, "required_margin": required_margin,
                            "required_contrast_margin": cfg["contrast_margin"] if attention else None})
        reason = "Local embedding anchor comparison selected a state." if accepted else "Embedding evidence is ambiguous; conservative non-attention fallback."
        return result(state, event, reason, self.threshold, diagnostics)
