/**
 * ROIDashboard tests — Week 29 Priority 2
 *
 * Covers every Definition-of-Done frontend scenario:
 *   - all 11 panels render from a mocked API response
 *   - loading state
 *   - error state (API error code + detail surfaced)
 *   - empty state (banner + zero-safe panels)
 *   - null / no-data values render as "No data" (not 0)
 *   - Decimal cost strings render as-is, never parsed to float
 *   - filters update API requests (query string includes filters)
 *   - malformed-record warning banner appears when count > 0
 *   - no hardcoded dashboard values (snapshot of source-string check)
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ROIDashboard from './ROIDashboard';

function makePayload(overrides = {}) {
  return {
    api_version: 'v1',
    filters_applied: {
      start_date: null, end_date: null,
      skill: null, actor_type: null, workflow_id: null,
    },
    execution: { total_tasks_completed: 12, tasks_by_skill: { pr_review: 8, kpi: 4 } },
    approval:  {
      approval_rate: 0.75, approvals_granted: 6, approvals_rejected: 2,
      approval_rate_by_skill: { pr_review: 0.75, kpi: null },
    },
    failure:   {
      failure_rate: 0.1, failed_tasks: 1, terminal_tasks: 10,
      failure_rate_by_skill: { pr_review: 0.0, kpi: 0.25 },
    },
    resolution: { avg_time_to_resolution_ms: 11500.0 },
    cost: { estimated_cost_total: '1.2345', estimated_cost_per_task: '0.6172', tasks_with_cost: 2 },
    human_intervention: { rate: 0.5 },
    artifacts:   { count: 3 },
    corrections: { count: 1 },
    models: { usage_breakdown: { 'claude-opus-4-7@2026-05': 4, 'phi-3-mini': 2 } },
    sources: {
      v2_event_count: 30, legacy_task_count: 5,
      legacy_evolution_count: 2, malformed_count: 0,
    },
    ...overrides,
  };
}

function _jsonHeaders() {
  return {
    get: (name) => name.toLowerCase() === 'content-type'
      ? 'application/json' : null,
  };
}

function _htmlHeaders() {
  return {
    get: (name) => name.toLowerCase() === 'content-type'
      ? 'text/html; charset=utf-8' : null,
  };
}

function mockOk(body) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: _jsonHeaders(),
    text: async () => JSON.stringify(body),
  });
}

function mockError(status, body) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    headers: _jsonHeaders(),
    text: async () => JSON.stringify(body),
  });
}

function mockHtml(status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    headers: _htmlHeaders(),
    text: async () => '<!doctype html><html><body>vite</body></html>',
  });
}

function mockInvalidJson() {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: _jsonHeaders(),
    text: async () => 'this is not json',
  });
}

function mockBadSchema(body) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: _jsonHeaders(),
    text: async () => JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ── Section A — Panels render from a mocked response ────────────────────────

describe('ROIDashboard — happy path', () => {
  it('renders all 11 panels from the mocked API response', async () => {
    vi.stubGlobal('fetch', mockOk(makePayload()));
    render(<ROIDashboard />);

    // 1. Execution coverage
    await waitFor(() => {
      expect(screen.getByTestId('panel-execution')).toBeInTheDocument();
    });
    expect(screen.getByTestId('execution-total')).toHaveTextContent('12');

    // 2. Tasks by skill
    const skillList = screen.getByTestId('tasks-by-skill-list');
    expect(skillList).toHaveTextContent('pr_review');
    expect(skillList).toHaveTextContent('kpi');

    // 3. Approval friction
    expect(screen.getByTestId('panel-approval')).toBeInTheDocument();
    expect(screen.getByTestId('approval-rate')).toHaveTextContent('75.0%');
    expect(screen.getByTestId('approval-rate')).toHaveTextContent('granted 6');
    expect(screen.getByTestId('approval-rate')).toHaveTextContent('rejected 2');
    // Skill with null rate renders as "No data"
    expect(screen.getByTestId('approval-rate-by-skill')).toHaveTextContent('No data');

    // 4. Failure containment
    expect(screen.getByTestId('failure-rate')).toHaveTextContent('10.0%');
    expect(screen.getByTestId('failure-rate-by-skill')).toBeInTheDocument();

    // 5. Avg time to resolution
    expect(screen.getByTestId('avg-resolution')).toHaveTextContent('11.5 s');

    // 6. Cost per task — Decimal STRINGS displayed verbatim
    expect(screen.getByTestId('cost-per-task')).toHaveTextContent('$0.6172');
    expect(screen.getByTestId('cost-per-task')).toHaveTextContent('$1.2345');

    // 7. Human intervention rate
    expect(screen.getByTestId('human-rate')).toHaveTextContent('50.0%');

    // 8. Artifact throughput
    expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');

    // 9. Correction learning signal
    expect(screen.getByTestId('correction-count')).toHaveTextContent('1');

    // 10. Model usage mix
    const modelList = screen.getByTestId('model-usage-list');
    expect(modelList).toHaveTextContent('claude-opus-4-7@2026-05');
    expect(modelList).toHaveTextContent('phi-3-mini');

    // 11. Legacy vs v2 source split
    expect(screen.getByTestId('source-v2')).toHaveTextContent('30');
    expect(screen.getByTestId('source-legacy-task')).toHaveTextContent('5');
    expect(screen.getByTestId('source-legacy-evolution')).toHaveTextContent('2');
    expect(screen.getByTestId('source-malformed')).toHaveTextContent('0');
  });

  it('renders Decimal cost strings verbatim (no float parsing)', async () => {
    const payload = makePayload({
      cost: { estimated_cost_total: '0.123456789012345678',
              estimated_cost_per_task: '0.061728394506172839',
              tasks_with_cost: 2 },
    });
    vi.stubGlobal('fetch', mockOk(payload));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('cost-per-task'))
        .toHaveTextContent('0.061728394506172839');
    });
    expect(screen.getByTestId('cost-per-task'))
      .toHaveTextContent('0.123456789012345678');
  });
});

// ── Section B — Loading / error / empty states ──────────────────────────────

describe('ROIDashboard — states', () => {
  it('shows the loading state while the fetch is in flight', () => {
    // Use a fetch that never resolves so loading state stays visible.
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    render(<ROIDashboard />);
    expect(screen.getByTestId('loading-state')).toBeInTheDocument();
  });

  it('shows the API error banner with error_code + detail', async () => {
    vi.stubGlobal('fetch', mockError(503, {
      error_code: 'filesystem_error',
      detail: 'Permission denied reading ledger: …',
    }));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state')).toHaveTextContent('filesystem_error');
    expect(screen.getByTestId('error-state')).toHaveTextContent('HTTP 503');
  });

  it('shows the network-error path when fetch throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('boom')));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state')).toHaveTextContent('network_error');
  });

  it('shows the empty banner when all source counts are zero', async () => {
    const empty = makePayload({
      execution: { total_tasks_completed: 0, tasks_by_skill: {} },
      approval:  { approval_rate: null, approvals_granted: 0,
                    approvals_rejected: 0, approval_rate_by_skill: {} },
      failure:   { failure_rate: null, failed_tasks: 0, terminal_tasks: 0,
                    failure_rate_by_skill: {} },
      resolution: { avg_time_to_resolution_ms: null },
      cost: { estimated_cost_total: '0', estimated_cost_per_task: null, tasks_with_cost: 0 },
      human_intervention: { rate: null },
      artifacts: { count: 0 }, corrections: { count: 0 },
      models: { usage_breakdown: {} },
      sources: { v2_event_count: 0, legacy_task_count: 0,
                  legacy_evolution_count: 0, malformed_count: 0 },
    });
    vi.stubGlobal('fetch', mockOk(empty));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('empty-banner')).toBeInTheDocument();
    });
  });

  it('renders null rate/cost/duration values as "No data" not zero', async () => {
    const partial = makePayload({
      approval: { approval_rate: null, approvals_granted: 0,
                   approvals_rejected: 0, approval_rate_by_skill: {} },
      failure:  { failure_rate: null, failed_tasks: 0, terminal_tasks: 0,
                   failure_rate_by_skill: {} },
      resolution: { avg_time_to_resolution_ms: null },
      cost: { estimated_cost_total: '0', estimated_cost_per_task: null, tasks_with_cost: 0 },
      human_intervention: { rate: null },
    });
    vi.stubGlobal('fetch', mockOk(partial));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('approval-rate')).toHaveTextContent('No data');
    });
    expect(screen.getByTestId('failure-rate')).toHaveTextContent('No data');
    expect(screen.getByTestId('avg-resolution')).toHaveTextContent('No data');
    expect(screen.getByTestId('cost-per-task')).toHaveTextContent('No data');
    expect(screen.getByTestId('human-rate')).toHaveTextContent('No data');
    // CRUCIAL: not "0%" anywhere.
    expect(screen.getByTestId('approval-rate')).not.toHaveTextContent('0.0%');
  });

  it('shows the malformed-record warning when sources.malformed_count > 0', async () => {
    const withMal = makePayload({
      sources: { v2_event_count: 5, legacy_task_count: 0,
                  legacy_evolution_count: 0, malformed_count: 3 },
    });
    vi.stubGlobal('fetch', mockOk(withMal));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('malformed-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('malformed-banner')).toHaveTextContent('3');
  });
});

// ── Section C — Filters update API requests ────────────────────────────────

describe('ROIDashboard — filters', () => {
  it('typed filters appear in the query string on Apply', async () => {
    const user = userEvent.setup();
    const fetchMock = mockOk(makePayload());
    vi.stubGlobal('fetch', fetchMock);
    render(<ROIDashboard />);

    // First call: unfiltered
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/ledger/metrics');

    await user.type(screen.getByTestId('filter-skill'), 'pr_review');
    await user.selectOptions(screen.getByTestId('filter-actor-type'), 'human');
    await user.type(screen.getByTestId('filter-workflow-id'), 'wf-9');
    await user.type(screen.getByTestId('filter-start-date'),
                     '2026-06-11T00:00:00+00:00');
    await user.click(screen.getByTestId('filter-apply'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const lastUrl = fetchMock.mock.calls[1][0];
    expect(lastUrl).toContain('skill=pr_review');
    expect(lastUrl).toContain('actor_type=human');
    expect(lastUrl).toContain('workflow_id=wf-9');
    expect(lastUrl).toContain('start_date=');
  });

  it('shows the filtered banner when filters_applied has any value', async () => {
    vi.stubGlobal('fetch', mockOk(makePayload({
      filters_applied: { start_date: null, end_date: null,
                          skill: 'pr_review',
                          actor_type: null, workflow_id: null },
    })));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('filtered-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('filtered-banner')).toHaveTextContent('skill=pr_review');
  });

  it('Reset clears filters and re-fetches with no params', async () => {
    const user = userEvent.setup();
    const fetchMock = mockOk(makePayload());
    vi.stubGlobal('fetch', fetchMock);
    render(<ROIDashboard />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await user.type(screen.getByTestId('filter-skill'), 'pr_review');
    await user.click(screen.getByTestId('filter-apply'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    await user.click(screen.getByTestId('filter-reset'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const resetUrl = fetchMock.mock.calls[2][0];
    expect(resetUrl).toBe('/api/v1/ledger/metrics');
  });
});

// ── Section CC — Round-2 fixes: schema / content-type validation ────────────

describe('ROIDashboard — defensive response validation', () => {
  it('treats text/html (Vite index.html) as an error, not empty success', async () => {
    // This reproduces the Round-1 finding: relative /api/* targeting
    // Vite returns index.html with HTTP 200. Without validation the
    // dashboard previously rendered it as an empty ledger.
    vi.stubGlobal('fetch', mockHtml(200));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('invalid_content_type');
    // CRUCIAL: empty-banner MUST NOT be present (would indicate the
    // false-success state we are protecting against).
    expect(screen.queryByTestId('empty-banner')).not.toBeInTheDocument();
  });

  it('treats invalid JSON in an application/json response as an error', async () => {
    vi.stubGlobal('fetch', mockInvalidJson());
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state')).toHaveTextContent('invalid_json');
  });

  it('rejects a JSON response missing api_version="v1"', async () => {
    vi.stubGlobal('fetch', mockBadSchema({ not_our_payload: true }));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('invalid_schema');
  });

  // ── Section CC.partial — full structural validation ──────────────────────

  it('rejects a payload that is only {api_version:"v1"} (Round-3 fix)', async () => {
    // This reproduces the Round-2 finding exactly: a stub payload that
    // would have passed the previous version-only check and rendered
    // fabricated "No data" / zero ROI numbers.
    vi.stubGlobal('fetch', mockBadSchema({ api_version: 'v1' }));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('invalid_schema');
    // CRUCIAL: no fabricated state appears.
    expect(screen.queryByTestId('empty-banner')).not.toBeInTheDocument();
    expect(screen.queryByTestId('execution-total')).not.toBeInTheDocument();
  });

  it('rejects a payload missing the execution panel', async () => {
    const bad = makePayload();
    delete bad.execution;
    vi.stubGlobal('fetch', mockBadSchema(bad));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('execution');
  });

  it('rejects a payload missing the sources panel', async () => {
    const bad = makePayload();
    delete bad.sources;
    vi.stubGlobal('fetch', mockBadSchema(bad));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('sources');
  });

  it('rejects a payload missing the cost panel', async () => {
    const bad = makePayload();
    delete bad.cost;
    vi.stubGlobal('fetch', mockBadSchema(bad));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('cost');
  });

  it('rejects a payload where execution.total_tasks_completed is a string', async () => {
    const bad = makePayload();
    bad.execution.total_tasks_completed = '12';   // wrong type
    vi.stubGlobal('fetch', mockBadSchema(bad));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('execution.total_tasks_completed');
  });

  it('rejects a payload where cost is a float (Decimal contract violation)', async () => {
    // Cost MUST be a decimal STRING; a float here means someone
    // re-serialised through float and may have lost precision.
    const bad = makePayload();
    bad.cost.estimated_cost_total = 1.23;
    vi.stubGlobal('fetch', mockBadSchema(bad));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('cost.estimated_cost_total');
  });

  it('rejects a payload missing a nested required field', async () => {
    const bad = makePayload();
    delete bad.sources.malformed_count;
    vi.stubGlobal('fetch', mockBadSchema(bad));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-state'))
      .toHaveTextContent('sources.malformed_count');
  });

  it('accepts a fully-shaped payload without false positives', async () => {
    // Sanity: the validator must NOT reject a real, complete payload.
    vi.stubGlobal('fetch', mockOk(makePayload()));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('panel-execution')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('error-state')).not.toBeInTheDocument();
  });

  it('reserves bottom padding so the App switcher cannot overlap content', async () => {
    vi.stubGlobal('fetch', mockOk(makePayload()));
    render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('roi-dashboard-root')).toBeInTheDocument();
    });
    const root = screen.getByTestId('roi-dashboard-root');
    // Tailwind class ``pb-32`` (8rem) reserves room so the fixed
    // bottom-right switcher does not overlay the last panel.
    expect(root.className).toMatch(/pb-32/);
  });
});

// ── Section D — No hardcoded production values ─────────────────────────────

describe('ROIDashboard — does not hardcode dashboard values', () => {
  it('renders with a 999-task payload exactly; renders with 7 next call', async () => {
    const a = makePayload({
      execution: { total_tasks_completed: 999, tasks_by_skill: { kpi: 999 } },
    });
    vi.stubGlobal('fetch', mockOk(a));
    const { rerender } = render(<ROIDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('execution-total')).toHaveTextContent('999');
    });

    const b = makePayload({
      execution: { total_tasks_completed: 7, tasks_by_skill: { kpi: 7 } },
    });
    vi.stubGlobal('fetch', mockOk(b));
    rerender(<ROIDashboard key="re" />);
    await waitFor(() => {
      // After re-render with new mock, the number is the mock's, not 999.
      expect(screen.getByTestId('execution-total')).toHaveTextContent('7');
    });
  });
});
