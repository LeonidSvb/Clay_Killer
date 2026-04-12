# VoiceType

Voice-to-text desktop tool for Windows. Hold **Ctrl+Space**, dictate, release — text is transcribed and pasted into whatever window is focused.

Uses Groq Whisper for transcription and an LLM for cleanup.

---

## Requirements

- Windows 10/11
- Python 3.10+
- A Groq API key — get one free at https://console.groq.com

---

## Installation

```bash
pip install groq sounddevice numpy pyperclip pynput pillow pystray pywin32 python-dotenv
```

Clone or download the repo, then create a `.env` file in the project folder:

```
GROQ_API_KEY=your_key_here
```

---

## Running

Double-click `voicetype.bat` — runs silently in the background with a tray icon.

Or directly:

```bash
python voicetype.py
```

---

## Usage

| Action | Result |
|---|---|
| Hold **Ctrl+Space** | Start recording |
| Release **Space** | Stop and transcribe |

A small overlay appears top-right: **REC** while recording, **...** while processing. Text is pasted automatically into the focused window.

Right-click the tray icon to edit the prompt or quit.

---

## Notes

- Windows only — uses WinAPI for text injection
- Prompt is editable from the tray without restart
- Short presses under 0.8s are ignored (prevents Whisper hallucinations)
