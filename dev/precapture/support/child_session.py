"""Post-child source reads only after qualified terminal observation.

This is an offline host policy, not a process observer or camera admission.
The caller must independently validate the native receipt, journal and two
process samples. A success-looking journal alone cannot allow further I/O.
"""
import hashlib


def verify_sources_after_terminal(observation, sources, read):
    """Return False without reading while child completion remains unknown.

    A private caller can end its healthy USB session and later observe the
    same fenced child. This function never retries, launches, cleans files,
    authenticates or authorizes an inverse. It cannot repair an unknown USB
    exchange; those sessions require their own recovery review.
    """
    if not isinstance(observation, dict):
        raise ValueError('Qualified child observation required')
    journal = observation.get('journal')
    if (observation.get('state') not in ('ABSENT', 'ZOMBIE')
            or observation.get('terminal') is not True
            or observation.get('cleanup_allowed') is not True
            or not isinstance(journal, dict)
            or journal.get('has_final_record') is not True):
        return False
    succeeded = (observation.get('success') is True
                 and journal.get('success_record') is True
                 and not observation.get('resolved_refusal')
                 and not journal.get('resolved_refusal_record'))
    # A separately qualified never-sent refusal can finish its own inverse.
    # Keep it distinct from a successful transaction; a negative return alone
    # cannot qualify this path or permit teardown of unresolved resources.
    refused = (observation.get('success') is False
               and journal.get('success_record') is False
               and observation.get('resolved_refusal') is True
               and journal.get('resolved_refusal_record') is True
               and observation.get('request_sent') is False
               and journal.get('request_sent') is False)
    if not (succeeded or refused):
        return False
    if not isinstance(sources, dict) or not sources or not callable(read):
        raise ValueError('Pinned source map and read callback required')
    for name, spec in sources.items():
        if (not isinstance(name, str) or not isinstance(spec, (list, tuple)) or len(spec) != 2
                or not isinstance(spec[0], str) or not spec[0].startswith('/') or '\0' in spec[0]
                or not isinstance(spec[1], str) or len(spec[1]) != 64
                or any(c not in '0123456789abcdef' for c in spec[1])):
            raise ValueError('Malformed source binding')
    for name, (path, expected) in sources.items():
        if hashlib.sha256(read(path)).hexdigest() != expected:
            raise ValueError('Current source differs: ' + name)
    return True
