from access import AddressOf, ArrayAccess, ScaleExpr
from ref import FunctionRef, BasicBlockRef

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
    def __init__(self, reg, expr: Expression=None, inst=None):
        self.reg = reg
        self.expr = expr
        self.inst = inst # The instruction that wrote to this register
        if expr:
            expr.inst = inst

    def __repr__(self):
        if self.expr:
            return f"Reg({REG_TO_STRING[self.reg]}, {self.expr})"
        else:
            return f"Reg({REG_TO_STRING[self.reg]})"

    def __eq__(self, other):
        if isinstance(other, Reg):
            return self.reg == other.reg
        if isinstance(other, str):
            return REG_TO_STRING[self.reg] == other
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
        return REG_TO_STRING[self.reg]

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
            if isinstance(access, str):
                raise ValueError(f"TODO: Base {self.base} is not an Access")
            # MSVC++ (without optimizations) doesn't seem to use all three at once (other than bp, which doesn't go through here)
            if self.index:
                assert self.disp == 0
                offset = ScaleExpr( self.index.expr.as_rvalue(), self.scale)
            else:
                offset = self.disp
            return access.deref(offset, self.size)

        elif self.disp and not self.index:
            access = self.scope.data_ref(self.disp)
            if not access:
                raise ValueError(f"Memory at disp {self.disp} not found in scope")
            return access.deref(0, self.size)

        raise ValueError("Cannot convert indexed Mem to LValue")

    def as_asm(self):
        access = None
        if self.disp:
            access = self.scope.data_ref(self.disp)

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

        access = access.deref(0, self.size)

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
        access = self.scope.data_ref(self.disp)
        if not access:
            raise ValueError(f"Memory at disp {self.disp} not found in scope")
        return f"{access.deref(0, self.size)}"

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
        access = self.scope.data_ref(self.disp)

        if not access:
            raise ValueError(f"Memory at disp {self.disp} not found in scope")
        return f"{access.deref(offset, self.size)}"

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
        self.access = scope.stack_ref(displacement)

    def __repr__(self):
        return f"LocalVar({self.disp}, {self.access})"

    def as_code(self):
        if not self.access:
            raise ValueError(f"Local variable at {self.disp} not found in scope")
        return f"{self.access.deref(0, self.size)}"

    def as_lvalue(self):
        if not self.access:
            raise ValueError(f"Local variable at {self.disp} not found in scope")
        return self.access.deref(0, self.size)

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

    def as_lvalue(self):
         # TODO: BinaryOps can be Lvalues if they are address calculations
        raise ValueError("Using BinaryOp as LValues not yet implemented")

    def as_rvalue(self):
        match self.op:
            case "add":
                return f"({self.left.as_rvalue()} + {self.right.as_rvalue()})"
            case "sub":
                return f"({self.left.as_rvalue()} - {self.right.as_rvalue()})"
            case "and":
                return f"({self.left.as_rvalue()} & {self.right.as_rvalue()})"
        raise ValueError(f"as_rvalue not implemented for BinaryOp {self.op}")


class UnaryOp(RValue):
    __match_args__ = ("op", "operand")
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand

    def __repr__(self):
        return f"UnaryOp({self.op}, {self.operand})"

    def as_rvalue(self):
        raise ValueError(f"as_rvalue not implemented for UnaryOp {self.op} {self.operand}")

class Lea(LValue):
    __match_args__ = ("mem",)
    def __init__(self, mem):
        self.mem = mem

    def __repr__(self):
        return f"Lea({self.mem})"

    def as_lvalue(self):
        return self.mem.as_lvalue()

    def as_rvalue(self):
        if isinstance(self.mem, LocalVar):
            return self.mem.as_lvalue()

        if self.mem.index:
            expr = BinaryOp("mul", self.mem.index.as_rvalue(), Const(self.mem.scale))
            if self.mem.base:
                expr = BinaryOp("add", self.mem.base.as_rvalue(), expr)
        elif self.mem.base:
            expr = self.mem.base
        else:
            raise ValueError("LEA without base or index")
            expr = self.mem.as_rvalue()

        if self.mem.disp:
            expr = BinaryOp("add", expr, Const(self.mem.disp))
        return expr.as_rvalue()

class Refrence(LValue):
    def __init__(self, expr):
        self.expr = expr

    def __repr__(self):
        return f"Refrence({self.expr})"

    def as_lvalue(self):
        return AddressOf(self.expr.as_lvalue())


