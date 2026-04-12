#!/usr/bin/env python3
"""VoiceType - Voice-to-Text Desktop Tool for Windows"""

import atexit
import ctypes
import io
import json
import os
import queue
import sys
import threading
import time
import wave
from ctypes import wintypes

import numpy as np
import pyperclip
import pystray
import sounddevice as sd
import tkinter as tk
import win32api
import win32con
from dotenv import load_dotenv
from groq import Groq
from PIL import Image, ImageDraw
from pynput import keyboard as kb

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
PROMPTS_DIR = os.path.join(SCRIPT_DIR, "prompts")
SYSTEM_PROMPT_PATH = os.path.join(PROMPTS_DIR, "system_prompt.txt")
USER_PROMPT_PATH = os.path.join(PROMPTS_DIR, "user_prompt.txt")
LOG_PATH = os.path.join(SCRIPT_DIR, "voicetype.log")
PID_PATH = os.path.join(SCRIPT_DIR, "voicetype.pid")
MUTEX_NAME = "Local\\VoiceTypeSingleton"
_PID = os.getpid()
_mutex_handle = None


def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [pid={_PID}] {msg}"
    print(line, file=sys.stderr)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _acquire_single_instance() -> bool:
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise OSError("CreateMutexW failed")
    if ctypes.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return False

    _mutex_handle = handle
    return True


def _release_single_instance():
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None


def _write_pid_file():
    with open(PID_PATH, "w", encoding="ascii") as f:
        f.write(str(_PID))


def _cleanup_runtime():
    try:
        if os.path.exists(PID_PATH):
            with open(PID_PATH, "r", encoding="ascii") as f:
                if f.read().strip() == str(_PID):
                    os.remove(PID_PATH)
    except Exception:
        pass
    _release_single_instance()


load_dotenv(os.path.join(SCRIPT_DIR, ".env"))


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def write_text_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


config = load_config()
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"


class S:
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"


_state = S.IDLE
_state_lock = threading.Lock()
_ui_queue = queue.Queue()
_audio_frames = []
_audio_lock = threading.Lock()
_hold_active = False
_toggle_active = False
_watchdog_timer = None
_injecting = False


def get_state():
    with _state_lock:
        return _state


def set_state(s):
    global _state
    with _state_lock:
        _state = s


def _start_watchdog():
    global _watchdog_timer
    _cancel_watchdog()
    _watchdog_timer = threading.Timer(90.0, _watchdog_fire)
    _watchdog_timer.daemon = True
    _watchdog_timer.start()


def _cancel_watchdog():
    global _watchdog_timer
    if _watchdog_timer is not None:
        _watchdog_timer.cancel()
        _watchdog_timer = None


def _watchdog_fire():
    global _hold_active, _toggle_active
    log("watchdog: max recording time exceeded, stopping")
    _hold_active = False
    _toggle_active = False
    if get_state() == S.RECORDING:
        stop_and_process()


def start_recording():
    global _audio_frames, _state
    with _state_lock:
        if _state != S.IDLE:
            return
        _state = S.RECORDING
    with _audio_lock:
        _audio_frames = []
    _ui_queue.put(S.RECORDING)
    _start_watchdog()
    threading.Thread(target=_record_loop, daemon=True).start()


def _record_loop():
    def callback(indata, frames, time_info, status):
        with _audio_lock:
            if get_state() == S.RECORDING:
                _audio_frames.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE, callback=callback):
        while get_state() == S.RECORDING:
            time.sleep(0.05)


def stop_and_process():
    global _state
    with _state_lock:
        if _state != S.RECORDING:
            return
        _state = S.PROCESSING
    _cancel_watchdog()
    _ui_queue.put(S.PROCESSING)
    threading.Thread(target=_process, daemon=True).start()


