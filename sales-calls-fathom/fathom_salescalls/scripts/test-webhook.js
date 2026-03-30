const fs   = require('fs');
const path = require('path');

const N8N_URL  = 'https://n8n.srv1133622.hstgr.cloud';
const CALLS_DIR = path.join(__dirname, '../data/calls');

async function main() {
  const files = fs.readdirSync(CALLS_DIR)
    .filter(f => f.includes('2026') && !f.includes('Demo'))
    .sort().reverse();

  const callData = JSON.parse(fs.readFileSync(path.join(CALLS_DIR, files[0]), 'utf8'));
  console.log('Testing with:', callData.title);
  console.log('Transcript segments:', callData.transcript?.length);

  const res = await fetch(`${N8N_URL}/webhook/fathom-sales-calls`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(callData)
  });

  console.log('Status:', res.status);
  const text = await res.text();
  console.log('Response:', text.slice(0, 800));
}

main().catch(e => { console.error(e.message); process.exit(1); });
