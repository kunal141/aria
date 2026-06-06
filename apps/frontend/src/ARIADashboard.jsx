import React, { useState } from 'react';

// ─── Mock Data (all dummy — wires to FastAPI ~Week 13) ────────────────────────

const MOCK_TASKS = [
  { id: 'T-001', goal: 'Review PR #47 — LangGraph orchestrator refactor', status: 'running', agent: 'PR Review Skill v2', tier: 2, eta: '~2 min', priority: 'high', created: '10:42 AM', pillar: 'AI Engineering' },
  { id: 'T-002', goal: 'Generate test cases for skills/registry.py changes', status: 'awaiting_approval', agent: 'QA Agent v1', tier: 3, eta: 'Pending approval', priority: 'high', created: '10:38 AM', pillar: 'QA Intelligence' },
  { id: 'T-003', goal: 'Summarize CI/CD failure — build #203', status: 'completed', agent: 'CI/CD Agent v1', tier: 1, eta: 'Done', priority: 'medium', created: '10:15 AM', pillar: 'CI/CD Intelligence' },
  { id: 'T-004', goal: 'Investigate KPI drop: pageviews -18% vs last week', status: 'running', agent: 'Analytics Agent v1', tier: 2, eta: '~5 min', priority: 'high', created: '09:58 AM', pillar: 'Data Science & Analytics' },
  { id: 'T-005', goal: 'Create Jira ticket from PR #45 CI failure', status: 'completed', agent: 'Jira Skill v1', tier: 3, eta: 'Done', priority: 'low', created: '09:30 AM', pillar: 'Jira / Delivery' },
  { id: 'T-006', goal: 'Draft leadership summary: Week 18 AI Engineering progress', status: 'pending', agent: 'Reporting Skill v1', tier: 3, eta: 'Queued', priority: 'medium', created: '09:10 AM', pillar: 'Reporting' },
];

const MOCK_APPROVALS = [
  { id: 'A-001', taskId: 'T-002', type: 'artifact_send', title: 'Send QA Test Cases to PR #47', description: 'ARIA generated 14 test cases for the LangGraph orchestrator refactor. Includes 9 functional tests, 3 edge cases, 2 negative tests. Coverage gap detected: no tests for checkpointer failure scenarios.', risk: 'low', riskScore: 2, agent: 'QA Agent v1', tier: 3, time: '2 min ago', artifact: 'test_cases_pr47.md', pillar: 'QA Intelligence' },
  { id: 'A-002', taskId: 'T-007', type: 'capability_proposal', title: 'Capability Proposal: Integrate Self-RAG into Knowledge Retrieval', description: 'ARIA reviewed the Self-RAG paper (Asai et al., 2023). Current retrieval has no relevance validation step — 23% of retrieved docs score below relevance threshold in benchmark. Self-RAG would add critique-and-retrieve loop. Expected improvement: +1.4 rubric score on knowledge retrieval quality.', risk: 'low', riskScore: 3, agent: 'Evolution Intelligence', tier: 2, time: '47 min ago', artifact: 'proposal_self_rag.md', pillar: 'Evolution Intelligence' },
  { id: 'A-003', taskId: 'T-008', type: 'jira_create', title: 'Create Jira Ticket: Missing Test Coverage — Memory Fabric', description: 'Test case generation for PR #46 (memory fabric v2) identified a critical gap: no tests for memory paging under concurrent load. ARIA proposes creating a Jira story in the ARIA-CORE project.', risk: 'medium', riskScore: 4, agent: 'QA Agent v1', tier: 3, time: '1h 12min ago', artifact: null, pillar: 'QA Intelligence' },
];

const MOCK_AGENTS = [
  { id: 'aria-core', name: 'ARIA Core Orchestrator', version: 'v1.0', status: 'healthy', type: 'orchestrator', tasks: 847, avgLatency: '1.8s', cost: '$12.40', rubricScore: 8.1, uptime: '99.7%', since: 'Week 3', pillar: 'Core', description: 'Main orchestrator: receives goals, decomposes, routes, synthesizes' },
  { id: 'pr-review', name: 'PR Review Skill', version: 'v2.1', status: 'healthy', type: 'skill', tasks: 47, avgLatency: '23s', cost: '$4.20', rubricScore: 7.8, uptime: '100%', since: 'Week 7', pillar: 'AI Engineering', description: 'Reviews code PRs: quality, deployment risk, business impact, missing tests' },
  { id: 'qa-agent', name: 'QA Agent', version: 'v1.0', status: 'healthy', type: 'agent', tasks: 31, avgLatency: '45s', cost: '$3.80', rubricScore: 7.2, uptime: '98.4%', since: 'Week 17', pillar: 'QA Intelligence', description: 'Test case generation, coverage gap detection, failed test analysis' },
  { id: 'analytics', name: 'Analytics Agent', version: 'v1.2', status: 'healthy', type: 'agent', tasks: 124, avgLatency: '12s', cost: '$8.10', rubricScore: 7.5, uptime: '99.1%', since: 'Week 4', pillar: 'Data Science', description: 'KPI investigation, anomaly detection, experiment analysis' },
  { id: 'cicd', name: 'CI/CD Agent', version: 'v1.0', status: 'healthy', type: 'agent', tasks: 89, avgLatency: '8s', cost: '$2.30', rubricScore: 8.0, uptime: '100%', since: 'Week 19', pillar: 'CI/CD Intelligence', description: 'Build log analysis, release readiness, rollback recommendations' },
  { id: 'knowledge', name: 'Knowledge Retrieval', version: 'v1.3', status: 'healthy', type: 'skill', tasks: 203, avgLatency: '3.2s', cost: '$6.70', rubricScore: 7.1, uptime: '99.8%', since: 'Week 9', pillar: 'Knowledge / RAG', description: 'SOP retrieval, architecture docs, org knowledge — HyDE + Self-RAG + Adaptive RAG' },
  { id: 'jira', name: 'Jira Skill', version: 'v1.0', status: 'degraded', type: 'skill', tasks: 38, avgLatency: '5.1s', cost: '$1.20', rubricScore: 6.8, uptime: '92.3%', since: 'Week 20', pillar: 'Jira / Delivery', description: 'Ticket creation, story refinement, sprint summaries, blocker tracking' },
  { id: 'evolution', name: 'Evolution Intelligence', version: 'v0.1', status: 'new', type: 'system', tasks: 3, avgLatency: '—', cost: '$0.40', rubricScore: null, uptime: '100%', since: 'Week 18', pillar: 'Evolution Intelligence', description: 'AI ecosystem monitoring — daily digest of papers, repos, frameworks' },
];