def _process():
    try:
        with _audio_lock:
            frames = list(_audio_frames)

        duration = len(frames) * 512 / SAMPLE_RATE
        log(f"audio frames={len(frames)} duration~{duration:.1f}s")

        if not frames or duration < 0.8:
            log(f"too short ({duration:.1f}s), skipping")
            return

        audio = np.concatenate(frames, axis=0)
        wav_bytes = _to_wav(audio)
        log(f"wav size={len(wav_bytes)} bytes")

        transcript = _transcribe(wav_bytes)
        log(f"whisper -> {repr(transcript)}")

        if not transcript:
            log("empty transcript, aborting")
            return

        cleaned = _llm_cleanup(transcript)
        log(f"llm -> {repr(cleaned)}")

        if not cleaned:
            log("empty llm output, aborting")
            return

        _inject(cleaned)
        log("injected ok")

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback

        log(traceback.format_exc())
    finally:
        set_state(S.IDLE)
        _ui_queue.put(S.IDLE)


def _to_wav(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


def _transcribe(wav_bytes: bytes) -> str:
    resp = groq_client.audio.transcriptions.create(
        model="whisper-large-v3",
        file=("audio.wav", wav_bytes, "audio/wav"),
        response_format="text",
    )
    text = resp if isinstance(resp, str) else resp.text
    return text.strip()


def _llm_cleanup(text: str) -> str:
    user_prompt = read_text_file(USER_PROMPT_PATH)
    system_prompt = ""
    if os.path.exists(SYSTEM_PROMPT_PATH):
        system_prompt = read_text_file(SYSTEM_PROMPT_PATH)

    llm_model = config.get("llm_model", "llama-3.3-70b-versatile")
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": f"{user_prompt}\n\n<transcript>{text}</transcript>"})

    resp = groq_client.chat.completions.create(
        model=llm_model,
        messages=messages,
        temperature=0.1,
        max_tokens=1024,
    )
    return resp.choices[0].message.content.strip()


def _inject(text: str):
    global _injecting
    log(
        f"[INJ] start | hold_active={_hold_active} toggle_active={_toggle_active} "
        f"ctrl_held={_ctrl_held} state={get_state()}"
    )
    pyperclip.copy(text)
    _injecting = True
    try:
        log("[INJ] clipboard set, sleeping 400ms")
        time.sleep(0.4)
        log(f"[INJ] before CTRL down | ctrl_held={_ctrl_held}")
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        log("[INJ] before V down")
        win32api.keybd_event(0x56, 0, 0, 0)
        log("[INJ] before V up")
        win32api.keybd_event(0x56, 0, win32con.KEYEVENTF_KEYUP, 0)
        log("[INJ] before CTRL up")
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        log(f"[INJ] done | ctrl_held={_ctrl_held} hold_active={_hold_active}")
        time.sleep(0.1)
    finally:
        _injecting = False


class Overlay:
    W = 52
    H = 18
    MARGIN = 6

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.90)
        self.root.configure(bg="#111111")

        sw = self.root.winfo_screenwidth()
        x = sw - self.W - self.MARGIN
        y = self.MARGIN
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

        self.label = tk.Label(
            self.root,
            text="",
            bg="#111111",
            fg="#555555",
            font=("Consolas", 8, "bold"),
            anchor="center",
        )
        self.label.pack(fill=tk.BOTH, expand=True)

        self.root.withdraw()
        self.root.after(80, self._poll)

    def _poll(self):
        try:
            while True:
                msg = _ui_queue.get_nowait()
                if isinstance(msg, tuple) and msg[0] == "open_editor":
                    self._open_prompt_editor(msg[1], msg[2])
                else:
                    self._apply(msg)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _open_prompt_editor(self, prompt_path: str, title: str):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.attributes("-topmost", True)
        win.resizable(True, True)
        win.geometry("700x520")

        txt = tk.Text(win, wrap=tk.WORD, font=("Consolas", 10), padx=6, pady=6)
        txt.insert("1.0", read_text_file(prompt_path))
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))
        txt.focus_set()

        def save():
            new_prompt = txt.get("1.0", tk.END).strip()
            try:
                write_text_file(prompt_path, new_prompt + "\n")
                log(f"prompt updated: {prompt_path} {repr(new_prompt[:60])}")
            except Exception as e:
                log(f"ERROR saving prompt: {e}")
            win.destroy()

        btn = tk.Button(win, text="Save", command=save, width=10)
        btn.pack(pady=(0, 8))
        win.bind("<Control-Return>", lambda e: save())

    def _apply(self, state: str):
        if state == S.RECORDING:
            self.label.config(text="REC", fg="#ff2222", bg="#1a0000")
            self.root.configure(bg="#1a0000")
            self.root.deiconify()
        elif state == S.PROCESSING:
            self.label.config(text="...", fg="#ffaa00", bg="#111111")
            self.root.configure(bg="#111111")
            self.root.deiconify()
        else:
            self.root.withdraw()

    def run(self):
        self.root.mainloop()


