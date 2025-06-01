

scope = None


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
    def __init__(self, reg, expr=None):
        self.reg = reg
        self.expr = expr

    def __repr__(self):
        if self.expr:
            return f"Reg({self.reg}, {self.expr})"
        else:
            return f"Reg({self.reg})"

    def __eq__(self, other):
        if isinstance(other, Reg):
            return self.reg == other.reg
        if isinstance(other, str):
            return self.reg == other
        return False

class Const(RValue):
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



class Mem(LValue):
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
        self.sym = scope.stack_access(displacement, size)

    def __repr__(self):
        return f"LocalVar({self.displacement})"

    def as_code(self):
        if not self.sym:
            raise ValueError(f"Local variable at {self.displacement} not found in scope")
        return f"{self.sym}"


class SegOverride(Mem):
    __match_args__ = ("segment", "mem")
    def __init__(self, segment, mem):
        super().__init__(mem.size, mem.base, mem.displacement, mem.index, mem.scale)
        self.mem = mem
        self.segment = segment

    def __repr__(self):
        return f"SegOverride(segment={self.segment}, {super().__repr__()})"

class BinaryOp(RValue):
    __match_args__ = ("op", "left", "right")
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self):
        return f"BinaryOp({self.op}, {self.left}, {self.right})"

class UnaryOp(RValue):
    __match_args__ = ("op", "operand")
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand

    def __repr__(self):
        return f"UnaryOp({self.op}, {self.operand})"

class FunctionRef:
    def __init__(self, fn):
        self.fn = fn

    def __repr__(self):
        return f"FunctionRef({self.fn.name})"

    def __eq__(self, other):
        if isinstance(other, FunctionRef):
            return self.fn == other.fn
        if isinstance(other, str):
            return self.fn.name == other
        if isinstance(other, int):
            return self.fn.address == other
        return False

    def as_code(self):
       return f"{self.fn.name}"

class BasicBlockRef:
    def __init__(self, label):
        self.label = label

    def __repr__(self):
        return f"BasicBlockRef({self.label})"

    def as_code(self):
        return self.label

class SignExtend(LValue):
    def __init__(self, size, expr):
        self.size = size
        self.expr = expr

    def __repr__(self):
        return f"SignExtend(size={self.size}, expr={self.expr})"

class ZeroExtend(LValue):
    def __init__(self, size, expr):
        self.size = size
        self.expr = expr

    def __repr__(self):
        return f"ZeroExtend(size={self.size}, expr={self.expr})"


from iced_x86 import OpKind, Register, Mnemonic, OpAccess, InstructionInfoFactory
info_factory = InstructionInfoFactory()

from x86 import formatter, REG_TO_STRING, memsize

def process_operand(inst, i, state):
    op = formatter.get_instruction_operand(inst, i)
    if op is None:
         return formatter.format_operand(inst, i)
    info = info_factory.info(inst)

    match inst.op_kind(op):
        case OpKind.REGISTER:
            reg = formatter.format_operand(inst, i)
            if info.op_access(op) in (OpAccess.READ, OpAccess.READ_WRITE):
                if expr := state.reg.get(reg):
                    # If the register is already defined in the state, return that expression
                    return expr
            return Reg(reg)

        case OpKind.IMMEDIATE8 | OpKind.IMMEDIATE8_2ND | OpKind.IMMEDIATE16 | OpKind.IMMEDIATE32 | OpKind.IMMEDIATE64 | OpKind.IMMEDIATE8TO16 | OpKind.IMMEDIATE8TO32 | OpKind.IMMEDIATE8TO64:
            imm = inst.immediate(op)
            if imm > 0x7fffffffffffffff:
                imm = imm - 0x10000000000000000
            return Const(imm)

        case OpKind.NEAR_BRANCH32:
            addr = inst.near_branch32
            target = scope.code_access(inst.ip32, addr)
            if not target:
                return formatter.format_operand(inst, i)

            if isinstance(target, str):
                return BasicBlockRef(target)
            if target.address == addr:
                return FunctionRef(target)
            else:
                offset = addr - target.address
                return f"{target.name}+{offset:#x}"


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
            return formatter.format_operand(inst, i)

