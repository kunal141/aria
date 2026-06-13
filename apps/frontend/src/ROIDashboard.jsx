/**
 * ROIDashboard — Week 29 Priority 2
 *
 * Consumes GET /api/v1/ledger/metrics from the backend. Every panel
 * reads from the API response — no hardcoded production numbers.
 *
 * Required states:
 *   - loading        — skeleton while fetch is in flight
 *   - api error      — typed error banner from MetricsErrorResponse
 *   - empty ledger   — when sources.{v2_event_count, legacy_*} all zero
 *   - partial/no-data — null rate/cost/duration values render as "No data"
 *   - malformed warning — banner when sources.malformed_count > 0
 *   - filtered results — banner echoing filters_applied
 *
 * Filter controls: date range, skill, actor_type, workflow_id.
 *
 * Money: Decimal strings come through as strings — never parsed to
 * float for display.
 */
import React, { useEffect, useMemo, useState } from 'react';

const NO_DATA = 'No data';

/** Resolve the API base URL. Allows override via VITE_API_BASE_URL. */
function apiBase() {
  const v = (typeof import.meta !== 'undefined' && import.meta.env) || {};
  return v.VITE_API_BASE_URL || '';
}

/**
 * Full structural validation of a MetricsResponse payload.
 *
 * Round-3 fix: a previous defensive check only confirmed
 * ``api_version === "v1"``. A payload of just ``{"api_version":"v1"}``
 * passed that check; missing panels then defaulted to 0 / "No data"
 * via optional chaining, fabricating ROI numbers. The dashboard must
 * reject ANY response that omits a required panel or has a wrong-typed
 * required field, BEFORE setData() so no fabricated values reach the
 * UI.
 *
 * Returns ``null`` on success, or a string describing the first
 * problem encountered.
 */
function validateMetricsResponse(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return 'Response must be a JSON object.';
  }
  if (body.api_version !== 'v1') {
    return 'Response is missing api_version="v1".';
  }

  const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const isNumOrNull = (v) => v === null || isNum(v);
  const isStr = (v) => typeof v === 'string';
  const isStrOrNull = (v) => v === null || isStr(v);
  const isStrIntDict = (v) =>
    isObj(v) && Object.values(v).every((x) => Number.isInteger(x));
  const isStrFloatOrNullDict = (v) =>
    isObj(v) && Object.values(v).every(isNumOrNull);

  // Each panel: list of [field, predicate, description].
  const panels = {
    filters_applied: [
      ['start_date',  isStrOrNull, 'string or null'],
      ['end_date',    isStrOrNull, 'string or null'],
      ['skill',       isStrOrNull, 'string or null'],
      ['actor_type',  isStrOrNull, 'string or null'],
      ['workflow_id', isStrOrNull, 'string or null'],
    ],
    execution: [
      ['total_tasks_completed', Number.isInteger, 'integer'],
      ['tasks_by_skill',        isStrIntDict,     'dict[str,int]'],
    ],
    approval: [
      ['approval_rate',          isNumOrNull,            'number or null'],
      ['approvals_granted',      Number.isInteger,       'integer'],
      ['approvals_rejected',     Number.isInteger,       'integer'],
      ['approval_rate_by_skill', isStrFloatOrNullDict,   'dict[str,number|null]'],
    ],
    failure: [
      ['failure_rate',           isNumOrNull,            'number or null'],
      ['failed_tasks',           Number.isInteger,       'integer'],
      ['terminal_tasks',         Number.isInteger,       'integer'],
      ['failure_rate_by_skill',  isStrFloatOrNullDict,   'dict[str,number|null]'],
    ],
    resolution: [
      ['avg_time_to_resolution_ms', isNumOrNull, 'number or null'],
    ],
    cost: [
      // Decimal serialised as a STRING — must never be a float.
      ['estimated_cost_total',    isStr,           'decimal string'],
      ['estimated_cost_per_task', isStrOrNull,     'decimal string or null'],
      ['tasks_with_cost',         Number.isInteger, 'integer'],
    ],
    human_intervention: [
      ['rate', isNumOrNull, 'number or null'],
    ],
    artifacts:   [['count', Number.isInteger, 'integer']],
    corrections: [['count', Number.isInteger, 'integer']],
    models: [
      ['usage_breakdown', isStrIntDict, 'dict[str,int]'],
    ],
    sources: [
      ['v2_event_count',         Number.isInteger, 'integer'],
      ['legacy_task_count',      Number.isInteger, 'integer'],
      ['legacy_evolution_count', Number.isInteger, 'integer'],
      ['malformed_count',        Number.isInteger, 'integer'],
    ],
  };

  for (const [panel, fields] of Object.entries(panels)) {
    const obj = body[panel];
    if (!isObj(obj)) {
      return `Response is missing required panel "${panel}".`;
    }
    for (const [field, predicate, desc] of fields) {
      if (!(field in obj)) {
        return `Response is missing required field "${panel}.${field}".`;
      }
      if (!predicate(obj[field])) {
        return `Response field "${panel}.${field}" must be ${desc}.`;
      }
    }
  }
  return null;
}