def _tray_icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=(45, 110, 190))
    d.ellipse([22, 10, 42, 30], fill=(220, 220, 220))
    d.rectangle([29, 28, 35, 44], fill=(220, 220, 220))
    d.line([22, 44, 42, 44], fill=(220, 220, 220), width=3)
    return img


def _tray_open_config(icon, item):
    os.startfile(CONFIG_PATH)


def _tray_open_prompts(icon, item):
    os.startfile(PROMPTS_DIR)


def _tray_edit_user_prompt(icon, item):
    _ui_queue.put(("open_editor", USER_PROMPT_PATH, "Edit User Prompt"))


def _tray_edit_system_prompt(icon, item):
    _ui_queue.put(("open_editor", SYSTEM_PROMPT_PATH, "Edit System Prompt"))


def _tray_quit(icon, item):
    icon.stop()
    os._exit(0)


def start_tray():
    icon = pystray.Icon(
        "VoiceType",
        _tray_icon(),
        "VoiceType",
        menu=pystray.Menu(
            pystray.MenuItem("Edit user prompt", _tray_edit_user_prompt),
            pystray.MenuItem("Edit system prompt", _tray_edit_system_prompt),
            pystray.MenuItem("Open prompts folder", _tray_open_prompts),
            pystray.MenuItem("Open config", _tray_open_config),
            pystray.MenuItem("Quit", _tray_quit),
        ),
    )
    icon.run()


_CTRL_KEYS = {kb.Key.ctrl_l, kb.Key.ctrl_r}
_SHIFT_KEYS = {kb.Key.shift, kb.Key.shift_l, kb.Key.shift_r}
_ctrl_held = False
_shift_held = False


def _on_press(key):
    global _hold_active, _toggle_active, _ctrl_held, _shift_held

    if _injecting:
        return

    if key in _CTRL_KEYS:
        _ctrl_held = True
        log(f"[KEY] CTRL press | state={get_state()} hold={_hold_active} toggle={_toggle_active}")
        return
    if key in _SHIFT_KEYS:
        _shift_held = True
        return

    if _toggle_active:
        if get_state() == S.RECORDING:
            log(f"[KEY] toggle stop by key={key}")
            _toggle_active = False
            stop_and_process()
        return

    if key == kb.Key.space and _ctrl_held and get_state() == S.IDLE:
        if _shift_held:
            _toggle_active = True
            log("toggle recording started")
            start_recording()
        else:
            _hold_active = True
            log("hold recording started")
            start_recording()


def _on_release(key):
    global _hold_active, _ctrl_held, _shift_held

    if _injecting:
        return

    if key in _SHIFT_KEYS:
        _shift_held = False
        return

    if key in _CTRL_KEYS:
        _ctrl_held = False
        log(f"[KEY] CTRL release | state={get_state()} hold={_hold_active}")
        if _hold_active and get_state() == S.RECORDING:
            _hold_active = False
            stop_and_process()
        return

    if _hold_active and key == kb.Key.space:
        log(f"[KEY] SPACE release | state={get_state()} hold={_hold_active}")
        if get_state() == S.RECORDING:
            _hold_active = False
            stop_and_process()


def start_listener():
    listener = kb.Listener(on_press=_on_press, on_release=_on_release)
    listener.daemon = True
    listener.start()
    return listener


if __name__ == "__main__":
    if not _acquire_single_instance():
        log("VoiceType already running, exiting second instance")
        sys.exit(0)

    _write_pid_file()
    atexit.register(_cleanup_runtime)
    log(f"VoiceType started, log={LOG_PATH}")
    log(f"hotkey_hold={config.get('hotkey_hold')} hotkey_toggle={config.get('hotkey_toggle')}")
    threading.Thread(target=start_tray, daemon=True).start()
    start_listener()
    overlay = Overlay()
    overlay.run()
