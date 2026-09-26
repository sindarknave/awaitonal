"""Deterministic additive synthesis, independent of classifiers and playback."""

from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re
import wave

import numpy as np

from .config import load_config
from .types import GESTURES
# Session voices change the instrument, never the gesture's notes or rhythm.
from .voices import VOICE_NAMES as VOICES

GESTURE_ORDER = GESTURES
# Kept as an import alias for callers of the original renderer.
STATE_ORDER = GESTURE_ORDER
# Elapsed time can enrich a routine result without changing its meaning.
# Attention cues and unfinished/continuing work keep their fixed arrangement.
LONG_TURN_GESTURES = frozenset(("done", "answer", "verdict", "plan", "artifact", "published"))
_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_frequency(note: str) -> float:
    """Translate a configured scientific-pitch note, using A4 = 440 Hz."""
    match = re.fullmatch(r"([A-G])([#b]?)(-?\d+)", note)
    if match is None:
        raise ValueError(f"Invalid pitch: {note!r}; expected a note such as C4")
    letter, accidental, octave = match.groups()
    midi = 12 * (int(octave) + 1) + _SEMITONES[letter]
    midi += {"": 0, "#": 1, "b": -1}[accidental]
    try:
        frequency = 440.0 * 2.0 ** ((midi - 69) / 12.0)
    except OverflowError as exc:
        raise ValueError(f"Pitch is outside the audible range: {note!r}") from exc
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError(f"Pitch is outside the audible range: {note!r}")
    return frequency


