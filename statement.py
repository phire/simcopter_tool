
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
        self.outgoing = None
        self.fallthrough = None
        self.fallfrom = None
        self.inlined = None

        self.statements = []


    def as_code(self):
        if self.statements:
            return "\n".join([s.as_code() for s in self.statements]) + "\n"
        return self.as_asm()


    def as_asm(self):
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

    def visit(self, fn):
        self.target.visit(fn)
        self.value.visit(fn)

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

    def visit(self, fn):
        self.target.visit(fn)

class Decrement(Statement):
    def __init__(self, target):
        self.target = target

    def __repr__(self):
        return f"Decrement({self.target})"

    def as_code(self):
        return f"{self.target.as_lvalue()}--;"

    def visit(self, fn):
        self.target.visit(fn)


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

    def visit(self, fn):
        self.value.visit(fn)

class ExprStatement(Statement):
    def __init__(self, expr):
        self.expr = expr

    def __repr__(self):
        return f"ExprStatement({self.expr})"

    def as_code(self):
        return f"{self.expr.as_rvalue()};"

    def visit(self, fn):
        self.expr.visit(fn)


def are_all_insts_used(explicit, exprs, insts, bblock=None):
    used = set(explicit)
    def collect_used(expr):
        nonlocal used
        if expr.inst:
            used.add(expr.inst)

    for expr in exprs:
        expr.visit(collect_used)

    if bblock:
        print(f"function: {bblock.dbg_name()}")
        for inst in insts:
            usedstr = " <not used>" if inst not in used else ""
            print(f"  {inst}{usedstr}")

    return all([x in used for x in insts])

def consume_insts(exprs, insts):
    used = set()
    def collect_used(expr):
        nonlocal used
        if expr.inst:
            used.add(expr.inst)

    for expr in exprs:
        expr.visit(collect_used)

    new_insts = []
    done = False
    for inst in insts:
        if inst not in used:
            if done:
                raise ValueError(f"insts can't be cleanly divided into used and unused")
            new_insts.append(inst)
        else:
            if inst.side_effects():
                raise ValueError(f"inst {inst} has side effects, cannot be consumed")
            done = True
    return new_insts


def match_statement(bblock):
    insts = bblock.insts()

    #effects = [x for x in insts if x.side_effects()]

    stmts = []
    while insts:
        match insts.pop():
            case I("jmp", _) as jmp:
                stmts.append(jmp)
                continue # filter out jump instructions
            case I("mov", (Mem() as mem, Expression() as expr)):
                stmt = Assign(mem, expr)
            case I("add", (Mem() as mem, Expression() as expr)):
                stmt = Modify("+", mem, expr)
            case I("sub", (Mem() as mem, Expression() as expr)):
                stmt = Modify("-", mem, expr)
            case I("inc", Mem() as mem):
                stmt = Increment(mem)
            case I("dec", Mem() as mem):
                stmt = Decrement(mem)
            case I("call") as call:
                stmt = ExprStatement(call.expr)
            case I("add", ("esp", _)) as cleanup if insts and not cleanup.side_effects():
                continue
            case _:
                return None

        try:
            stmt.as_code()
            stmts.insert(0, stmt)
        except:
            # for now, just ignore bblocks that cannot be converted to code
            return None
        try:
            insts = consume_insts([stmt], insts)
        except ValueError as e:
            return None

    return stmts

def match_cond(bb):
    """ Match a conditional expression """
    _, insts = bb.decomp()
    match [x for x in insts if x.side_effects()]:
        case [JCond(cond)] as explicit:
            return cond if are_all_insts_used(explicit, [cond], insts) else None

def match_ternary(bb, size):
    """
    Match a ternary expression that is used directly with eax.
    Only seems to be used for return statements
    """

    incommming = next(iter(bb.incomming), None)
    cond_bb = incommming.fallfrom if incommming else None

    if not cond_bb or cond_bb.outgoing is not bb.fallfrom:
        return None, []
    left_bb = cond_bb.fallthrough
    right_bb = cond_bb.outgoing

    if len(bb.incomming) != 1:
        # TODO: There is a nested ternary in the right side
        #       (nested ternaries on the left side will fail to match the condition)
        return None, []
    if len(right_bb.incomming) > 1:
        # TODO: This seems to happen when the condition of a ternary is an inlined function
        return None, []
    assert left_bb.fallthrough is None
    assert right_bb.fallthrough is bb and right_bb.outgoing is None

    def match_leaf(leaf):
        state, insts = leaf.decomp()
        match insts:
            case [*insts, I('jmp', _)]: pass  # filter out jump instructions

        if expr := state.get_eax(size):
            if any(x.side_effects() for x in insts if x != expr.inst):
                # if there are any side effects, we cannot use this expression
                return None

            assert are_all_insts_used([], [expr], insts)
            return expr

    if (cond := match_cond(cond_bb)) and \
      (left := match_leaf(left_bb)) and \
      (right := match_leaf(right_bb)):
        match left, right:
            case Const(1), Const(0): # special case for boolean expressions
                return cond, [cond_bb, left_bb, right_bb]
        return TernaryExpr(cond, left, right), [cond_bb, left_bb, right_bb]
    return None, []


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
    extra_bbs = []

    if head:
        match state.get_eax(size):
            case UnaryOp("xor", _) as xor:
                # xor eax, eax
                expr = Const(0)
                expr.inst = xor.inst
            case Lea(mem) as lea:
                explict += [lea.inst]
                expr = Refrence(mem)
            case expr: pass
    else:
        expr, extra_bbs = match_ternary(bb, size)

    if expr is not None and are_all_insts_used(explict, [expr], insts):
        stmt = Return(return_ty, expr)
        try:
            stmt.as_code()
        except:
            # for now, just ignore statements that cannot be converted to code
            return False

        bb.statements = [stmt]
        for ebb in extra_bbs:
            ebb.inlined = stmt
        return True
    return False