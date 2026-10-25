"""Original release notification with explicit synthetic CPU/lock ownership.

Acquisition, context selection, unlock and uncontended reacquisition execute
original instructions. Waits, messages, diagnostics and clocks stop before
execution. No live task ownership or physical completion is supplied.
"""
import struct

from unicorn import arm_const as R
from .capture_native import BASE, STACK, STOP, words

CONTEXT, LOCK = 0x31000000, 0x31001000
CPU_TABLE, LOCK_TABLE = 0x1b30708, 0x1b29194
REGIONS = ((CONTEXT, 8192), (CPU_TABLE & ~4095, 4096), (LOCK_TABLE & ~4095, 4096))
SCENARIOS = ('default_category', 'category_one', 'busy', 'wrong_owner', 'contended_reacquire')
BOUNDARIES = (0xb160da, 0x45d204, 0x45cfac, 0x4fdd70, 0x4e64fc, 0x4e655c)


def prepare(native, scenario):
    if scenario not in SCENARIOS:
        raise ValueError('Unsupported synthetic notification scenario')
    u = native.u
    put = lambda at, value: u.mem_write(at, words(value))
    assert u.cpr_read(15, 0, 0, 0, 5, 1, False) & 3 == 0
    u.mem_write(CONTEXT, bytes(8192))
    put(CPU_TABLE, CONTEXT)
    put(LOCK_TABLE+107*4, LOCK)
    put(LOCK+8, 0x55)
    u.reg_write(R.UC_ARM_REG_CPSR, 0x13)
    got = native.run(0x4e66f0, (), [(R.UC_ARM_REG_R0, 0x6c),
        (R.UC_ARM_REG_SP, STACK+0x8000), (R.UC_ARM_REG_LR, STOP | 1)], thumb=False)
    assert got['address'] == STOP and u.reg_read(R.UC_ARM_REG_R0) == 0
    assert int.from_bytes(u.mem_read(CONTEXT+0x10, 4), 'little') == 0x6c
    assert int.from_bytes(u.mem_read(LOCK, 4), 'little') == 1
    assert u.reg_read(R.UC_ARM_REG_CPSR) & 0x80
    # Runtime values below are stated test inputs. No category-changing native
    # service is called or claimed, and no camera configuration is inferred.
    if scenario == 'category_one':
        selected = int.from_bytes(u.mem_read(0x1a8c0d8, 4), 'little')
        u.mem_write(selected, struct.pack('<H', 1))
    if scenario == 'busy':
        u.mem_write(0x1b200f5, b'\x01')
    if scenario == 'wrong_owner':
        put(CONTEXT+0x10, 0)


def finish(native, scenario):
    u = native.u
    get = lambda at: int.from_bytes(u.mem_read(at, 4), 'little')
    if scenario == 'contended_reacquire':
        got = native.run(0xb1746c, (*BOUNDARIES, 0xb1788a))
        assert got['address'] == BASE+0xb1788a
        assert get(CONTEXT+0x10) == get(LOCK) == 0
        assert not u.reg_read(R.UC_ARM_REG_CPSR) & 0x80
        # Explicit adversarial interleaving while the original path is unlocked.
        # No real contender/task or successful acquisition is manufactured.
        u.mem_write(LOCK, words(1))
        u.mem_write(LOCK+8, words(0x55))
        got = native.run(0xb1788a, BOUNDARIES)
    else:
        got = native.run(0xb1746c, BOUNDARIES)
    boundary = got['address']-BASE
    expected = dict(default_category=0xb160da, category_one=0x45d204,
        busy=0x45cfac, wrong_owner=0x4fdd70, contended_reacquire=0x4e64fc)[scenario]
    assert boundary == expected, (scenario, hex(boundary))
    busy = bytes(u.mem_read(0x1b200f5, 1))[0]
    assert busy == 1
    held = get(CONTEXT+0x10)
    irq = bool(u.reg_read(R.UC_ARM_REG_CPSR) & 0x80)
    if scenario == 'default_category':
        assert held == 0x6c and get(LOCK) == 1 and irq
    elif scenario == 'wrong_owner':
        assert held == 0 and get(LOCK) == 1 and irq
        assert got['args'][2] == 0xffffffe4
    elif scenario == 'contended_reacquire':
        assert held == 0 and get(LOCK) == 1 and not irq
    else:
        assert held == get(LOCK) == 0 and not irq
    result = dict(scenario=scenario, stopped_before_file=hex(boundary),
        arguments_raw=got['args'], busy_flag=busy, held_lock_id=held,
        lock_word=get(LOCK), irq_masked=irq,
        native_try_lock_and_context_query_executed=True,
        native_unlock_rejected=scenario == 'wrong_owner',
        native_unlock_executed=True,
        native_uncontended_reacquire_executed=scenario == 'default_category',
        adversarial_reacquire_contention=scenario == 'contended_reacquire',
        stopped_before_blocking_WFE=scenario == 'contended_reacquire',
        message_allocation_or_send_executed=False, scheduler_wait_executed=False,
        timer_executed=False, notifier_returned=False, physical_completion_verified=False)
    if scenario == 'category_one':
        assert got['args'][0] == 0x92a20524 and got['args'][2:] == [16, 1]
    if scenario == 'busy':
        assert got['args'][0] == 0x910041
        assert struct.unpack('<10I', u.mem_read(got['args'][1], 40)) == (40, 0, 0, 0, 0, 0, 10, 0, 0, 0)
    return result