class Pushed(Expression):
    def __init__(self, expr, inst):
        self.expr = expr
        self.inst = inst

    def __repr__(self):
        return f"Pushed({self.expr})"

    def as_lvalue(self):
        return self.expr.as_lvalue()

    def as_rvalue(self):
        return self.expr.as_rvalue()

class CallExpr(Expression):
    def __init__(self, fn, args, inst, this_expr=None):
        self.fn = fn
        self.args = args
        self.inst = inst
        self.adjust_expr = None
        self.this_expr = this_expr

    def __repr__(self):
        return f"Call({self.fn}, args={self.args})"

    def as_rvalue(self):
        args = ", ".join(str(arg.as_rvalue()) for arg in self.args)
        if self.this_expr:
            return f"{self.this_expr.as_rvalue()}->{self.fn.name}({args})"
        return f"{self.fn.name}({args})"


    def visit(self, fn):
        fn(self)
        if self.this_expr:
            self.this_expr.visit(fn)
        if self.adjust_expr:
            self.adjust_expr.visit(fn)
        for arg in self.args:
            arg.visit(fn)

class TernaryExpr(RValue):
    def __init__(self, cond, left, right):
        self.cond = cond
        self.left = left
        self.right = right

    def as_rvalue(self):
        return f"{self.cond.as_rvalue()} ? {self.left.as_rvalue()} : {self.right.as_rvalue()}"

    def __repr__(self):
        return f"TernaryExpr({self.cond}, {self.left}, {self.right})"

class NulOp(RValue):
    def __init__(self, op):
        self.op = op

    def __repr__(self):
        return f"NulOp({self.op})"

    def collect_insts(self, lst):
        pass

class SignExtend(LValue):
    def __init__(self, size, expr):
        self.size = size
        self.expr = expr

    def __repr__(self):
        return f"SignExtend(size={self.size}, expr={self.expr})"

    def as_rvalue(self):
        return f"reinterpret_cast<int{self.size*8}_t>({self.expr.as_code()})"

class ZeroExtend(LValue):
    def __init__(self, size, expr):
        self.size = size
        self.expr = expr

    def __repr__(self):
        return f"ZeroExtend(size={self.size}, expr={self.expr})"


from iced_x86 import Decoder, Instruction, OpKind, Register, Mnemonic as M, OpAccess, InstructionInfoFactory, Code
info_factory = InstructionInfoFactory()

from x86 import formatter, REG_TO_STRING, memsize

def process_operand(inst, info, i, state):
    op = formatter.get_instruction_operand(inst, i)
    if op is None:
         return formatter.format_operand(inst, i)

    if state:
        def get_reg(reg_id):
            if reg_id == Register.NONE:
                return None
            if expr := state.reg.get(reg_id):
                return expr
            return Reg(reg_id)
    else:
        def get_reg(reg_id):
            if reg_id == Register.NONE:
                return None
            return Reg(reg_id)

    match inst.op_kind(op):
        case OpKind.REGISTER:
            reg_id = inst.op_register(op)
            if info.op_access(op) in (OpAccess.READ, OpAccess.READ_WRITE):

                if expr := get_reg(reg_id):
                    # If the register is already defined in the state, return that expression
                    return expr
            return Reg(reg_id)

        case OpKind.IMMEDIATE8 | OpKind.IMMEDIATE8_2ND | OpKind.IMMEDIATE16 | OpKind.IMMEDIATE32 | OpKind.IMMEDIATE64 | OpKind.IMMEDIATE8TO16 | OpKind.IMMEDIATE8TO32 | OpKind.IMMEDIATE8TO64:
            imm = inst.immediate(op)
            if imm > 0x7fffffffffffffff:
                imm = imm - 0x10000000000000000
            return Const(imm)

        case OpKind.NEAR_BRANCH32:
            addr = inst.near_branch32
            target = scope.code_ref(inst.ip32, addr)
            if not target:
                return formatter.format_operand(inst, i)
            return target


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

