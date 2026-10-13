"""Voice front end for the small-model client.

    python -m automation.mcp.voice                  say "hey aura, turn bluetooth off"
    python -m automation.mcp.voice --push-to-talk   press Enter, speak, press Enter

Speech is transcribed on this PC with Whisper and run through slm_client. A glow around the screen and a
caption show what was heard; the outcome is spoken back with a local neural voice.
Actions not marked safe are confirmed first (say "yes", or type `y` in push-to-talk mode), so a
misheard command cannot delete files. automation.mcp.tray runs the same loop from the system tray.
"""
import argparse
import asyncio
import collections
import contextlib
import json
import os
import pathlib
import queue
import re

import numpy as np

from automation.mcp import slm_client

RATE = 16000  # Hz, what Whisper expects
BLOCK = RATE // 10
WHISPER_MODEL = os.environ.get("AURA_WHISPER_MODEL", "base.en")
# ponytail: CPU by default; "cuda" needs the cuBLAS/cuDNN DLLs on PATH. Switch if transcription feels slow.
WHISPER_DEVICE = os.environ.get("AURA_WHISPER_DEVICE", "cpu")
# Loudness (RMS, 0-1) above which a block counts as speech. Unset: follows the room noise automatically.
THRESHOLD = float(os.environ["AURA_MIC_THRESHOLD"]) if os.environ.get("AURA_MIC_THRESHOLD") else None
# ponytail: the wake phrase is spotted in Whisper's transcript, so all nearby speech is transcribed (locally).
# Swap in a trained wake-word model (openWakeWord) if idle CPU use or false triggers become a problem.
# After a greeting, common mishearings of "aura" are accepted too.
WAKE = re.compile(r"^\W*(?:(?:hey|hi|hay|ok|okay)\W+(?:aura|ora|aurora|oura|laura|ara|aira|auro|orra|or a|our a)"
                  r"|aura)\b\W*(.*)$", re.I | re.S)
MODELS = pathlib.Path(os.environ.get("AURA_DATA_DIR") or pathlib.Path(os.environ.get("LOCALAPPDATA", ".")) / "AURA") / "models"
VOICE = os.environ.get("AURA_VOICE", "af_heart")  # any Kokoro voice name
YES = re.compile(r"\W*(yes|yeah|yep|sure|do it)\b", re.I)

_blocks = queue.Queue()


def flush():
    """Drops audio captured while AURA itself was busy, beeping or speaking."""
    while not _blocks.empty():
        _blocks.get_nowait()


def _tone(notes, seconds=0.9, rate=44100):
    """A soft bell chord: each note enters slightly after the last and rings out."""
    t = np.arange(int(seconds * rate)) / rate
    wave = np.zeros_like(t)
    for i, frequency in enumerate(notes):
        start = i * 0.07
        ring = np.where(t >= start, np.exp(-(t - start) * 5.5) * np.minimum(1, (t - start) / 0.012), 0)
        wave += ring * (np.sin(2 * np.pi * frequency * t) + 0.25 * np.sin(4 * np.pi * frequency * t))
    return (0.16 * wave / len(notes) ** 0.5).astype("float32"), rate


CHIMES = {True: _tone([523.25, 659.25, 783.99, 1174.66]),  # C major add 9, rising: "I'm listening" / "done"
          False: _tone([440.0, 349.23, 293.66])}            # falling D minor: "that did not work"


def chime(ok=True):
    import sounddevice as sd
    sd.play(*CHIMES[ok], blocking=True)


_kokoro = None


def load_voice():
    """Loads the Kokoro neural voice (a few seconds); raises until its files are installed."""
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
    return _kokoro


def say(text):
    """Speaks with the Kokoro voice; falls back to the built-in Windows voice when it is not available."""
    import sounddevice as sd
    try:
        sd.play(*load_voice().create(text, voice=VOICE, speed=1.0, lang="en-us"), blocking=True)
    except Exception as error:
        print(f"Kokoro voice unavailable ({error}); using the Windows voice.")
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        win32com.client.Dispatch("SAPI.SpVoice").Speak(text)


def warn_if_silent(audio):
    if not audio.size or float(np.abs(audio).max()) < 1e-4:
        import sounddevice as sd
        print(f"No sound at all from '{sd.query_devices(kind='input')['name']}'. "
              "Is the microphone muted in Windows (Settings > System > Sound > Input) or by the laptop's mic key?")


def record():
    """Records the microphone until Enter is pressed; returns mono float32 samples at RATE."""
    import sounddevice as sd
    chunks = []
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                        callback=lambda data, *_: chunks.append(data[:, 0].copy())):
        input("Listening... press Enter when done ")
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype="float32")
    warn_if_silent(audio)
    return audio


def microphone():
    """Yields 0.1 s blocks from the default microphone until interrupted."""
    import sounddevice as sd
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK,
                        callback=lambda data, *_: _blocks.put(data[:, 0].copy())):
        # The first second is dropped: this mic opens with a loud pop that would wreck the noise measurement.
        warn_if_silent(np.concatenate([_blocks.get() for _ in range(10)]))
        while True:
            yield _blocks.get()