/** Build a query string from a filters object, dropping empty values. */
function buildQuery(filters) {
  const params = new URLSearchParams();
  if (filters.start_date)  params.set('start_date',  filters.start_date);
  if (filters.end_date)    params.set('end_date',    filters.end_date);
  if (filters.skill)       params.set('skill',       filters.skill);
  if (filters.actor_type)  params.set('actor_type',  filters.actor_type);
  if (filters.workflow_id) params.set('workflow_id', filters.workflow_id);
  const s = params.toString();
  return s ? `?${s}` : '';
}

/** Render a number or "No data" — null and undefined become "No data". */
function fmtNumber(v) {
  if (v === null || v === undefined) return NO_DATA;
  return typeof v === 'number'
    ? v.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : String(v);
}

function fmtPercent(v) {
  if (v === null || v === undefined) return NO_DATA;
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function fmtMs(v) {
  if (v === null || v === undefined) return NO_DATA;
  const n = Number(v);
  if (n < 1000) return `${n.toFixed(0)} ms`;
  if (n < 60_000) return `${(n / 1000).toFixed(1)} s`;
  return `${(n / 60_000).toFixed(1)} min`;
}

function fmtCost(v) {
  if (v === null || v === undefined) return NO_DATA;
  // v is a Decimal string from the backend — display as-is with $ prefix.
  return `$${v}`;
}

// ── Panel wrapper ────────────────────────────────────────────────────────────

function Panel({ title, children, testId, fullWidth = false }) {
  return (
    <div
      data-testid={testId}
      className={`rounded-2xl border border-gray-200 bg-white p-5 shadow-sm
        ${fullWidth ? 'sm:col-span-2 lg:col-span-3' : ''}`}
    >
      <h3 className="text-xs font-medium uppercase tracking-wider text-gray-500 mb-3">
        {title}
      </h3>
      {children}
    </div>
  );
}

function BigNumber({ value, label, testId }) {
  return (
    <div data-testid={testId}>
      <div className="text-3xl font-semibold text-gray-900">{value}</div>
      {label && <div className="text-sm text-gray-500 mt-1">{label}</div>}
    </div>
  );
}

function BreakdownList({ data, valueLabel, formatter = fmtNumber, testId }) {
  const entries = Object.entries(data || {});
  if (entries.length === 0) {
    return <div data-testid={testId} className="text-sm text-gray-500">{NO_DATA}</div>;
  }
  return (
    <ul data-testid={testId} className="space-y-2">
      {entries.map(([key, value]) => (
        <li key={key} className="flex items-center justify-between text-sm">
          <span className="text-gray-700">{key}</span>
          <span className="font-medium text-gray-900">{formatter(value)}</span>
        </li>
      ))}
    </ul>
  );
}

// ── Filter bar ───────────────────────────────────────────────────────────────

const ACTOR_TYPES = ['human', 'aria', 'subagent', 'system', 'tool'];

function FilterBar({ filters, onChange, onApply, onReset, disabled }) {
  return (
    <form
      data-testid="filter-bar"
      onSubmit={(e) => { e.preventDefault(); onApply(); }}
      className="flex flex-wrap items-end gap-3 bg-white rounded-2xl border border-gray-200 p-4 shadow-sm"
    >
      <div className="flex flex-col">
        <label htmlFor="start_date" className="text-xs uppercase text-gray-500 mb-1">
          Start date
        </label>
        <input
          id="start_date" data-testid="filter-start-date" type="text"
          placeholder="2026-06-11T00:00:00+00:00"
          value={filters.start_date || ''}
          onChange={(e) => onChange({ ...filters, start_date: e.target.value })}
          disabled={disabled}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm w-56"
        />
      </div>
      <div className="flex flex-col">
        <label htmlFor="end_date" className="text-xs uppercase text-gray-500 mb-1">
          End date
        </label>
        <input
          id="end_date" data-testid="filter-end-date" type="text"
          placeholder="2026-06-12T00:00:00+00:00"
          value={filters.end_date || ''}
          onChange={(e) => onChange({ ...filters, end_date: e.target.value })}
          disabled={disabled}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm w-56"
        />
      </div>
      <div className="flex flex-col">
        <label htmlFor="skill" className="text-xs uppercase text-gray-500 mb-1">
          Skill
        </label>
        <input
          id="skill" data-testid="filter-skill" type="text"
          value={filters.skill || ''}
          onChange={(e) => onChange({ ...filters, skill: e.target.value })}
          disabled={disabled}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm w-40"
        />
      </div>
      <div className="flex flex-col">
        <label htmlFor="actor_type" className="text-xs uppercase text-gray-500 mb-1">
          Actor type
        </label>
        <select
          id="actor_type" data-testid="filter-actor-type"
          value={filters.actor_type || ''}
          onChange={(e) => onChange({ ...filters, actor_type: e.target.value })}
          disabled={disabled}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm"
        >
          <option value="">Any</option>
          {ACTOR_TYPES.map((at) => (
            <option key={at} value={at}>{at}</option>
          ))}
        </select>
      </div>
      <div className="flex flex-col">
        <label htmlFor="workflow_id" className="text-xs uppercase text-gray-500 mb-1">
          Workflow ID
        </label>
        <input
          id="workflow_id" data-testid="filter-workflow-id" type="text"
          value={filters.workflow_id || ''}
          onChange={(e) => onChange({ ...filters, workflow_id: e.target.value })}
          disabled={disabled}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm w-40"
        />
      </div>
      <div className="flex gap-2 ml-auto">
        <button
          type="button" data-testid="filter-reset" onClick={onReset}
          disabled={disabled}
          className="px-4 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
        >
          Reset
        </button>
        <button
          type="submit" data-testid="filter-apply"
          disabled={disabled}
          className="px-4 py-2 text-sm rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
        >
          Apply
        </button>
      </div>
    </form>
  );
}

// ── Banners ──────────────────────────────────────────────────────────────────

function EmptyBanner() {
  return (
    <div data-testid="empty-banner"
         className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      No ledger records found. The dashboard will populate once tasks are logged.
    </div>
  );
}

function MalformedBanner({ count }) {
  return (
    <div data-testid="malformed-banner"
         className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <strong>{count}</strong> malformed ledger record{count === 1 ? '' : 's'} were
      skipped during aggregation. Investigate the upstream writer.
    </div>
  );
}

function FilteredBanner({ filters }) {
  const parts = [];
  if (filters.start_date)  parts.push(`start=${filters.start_date}`);
  if (filters.end_date)    parts.push(`end=${filters.end_date}`);
  if (filters.skill)       parts.push(`skill=${filters.skill}`);
  if (filters.actor_type)  parts.push(`actor_type=${filters.actor_type}`);
  if (filters.workflow_id) parts.push(`workflow_id=${filters.workflow_id}`);
  if (parts.length === 0) return null;
  return (
    <div data-testid="filtered-banner"
         className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-800">
      Filtered view: {parts.join(' · ')}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

const EMPTY_FILTERS = {
  start_date: '', end_date: '', skill: '', actor_type: '', workflow_id: '',
};

export default function ROIDashboard() {
  const [filters, setFilters]       = useState(EMPTY_FILTERS);
  const [appliedFilters, setApplied] = useState(EMPTY_FILTERS);
  const [data,    setData]    = useState(null);
  const [error,   setError]   = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function fetchMetrics() {
      setLoading(true);
      setError(null);
      try {
        const url = `${apiBase()}/api/v1/ledger/metrics${buildQuery(appliedFilters)}`;
        const res = await fetch(url, {
          headers: { Accept: 'application/json' },
        });

        // Guard: when /api isn't proxied to the backend the Vite dev
        // server returns index.html with HTTP 200 — silently parsing
        // that as "empty metrics" creates a false success state. Reject
        // anything that isn't an application/json content type BEFORE
        // attempting to read the body.
        const contentType = res.headers.get('content-type') || '';
        if (!contentType.toLowerCase().includes('application/json')) {
          if (cancelled) return;
          setError({
            status: res.status,
            error_code: 'invalid_content_type',
            detail:
              `Expected application/json from /api/v1/ledger/metrics; got ` +
              `${contentType || '(none)'}. The backend may be unreachable ` +
              `(check the Vite proxy or VITE_API_PROXY_TARGET).`,
          });
          setData(null);
          return;
        }

        // Read the body as text first so a parse failure surfaces as a
        // typed error instead of being swallowed as ``{}``.
        const text = await res.text();
        let body;
        try {
          body = JSON.parse(text);
        } catch (parseErr) {
          if (cancelled) return;
          setError({
            status: res.status,
            error_code: 'invalid_json',
            detail: `Backend returned invalid JSON (${parseErr.message}).`,
          });
          setData(null);
          return;
        }
        if (cancelled) return;
        if (!res.ok) {
          setError({
            status: res.status,
            error_code: body.error_code || 'unknown',
            detail: body.detail || `HTTP ${res.status}`,
          });
          setData(null);
          return;
        }

        // Full structural validation — guards against partial v1
        // payloads silently falling through optional chaining and
        // rendering fabricated zero metrics.
        const schemaProblem = validateMetricsResponse(body);
        if (schemaProblem) {
          setError({
            status: res.status,
            error_code: 'invalid_schema',
            detail: `Response did not match the expected MetricsResponse schema: ${schemaProblem}`,
          });
          setData(null);
          return;
        }

        setData(body);
      } catch (err) {
        if (cancelled) return;
        setError({
          status: 0,
          error_code: 'network_error',
          detail: err && err.message ? err.message : 'Network error',
        });
        setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchMetrics();
    return () => { cancelled = true; };
  }, [appliedFilters]);

  const isEmpty = useMemo(() => {
    if (!data) return false;
    const s = data.sources || {};
    return (
      (s.v2_event_count || 0) === 0
      && (s.legacy_task_count || 0) === 0
      && (s.legacy_evolution_count || 0) === 0
    );
  }, [data]);

  return (
    // ``pb-32`` reserves bottom padding so the App.jsx fixed view-
    // switcher (anchored bottom-right with ``fixed bottom-5``) cannot
    // overlap the last ROI panel on either desktop OR mobile widths.
    // The reservation is intentionally generous to cover the
    // switcher's wrapped second row on narrow viewports.
    <div data-testid="roi-dashboard-root"
         className="min-h-screen bg-gray-50 px-6 py-8 pb-32 sm:pb-28">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">ROI Dashboard</h1>
            <p className="text-sm text-gray-500 mt-1">
              Harness-engineered ROI metrics from the Work Ledger.
            </p>
          </div>
          {data && data.api_version && (
            <span data-testid="api-version" className="text-xs text-gray-400">
              API {data.api_version}
            </span>
          )}
        </header>

        <FilterBar
          filters={filters}
          onChange={setFilters}
          onApply={() => setApplied(filters)}
          onReset={() => {
            setFilters(EMPTY_FILTERS);
            setApplied(EMPTY_FILTERS);
          }}
          disabled={loading}
        />

        {loading && (
          <div data-testid="loading-state" className="rounded-2xl bg-white border border-gray-200 p-8 text-center text-gray-500">
            Loading metrics…
          </div>
        )}

        {!loading && error && (
          <div data-testid="error-state"
               className="rounded-2xl border border-red-300 bg-red-50 p-6">
            <h2 className="text-lg font-semibold text-red-800">
              Metrics unavailable
            </h2>
            <p className="text-sm text-red-700 mt-2">
              <strong>{error.error_code}</strong>{error.status ? ` (HTTP ${error.status})` : ''}
              {' — '}{error.detail}
            </p>
          </div>
        )}

        {!loading && !error && data && (
          <>
            {(() => {
              const f = data.filters_applied || {};
              return Object.values(f).some((v) => v) ? <FilteredBanner filters={f} /> : null;
            })()}
            {isEmpty && <EmptyBanner />}
            {data.sources && data.sources.malformed_count > 0 && (
              <MalformedBanner count={data.sources.malformed_count} />
            )}

            {/* ── Panel grid ── */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">

              {/* 1. Execution coverage */}
              <Panel title="Execution coverage" testId="panel-execution">
                <BigNumber
                  testId="execution-total"
                  value={fmtNumber(data.execution?.total_tasks_completed ?? 0)}
                  label="completed tasks"
                />
              </Panel>

              {/* 2. Tasks by skill */}
              <Panel title="Tasks by skill" testId="panel-tasks-by-skill">
                <BreakdownList
                  testId="tasks-by-skill-list"
                  data={data.execution?.tasks_by_skill}
                  valueLabel="tasks"
                />
              </Panel>

              {/* 3. Approval friction */}
              <Panel title="Approval friction" testId="panel-approval">
                <BigNumber
                  testId="approval-rate"
                  value={fmtPercent(data.approval?.approval_rate)}
                  label={`granted ${data.approval?.approvals_granted ?? 0} / rejected ${data.approval?.approvals_rejected ?? 0}`}
                />
                <div className="mt-4">
                  <BreakdownList
                    testId="approval-rate-by-skill"
                    data={data.approval?.approval_rate_by_skill}
                    formatter={fmtPercent}
                  />
                </div>
              </Panel>

              {/* 4. Failure containment */}
              <Panel title="Failure containment" testId="panel-failure">
                <BigNumber
                  testId="failure-rate"
                  value={fmtPercent(data.failure?.failure_rate)}
                  label={`failed ${data.failure?.failed_tasks ?? 0} / terminal ${data.failure?.terminal_tasks ?? 0}`}
                />
                <div className="mt-4">
                  <BreakdownList
                    testId="failure-rate-by-skill"
                    data={data.failure?.failure_rate_by_skill}
                    formatter={fmtPercent}
                  />
                </div>
              </Panel>

              {/* 5. Avg time to resolution */}
              <Panel title="Average time to resolution" testId="panel-resolution">
                <BigNumber
                  testId="avg-resolution"
                  value={fmtMs(data.resolution?.avg_time_to_resolution_ms)}
                />
              </Panel>

              {/* 6. Cost per task */}
              <Panel title="Cost per task" testId="panel-cost">
                <BigNumber
                  testId="cost-per-task"
                  value={fmtCost(data.cost?.estimated_cost_per_task)}
                  label={`total ${fmtCost(data.cost?.estimated_cost_total)} across ${data.cost?.tasks_with_cost ?? 0} task${(data.cost?.tasks_with_cost ?? 0) === 1 ? '' : 's'}`}
                />
              </Panel>

              {/* 7. Human intervention rate */}
              <Panel title="Human intervention rate" testId="panel-human">
                <BigNumber
                  testId="human-rate"
                  value={fmtPercent(data.human_intervention?.rate)}
                />
              </Panel>

              {/* 8. Artifact throughput */}
              <Panel title="Artifact throughput" testId="panel-artifacts">
                <BigNumber
                  testId="artifact-count"
                  value={fmtNumber(data.artifacts?.count ?? 0)}
                />
              </Panel>

              {/* 9. Correction learning signal */}
              <Panel title="Correction learning signal" testId="panel-corrections">
                <BigNumber
                  testId="correction-count"
                  value={fmtNumber(data.corrections?.count ?? 0)}
                />
              </Panel>

              {/* 10. Model usage mix */}
              <Panel title="Model usage mix" testId="panel-models">
                <BreakdownList
                  testId="model-usage-list"
                  data={data.models?.usage_breakdown}
                />
              </Panel>

              {/* 11. Legacy vs v2 source split */}
              <Panel title="Source split (legacy vs v2)" testId="panel-sources" fullWidth>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div data-testid="source-v2">
                    <div className="text-xs text-gray-500 uppercase">v2 events</div>
                    <div className="text-2xl font-semibold text-gray-900">
                      {fmtNumber(data.sources?.v2_event_count ?? 0)}
                    </div>
                  </div>
                  <div data-testid="source-legacy-task">
                    <div className="text-xs text-gray-500 uppercase">Legacy tasks</div>
                    <div className="text-2xl font-semibold text-gray-900">
                      {fmtNumber(data.sources?.legacy_task_count ?? 0)}
                    </div>
                  </div>
                  <div data-testid="source-legacy-evolution">
                    <div className="text-xs text-gray-500 uppercase">Legacy evolution</div>
                    <div className="text-2xl font-semibold text-gray-900">
                      {fmtNumber(data.sources?.legacy_evolution_count ?? 0)}
                    </div>
                  </div>
                  <div data-testid="source-malformed">
                    <div className="text-xs text-gray-500 uppercase">Malformed</div>
                    <div className="text-2xl font-semibold text-gray-900">
                      {fmtNumber(data.sources?.malformed_count ?? 0)}
                    </div>
                  </div>
                </div>
              </Panel>

            </div>
          </>
        )}
      </div>
    </div>
  );
}