def modifies_reg(inst, info, mnenomic, operands):

    if len(operands) != inst.op_count:
        return None

    if len(operands) == 2 and inst.op0_kind == OpKind.REGISTER:
        if info.op0_access == OpAccess.READ:
            # eg cmp/test
            return None
        if info.op0_access == OpAccess.WRITE and info.op1_access == OpAccess.READ:
            if inst.mnemonic == M.MOV:
                # MOV op, reg
                return operands[0], operands[1]
            if inst.mnemonic == M.MOVSX:
                # MOVSX op, reg
                return operands[0], SignExtend(regsize(inst.op0_register), operands[1])
            if inst.mnemonic == M.MOVZX:
                # MOVZX op, reg
                return operands[0], ZeroExtend(regsize(inst.op0_register), operands[1])

        elif info.op0_access == OpAccess.WRITE:
            match inst.mnemonic:
                case M.LEA:
                    return operands[0], Lea(operands[1])
                case M.XOR:
                    assert operands[0] == operands[1], f"XOR {operands[0]} {operands[1]} not allowed"
                    return operands[0], Const(0)

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
    def __init__(self, mnenomic, operands, inst: Instruction=None):
        self.mnenomic = mnenomic
        match operands:
            case [op]:
                operands = op
            case ops:
                operands = tuple(ops)
        self.operands = operands
        self.inst = inst
        self.stack_compensate = None
        self.no_effects = False

    def from_inst(inst, state):
        mnemonic = formatter.format_mnemonic(inst)
        info = info_factory.info(inst)
        operands = [process_operand(inst, info, i, state) for i in range(formatter.operand_count(inst))]

        ir = I(mnemonic, operands, inst)
        match inst.mnemonic:
            case M.JA | M.JAE | M.JB | M.JBE | M.JE | M.JG | M.JGE | M.JL | \
              M.JLE | M.JNE | M.JNO | M.JNP | M.JNS | M.JO | M.JP | M.JS:
                return JCond(inst, state)
            case M.CALL:
                this_expr = state.reg.get(Register.ECX)
                state.clear()
                args = list(state.stack)

                match operands[0]:
                    case FunctionRef(fn) if reg := fn.return_reg():
                        if not fn.is_thiscall():
                            this_expr = None
                        state.call = expr = CallExpr(fn, args, ir, this_expr)
                        adjust = fn.stack_adjust
                        while adjust and state.stack and (expr := state.stack.pop()):
                            i = expr.inst
                            adjust += i.inst.stack_pointer_increment
                            assert adjust >= 0
                            i.stack_compensate = ir
                            i.no_effects = True
                        if adjust == 0:
                            ir.no_effects = True

                        state.reg[reg] = Reg(reg, expr, ir)
                    case _:
                        state.call = expr = CallExpr(None, args, ir, None)

            case M.PUSH:
                state.push(Pushed(operands[0], ir))
            case M.ADD if inst.op0_register == Register.ESP and inst.op0_kind == OpKind.REGISTER and inst.op1_kind >= OpKind.IMMEDIATE8:
                adjust = inst.immediate(1)
                if state.call:
                    adjust_expr = Const(adjust)
                    adjust_expr.inst = ir
                    state.call.adjust_expr = adjust_expr
                if (sum(i.inst.inst.stack_pointer_increment for i in state.stack) + adjust) == 0:
                    for i in [e.inst for e in state.stack]:
                        i.stack_compensate = ir
                        i.no_effects = True
                    state.stack.clear()
                    ir.no_effects = True

            case _:
                modifies = modifies_reg(inst, info, mnemonic, operands)
                if modifies:
                    reg, expr = modifies
                    state.reg[reg.reg] = Reg(reg.reg, expr, ir)

                if inst.rflags_modified:
                    state.setFlags(ir)

        return ir

    def side_effects(self):
        # side effects are instructions that modify memory or any registers other than eax, ecx, edx, esi, edi
        if self.no_effects:
            return False
        if self.inst.op0_kind == OpKind.NEAR_BRANCH32:
            if self.inst.mnemonic == M.JMP:
                return False
            return True
        info = info_factory.info(self.inst)
        for mem in info.used_memory():
            if mem.segment == Register.SS and self.stack_compensate:
                continue
            if mem.access in (OpAccess.WRITE, OpAccess.READ_WRITE, OpAccess.COND_WRITE, OpAccess.READ_COND_WRITE):
                return True
        for reg in info.used_registers():
            if reg.access in (OpAccess.WRITE, OpAccess.READ_WRITE, OpAccess.COND_WRITE, OpAccess.READ_COND_WRITE):
                if reg.register not in (Register.EAX, Register.ECX, Register.EDX, Register.ESI, Register.EDI):
                    # for now, we won't consider sub registers like AH, AL, etc to be side-effect free
                    return True
        return False

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




