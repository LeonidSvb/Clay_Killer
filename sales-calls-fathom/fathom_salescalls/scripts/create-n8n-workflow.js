/**
 * Creates the Fathom → Sales Calls Library workflow in n8n
 * Run once: node scripts/create-n8n-workflow.js
 */

require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const N8N_URL = process.env.N8N_URL;
const N8N_KEY = process.env.N8N_API_KEY;

function uid(p) {
  return p + '-' + Math.random().toString(36).slice(2, 10);
}

const ID_WEBHOOK = uid('webhook');
const ID_PARSE   = uid('parse');
const ID_CHAIN   = uid('chain');
const ID_CLAUDE  = uid('claude');
const ID_FORMAT  = uid('format');
const ID_SHEETS  = uid('sheets');

// ─────────────────────────────────────────────
// Parse Fathom Payload
// ─────────────────────────────────────────────
const parseCode = [
  'const body = $input.first().json.body || $input.first().json;',
  '',
  'const recordingId  = body.recording_id || "";',
  'const title        = body.title || body.meeting_title || "";',
  'const createdAt    = body.created_at || "";',
  'const startTime    = body.recording_start_time || "";',
  'const endTime      = body.recording_end_time || "";',
  'const url          = body.url || "";',
  'const transcript   = body.transcript || [];',
  'const summary      = body.default_summary?.markdown_formatted || "";',
  'const actionItems  = (body.action_items || [])',
  '  .map(i => (typeof i === "string" ? i : i.text || i.description || ""))',
  '  .filter(Boolean).join(" | ");',
  'const invitees = (body.calendar_invitees || [])',
  '  .map(i => i.name || i.email || "").filter(Boolean).join(", ");',
  '',
  '// Duration',
  'let durationMin = "";',
  'if (startTime && endTime) {',
  '  const diff = Math.round((new Date(endTime) - new Date(startTime)) / 60000);',
  '  if (diff > 0 && diff < 480) durationMin = diff;',
  '}',
  '',
  '// Prospect name from title',
  'const match = title.match(/between\\s+(.+?)(?:\\s*$|\\s*-|\\s*\\()/i);',
  'const prospectName = match ? match[1].trim() : (invitees || title.slice(0, 50));',
  '',
  '// Talk ratio Leo vs prospect',
  'const myNames = ["leo", "leonid"];',
  'let myChars = 0, totalChars = 0;',
  'for (const seg of transcript) {',
  '  const spk = (seg.speaker?.display_name || "").toLowerCase();',
  '  const len = (seg.text || "").length;',
  '  totalChars += len;',
  '  if (myNames.some(n => spk.includes(n))) myChars += len;',
  '}',
  'const leoTalkPct = totalChars > 0 ? Math.round((myChars / totalChars) * 100) : "";',
  '',
  '// Transcript text for Claude (capped at 14000 chars)',
  'const transcriptText = transcript',
  '  .map(s => (s.speaker?.display_name || "Unknown") + ": " + s.text)',
  '  .join("\\n")',
  '  .slice(0, 14000);',
  '',
  '// Build Claude prompt',
  'const claudePrompt = [',
  '  "You are analyzing a B2B sales call for System Hustle, a signal-based BD service for recruiting agencies.",',
  '  "",',
  '  "Prospect: " + prospectName,',
  '  "Duration: " + durationMin + " minutes",',
  '  "Leo talk ratio: " + leoTalkPct + "%",',
  '  "",',
  '  "TRANSCRIPT:",',
  '  transcriptText,',
  '  "",',
  '  "FATHOM SUMMARY:",',
  '  summary,',
  '  "",',
  '  "Return ONLY a valid JSON object, no markdown, no explanation:",',
  '  JSON.stringify({',
  '    outcome: "Closed|Interested|Not Fit|Follow-up|No Show",',
  '    engagement: "<1-10 how engaged was prospect>",',
  '    leo_confidence: "<1-10 how confident and in-control Leo sounded>",',
  '    key_objection: "<main objection raised or none>",',
  '    buying_signals: "<specific moments showing real interest or none>",',
  '    what_worked: "<1-2 things Leo did well>",',
  '    biggest_mistake: "<single most important thing to fix>",',
  '    next_step: "<concrete agreed next action>"',
  '  }, null, 2)',
  '].join("\\n");',
  '',
  'return [{',
  '  json: {',
  '    recordingId, title, prospectName,',
  '    date: createdAt.slice(0, 10),',
  '    durationMin, leoTalkPct, url,',
  '    summary, actionItems, invitees,',
  '    transcriptLength: transcript.length,',
  '    claudePrompt',
  '  }',
  '}];',
].join('\n');

