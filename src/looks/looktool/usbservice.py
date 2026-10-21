"""One service-first session, shared by FL23, LUT and checkpoint recovery."""


def open_service(transport, expected=None):
    # Session owns model/body checks and cleanup of failed entry. A timeout,
    # disconnect or interrupted authentication must propagate without retry.
    link = transport.Session(expected)
    link.__enter__()
    return link
