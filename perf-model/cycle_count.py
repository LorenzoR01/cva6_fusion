# Copyright 2024 Thales Silicon Security
#
# Licensed under the Solderpad Hardware Licence, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.0
# You may obtain a copy of the License at https://solderpad.org/licenses/
#
# Original Author: Côme ALLART - Thales

"""
Performance model of the cva6
"""

import sys
import re

from dataclasses import dataclass
from enum import Enum
from collections import defaultdict

#from matplotlib import pyplot as plt

from isa import Instr, Reg

EventKind = Enum('EventKind', [
    'WAW', 'WAR', 'RAW',
    'BMISS', 'BHIT',
    'STRUCT',
    'issue', 'done', 'commit',
])

def to_signed(value, xlen=32):
    signed = value
    if signed >> (xlen - 1):
        signed -= 1 << xlen
    return signed

class Event:
    """Represents an event on an instruction"""
    def __init__(self, kind, cycle):
        self.kind = kind
        self.cycle = cycle

    def __repr__(self):
        return f"@{self.cycle}: {self.kind}"

class Instruction(Instr):
    """Represents a RISC-V instruction with annotations"""

    def __init__(self, line, address, hex_code, cycle, mnemo):
        Instr.__init__(self, int(hex_code, base=16))
        self.line = line
        self.address = int(address, base=16)
        self.hex_code = hex_code
        self.cycle = cycle
        self.mnemo = mnemo
        self.events = []

    def mnemo_name(self):
        """The name of the instruction (fisrt word of the mnemo)"""
        return self.mnemo.split()[0]

    def next_addr(self):
        """Address of next instruction"""
        return self.address + self.size()

    _ret_regs = [Reg.ra, Reg.t0]

    def is_ret(self):
        "Does CVA6 consider this instruction as a ret?"
        f = self.fields()
        # Strange conditions, no imm check, no rd-discard check
        return self.is_regjump() \
                and f.rs1 in Instruction._ret_regs \
                and (self.is_compressed() or f.rs1 != f.rd)

    def is_call(self):
        "Does CVA6 consider this instruction as a ret?"
        base = self.base()
        f = self.fields()
        return base == 'C.JAL' \
            or base == 'C.J[AL]R/C.MV/C.ADD' and f.name == 'C.JALR' \
            or base in ['JAL', 'JALR'] and f.rd in Instruction._ret_regs

    def __repr__(self):
        return self.mnemo

@dataclass
class Entry:
    """A scoreboard entry"""
    instr: Instruction
    cycles_since_issue = 0
    done: bool = False

    def __repr__(self):
        status = "DONE" if self.done else "WIP "
        addr = f"0x{self.instr.address:08X}"
        return f"{status} {addr}:`{self.instr}` for {self.cycles_since_issue}"

@dataclass
class LastIssue:
    """To store the last issued instruction"""
    instr: Instruction
    issue_cycle: int

class IqLen:
    """Model of the instruction queue with only a size counter"""
    def __init__(self, fetch_size, debug=False):
        self.fetch_size = 4
        while self.fetch_size < fetch_size:
            self.fetch_size <<= 1
        self.debug = debug
        self.len = self.fetch_size
        self.new_fetch = True

    def fetch(self):
        """Fetch bytes"""
        self.len += self.fetch_size
        self._debug(f"fetched {self.fetch_size}, got {self.len}")
        self.new_fetch = True

    def flush(self):
        """Flush instruction queue (bmiss or exception)"""
        self.len = 0
        self._debug(f"flushed, got {self.len}")
        self.new_fetch = False

    def jump(self):
        """Loose a fetch cycle and truncate (jump, branch hit taken)"""
        if self.new_fetch:
            self.len -= self.fetch_size
            self._debug(f"jumping, removed {self.fetch_size}, got {self.len}")
            self.new_fetch = False
        self._truncate()
        self._debug(f"jumped, got {self.len}")

    def has(self, instr):
        """Does the instruction queue have this instruction?"""
        length = self.len
        if self._is_crossword(instr):
            length -= (self.fetch_size - 2)
        self._debug(f"comparing {length} to {instr.size()} ({instr})")
        return length >= instr.size()

    def remove(self, instr):
        """Remove instruction from queue"""
        self.len -= instr.size()
        self._debug(f"removed {instr.size()}, got {self.len}")
        self._truncate(self._addr_index(instr.next_addr()))
        if instr.is_jump():
            self.jump()

    def _addr_index(self, addr):
        return addr & (self.fetch_size - 1)

    def _is_crossword(self, instr):
        is_last = self._addr_index(instr.address) == self.fetch_size - 2
        return is_last and not instr.is_compressed()

    def _truncate(self, index=0):
        occupancy = self.fetch_size - self._addr_index(self.len)
        to_remove = index - occupancy
        if to_remove < 0:
            to_remove += self.fetch_size
        self.len -= to_remove
        self._debug(f"truncated, removed {to_remove}, got {self.len}")

    def _debug(self, message):
        if self.debug:
            print(f"iq: {message}")

