/**
 * Updates the Fathom workflow:
 * - Replaces Anthropic Claude node with Groq DeepSeek-R1 reasoning model
 * - Sets actual Google Sheets spreadsheet ID
 * - Adds StickyNote per reference rules
 * - Activates the workflow
 */

require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const N8N_URL     = process.env.N8N_URL;
const N8N_KEY     = process.env.N8N_API_KEY;
const WF_ID       = process.env.N8N_WORKFLOW_ID || '031gIgLPBlR0KbpM';
const SHEET_ID    = '1kLHxA4fOmeVTyaVaAgPPS4cqoNf85lq1m0pUCuyC6pM';

async function api(method, path, body) {
  const res = await fetch(`${N8N_URL}/api/v1${path}`, {
    method,
    headers: { 'X-N8N-API-KEY': N8N_KEY, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  });
  return res.json();
}

// ─────────────────────────────────────────────
// Format for Sheets — updated to handle DeepSeek <think> tags
// ─────────────────────────────────────────────
const formatCode = [
  'const parsed = $("Parse Fathom Data").first().json;',
  'let ai = {};',
  '',
  'try {',
  '  let raw = $input.first().json.text || "";',
  '  // Strip DeepSeek reasoning <think>...</think> block',
  '  raw = raw.replace(/<think>[\\s\\S]*?<\\/think>/gi, "").trim();',
  '  // Strip markdown fences',
  '  raw = raw.replace(/```json?\\n?/g, "").replace(/```/g, "").trim();',
  '  ai = JSON.parse(raw);',
  '} catch(e) {',
  '  ai = { outcome: "Parse error", biggest_mistake: e.message };',
  '}',
  '',
  'return [{',
  '  json: {',
  '    "Date":            parsed.date,',
  '    "Prospect":        parsed.prospectName,',
  '    "Duration (min)":  parsed.durationMin,',
  '    "Leo Talk %":      parsed.leoTalkPct,',
  '    "Outcome":         ai.outcome || "",',
  '    "Engagement":      ai.engagement || "",',
  '    "Leo Confidence":  ai.leo_confidence || "",',
  '    "Key Objection":   ai.key_objection || "",',
  '    "Buying Signals":  ai.buying_signals || "",',
  '    "What Worked":     ai.what_worked || "",',
  '    "Biggest Mistake": ai.biggest_mistake || "",',
  '    "Next Step":       ai.next_step || "",',
  '    "Action Items":    parsed.actionItems,',
  '    "Summary":         parsed.summary.slice(0, 2000),',
  '    "Recording ID":    parsed.recordingId,',
  '    "Fathom URL":      parsed.url',
  '  }',
  '}];',
].join('\n');

async function main() {
  console.log('Fetching current workflow...');
  const wf = await api('GET', `/workflows/${WF_ID}`);

  // ── 1. Replace Claude node → Groq DeepSeek-R1 ──────────────────────────
  const newNodes = wf.nodes.map(node => {
    if (node.name === 'Claude Haiku') {
      return {
        ...node,
        id: 'groq-r1-model',
        name: 'DeepSeek R1 (Groq)',
        type: '@n8n/n8n-nodes-langchain.lmChatGroq',
        typeVersion: 1,
        parameters: {
          model: 'deepseek-r1-distill-llama-70b',
          options: {
            maxTokensToSample: 1200,
            temperature: 0.4
          }
        },
        credentials: {
          groqApi: {
            id: 'Qcnvgli2vMgSfRID',
            name: 'Groq account'
          }
        }
      };
    }

    // Update Google Sheets node with real spreadsheet ID
    if (node.name === 'Add to Sales Calls Sheet') {
      return {
        ...node,
        parameters: {
          ...node.parameters,
          operation: 'append',
          documentId: {
            __rl: true,
            value: SHEET_ID,
            mode: 'id'
          },
          sheetName: {
            __rl: true,
            value: 'gid=0',
            mode: 'id'
          },
          columns: {
            mappingMode: 'autoMapInputData',
            value: {},
            matchingColumns: [],
            schema: []
          },
          options: {}
        }
      };
    }

    // Update Format node with think-tag stripping
    if (node.name === 'Format for Sheets') {
      return {
        ...node,
        parameters: { jsCode: formatCode }
      };
    }

    return node;
  });

  // ── 2. Add StickyNote ───────────────────────────────────────────────────
  newNodes.push({
    id: 'sticky-fathom',
    name: 'Sticky Note',
    type: 'n8n-nodes-base.stickyNote',
    typeVersion: 1,
    position: [0, 0],
    parameters: {
      content: [
        '## SALES - Fathom Webhook → Sales Calls Library',
        '',
        '## Что делает',
        'После каждого звонка Fathom отправляет данные сюда.',
        'Транскрипт анализирует DeepSeek R1 (Groq) и записывает результат в Google Sheets.',
        '',
        '## Триггер',
        'Webhook POST /fathom-sales-calls (зарегистрирован в Fathom API)',
        '',
        '## Credentials нужны',
        '- Groq (Qcnvgli2vMgSfRID)',
        '- Google Sheets (isvTmT5STgsOYA7P)',
        '',
        '## Fathom Webhook ID',
        'Wy8j_zgK_nj_Vsdx',
        '',
        '## Google Sheet',
        '1kLHxA4fOmeVTyaVaAgPPS4cqoNf85lq1m0pUCuyC6pM',
      ].join('\n')
    }
  });

  // ── 3. Fix connections: Claude Haiku → DeepSeek R1 ─────────────────────
  const newConnections = { ...wf.connections };
  if (newConnections['Claude Haiku']) {
    newConnections['DeepSeek R1 (Groq)'] = newConnections['Claude Haiku'];
    delete newConnections['Claude Haiku'];
  }

  // ── 4. PUT updated workflow (only fields n8n accepts) ──────────────────
  console.log('Updating workflow...');
  const updated = await api('PUT', `/workflows/${WF_ID}`, {
    name: 'SALES - Fathom -> Sales Calls Library',
    nodes: newNodes,
    connections: newConnections,
    settings: wf.settings || { executionOrder: 'v1' },
    staticData: wf.staticData || null
  });

  if (updated.id) {
    console.log('Updated. ID:', updated.id);
    console.log('Nodes:', updated.nodes.map(n => n.name).join(', '));
  } else {
    console.error('Update error:', JSON.stringify(updated).slice(0, 500));
    process.exit(1);
  }

  // ── 5. Activate ─────────────────────────────────────────────────────────
  console.log('Activating...');
  const activated = await api('POST', `/workflows/${WF_ID}/activate`);
  console.log('Active:', activated.active);
  console.log('\nDone.');
  console.log('Webhook: https://n8n.srv1133622.hstgr.cloud/webhook/fathom-sales-calls');
  console.log('Sheet:   https://docs.google.com/spreadsheets/d/' + SHEET_ID);
}

main().catch(e => { console.error(e.message); process.exit(1); });
