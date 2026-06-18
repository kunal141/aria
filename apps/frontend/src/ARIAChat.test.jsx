/**
 * ARIAChat tests — Week 33 V2 web chat.
 *
 * Covers: render, session start, message send, streamed token/event rendering,
 * memory-proposal card + approve calling the decision endpoint, citation render,
 * safe error render, and the local-only pilot warning.
 *
 * Streaming is mocked with a fetch that returns a ReadableStream-like body whose
 * getReader() yields NDJSON bytes — exactly what the component consumes via
 * fetch() + ReadableStream.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ARIAChat from './ARIAChat';

const SESSION = { session_id: 'sess-1', owner: 'human:local', scope: 'analytics.events', created_at: '2026-06-17T00:00:00+00:00' };

function ndjsonBody(lines) {
  const text = lines.map((l) => JSON.stringify(l)).join('\n') + '\n';
  const chunks = [new TextEncoder().encode(text)];
  let i = 0;
  return {
    getReader: () => ({
      read: () =>
        i < chunks.length
          ? Promise.resolve({ done: false, value: chunks[i++] })
          : Promise.resolve({ done: true, value: undefined }),
    }),
  };
}

function jsonResp(body, ok = true, status = 200) {
  return Promise.resolve({ ok, status, text: async () => JSON.stringify(body) });
}

function streamResp(lines) {
  return Promise.resolve({ ok: true, status: 200, body: ndjsonBody(lines) });
}

// A routing fetch mock. `streamLines` is the NDJSON event sequence for /messages.
function routedFetch({ streamLines = [], decision = { decision: 'approve', memory_id: 'mem-1', memory_version: 1 } } = {}) {
  return vi.fn((url) => {
    if (url === '/api/v2/chat/sessions') return jsonResp(SESSION);
    if (String(url).includes('/messages')) return streamResp(streamLines);
    if (String(url).includes('/decision')) return jsonResp(decision);
    return jsonResp({}, false, 404);
  });
}

const PROPOSE_STREAM = [
  { event: 'message.started', data: { session_id: 'sess-1' } },
  { event: 'memory.proposed', data: { proposal_id: 'prop-1', scope: 'analytics.events', structured_value: { table: 'story_events', field: 'event_type', mapping: { 1: 'page_view' } } } },
  { event: 'approval.required', data: { proposal_id: 'prop-1', kind: 'memory' } },
  { event: 'workspace.updated', data: { workspace_id: 'ws-1' } },
  { event: 'token', data: { text: 'Proposed ' } },
  { event: 'token', data: { text: 'memory.' } },
  { event: 'message.completed', data: { decision: 'propose_memory', response: 'Proposed memory.', citation: null, proposal_id: 'prop-1' } },
];

const RECALL_STREAM = [
  { event: 'message.started', data: { session_id: 'sess-1' } },
  { event: 'memory.recalled', data: { memory_id: 'mem-1', version: 1, retrieval_reason: 'matched table=story_events field=event_type' } },
  { event: 'token', data: { text: 'event_type ' } },
  { event: 'token', data: { text: 'means…' } },
  { event: 'message.completed', data: { decision: 'converse', response: 'event_type means…', citation: { memory_id: 'mem-1', version: 1, retrieval_reason: 'matched table=story_events field=event_type' } } },
];

const ERROR_STREAM = [
  { event: 'message.started', data: { session_id: 'sess-1' } },
  { event: 'error', data: { error_type: 'RuntimeError', detail: 'redacted' } },
];

const PILOT_STREAM = [
  { event: 'message.started', data: { session_id: 'sess-1' } },
  { event: 'workflow.started', data: { task_type: 'pr_review' } },
  { event: 'workflow.completed', data: { task_type: 'pr_review' } },
  { event: 'pilot.report', data: {
      pilot: 'pr_review', title: 'PR Review Report', summary: 'PR PR-481: 4 files, 3 risky.',
      connector_mode: 'fixtures', evidence_references: ['fixture:pr:PR-481'],
      memory_citations: [], boundary: 'Read-only PR review. Draft-only, nothing posted.',
      workspace_id: 'ws-1',
  } },
  { event: 'draft.created', data: { draft_id: 'd1', kind: 'pr_comment', title: 'Review: ranker.py', boundary: 'Draft only. Not posted. No external write executed.' } },
  { event: 'workspace.updated', data: { workspace_id: 'ws-1' } },
  { event: 'token', data: { text: 'PR ' } },
  { event: 'token', data: { text: 'report.' } },
  { event: 'message.completed', data: { decision: 'run_workflow', response: 'PR report.', citation: null } },
];

beforeEach(() => { vi.stubGlobal('fetch', vi.fn()); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function renderAndStart(fetchMock) {
  vi.stubGlobal('fetch', fetchMock);
  render(<ARIAChat />);
  await waitFor(() => expect(screen.getByTestId('session-id')).toHaveTextContent('sess-1'));
}

describe('ARIAChat — render + session', () => {
  it('renders the local-only pilot warning', async () => {
    await renderAndStart(routedFetch());
    expect(screen.getByTestId('pilot-warning')).toHaveTextContent('External writes are blocked');
    expect(screen.getByTestId('pilot-warning')).toHaveTextContent('record decisions only');
  });

  it('starts a session on mount', async () => {
    const fetchMock = routedFetch();
    await renderAndStart(fetchMock);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v2/chat/sessions');
    expect(screen.getByTestId('ariachat-root')).toBeInTheDocument();
  });
});

describe('ARIAChat — messaging + streaming', () => {
  it('sends a message and renders streamed tokens', async () => {
    const user = userEvent.setup();
    await renderAndStart(routedFetch({ streamLines: RECALL_STREAM }));

    await user.type(screen.getByTestId('chat-input'), 'What does event_type mean in story_events?');
    await user.click(screen.getByTestId('send-button'));

    // The user message renders, and the streamed assistant text appears.
    await waitFor(() => expect(screen.getByTestId('msg-user-text')).toHaveTextContent('event_type mean'));
    await waitFor(() => expect(screen.getByTestId('msg-aria-text')).toHaveTextContent('event_type means'));
  });

  it('renders a memory proposal card and Approve calls the decision endpoint', async () => {
    const user = userEvent.setup();
    const fetchMock = routedFetch({ streamLines: PROPOSE_STREAM });
    await renderAndStart(fetchMock);

    await user.type(screen.getByTestId('chat-input'), 'In story_events table, event_type = 1 means page_view');
    await user.click(screen.getByTestId('send-button'));

    await waitFor(() => expect(screen.getByTestId('proposal-card')).toBeInTheDocument());
    expect(screen.getByTestId('proposal-value')).toHaveTextContent('story_events');

    await user.click(screen.getByTestId('approve-button'));
    await waitFor(() => {
      const decisionCall = fetchMock.mock.calls.find((c) => String(c[0]).includes('/decision'));
      expect(decisionCall).toBeTruthy();
      expect(decisionCall[0]).toBe('/api/v2/memory/proposals/prop-1/decision');
    });
    await waitFor(() => expect(screen.getByTestId('proposal-status')).toHaveTextContent('approved'));
  });

  it('renders a memory citation when recalled', async () => {
    const user = userEvent.setup();
    await renderAndStart(routedFetch({ streamLines: RECALL_STREAM }));

    await user.type(screen.getByTestId('chat-input'), 'What does event_type mean in story_events?');
    await user.click(screen.getByTestId('send-button'));

    await waitFor(() => expect(screen.getByTestId('citation')).toBeInTheDocument());
    expect(screen.getByTestId('citation')).toHaveTextContent('mem-1');
    expect(screen.getByTestId('citation')).toHaveTextContent('v1');
  });

  it('shows a safe (redacted) error on an error event', async () => {
    const user = userEvent.setup();
    await renderAndStart(routedFetch({ streamLines: ERROR_STREAM }));

    await user.type(screen.getByTestId('chat-input'), 'trigger');
    await user.click(screen.getByTestId('send-button'));

    await waitFor(() => expect(screen.getByTestId('chat-error')).toBeInTheDocument());
    expect(screen.getByTestId('chat-error')).toHaveTextContent('RuntimeError');
    expect(screen.getByTestId('chat-error')).toHaveTextContent('redacted');
  });

  it('renders a pilot report with evidence, boundary, and draft chips', async () => {
    const user = userEvent.setup();
    await renderAndStart(routedFetch({ streamLines: PILOT_STREAM }));

    await user.type(screen.getByTestId('chat-input'), 'Review this PR');
    await user.click(screen.getByTestId('send-button'));

    await waitFor(() => expect(screen.getByTestId('pilot-report')).toBeInTheDocument());
    expect(screen.getByTestId('pilot-report')).toHaveTextContent('PR Review Report');
    expect(screen.getByTestId('pilot-evidence')).toHaveTextContent('fixture:pr:PR-481');
    expect(screen.getByTestId('pilot-boundary')).toHaveTextContent('Draft-only');
    expect(screen.getByTestId('draft-chip')).toHaveTextContent('Not posted');
    expect(screen.getByTestId('workspace-id')).toHaveTextContent('ws-1');
  });
});
