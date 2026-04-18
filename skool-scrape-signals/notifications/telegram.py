import os
import json
import time
import urllib.request
from dotenv import load_dotenv
from db.client import get_unnotified_signals, mark_notified

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', 'upwork-pipeline', '.env'))

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID   = os.environ.get('TG_GROUP_ID', '')
TOPIC_ID  = os.environ.get('TG_TOPIC_SKOOL', '')

CONFIDENCE_LABEL = {'high': 'HIGH', 'medium': 'MED'}
COMMUNITY_NAME = os.environ.get('SKOOL_COMMUNITY_NAME', 'Skool')


def send_message(text, reply_markup=None):
    payload = {
        'chat_id': CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
        'message_thread_id': int(TOPIC_ID) if TOPIC_ID else None,
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    body = json.dumps(payload).encode('utf-8')

    req = urllib.request.Request(
        f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def format_signal(s):
    conf = CONFIDENCE_LABEL.get(s.get('confidence', ''), s.get('confidence', '').upper())
    contact = s.get('contact') or {}
    if isinstance(contact, str):
        try:
            contact = json.loads(contact)
        except Exception:
            contact = {}

    name        = contact.get('name', 'Unknown')
    linkedin    = contact.get('linkedin', '')
    signal_type = (s.get('signal_type') or 'signal').replace('_', ' ').title()
    intent      = (s.get('intent') or '').replace('_', ' ')
    source      = contact.get('source', 'post')

    name_part = name
    if linkedin:
        name_part = f'<a href="{linkedin}">{name}</a>'

    post_link = ''
    if s.get('post_url'):
        post_link = f' | <a href="{s[\"post_url\"]}">Open post</a>'

    lines = [
        f"[{conf}] {signal_type} | {intent} | {COMMUNITY_NAME}",
        f"<b>{s.get('post_title') or 'No title'}</b>",
        f"{name_part} ({source}){post_link}",
        f"",
        f'<i>"{s.get("signal_text", "")[:200]}"</i>',
        f"",
        f"Why: {s.get('reason', '')}",
    ]

    return '\n'.join(lines)


def signal_keyboard(post_id):
    return json.dumps({
        'inline_keyboard': [[
            {'text': 'Good lead', 'callback_data': f'sk:good:{post_id}'},
            {'text': 'Not relevant', 'callback_data': f'sk:bad:{post_id}'},
        ]]
    })


def notify_pending():
    signals = get_unnotified_signals()
    if not signals:
        print('[notify] No new signals to send')
        return 0

    print(f'[notify] Sending {len(signals)} signals...')
    sent_ids = []
    for s in signals:
        try:
            text = format_signal(s)
            keyboard = signal_keyboard(s['post_id'])
            send_message(text, reply_markup=keyboard)
            sent_ids.append(s['post_id'])
            print(f"  sent: {s.get('post_title', '')[:50]}")
            time.sleep(1.5)
        except Exception as e:
            print(f"  error: {e}")
            time.sleep(3)

    mark_notified(sent_ids)
    print(f'[notify] Done: {len(sent_ids)} sent')
    return len(sent_ids)


if __name__ == '__main__':
    notify_pending()
