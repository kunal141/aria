/**
 * ARIASkills — read-only catalog of ARIA's domain skills.
 *
 * Consumes GET /api/skills from the backend. Every card reads from the API
 * response — no hardcoded skill list. Mirrors ROIDashboard's fetch discipline:
 * content-type guard (so a Vite index.html fallback can't masquerade as data),
 * typed error banner, and loading state.
 */
import React, { useEffect, useState } from 'react';

function apiBase() {
  const v = (typeof import.meta !== 'undefined' && import.meta.env) || {};
  return v.VITE_API_BASE_URL || '';
}

const TIER_STYLES = {
  1: 'bg-slate-100 text-slate-700 border-slate-200',
  2: 'bg-sky-100 text-sky-700 border-sky-200',
  3: 'bg-amber-100 text-amber-800 border-amber-200',
  4: 'bg-orange-100 text-orange-800 border-orange-200',
  5: 'bg-red-100 text-red-800 border-red-200',
};

function TierBadge({ tier, name }) {
  const cls = TIER_STYLES[tier] || TIER_STYLES[1];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      T{tier} · {name}
    </span>
  );
}

function SkillCard({ skill }) {
  return (
    <div
      data-testid={`skill-card-${skill.name}`}
      className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm flex flex-col gap-3"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-900">{skill.title}</h3>
          <div className="text-xs text-gray-400 mt-0.5">
            {skill.category} · {skill.version}
          </div>
        </div>
        <TierBadge tier={skill.action_tier} name={skill.tier_name} />
      </div>

      <p className="text-sm text-gray-600 leading-relaxed">{skill.description}</p>

      <div className="mt-auto flex items-center gap-2 pt-2 text-xs font-mono">
        <span className="rounded-md bg-gray-50 border border-gray-200 px-2 py-1 text-gray-600">
          {skill.input_schema}
        </span>
        <span className="text-gray-400">→</span>
        <span className="rounded-md bg-gray-50 border border-gray-200 px-2 py-1 text-gray-600">
          {skill.output_schema}
        </span>
      </div>
    </div>
  );
}

export default function ARIASkills() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function fetchSkills() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${apiBase()}/api/skills`, {
          headers: { Accept: 'application/json' },
        });
        const contentType = res.headers.get('content-type') || '';
        if (!contentType.toLowerCase().includes('application/json')) {
          if (cancelled) return;
          setError({
            status: res.status,
            error_code: 'invalid_content_type',
            detail:
              `Expected application/json from /api/skills; got ${contentType || '(none)'}. ` +
              `The backend may be unreachable (check the Vite proxy or VITE_API_PROXY_TARGET).`,
          });
          setData(null);
          return;
        }
        const body = await res.json();
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
    fetchSkills();
    return () => { cancelled = true; };
  }, []);

  return (
    <div data-testid="skills-root" className="min-h-screen bg-gray-50 px-6 py-8 pb-32 sm:pb-28">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Skills</h1>
            <p className="text-sm text-gray-500 mt-1">
              ARIA's governed domain skills — each a typed input → output contract with an
              action tier. Read-only catalog; nothing here executes a skill.
            </p>
          </div>
          {data && (
            <span data-testid="skills-count" className="text-xs text-gray-400">
              {data.count} skill{data.count === 1 ? '' : 's'} · API {data.api_version}
            </span>
          )}
        </header>

        {loading && (
          <div data-testid="loading-state"
               className="rounded-2xl bg-white border border-gray-200 p-8 text-center text-gray-500">
            Loading skills…
          </div>
        )}

        {!loading && error && (
          <div data-testid="error-state" className="rounded-2xl border border-red-300 bg-red-50 p-6">
            <h2 className="text-lg font-semibold text-red-800">Skills unavailable</h2>
            <p className="text-sm text-red-700 mt-2">
              <strong>{error.error_code}</strong>{error.status ? ` (HTTP ${error.status})` : ''}
              {' — '}{error.detail}
            </p>
          </div>
        )}

        {!loading && !error && data && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {data.skills.map((s) => <SkillCard key={s.name} skill={s} />)}
          </div>
        )}
      </div>
    </div>
  );
}
