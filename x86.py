from iced_x86 import Decoder, Formatter, FormatterSyntax, Mnemonic, OpKind, Register, MemorySize

def create_enum_dict(module):
    return {module.__dict__[key]:key.lower() for key in module.__dict__ if isinstance(module.__dict__[key], int)}

MEMSIZE_TO_STRING = create_enum_dict(MemorySize)
REG_TO_STRING = create_enum_dict(Register)


class SetReg:
    def __init__(self, reg, val):
        self.reg = reg
        self.val = val

class Store:
    def __init__(self, mem, val):
        self.mem = mem
        self.val = val

class Copy:
    def __init__(self, instr):
        self.instr = instr
        self.dst = instr.op0
        self.src = instr.op1

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


formatter = Formatter(FormatterSyntax.MASM)
formatter.hex_prefix = "0x"
formatter.hex_suffix = ""
formatter.space_after_operand_separator = True



def operandToStr(instr, i, scope):
    op = formatter.get_instruction_operand(instr, i)
    if op is None:
        return formatter.format_operand(instr, i)

    if instr.op_kind(op) == OpKind.MEMORY and instr.memory_base == Register.EBP and instr.memory_index == Register.NONE:
        disp = instr.memory_displacement
        if disp > 0x7FFFFFFF:
            disp -= 0x100000000
        if s:= scope.stack_access(disp, memsize(instr)):
            return s

    return formatter.format_operand(instr, i)

def toStr(instr, scope):
    s = formatter.format_mnemonic(instr)

    ops = [operandToStr(instr, i, scope) for i in range(formatter.operand_count(instr))]

    if ops:
        s = f"{s:6} {formatter.format_operand_separator(instr).join(ops)}"

    return s

def memsize(instr):
    match instr.memory_size:
        case MemorySize.UINT8 | MemorySize.INT8:
            return 1
        case MemorySize.UINT16 | MemorySize.INT16:
            return 2
        case MemorySize.UINT32 | MemorySize.INT32 | MemorySize.FLOAT32 | MemorySize.DWORD_OFFSET | MemorySize.SEG_PTR32:
            return 4
        case MemorySize.UINT64 | MemorySize.INT64 | MemorySize.FLOAT64 | MemorySize.PACKED64_UINT16:
            return 8
        case MemorySize.UNKNOWN:
            return None
        case _:
            print(f"Unknown memory size: {instr.memory_size} ({MEMSIZE_TO_STRING[instr.memory_size]})")
            #breakpoint()
            raise ValueError(f"Unknown memory size: {instr.memory_size} ({MEMSIZE_TO_STRING[instr.memory_size]})")


def disassemble(data, addr=0):
    decoder = Decoder(32, data, ip=addr)
    instrs = []
    for instr in decoder:
        instrs.append(instr)
    return instrs