def as_asm(data, addr, _scope):
    global scope
    scope = _scope

    s = ""
    decoder = Decoder(32, data, ip=addr)
    inst = Instruction.create(Code.INVALID)

    while decoder.can_decode:
        decoder.decode_out(inst)

        mnemonic = formatter.format_mnemonic(inst)

        op_count = formatter.operand_count(inst)
        if op_count == 0:
            s += f"__asm        {mnemonic};\n"
            continue

        ops = []
        for i in range(formatter.operand_count(inst)):
            opnd = formatter.get_instruction_operand(inst, i)
            if opnd is not None and inst.op_kind(opnd) != OpKind.REGISTER:
                op = process_operand(inst, None, i, None)
                if isinstance(op, str):
                    ops.append(op)
                    continue
                try:
                    ops.append(op.as_asm())
                    continue
                except ValueError:
                    pass
            ops.append(formatter.format_operand(inst, i))
        s += f"__asm        {mnemonic:6} {", ".join(ops)};\n"
    return s

class State:
    def __init__(self):
        self.reg = {}
        self.flags = None
        self.stack = []
        self.call = None  # The last call instruction, if any

    def clear(self):
        self.reg.clear()
        self.flags = None
        self.call = None

    def get_eax(self, size):
        match size:
            case 1: reg = self.reg.get(Register.AL)
            case 2: reg = self.reg.get(Register.AX)
            case 4: reg = self.reg.get(Register.EAX)
            case _: reg = None
        return reg.expr if reg else None

    def setFlags(self, inst):
        # We probably don't need to track each flag individually...
        # so just track the last instruction that modified the flags
        self.flags = inst

    def push(self, expr):
        self.stack.append(expr)


def set_scope(_scope):
    global scope
    scope = _scope


class Cond(Expression):
    def __init__(self, cond, left, right = None):
        self.cond = cond
        self.left = left
        self.expr = right

    def __repr__(self):
        return f"Cond({self.cond}, {self.left}, {self.expr})"

    def as_rvalue(self):
        return f"({self.left.as_rvalue()} {self.cond} {self.expr.as_rvalue()})"

class ErrorCond(Expression):
    def __init__(self, cond):
        self.cond = cond

    def __repr__(self):
        return f"ErrorCond({self.cond})"

class JCond(I):
    __match_args__ = ("cond", "target")
    def __init__(self, inst: Instruction, state: State):
        self.inst = inst
        addr = inst.near_branch32
        self.target = scope.code_ref(inst.ip32, addr) or formatter.format_operand(inst, 0)
        self.operands = self.target
        cmp = state.flags
        self.mnenomic = formatter.format_mnemonic(inst)
        if not cmp or inst.rflags_read & cmp.inst.rflags_modified == 0:
            self.cond = ErrorCond(self.mnenomic)
            return

        if isinstance(cmp.operands, tuple):
            left, right = cmp.operands
        else:
            left = cmp.operands
            right = None
        match cmp.inst.mnemonic, inst.mnemonic:
            case M.CMP, M.JA | M.JG: self.cond = Cond(">", left, right)
            case M.CMP, M.JAE | M.JGE: self.cond = Cond(">=", left, right)
            case M.CMP, M.JB | M.JL: self.cond = Cond("<", left, right)
            case M.CMP, M.JBE | M.JLE: self.cond = Cond("<=", left, right)
            case M.CMP, M.JE: self.cond = Cond("==", left, right)
            case M.CMP, M.JNE: self.cond = Cond("!=", left, right)
            case M.CMP, _: self.cond = ErrorCond(f"Unexpected flags {self.mnenomic} for {cmp}")
            case M.TEST, (M.JE | M.JNE) as m:
                if left == right:
                    expr = left
                else:
                    expr = BinaryOp("and", left, right)
                expr.inst = cmp
                self.cond = Cond("==" if m == M.JE else "!=", expr, Const(0))
            case M.TEST, _: self.cond = ErrorCond(f"Unexpected flags {self.mnenomic} for {cmp}")
            case _, _: self.cond = ErrorCond(f"Unknown {self.mnenomic} for {cmp}")
            case M.DEC, M.JS: self.cond = Cond("<", left, Const(0))

        self.cond.inst = cmp

    def __repr__(self):
        if isinstance(self.operands, tuple):
            return f"I({self.mnenomic} {', '.join(map(str, self.operands))})"

        return f"JCond({self.mnenomic} {self.operands})"

    def side_effects(self) -> bool:
        # Changing control flow is a side effect
        return True

