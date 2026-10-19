"""Safe, read-only summaries of recorded task progress."""
from . import privacy


def _empty():
    return dict(title='', done=[], left=[], stopped=False, verified=False)


def _text(value):
    return ' '.join(privacy.redact(value, force=True).split())[:200]


def summarize(job) -> dict:
    """Summarize explicit progress; completed steps alone are not verification."""
    if not isinstance(job, dict):
        return _empty()
    title = job.get('title', job.get('request'))
    state = job.get('state')
    steps = job.get('steps')
    if not isinstance(title, str) or not title.strip() or not isinstance(state, str) or not isinstance(steps, list):
        return _empty()
    done, left = [], []
    for step in steps:
        if not isinstance(step, dict):
            return _empty()
        text = step.get('text', step.get('title', step.get('label')))
        status = step.get('state')
        if not isinstance(text, str) or not text.strip() or not isinstance(status, str):
            return _empty()
        (done if status in ('done', 'completed') else left).append(_text(text))
    stopped = False
    verified = bool(steps) and not left and not stopped and state in ('done', 'completed') and (
        job.get('verified') is True or all(step.get('verified') is True for step in steps))
    return dict(title=_text(title), done=done, left=left, stopped=stopped, verified=verified)
