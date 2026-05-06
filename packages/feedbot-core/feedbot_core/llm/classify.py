"""High-level classify_feedback() — the only entry point most callers need.

Handles: settings lookup, key decryption, monthly-budget check, dispatch,
cost computation, llm_calls insert, and structured logging. Every call is
audited; over-budget calls are recorded with status='over_budget' and skip
the actual API request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_core.llm.base import get_provider
from feedbot_core.llm.crypto import decrypt_key
from feedbot_core.llm.exceptions import LLMConfigError, LLMError, LLMRefusalError
from feedbot_core.llm.pricing import estimate_cost
from feedbot_core.llm.schema import Classification
from feedbot_core.models import LLMCall, ProjectLLMSettings

log = logging.getLogger("feedbot.llm")


@dataclass(slots=True)
class ClassifyOutcome:
    """Result of a classify call: either a Classification or a structured failure."""

    classification: Classification | None
    status: str  # ok | refused | error | over_budget | disabled
    error_text: str | None = None
    usd_cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    provider: str = ""
    model: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.classification is not None


async def _month_to_date_cost(session: AsyncSession, project_id: int) -> float:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    row = await session.execute(
        select(func.coalesce(func.sum(LLMCall.usd_cost), 0.0)).where(
            LLMCall.project_id == project_id, LLMCall.created_at >= start
        )
    )
    return float(row.scalar_one() or 0.0)


async def _audit(
    session: AsyncSession,
    *,
    project_id: int,
    feedback_id: int | None,
    provider: str,
    model: str,
    purpose: str,
    outcome: ClassifyOutcome,
) -> None:
    row = LLMCall(
        project_id=project_id,
        feedback_id=feedback_id,
        provider=provider,
        model=model,
        purpose=purpose,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        total_tokens=outcome.input_tokens + outcome.output_tokens,
        usd_cost=outcome.usd_cost,
        latency_ms=outcome.latency_ms,
        status=outcome.status,
        error_text=outcome.error_text,
    )
    session.add(row)
    await session.flush()
    log.info(
        "llm_call provider=%s model=%s purpose=%s status=%s "
        "in=%d out=%d cost=$%.6f latency_ms=%d project_id=%d feedback_id=%s",
        provider,
        model,
        purpose,
        outcome.status,
        outcome.input_tokens,
        outcome.output_tokens,
        outcome.usd_cost,
        outcome.latency_ms,
        project_id,
        feedback_id,
    )


async def classify_feedback(
    session: AsyncSession,
    *,
    project_id: int,
    text: str,
    feedback_id: int | None = None,
    project_hint: str = "",
    purpose: str = "classify",
) -> ClassifyOutcome:
    """Classify a piece of feedback using the project's configured provider.

    Always returns an outcome (never raises). Always writes one llm_calls row
    when settings exist and are enabled — that includes over-budget and error
    cases so the audit trail is complete.
    """
    settings = await session.get(ProjectLLMSettings, project_id)
    if settings is None or not settings.enabled or settings.provider == "none":
        return ClassifyOutcome(classification=None, status="disabled")
    if settings.encrypted_api_key is None:
        return ClassifyOutcome(classification=None, status="error", error_text="no api key configured")

    # Budget guard.
    if settings.monthly_budget_usd is not None:
        spent = await _month_to_date_cost(session, project_id)
        if spent >= settings.monthly_budget_usd:
            outcome = ClassifyOutcome(
                classification=None,
                status="over_budget",
                error_text=f"monthly budget reached: ${spent:.4f}/${settings.monthly_budget_usd:.2f}",
                provider=settings.provider,
                model=settings.model or "",
            )
            await _audit(
                session,
                project_id=project_id,
                feedback_id=feedback_id,
                provider=settings.provider,
                model=settings.model or "",
                purpose=purpose,
                outcome=outcome,
            )
            return outcome

    try:
        api_key = decrypt_key(settings.encrypted_api_key)
        provider = get_provider(settings.provider, api_key, settings.model)
    except LLMConfigError as exc:
        outcome = ClassifyOutcome(
            classification=None,
            status="error",
            error_text=str(exc),
            provider=settings.provider,
            model=settings.model or "",
        )
        await _audit(
            session,
            project_id=project_id,
            feedback_id=feedback_id,
            provider=settings.provider,
            model=settings.model or "",
            purpose=purpose,
            outcome=outcome,
        )
        return outcome

    try:
        classification, usage = await provider.classify(text=text, project_hint=project_hint)
        cost = estimate_cost(
            settings.provider,
            provider._model,
            usage.input_tokens,
            usage.output_tokens,  # type: ignore[attr-defined]
        )
        outcome = ClassifyOutcome(
            classification=classification,
            status="ok",
            usd_cost=cost,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            provider=settings.provider,
            model=provider._model,  # type: ignore[attr-defined]
        )
    except LLMRefusalError as exc:
        outcome = ClassifyOutcome(
            classification=None,
            status="refused",
            error_text=str(exc),
            provider=settings.provider,
            model=settings.model or "",
        )
    except LLMError as exc:
        outcome = ClassifyOutcome(
            classification=None,
            status="error",
            error_text=str(exc),
            provider=settings.provider,
            model=settings.model or "",
        )

    await _audit(
        session,
        project_id=project_id,
        feedback_id=feedback_id,
        provider=outcome.provider,
        model=outcome.model,
        purpose=purpose,
        outcome=outcome,
    )
    return outcome
