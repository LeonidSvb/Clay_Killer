# VoiceType
## Voice-to-Text Desktop Tool for Windows
### Product Requirements Document
Personal Use - April 2026

## Platform
- Windows 10/11
- Hotkey: Right Alt (hold)
- STT Engine: Groq Whisper (primary)
- Languages: Russian + English (mixed)
- Post-processing: one editable global LLM prompt

## 1. Problem Statement
Dictating text on Windows is unnecessarily painful. Existing solutions like Aqua Voice ($10/mo) work well but cost money every month and offer limited control over how transcription is processed. As someone who codes, writes cold emails, and messages clients daily, switching between keyboard and voice should be instant and zero-friction.

The core problem: there is no lightweight, hotkey-triggered voice input tool on Windows that works globally in any app, transcribes fast, and stays simple enough to trust every day.

## 2. Who This Is For
This tool is built for personal use only: Leonid Shvorob, a solopreneur running a B2B agency from Bali. The typical usage context:

- Coding in VS Code or Cursor - dictating variable names, comments, prompts
- Writing cold emails in the browser - needs clean English output
- Messaging clients in Telegram or WhatsApp Desktop - casual Russian tone
- Filling in Notion / Airtable / Google Sheets - quick data entry without typing
- Working long hours where typing causes fatigue

No multi-user support, no SaaS layer, no accounts. One machine, one user, one config file.

## 3. Goals & Success Metrics
### Primary Goal
Dictate text into any Windows field in under 2 seconds from hotkey press to text appearing, with automatic LLM cleanup driven by one simple editable prompt.

### Success Looks Like
- Hold Right Shift, speak, release, text appears. Total flow under 2s for short phrases.
- Output is cleaned by a global prompt that can be edited quickly in `config.json`
- Monthly API cost under $5 for typical daily usage (~30-60 min dictation/day)
- Zero subscription fees. One-time setup, runs forever.

## 4. Core User Flow
### Happy Path

| Step | Action | What Happens |
| --- | --- | --- |
| 1 | Hold Right Shift | Microphone starts recording. Small overlay appears (REC). |
| 2 | Speak | Audio is captured continuously in memory as WAV/MP3. |
| 3 | Release Right Shift | Recording stops. Overlay changes to standby. Audio sent to Groq Whisper API. |
| 4 | STT + LLM | Raw transcript sent to LLM (Groq llama) with one global editable prompt. Clean text returned. |
| 5 | Text injected | Text copied to clipboard, simulated Ctrl+V pastes into the current cursor location. Overlay disappears. |

## 5. Feature Scope
### MVP Features

| Feature | Detail | Phase |
| --- | --- | --- |
| Global hotkey | Right Shift held = record, released = send. Works in any focused window via pynput. | MVP |
| Groq STT | Whisper-large-v3 via Groq API. Supports RU+EN mixed speech. ~0.001$/min. | MVP |
| Clipboard inject | pyperclip.copy() + keyboard.send('ctrl+v') pastes into the focused cursor location. | MVP |
| Recording indicator | Tiny always-on-top overlay (tkinter or win32). Shows REC / standby states. | MVP |
| Tray icon | System tray icon via pystray. Right-click to quit or open config. | MVP |
| Config file (JSON) | Editable JSON with API key, hotkey, and one global prompt that can be changed fast. | MVP |
| BAT launcher | voicetype.bat in startup folder so it launches on Windows boot silently. | MVP |
| Hotkey toggle | Optional second hotkey to enable/disable without closing app. | V2 |
| .exe packaging | PyInstaller build so Python install is not required. | V2 |

## 6. Prompt Model
The config file (`config.json`) uses one editable global prompt. There are no app rules, no profile switching, and no hidden priority logic.

Recommended default prompt:

```text
Fix punctuation and paragraph breaks. Preserve the original language. If the speech is mixed Russian and English, keep both languages as spoken and only clean obvious errors. Return only the final text, no explanations.
```

If you want it stricter later, this prompt is the only thing to edit.

## 7. Technical Architecture
### Stack
- Language: Python 3.11+
- Audio capture: sounddevice + numpy (WAV in memory, no temp files)
- Hotkey listener: pynput (global keyboard hook, works even when app not focused)
- STT API: Groq Whisper large-v3 via groq Python SDK
- LLM post-processing: Groq llama-3-8b-instant (fast, cheap, ~$0.0001/call)
- Text injection: pyperclip + pynput keyboard controller (Ctrl+V simulation)
- Overlay UI: tkinter always-on-top window (minimal, no dependencies)
- Tray icon: pystray + Pillow
- Config: JSON file in same directory as script
- Launcher: .bat file added to Windows Startup folder

### Cost Estimate (daily 30 min dictation)
- Groq Whisper: 30 min x $0.001/min = $0.03/day, about $0.90/month
- Groq LLM (llama-3-8b): small cleanup pass per dictation, under $0.10/month
- Total: about $1-2/month vs Aqua at $10/month, 5-10x cheaper

## 8. Configuration File Structure
`config.json` sits next to the script. Edit it in any text editor to add/modify rules.

```json
{
  "groq_api_key": "gsk_...",
  "hotkey": "right_shift",
  "default_prompt": "Fix punctuation and paragraph breaks. Preserve the original language. Return only the final text."
}
```

## 9. Out of Scope (MVP)
- Cloud sync or remote config
- Multiple user profiles
- Streaming / real-time transcription (word-by-word)
- Voice commands (e.g. "delete last word")
- Mobile version
- GUI settings panel (use config.json directly)
- Offline mode / local Whisper
- App-aware prompt rules
- History log

## 10. Risks & Mitigations
| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Ctrl+V pastes in the wrong place if focus changes during processing | Medium | Keep the workflow as short as possible and paste immediately after cleanup. |
| Groq API downtime | Medium | No fallback in MVP. If Groq is unavailable, transcription waits and shows an error. |
| Windows Defender flags pynput (keyboard hook) | Medium | Add exception in Defender. Known issue with keyboard hook libraries. |
| Clipboard overwritten by another app during inject | Low | Save and restore clipboard before/after paste. 100ms delay window. |

## 11. Implementation Plan
### Phase 1 - MVP (Est. 4-6 hours total)
- Hour 1: Project setup, config.json structure, Groq API test
- Hour 2: pynput hotkey + sounddevice audio capture loop
- Hour 3: Groq Whisper integration + LLM post-processing pipeline
- Hour 4: pyperclip inject + overlay UI (tkinter)
- Hour 5: pystray tray icon + BAT launcher + end-to-end test

### Phase 2 - Polish (Est. 2-3 hours)
- Hotkey toggle (enable/disable without restart)
- Error handling: API failures, microphone not found, network timeout
- Simple prompt editing in `config.json`

### Phase 3 - Optional
- PyInstaller .exe packaging (no Python install needed)
- Better tray UX
- Optional richer prompt presets

---

VoiceType PRD - Personal Use - Leonid Shvorob - April 2026
