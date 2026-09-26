"""Small repeatable listening trials; overlapping playback is audition-only."""
from dataclasses import dataclass

import numpy as np

from .config import load_config
from .synth import render
from .voices import SESSION_VOICES

STUDY_GESTURES = ("done", "review", "needs-you")
DEMO_MODES = ("voices", "serial", "overlap")


@dataclass(frozen=True)
class AuditionCue:
    voice: str
    gesture: str
    start: float
    duration: float


def render_ensemble_demo(config=None, *, mode="voices"):
    """Return mono samples and a cue sheet for a fixed listening comparison.

    voices: each gesture in wood, glass, round, separated by 450ms.
    serial/overlap: the same wood/done, glass/review, round/needs-you sequence.
    Overlap starts the first two 300ms apart; the required-action cue has its
    own space. This is a composed demo, not the live service's queue policy.
    """
    if mode not in DEMO_MODES:
        raise ValueError(f"Unknown ensemble demo mode: {mode}")
    config = load_config() if config is None else config
    rate = config["synth"]["sample_rate"]
    pairs = ([(voice, gesture) for gesture in STUDY_GESTURES for voice in SESSION_VOICES]
             if mode == "voices" else list(zip(SESSION_VOICES, STUDY_GESTURES, strict=True)))
    cues, parts = [], []
    cursor = 0
    for index, (voice, gesture) in enumerate(pairs):
        audio = render(gesture, config, voice=voice)
        start = round(.3 * rate) if mode == "overlap" and index == 1 else cursor
        cues.append(AuditionCue(voice, gesture, start / rate, len(audio) / rate))
        parts.append((start, audio))
        gap = .45 if mode == "voices" else .15
        cursor = max(cursor, start + len(audio) + round(gap * rate))
    samples = np.zeros(max(start + len(audio) for start, audio in parts), dtype=np.float64)
    for start, audio in parts:
        samples[start:start + len(audio)] += audio
    peak = float(np.max(np.abs(samples)))
    limit = float(config["synth"]["peak_limit"])
    if peak > limit:
        samples *= limit / peak
    samples[0] = samples[-1] = 0
    return samples, cues
