from access import ArrayAccess
from base_types import ScaleExpr

scope = None

class Expression:
    inst = None

    def is_known(self):
        return True

    def as_code(self):
        raise ValueError(f"Can't convert {self.__class__.__name__} {self} to code")

    def as_asm(self):
        return self.as_code()

    def visit(self, fn):
        fn(self)
        for expr in self.__dict__.values():
            if isinstance(expr, Expression):
                expr.visit(fn)

class LValue(Expression):
    def __init__(self):
        pass

    def as_rvalue(self):
        # LValues can be used as RValues
        return self.as_lvalue()

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
    def __init__(self, reg, expr=None, inst=None):
        self.reg = reg
        self.expr = expr
        self.inst = inst # The instruction that wrote to this register

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

    def as_lvalue(self):
        if not self.expr:
            raise ValueError("Cannot convert Reg to LValue without an expression")
        return self.expr.as_lvalue()

    def as_rvalue(self):
        if not self.expr:
            raise ValueError("Cannot convert Reg to RValue without an expression")
        return self.expr.as_rvalue()

    def is_known(self):
        if self.expr:
            return self.expr.is_known()
        return False

    def as_asm(self):
        return self.reg

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

    def as_rvalue(self):
        return f"{self.value:#x}"

class Addr(LValue):
    # constant address
    def __init__(self, addr):
        self.addr = addr
        self.scope = scope

    def __repr__(self):
        return f"Addr({self.addr})"

class Displace(LValue):
    # adds a displacement to an address
    def __init__(self, expr, displacement):
        self.addr = expr
        self.disp = displacement
        self.scope = scope

    def __repr__(self):
        return f"Displace({self.addr}, {self.disp})"

class Index(LValue):
    # adds a scaled index to an address
    def __init__(self, base_expr, index_expr, scale):
        self.base_expr = base_expr
        self.index_expr = index_expr
        self.scale = scale
        self.scope = scope

    def __repr__(self):
        return f"Index({self.base_expr}, {self.index_expr}, {self.scale})"

class Mem(LValue):
    __match_args__ = ("size", "expr")
    def __init__(self, size, base, displacement=0, index=None, scale=1):

        self.scope = scope
        self.size = size
        self.base = base
        self.index = index
        self.scale = scale
        self.disp = displacement
        self.expr = None
        expr = None
        if base:
            if not base.expr:
                return
            expr = base.expr
        if index:
            if not index.expr:
                return
            expr = Index(expr, index.expr, scale)
        if displacement:
            if not expr:
                expr = Addr(self.disp)
            else:
                expr = Displace(expr, displacement)
        self.expr = expr

    def __repr__(self):
        if self.expr:
            return f"Mem{self.size}({self.expr})"
        return f"Mem(size={self.size} base={self.base}, displacement={self.disp})"

    def as_lvalue(self):
        if not self.expr:
            raise ValueError("Cannot convert Mem to LValue without an expression")


        if self.base:
            access = self.base.expr.as_lvalue()
            offset = self.disp
            if self.index:
                offset = f"{self.index.expr.as_rvalue()} * {self.scale} + {offset:x}"
            return access.deref(offset, self.size)

        elif self.disp and not self.index:
            return self.scope.data_access(self.disp, self.size)

        raise ValueError("Cannot convert indexed Mem to LValue")

    def as_asm(self):
        access = None
        if self.disp:
            access = self.scope.data_access(self.disp, self.size)

        if not access:
            raise ValueError(f"Memory at disp {self.disp} not found in scope")

        s = ""
        if self.base:
            s += self.base.as_asm()
        if self.index:
            s += "+" if s else ""
            s += self.index.as_asm()
            if self.scale != 1:
                s += f"*{self.scale}"
        if self.disp and not access:
            s += "-" if self.disp < 0 else ""
            s += "+" if self.disp >= 0 or s else ""
            s += f"0x{self.disp:X}"

        if s and isinstance(access, ArrayAccess):
            if access.index == 0:
                # remove extra level of indirection
                access = access.lvalue
            else:
                # todo: need to take address of lvalue
                pass

        try:
            a = access.as_asm()
        except AttributeError:
            a = str(access)

        if access and s:
            return f"{a}[{s}]"
        if access:
            return a

        if self.size:
            SIZES = ["<{0} ptr>", "byte ptr", "word ptr", "{3} ptr", "dword ptr", "{5} ptr", "{6} ptr", "{7} ptr", "qword ptr"]
            return f"{SIZES[self.size]} [{s}]"
        return f"[{s}]"

class MemBase(Mem):
    __match_args__ = ("base", "size")
    def __init__(self, size, base):
        super().__init__(size, base)

    def __repr__(self):
        if self.expr:
            return Mem.__repr__(self)
        return f"MemBase(size={self.size}, base={self.base})"

class MemDisp(Mem):
    __match_args__ = ("disp", "size")
    def __init__(self, size, displacement):
        super().__init__(size, None, displacement)

    def __repr__(self):
        if self.expr:
            return Mem.__repr__(self)
        return f"MemDisp(size={self.size}, displacement={self.disp})"

    def as_code(self):
        access = self.scope.data_access(self.disp, self.size)
        if not access:
            raise ValueError(f"Memory at disp {self.disp} not found in scope")
        return f"{access}"

class MemBaseDisp(Mem):
    __match_args__ = ("base", "disp", "size")
    def __init__(self, size, base, displacement):
        super().__init__(size, base, displacement)

    def __repr__(self):
        if self.expr:
            return Mem.__repr__(self)
        return f"MemBaseDisp(size={self.size}, base={self.base}, disp={self.disp})"

