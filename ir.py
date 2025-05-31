


class Block:
    pass

class BasicBlock:
    pass

class Expression:
    pass

class LValue(Expression):
    def __init__(self):
        pass

class RValue(LValue):
    pass

class Load(LValue):
    pass

class Statement:
    pass

class Store(Statement):
    def __init__(self, lvalue, rvalue):
        self.lvalue = lvalue
        self.rvalue = rvalue


class Reg(Expression):
    def __init__(self, reg):
        self.reg = reg

    def __repr__(self):
        return f"Register({self.reg})"

    def __eq__(self, other):
        if isinstance(other, Reg):
            return self.reg == other.reg
        if isinstance(other, str):
            return self.reg == other
        return False

class Const(LValue):
    __match_args__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Const({self.value})"

    def __eq__(self, other):
        if isinstance(other, Const):
            return self.value == other.value
        if isinstance(other, int):
            return self.value == other
        return False



class Mem(RValue):
    __match_args__ = ("size")
    def __init__(self, size, base, displacement=0, index=None, scale=1):
        self.size = size
        self.base = base
        self.index = index
        self.scale = scale
        self.displacement = displacement

    def __repr__(self):
        return f"Mem(size={self.size} base={self.base}, displacement={self.displacement})"

class MemBase(Mem):
    __match_args__ = ("base", "size")
    def __init__(self, size, base):
        super().__init__(size, base)

    def __repr__(self):
        return f"MemBase(size={self.size}, base={self.base})"

class MemDisp(Mem):
    __match_args__ = ("displacement", "size")
    def __init__(self, size, displacement):
        super().__init__(size, None, displacement)

    def __repr__(self):
        return f"MemDisp(size={self.size}, displacement={self.displacement})"

class MemBaseDisp(Mem):
    __match_args__ = ("base", "displacement", "size")
    def __init__(self, size, base, displacement):
        super().__init__(size, base, displacement)

    def __repr__(self):
        return f"MemBaseDisp(size={self.size}, base={self.base}, displacement={self.displacement})"

class MemComplex(Mem):
    def __init__(self, size, base, index, scale, displacement=0):
        super().__init__(size, base, displacement, index, scale)

    def __repr__(self):
        return f"MemIndexed(size={self.size}, base={self.base}, index={self.index}, scale={self.scale}, displacement={self.displacement})"


class LocalVar(Mem):
    def __init__(self, size, displacement):
        super().__init__(size, base="EBP", displacement=displacement)

    def __repr__(self):
        return f"LocalVar({self.displacement})"

class SegOverride(Mem):
    __match_args__ = ("segment", "mem")
    def __init__(self, segment, mem):
        super().__init__(mem.size, mem.base, mem.displacement, mem.index, mem.scale)
        self.mem = mem
        self.segment = segment

    def __repr__(self):
        return f"SegOverride(segment={self.segment}, {super().__repr__()})"

from iced_x86 import OpKind, Register, MemorySize
from x86 import formatter, REG_TO_STRING, memsize

def process_operand(inst, i):
    op = formatter.get_instruction_operand(inst, i)
    if op is None:
         return formatter.format_operand(inst, i)

    match inst.op_kind(op):
        case OpKind.REGISTER:
            reg = formatter.format_operand(inst, i)
            return Reg(reg)

        case OpKind.IMMEDIATE8 | OpKind.IMMEDIATE8_2ND | OpKind.IMMEDIATE16 | OpKind.IMMEDIATE32 | OpKind.IMMEDIATE64 | OpKind.IMMEDIATE8TO16 | OpKind.IMMEDIATE8TO32 | OpKind.IMMEDIATE8TO64:
            imm = inst.immediate(op)
            return Const(imm)

        case OpKind.NEAR_BRANCH16 | OpKind.NEAR_BRANCH32 | OpKind.NEAR_BRANCH64 | OpKind.FAR_BRANCH16 | OpKind.FAR_BRANCH32:
            return formatter.format_operand(inst, i)

        case OpKind.MEMORY if inst.memory_base == Register.EBP and inst.memory_segment == Register.SS and inst.memory_index == Register.NONE:
            disp = inst.memory_displacement
            if disp > 0x7FFFFFFF:
                disp -= 0x100000000
            size = memsize(inst)

            # todo: handle indexed ebp
            assert inst.memory_index == Register.NONE
            return LocalVar(size, disp)

        case OpKind.MEMORY if inst.memory_base not in (Register.FS, Register.GS):
            disp = inst.memory_displacement
            if disp > 0x7FFFFFFF:
                disp -= 0x100000000

            base = REG_TO_STRING[inst.memory_base] if inst.memory_base != Register.NONE else None
            index = REG_TO_STRING[inst.memory_index] if inst.memory_index != Register.NONE else None
            scale = inst.memory_index_scale
            try:
                size = memsize(inst)
            except ValueError:
                return formatter.format_operand(inst, i)

            if index:
                mem = MemComplex(size, base, index, scale, disp)
            elif not base and not index:
                mem = MemDisp(size,  disp)
            elif disp:
                mem = MemBaseDisp(size, base, disp)
            else:
                mem = MemBase(size, base)

            if inst.memory_segment != Register.DS:
                mem.segment = REG_TO_STRING[inst.memory_segment]
                return SegOverride(mem.segment, mem)
            return mem


        case _:
            breakpoint()


class I:
    __match_args__ = ("mnenomic", "operands")
    def __init__(self, mnenomic, operands, inst=None):
        self.mnenomic = mnenomic
        match operands:
            case [op]:
                operands = op
            case ops:
                operands = tuple(ops)
        self.operands = operands
        self.inst = inst

    def from_inst(inst):
        mnemonic = formatter.format_mnemonic(inst)

        operands = [process_operand(inst, i) for i in range(formatter.operand_count(inst))]

        return I(mnemonic, operands, inst=inst)

    def __repr__(self):
        if isinstance(self.operands, tuple):
            return f"I({self.mnenomic} {', '.join(map(str, self.operands))})"

        return f"I({self.mnenomic} {self.operands})"