const MOCK_LEDGER = [
  { id: 'L-847', goal: 'Review PR #47 — LangGraph refactor', agent: 'PR Review Skill v2', status: 'running', outcome: null, roi: null, time: '10:42 AM', tier: 2, pillar: 'AI Engineering', tokens: 2840 },
  { id: 'L-846', goal: 'Summarize CI failure — build #203', agent: 'CI/CD Agent v1', status: 'completed', outcome: 'Root cause: missing env var LANGSMITH_API_KEY in staging. Recommended fix applied.', roi: 'Prevented 45min manual investigation', time: '10:15 AM', tier: 1, pillar: 'CI/CD Intelligence', tokens: 1240 },
  { id: 'L-845', goal: 'Investigate KPI drop: pageviews -18%', agent: 'Analytics Agent v1', status: 'running', outcome: null, roi: null, time: '09:58 AM', tier: 2, pillar: 'Data Science', tokens: 3100 },
  { id: 'L-844', goal: 'Create Jira ticket from PR #45 failure', agent: 'Jira Skill v1', status: 'completed', outcome: 'ARIA-203 created: "Add test coverage for checkpointer failure scenarios"', roi: 'Saved ~15min manual ticket creation', time: '09:30 AM', tier: 3, pillar: 'Jira / Delivery', tokens: 890 },
  { id: 'L-843', goal: 'Generate test cases for memory fabric v2', agent: 'QA Agent v1', status: 'completed', outcome: '11 test cases generated. 2 critical gaps found: no concurrency tests, no memory paging tests.', roi: 'Caught 2 coverage gaps before PR merge', time: 'Yesterday 4:12 PM', tier: 2, pillar: 'QA Intelligence', tokens: 2200 },
  { id: 'L-842', goal: 'Review PR #46 — memory fabric v2', agent: 'PR Review Skill v2', status: 'completed', outcome: 'Risk: HIGH — missing test coverage for concurrency. Deployment recommended only after test gaps closed.', roi: 'Prevented risky deployment', time: 'Yesterday 3:45 PM', tier: 2, pillar: 'AI Engineering', tokens: 3400 },
  { id: 'L-841', goal: 'Weekly PR review summary report', agent: 'Reporting Skill v1', status: 'completed', outcome: 'Report generated: 7 PRs reviewed, 2 high-risk flagged, 1 rejected deployment. Sent to Teams.', roi: 'Saved ~2hr manual reporting', time: 'Yesterday 9:00 AM', tier: 1, pillar: 'Reporting', tokens: 1800 },
  { id: 'L-840', goal: 'Read arxiv paper: Self-RAG (Asai et al. 2023)', agent: 'Evolution Intelligence', status: 'completed', outcome: 'Relevance score: 9/10. Capability proposal drafted: Self-RAG integration into knowledge retrieval layer.', roi: 'Identified +1.4 rubric improvement opportunity', time: '2 days ago', tier: 1, pillar: 'Evolution Intelligence', tokens: 4200 },
];

const MOCK_EVOLUTION = [
  { id: 'EV-001', type: 'proposal', status: 'pending_approval', title: 'Integrate Self-RAG into Knowledge Retrieval Layer', source: 'Self-RAG: Learning to Retrieve, Generate, and Critique (Asai et al., 2023)', sourceType: 'paper', relevance: 9, gap: 'Current retrieval has no relevance validation — 23% of retrieved docs score below threshold in benchmark.', expectedImprovement: '+1.4 rubric score on knowledge retrieval quality metric', effort: '3-4 days', risk: 'low', submittedAt: '47 min ago' },
  { id: 'EV-002', type: 'signal', status: 'reviewed', title: 'LangGraph v0.2.28 released — new streaming API', source: 'LangGraph GitHub Changelog', sourceType: 'changelog', relevance: 8, gap: 'ARIA uses older streaming API. New version adds streaming mid-graph updates.', expectedImprovement: 'Better real-time task progress visibility in Teams bot', effort: '1 day', risk: 'low', submittedAt: '3h ago' },
  { id: 'EV-003', type: 'signal', status: 'new', title: 'RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval', source: 'arxiv:2401.18059', sourceType: 'paper', relevance: 7, gap: 'ARIA uses flat chunking for long docs — loses hierarchical structure.', expectedImprovement: 'Better retrieval for architecture docs, annual reports, long SOPs', effort: '2-3 days', risk: 'low', submittedAt: 'Yesterday' },
  { id: 'EV-004', type: 'signal', status: 'new', title: 'CrewAI v0.5 — role-based agent framework update', source: 'GitHub Trending — AI/Agent', sourceType: 'repo', relevance: 5, gap: 'No direct gap — ARIA uses LangGraph. CrewAI coordination patterns may inform Week 17 workforce orchestration.', expectedImprovement: 'Better multi-agent task assignment patterns', effort: '1 day to review', risk: 'none', submittedAt: 'Yesterday' },
  { id: 'EV-005', type: 'integrated', status: 'live', title: 'HyDE now live in Knowledge Retrieval', source: 'Precise Zero-Shot Dense Retrieval without Relevance Labels (Gao et al., 2022)', sourceType: 'paper', relevance: 9, gap: 'Was: plain embedding of query. Now: embed hypothetical answer → better doc matching.', expectedImprovement: 'Retrieval relevance rubric: 5.8 → 7.1 (+1.3)', effort: 'Completed Week 9', risk: 'low', submittedAt: 'Week 9' },
];

