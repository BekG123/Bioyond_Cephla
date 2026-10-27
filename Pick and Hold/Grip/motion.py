"""Compatibility refusal only. Grip control has been removed."""


def seq_grip(run, svc, params):
    # Legacy workflows must fail closed, rather than continue to lift/transfer.
    run.state = 'error'
    message = 'Grip control was removed. Replacement is not implemented.'
    run.say(message, 'warn')
    return dict(ok=False, gripped=False, grip_unavailable=True, error=message)
