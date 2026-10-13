"""Offline checks for the voice loops: run with `python -m pytest tests` from the repo root."""
import asyncio

import numpy as np

from automation.mcp import voice

QUIET, LOUD = np.zeros(voice.BLOCK, dtype="float32"), np.full(voice.BLOCK, 0.2, dtype="float32")
DONE = [{"call": "x.y {}", "status": "success", "details": ""}]


def wake_loop(heard, run, **kwargs):
    """Runs the wake-word loop over one utterance per transcript in `heard`; returns (spoken, chimes, captions)."""
    transcripts, spoken, chimes, captions = iter(heard), [], [], []
    asyncio.run(voice.listen_for_wake_word(
        "tool", ([LOUD] + [QUIET] * 8) * len(heard), lambda audio: next(transcripts), run=run,
        show=lambda text, done=False: captions.append(text), say=spoken.append,
        chime=lambda ok=True: chimes.append(ok), flush=lambda: None, threshold=0.01, **kwargs))
    return spoken, chimes, captions


def recorder(ran, steps=DONE):
    async def run(text, call_tool, confirm):
        ran.append(text)
        return steps
    return run


def test_push_to_talk_runs_heard_commands_and_ignores_silence():
    keys = iter(["", "", "q"])
    heard = iter([" turn bluetooth off ", "  "])
    ran = []
    asyncio.run(voice.listen("tool", record=lambda: b"audio", transcribe=lambda audio: next(heard), run=recorder(ran),
                             wait=lambda prompt: next(keys), say=lambda text: None, chime=lambda ok=True: None))
    assert ran == ["turn bluetooth off"]


def test_utterances_are_cut_at_pauses():
    blocks = [QUIET] * 5 + [LOUD] * 4 + [QUIET] * 10 + [LOUD] * 2 + [QUIET] * 10
    for threshold in (0.01, None):  # fixed, and following the room noise
        lengths = [len(u) // voice.BLOCK for u in voice.utterances(blocks, threshold=threshold)]
        assert lengths == [3 + 4 + 8, 2 + 2 + 8]  # lead-in + speech + trailing quiet


def test_only_speech_after_the_wake_phrase_is_run():
    ran = []
    _, _, captions = wake_loop(["Delete everything.", "Hey, Aura, turn Bluetooth off.", "Hey Ora.", "Set the volume to 30.",
                                "Shut down the PC.", "Aura mute", "Laura called me"], recorder(ran))
    assert ran == ["turn Bluetooth off.", "Set the volume to 30.", "mute"]
    assert "Listening…" in captions and "Delete everything." not in captions


def test_paused_listening_runs_nothing():
    ran = []
    wake_loop(["Hey Aura, mute"], recorder(ran), enabled=lambda: False)
    assert ran == []


def test_outcome_is_spoken_and_plain_success_only_chimes():
    spoken, chimes, _ = wake_loop(["Hey Aura, mute"], recorder([]))
    assert spoken == [] and chimes == [True, True]  # wake chime, then the done chime instead of saying "Done."
    spoken, chimes, _ = wake_loop(["Hey Aura, battery"], recorder([], [{"call": "c", "status": "success", "details": "80 percent"}]))
    assert spoken == ["80 percent"] and chimes == [True]
    spoken, chimes, _ = wake_loop(["Hey Aura, wifi"], recorder([], [{"call": "c", "status": "failure", "details": "No Wi-Fi radio"}]))
    assert spoken == ["That failed. No Wi-Fi radio"] and chimes == [True, False]


def test_risky_action_is_confirmed_by_voice():
    answers = []

    async def run(text, call_tool, confirm):
        answers.append(confirm("Run explorer.delete {}? [y/N] "))
        return [{"call": "explorer.delete {}", "status": "success" if answers[-1] == "y" else "skipped", "details": "Deleted 1 item"}]

    spoken, _, _ = wake_loop(["Hey Aura, delete it", "No wait", "Hey Aura, delete it", "Yes."], run)
    assert answers == ["n", "y"]
    assert spoken == ["Should I run explorer delete? Say yes or no.", "Nothing was done.",
                      "Should I run explorer delete? Say yes or no.", "Deleted 1 item"]