const MOCK_MARKETPLACE = [
  { num: 1,  name: 'Conversational Tasking',         status: 'V1', week: 4,  rubric: 7.9, teams: ['AI Eng'],              description: 'Goal intake, decomposition, routing, synthesis', skills: 3 },
  { num: 2,  name: 'AI Engineering',                 status: 'V1', week: 7,  rubric: 7.8, teams: ['AI Eng', 'Dev'],       description: 'PR review, code intelligence, deployment risk', skills: 6 },
  { num: 3,  name: 'Data Science & Analytics',       status: 'V1', week: 11, rubric: 7.5, teams: ['Analytics'],           description: 'KPI investigation, anomaly detection, experiment analysis', skills: 4 },
  { num: 4,  name: 'QA / Test Intelligence',         status: 'V1', week: 17, rubric: 7.2, teams: ['QA', 'Dev'],           description: 'Test generation, coverage gaps, failed test analysis', skills: 4 },
  { num: 5,  name: 'CI/CD & Release',                status: 'V1', week: 19, rubric: 8.0, teams: ['DevOps'],              description: 'Build log analysis, release readiness, rollback', skills: 3 },
  { num: 6,  name: 'Jira / Delivery',                status: 'V1', week: 20, rubric: 6.8, teams: ['PM', 'Dev'],           description: 'Ticket creation, sprint summaries, blockers', skills: 3 },
  { num: 7,  name: 'Reporting & Communication',      status: 'V1', week: 8,  rubric: 7.6, teams: ['Leadership', 'AI Eng'],description: 'Executive briefs, stakeholder emails, Teams updates', skills: 5 },
  { num: 8,  name: 'Knowledge / RAG / Org Intel',    status: 'V1', week: 9,  rubric: 7.1, teams: ['All'],                 description: 'SOP retrieval, architecture docs, org knowledge', skills: 4 },
  { num: 9,  name: 'Code Intelligence',              status: 'V1', week: 10, rubric: 7.4, teams: ['Dev', 'AI Eng'],       description: 'Repo Q&A, AST parsing, dependency graph', skills: 5 },
  { num: 10, name: 'Governance & Trust',             status: 'V1', week: 15, rubric: 8.3, teams: ['All'],                 description: 'Action tiers, RBAC, audit log, approval engine', skills: 6 },
  { num: 11, name: 'Agent Runtime Harness',          status: 'V1', week: 21, rubric: null,teams: ['Internal'],            description: 'Retries, checkpointing, idempotency, circuit breaker', skills: 2 },
  { num: 12, name: 'Agent Evaluation Harness',       status: 'V1', week: 14, rubric: null,teams: ['Internal'],            description: 'LangSmith rubrics, regression suite, LLM-as-judge', skills: 3 },
  { num: 13, name: 'Agent Factory',                  status: 'V2', week: 22, rubric: null,teams: ['AI Eng'],              description: 'Create, sandbox, evaluate, register new agents', skills: 0 },
  { num: 14, name: 'AI Workforce Expansion',         status: 'V2', week: 17, rubric: null,teams: ['AI Eng'],              description: 'Spawn, assign, monitor, retire specialist agents', skills: 0 },
  { num: 15, name: 'Agent Control Plane',            status: 'V2', week: 16, rubric: null,teams: ['AI Eng'],              description: 'Registry, health, lifecycle for all agents', skills: 0 },
  { num: 16, name: 'AI Work Ledger',                 status: 'V2', week: 29, rubric: null,teams: ['Leadership', 'AI Eng'],description: 'Permanent audit trail, ROI dashboard, 10 record types', skills: 0 },
  { num: 17, name: 'Human Teaching Layer',           status: 'V1', week: 9,  rubric: null,teams: ['Internal'],            description: 'Feedback capture, correction logging, preference memory', skills: 2 },
  { num: 18, name: 'Evolution Intelligence',         status: 'V2', week: 18, rubric: null,teams: ['AI Eng'],              description: 'AI ecosystem monitoring, capability proposals', skills: 1 },
  { num: 19, name: 'Workflow Mining',                status: 'V2', week: 22, rubric: null,teams: ['AI Eng'],              description: 'Detect repetition, identify automation candidates', skills: 0 },
  { num: 20, name: 'Decision Intelligence',          status: 'V3', week: 24, rubric: null,teams: [],                      description: 'Next-best-action, option ranking, LATS search', skills: 0 },
  { num: 21, name: 'Confidence, Cost & Risk',        status: 'V3', week: 25, rubric: null,teams: [],                      description: 'Model routing, approval prediction, release risk ML', skills: 0 },
  { num: 22, name: 'AI Capability Marketplace',      status: 'V3', week: 28, rubric: null,teams: [],                      description: 'Skill catalog, adoption tracking, team-facing UI', skills: 0 },
  { num: 23, name: 'AI Employee as a Service',       status: 'V3', week: 29, rubric: null,teams: [],                      description: 'Multi-tenant platform, governance console, billing', skills: 0 },
];

