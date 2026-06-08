"""
Evolution Debate Engine — Week 27

AutoGen-inspired three-agent debate:
  ResearchAgent  — builds the case FOR the proposal
  ScepticAgent   — challenges assumptions and surfaces risks
  ModeratorAgent — weighs arguments, issues structured DebateVerdict

Design choices:
  - Does NOT require pyautogen as a dependency — implements the conversational
    back-and-forth pattern using ARIA's existing langchain-anthropic stack.
  - Graceful no-LLM fallback: when no LLM is configured, runs a deterministic
    heuristic debate so tests never require an API key.
  - Transcript is fully recorded in DebateVerdict.
  - ModeratorAgent auto-rejects proposals that exceed RISK_CEILING.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from aria.evolution.models import (
    RISK_CEILING,
    DebateArgument,
    DebateVerdict,
    EvolutionProposal,
    utc_now,
)

_DEFAULT_ROUNDS = 2


# ── Agent persona prompts ──────────────────────────────────────────────────────

_RESEARCH_SYSTEM = """\
You are ResearchAgent, an expert in AI capability improvement.
Your role: build a focused, evidence-based case FOR the proposal.
Be specific about expected gains. Reference the evidence provided.
Reply in 2–3 concise sentences."""

_SCEPTIC_SYSTEM = """\
You are ScepticAgent, a rigorous risk analyst.
Your role: identify weaknesses, unintended consequences, and missing prerequisites.
Be specific about risks. Do NOT be contrarian without reason.
Reply in 2–3 concise sentences."""

_MODERATOR_SYSTEM = """\
You are ModeratorAgent, an impartial judge.
Your role: weigh the arguments from ResearchAgent and ScepticAgent, then issue a verdict.
Output JSON only — no prose outside the JSON block:
{
  "recommendation": "approve" | "reject" | "defer",
  "confidence": 0.0–1.0,
  "pro_arguments": ["...", ...],
  "con_arguments": ["...", ...],
  "conditions": ["..."]   // requirements before integration; empty if not approving
}"""


@dataclass
class DebateResult:
    verdict: DebateVerdict
    used_llm: bool


class DebateEngine:
    """
    Runs a multi-round debate on an EvolutionProposal.

    Parameters
    ----------
    llm_enabled : bool | None
        If None (default), auto-detects from ANTHROPIC_API_KEY env var.
        Pass False explicitly in tests to force heuristic mode.
    rounds : int
        Number of research ↔ sceptic exchange rounds before moderation.
    """

    def __init__(
        self,
        llm_enabled: Optional[bool] = None,
        rounds: int = _DEFAULT_ROUNDS,
    ) -> None:
        if llm_enabled is None:
            llm_enabled = bool(os.getenv("ANTHROPIC_API_KEY"))
        self._llm_enabled = llm_enabled
        self._rounds = max(1, rounds)

    def debate(self, proposal: EvolutionProposal) -> DebateResult:
        """Run the full debate cycle and return a DebateResult."""
        if proposal.exceeds_risk_ceiling():
            return self._auto_reject_risk_ceiling(proposal)

        if self._llm_enabled:
            return self._llm_debate(proposal)
        return self._heuristic_debate(proposal)

    # ── LLM-backed path ────────────────────────────────────────────────────────

    def _llm_debate(self, proposal: EvolutionProposal) -> DebateResult:
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError:
            return self._heuristic_debate(proposal)

        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", max_tokens=512)  # type: ignore[call-arg]
        transcript: list[DebateArgument] = []
        context_lines: list[str] = [
            f"Proposal: {proposal.title}",
            f"Description: {proposal.description}",
            f"Type: {proposal.evolution_type.value}",
            f"Risk score: {proposal.risk_score}",
            f"Evidence: {'; '.join(proposal.evidence[:3])}",
        ]
        context = "\n".join(context_lines)

        research_args: list[str] = []
        sceptic_args:  list[str] = []

        for rnd in range(1, self._rounds + 1):
            # Research turn
            r_resp = llm.invoke([
                SystemMessage(content=_RESEARCH_SYSTEM),
                HumanMessage(content=f"{context}\n\nRound {rnd}: make your case."),
            ])
            r_text = str(r_resp.content).strip()
            research_args.append(r_text)
            transcript.append(DebateArgument(agent="ResearchAgent", round=rnd, content=r_text))

            # Sceptic turn
            s_resp = llm.invoke([
                SystemMessage(content=_SCEPTIC_SYSTEM),
                HumanMessage(content=f"{context}\n\nResearch says: {r_text}\n\nRound {rnd}: challenge this."),
            ])
            s_text = str(s_resp.content).strip()
            sceptic_args.append(s_text)
            transcript.append(DebateArgument(agent="ScepticAgent", round=rnd, content=s_text))

        # Moderator verdict
        mod_prompt = (
            f"{context}\n\n"
            f"Research arguments:\n" + "\n".join(f"- {a}" for a in research_args) + "\n\n"
            f"Sceptic arguments:\n" + "\n".join(f"- {a}" for a in sceptic_args) + "\n\n"
            "Issue your structured JSON verdict."
        )
        m_resp = llm.invoke([
            SystemMessage(content=_MODERATOR_SYSTEM),
            HumanMessage(content=mod_prompt),
        ])
        verdict = _parse_moderator_output(str(m_resp.content), proposal, transcript, self._rounds)
        return DebateResult(verdict=verdict, used_llm=True)

    # ── Heuristic fallback ─────────────────────────────────────────────────────

    def _heuristic_debate(self, proposal: EvolutionProposal) -> DebateResult:
        """
        Deterministic debate used when no LLM is available.

        Decision rule:
          - risk_score ≤ 0.35 and evidence ≥ 2 → approve (confidence=0.75)
          - risk_score ≤ 0.55 and evidence ≥ 1 → defer  (confidence=0.60)
          - otherwise                            → reject (confidence=0.70)
        """
        transcript: list[DebateArgument] = []
        n_evidence = len(proposal.evidence)

        for rnd in range(1, self._rounds + 1):
            transcript.append(DebateArgument(
                agent="ResearchAgent",
                round=rnd,
                content=(
                    f"The proposal is supported by {n_evidence} evidence item(s). "
                    f"Risk score {proposal.risk_score} is within acceptable range for "
                    f"{proposal.evolution_type.value} evolution."
                ),
            ))
            transcript.append(DebateArgument(
                agent="ScepticAgent",
                round=rnd,
                content=(
                    f"Risk score {proposal.risk_score} vs ceiling "
                    f"{RISK_CEILING.get(proposal.evolution_type.value, 1.0)} must be verified. "
                    "Sandbox evaluation required before integration."
                ),
            ))

        if proposal.risk_score <= 0.35 and n_evidence >= 2:
            rec, conf = "approve", 0.75
            conditions: list[str] = ["sandbox evaluation must pass"]
        elif proposal.risk_score <= 0.55 and n_evidence >= 1:
            rec, conf = "defer", 0.60
            conditions = ["gather more evidence", "sandbox evaluation required"]
        else:
            rec, conf = "reject", 0.70
            conditions = []

        transcript.append(DebateArgument(
            agent="ModeratorAgent",
            round=self._rounds,
            content=f"Heuristic verdict: {rec} (confidence={conf})",
        ))

        verdict = DebateVerdict(
            proposal_id=proposal.proposal_id,
            recommendation=rec,  # type: ignore[arg-type]
            confidence=conf,
            pro_arguments=[a.content for a in transcript if a.agent == "ResearchAgent"],
            con_arguments=[a.content for a in transcript if a.agent == "ScepticAgent"],
            conditions=conditions,
            transcript=transcript,
            debated_at=utc_now(),
            rounds=self._rounds,
        )
        return DebateResult(verdict=verdict, used_llm=False)

    # ── Auto-reject ────────────────────────────────────────────────────────────

    def _auto_reject_risk_ceiling(self, proposal: EvolutionProposal) -> DebateResult:
        ceiling = RISK_CEILING.get(proposal.evolution_type.value, 1.0)
        msg = (
            f"Proposal auto-rejected: risk_score {proposal.risk_score} exceeds "
            f"ceiling {ceiling} for {proposal.evolution_type.value} evolution."
        )
        transcript = [DebateArgument(agent="ModeratorAgent", round=1, content=msg)]
        verdict = DebateVerdict(
            proposal_id=proposal.proposal_id,
            recommendation="reject",
            confidence=1.0,
            pro_arguments=[],
            con_arguments=[msg],
            conditions=[],
            transcript=transcript,
            debated_at=utc_now(),
            rounds=1,
        )
        return DebateResult(verdict=verdict, used_llm=False)


# ── Moderator output parser ────────────────────────────────────────────────────

def _parse_moderator_output(
    raw: str,
    proposal: EvolutionProposal,
    transcript: list[DebateArgument],
    rounds: int,
) -> DebateVerdict:
    """Parse JSON from ModeratorAgent output; fall back to defer on malformed output."""
    import json
    import re

    # Extract first JSON block
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            rec = data.get("recommendation", "defer")
            if rec not in ("approve", "reject", "defer"):
                rec = "defer"
            conf = float(data.get("confidence", 0.6))
            conf = max(0.0, min(1.0, conf))
            transcript.append(DebateArgument(
                agent="ModeratorAgent",
                round=rounds,
                content=raw[:400],
            ))
            return DebateVerdict(
                proposal_id=proposal.proposal_id,
                recommendation=rec,  # type: ignore[arg-type]
                confidence=conf,
                pro_arguments=data.get("pro_arguments", []),
                con_arguments=data.get("con_arguments", []),
                conditions=data.get("conditions", []),
                transcript=transcript,
                debated_at=utc_now(),
                rounds=rounds,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Fallback: defer
    transcript.append(DebateArgument(
        agent="ModeratorAgent",
        round=rounds,
        content="Moderator output could not be parsed — deferring.",
    ))
    return DebateVerdict(
        proposal_id=proposal.proposal_id,
        recommendation="defer",
        confidence=0.5,
        pro_arguments=[],
        con_arguments=["Moderator output unparseable"],
        conditions=["re-run debate after reviewing proposal"],
        transcript=transcript,
        debated_at=utc_now(),
        rounds=rounds,
    )
