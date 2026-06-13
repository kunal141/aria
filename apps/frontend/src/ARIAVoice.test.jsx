/**
 * ARIAVoice — voice transcript stale-closure tests
 *
 * Item 8 of the Week 28 Stabilization Checklist.
 *
 * The bug being tested: ARIAVoice.jsx used to read the `transcript` React
 * state inside the `onend` closure, which could be stale because React state
 * updates are asynchronous. The fix stores the current transcript in a ref
 * (`transcriptRef`) which is always up-to-date.
 *
 * We stub out SpeechRecognition via a fake class that exposes
 * `triggerResult()` and `triggerEnd()` helpers so tests can drive the
 * recognition lifecycle synchronously.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ARIAVoice from './ARIAVoice';

// ── Fake SpeechRecognition ──────────────────────────────────────────────────

function makeFakeSpeechRecognition() {
  let instance = null;

  class FakeSpeechRecognition {
    constructor() {
      this.lang = '';
      this.interimResults = true;
      this.maxAlternatives = 1;
      this.onstart = null;
      this.onresult = null;
      this.onend = null;
      this.onerror = null;
      instance = this;
    }
    start() {
      if (this.onstart) this.onstart();
    }
    stop() {
      // Stopping fires onend
      if (this.onend) this.onend();
    }
    triggerResult(transcript) {
      if (this.onresult) {
        this.onresult({
          results: [
            Object.assign([{ transcript }], { isFinal: true }),
          ],
        });
      }
    }
    triggerEnd() {
      if (this.onend) this.onend();
    }
  }

  return { FakeSpeechRecognition, getInstance: () => instance };
}

// ── Setup ───────────────────────────────────────────────────────────────────

let fetchMock;
let recognition;
let FakeSpeechRecognition;

beforeEach(() => {
  const fake = makeFakeSpeechRecognition();
  FakeSpeechRecognition = fake.FakeSpeechRecognition;
  recognition = fake;

  window.SpeechRecognition = FakeSpeechRecognition;
  window.webkitSpeechRecognition = FakeSpeechRecognition;
  window.speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn(),
  };

  fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      task_id: 'test-id',
      task_type: 'general',
      skill_output: 'Hello from ARIA',
      approval_required: false,
    }),
  });
  global.fetch = fetchMock;
});

afterEach(() => {
  vi.restoreAllMocks();
  delete window.SpeechRecognition;
  delete window.webkitSpeechRecognition;
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe('ARIAVoice transcript fix', () => {
  it('submits the current finalized transcript', async () => {
    render(<ARIAVoice />);

    // Start listening
    const micBtn = screen.getByRole('button', { name: /hold to speak/i });
    fireEvent.mouseDown(micBtn);

    const recog = recognition.getInstance();
    expect(recog).not.toBeNull();

    // Simulate speech recognition result
    recog.triggerResult('what is the CTR drop today');
    // Stop listening — should fire onend which reads the ref, not stale state
    fireEvent.mouseUp(micBtn);

    // Wait for fetch to be called with the exact transcript
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.transcript).toBe('what is the CTR drop today');
  });

  it('submits consecutive transcripts without stale state', async () => {
    render(<ARIAVoice />);
    const micBtn = screen.getByRole('button', { name: /hold to speak/i });

    // ── First utterance ──────────────────────────────────────────────────────
    fireEvent.mouseDown(micBtn);
    const recog = recognition.getInstance();
    recog.triggerResult('first utterance');
    fireEvent.mouseUp(micBtn);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const firstBody = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(firstBody.transcript).toBe('first utterance');

    // ── Second utterance — must not reuse first transcript ───────────────────
    // Wait for ARIA to go back to idle (speech synthesis ends)
    window.speechSynthesis.speak.mock.calls[0]?.[0]?.onend?.();

    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        task_id: 'test-id-2',
        task_type: 'general',
        skill_output: 'Second reply',
        approval_required: false,
      }),
    });

    fireEvent.mouseDown(micBtn);
    const recog2 = recognition.getInstance();
    recog2.triggerResult('second utterance');
    fireEvent.mouseUp(micBtn);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(secondBody.transcript).toBe('second utterance');
    expect(secondBody.transcript).not.toBe('first utterance');
  });
});
