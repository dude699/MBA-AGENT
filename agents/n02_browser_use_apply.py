"""
NEXUS v0.2 — Agent N02 · Browser-Use v2.0 Apply Executor
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Browser-Use v2.0 (Jan 2026, MIT, 79K stars) wraps Playwright in an LLM-driven
control loop. We hand it a natural-language goal:

    "Fill this internship application using my profile {profile} and submit."

…and it reasons through the page semantically — no CSS selectors, no XPaths.

This adapter is invoked by N01's AI-MODE branch. While Browser-Use drives the
page, we record the action trace and translate it into a deterministic
Playwright code blob that Skyvern caches (Innovation 2 — First-Apply Code
Crystallisation).

Capabilities of Browser-Use v2.0 used here:
  • +12% accuracy over v1.0 on multi-step form flows
  • Native CAPTCHA hooks → forwards to NEXUS Layer 5 resolver
  • Saved browser profiles (we use Camoufox context instead)
  • Anti-fingerprinting layer on top of Camoufox
  • Marketplace of 1,200+ community automations (portal-specific helpers)
  • Pluggable reasoning model (Gemini / Groq / Cerebras — zero OpenAI)

Heavy imports are guarded so this module loads cleanly on the slim Render
dyno without Browser-Use installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import textwrap
import time
from typing import Any

from core.nexus_config import STACK
from core.stealth_triad import ApplyContext, ApplyOutcome

log = logging.getLogger("nexus.n02_browser_use")

# ─── Heavy import guard ───────────────────────────────────────────────────
try:
    from browser_use import Agent as BUAgent              # type: ignore
    from browser_use import Browser as BUBrowser          # type: ignore
    from browser_use.agent.views import ActionResult      # type: ignore
    BROWSER_USE_AVAILABLE = True
except Exception:                                          # noqa: BLE001
    BUAgent = None                                         # type: ignore
    BUBrowser = None                                       # type: ignore
    BROWSER_USE_AVAILABLE = False


# ────────────────────────────────────────────────────────────────────────────
# LLM provider selector (zero OpenAI — Innovation 2 in the doc)
# ────────────────────────────────────────────────────────────────────────────
def _build_llm(model_handle: str):
    """
    Resolve a model handle like 'groq/llama-3.3-70b-versatile' or
    'gemini/gemini-2.5-flash' or 'cerebras/llama-3.3-70b' to a Browser-Use
    compatible chat model.
    """
    if not BROWSER_USE_AVAILABLE:
        return None
    provider, _, model = model_handle.partition("/")
    if provider == "groq":
        from browser_use.llm import ChatGroq               # type: ignore
        return ChatGroq(model=model or STACK.groq_llm)
    if provider == "gemini":
        from browser_use.llm import ChatGoogle             # type: ignore
        return ChatGoogle(model=model or STACK.gemini_flash)
    if provider == "cerebras":
        from browser_use.llm import ChatCerebras           # type: ignore
        return ChatCerebras(model=model or STACK.cerebras_llm)
    raise ValueError(f"unknown provider in model_handle={model_handle!r}")


# ────────────────────────────────────────────────────────────────────────────
# Goal builder — maps an ApplyContext to a natural-language Browser-Use task
# ────────────────────────────────────────────────────────────────────────────
def _build_apply_goal(ctx: ApplyContext) -> str:
    profile_summary = json.dumps({
        "name":         ctx.profile.get("name"),
        "email":        ctx.profile.get("email"),
        "phone":        ctx.profile.get("phone"),
        "education":    ctx.profile.get("education"),
        "skills":       ctx.profile.get("skills"),
        "min_stipend":  ctx.profile.get("min_stipend"),
    }, ensure_ascii=False)

    custom_answers = "\n".join(
        f"  • Q: {q!r} → A: {a!r}" for q, a in ctx.answers.items()
    ) or "  (no pre-generated answers — generate inline if asked)"

    return textwrap.dedent(f"""
    You are NEXUS, an autonomous job application agent.
    Goal: Apply to the job at {ctx.job_url} on portal {ctx.portal!r}.

    Use this profile to fill any required fields:
    {profile_summary}

    Resume file path (upload when asked): {ctx.resume_path or '(none — skip resume upload only if optional)'}

    Pre-generated answers for known custom questions:
    {custom_answers}

    Rules:
      1. Never click any button labelled "Sign in" or "Login" — the session
         cookies are already injected.
      2. If you encounter a CAPTCHA, return early with status CAPTCHA_NEEDED.
      3. If the portal blocks you with a "verify you are human" full-page
         interstitial, return PORTAL_BLOCKED.
      4. After submission, look for an explicit confirmation
         ("Application submitted", "Thanks for applying", "We'll get back…").
         Only then return SUCCESS.
      5. Do NOT submit duplicate applications — if the page already says
         "You've applied", return SUCCESS without re-submitting.
      6. Mention {ctx.profile.get('name', 'the applicant')} by name only
         when the form requires it.

    Final output: a single JSON object: {{"status": "SUCCESS|FAILED|CAPTCHA_NEEDED|PORTAL_BLOCKED",
                                          "evidence": "<short text>"}}
    """).strip()


# ────────────────────────────────────────────────────────────────────────────
# Action-trace → Playwright code crystallisation (Innovation 2)
# ────────────────────────────────────────────────────────────────────────────
_CODE_PREAMBLE = '''\
"""Auto-generated Playwright code blob crystallised by NEXUS v0.2.
Replays the successful Browser-Use flow without any LLM call.
Function signature: async def run(page, ctx) -> str  ('SUCCESS' | 'FAILED' | ...).
"""
async def run(page, ctx):
    profile = ctx["profile"]
    answers = ctx.get("answers", {})
'''


def _crystallise_actions_to_code(action_trace: list[dict[str, Any]]) -> str:
    """
    Best-effort translation of a Browser-Use action trace into deterministic
    Playwright code.  We support the core action verbs Browser-Use emits:
        navigate, click, type, select, upload, scroll, wait, done.

    Anything we can't translate is dropped — the next AI-mode run will
    re-crystallise from scratch (Skyvern's own self-healing).
    """
    lines: list[str] = [_CODE_PREAMBLE.rstrip()]
    indent = "    "

    for step in action_trace:
        verb = step.get("action") or step.get("type")
        if verb == "navigate":
            url = step["url"]
            lines.append(f'{indent}await page.goto({url!r}, wait_until="domcontentloaded")')
        elif verb == "click":
            sel = step.get("selector")
            if sel:
                lines.append(f'{indent}await page.locator({sel!r}).click()')
            elif "role" in step and "name" in step:
                lines.append(
                    f'{indent}await page.get_by_role({step["role"]!r}, '
                    f'name={step["name"]!r}).click()'
                )
        elif verb == "type":
            sel = step.get("selector")
            value_key = step.get("value_from_profile")
            value_lit = step.get("value")
            if sel and value_key:
                lines.append(
                    f'{indent}await page.locator({sel!r}).fill('
                    f'str(profile.get({value_key!r}, "")))'
                )
            elif sel and value_lit is not None:
                lines.append(f'{indent}await page.locator({sel!r}).fill({value_lit!r})')
        elif verb == "select":
            sel = step.get("selector")
            value = step.get("value")
            if sel and value is not None:
                lines.append(
                    f'{indent}await page.locator({sel!r}).select_option({value!r})'
                )
        elif verb == "upload":
            sel = step.get("selector")
            if sel:
                lines.append(
                    f'{indent}await page.locator({sel!r}).set_input_files('
                    f'ctx.get("resume_path"))'
                )
        elif verb == "scroll":
            y = step.get("y", 400)
            lines.append(f'{indent}await page.mouse.wheel(0, {int(y)})')
        elif verb == "wait":
            ms = int(step.get("ms", 800))
            lines.append(f'{indent}await page.wait_for_timeout({ms})')
        elif verb == "done":
            status = step.get("status", "SUCCESS")
            lines.append(f'{indent}return {status!r}')
            break

    if not any(line.strip().startswith("return ") for line in lines):
        lines.append(f'{indent}return "SUCCESS"')

    return "\n".join(lines) + "\n"


# ────────────────────────────────────────────────────────────────────────────
# Public entry — called by N01 AI-MODE
# ────────────────────────────────────────────────────────────────────────────
async def run_browser_use_apply(
    page,
    ctx: ApplyContext,
    ai_model: str = "groq/llama-3.3-70b-versatile",
    max_steps: int = 25,
) -> tuple[ApplyOutcome, str]:
    """
    Drives `page` with Browser-Use to complete the apply. Returns:
        (ApplyOutcome, generated_playwright_code_blob_or_empty_str)

    The empty-string code blob signals to the orchestrator that nothing
    cacheable was produced (e.g. failure / CAPTCHA / blocked).
    """
    if not BROWSER_USE_AVAILABLE:
        log.warning("n02.unavailable portal=%s — browser-use not installed", ctx.portal)
        return ApplyOutcome.FAILED, ""

    llm = _build_llm(ai_model)
    goal = _build_apply_goal(ctx)
    log.info("n02.start portal=%s job=%s model=%s", ctx.portal, ctx.job_id, ai_model)

    # Action trace recorder — Browser-Use exposes a callback per agent step
    action_trace: list[dict[str, Any]] = []

    async def _on_step(step):                                  # type: ignore[no-redef]
        try:
            # `step` shape (Browser-Use v2.0): { action, selector?, url?, ... }
            action_trace.append(step.dict() if hasattr(step, "dict") else dict(step))
        except Exception:                                      # noqa: BLE001
            pass

    try:
        # Browser-Use v2.0 accepts an existing Playwright page so we can keep
        # the Camoufox context active.
        agent = BUAgent(
            task=goal,
            llm=llm,
            page=page,
            max_steps=max_steps,
            on_step_end=_on_step,
            use_vision=True,
        )
        result: ActionResult = await agent.run()                # type: ignore

        # Browser-Use returns the agent's final structured output.
        final = result.final_output if hasattr(result, "final_output") else None
        status_str = "FAILED"
        if isinstance(final, dict):
            status_str = str(final.get("status", "FAILED")).upper()
        elif isinstance(final, str):
            try:
                status_str = str(json.loads(final).get("status", "FAILED")).upper()
            except Exception:
                pass

        outcome = {
            "SUCCESS":         ApplyOutcome.SUCCESS,
            "FAILED":          ApplyOutcome.FAILED,
            "CAPTCHA_NEEDED":  ApplyOutcome.CAPTCHA_NEEDED,
            "PORTAL_BLOCKED":  ApplyOutcome.PORTAL_BLOCKED,
        }.get(status_str, ApplyOutcome.FAILED)

        # Crystallise only on confirmed success — never cache a flow that
        # ended in failure or CAPTCHA escalation.
        code_blob = (
            _crystallise_actions_to_code(action_trace)
            if outcome == ApplyOutcome.SUCCESS and action_trace
            else ""
        )

        log.info(
            "n02.done portal=%s job=%s outcome=%s steps=%s crystallised=%s",
            ctx.portal, ctx.job_id, outcome.value, len(action_trace), bool(code_blob),
        )
        return outcome, code_blob

    except Exception as e:                                     # noqa: BLE001
        log.exception("n02.crash portal=%s err=%s", ctx.portal, e)
        return ApplyOutcome.FAILED, ""


__all__ = [
    "run_browser_use_apply",
    "BROWSER_USE_AVAILABLE",
    "_build_apply_goal",                # exported for tests
    "_crystallise_actions_to_code",     # exported for tests
]