class MemIndexed(Mem):
    def __init__(self, size, index, scale, displacement):
        super().__init__(size, None, displacement, index, scale)

    def __repr__(self):
        if self.expr:
            return Mem.__repr__(self)
        return f"MemIndexed(size={self.size}, index={self.index}, scale={self.scale}, disp={self.disp})"

    def as_code(self):
        offset = ScaleExpr(self.index, self.scale)
        access = self.scope.data_access(self.disp, self.size, offset_expr=offset)

        if not access:
            raise ValueError(f"Memory at disp {self.disp} not found in scope")
        return f"{access}"

class MemComplex(Mem):
    def __init__(self, size, base, index, scale, displacement=0):
        super().__init__(size, base, displacement, index, scale)

    def __repr__(self):
        if self.expr:
            return Mem.__repr__(self)
        return f"MemComplex(size={self.size}, base={self.base}, index={self.index}, scale={self.scale}, displacement={self.disp})"

class LocalVar(Mem):
    def __init__(self, size, displacement):
        #super().__init__(size, base="EBP", displacement=displacement)
        self.size = size
        self.disp = displacement
        self.scope = scope
        self.access = scope.stack_access(displacement, size)

    def __repr__(self):
        return f"LocalVar({self.disp})"

    def as_code(self):
        if not self.access:
            raise ValueError(f"Local variable at {self.disp} not found in scope")
        return f"{self.access}"

    def as_lvalue(self):
        return self.access

    def as_asm(self):
        return self.as_code()


class SegOverride(Mem):
    __match_args__ = ("segment", "mem")
    def __init__(self, segment, mem):
        super().__init__(mem.size, mem.base, mem.disp, mem.index, mem.scale)
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


class NulOp(RValue):
    def __init__(self, op):
        self.op = op

    def __repr__(self):
        return f"NulOp({self.op})"

    def collect_insts(self, lst):
        pass

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

    def as_asm(self):
        return f"{self.fn.name}"

class BasicBlockRef:
    def __init__(self, addr, label, scope):
        self.label = label
        self.addr = addr
        self.scope = scope

    def __repr__(self):
        return f"BasicBlockRef({self.label})"

    def as_code(self):
        return self.label

    def as_asm(self):
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

    def get_reg(reg_id):
        if reg_id == Register.NONE:
            return None
        reg = REG_TO_STRING[reg_id]
        if expr := state.reg.get(reg):
            return expr
        return Reg(reg)


    match inst.op_kind(op):
        case OpKind.REGISTER:
            reg_id = inst.op_register(op)
            if info.op_access(op) in (OpAccess.READ, OpAccess.READ_WRITE):

                if expr := get_reg(reg_id):
                    # If the register is already defined in the state, return that expression
                    return expr
            return Reg(REG_TO_STRING[reg_id])

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
                return BasicBlockRef(addr, target, scope)
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

            base = get_reg(inst.memory_base)
            index = get_reg(inst.memory_index)
            scale = inst.memory_index_scale
            try:
                size = memsize(inst)
            except ValueError:
                return formatter.format_operand(inst, i)

            if index and base:
                mem = MemComplex(size, base, index, scale, disp)
            elif index:
                mem = MemIndexed(size, index, scale, disp)
            elif not base:
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

    if len(operands) == 2 and inst.op0_kind == OpKind.REGISTER:
        if info.op0_access == OpAccess.READ:
            # eg cmp/test
            return None
        if info.op0_access == OpAccess.WRITE and info.op1_access == OpAccess.READ:
            if inst.mnemonic == Mnemonic.MOV:
                # MOV op, reg
                return operands[0], operands[1]
            if inst.mnemonic == Mnemonic.MOVSX:
                # MOVSX op, reg
                return operands[0], SignExtend(regsize(inst.op0_register), operands[1])
            if inst.mnemonic == Mnemonic.MOVZX:
                # MOVZX op, reg
                return operands[0], ZeroExtend(regsize(inst.op0_register), operands[1])

        elif info.op0_access == OpAccess.WRITE:
            return operands[0], UnaryOp(mnenomic, operands[1])
        elif info.op0_access == OpAccess.READ_WRITE:
            # eg Add etc
            return operands[0], BinaryOp(mnenomic, operands[0], operands[1])


    if len(operands) == 1 and inst.op0_kind == OpKind.REGISTER:
        # eg. INC reg, DEC reg
        if info.op0_access == OpAccess.READ_WRITE:
            return operands[0], UnaryOp(mnenomic, operands[0])
        elif info.op0_access == OpAccess.WRITE:
            # eg pop reg
            return operands[0], NulOp(mnenomic)

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
        self.used = False

    def from_inst(inst, state):
        global g_state
        g_state = state
        mnemonic = formatter.format_mnemonic(inst)
        operands = [process_operand(inst, i, state) for i in range(formatter.operand_count(inst))]

        modifies = modifies_reg(inst, mnemonic, operands)
        ir = I(mnemonic, operands, inst)
        if modifies:
            reg, expr = modifies
            expr.inst = ir
            state.reg[reg.reg] = Reg(reg.reg, expr, ir)

        return ir

    def side_effects(self):
        # side effects are instructions that modify memory or any registers other than eax, ecx, edx, esi, edi
        info = info_factory.info(self.inst)
        effects = []
        if self.inst.op0_kind == OpKind.NEAR_BRANCH32:
            # branches are always side-effecting
            effects.append("branch")
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
            if isinstance(op, str):
                ops.append(op)
                continue
            try:
                ops.append(op.as_asm())
            except ValueError:
                ops.append(formatter.format_operand(self.inst, i))

        if ops:
            return f"__asm        {self.mnenomic:6} {", ".join(ops)};"
        return f"__asm        {self.mnenomic};"

class State:
    def __init__(self):
        self.reg = {}

def set_scope(_scope):
    global scope
    scope = _scope