// ─────────────────────────────────────────────
// Format for Google Sheets
// ─────────────────────────────────────────────
const formatCode = [
  'const parsed = $("Parse Fathom Data").first().json;',
  'let ai = {};',
  '',
  'try {',
  '  const raw = $input.first().json.text || "";',
  '  const cleaned = raw.replace(/```json?\\n?/g, "").replace(/```/g, "").trim();',
  '  ai = JSON.parse(cleaned);',
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

// ─────────────────────────────────────────────
// Workflow definition
// ─────────────────────────────────────────────
const workflow = {
  name: "Fathom -> Sales Calls Library",
  nodes: [
    {
      id: ID_WEBHOOK,
      name: "Fathom Webhook",
      type: "n8n-nodes-base.webhook",
      typeVersion: 2,
      position: [0, 300],
      parameters: {
        httpMethod: "POST",
        path: "fathom-sales-calls",
        responseMode: "onReceived",
        responseData: "",
        options: {}
      },
      webhookId: "fathom-sales-calls"
    },
    {
      id: ID_PARSE,
      name: "Parse Fathom Data",
      type: "n8n-nodes-base.code",
      typeVersion: 2,
      position: [260, 300],
      parameters: { jsCode: parseCode }
    },
    {
      id: ID_CHAIN,
      name: "AI Sales Analysis",
      type: "@n8n/n8n-nodes-langchain.chainLlm",
      typeVersion: 1.7,
      position: [520, 300],
      parameters: {
        promptType: "define",
        text: "={{ $json.claudePrompt }}",
        batching: {}
      }
    },
    {
      id: ID_CLAUDE,
      name: "Claude Haiku",
      type: "@n8n/n8n-nodes-langchain.lmChatAnthropic",
      typeVersion: 1,
      position: [520, 520],
      parameters: {
        model: "claude-haiku-4-5-20251001",
        options: {
          maxTokensToSample: 800,
          temperature: 0.3
        }
      },
      credentials: {
        anthropicApi: {
          id: "tl43n5Qde7Kp6f27",
          name: "Anthropic account"
        }
      }
    },
    {
      id: ID_FORMAT,
      name: "Format for Sheets",
      type: "n8n-nodes-base.code",
      typeVersion: 2,
      position: [780, 300],
      parameters: { jsCode: formatCode }
    },
    {
      id: ID_SHEETS,
      name: "Add to Sales Calls Sheet",
      type: "n8n-nodes-base.googleSheets",
      typeVersion: 4.7,
      position: [1040, 300],
      parameters: {
        operation: "append",
        documentId: {
          __rl: true,
          value: "SHEET_ID_PLACEHOLDER",
          mode: "id"
        },
        sheetName: {
          __rl: true,
          value: "gid=0",
          mode: "id"
        },
        columns: {
          mappingMode: "autoMapInputData",
          value: {},
          matchingColumns: [],
          schema: []
        },
        options: {}
      },
      credentials: {
        googleSheetsOAuth2Api: {
          id: "isvTmT5STgsOYA7P",
          name: "Google Sheets account"
        }
      }
    }
  ],
  connections: {
    "Fathom Webhook": {
      main: [[{ node: "Parse Fathom Data", type: "main", index: 0 }]]
    },
    "Parse Fathom Data": {
      main: [[{ node: "AI Sales Analysis", type: "main", index: 0 }]]
    },
    "Claude Haiku": {
      ai_languageModel: [[{ node: "AI Sales Analysis", type: "ai_languageModel", index: 0 }]]
    },
    "AI Sales Analysis": {
      main: [[{ node: "Format for Sheets", type: "main", index: 0 }]]
    },
    "Format for Sheets": {
      main: [[{ node: "Add to Sales Calls Sheet", type: "main", index: 0 }]]
    }
  },
  settings: {
    executionOrder: "v1"
  }
};

// ─────────────────────────────────────────────
// Create via n8n API
// ─────────────────────────────────────────────
async function main() {
  console.log('Creating workflow in n8n...');
  const res = await fetch(`${N8N_URL}/api/v1/workflows`, {
    method: 'POST',
    headers: {
      'X-N8N-API-KEY': N8N_KEY,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(workflow)
  });

  const created = await res.json();
  if (res.ok && created.id) {
    console.log('Created. Workflow ID:', created.id);
    console.log('Webhook URL:', `${N8N_URL}/webhook/fathom-sales-calls`);
    console.log('Test URL:   ', `${N8N_URL}/webhook-test/fathom-sales-calls`);
  } else {
    console.error('Error:', JSON.stringify(created, null, 2).slice(0, 1000));
    process.exit(1);
  }
}

main().catch(err => { console.error(err.message); process.exit(1); });
