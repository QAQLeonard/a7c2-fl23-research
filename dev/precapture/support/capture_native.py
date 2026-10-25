"""Shared original capture-object fixture; synthetic objects, no device I/O.

External calls stop before execution. Separate post-call slices never supply
successful locks, scheduling, clocks, image allocation, save or release.
Complete source admission remains the caller's responsibility, as before.
"""
import struct
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R8,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

BASE, OWNER, WIRE, STACK, STOP = 0x108000, 0x30000000, 0x30002000, 0x40000000, 0x20000000
DEBUG = 0x1a533a4


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


class NativeCapture:
    def __init__(self, cp):
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        u.mem_map(BASE, (len(cp) + 4095) & ~4095)
        u.mem_write(BASE, cp)
        for at, size in [(OWNER, 0x10000), (STACK, 0x10000), (STOP, 4096),
                          (DEBUG & ~4095, 4096)]:
            u.mem_map(at, size)
        self.stops, self.observed = set(), []
        # External/native service boundaries never execute in this audit.
        self.external = {BASE + n for n in (0xa3c516, 0xa3c57a, 0x69f488,
            0x9dc38e, 0x9dc4de, 0x9dbcca, 0x9dbbfa, 0x45d204, 0x45cb38, 0xae133a,
            0xa3b61c)}
        def trace(cpu, at, size, user):
            if at in self.stops or at in self.external:
                self.observed.append(dict(address=at, args=[cpu.reg_read(r) for r in
                    (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)], executed=False))
                cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE, trace)

    def run(self, start, stops, inputs=(), *, instruction_budget=15000):
        if type(instruction_budget) is not int or not 1 <= instruction_budget <= 500000:
            raise ValueError('Invalid bounded original-instruction budget')
        u = self.u
        for reg, value in inputs:
            u.reg_write(reg, value)
        self.stops = {BASE + n for n in stops} | {STOP}
        self.observed.clear()
        try:
            u.emu_start(BASE + start | 1, 0xffffffff, count=instruction_budget)
        except UcError as error:
            raise RuntimeError('Original execution failed at ' + hex(u.reg_read(UC_ARM_REG_PC)) +
                ' args=' + repr([hex(u.reg_read(r)) for r in
                    (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)])) from error
        assert len(self.observed) == 1
        got = self.observed[0]
        assert u.reg_read(UC_ARM_REG_PC) == got['address']
        assert got['address'] in self.stops, 'Unexpected external boundary: ' + hex(got['address'])
        return got

    def call(self, start, values):
        inputs = list(zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), values))
        inputs += [(UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)]
        return self.run(start, (), inputs)

    def fixture(self):
        u = self.u
        u.mem_write(OWNER, bytes(0x1000))  # Native global normally follows BSS clear.
        u.mem_write(OWNER + 0x1000, bytes([0xa5]) * 64)
        self.call(0x9da010, [OWNER])  # Whole original constructor, including native ARM bzero.
        # Separate original pointer/init slice AFTER backup/timer binding.
        # The omitted binding reads hardware/configuration; no return is supplied.
        self.run(0x9d94be, (0x9d9556,), [(UC_ARM_REG_R4, OWNER),
            (UC_ARM_REG_R8, OWNER + 0x2ac), (UC_ARM_REG_SP, STACK + 0x8000)])
        assert struct.unpack('<I', u.mem_read(OWNER + 0x15c, 4))[0] == BASE + 0x350559
        assert struct.unpack('<3I', u.mem_read(OWNER + 0x27c, 12)) == (
            OWNER + 0x158, OWNER + 0x298, OWNER + 0x2ac)
        self.call(0x9d940e, [OWNER + 0x298, 0x4000000])
        assert struct.unpack('<I', u.mem_read(OWNER + 0x2a0, 4))[0] == 0x4000000
        # Explicit pre-existing synthetic timer metadata, rather than the
        # omitted configuration reader's return. It contains no pixel buffer.
        u.mem_write(OWNER + 0x5000, words(2, 0, 0, 0))
        u.mem_write(OWNER + 0x2b0, words(OWNER + 0x5000))
        self.call(0x9d89e6, [OWNER + 0x2ac])
        assert bytes(u.mem_read(OWNER + 0x1000, 64)) == bytes([0xa5]) * 64
        return bytes(u.mem_read(OWNER, 0x1000))


