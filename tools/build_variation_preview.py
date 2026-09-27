#!/usr/bin/env python3
"""Build an offline listening gallery. Audio plays only after a browser click.

Run from an installed source checkout:
    .venv/bin/python tools/build_variation_preview.py
The HTML, manifest and WAVs are self-contained and need no server or web assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from awaitonal.config import load_config
from awaitonal.synth import render, write_wav
from awaitonal.voices import SESSION_VOICES

ROOT = Path(__file__).resolve().parents[1]
GESTURES = ("answer", "done")
TURN_ORDER = ("answer", "done", "answer", "answer", "done", "done", "answer", "done")
TURN_SECONDS = (12, 8, 180, 185, 150, 155, 18, 15)
LEAD_SECONDS = .30
GAP_SECONDS = .55
TAIL_SECONDS = .40

HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Awaitonal · Phrase variations</title>
<style>
:root{color-scheme:dark;--bg:#0d1721;--panel:#142331;--line:#29414f;--ink:#eef7f5;--muted:#a4bcc5;--answer:#74d9c5;--done:#f2bf78;--focus:#8bdfe6;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 15% 0,#18394a 0,transparent 55%),var(--bg);color:var(--ink);line-height:1.55}main{max-width:1080px;margin:auto;padding:52px 28px 32px}h1{font-size:clamp(2rem,5vw,3.6rem);line-height:1.1;letter-spacing:-.05em;margin:12px 0 18px}h2{font-size:1.3rem;margin:0 0 8px;letter-spacing:-.02em}h3{font-size:1rem;margin:0 0 3px}p{margin:0 0 16px}.eyebrow{text-transform:uppercase;letter-spacing:.18em;font-size:.74rem;color:var(--answer);font-weight:700}.intro{max-width:740px;color:var(--muted);font-size:1.08rem}.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:28px 0 32px;padding:18px 20px;border:1px solid var(--line);border-radius:15px;background:#12212bd9}.toolbar label{font-weight:650}select,button{font:inherit;color:var(--ink)}select{border:1px solid #496270;border-radius:9px;background:var(--bg);padding:9px 34px 9px 12px}button{cursor:pointer;border:1px solid #385360;background:#213947;border-radius:10px;padding:10px 14px;font-weight:650;transition:background .15s,border-color .15s}button:hover{background:#304e5e;border-color:var(--focus)}button:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid var(--focus);outline-offset:3px}button[aria-pressed="true"]{border-color:var(--focus);background:#315767}.hint,.meta{font-size:.85rem;color:var(--muted)}.toolbar .hint{margin-left:auto}.group{margin:0 0 28px}.grouphead{display:flex;gap:16px;align-items:baseline;justify-content:space-between}.grouphead p{font-size:.9rem;color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.card{border:1px solid var(--line);border-top:3px solid var(--answer);background:var(--panel);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:12px}.group.done .card{border-top-color:var(--done)}.card .variant-name{min-height:2.6em;font-size:.88rem;color:var(--muted);line-height:1.35}.card .badge{align-self:flex-start;padding:2px 8px;border:1px solid #42616d;border-radius:20px;font-size:.73rem;color:var(--muted)}.card .badge.full{border-color:#907148;color:#f2ce96}.card .meta{margin-top:auto}.card button{width:100%}.compare{border:1px solid var(--line);background:linear-gradient(120deg,#152e38,#172331);border-radius:17px;padding:24px;margin:36px 0 22px}.compare p{color:var(--muted)}.compare-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.compare-box{border:1px solid var(--line);border-radius:12px;padding:17px;background:#0d182140}.compare-box p{font-size:.87rem;min-height:2.8em}.compare-box button{width:100%}.timeline{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:6px;margin:18px 0 0}.step{padding:8px 3px;text-align:center;border:1px solid #34505d;border-radius:7px;font-size:.72rem;color:var(--muted);transition:background .1s}.step strong{display:block;color:var(--answer);font-size:.74rem}.step[data-gesture="done"] strong{color:var(--done)}.step .elapsed,.step .choice{display:block;margin-top:4px}.step .choice{font-size:.7rem;color:var(--ink)}details{margin-top:15px;font-size:.88rem;color:var(--muted)}summary{cursor:pointer;color:var(--ink)}details li{margin:7px 0}.missing{border:1px solid var(--line);border-radius:13px;padding:19px 22px;margin:20px 0}.missing p{color:var(--muted);font-size:.9rem}.missing-actions{display:flex;gap:12px;flex-wrap:wrap}.step.active{background:#345965;box-shadow:0 0 0 1px var(--focus)}.tour{display:flex;gap:18px;flex-wrap:wrap;align-items:center;justify-content:space-between;padding:18px 0 24px}.tour p{margin:0;color:var(--muted);font-size:.88rem}.player-shell{position:sticky;bottom:14px;z-index:2;border:1px solid #496673;border-radius:15px;box-shadow:0 10px 45px #0008;background:#172a35f5;backdrop-filter:blur(14px);padding:15px 19px;display:grid;grid-template-columns:minmax(200px,1fr) minmax(260px,1.2fr);gap:10px 20px;align-items:center}.player-shell strong{font-size:.94rem}.player-shell .meta{display:block}audio{width:100%;height:42px}#open-wav{color:var(--answer);font-size:.8rem}footer{color:var(--muted);font-size:.8rem;padding:24px 2px 0}footer a{color:var(--answer)}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}#error{color:#ffd09a;font-size:.88rem;margin:0}noscript{display:block;border:1px solid var(--line);padding:18px;border-radius:10px}
@media(max-width:700px){main{padding:30px 18px 24px}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar .hint{margin:0;width:100%}.grouphead{display:block}.grouphead p{margin-bottom:10px}.compare{padding:18px}.compare-grid{grid-template-columns:1fr}.compare-box p{min-height:0}.player-shell{grid-template-columns:1fr;bottom:8px;padding:12px 14px}.timeline{gap:5px;grid-template-columns:repeat(4,minmax(0,1fr))}.step{font-size:.68rem}.step strong{font-size:.62rem}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body><main>
<div class="eyebrow">Awaitonal listening room</div>
<h1>A little variation.<br>The same meaning.</h1>
<p class="intro">Compare four phrases for an answer and four for a completed change. Hear how elapsed turn time and repetition shape the choice.</p>
<div class="toolbar"><label for="voice">Session instrument</label><select id="voice"></select><span class="hint">Audio starts only when you press Play.</span></div>
<noscript>This gallery needs JavaScript for its player controls. The WAV files are in the adjacent audio folder; the manifest lists every clip.</noscript>
<div id="individuals"></div>
<section class="compare" aria-labelledby="compare-title"><h2 id="compare-title">Eight turns, two ways</h2><p id="policy-summary"></p><p class="hint">Elapsed time is time on the clock, including work and waiting. It is not thinking duration.</p><div class="compare-grid"><div class="compare-box"><h3>Repeated original</h3><p>Each answer and done uses its original phrase.</p><button id="play-original" type="button">Play repeated original</button></div><div class="compare-box"><h3>Duration-guided variation</h3><p>Use elapsed time to choose a group, then alternate phrases within that group.</p><button id="play-contextual" type="button">Play duration-guided</button></div></div><div id="timeline" class="timeline" aria-label="Eight-turn sequence with elapsed durations"></div><p class="hint" id="sequence-note" style="margin:12px 0 0"></p><details><summary>Why these phrases?</summary><ol id="selection-reasons"></ol></details></section>
<section class="missing" aria-labelledby="missing-title"><h2 id="missing-title">No matched timing? Use the original.</h2><p>If the turn has no reliable elapsed duration, it keeps the original phrase. Hear that fallback in the selected instrument.</p><div class="missing-actions"><button id="play-missing-answer" type="button">Play answer with missing timing</button><button id="play-missing-done" type="button">Play done with missing timing</button></div></section>
<section class="tour"><div><h2 id="tour-title">All eight phrases</h2><p>Answer first, then done. Original, variation 1, variation 2, variation 3.</p></div><button id="play-tour" type="button">Play all eight</button></section>
<div class="player-shell"><div><strong id="now-playing">Choose a phrase to listen.</strong><span id="player-detail" class="meta">Nothing loads until you click.</span><a id="open-wav" hidden target="_blank" rel="noopener">Open this WAV</a></div><audio id="player" controls preload="none" aria-label="Awaitonal preview player"></audio><p id="error" role="status" hidden></p></div>
<div id="announcement" class="sr-only" aria-live="polite"></div>
<footer>Generated locally. No uploads or external assets. <a href="manifest.json" target="_blank" rel="noopener">Clip and sequence manifest</a></footer>
</main>
<script id="preview-data" type="application/json">__MANIFEST_JSON__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('preview-data').textContent);
const player=document.getElementById('player');
const voiceSelect=document.getElementById('voice');
const timeline=document.getElementById('timeline');
let activeTrack=null,activeButton=null,playGeneration=0;
const titleCase=s=>s.charAt(0).toUpperCase()+s.slice(1);
for(const voice of data.voices){const option=document.createElement('option');option.value=voice;option.textContent=titleCase(voice);voiceSelect.append(option)}
function announce(text){document.getElementById('announcement').textContent=text}
function clearSteps(){for(const step of timeline.children)step.classList.remove('active')}
function reset(){playGeneration++;player.pause();player.removeAttribute('src');player.load();activeTrack=null;if(activeButton)activeButton.setAttribute('aria-pressed','false');activeButton=null;clearSteps();document.getElementById('now-playing').textContent='Choose a phrase to listen.';document.getElementById('player-detail').textContent=titleCase(voiceSelect.value)+' selected';document.getElementById('open-wav').hidden=true;document.getElementById('error').hidden=true}
function play(track,label,button){const request=++playGeneration;player.pause();if(activeButton)activeButton.setAttribute('aria-pressed','false');activeButton=button;activeTrack=track;button.setAttribute('aria-pressed','true');clearSteps();player.src=track.file;document.getElementById('now-playing').textContent=label;document.getElementById('player-detail').textContent=titleCase(track.voice)+' · '+track.duration_seconds.toFixed(2)+' seconds';const link=document.getElementById('open-wav');link.href=track.file;link.hidden=false;document.getElementById('error').hidden=true;announce(label);const started=player.play();if(started)started.catch(()=>{if(request!==playGeneration)return;document.getElementById('error').textContent="This browser could not start the audio. Try the Open this WAV link.";document.getElementById('error').hidden=false;button.setAttribute('aria-pressed','false')})}
function selectedSequence(kind){return data.sequences.find(s=>s.voice===voiceSelect.value&&s.kind===kind)}
function renderTimeline(track){timeline.replaceChildren();const reasons=document.getElementById('selection-reasons');reasons.replaceChildren();for(const turn of track.timeline){const step=document.createElement('div');step.className='step';step.dataset.gesture=turn.gesture;const number=document.createElement('span');number.textContent=String(turn.turn);const label=document.createElement('strong');label.textContent=titleCase(turn.gesture);const elapsed=document.createElement('span');elapsed.className='elapsed';elapsed.textContent=turn.turn_seconds+'s elapsed';const choice=document.createElement('span');choice.className='choice';choice.textContent=track.kind==='original'?'Original':titleCase(turn.selection_group)+' · '+(turn.variation===0?'original':'var '+turn.variation);step.append(number,label,elapsed,choice);timeline.append(step);const reason=document.createElement('li');reason.textContent=titleCase(turn.gesture)+' after '+turn.turn_seconds+'s: '+turn.selection_reason;reasons.append(reason)}document.getElementById('sequence-note').textContent='An '+track.duration_seconds.toFixed(2)+'-second listening example of eight synthetic turns. Both comparisons have the same turn order and start times.'}
function renderVoice(){reset();const wrap=document.getElementById('individuals');wrap.replaceChildren();for(const gesture of data.gestures){const section=document.createElement('section');section.className='group '+gesture;const head=document.createElement('div');head.className='grouphead';const heading=document.createElement('h2');heading.textContent=titleCase(gesture);const description=document.createElement('p');description.textContent=gesture==='answer'?'An explanation or answer.':'A change or operation is complete.';head.append(heading,description);section.append(head);const cards=document.createElement('div');cards.className='cards';for(const clip of data.clips.filter(c=>c.voice===voiceSelect.value&&c.gesture===gesture)){const card=document.createElement('div');card.className='card';const name=document.createElement('h3');name.textContent=clip.variation===0?'Original':'Variation '+clip.variation;const badge=document.createElement('span');badge.className='badge '+clip.phrase_group;badge.textContent=titleCase(clip.phrase_group);const note=document.createElement('div');note.className='variant-name';note.textContent=clip.phrase_name;const meta=document.createElement('div');meta.className='meta';meta.textContent=clip.duration_seconds.toFixed(2)+' seconds';const button=document.createElement('button');button.type='button';button.textContent='▶ Play';button.setAttribute('aria-label','Play '+titleCase(gesture)+' '+name.textContent.toLowerCase()+' on '+voiceSelect.value);button.setAttribute('aria-pressed','false');button.addEventListener('click',()=>play(clip,titleCase(gesture)+' · '+name.textContent,button));card.append(name,badge,note,meta,button);cards.append(card)}section.append(cards);wrap.append(section)}renderTimeline(selectedSequence('contextual'));document.getElementById('policy-summary').textContent=data.duration_groups.answer&&data.duration_groups.done?'Light phrases below '+data.full_after_seconds+' seconds; full phrases at '+data.full_after_seconds+' seconds or longer. Repeated gestures alternate within their selected group.':'Gestures with duration groups use light/full phrases around the '+data.full_after_seconds+'-second threshold. Ungrouped gestures alternate their ordinary phrases.'}
voiceSelect.addEventListener('change',renderVoice);
for(const kind of ['original','contextual']){const button=document.getElementById('play-'+kind);button.addEventListener('click',()=>{const track=selectedSequence(kind);renderTimeline(track);play(track,kind==='original'?'Eight turns · repeated original':'Eight turns · duration-guided variation',button)})}
for(const gesture of data.gestures){const button=document.getElementById('play-missing-'+gesture);button.addEventListener('click',()=>{const clip=data.clips.find(c=>c.voice===voiceSelect.value&&c.gesture===gesture&&c.variation===0);play(clip,titleCase(gesture)+' · missing timing uses original',button)})}
const tourButton=document.getElementById('play-tour');document.getElementById('tour-title').textContent='All eight phrases · '+titleCase(data.sampler.voice);tourButton.addEventListener('click',()=>play(data.sampler,'All eight phrases · '+titleCase(data.sampler.voice),tourButton));
player.addEventListener('timeupdate',()=>{clearSteps();if(!activeTrack||!['original','contextual'].includes(activeTrack.kind))return;for(const turn of activeTrack.timeline){if(player.currentTime>=turn.offset_seconds&&player.currentTime<turn.offset_seconds+turn.slot_duration_seconds){timeline.children[turn.turn-1]?.classList.add('active');break}}});
player.addEventListener('ended',()=>{if(activeButton)activeButton.setAttribute('aria-pressed','false');clearSteps();announce('Playback finished.')});
player.addEventListener('error',()=>{if(!activeTrack)return;document.getElementById('error').textContent='The audio file could not be opened. Keep this HTML beside its audio folder, or try Open this WAV.';document.getElementById('error').hidden=false});
renderVoice();
</script></body></html>
'''


def _validated_voices(voices):
    if not voices or len(set(voices)) != len(voices) or any(voice not in SESSION_VOICES for voice in voices):
        raise ValueError("Choose unique session voices: " + ", ".join(SESSION_VOICES))
    return tuple(voices)


def make_sequence(clips, choices, sample_rate, *, gap_seconds=GAP_SECONDS,
                  lead_seconds=LEAD_SECONDS, tail_seconds=TAIL_SECONDS):
    """Use identical turn slots for every choice, with sample-exact cue offsets.

    clips maps (gesture, variation) to one voice's samples. Each slot reserves
    the longest available phrase for that gesture, followed by a fixed gap.
    Thus repeated/varied comparisons start every corresponding turn together.
    """
    if not choices or any(key not in clips for key in choices):
        raise ValueError("Every sequence choice needs a rendered clip")
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    if any(not np.isfinite(x) or x < 0 for x in (gap_seconds, lead_seconds, tail_seconds)):
        raise ValueError("Sequence silence durations must be finite and nonnegative")
    slot_frames = {gesture: max(len(samples) for (name, _), samples in clips.items() if name == gesture)
                   for gesture, _ in choices}
    gap, lead, tail = (round(value * sample_rate) for value in (gap_seconds, lead_seconds, tail_seconds))
    total = lead + sum(slot_frames[gesture] for gesture, _ in choices) + gap * (len(choices) - 1) + tail
    audio = np.zeros(total, dtype=np.float64)
    timeline = []
    cursor = lead
    for index, (gesture, variation) in enumerate(choices):
        samples = clips[(gesture, variation)]
        audio[cursor:cursor + len(samples)] = samples
        timeline.append({"turn": index + 1, "gesture": gesture, "variation": variation,
                         "offset_frames": cursor, "offset_seconds": cursor / sample_rate,
                         "duration_frames": len(samples), "duration_seconds": len(samples) / sample_rate,
                         "slot_duration_frames": slot_frames[gesture],
                         "slot_duration_seconds": slot_frames[gesture] / sample_rate})
        cursor += slot_frames[gesture] + (gap if index < len(choices) - 1 else 0)
    return audio, timeline


def variation_policy(config):
    """Pass palette groups explicitly; custom palettes never inherit guessed roles."""
    from awaitonal.synth import variation_count, variation_groups
    counts = {gesture: variation_count(gesture, config) for gesture in GESTURES}
    groups = {gesture: group for gesture in GESTURES
              if (group := variation_groups(gesture, config)) is not None}
    cutoff = config.get("notifications", {}).get("variation_full_after_seconds", 120)
    return counts, groups, cutoff


def contextual_plan(config, *, turn_order=TURN_ORDER, elapsed_seconds=TURN_SECONDS):
    """Use actual deterministic selection with synthetic matched elapsed times."""
    from awaitonal.variations import SessionVariations
    if len(turn_order) != len(elapsed_seconds):
        raise ValueError("Each preview turn needs a corresponding elapsed-time value")
    counts, groups, cutoff = variation_policy(config)
    selector = SessionVariations(counts, groups=groups, full_after_seconds=cutoff)
    occurrences = {}
    plan = []
    for index, (gesture, elapsed) in enumerate(zip(turn_order, elapsed_seconds)):
        group = selector.group_for(gesture, elapsed)
        variation = selector.choose("preview-session", gesture, now=index, turn_seconds=elapsed)
        occurrence = occurrences.get((gesture, group), 0)
        if elapsed is None:
            reason = "Missing matched timing uses the original phrase."
            occurrence = None
        else:
            occurrences[(gesture, group)] = occurrence + 1
            if group == "full":
                reason = f"Long turn ({elapsed:g}s ≥ {cutoff:g}s) selects the full group."
            elif group == "light":
                reason = f"Short turn ({elapsed:g}s < {cutoff:g}s) selects the light group."
            else:
                reason = "The palette has no duration groups, so use an ordinary phrase."
            reason += (" A repeated gesture in this group moves to the next phrase." if occurrence
                       else " This is the first occurrence of this gesture in this group.")
        plan.append({"gesture": gesture, "turn_seconds": elapsed, "variation": variation,
                     "selection_group": group, "group_occurrence": occurrence,
                     "selection_reason": reason})
    return plan


def phrase_group(groups, gesture, variation):
    return next((group for group, members in groups.get(gesture, {}).items() if variation in members), "ordinary")


def _audio_metadata(path, samples, sample_rate, relative):
    write_wav(path, samples, sample_rate)
    return {"file": relative, "frames": len(samples), "duration_seconds": len(samples) / sample_rate,
            "sample_rate": sample_rate, "channels": 1, "pcm_bits": 16,
            "wav_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def build(output, *, config=None, voices=SESSION_VOICES):
    from awaitonal.synth import variation_count
    voices = _validated_voices(voices)
    config = load_config() if config is None else config
    if any(variation_count(gesture, config) != 4 for gesture in GESTURES):
        raise ValueError("This preview needs the original and three variations for answer and done")
    sample_rate = config["synth"]["sample_rate"]
    plan = contextual_plan(config)
    _, groups, cutoff = variation_policy(config)
    varied = [turn["variation"] for turn in plan]
    if len(varied) != len(TURN_ORDER) or any(not 0 <= value < 4 for value in varied):
        raise ValueError("The variation selector returned an invalid eight-turn sequence")
    rendered = {voice: {(gesture, variation): render(gesture, config, voice=voice, variation=variation)
                        for gesture in GESTURES for variation in range(4)} for voice in voices}
    output = Path(output)
    (output / "audio").mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 2, "gestures": list(GESTURES), "voices": list(voices),
                "variation_count": 4, "sample_rate": sample_rate, "turn_order": list(TURN_ORDER),
                "turn_seconds": list(TURN_SECONDS), "duration_groups": groups, "full_after_seconds": cutoff,
                "selection_policy": "Shared deterministic service policy: elapsed-duration group, then independent per-session/gesture/group alternation. Missing timing uses original0.",
                "timing_meaning": "Matched elapsed clock time, including work and waiting; not thinking duration.",
                "silence": {"lead_seconds": LEAD_SECONDS, "gap_seconds": GAP_SECONDS, "tail_seconds": TAIL_SECONDS},
                "timing_policy": "Corresponding turns have identical start offsets. Slots reserve the longest variant of that gesture, then the fixed gap.",
                "render_settings": {"long_turn": False, "response_length": 0}, "clips": [], "sequences": []}
    for voice in voices:
        for gesture in GESTURES:
            for variation in range(4):
                filename = f"audio/{voice}-{gesture}-v{variation}.wav"
                phrase_name = "The original phrase" if variation == 0 else config["states"][gesture]["variations"][variation-1].get("name", f"Variation {variation}")
                manifest["clips"].append({"id": f"{voice}-{gesture}-v{variation}", "gesture": gesture,
                    "voice": voice, "variation": variation, "phrase_name": phrase_name,
                    "phrase_group": phrase_group(groups, gesture, variation),
                    **_audio_metadata(output/filename, rendered[voice][(gesture, variation)], sample_rate, filename)})
        for kind, order in (("original", [0] * len(TURN_ORDER)), ("contextual", varied)):
            choices = list(zip(TURN_ORDER, order))
            audio, timeline = make_sequence(rendered[voice], choices, sample_rate)
            for turn, context in zip(timeline, plan):
                turn.update(voice=voice, clip_id=f"{voice}-{turn['gesture']}-v{turn['variation']}",
                            turn_seconds=context["turn_seconds"], context_group=context["selection_group"],
                            phrase_group=phrase_group(groups, turn["gesture"], turn["variation"]),
                            selection_group=context["selection_group"] if kind == "contextual" else "original",
                            group_occurrence=context["group_occurrence"] if kind == "contextual" else None,
                            selection_reason=context["selection_reason"] if kind == "contextual" else
                                "Original reference phrase; this comparison does not adapt to elapsed time or repetition.")
            suffix = "duration-guided" if kind == "contextual" else "original"
            filename = f"audio/{voice}-eight-turns-{suffix}.wav"
            manifest["sequences"].append({"kind": kind, "voice": voice, "timeline": timeline,
                **_audio_metadata(output/filename, audio, sample_rate, filename)})
    sampler_voice = "marimba" if "marimba" in voices else voices[0]
    sampler_choices = [(gesture, variation) for gesture in GESTURES for variation in range(4)]
    audio, timeline = make_sequence(rendered[sampler_voice], sampler_choices, sample_rate)
    for turn in timeline:
        turn.update(voice=sampler_voice, clip_id=f"{sampler_voice}-{turn['gesture']}-v{turn['variation']}")
    filename = f"audio/{sampler_voice}-all-eight-phrases.wav"
    manifest["sampler"] = {"kind": "sampler", "voice": sampler_voice, "timeline": timeline,
        **_audio_metadata(output/filename, audio, sample_rate, filename)}
    missing = contextual_plan(config, turn_order=GESTURES, elapsed_seconds=(None, None))
    if any(turn["variation"] != 0 for turn in missing):
        raise ValueError("Missing timing must retain the original phrase")
    manifest["missing_timing"] = [dict(turn, voice=voice, clip_id=f"{voice}-{turn['gesture']}-v0")
                                  for voice in voices for turn in missing]
    tracks = [*manifest["clips"], *manifest["sequences"], manifest["sampler"]]
    manifest["footprint"] = {"wav_files": len(tracks), "wav_bytes": sum(track["bytes"] for track in tracks)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    embedded = json.dumps(manifest, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    (output / "index.html").write_text(HTML.replace("__MANIFEST_JSON__", embedded))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/variation-preview")
    parser.add_argument("--config", type=Path, help="Optional palette overrides")
    parser.add_argument("--voices", nargs="+", choices=SESSION_VOICES, default=list(SESSION_VOICES))
    args = parser.parse_args()
    try:
        manifest = build(args.output, config=load_config(args.config), voices=args.voices)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps({"index": str((args.output / "index.html").resolve()),
                      "voices": manifest["voices"], **manifest["footprint"]}, indent=2))


if __name__ == "__main__":
    main()