// ─── Shared helpers ───────────────────────────────────────────────────────────

const STATUS = {
  running:           { dot: 'bg-blue-500',   bg: 'bg-blue-50',   text: 'text-blue-700',   border: 'border-blue-200',   label: 'Running' },
  completed:         { dot: 'bg-green-500',  bg: 'bg-green-50',  text: 'text-green-700',  border: 'border-green-200',  label: 'Completed' },
  awaiting_approval: { dot: 'bg-amber-500',  bg: 'bg-amber-50',  text: 'text-amber-700',  border: 'border-amber-200',  label: 'Awaiting Approval' },
  pending:           { dot: 'bg-gray-400',   bg: 'bg-gray-100',  text: 'text-gray-600',   border: 'border-gray-200',   label: 'Pending' },
  failed:            { dot: 'bg-red-500',    bg: 'bg-red-50',    text: 'text-red-700',    border: 'border-red-200',    label: 'Failed' },
  healthy:           { dot: 'bg-green-500',  bg: 'bg-green-50',  text: 'text-green-700',  border: 'border-green-200',  label: 'Healthy' },
  degraded:          { dot: 'bg-amber-500',  bg: 'bg-amber-50',  text: 'text-amber-700',  border: 'border-amber-200',  label: 'Degraded' },
  new:               { dot: 'bg-violet-500', bg: 'bg-violet-50', text: 'text-violet-700', border: 'border-violet-200', label: 'New' },
};

const TIER_STYLE = {
  1: 'bg-green-50 text-green-700 border border-green-200',
  2: 'bg-blue-50 text-blue-700 border border-blue-200',
  3: 'bg-amber-50 text-amber-700 border border-amber-200',
  4: 'bg-orange-50 text-orange-700 border border-orange-200',
  5: 'bg-red-50 text-red-700 border border-red-200',
};
const TIER_LABEL = { 1: 'T1 Read', 2: 'T2 Recommend', 3: 'T3 Draft', 4: 'T4 Execute', 5: 'T5 Auto' };

const VERSION_STYLE = {
  V1: 'bg-green-50 text-green-700 border border-green-200',
  V2: 'bg-blue-50 text-blue-700 border border-blue-200',
  V3: 'bg-violet-50 text-violet-700 border border-violet-200',
};

const SIGNAL_ICON = { paper: '📄', changelog: '🔧', repo: '📦' };
const RISK_TEXT   = { low: 'text-green-600', medium: 'text-amber-600', high: 'text-red-600', none: 'text-gray-400' };

function Badge({ children, className = '' }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function Card({ children, className = '' }) {
  return (
    <div className={`bg-white border border-gray-200 rounded-xl shadow-sm ${className}`}>
      {children}
    </div>
  );
}

function StatCard({ label, value, sub, color = 'text-gray-900' }) {
  return (
    <Card className="p-4 text-center">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400 font-medium mt-0.5">{sub}</div>}
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </Card>
  );
}

function StatusDot({ status }) {
  const s = STATUS[status] || STATUS.pending;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium border ${s.bg} ${s.text} ${s.border}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot} ${status === 'running' ? 'animate-pulse' : ''}`} />
      {s.label}
    </span>
  );
}

function RubricBar({ score }) {
  if (score === null || score === undefined) return <span className="text-xs text-gray-400">—</span>;
  const pct = (score / 10) * 100;
  const color = score >= 8 ? 'bg-green-500' : score >= 7 ? 'bg-blue-500' : score >= 6 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-100 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-gray-700 w-6 text-right">{score}</span>
    </div>
  );
}

function FilterBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
        active
          ? 'bg-violet-600 text-white shadow-sm'
          : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
      }`}
    >
      {children}
    </button>
  );
}

function SearchInput({ value, onChange, placeholder }) {
  return (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="flex-1 bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
    />
  );
}

// ─── Panel: Task Queue ────────────────────────────────────────────────────────