class Ras:
    "Return Address Stack"
    def __init__(self, depth=2, debug=False):
        self.depth = depth - 1
        self.stack = []
        self.debug = debug
        self.last_dropped = None

    def push(self, addr):
        "Push an address on the stack, forget oldest entry if full"
        self.stack.append(addr)
        self._debug(f"pushed 0x{addr:08X}")
        if len(self.stack) > self.depth:
            self.stack.pop(0)
            self._debug("overflown")

    def drop(self):
        "Drop an address from the stack"
        self._debug("dropping")
        if len(self.stack) > 0:
            self.last_dropped = self.stack.pop()
        else:
            self.last_dropped = None
            self._debug("was already empty")

    def read(self):
        "Read the top of the stack without modifying it"
        self._debug("reading")
        if self.last_dropped is not None:
            addr = self.last_dropped
            self._debug(f"read 0x{addr:08X}")
            return addr
        self._debug("was empty")
        return None

    def resolve(self, instr):
        "Push or pop depending on the instruction"
        self._debug(f"issuing {instr}")
        if instr.is_ret():
            self._debug("detected ret")
            self.drop()
        if instr.is_call():
            self._debug("detected call")
            self.push(instr.next_addr())

    def _debug(self, message):
        if self.debug:
            print(f"RAS: {message}")

class Bht:
    "Branch History Table"

    @dataclass
    class Entry:
        "A BTB entry"
        valid: bool = False
        sat_counter: int = 0

    def __init__(self, entries=128):
        self.contents = [Bht.Entry() for _ in range(entries)]

    def predict(self, addr):
        "Is the branch taken? None if don't know"
        entry = self.contents[self._index(addr)]
        if entry.valid:
            return entry.sat_counter >= 2
        return None

    def resolve(self, addr, taken):
        "Update branch prediction"
        index = self._index(addr)
        entry = self.contents[index]
        entry.valid = True
        if taken:
            if entry.sat_counter < 3:
                entry.sat_counter += 1
        else:
            if entry.sat_counter > 0:
                entry.sat_counter -= 1

    def _index(self, addr):
        return (addr >> 1) % len(self.contents)

Fu = Enum('Fu', ['ALU', 'MUL', 'BRANCH', 'LDU', 'STU'])

# We have
# - FLU gathering ALU + BRANCH (+ CSR, not significant in CoreMark)
# - LSU for loads and stores
# - FP gathering MUL + second ALU (+ Floating, unused in CoreMark)
# This way we do not have more write-back ports than currently with F

def to_fu(instr):
    if instr.is_branch() or instr.is_regjump():
        return Fu.BRANCH
    if instr.is_muldiv():
        return Fu.MUL
    if instr.is_load():
        return Fu.LDU
    if instr.is_store():
        return Fu.STU
    return Fu.ALU

