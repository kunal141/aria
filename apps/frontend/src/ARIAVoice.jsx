/**
 * ARIA Voice MVP — Week 26
 *
 * Browser-native voice interface using Web Speech API (no external SDK).
 * Sends transcripts to the ARIA Voice API and speaks the response.
 *
 * Governance contract (identical to Teams bot):
 *   - T1/T2 (read-only: kpi, pr_review, ci_cd, qa, test_review) execute directly.
 *   - T3/T4 (jira creation, posting) are REFUSED. Voice cannot bypass approvals.
 *   - When approval_required=true the response card is shown but speech says
 *     "I need your approval before I can do that. Open the dashboard to proceed."
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

const VOICE_API = 'http://localhost:8001/voice/run';

// ── Task-type display helpers ─────────────────────────────────────────────────
const TYPE_LABELS = {
  kpi:          { label: 'KPI Analysis',     color: 'bg-blue-100 text-blue-800'   },
  pr_review:    { label: 'PR Review',        color: 'bg-purple-100 text-purple-800' },
  ci_cd:        { label: 'CI/CD',            color: 'bg-orange-100 text-orange-800' },
  qa:           { label: 'QA / Test Gen',    color: 'bg-green-100 text-green-800'  },
  test_review:  { label: 'Test Review',      color: 'bg-teal-100 text-teal-800'   },
  jira:         { label: 'Jira',             color: 'bg-red-100 text-red-800'     },
  general:      { label: 'General',          color: 'bg-gray-100 text-gray-700'   },
  unknown:      { label: 'Unknown',          color: 'bg-gray-100 text-gray-700'   },
};

function TypeBadge({ taskType }) {
  const meta = TYPE_LABELS[taskType] || TYPE_LABELS.unknown;
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${meta.color}`}>
      {meta.label}
    </span>
  );
}

// ── Mic button states ─────────────────────────────────────────────────────────
const MIC_IDLE     = 'idle';
const MIC_LISTEN   = 'listening';
const MIC_THINKING = 'thinking';
const MIC_SPEAKING = 'speaking';

const MIC_COLORS = {
  [MIC_IDLE]:     'bg-violet-600 hover:bg-violet-700',
  [MIC_LISTEN]:   'bg-red-500 hover:bg-red-600 animate-pulse',
  [MIC_THINKING]: 'bg-amber-500 cursor-wait',
  [MIC_SPEAKING]: 'bg-green-600 cursor-default',
};

const MIC_LABELS = {
  [MIC_IDLE]:     'Hold to speak',
  [MIC_LISTEN]:   'Listening...',
  [MIC_THINKING]: 'Thinking...',
  [MIC_SPEAKING]: 'Speaking...',
};

// ── History item ──────────────────────────────────────────────────────────────
function HistoryItem({ item }) {
  const isBlocked = item.approval_required;
  return (
    <div className={`rounded-lg border p-4 ${isBlocked ? 'border-amber-300 bg-amber-50' : 'border-gray-200 bg-white'}`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <TypeBadge taskType={item.task_type} />
        <span className="text-xs text-gray-400">{item.timestamp}</span>
      </div>

      {/* User transcript */}
      <p className="text-sm text-gray-500 mb-1">
        <span className="font-medium text-gray-600">You: </span>
        {item.transcript}
      </p>

      {/* ARIA response */}
      <p className={`text-sm ${isBlocked ? 'text-amber-800' : 'text-gray-800'}`}>
        <span className="font-medium">ARIA: </span>
        {item.skill_output}
      </p>

      {/* Approval card */}
      {isBlocked && (
        <div className="mt-3 rounded bg-amber-100 border border-amber-300 p-3 text-xs text-amber-900">
          <span className="font-semibold">Approval required — </span>
          {item.approval_message || 'Open the ARIA dashboard to review and approve this action.'}
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function ARIAVoice() {
  const [micState,  setMicState]  = useState(MIC_IDLE);
  const [transcript, setTranscript] = useState('');
  const [history,   setHistory]   = useState([]);
  const [error,     setError]     = useState(null);
  const [supported, setSupported] = useState(true);

  const recognitionRef  = useRef(null);
  const synthRef        = useRef(window.speechSynthesis);
  const transcriptRef   = useRef('');

  // Check browser support once
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setSupported(false);
    }
  }, []);

  const speak = useCallback((text) => {
    if (!synthRef.current) return;
    synthRef.current.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate  = 1.0;
    utter.pitch = 1.0;
    utter.onstart = () => setMicState(MIC_SPEAKING);
    utter.onend   = () => setMicState(MIC_IDLE);
    synthRef.current.speak(utter);
  }, []);

  const callVoiceApi = useCallback(async (text) => {
    setMicState(MIC_THINKING);
    setError(null);
    try {
      const res = await fetch(VOICE_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: text }),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();

      const item = {
        id:               data.task_id,
        task_type:        data.task_type,
        transcript:       text,
        skill_output:     data.skill_output,
        approval_required: data.approval_required,
        approval_message: data.approval_message,
        timestamp:        new Date().toLocaleTimeString(),
      };
      setHistory(prev => [item, ...prev]);
      speak(data.skill_output);
    } catch (err) {
      const msg = `Could not reach ARIA. Is the voice API running on port 8001? (${err.message})`;
      setError(msg);
      setMicState(MIC_IDLE);
    }
  }, [speak]);

  const startListening = useCallback(() => {
    if (micState !== MIC_IDLE) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognitionRef.current = recognition;
    recognition.lang           = 'en-IN';
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart  = () => setMicState(MIC_LISTEN);
    recognition.onresult = (e) => {
      const interim = Array.from(e.results)
        .map(r => r[0].transcript)
        .join('');
      transcriptRef.current = interim;
      setTranscript(interim);
    };
    recognition.onend = () => {
      const final = transcriptRef.current || '';
      if (final.trim()) {
        callVoiceApi(final.trim());
      } else {
        setMicState(MIC_IDLE);
      }
    };
    recognition.onerror = (e) => {
      setError(`Speech recognition error: ${e.error}`);
      setMicState(MIC_IDLE);
    };

    transcriptRef.current = '';
    setTranscript('');
    recognition.start();
  }, [micState, transcript, callVoiceApi]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  }, []);

  const cancelSpeech = useCallback(() => {
    if (synthRef.current) {
      synthRef.current.cancel();
      setMicState(MIC_IDLE);
    }
  }, []);

  // ── Render ──────────────────────────────────────────────────────────────────
  if (!supported) {
    return (
      <div className="flex items-center justify-center h-full p-8 text-center">
        <div className="max-w-sm">
          <p className="text-lg font-semibold text-gray-700 mb-2">Browser not supported</p>
          <p className="text-sm text-gray-500">
            Web Speech API requires Chrome or Edge. Safari has partial support.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full max-w-2xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-bold text-gray-900">ARIA Voice</h1>
        <p className="text-sm text-gray-500 mt-1">
          Speak to ARIA — read-only skills only. Approvals still required for real actions.
        </p>
      </div>

      {/* Governance notice */}
      <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-xs text-blue-800">
        <span className="font-semibold">Governance active: </span>
        KPI, PR review, CI/CD, QA and test analysis run immediately.
        Jira ticket creation and PR comment posting require your approval in the dashboard.
      </div>

      {/* Mic + live transcript */}
      <div className="flex flex-col items-center gap-4 py-6">
        <button
          onMouseDown={startListening}
          onMouseUp={stopListening}
          onTouchStart={startListening}
          onTouchEnd={stopListening}
          disabled={micState === MIC_THINKING}
          className={`w-24 h-24 rounded-full text-white text-3xl font-bold shadow-lg transition-all ${MIC_COLORS[micState]}`}
          title={MIC_LABELS[micState]}
          aria-label={MIC_LABELS[micState]}
        >
          {micState === MIC_LISTEN ? '⏹' : micState === MIC_SPEAKING ? '🔊' : '🎙'}
        </button>

        <p className="text-sm font-medium text-gray-500">{MIC_LABELS[micState]}</p>

        {transcript && (
          <div className="w-full rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-3">
            <p className="text-sm text-gray-600 italic">"{transcript}"</p>
          </div>
        )}

        {micState === MIC_SPEAKING && (
          <button
            onClick={cancelSpeech}
            className="text-xs text-gray-400 underline hover:text-gray-600"
          >
            Stop speaking
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {/* Conversation history */}
      {history.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-600">Recent exchanges</h2>
            <button
              onClick={() => setHistory([])}
              className="text-xs text-gray-400 hover:text-gray-600 underline"
            >
              Clear
            </button>
          </div>
          {history.map(item => (
            <HistoryItem key={item.id} item={item} />
          ))}
        </div>
      )}

      {history.length === 0 && micState === MIC_IDLE && !error && (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-sm text-gray-400 text-center">
            Hold the button and ask ARIA something.<br />
            Try: "What's causing the CTR drop on the news feed?"
          </p>
        </div>
      )}
    </div>
  );
}
