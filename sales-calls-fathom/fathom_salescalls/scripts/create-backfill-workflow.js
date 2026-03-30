/**
 * Creates n8n workflow: reads Google Sheets rows without analysis,
 * fetches transcript from Fathom, analyzes via GPT-OSS 120B, updates sheet.
 */

require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const N8N_URL   = process.env.N8N_URL;
const N8N_KEY   = process.env.N8N_API_KEY;
const SHEET_ID  = '1kLHxA4fOmeVTyaVaAgPPS4cqoNf85lq1m0pUCuyC6pM';
const FATHOM_KEY = process.env.FATHOM_API_KEY;

async function api(method, path, body) {
  const res = await fetch(`${N8N_URL}/api/v1${path}`, {
    method,
    headers: { 'X-N8N-API-KEY': N8N_KEY, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  });
  return res.json();
}

// ─── Code: Build AI Prompt ────────────────────────────────────────────────────
const buildPromptCode = [
  '// Sheet row comes from the loop (splitInBatches output)',
  'const row = $("Loop Over Calls").first().json;',
  '',
  '// Transcript from Fathom HTTP response',
  'const transcriptData = $input.first().json;',
  'const transcript = Array.isArray(transcriptData.transcript)',
  '  ? transcriptData.transcript',
  '      .map(s => (s.speaker?.display_name || "Unknown") + ": " + s.text)',
  '      .join("\\n").slice(0, 14000)',
  '  : "";',
  '',
  'const prospect = row["Prospect"] || "";',
  'const duration = row["Duration (min)"] || "";',
  'const talkPct  = row["Leo Talk %"] || "";',
  'const summary  = row["Summary"] || "";',
  '',
  'const claudePrompt = [',
  '  "You are analyzing a B2B sales call for System Hustle, a signal-based BD service for recruiting agencies.",',
  '  "",',
  '  "Prospect: " + prospect,',
  '  "Duration: " + duration + " minutes",',
  '  "Leo talk ratio: " + talkPct + "%",',
  '  "",',
  '  "TRANSCRIPT:",',
  '  transcript || "(not available)",',
  '  "",',
  '  "FATHOM SUMMARY:",',
  '  summary,',
  '  "",',
  '  "Return ONLY valid JSON, no markdown, no explanation:",',
  '  "{",',
  '  "  \\"outcome\\": \\"Closed|Interested|Not Fit|Follow-up|No Show\\",",',
  '  "  \\"engagement\\": <1-10 how engaged was prospect>,",',
  '  "  \\"leo_confidence\\": <1-10 how confident and in-control Leo sounded>,",',
  '  "  \\"key_objection\\": \\"<main objection raised or none>\\",",',
  '  "  \\"buying_signals\\": \\"<specific interest signals or none>\\",",',
  '  "  \\"what_worked\\": \\"<1-2 things Leo did well>\\",",',
  '  "  \\"biggest_mistake\\": \\"<main thing to fix>\\",",',
  '  "  \\"next_step\\": \\"<concrete agreed next action>\\"",',
  '  "}"',
  '].join("\\n");',
  '',
  'return [{ json: { row_number: row.row_number, claudePrompt } }];',
].join('\n');

// ─── Code: Parse AI Response + Format for Update ─────────────────────────────
const parseCode = [
  'const prepared = $("Code: Build Prompt").first().json;',
  'let ai = {};',
  '',
  'try {',
  '  let raw = $input.first().json.text || "";',
  '  raw = raw.replace(/<think>[\\s\\S]*?<\\/think>/gi, "").trim();',
  '  raw = raw.replace(/```json?\\n?/g, "").replace(/```/g, "").trim();',
  '  ai = JSON.parse(raw);',
  '} catch(e) {',
  '  ai = { outcome: "Parse error", biggest_mistake: e.message };',
  '}',
  '',
  'return [{',
  '  json: {',
  '    row_number:        prepared.row_number,',
  '    "Outcome":         ai.outcome || "",',
  '    "Engagement":      String(ai.engagement || ""),',
  '    "Leo Confidence":  String(ai.leo_confidence || ""),',
  '    "Key Objection":   ai.key_objection || "",',
  '    "Buying Signals":  ai.buying_signals || "",',
  '    "What Worked":     ai.what_worked || "",',
  '    "Biggest Mistake": ai.biggest_mistake || "",',
  '    "Next Step":       ai.next_step || ""',
  '  }',
  '}];',
].join('\n');

// ─── Node IDs ─────────────────────────────────────────────────────────────────
const IDs = {
  trigger:     'backfill-trigger',
  getRows:     'backfill-get-rows',
  filter:      'backfill-filter',
  loop:        'backfill-loop',
  transcript:  'backfill-transcript',
  buildPrompt: 'backfill-build-prompt',
  chain:       'backfill-chain',
  groq:        'backfill-groq',
  parse:       'backfill-parse',
  update:      'backfill-update',
  sticky:      'backfill-sticky',
};

const sheetColumns = [
  'Date','Prospect','Duration (min)','Leo Talk %',
  'Outcome','Engagement','Leo Confidence','Key Objection',
  'Buying Signals','What Worked','Biggest Mistake','Next Step',
  'Action Items','Summary','Recording ID','Fathom URL'
];

function schemaEntry(name) {
  return { id: name, displayName: name, required: false, defaultMatch: name === 'row_number', display: true, type: 'string', canBeUsedToMatch: name === 'row_number' };
}

const workflow = {
  name: 'SALES - Backfill Analysis from Sheets',
  nodes: [
    // 1. Manual Trigger
    {
      id: IDs.trigger,
      name: 'Run Manually',
      type: 'n8n-nodes-base.manualTrigger',
      typeVersion: 1,
      position: [0, 300],
      parameters: {}
    },

    // 2. Google Sheets - Get All Rows
    {
      id: IDs.getRows,
      name: 'Get All Rows',
      type: 'n8n-nodes-base.googleSheets',
      typeVersion: 4.7,
      position: [220, 300],
      parameters: {
        operation: 'getAll',
        documentId: { __rl: true, value: SHEET_ID, mode: 'id' },
        sheetName:  { __rl: true, value: 'gid=0', mode: 'id' },
        filtersUI:  { values: [] },
        options:    { returnAllMatches: true }
      },
      credentials: {
        googleSheetsOAuth2Api: { id: 'isvTmT5STgsOYA7P', name: 'Google Sheets account' }
      }
    },

    // 3. Filter - rows without Outcome
    {
      id: IDs.filter,
      name: 'Filter: Missing Analysis',
      type: 'n8n-nodes-base.filter',
      typeVersion: 2.2,
      position: [440, 300],
      parameters: {
        conditions: {
          options: { caseSensitive: false, leftValue: '', typeValidation: 'loose' },
          conditions: [
            {
              id: 'cond-outcome-empty',
              leftValue: "={{ $json['Outcome'] }}",
              rightValue: '',
              operator: { type: 'string', operation: 'empty', singleValue: true }
            },
            {
              id: 'cond-recording-id',
              leftValue: "={{ $json['Recording ID'] }}",
              rightValue: '',
              operator: { type: 'string', operation: 'notEmpty', singleValue: true }
            }
          ],
          combinator: 'and'
        }
      }
    },

    // 4. Loop Over Calls (splitInBatches, 1 at a time)
    {
      id: IDs.loop,
      name: 'Loop Over Calls',
      type: 'n8n-nodes-base.splitInBatches',
      typeVersion: 3,
      position: [660, 300],
      parameters: { batchSize: 1, options: {} }
    },

    // 5. HTTP Request - Fathom Transcript
    {
      id: IDs.transcript,
      name: 'Fathom: Get Transcript',
      type: 'n8n-nodes-base.httpRequest',
      typeVersion: 4.2,
      position: [880, 300],
      parameters: {
        method: 'GET',
        url: `=https://api.fathom.ai/external/v1/recordings/{{ $json['Recording ID'] }}/transcript`,
        authentication: 'none',
        sendHeaders: true,
        headerParameters: {
          parameters: [
            { name: 'X-Api-Key', value: FATHOM_KEY }
          ]
        },
        options: {}
      }
    },

    // 6. Code: Build AI Prompt
    {
      id: IDs.buildPrompt,
      name: 'Code: Build Prompt',
      type: 'n8n-nodes-base.code',
      typeVersion: 2,
      position: [1100, 300],
      parameters: { jsCode: buildPromptCode }
    },

    // 7. AI Chain
    {
      id: IDs.chain,
      name: 'AI Sales Analysis',
      type: '@n8n/n8n-nodes-langchain.chainLlm',
      typeVersion: 1.7,
      position: [1320, 300],
      parameters: {
        promptType: 'define',
        text: '={{ $json.claudePrompt }}',
        batching: {}
      }
    },

    // 8. Groq GPT-OSS 120B (sub-node)
    {
      id: IDs.groq,
      name: 'GPT-OSS 120B (Groq)',
      type: '@n8n/n8n-nodes-langchain.lmChatGroq',
      typeVersion: 1,
      position: [1320, 500],
      parameters: {
        model: 'openai/gpt-oss-120b',
        options: { maxTokensToSample: 1200, temperature: 0.3 }
      },
      credentials: {
        groqApi: { id: 'Qcnvgli2vMgSfRID', name: 'Groq account' }
      }
    },

    // 9. Code: Parse AI Response
    {
      id: IDs.parse,
      name: 'Code: Parse AI',
      type: 'n8n-nodes-base.code',
      typeVersion: 2,
      position: [1540, 300],
      parameters: { jsCode: parseCode }
    },

    // 10. Google Sheets - Update Row
    {
      id: IDs.update,
      name: 'Update Sheet Row',
      type: 'n8n-nodes-base.googleSheets',
      typeVersion: 4.7,
      position: [1760, 300],
      parameters: {
        operation: 'update',
        documentId: { __rl: true, value: SHEET_ID, mode: 'id' },
        sheetName:  { __rl: true, value: 'gid=0', mode: 'id' },
        columns: {
          mappingMode: 'defineBelow',
          value: {
            row_number:          '={{ $json.row_number }}',
            'Outcome':           "={{ $json['Outcome'] }}",
            'Engagement':        "={{ $json['Engagement'] }}",
            'Leo Confidence':    "={{ $json['Leo Confidence'] }}",
            'Key Objection':     "={{ $json['Key Objection'] }}",
            'Buying Signals':    "={{ $json['Buying Signals'] }}",
            'What Worked':       "={{ $json['What Worked'] }}",
            'Biggest Mistake':   "={{ $json['Biggest Mistake'] }}",
            'Next Step':         "={{ $json['Next Step'] }}"
          },
          matchingColumns: ['row_number'],
          schema: [
            schemaEntry('row_number'),
            ...['Outcome','Engagement','Leo Confidence','Key Objection',
                'Buying Signals','What Worked','Biggest Mistake','Next Step'].map(schemaEntry)
          ]
        },
        options: {}
      },
      credentials: {
        googleSheetsOAuth2Api: { id: 'isvTmT5STgsOYA7P', name: 'Google Sheets account' }
      }
    },

    // Sticky Note
    {
      id: IDs.sticky,
      name: 'Sticky Note',
      type: 'n8n-nodes-base.stickyNote',
      typeVersion: 1,
      position: [0, 60],
      parameters: {
        content: [
          '## SALES - Backfill Analysis from Sheets',
          '',
          '## Что делает',
          'Читает Google Sheet, находит строки без Outcome,',
          'подтягивает транскрипт из Fathom API,',
          'анализирует через GPT-OSS 120B (Groq),',
          'обновляет строку в листе.',
          '',
          '## Триггер',
          'Manual — запускать вручную после импорта CSV',
          '',
          '## Credentials',
          '- Google Sheets (isvTmT5STgsOYA7P)',
          '- Groq (Qcnvgli2vMgSfRID)',
          '',
          '## Google Sheet',
          '1kLHxA4fOmeVTyaVaAgPPS4cqoNf85lq1m0pUCuyC6pM',
          '',
          '## Связанные воркфлоу',
          '031gIgLPBlR0KbpM: SALES - Fathom -> Sales Calls Library',
        ].join('\n')
      }
    }
  ],

  connections: {
    'Run Manually':           { main: [[{ node: 'Get All Rows',          type: 'main', index: 0 }]] },
    'Get All Rows':           { main: [[{ node: 'Filter: Missing Analysis', type: 'main', index: 0 }]] },
    'Filter: Missing Analysis': { main: [[{ node: 'Loop Over Calls',     type: 'main', index: 0 }]] },
    'Loop Over Calls':        { main: [
      [],  // output[0] = done
      [{ node: 'Fathom: Get Transcript', type: 'main', index: 0 }]  // output[1] = loop body
    ]},
    'Fathom: Get Transcript': { main: [[{ node: 'Code: Build Prompt',   type: 'main', index: 0 }]] },
    'Code: Build Prompt':     { main: [[{ node: 'AI Sales Analysis',     type: 'main', index: 0 }]] },
    'GPT-OSS 120B (Groq)':   { ai_languageModel: [[{ node: 'AI Sales Analysis', type: 'ai_languageModel', index: 0 }]] },
    'AI Sales Analysis':      { main: [[{ node: 'Code: Parse AI',        type: 'main', index: 0 }]] },
    'Code: Parse AI':         { main: [[{ node: 'Update Sheet Row',      type: 'main', index: 0 }]] },
    'Update Sheet Row':       { main: [[{ node: 'Loop Over Calls',       type: 'main', index: 0 }]] },  // back to loop
  },

  settings: { executionOrder: 'v1' }
};

async function main() {
  console.log('Creating backfill workflow...');
  const created = await api('POST', '/workflows', workflow);

  if (!created.id) {
    console.error('Error:', JSON.stringify(created).slice(0, 500));
    process.exit(1);
  }

  console.log('Created. ID:', created.id);
  console.log('Name:', created.name);
  console.log('Nodes:', created.nodes.map(n => n.name).join(' → '));
  console.log('\nOpen in n8n:', `${N8N_URL}/workflow/${created.id}`);
  console.log('Run manually from n8n UI after importing CSV to Google Sheets.');
}

main().catch(e => { console.error(e.message); process.exit(1); });
