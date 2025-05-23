from iced_x86 import Decoder, Mnemonic, OpKind, Register

class SetReg:
    def __init__(self, reg, val):
        self.reg = reg
        self.val = val

class Store:
    def __init__(self, mem, val):
        self.mem = mem
        self.val = val

class Load:
    def __init__(self, mem):
        self.mem = mem
        self.src = src

class Local:
    def __init__(self, displacement):
        self.displacement = displacement

class Arg:
    def __init__(self, displacement):
        self.displacement = displacement

class Global:
    def __init__(self, displacement):
        self.displacement = displacement

class Relative:
    def __init__(self, base, displacement):
        self.base = base
        self.displacement = displacement

class Indexed:
    def __init__(self, base, index, scale):
        self.base = base
        self.index = index
        self.scale = scale


def toMem(i):
    # We aren't going to deal with thread local storage
    assert i.memory_segment not in (Register.FS, Register.GS)

    if i.memory_base == Register.EBP:
        assert i.memory_index == Register.NONE
        if i.memory_displacement < 0:
            return Local(i.memory_displacement)
        else:
            return Arg(i.memory_displacement)

def toIR(i):
    if i.mnemonic == Mnemonic.MOV:
        match i.op0.kind, i.op1.kind:
            case OpKind.REGISTER, OpKind.REGISTER:
                return Copy(instr)
            case OpKind.MEMORY, OpKind.REGISTER:
                return Store(instr)
            case OpKind.REGISTER, OpKind.MEMORY:
                return Load(toMem(i))

class Instruction:
    def __init__(self, instr):
        self.instr = instr


def disassemble(data, addr=0):
    decoder = Decoder(32, data, ip=addr)
    instrs = []
    for instr in decoder:
        instrs.append(instr)
    return instrs