class FusBusy:
    "Is each functional unit busy"
    def __init__(self, has_alu2 = False):
        self.has_alu2 = has_alu2

        self.alu = False
        self.mul = False
        self.branch = False
        self.ldu = False
        self.stu = False
        self.alu2 = False

        self.issued_mul = False

    def _alu2_ready(self):
        return self.has_alu2 and not self.alu2

    def is_ready(self, fu):
        return {
            Fu.ALU: self._alu2_ready() or not self.alu,
            Fu.MUL: not self.mul,
            Fu.BRANCH: not self.branch,
            Fu.LDU: not self.ldu,
            Fu.STU: not self.stu,
        }[fu]

    def is_ready_for(self, instr):
        return self.is_ready(to_fu(instr))

    def issue(self, instr):
        return {
            Fu.ALU: FusBusy.issue_alu,
            Fu.MUL: FusBusy.issue_mul,
            Fu.BRANCH: FusBusy.issue_branch,
            Fu.LDU: FusBusy.issue_ldu,
            Fu.STU: FusBusy.issue_stu,
        }[to_fu(instr)](self)

    def issue_mul(self):
        self.mul = True
        self.issued_mul = True

    def issue_alu(self):
        if not self._alu2_ready():
            assert not self.alu
            self.alu = True
            self.branch = True
        else:
            self.alu2 = True

    def issue_branch(self):
        self.alu = True
        self.branch = True
        # Stores are not allowed yet
        self.stu = True

    def issue_ldu(self):
        self.ldu = True
        self.stu = True

    def issue_stu(self):
        self.stu = True
        self.ldu = True

    def cycle(self):
        self.alu = self.issued_mul
        self.mul = False
        self.branch = self.issued_mul
        self.ldu = False
        self.stu = False
        self.alu2 = False
        self.issued_mul = False

class Model:
    """Models the scheduling of CVA6"""

    re_instr = re.compile(
        r"([a-z]+)\s+0:\s*0x00000000([0-9a-f]+)\s*\(([0-9a-fx]+)\)\s*@\s*([0-9]+)\s*(.*)"
    )

    def __init__(
            self,
            debug=False,
            issue=1,
            commit=2,
            sb_len=8,
            fetch_size=None,
            has_forwarding=True,
            has_renaming=True):
        self.ras = Ras(debug=debug)
        self.bht = Bht()
        self.instr_queue = []
        self.scoreboard = []
        self.fus = FusBusy(issue > 1)
        self.last_issued = None
        self.last_committed = None
        self.retired = []
        self.sb_len = sb_len
        self.debug = debug
        self.iqlen = IqLen(fetch_size or 4 * issue, debug)
        self.issue_width = issue
        self.commit_width = commit
        self.has_forwarding = has_forwarding
        self.has_renaming = has_renaming
        self.log = []

    def log_event_on(self, instr, kind, cycle):
        """Log an event on the instruction"""
        if self.debug:
            print(f"{instr}: {kind}")
        event = Event(kind, cycle)
        instr.events.append(event)
        self.log.append((event, instr))


    def load_file(self, path):
        """Fill a model from a trace file"""
        with open(path, "r", encoding="utf8") as file:
            for line in [l.strip() for l in file]:
                found = Model.re_instr.search(line)
                if found:
                    address = found.group(2)
                    hex_code = found.group(3)
                    cycle = found.group(4)
                    mnemo = found.group(5)
                    instr = Instruction(line, address, hex_code, cycle, mnemo)
                    self.instr_queue.append(instr)

    
def print_data(name, value, filename=None, ts=24, sep='='):
    "Prints 'name = data' with alignment of the '='"

    spaces = ' ' * (ts - len(name))
    print(f"{name}{spaces} {sep} {value}", file=filename)


def filter_timed_part(all_instructions):
    "Keep only timed part from a trace"
    filtered = []
    # re_csrr_minstret = re.compile(r"^csrr\s+\w\w,\s*minstret$")
    accepting = False
    for instr in all_instructions:
        # if re_csrr_minstret.search(instr.mnemo):
        if "32951073" in instr.hex_code:
            accepting = not accepting
            continue
        if accepting:
            filtered.append(instr)
    return filtered

def count_cycles(retired):
    start = retired[0].cycle
    end = retired[-1].cycle
    return int(end) - int(start)

def print_stats(instructions, input_file):    
    n_instr = len(instructions)
    n_cycles = count_cycles(instructions)
    with open('out.txt', 'a') as f:
        print(f"\n\n{input_file}    QUESTASIM", file=f)
        print_data("cycle number", n_cycles, f)
        print_data("Coremark/MHz", 1000000 / n_cycles, f)
        print_data("instruction number", n_instr, f)

def main(input_file: str):
    "Entry point"

    model = Model(debug=False, issue=2, commit=2)
    model.load_file(input_file)
    print_stats(filter_timed_part(model.instr_queue), input_file)

if __name__ == "__main__":
    main(sys.argv[1])