def _number(value: object, name: str, low: float, high: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return result


def _sample_rate(config: dict) -> int:
    value = _number(config["synth"]["sample_rate"], "sample_rate", 8000, 192000)
    if value != int(value):
        raise ValueError("sample_rate must be an integer")
    return int(value)


def _voice_profile(config: dict, voice: str) -> dict | None:
    """Validate only the selected voice; default retains the original signal."""
    if voice not in VOICES:
        raise ValueError(f"Unknown voice {voice!r}; expected one of {', '.join(VOICES)}")
    if voice == "default":
        return None
    profiles = config.get("voices")
    if not isinstance(profiles, dict) or not isinstance(profiles.get(voice), dict):
        raise ValueError(f"voices.{voice} must be a table")
    profile = profiles[voice]
    validated = {}
    for key, low, high in (("harmonics", 1.0, 32.0), ("harmonic_weights", 0.0, 4.0)):
        values = profile.get(key)
        if not isinstance(values, list) or not 1 <= len(values) <= 32:
            raise ValueError(f"voices.{voice}.{key} must contain between 1 and 32 values")
        validated[key] = [_number(value, f"voices.{voice}.{key}", low, high) for value in values]
    if (len(validated["harmonics"]) != len(validated["harmonic_weights"])
            or not any(validated["harmonic_weights"])):
        raise ValueError(f"voices.{voice} needs equally sized harmonics and nonzero weights")
    for key, low, high in (("partial_decay", 0.0, 10.0), ("attack_scale", .25, 4.0),
                           ("decay_scale", .25, 4.0), ("release_scale", .25, 4.0)):
        validated[key] = _number(profile.get(key), f"voices.{voice}.{key}", low, high)
    # Optional compact envelopes leave legacy profiles sample-for-sample intact.
    for key, low, high in (("max_decay", .015, 1.0), ("max_note_duration", .06, 2.0)):
        if key in profile:
            validated[key] = _number(profile[key], f"voices.{voice}.{key}", low, high)
    detunes = profile.get("detune_cents", [0.0])
    if not isinstance(detunes, list) or not 1 <= len(detunes) <= 7:
        raise ValueError(f"voices.{voice}.detune_cents must contain between 1 and 7 values")
    validated["detune_cents"] = [_number(value, f"voices.{voice}.detune_cents", -12, 12)
                                  for value in detunes]
    if 0.0 not in validated["detune_cents"]:
        raise ValueError(f"voices.{voice}.detune_cents must include the unshifted root")
    return validated


def _long_turn_patch(patch: dict) -> dict:
    """Keep the opening, then lift into a wider, longer final chord."""
    expanded = deepcopy(patch)
    events = expanded["events"]
    profile = expanded.get("long_turn", {})
    if not isinstance(profile, dict):
        raise ValueError("long_turn must be a table")
    final_index = max(range(len(events)), key=lambda i: float(events[i]["time"]))
    final = events.pop(final_index)
    lift = profile.get("lift", [final["notes"][0], final["notes"][-1]])
    chord = profile.get("chord", final["notes"])
    if not isinstance(lift, list) or len(lift) != 2:
        raise ValueError("long_turn lift requires two notes")
    # Leave room for two new attacks without stretching the familiar opening.
    start = float(final["time"])
    for index, note in enumerate(lift):
        events.append({"time": start + .18 * index, "notes": [note],
                       "duration": .26, "attack": .012, "decay": .18,
                       "release": .075, "gain": float(final["gain"]) * (.78 + .10 * index)})
    final.update(time=start + .36, notes=chord, duration=float(final["duration"]) + .44,
                 decay=min(10.0, float(final["decay"]) * 2.5), release=max(.20, float(final["release"])))
    events.append(final)
    expanded["duration"] = float(expanded["duration"]) + .80
    return expanded


def _render_events(state: str, config: dict, brightness: float, *, extended: bool = False,
                   voice_profile: dict | None = None) -> np.ndarray:
    settings = config["synth"] if voice_profile is None else voice_profile
    sample_rate = _sample_rate(config)
    patch = config["states"][state]
    if extended:
        patch = _long_turn_patch(patch)
    duration = _number(patch["duration"], "state duration", 0.05, 10.8 if extended else 10.0)
    samples = np.zeros(round(duration * sample_rate), dtype=np.float64)
    harmonics = np.asarray(settings["harmonics"], dtype=np.float64)
    weights = np.asarray(settings["harmonic_weights"], dtype=np.float64)
    if (harmonics.ndim != 1 or weights.shape != harmonics.shape
            or len(harmonics) == 0 or len(harmonics) > 32
            or not np.isfinite(harmonics).all() or not np.isfinite(weights).all()
            or (harmonics < 1).any() or (weights < 0).any()
            or not (weights > 0).any()):
        raise ValueError("Harmonics and weights must be finite, equally sized positive lists")
    # Boost upper partials gradually. Per-voice energy normalization and the
    # final RMS match in render keep this independent of output volume.
    weights = weights * (1.0 + brightness * (1.0 - 1.0 / harmonics))
    partial_decay = _number(settings["partial_decay"], "partial_decay", 0.0, 10.0)
    events = patch["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= (34 if extended else 32):
        raise ValueError("A state must contain between 1 and 32 events")
    last_end = 0
    for event in events:
        start = _number(event["time"], "event time", 0.0, duration)
        length = _number(event["duration"], "event duration", 0.005, duration)
        if start + length > duration + 1.0 / sample_rate:
            raise ValueError("An event must finish within its state's duration")
        attack = _number(event["attack"], "attack", 0.001, length)
        release = _number(event["release"], "release", 0.001, length)
        decay = _number(event["decay"], "decay", 0.001, 10.0)
        if voice_profile is not None:
            # Keep every event's boundaries and the long-turn arrangement. The
            # instrument shapes only its attack, decay, and release inside them.
            attack = min(length, max(.001, attack * voice_profile["attack_scale"]))
            decay = min(10.0, max(.001, decay * voice_profile["decay_scale"]))
            release = min(length, max(.001, release * voice_profile["release_scale"]))
            decay = min(decay, voice_profile.get("max_decay", decay))
            length = min(length, voice_profile.get("max_note_duration", length))
            attack, release = min(attack, length), min(release, length)
        gain = _number(event["gain"], "event gain", 0.0, 4.0)
        notes = event["notes"]
        if not isinstance(notes, list) or not 1 <= len(notes) <= 16:
            raise ValueError("Each event needs between 1 and 16 notes")
        count = round(length * sample_rate)
        times = np.arange(count, dtype=np.float64) / sample_rate
        # Raised cosine ramps have zero slope at both ends. Multiplying
        # overlapping ramps also safely handles very short configured events.
        onset = 0.5 - 0.5 * np.cos(np.pi * np.minimum(times / attack, 1.0))
        remaining = (count - 1 - np.arange(count)) / sample_rate
        ending = 0.5 - 0.5 * np.cos(np.pi * np.minimum(remaining / release, 1.0))
        envelope = onset * ending * np.exp(-times / decay)
        chord = np.zeros(count, dtype=np.float64)
        voices = [(note_frequency(note), 1.0) for note in notes]
        detunes = [0.0] if voice_profile is None else voice_profile["detune_cents"]
        for frequency, amplitude in voices:
            if frequency >= sample_rate / 2:
                raise ValueError("Fundamental is at or above Nyquist")
            # Check the highest detuned oscillator too, before dropping partials.
            highest = frequency * 2 ** (max(detunes) / 1200)
            usable = highest * harmonics < sample_rate / 2
            local_weights = weights[usable]
            local_harmonics = harmonics[usable]
            norm = float(np.linalg.norm(local_weights))
            if norm == 0:
                raise ValueError("No audible partial has a nonzero weight")
            for harmonic, weight in zip(local_harmonics, local_weights, strict=True):
                partial_envelope = np.exp(-times * partial_decay * (harmonic - 1) / decay)
                for cents in detunes:
                    chord += (amplitude * weight / norm / math.sqrt(len(detunes))) * partial_envelope * np.sin(
                        2.0 * np.pi * frequency * 2 ** (cents / 1200) * harmonic * times
                    )
        # Energy, rather than peak, scaling stops richer chords becoming louder.
        chord *= envelope * gain / math.sqrt(sum(amplitude ** 2 for _, amplitude in voices))
        offset = round(start * sample_rate)
        end = min(len(samples), offset + count)
        samples[offset:end] += chord[:end - offset]
        last_end = max(last_end, end)
    if voice_profile is not None and "max_note_duration" in voice_profile:
        # Avoid holding the serial player open for a now-silent sustained tail.
        samples = samples[:min(len(samples), last_end + round(.025 * sample_rate))]
    return samples


def render(state: str, config: dict | None = None, response_length: int = 0,
           *, long_turn: bool = False, voice: str = "default") -> np.ndarray:
    """Render one gesture as mono float64 samples, with guaranteed headroom.

    Brightness is opt-in, bounded, and RMS-matched to the same fixed gesture.
    Character count never changes duration or the intended volume. Separately,
    long_turn adds a rising lift and longer final chord to routine results at
    similar RMS level. It describes elapsed time, not reasoning or confidence.
    Named session voices use different partials and envelopes at the same RMS
    level. Compact voices keep pitches/onsets and shorten note tails; long turns
    retain their two extra rising attacks. The default voice preserves the
    original palette sample for sample.
    """
    config = load_config() if config is None else config
    if state not in GESTURE_ORDER:
        raise ValueError(f"Unknown gesture {state!r}; expected one of {', '.join(GESTURE_ORDER)}")
    profile = _voice_profile(config, voice)
    settings = config["synth"]
    master_gain = _number(settings["master_gain"], "master_gain", 0.0, 1.0)
    peak_limit = _number(settings["peak_limit"], "peak_limit", 0.01, 0.98)
    samples = _render_events(state, config, 0.0)
    reference_energy = float(np.dot(samples, samples))
    extended = long_turn and state in LONG_TURN_GESTURES
    amount = 0.0
    brightness_config = settings.get("brightness", {})
    if brightness_config.get("enabled", False):
        scale = _number(brightness_config["length_scale"], "length_scale", 1.0, 1e9)
        max_boost = _number(brightness_config["max_boost"], "max_boost", 0.0, 2.0)
        count = _number(response_length, "response_length", 0.0, 1e15)
        amount = max_boost * count / (count + scale)
    if amount > 0 or extended or profile is not None:
        variant = _render_events(state, config, amount, extended=extended, voice_profile=profile)
        energy = float(np.dot(variant, variant))
        if energy > 0:
            variant *= math.sqrt(reference_energy / energy * (len(variant) / len(samples)))
        samples = variant
    samples *= master_gain
    peak = float(np.max(np.abs(samples)))
    if peak > peak_limit:
        # Uniform emergency attenuation, never waveform clipping. Ordinarily
        # inactive with the conservative packaged palette.
        samples *= peak_limit / peak
    samples[0] = samples[-1] = 0.0
    return samples


def render_demo(config: dict | None = None, *, voice: str = "default") -> np.ndarray:
    """Audition the full gesture palette with configurable gaps."""
    config = load_config() if config is None else config
    gap = _number(config["synth"]["demo_gap"], "demo_gap", 0.0, 10.0)
    silence = np.zeros(round(gap * _sample_rate(config)), dtype=np.float64)
    parts = []
    for index, state in enumerate(GESTURE_ORDER):
        if index:
            parts.append(silence)
        parts.append(render(state, config, voice=voice))
    return np.concatenate(parts)


def write_wav(path: str | Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write mono PCM16 WAV. Reject invalid audio instead of hiding clipping."""
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim != 1 or len(audio) == 0 or not np.isfinite(audio).all():
        raise ValueError("WAV samples must be finite, nonempty mono audio")
    if np.max(np.abs(audio)) > 1.0:
        raise ValueError("WAV samples exceed full scale")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    pcm = np.rint(audio * 32767.0).astype("<i2")
    with wave.open(str(Path(path)), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(pcm.tobytes())
