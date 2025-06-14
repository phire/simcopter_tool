
from iced_x86 import Decoder, Instruction, Code
import base_types
import ir
from ir import *
import function
import x86

class BasicBlock:
    def __init__(self, labels, scope, start, end):
        self.scope = scope
        self.labels = labels
        self.label = next((x for x in labels if isinstance(x, function.Label)), None)
        self.start = start
        self.end = end
        self.incomming = set()
        self.fallthough = None

        self.statements = None


    def as_code(self):
        if self.statements:
            return "\n".join([s.as_code() for s in self.statements]) + "\n"
        return ir.as_asm(self.data(), self.address(), self.scope)

    def insts(self):
        state = ir.State()
        ir.set_scope(self.scope)
        return [I.from_inst(i, state) for i in x86.disassemble(self.data(), self.address())]

    def decomp(self):
        state = ir.State()
        ir.set_scope(self.scope)
        insts = [I.from_inst(i, state) for i in x86.disassemble(self.data(), self.address())]
        return state, insts

    def data(self):
        return self.scope.fn.data()[self.start:self.end]

    def empty(self):
        return self.start == self.end

    def address(self):
        return self.scope.fn.address + self.start

    def dbg_name(self):
        fn = self.scope.fn
        addr = self.address()
        if not addr:
            return f"{fn.name}+(no address)"
        offset = addr - fn.address
        return f"{fn.name}+{offset:#x}"

class Statement:
     pass

class Assign(Statement):
    def __init__(self, target, value):
        self.target = target
        self.value = value

    def __repr__(self):
        return f"Assign({self.target}, {self.value})"

    def as_code(self):
        return f"{self.target.as_lvalue()} = {self.value.as_rvalue()};"

    def __bool__(self):
        if not self.target.is_known() or not self.value.is_known():
            return False
        try:
            self.as_code()
        except ValueError:
            return False
        except:
            return False
        return True

class Modify(Assign):
    def __init__(self, op, target, value):
        self.op = op
        self.target = target
        self.value = value

    def __repr__(self):
        return f"Modify({self.op}, {self.target}, {self.value})"

    def as_code(self):
        return f"{self.target.as_lvalue()} {self.op}= {self.value.as_rvalue()};"



class Increment(Statement):
    def __init__(self, target):
        self.target = target

    def __repr__(self):
        return f"Increment({self.target})"

    def as_code(self):
        return f"{self.target.as_lvalue()}++;"

class Decrement(Statement):
    def __init__(self, target):
        self.target = target

    def __repr__(self):
        return f"Decrement({self.target})"

    def as_code(self):
        return f"{self.target.as_lvalue()}--;"


class Return(Statement):
    def __init__(self, ty, value):
        self.ty = ty
        self.value = value

    def __repr__(self):
        return f"Return({self.ty}, {self.value})"

    def as_code(self):
        if not self.value:
            return "return;"
        return f"return {self.value.as_rvalue()};"


def are_all_insts_used(explicit, exprs, insts):
    used = set(explicit)
    def collect_used(expr):
        nonlocal used
        if expr.inst:
            used.add(expr.inst)

    for expr in exprs:
        expr.visit(collect_used)


    # print(f"function: {bblock.dbg_name()}")
    # for inst in bblock.insts:
    #     usedstr = " <not used>" if inst not in used else ""
    #     print(f"  {inst}{usedstr}")
    # if all([x in used for x in bblock.insts]):
    #     print(f"matched: {stmt}")

    #     print(f"  code: {stmt.as_code()}")
    # else:
    #     print(f"not matched: {stmt}")

    return all([x in used for x in insts])


def match_statement(bblock):
    insts = bblock.insts()

    effects = [x for x in insts if x.side_effects()]

    head = stmt = None
    match effects:
        case [*head, I("mov", (Mem() as mem, Expression() as expr)) as i]:
            stmt = Assign(mem, expr)
        case [*head, I("add", (Mem() as mem, Expression() as expr)) as i]:
            stmt = Modify("+", mem, expr)
        case [*head, I("sub", (Mem() as mem, Expression() as expr)) as i]:
            stmt = Modify("-", mem, expr)
        case [*head, I("inc", Mem() as mem) as i]:
            stmt = Increment(mem)
        case [*head, I("dec", Mem() as mem) as i]:
            stmt = Decrement(mem)

    if not stmt:
        return None

    exprs = [stmt.target]
    if hasattr(stmt, 'value'):
        exprs.append(stmt.value)

    if are_all_insts_used([i], exprs, insts):
        try:
            stmt.as_code()
            return stmt
        except:
            # for now, just ignore statements that cannot be converted to code
            return None
    return None

def match_return(bb, return_ty, return_bb):
    """ Match a return statement """
    state, insts = bb.decomp()

    #effects = [x for x in insts if x.side_effects()]
    match insts:
        case [*head, I("jmp", dest) as i]:
            assert dest == return_bb
        case _: return False

    explict = [i]

    if return_ty == base_types.Void:
        if are_all_insts_used(explict, [], insts):
            bb.statements = [Return(return_ty, None)]
            return True
        return False

    try: size = return_ty.type_size()
    except: return False

    expr = state.get_eax(size)
    match expr:
        case UnaryOp("xor", _) as xor:
            # xor eax, eax
            expr = Const(0)
            expr.inst = xor.inst
        case Lea(mem) as lea:
            explict += [lea.inst]
            expr = Refrence(mem)

    if expr is not None and are_all_insts_used(explict, [expr], insts):
        stmt = Return(return_ty, expr)
        try:
            stmt.as_code()
            bb.statements = [stmt]
            return True
        except:
            # for now, just ignore statements that cannot be converted to code
            pass
    return False