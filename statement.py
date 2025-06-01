
import ir
from ir import *


class Statement:
     pass

class Assign(Statement):
    def __init__(self, target, value):
        self.target = target
        self.value = value

    def __repr__(self):
        return f"Assign({self.target}, {self.value})"

    def as_code(self):
        return f"{self.target} = {self.value}"

class Modify(Statement):
    def __init__(self, op, target, value):
        self.op = op
        self.target = target
        self.value = value

    def __repr__(self):
        return f"Modify({self.op}, {self.target}, {self.value})"

    def as_code(self):
        return f"{self.target} {self.op}= {self.value}"

class Increment(Statement):
    def __init__(self, target):
        self.target = target

    def __repr__(self):
        return f"Increment({self.target})"

    def as_code(self):
        return f"{self.target}++"

class Decrement(Statement):
    def __init__(self, target):
        self.target = target

    def __repr__(self):
        return f"Decrement({self.target})"

    def as_code(self):
        return f"{self.target}--"


def match_statement(insts, func):
    if not insts:
        return insts, None

    address = insts[0].inst.ip32
    offset = address - func.address

    print(f"function: {func.name}+{offset:#x}")
    effect_insts = []
    for inst in insts:
        effects = inst.side_effects()
        if effects:
            print(f"inst {inst} has side effects: {effects}")
            effect_insts.append(inst)
        else:
            print(f"inst {inst}")


    match effect_insts:
        case [*head, I("mov", (Mem() as mem, Expression() as expr))]:
            return head, Assign(mem, expr)
        case [*head, I("add", (Expression() as expr, Mem() as mem))]:
            return head, Modify("+", mem, expr)
        case [*head, I("sub", (Expression() as expr, Mem() as mem))]:
            return head, Modify("-", mem, expr)
        case [*head, I("inc", (Mem() as mem,))]:
            return head, Increment(mem)
        case [*head, I("dec", (Mem() as mem,))]:
            return head, Decrement(mem)

    return insts, None

