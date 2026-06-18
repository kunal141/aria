/**
 * ARIAChat — minimal V2 web chat (Week 33).
 *
 * Local V2 pilot UI: create a session, send messages, consume the streamed
 * response via fetch() + ReadableStream (NOT EventSource), render streamed
 * tokens/events, show memory-proposal cards with approve/reject, show memory
 * citations, show approval-required cards, show the workspace id, and surface
 * safe (redacted) errors.
 *
 * Boundary: external writes are blocked; approvals record decisions only. The UI
 * never shows raw chain-of-thought or raw exception text, and never hardcodes a
 * personal identity (the actor lives server-side via ARIA_USER_ID).
 */
import React, { useEffect, useRef, useState } from 'react';

const PILOT_WARNING =
  'Local V2 pilot. External writes are blocked. Approvals record decisions only; ' +
  'they do not post, send, or create anything in external systems.';

async function postJson(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try { data = JSON.parse(await res.text()); } catch { data = null; }
  return { ok: res.ok, status: res.status, data };
}

export default function ARIAChat() {
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]); // {role, text, citation?, proposal?, workspaceId?}
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [workspaceId, setWorkspaceId] = useState(null);
  const [proposals, setProposals] = useState({}); // proposal_id -> {scope, structured_value, status}
  const startedRef = useRef(false);

  async function startSession() {
    setError(null);
    const { ok, data } = await postJson('/api/v2/chat/sessions', { scope: 'analytics.events' });
    if (!ok || !data || !data.session_id) {
      setError('session_error');
      return;
    }
    setSessionId(data.session_id);
    setMessages([]);
    setProposals({});
    setWorkspaceId(null);
  }

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    startSession();
  }, []);

  function handleEvent(ev, assistantIndex) {
    const { event, data } = ev;
    if (event === 'token') {
      setMessages((prev) => {
        const next = [...prev];
        if (next[assistantIndex]) next[assistantIndex] = {
          ...next[assistantIndex], text: (next[assistantIndex].text || '') + (data.text || ''),
        };
        return next;
      });
    } else if (event === 'memory.proposed') {
      setProposals((prev) => ({
        ...prev,
        [data.proposal_id]: { scope: data.scope, structured_value: data.structured_value, status: 'pending' },
      }));
      setMessages((prev) => {
        const next = [...prev];
        if (next[assistantIndex]) next[assistantIndex] = { ...next[assistantIndex], proposalId: data.proposal_id };
        return next;
      });
    } else if (event === 'memory.recalled') {
      setMessages((prev) => {
        const next = [...prev];
        if (next[assistantIndex]) next[assistantIndex] = { ...next[assistantIndex], citation: data };
        return next;
      });
    } else if (event === 'pilot.report') {
      setMessages((prev) => {
        const next = [...prev];
        if (next[assistantIndex]) next[assistantIndex] = { ...next[assistantIndex], pilot: data, drafts: [] };
        return next;
      });
    } else if (event === 'draft.created') {
      setMessages((prev) => {
        const next = [...prev];
        if (next[assistantIndex]) {
          const drafts = [...(next[assistantIndex].drafts || []), data];
          next[assistantIndex] = { ...next[assistantIndex], drafts };
        }
        return next;
      });
    } else if (event === 'workspace.updated') {
      setWorkspaceId(data.workspace_id);
    } else if (event === 'message.completed') {
      setMessages((prev) => {
        const next = [...prev];
        if (next[assistantIndex]) {
          next[assistantIndex] = {
            ...next[assistantIndex],
            text: data.response || next[assistantIndex].text,
            citation: data.citation || next[assistantIndex].citation,
            decision: data.decision,
          };
        }
        return next;
      });
    } else if (event === 'error') {
      setError(`${data.error_type || 'error'} (details redacted)`);
    }
    // workflow.started/completed, artifact.created, approval.required are
    // informational; the proposal card + citation already cover the UI needs.
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || !sessionId || busy) return;
    setError(null);
    setBusy(true);
    setInput('');
    let assistantIndex = -1;
    setMessages((prev) => {
      const next = [...prev, { role: 'user', text }, { role: 'aria', text: '' }];
      assistantIndex = next.length - 1;
      return next;
    });

    try {
      const res = await fetch(`/api/v2/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok || !res.body) {
        setError('stream_error');
        setBusy(false);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 1);
          if (!line) continue;
          try { handleEvent(JSON.parse(line), assistantIndex); } catch { /* skip bad line */ }
        }
      }
    } catch {
      setError('network_error');
    } finally {
      setBusy(false);
    }
  }

  async function decide(proposalId, decision) {
    const { ok, data } = await postJson(
      `/api/v2/memory/proposals/${proposalId}/decision`,
      { decision, session_id: sessionId },
    );
    setProposals((prev) => ({
      ...prev,
      [proposalId]: {
        ...prev[proposalId],
        status: ok ? decision + 'd' : (data && data.error_code) || 'error',
      },
    }));
  }

  return (
    <div data-testid="ariachat-root" className="min-h-screen bg-gray-50 p-6 pb-32 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold text-gray-800 mb-2">ARIA Chat — V2 pilot</h1>
      <div data-testid="pilot-warning" className="mb-4 rounded-lg bg-amber-50 border border-amber-300 text-amber-800 text-sm px-4 py-2">
        {PILOT_WARNING}
      </div>

      <div className="mb-3 text-xs text-gray-500 flex gap-4">
        <span data-testid="session-id">Session: {sessionId || '(starting…)'}</span>
        {workspaceId && <span data-testid="workspace-id">Workspace: {workspaceId}</span>}
        <button data-testid="new-session" onClick={startSession} className="text-violet-600 hover:underline">
          New session
        </button>
      </div>

      {error && (
        <div data-testid="chat-error" className="mb-3 rounded bg-red-50 border border-red-300 text-red-700 text-sm px-3 py-2">
          {error}
        </div>
      )}

      <div data-testid="conversation" className="space-y-3 mb-4">
        {messages.map((m, i) => (
          <div key={i} data-testid={m.role === 'user' ? 'msg-user' : 'msg-aria'}
               className={`rounded-lg px-3 py-2 text-sm ${m.role === 'user' ? 'bg-violet-50 text-gray-800' : 'bg-white border border-gray-200 text-gray-700'}`}>
            <div className="font-medium text-xs text-gray-400 mb-1">{m.role === 'user' ? 'You' : 'ARIA'}</div>
            <div data-testid={m.role === 'user' ? 'msg-user-text' : 'msg-aria-text'} className="whitespace-pre-wrap">{m.text}</div>

            {m.proposalId && proposals[m.proposalId] && (
              <div data-testid="proposal-card" className="mt-2 rounded border border-blue-200 bg-blue-50 px-3 py-2">
                <div className="text-xs font-semibold text-blue-800">Proposed memory (needs your approval)</div>
                <div className="text-xs text-blue-700">Scope: {proposals[m.proposalId].scope}</div>
                <pre data-testid="proposal-value" className="text-xs text-blue-700 overflow-x-auto">
                  {JSON.stringify(proposals[m.proposalId].structured_value)}
                </pre>
                <div data-testid="proposal-status" className="text-xs text-gray-500">status: {proposals[m.proposalId].status}</div>
                {proposals[m.proposalId].status === 'pending' && (
                  <div className="flex gap-2 mt-1">
                    <button data-testid="approve-button" onClick={() => decide(m.proposalId, 'approve')}
                            className="px-2 py-1 text-xs rounded bg-green-600 text-white">Approve</button>
                    <button data-testid="reject-button" onClick={() => decide(m.proposalId, 'reject')}
                            className="px-2 py-1 text-xs rounded bg-gray-300 text-gray-700">Reject</button>
                  </div>
                )}
              </div>
            )}

            {m.citation && (
              <div data-testid="citation" className="mt-2 text-xs text-gray-500 border-l-2 border-gray-300 pl-2">
                memory {m.citation.memory_id} v{m.citation.version} — {m.citation.retrieval_reason}
              </div>
            )}

            {m.pilot && (
              <div data-testid="pilot-report" className="mt-2 rounded border border-emerald-200 bg-emerald-50 px-3 py-2">
                <div className="text-xs font-semibold text-emerald-800">
                  {m.pilot.title} ({m.pilot.pilot}) · mode: {m.pilot.connector_mode}
                </div>
                <div className="text-xs text-emerald-700">{m.pilot.summary}</div>
                {m.pilot.evidence_references && m.pilot.evidence_references.length > 0 && (
                  <div data-testid="pilot-evidence" className="text-xs text-emerald-700 mt-1">
                    Evidence: {m.pilot.evidence_references.join(', ')}
                  </div>
                )}
                <div data-testid="pilot-boundary" className="text-xs text-gray-500 mt-1">{m.pilot.boundary}</div>
                {(m.drafts || []).map((d) => (
                  <div key={d.draft_id} data-testid="draft-chip" className="text-xs text-amber-800 mt-1">
                    [{d.kind}] {d.title} — {d.boundary}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') sendMessage(); }}
          placeholder="Tell ARIA a domain fact, ask what a term means, or ask for a workflow…"
          className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm"
        />
        <button data-testid="send-button" onClick={sendMessage} disabled={busy || !sessionId}
                className="px-4 py-2 rounded bg-violet-600 text-white text-sm disabled:opacity-50">
          {busy ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  );
}
