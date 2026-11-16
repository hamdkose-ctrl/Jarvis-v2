"""Test actor for a user's EXPLICIT, bound Writer approval.

Use only in post-consent integration tests. Pending and deny paths are
covered separately; production code never imports this helper.
"""
from modules import goal_executor


def run_with_explicit_writer_approval(runtime, request, **kwargs):
    result = goal_executor.run(runtime, request, **kwargs)
    for _ in range(6):
        job = goal_executor.latest(runtime.profile.slug)
        waiting = next((s for s in job.get('steps', ())
                        if s.get('id') == job.get('waiting')
                        and s.get('state') == 'approval'
                        and s.get('tool') == 'writer'), None) if job else None
        if waiting is None:
            break
        # Act as the real user: consume the exact displayed control once.
        result = goal_executor.run(
            runtime, 'hedef onayla', resume=True, approve=True,
            expected_job_id=job['id'],
            expected_control=goal_executor.control_key(job),
        )
    return result