def utterances(blocks, threshold=THRESHOLD, quiet_blocks=8, max_blocks=150):
    """Groups microphone blocks into utterances: speech, then ~0.8 s of quiet (or 15 s at most)."""
    def loudness(block):
        return float(np.sqrt((block ** 2).mean()))

    lead, speech, quiet = collections.deque(maxlen=3), [], 0
    recent = collections.deque(maxlen=50)  # loudness of the last 5 s, to follow the room's noise level
    for block in blocks:
        recent.append(loudness(block))
        # ponytail: speech = 4x the quiet end of the last 5 s. Set AURA_MIC_THRESHOLD if a steady noise (fan, music) fools it.
        limit = threshold if threshold is not None else max(0.006, 4 * sorted(recent)[len(recent) // 5])
        loud = recent[-1] > limit
        if not speech and not loud:
            lead.append(block)
            continue
        speech.append(block)
        quiet = 0 if loud else quiet + 1
        if quiet >= quiet_blocks or len(speech) >= max_blocks:
            yield np.concatenate([*lead, *speech])
            lead.clear()
            speech, quiet = [], 0


def load_transcriber():
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type="int8" if WHISPER_DEVICE == "cpu" else "float16")

    def transcribe(audio):
        # The prompt only teaches Whisper how the name is spelled; it makes "hey aura" far less likely to come out as "hey ora".
        segments, _ = model.transcribe(audio, language="en", vad_filter=True, initial_prompt="Hey Aura, open Notepad.")
        return " ".join(segment.text.strip() for segment in segments)

    return transcribe


SORRY = "Sorry, that didn't work."


def outcome(steps):
    """(sentence to show and speak, whether it went well) for the steps slm_client.run() returned."""
    if not steps or steps[-1]["status"] == "skipped":
        return "Nothing was done.", True
    last = steps[-1]
    if last["status"] == "failure":
        print(f"Failed: {last['call']} -> {last['details']}")  # the full reason goes to the log, not the user's ears
        return SORRY, False
    return last["details"][:200] or "Done.", True


def spoken_reply(request, steps, llm=slm_client.reply):
    """The last step's result as one natural sentence; agents report in terse technical form ("volume: 30, muted: False")."""
    reply, ok = outcome(steps)
    if not ok or reply in ("Done.", "Nothing was done.") or steps[-1]["call"].startswith("browser.answer_question"):
        return reply, ok
    try:
        reply = llm(slm_client.reply_prompt(request, steps[-1]["call"], steps[-1]["details"]),
                    slm_client.REPLY_SCHEMA)["reply"].strip() or reply
    except Exception as error:  # the raw result is still better than silence
        print(f"Could not rephrase the reply: {error!r}")
    return reply, ok


async def act(text, call_tool, run, confirm, show, say, chime, reply_for=spoken_reply):
    show(text)
    try:
        reply, ok = reply_for(text, await run(text, call_tool, confirm=confirm))
    except Exception as error:  # e.g. the model server is not running; keep listening
        print(f"Could not run that: {error!r}")
        reply, ok = SORRY, False
    show(reply, done=True)
    if not ok or reply == "Done.":
        chime(ok)
    if reply != "Done.":
        say(reply)


def show(text, done=False):
    print(("-> " if done else "Heard: ") + text)


async def listen(call_tool, record, transcribe, run=slm_client.run, wait=input, say=say, chime=chime, reply_for=spoken_reply):
    while wait("\nPress Enter and speak (q to quit): ").strip().lower() != "q":
        text = transcribe(record()).strip()
        if text:
            await act(text, call_tool, run, input, show, say, chime, reply_for)
        else:
            print("Heard nothing.")


async def listen_for_wake_word(call_tool, blocks, transcribe, run=slm_client.run, show=show, say=say, chime=chime,
                               flush=flush, enabled=lambda: True, threshold=THRESHOLD, reply_for=spoken_reply):
    heard = utterances(blocks, threshold)

    def confirm(prompt):
        # ponytail: waits for the next thing said, however long that takes; anything but a yes cancels.
        words = prompt.split()
        say(f"Should I run {re.sub('[._]', ' ', words[1]) if len(words) > 1 else 'that'}? Say yes or no.")
        flush()
        answer = next(heard, None)
        return "y" if answer is not None and YES.match(transcribe(answer)) else "n"

    print('Say "hey aura" and a command.')
    armed = False  # "hey aura" was said on its own; the next thing heard is the command
    for audio in heard:
        if not enabled():
            armed = False
            continue
        text = transcribe(audio).strip()
        match = WAKE.match(text)
        command = match.group(1).strip() if match else (text if armed else "")
        armed = bool(match) and not command
        if match:
            show(command or "Listening…")
            chime()
        if command:
            await act(command, call_tool, run, confirm, show, say, chime, reply_for)
        elif text and not match:
            print(f"(ignored: {text})")
        if match or command:
            flush()


async def serve(push_to_talk=False, enabled=lambda: True):
    transcribe = load_transcriber()
    with contextlib.suppress(Exception):  # so the first reply is not delayed; say() reports a missing voice itself
        load_voice()
    slm_client.server_url()  # start the model now rather than on the first command
    async with slm_client.connect() as call_tool:
        if push_to_talk:
            return await listen(call_tool, record, transcribe)
        from automation.mcp.overlay import Overlay
        overlay = Overlay()

        def on_screen(text, done=False):
            show(text, done)
            overlay.caption(text, 4 if done else 12)  # the glow stays while AURA is listening or working

        await listen_for_wake_word(call_tool, microphone(), transcribe, show=on_screen, enabled=enabled)


def main():
    parser = argparse.ArgumentParser(description="Voice control for AURA")
    parser.add_argument("--push-to-talk", action="store_true", help="press Enter to talk instead of saying 'hey aura'")
    asyncio.run(serve(parser.parse_args().push_to_talk))


if __name__ == "__main__":
    main()
