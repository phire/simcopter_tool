
import ir
from ir import *

class BasicBlock:
    def __init__(self, insts, scope, labels):
        self.insts = insts
        self.scope = scope
        self.labels = labels
        self.effects = [x for x in insts if x.side_effects()]
        self.statements = insts[:]

    def address(self):
        if not self.insts:
            return None
        return self.insts[0].inst.ip32

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
        return self.target.is_known() and self.value.is_known()

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


def match_statement(bblock):
    if not bblock.insts:
        return None



    head = stmt = None
    match bblock.effects:
        case [*head, I("mov", (Mem() as mem, Expression() as expr)) as i]:
            stmt = Assign(mem, expr)
        case [*head, I("add", (Expression() as expr, Mem() as mem)) as i]:
            stmt = Modify("+", mem, expr)
        case [*head, I("sub", (Expression() as expr, Mem() as mem)) as i]:
            stmt = Modify("-", mem, expr)
        case [*head, I("inc", (Mem() as mem,)) as i]:
            stmt = Increment(mem)
        case [*head, I("dec", (Mem() as mem,)) as i]:
            stmt = Decrement(mem)

    if not stmt:
        return None

    used = set([i])
    def collect_used(expr):
        nonlocal used
        if expr.inst:
            used.add(expr.inst)

    stmt.target.visit(collect_used)
    if hasattr(stmt, 'value'):
        stmt.value.visit(collect_used)

    try:
        stmt.as_code()
    except:
        # for now, just ignore statements that cannot be converted to code
        return None

    if all([x in used for x in bblock.insts]):
        return stmt

    # print(f"function: {bblock.dbg_name()}")
    # for inst in bblock.insts:
    #     usedstr = " <not used>" if inst not in used else ""
    #     print(f"  {inst}{usedstr}")
    # if all([x in used for x in bblock.insts]):
    #     print(f"matched: {stmt}")

    #     print(f"  code: {stmt.as_code()}")
    # else:
    #     print(f"not matched: {stmt}")

    return None

