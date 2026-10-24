"""Record either reported charge or explicit adequate-power confirmation."""


def require_power(battery=None, *, confirmed=False):
    if confirmed is True:
        return {'confirmed': True}
    if type(battery) is int and 50 <= battery <= 100:
        return {'confirmed': True, 'battery_percent': battery}
    raise ValueError('Confirm adequate continuous power, or report a battery percentage of 50..100')
