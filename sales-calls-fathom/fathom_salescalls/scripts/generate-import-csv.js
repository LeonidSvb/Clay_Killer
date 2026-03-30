/**
 * Generates a Google Sheets-ready CSV from all downloaded call JSON files.
 * Analyzes each call with Claude Haiku (using ANTHROPIC_API_KEY from env).
 * Usage: ANTHROPIC_API_KEY=sk-ant-... node scripts/generate-import-csv.js
 *   OR:  node scripts/generate-import-csv.js  (skips AI, leaves analysis cols blank)
 */

const fs   = require('fs');
const path = require('path');

require('dotenv').config({ path: path.join(__dirname, '../.env') });

const CALLS_DIR  = path.join(__dirname, '../data/calls');
const OUTPUT_CSV = path.join(__dirname, '../data/calls-import.csv');
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;

function escapeCSV(v) {
  if (v === null || v === undefined) return '';
  const s = String(v).replace(/\r?\n/g, ' ');
  return (s.includes(',') || s.includes('"')) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function calcDuration(start, end) {
  if (!start || !end) return '';
  const d = Math.round((new Date(end) - new Date(start)) / 60000);
  return (d > 0 && d < 480) ? d : '';
}

function calcTalkRatio(transcript) {
  if (!Array.isArray(transcript) || transcript.length === 0) return '';
  const myNames = ['leo', 'leonid'];
  let myChars = 0, total = 0;
  for (const seg of transcript) {
    const spk = (seg.speaker?.display_name || '').toLowerCase();
    const len = (seg.text || '').length;
    total += len;
    if (myNames.some(n => spk.includes(n))) myChars += len;
  }
  return total > 0 ? Math.round((myChars / total) * 100) : '';
}

function extractProspect(title, invitees) {
  const m = title.match(/between\s+(.+?)(?:\s*$|\s*-|\s*\()/i);
  if (m) return m[1].trim();
  return invitees || title.slice(0, 50);
}

async function analyzeWithClaude(call, transcriptText) {
  if (!ANTHROPIC_KEY) return null;

  const invitees = (call.calendar_invitees || [])
    .map(i => i.name || i.email || '').filter(Boolean).join(', ');
  const prospect = extractProspect(call.title || '', invitees);
  const duration = calcDuration(call.recording_start_time, call.recording_end_time);
  const talkPct  = calcTalkRatio(call.transcript);
  const summary  = call.default_summary?.markdown_formatted || '';

  const prompt = [
    'You are analyzing a B2B sales call for System Hustle, a signal-based BD service for recruiting agencies.',
    '',
    'Prospect: ' + prospect,
    'Duration: ' + duration + ' minutes',
    'Leo talk ratio: ' + talkPct + '%',
    '',
    'TRANSCRIPT (excerpt):',
    transcriptText.slice(0, 10000),
    '',
    'FATHOM SUMMARY:',
    summary.slice(0, 2000),
    '',
    'Return ONLY a valid JSON object, no markdown:',
    '{',
    '  "outcome": "Closed|Interested|Not Fit|Follow-up|No Show",',
    '  "engagement": <1-10>,',
    '  "leo_confidence": <1-10>,',
    '  "key_objection": "<main objection or none>",',
    '  "buying_signals": "<specific interest signals or none>",',
    '  "what_worked": "<1-2 things Leo did well>",',
    '  "biggest_mistake": "<main thing to fix>",',
    '  "next_step": "<agreed next action>"',
    '}'
  ].join('\n');

  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': ANTHROPIC_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json'
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 600,
        temperature: 0.3,
        messages: [{ role: 'user', content: prompt }]
      })
    });
    const data = await res.json();
    const raw = data.content?.[0]?.text || '';
    const cleaned = raw.replace(/```json?\n?/g, '').replace(/```/g, '').trim();
    return JSON.parse(cleaned);
  } catch(e) {
    console.warn('  Claude error for', call.recording_id + ':', e.message);
    return null;
  }
}

async function main() {
  const files = fs.readdirSync(CALLS_DIR)
    .filter(f => f.endsWith('.json'))
    .sort()
    .reverse(); // newest first

  console.log(`Processing ${files.length} calls...`);
  if (ANTHROPIC_KEY) {
    console.log('Claude Haiku analysis: ON');
  } else {
    console.log('Claude analysis: OFF (set ANTHROPIC_API_KEY to enable)');
  }

  const columns = [
    'Date', 'Prospect', 'Duration (min)', 'Leo Talk %',
    'Outcome', 'Engagement', 'Leo Confidence',
    'Key Objection', 'Buying Signals', 'What Worked', 'Biggest Mistake', 'Next Step',
    'Action Items', 'Summary', 'Recording ID', 'Fathom URL'
  ];

  const rows = [columns.join(',')];

  for (const file of files) {
    const call = JSON.parse(fs.readFileSync(path.join(CALLS_DIR, file), 'utf8'));

    const invitees  = (call.calendar_invitees || [])
      .map(i => i.name || i.email || '').filter(Boolean).join(', ');
    const prospect  = extractProspect(call.title || '', invitees);
    const date      = (call.created_at || '').slice(0, 10);
    const duration  = calcDuration(call.recording_start_time, call.recording_end_time);
    const talkPct   = calcTalkRatio(call.transcript);
    const summary   = call.default_summary?.markdown_formatted || '';
    const actionItems = (call.action_items || [])
      .map(i => (typeof i === 'string' ? i : i.text || '')).filter(Boolean).join(' | ');

    const transcriptText = Array.isArray(call.transcript)
      ? call.transcript.map(s => (s.speaker?.display_name || 'Unknown') + ': ' + s.text).join('\n')
      : '';

    let ai = null;
    if (ANTHROPIC_KEY) {
      process.stdout.write('  Analyzing: ' + prospect + '...');
      ai = await analyzeWithClaude(call, transcriptText);
      console.log(ai ? ' done' : ' failed');
      await new Promise(r => setTimeout(r, 500));
    }

    const row = [
      date,
      prospect,
      duration,
      talkPct,
      ai?.outcome || '',
      ai?.engagement || '',
      ai?.leo_confidence || '',
      ai?.key_objection || '',
      ai?.buying_signals || '',
      ai?.what_worked || '',
      ai?.biggest_mistake || '',
      ai?.next_step || '',
      actionItems,
      summary.replace(/\n/g, ' ').slice(0, 1500),
      call.recording_id || '',
      call.url || ''
    ].map(escapeCSV).join(',');

    rows.push(row);
  }

  fs.writeFileSync(OUTPUT_CSV, rows.join('\n'), 'utf8');
  console.log('\nSaved:', OUTPUT_CSV);
  console.log('Rows:', rows.length - 1);
}

main().catch(e => { console.error(e.message); process.exit(1); });
