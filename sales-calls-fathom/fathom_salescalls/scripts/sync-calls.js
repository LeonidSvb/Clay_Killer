/**
 * Fathom Sales Calls Sync
 * Downloads all calls with transcripts, summaries, and action items.
 * Saves each call as individual JSON + exports CSV library.
 *
 * Usage: node scripts/sync-calls.js
 */

const fs = require('fs');
const path = require('path');

require('dotenv').config({ path: path.join(__dirname, '../.env') });

const API_KEY = process.env.FATHOM_API_KEY;
const BASE = process.env.FATHOM_API_BASE || 'https://api.fathom.ai/external/v1';
const DATA_DIR = path.join(__dirname, '../data/calls');
const CSV_PATH = path.join(__dirname, '../data/calls-library.csv');

async function apiFetch(endpoint) {
  const res = await fetch(`${BASE}${endpoint}`, {
    headers: { 'X-Api-Key': API_KEY }
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

async function fetchAllMeetings() {
  const meetings = [];
  let cursor = null;

  while (true) {
    const params = new URLSearchParams({
      limit: '100',
      include_summary: 'true',
      include_action_items: 'true'
    });
    if (cursor) params.set('cursor', cursor);

    const data = await apiFetch(`/meetings?${params}`);
    meetings.push(...(data.items || []));

    console.log(`  Загружено: ${meetings.length} звонков...`);

    if (!data.next_cursor) break;
    cursor = data.next_cursor;
  }

  return meetings;
}

async function fetchTranscript(recording_id) {
  try {
    const data = await apiFetch(`/recordings/${recording_id}/transcript`);
    return data;
  } catch (e) {
    console.warn(`  Транскрипт для ${recording_id} недоступен: ${e.message}`);
    return null;
  }
}

function calcDurationMinutes(start, end) {
  if (!start || !end) return null;
  const diff = Math.round((new Date(end) - new Date(start)) / 60000);
  // sanity check: calls longer than 8 hours are likely corrupt data
  if (diff < 0 || diff > 480) return null;
  return diff;
}

function formatDate(isoString) {
  if (!isoString) return '';
  return new Date(isoString).toISOString().slice(0, 10);
}

function escapeCSV(value) {
  if (value === null || value === undefined) return '';
  const str = String(value);
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return '"' + str.replace(/"/g, '""') + '"';
  }
  return str;
}

function buildCSVRow(call) {
  const invitees = (call.calendar_invitees || [])
    .map(i => i.email || i.name || '').filter(Boolean).join('; ');

  const actionItems = (call.action_items || [])
    .map(item => typeof item === 'string' ? item : item.text || item.description || JSON.stringify(item))
    .join(' | ');

  const summaryText = call.default_summary
    ? call.default_summary.markdown_formatted.replace(/\n/g, ' ').slice(0, 1000)
    : '';

  return [
    call.recording_id,
    formatDate(call.created_at),
    formatDate(call.recording_start_time),
    escapeCSV(call.title),
    calcDurationMinutes(call.recording_start_time, call.recording_end_time),
    escapeCSV(call.recorded_by || ''),
    escapeCSV(invitees),
    escapeCSV(call.transcript_language || ''),
    call.transcript ? call.transcript.length : 0,
    escapeCSV(actionItems),
    escapeCSV(summaryText),
    escapeCSV(call.url || ''),
    escapeCSV(call.share_url || '')
  ].join(',');
}

async function main() {
  console.log('Fathom Sales Calls Sync');
  console.log('=======================\n');

  if (!API_KEY) {
    console.error('FATHOM_API_KEY не найден в .env');
    process.exit(1);
  }

  console.log('1. Получаю список всех звонков...');
  const meetings = await fetchAllMeetings();
  console.log(`   Всего найдено: ${meetings.length} звонков\n`);

  console.log('2. Скачиваю транскрипты...');
  let transcriptCount = 0;
  for (const meeting of meetings) {
    const transcriptData = await fetchTranscript(meeting.recording_id);
    if (transcriptData) {
      // API returns { transcript: [...] }, unwrap to array
      meeting.transcript = transcriptData.transcript || transcriptData;
      transcriptCount++;
    }
    // небольшая пауза чтобы не превысить rate limit
    await new Promise(r => setTimeout(r, 200));
  }
  console.log(`   Транскриптов загружено: ${transcriptCount}/${meetings.length}\n`);

  console.log('3. Сохраняю JSON файлы...');
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

  for (const meeting of meetings) {
    const date = formatDate(meeting.recording_start_time || meeting.created_at);
    const safeName = (meeting.title || 'untitled')
      .replace(/[^a-zA-Z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .slice(0, 60);
    const filename = `${date}_${meeting.recording_id}_${safeName}.json`;
    const filepath = path.join(DATA_DIR, filename);
    fs.writeFileSync(filepath, JSON.stringify(meeting, null, 2), 'utf8');
  }
  console.log(`   Сохранено: ${meetings.length} файлов в data/calls/\n`);

  console.log('4. Генерирую CSV библиотеку...');
  const csvHeader = [
    'recording_id', 'date_created', 'date_recorded', 'title',
    'duration_min', 'recorded_by', 'invitees', 'language',
    'transcript_segments', 'action_items', 'summary',
    'url', 'share_url'
  ].join(',');

  const csvRows = meetings.map(buildCSVRow);
  const csvContent = [csvHeader, ...csvRows].join('\n');
  fs.writeFileSync(CSV_PATH, csvContent, 'utf8');
  console.log(`   CSV сохранен: data/calls-library.csv\n`);

  // Итоговая статистика
  const totalMinutes = meetings.reduce((sum, m) => {
    return sum + (calcDurationMinutes(m.recording_start_time, m.recording_end_time) || 0);
  }, 0);

  console.log('=======================');
  console.log('Готово!');
  console.log(`Всего звонков:    ${meetings.length}`);
  console.log(`Общее время:      ${Math.round(totalMinutes / 60)}ч ${totalMinutes % 60}мин`);
  console.log(`С транскриптом:   ${transcriptCount}`);
  console.log(`CSV:              data/calls-library.csv`);
  console.log(`JSON файлы:       data/calls/ (${meetings.length} файлов)`);
}

main().catch(err => {
  console.error('Ошибка:', err.message);
  process.exit(1);
});
