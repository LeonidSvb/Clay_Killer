/**
 * Sends all historical calls through the n8n webhook.
 * Each call gets analyzed by GPT-OSS 120B and added to Google Sheets.
 * Usage: node scripts/backfill-sheet.js
 */

const fs   = require('fs');
const path = require('path');

require('dotenv').config({ path: path.join(__dirname, '../.env') });

const WEBHOOK_URL = `${process.env.N8N_URL}/webhook/fathom-sales-calls`;
const CALLS_DIR   = path.join(__dirname, '../data/calls');

async function main() {
  const files = fs.readdirSync(CALLS_DIR)
    .filter(f => f.endsWith('.json'))
    .sort(); // oldest first

  console.log(`Sending ${files.length} calls to n8n...\n`);

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const call = JSON.parse(fs.readFileSync(path.join(CALLS_DIR, file), 'utf8'));
    const label = `[${i + 1}/${files.length}] ${call.title?.slice(0, 55) || file}`;

    process.stdout.write(label + ' ... ');

    try {
      const res = await fetch(WEBHOOK_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(call)
      });
      const text = await res.text();
      if (res.ok) {
        console.log('sent');
      } else {
        console.log('ERROR', res.status, text.slice(0, 100));
      }
    } catch(e) {
      console.log('FAILED:', e.message);
    }

    // 4s between calls — Groq + Sheets rate limit
    if (i < files.length - 1) {
      await new Promise(r => setTimeout(r, 4000));
    }
  }

  console.log('\nAll sent. Waiting 15s for last execution to finish...');
  await new Promise(r => setTimeout(r, 15000));
  console.log('Done. Check Google Sheets.');
}

main().catch(e => { console.error(e.message); process.exit(1); });
