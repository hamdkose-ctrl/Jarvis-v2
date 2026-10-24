"""Pure complete/continue/waiting/terminal classification for goal completion.

This module makes no provider/network call, reads no file and mutates nothing.
It only classifies an already-available result into one of four decisions, so
the goal executor's completion gate becomes explicit and independently
testable instead of a bare try/except scattered across several call sites.

First real binding (this PR): the one-shot read-only news/research evidence
completion gate in goal_executor.py (`_check_news_completion`, which delegates
to `news_policy.check_completion`). No RSS subscription, cron, new planner or
GoalState cutover is introduced here.
"""

COMPLETE='complete'
CONTINUE='continue'
WAITING='waiting'
TERMINAL='terminal'

DECISIONS=frozenset({COMPLETE,CONTINUE,WAITING,TERMINAL})


def evaluate_evidence(check,*args,**kwargs):
    """Run an evidence-completion check and classify its outcome.

    `check(*args,**kwargs)` must either return normally (evidence accepted,
    COMPLETE) or raise ValueError (evidence insufficient/invalid, CONTINUE —
    more work is needed, the goal is not done). No other exception type is
    swallowed; it propagates so a real bug is never misclassified as
    "needs more evidence". Never retries the check and never mutates the
    job/goal itself — the caller applies the resulting decision.
    """
    try:
        check(*args,**kwargs)
    except ValueError as exc:
        return {'decision':CONTINUE,'reason':str(exc)}
    return {'decision':COMPLETE,'reason':None}


def job_decision(job):
    """Classify a goal-job's current state into complete/continue/waiting/terminal.

    Read-only: looks only at `job['state']`. This mirrors the existing state
    machine's own vocabulary (done/cancelled/question/approval/anything-else)
    rather than inventing new states; it does not decide transitions.
    """
    state=job.get('state') if isinstance(job,dict) else None
    if state=='done':return COMPLETE
    if state=='cancelled':return TERMINAL
    if state in ('question','approval'):return WAITING
    return CONTINUE