def regsize(reg):
    if REG_TO_STRING[reg].startswith("E"):
        return 4
    elif REG_TO_STRING[reg].startswith("R"):
        return 8
    else:
        return 2

def modifies_reg(inst, mnenomic, operands):
    info = info_factory.info(inst)

    if len(operands) != inst.op_count:
        return None

    if len(operands) == 2 and inst.op0_kind == OpKind.REGISTER and info.op1_access == OpAccess.READ:
        if info.op0_access == OpAccess.READ:
            # eg cmp/test
            return None
        if info.op0_access == OpAccess.WRITE:
            if inst.mnemonic == Mnemonic.MOV:
                # MOV op, reg
                return operands[0], operands[1]
            if inst.mnemonic == Mnemonic.MOVSX:
                # MOVSX op, reg

                return operands[0], SignExtend(regsize(inst.op0_register), operands[1])
            if inst.mnemonic == Mnemonic.MOVZX:
                # MOVZX op, reg
                return operands[0], ZeroExtend(regsize(inst.op0_register), operands[1])

            breakpoint()
        elif info.op0_access == OpAccess.READ_WRITE:
            # eg Add etc
            return operands[0], BinaryOp(mnenomic, operands[0], operands[1])

    if len(operands) == 1 and inst.op0_kind == OpKind.REGISTER:
        # eg. INC reg, DEC reg
        if info.op0_access == OpAccess.READ_WRITE:
            return operands[0], (mnenomic, operands[0])
        elif info.op0_access == OpAccess.WRITE:
            # eg pop reg
            return operands[0], mnenomic

        return None


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

    def from_inst(inst, state):
        mnemonic = formatter.format_mnemonic(inst)
        operands = [process_operand(inst, i, state) for i in range(formatter.operand_count(inst))]

        modifies = modifies_reg(inst, mnemonic, operands)
        if modifies:
            reg, expr = modifies
            state.reg[reg.reg] = Reg(reg.reg, expr)

        return I(mnemonic, operands, inst=inst)

    def side_effects(self):
        # side effects are instructions that modify memory or any registers other than eax, ecx, edx, esi, edi
        info = info_factory.info(self.inst)
        effects = []
        for mem in info.used_memory():
            if mem.access in (OpAccess.WRITE, OpAccess.READ_WRITE, OpAccess.COND_WRITE, OpAccess.READ_COND_WRITE):
                effects.append("memory")
        for reg in info.used_registers():
            if reg.access in (OpAccess.WRITE, OpAccess.READ_WRITE, OpAccess.COND_WRITE, OpAccess.READ_COND_WRITE):
                if reg.register not in (Register.EAX, Register.ECX, Register.EDX, Register.ESI, Register.EDI):
                    # for now, we won't consider sub registers like AH, AL, etc to be side-effect free
                    effects.append(REG_TO_STRING[reg.register])
        return effects

    def __repr__(self):
        if isinstance(self.operands, tuple):
            return f"I({self.mnenomic} {', '.join(map(str, self.operands))})"

        return f"I({self.mnenomic} {self.operands})"

    def ops(self):
        if isinstance(self.operands, tuple):
            return self.operands
        return (self.operands,)

    def as_code(self):
        ops = []
        for i, op in enumerate(self.ops()):
            try:
                ops.append(op.as_code())
            except:
                ops.append(formatter.format_operand(self.inst, i))

        if ops:
            return f"\t__asm        {self.mnenomic:6} {", ".join(ops)};\n"
        return f"\t__asm        {self.mnenomic};\n"

class State:
    def __init__(self):
        self.reg = {}

def set_scope(_scope):
    global scope
    scope = _scope