function TaskQueue() {
  const [filter, setFilter] = useState('all');
  const counts = {
    running:           MOCK_TASKS.filter(t => t.status === 'running').length,
    awaiting_approval: MOCK_TASKS.filter(t => t.status === 'awaiting_approval').length,
    completed:         MOCK_TASKS.filter(t => t.status === 'completed').length,
  };
  const filtered = filter === 'all' ? MOCK_TASKS : MOCK_TASKS.filter(t => t.status === filter);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex gap-2 flex-wrap">
          <FilterBtn active={filter === 'all'} onClick={() => setFilter('all')}>All ({MOCK_TASKS.length})</FilterBtn>
          <FilterBtn active={filter === 'running'} onClick={() => setFilter('running')}>Running ({counts.running})</FilterBtn>
          <FilterBtn active={filter === 'awaiting_approval'} onClick={() => setFilter('awaiting_approval')}>Awaiting Approval ({counts.awaiting_approval})</FilterBtn>
          <FilterBtn active={filter === 'completed'} onClick={() => setFilter('completed')}>Completed ({counts.completed})</FilterBtn>
        </div>
        <p className="text-xs text-gray-400">All data is mock — wires to FastAPI at Week 13</p>
      </div>

      <div className="space-y-2">
        {filtered.map(task => (
          <Card key={task.id} className="p-4 hover:shadow-md transition-shadow">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="text-xs text-gray-400 font-mono">{task.id}</span>
                  <StatusDot status={task.status} />
                  <Badge className={TIER_STYLE[task.tier]}>{TIER_LABEL[task.tier]}</Badge>
                  <Badge className="bg-gray-50 text-gray-600 border border-gray-200">{task.pillar}</Badge>
                  {task.priority === 'high' && <Badge className="bg-red-50 text-red-700 border border-red-200">↑ High</Badge>}
                </div>
                <p className="text-sm font-medium text-gray-900 truncate">{task.goal}</p>
                <p className="text-xs text-gray-500 mt-1">
                  Agent: <span className="text-gray-700">{task.agent}</span>
                  {' · '}ETA: <span className="text-gray-700">{task.eta}</span>
                  {' · '}{task.created}
                </p>
              </div>
              {task.status === 'awaiting_approval' && (
                <div className="flex gap-2 shrink-0">
                  <button className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium transition-colors shadow-sm">✓ Approve</button>
                  <button className="px-3 py-1.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 text-xs font-medium transition-colors">✗ Reject</button>
                </div>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ─── Panel: Approval Inbox ────────────────────────────────────────────────────

function ApprovalInbox() {
  const [expanded, setExpanded] = useState(null);
  const [decisions, setDecisions] = useState({});
  const decide = (id, d) => setDecisions(prev => ({ ...prev, [id]: d }));
  const pending = MOCK_APPROVALS.filter(a => !decisions[a.id]).length;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 p-3 bg-amber-50 border border-amber-200 rounded-xl">
        <span className="text-amber-600 font-medium text-sm">⏳ {pending} approval{pending !== 1 ? 's' : ''} waiting</span>
        <span className="text-amber-500 text-xs">ARIA is paused until you decide. Action tier enforcement is working.</span>
      </div>

      <div className="space-y-3">
        {MOCK_APPROVALS.map(approval => {
          const decided = decisions[approval.id];
          const isOpen = expanded === approval.id;
          return (
            <Card key={approval.id} className={`p-4 transition-all ${decided ? 'opacity-60' : 'hover:shadow-md'} ${approval.type === 'capability_proposal' ? 'border-violet-200' : ''}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className="text-xs text-gray-400 font-mono">{approval.id}</span>
                    <Badge className={`bg-gray-50 border border-gray-200 text-gray-600 text-xs`}>
                      Risk: <span className={RISK_TEXT[approval.risk]}>{approval.riskScore}/10 · {approval.risk}</span>
                    </Badge>
                    <Badge className={TIER_STYLE[approval.tier]}>{TIER_LABEL[approval.tier]}</Badge>
                    <Badge className="bg-gray-50 text-gray-600 border border-gray-200">{approval.pillar}</Badge>
                    <span className="text-xs text-gray-400 ml-auto">{approval.time}</span>
                  </div>

                  <h3 className="text-sm font-semibold text-gray-900 mb-1">{approval.title}</h3>
                  <p className="text-xs text-gray-600 leading-relaxed">
                    {isOpen ? approval.description : approval.description.slice(0, 130) + '…'}
                  </p>

                  {approval.artifact && (
                    <div className="mt-2 flex items-center gap-1.5 text-xs text-violet-600 font-medium">
                      <span>📎</span><span className="font-mono">{approval.artifact}</span>
                    </div>
                  )}

                  <button
                    onClick={() => setExpanded(isOpen ? null : approval.id)}
                    className="mt-2 text-xs text-violet-600 hover:text-violet-800 font-medium transition-colors"
                  >
                    {isOpen ? '▲ Collapse' : '▼ Full context'}
                  </button>
                </div>

                <div className="flex flex-col gap-2 shrink-0">
                  {decided ? (
                    <Badge className={decided === 'approved' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}>
                      {decided === 'approved' ? '✓ Approved' : '✗ Rejected'}
                    </Badge>
                  ) : (
                    <>
                      <button onClick={() => decide(approval.id, 'approved')} className="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium transition-colors shadow-sm">✓ Approve</button>
                      <button onClick={() => decide(approval.id, 'rejected')} className="px-4 py-1.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 text-xs font-medium transition-colors">✗ Reject</button>
                    </>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ─── Panel: Agent Control Plane ───────────────────────────────────────────────

function AgentControlPlane() {
  const [selected, setSelected] = useState(null);
  const totalTasks = MOCK_AGENTS.reduce((s, a) => s + a.tasks, 0);
  const totalCost  = MOCK_AGENTS.reduce((s, a) => s + parseFloat(a.cost.replace('$', '')), 0).toFixed(2);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Registered Agents" value={MOCK_AGENTS.length} color="text-violet-600" />
        <StatCard label="Tasks Executed (all time)" value={totalTasks.toLocaleString()} color="text-blue-600" />
        <StatCard label="Total API Cost" value={`$${totalCost}`} color="text-green-600" />
      </div>

      <div className="space-y-2">
        {MOCK_AGENTS.map(a => {
          const isOpen = selected === a.id;
          return (
            <Card key={a.id} className={`p-4 cursor-pointer transition-all hover:shadow-md ${isOpen ? 'ring-2 ring-violet-500 ring-offset-1' : ''}`}
              onClick={() => setSelected(isOpen ? null : a.id)}>
              <div className="flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="text-sm font-semibold text-gray-900">{a.name}</span>
                    <span className="text-xs text-gray-400 font-mono">{a.version}</span>
                    <StatusDot status={a.status} />
                    <Badge className="bg-gray-50 text-gray-500 border border-gray-200 text-xs">{a.type}</Badge>
                    <Badge className="bg-violet-50 text-violet-700 border border-violet-200 text-xs">{a.pillar}</Badge>
                  </div>
                  {isOpen && <p className="text-xs text-gray-500 mt-1">{a.description}</p>}
                </div>
                <div className="flex items-center gap-5 shrink-0">
                  <div className="text-center">
                    <div className="text-sm font-semibold text-gray-900">{a.tasks}</div>
                    <div className="text-xs text-gray-400">tasks</div>
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-semibold text-gray-900">{a.avgLatency}</div>
                    <div className="text-xs text-gray-400">latency</div>
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-semibold text-gray-900">{a.cost}</div>
                    <div className="text-xs text-gray-400">cost</div>
                  </div>
                  <div className="w-24">
                    <div className="text-xs text-gray-400 mb-1">Rubric</div>
                    <RubricBar score={a.rubricScore} />
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-semibold text-gray-900">{a.uptime}</div>
                    <div className="text-xs text-gray-400">uptime</div>
                  </div>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ─── Panel: AI Work Ledger ────────────────────────────────────────────────────

function AIWorkLedger() {
  const [search, setSearch]       = useState('');
  const [pillarFilter, setPillar] = useState('all');
  const pillars = ['all', ...new Set(MOCK_LEDGER.map(l => l.pillar))];

  const filtered = MOCK_LEDGER.filter(l => {
    const matchSearch = !search || l.goal.toLowerCase().includes(search.toLowerCase()) || l.id.toLowerCase().includes(search.toLowerCase());
    const matchPillar = pillarFilter === 'all' || l.pillar === pillarFilter;
    return matchSearch && matchPillar;
  });

  const totalTokens = MOCK_LEDGER.reduce((s, l) => s + l.tokens, 0);
  const roiCount    = MOCK_LEDGER.filter(l => l.roi).length;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        <StatCard label="Total Tasks" value={MOCK_LEDGER.length} color="text-violet-600" />
        <StatCard label="Completed" value={MOCK_LEDGER.filter(l => l.status === 'completed').length} color="text-green-600" />
        <StatCard label="ROI Signals Captured" value={roiCount} color="text-blue-600" />
        <StatCard label="Tokens Used" value={totalTokens.toLocaleString()} sub="mock estimate" color="text-amber-600" />
      </div>

      <div className="flex gap-3">
        <SearchInput value={search} onChange={setSearch} placeholder="Search tasks, IDs…" />
        <select
          value={pillarFilter}
          onChange={e => setPillar(e.target.value)}
          className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-500"
        >
          {pillars.map(p => <option key={p} value={p}>{p === 'all' ? 'All Pillars' : p}</option>)}
        </select>
      </div>

      <div className="space-y-2">
        {filtered.map(entry => (
          <Card key={entry.id} className="p-4 hover:shadow-md transition-shadow">
            <div className="flex items-start gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="text-xs text-gray-400 font-mono">{entry.id}</span>
                  <StatusDot status={entry.status} />
                  <Badge className={TIER_STYLE[entry.tier]}>{TIER_LABEL[entry.tier]}</Badge>
                  <Badge className="bg-gray-50 text-gray-500 border border-gray-200 text-xs">{entry.pillar}</Badge>
                  <span className="text-xs text-gray-400 ml-auto">{entry.time}</span>
                  <span className="text-xs text-gray-400">{entry.tokens.toLocaleString()} tokens</span>
                </div>
                <p className="text-sm font-medium text-gray-900">{entry.goal}</p>
                <p className="text-xs text-gray-500 mt-0.5">Agent: {entry.agent}</p>
                {entry.outcome && (
                  <div className="mt-2 p-2.5 bg-gray-50 rounded-lg text-xs text-gray-700 leading-relaxed border border-gray-100">
                    <span className="text-gray-400 font-medium">Outcome: </span>{entry.outcome}
                  </div>
                )}
                {entry.roi && (
                  <div className="mt-2 flex items-center gap-1.5 text-xs text-green-700 font-medium">
                    <span>💰</span><span>{entry.roi}</span>
                  </div>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ─── Panel: Evolution Radar ───────────────────────────────────────────────────

function EvolutionRadar() {
  const [filter, setFilter]   = useState('all');
  const [decisions, setDecisions] = useState({});
  const decide = (id, d) => setDecisions(prev => ({ ...prev, [id]: d }));

  const filtered = filter === 'all' ? MOCK_EVOLUTION
    : MOCK_EVOLUTION.filter(e => e.status === filter || e.type === filter);

  const relevanceColor = r => r >= 8 ? 'text-green-600' : r >= 6 ? 'text-amber-600' : 'text-gray-500';

  const SIGNAL_STATUS = {
    pending_approval: 'bg-amber-50 text-amber-700 border-amber-200',
    reviewed:         'bg-blue-50 text-blue-700 border-blue-200',
    new:              'bg-violet-50 text-violet-700 border-violet-200',
    live:             'bg-green-50 text-green-700 border-green-200',
  };
  const SIGNAL_LABEL = {
    pending_approval: '⏳ Proposal — Awaiting Approval',
    reviewed:         '◉ Reviewed',
    new:              '✦ New Signal',
    live:             '✓ Integrated',
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex gap-2 flex-wrap">
          <FilterBtn active={filter === 'all'} onClick={() => setFilter('all')}>All</FilterBtn>
          <FilterBtn active={filter === 'proposal'} onClick={() => setFilter('proposal')}>Proposals ({MOCK_EVOLUTION.filter(e => e.type === 'proposal').length})</FilterBtn>
          <FilterBtn active={filter === 'new'} onClick={() => setFilter('new')}>New Signals ({MOCK_EVOLUTION.filter(e => e.status === 'new').length})</FilterBtn>
          <FilterBtn active={filter === 'live'} onClick={() => setFilter('live')}>Integrated ({MOCK_EVOLUTION.filter(e => e.status === 'live').length})</FilterBtn>
        </div>
        <p className="text-xs text-gray-400">ARIA monitors arxiv · GitHub · HuggingFace · LangChain changelog daily</p>
      </div>

      <div className="space-y-3">
        {filtered.map(item => {
          const decided = decisions[item.id];
          const st = SIGNAL_STATUS[item.status] || 'bg-gray-50 text-gray-600 border-gray-200';
          const sl = SIGNAL_LABEL[item.status] || 'Signal';
          return (
            <Card key={item.id} className={`p-4 hover:shadow-md transition-shadow ${item.type === 'proposal' ? 'border-violet-300' : ''}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span>{SIGNAL_ICON[item.sourceType] || '📡'}</span>
                    <Badge className={`border ${st}`}>{sl}</Badge>
                    <Badge className="bg-gray-50 text-gray-600 border border-gray-200 text-xs">
                      Relevance: <span className={`font-semibold ${relevanceColor(item.relevance)}`}>{item.relevance}/10</span>
                    </Badge>
                    <span className="text-xs text-gray-400 ml-auto">{item.submittedAt}</span>
                  </div>
                  <h3 className="text-sm font-semibold text-gray-900 mb-1">{item.title}</h3>
                  <p className="text-xs text-gray-500 mb-2">Source: <span className="text-gray-700 font-mono text-xs">{item.source}</span></p>
                  <div className="space-y-1 text-xs">
                    <div><span className="text-gray-400">Gap: </span><span className="text-gray-700">{item.gap}</span></div>
                    <div><span className="text-gray-400">Expected: </span><span className="text-green-700 font-medium">{item.expectedImprovement}</span></div>
                    <div className="flex gap-4">
                      <span><span className="text-gray-400">Effort: </span><span className="text-gray-700">{item.effort}</span></span>
                      <span><span className="text-gray-400">Risk: </span><span className={`font-medium ${RISK_TEXT[item.risk]}`}>{item.risk}</span></span>
                    </div>
                  </div>
                </div>
                {item.type === 'proposal' && item.status === 'pending_approval' && (
                  <div className="flex flex-col gap-2 shrink-0">
                    {decided ? (
                      <Badge className={decided === 'approved' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}>
                        {decided === 'approved' ? '✓ Approved' : '✗ Rejected'}
                      </Badge>
                    ) : (
                      <>
                        <button onClick={() => decide(item.id, 'approved')} className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium transition-colors shadow-sm">✓ Approve</button>
                        <button onClick={() => decide(item.id, 'rejected')} className="px-3 py-1.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 text-xs font-medium transition-colors">✗ Reject</button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ─── Panel: Capability Marketplace ───────────────────────────────────────────

function CapabilityMarketplace() {
  const [vFilter, setVFilter] = useState('all');
  const [search, setSearch]   = useState('');

  const filtered = MOCK_MARKETPLACE.filter(p =>
    (vFilter === 'all' || p.status === vFilter) &&
    (!search || p.name.toLowerCase().includes(search.toLowerCase()) || p.description.toLowerCase().includes(search.toLowerCase()))
  );

  const v1 = MOCK_MARKETPLACE.filter(p => p.status === 'V1').length;
  const v2 = MOCK_MARKETPLACE.filter(p => p.status === 'V2').length;
  const v3 = MOCK_MARKETPLACE.filter(p => p.status === 'V3').length;
  const avgRubric = (MOCK_MARKETPLACE.filter(p => p.rubric).reduce((s, p) => s + p.rubric, 0) / MOCK_MARKETPLACE.filter(p => p.rubric).length).toFixed(1);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        <StatCard label="Total Pillars" value={23} color="text-violet-600" />
        <StatCard label="V1 Live" value={v1} color="text-green-600" />
        <StatCard label="V2 Building" value={v2} color="text-blue-600" />
        <StatCard label="Avg Rubric Score" value={avgRubric} sub="across V1 pillars" color="text-amber-600" />
      </div>

      <div className="flex gap-3 flex-wrap">
        <SearchInput value={search} onChange={setSearch} placeholder="Search capabilities…" />
        <div className="flex gap-2">
          {[['all','All (23)'],['V1',`V1 (${v1})`],['V2',`V2 (${v2})`],['V3',`V3 (${v3})`]].map(([k, l]) => (
            <FilterBtn key={k} active={vFilter === k} onClick={() => setVFilter(k)}>{l}</FilterBtn>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {filtered.map(p => (
          <Card key={p.num} className="p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className="text-xs text-gray-400 font-mono w-5">{p.num}</span>
                  <span className="text-sm font-semibold text-gray-900">{p.name}</span>
                  <Badge className={`${VERSION_STYLE[p.status]} text-xs`}>{p.status}</Badge>
                  <Badge className="bg-gray-50 text-gray-500 border border-gray-200 text-xs">Week {p.week}</Badge>
                  {p.skills > 0 && <Badge className="bg-gray-50 text-gray-500 border border-gray-200 text-xs">{p.skills} skills</Badge>}
                </div>
                <p className="text-xs text-gray-500 ml-5">{p.description}</p>
                {p.teams.length > 0 && (
                  <div className="flex gap-1 mt-1.5 ml-5 flex-wrap">
                    {p.teams.map(t => (
                      <span key={t} className="text-xs bg-blue-50 text-blue-600 border border-blue-100 px-1.5 py-0.5 rounded">{t}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className="w-28 shrink-0">
                {p.rubric ? (
                  <>
                    <div className="text-xs text-gray-400 mb-1">Rubric Score</div>
                    <RubricBar score={p.rubric} />
                  </>
                ) : (
                  <span className="text-xs text-gray-400">No rubric yet</span>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

const TABS = [
  { id: 'tasks',       label: 'Task Queue',            icon: '⚡', count: () => MOCK_TASKS.filter(t => t.status === 'running').length },
  { id: 'approvals',   label: 'Approval Inbox',         icon: '⏳', count: () => MOCK_APPROVALS.length },
  { id: 'agents',      label: 'Agent Control Plane',    icon: '🤖', count: () => MOCK_AGENTS.length },
  { id: 'ledger',      label: 'AI Work Ledger',          icon: '📋', count: () => MOCK_LEDGER.length },
  { id: 'evolution',   label: 'Evolution Radar',         icon: '🛰', count: () => MOCK_EVOLUTION.filter(e => e.status === 'new' || e.status === 'pending_approval').length },
  { id: 'marketplace', label: 'Capability Marketplace',  icon: '🏪', count: () => 23 },
];

export default function ARIADashboard() {
  const [activeTab, setActiveTab] = useState('tasks');
  const now = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

  return (
    <div className="min-h-screen bg-gray-50 font-sans">

      {/* ── Header ── */}
      <header className="bg-white border-b border-gray-200 px-6 py-3 sticky top-0 z-40 shadow-sm">
        <div className="flex items-center justify-between max-w-screen-xl mx-auto">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-violet-600 flex items-center justify-center text-white text-sm font-bold shadow-sm">A</div>
              <div>
                <span className="text-gray-900 font-bold text-base tracking-tight">ARIA</span>
                <span className="text-gray-400 text-xs ml-2 hidden sm:inline">Autonomous Role-based Intelligence Agent</span>
              </div>
            </div>
            <div className="flex items-center gap-1.5 px-2.5 py-1 bg-green-50 border border-green-200 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              <span className="text-green-700 text-xs font-medium">Online</span>
            </div>
          </div>

          <div className="flex items-center gap-6 text-xs text-gray-500">
            <div className="flex items-center gap-3 divide-x divide-gray-200">
              <span className="pr-3">Week <strong className="text-gray-800">18</strong> / 30</span>
              <span className="px-3">LangSmith <strong className="text-green-600">connected</strong></span>
              <span className="pl-3">Teams <strong className="text-green-600">connected</strong></span>
            </div>
            <div className="flex gap-3 divide-x divide-gray-200">
              <span className="pr-3">Tasks today: <strong className="text-gray-800">12</strong></span>
              <span className="px-3">Pending: <strong className="text-amber-600">3</strong></span>
              <span className="pl-3 text-gray-400">{now}</span>
            </div>
          </div>
        </div>
      </header>

      {/* ── ROI Banner ── */}
      <div className="bg-violet-50 border-b border-violet-100 px-6 py-2">
        <div className="flex items-center gap-6 text-xs max-w-screen-xl mx-auto flex-wrap">
          <span className="text-violet-700 font-semibold">AI Work Ledger</span>
          <span className="text-gray-600">Tasks completed: <strong className="text-gray-800">847</strong></span>
          <span className="text-gray-600">Hours saved: <strong className="text-green-700">~120h</strong></span>
          <span className="text-gray-600">PRs reviewed (self-dogfooding): <strong className="text-gray-800">47</strong></span>
          <span className="text-gray-600">Review acceptance rate: <strong className="text-blue-700">74%</strong></span>
          <span className="text-gray-600">Bugs caught by ARIA: <strong className="text-orange-600">3</strong></span>
          <span className="ml-auto text-gray-400 italic">All figures are mock data</span>
        </div>
      </div>

      {/* ── Tab Navigation ── */}
      <nav className="bg-white border-b border-gray-200 px-6 sticky top-14 z-30">
        <div className="flex max-w-screen-xl mx-auto overflow-x-auto">
          {TABS.map(tab => {
            const cnt = tab.count();
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
                  activeTab === tab.id
                    ? 'border-violet-600 text-violet-700'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
                {cnt > 0 && (
                  <span className={`px-1.5 py-0.5 rounded-full text-xs font-medium ${
                    activeTab === tab.id ? 'bg-violet-100 text-violet-700' : 'bg-gray-100 text-gray-500'
                  }`}>{cnt}</span>
                )}
              </button>
            );
          })}
        </div>
      </nav>

      {/* ── Panel Content ── */}
      <main className="px-6 py-6 max-w-screen-xl mx-auto">
        {activeTab === 'tasks'       && <TaskQueue />}
        {activeTab === 'approvals'   && <ApprovalInbox />}
        {activeTab === 'agents'      && <AgentControlPlane />}
        {activeTab === 'ledger'      && <AIWorkLedger />}
        {activeTab === 'evolution'   && <EvolutionRadar />}
        {activeTab === 'marketplace' && <CapabilityMarketplace />}
      </main>

      {/* ── Footer ── */}
      <footer className="bg-white border-t border-gray-200 px-6 py-3 mt-8">
        <div className="flex items-center justify-between text-xs text-gray-400 max-w-screen-xl mx-auto">
          <span>ARIA v1.0 · Week 18 of 30 · Built by Kunal Mahajan, Head of AI @ Amar Ujala</span>
          <span>Claude + LangGraph + LangSmith · LangChain · CrewAI patterns</span>
        </div>
      </footer>
    </div>
  );
}
