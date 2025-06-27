

import itertools
import textwrap
from ir import I
from labels import Label
from statement import Statement, BasicBlock, match_cond, match_statement
from switch import SwitchPointers
import heapq

def is_bb(bb):
    return isinstance(bb, BasicBlock)

def find_backedges(fn):
    # Body is already pretty much a control flow graph, but we want them sorted by visit order

    to_visit = [x for x in fn.body.values() if is_bb(x) and not (x.fallfrom or x.incomming)]
    heapq.heapify(to_visit)

    visited = set()
    body_iter = iter(fn.body.values())
    to_visit.append(next(body_iter, None))  # start with the first basic block

    def next_bb():
        nonlocal to_visit, body_iter
        if to_visit:
            return heapq.heappop(to_visit)
        return next(body_iter, None)

    while bb := next_bb():
        if bb in visited:
            continue

        visited.add(bb)
        bb.branch_id = len(visited)
        match bb:
            case BasicBlock():
                if bb.fallthrough and bb.fallthrough.incomming.issubset(visited):
                    heapq.heappush(to_visit, bb.fallthrough)
                match out := bb.outgoing:
                    case BasicBlock() if out in visited:
                        assert out.start < bb.start, f"Backedge from {out.start:#x} to {bb.start:#x}"
                        if any(isinstance(l, Label) and not l.name.startswith("_T") for l in out.labels):
                            continue # just a goto that goes backwards
                        fn.backedges.add(out)
                    case BasicBlock() if (not out.fallfrom or out.fallfrom in visited) and out.incomming.issubset(visited):
                        # all incoming edges have been visited
                        heapq.heappush(to_visit, out)
            case SwitchPointers():
                fn_addr = bb.fn.address
                blocks = [bb.fn.getJumpDest(x - fn_addr).bb for x in bb.targets]
                heapq.heapify(blocks)
                heapq.merge(to_visit, blocks)
    for bb in fn.body.values():
        assert bb in visited


def find_loops(fn, iter):
    block = Block()

    while bb := next(iter, None):
        if bb in fn.backedges:
            sources = [x for x in bb.incomming if x.branch_id > bb.branch_id]
            loop_end = max(sources, key=lambda x: x.branch_id)
            body = find_loops(fn, itertools.takewhile(lambda x: x != loop_end, iter))

            try:
                stmt = match_loop(bb, loop_end, body, block)
                stmt.as_code()
                block.append(stmt)
            except ValueError:
                block.append(bb)
                block.extend(body)
                block.append(loop_end)
        else:
            block.append(bb)

    return block

def match_loop(loop_head, loop_end, body, parent):
    off = loop_head.start
    if not loop_end.is_conditional() and loop_head.outgoing and loop_head.outgoing == loop_end.after:
        # this is a while loop
        loop_head.set_label(f"__WHILE_{off:02x}")
        assert loop_head.is_conditional(), "Loop head must be conditional for a while loop"
        cond = match_cond(loop_head)
        if cond:
            cond = cond.invert()
        else:
            raise ValueError("failed to match condition")

        trim_end(loop_end, body)

        return WhileLoop(cond, loop_head, body)
    elif loop_end.is_conditional():
        # this is a do-while loop
        loop_head.set_label(f"__DO_{off:02x}")
        loop_end.set_label(f"__DO_WHILE_{off:02x}")
        cond = match_cond(loop_end)
        if not cond:
            raise ValueError("failed to match condition")
        body.insert(0, loop_head)

        return DoLoop(cond, loop_head, body)
    elif not loop_head.fallfrom and loop_head.before.outgoing == loop_head.after:
        # it's a for loop.
        cond_bb = loop_head.fallthrough
        cond = match_cond(cond_bb)
        init_bb = loop_head.before

        init_bb.set_label(f"_FOR_{off:02x}")
        cond_bb.set_label(f"_FOR_COND_{off:02x}")
        loop_head.set_label(f"_FOR_NEXT_{off:02x}")

        if cond and cond.as_rvalue():
            cond = cond.invert()
        else:
            raise ValueError("failed to match condition")

        match match_statement(loop_head):
            case [next_expr]: pass
            case _: raise ValueError("failed to match next step statement")

        body.remove(cond_bb)
        trim_end(loop_end, body)

        match match_statement(init_bb):
            case [init, I("jmp", _)]:
                parent.remove(init_bb)
                head = init_bb
            case [I("jmp", _)]:
                init = None
                parent.remove(init_bb)
                head = init_bb
            case _:
                # if we fail to match the init, just leave it in the parent block for now
                init = None
                head = loop_head

        return ForLoop(init, cond, next_expr, head, body)
    else:
        loop_head.set_label(f"_LOOP_{off:02x}")
        body.insert(0, loop_head)
        trim_end(loop_end, body)
        return InfiniteLoop(body)

def trim_end(bb, body):
    match match_statement(bb):
        case None:
            body.append(bb)
        case [I("jmp", _)]:
            if bb.incomming:
                bb.inlined = True
                body.append(bb)
        case [*stmts, I("jmp", _)]:
            bb.statements = stmts
            body.append(bb)
        case _:
            assert False, f"Unexpected end of loop: {bb.as_code()}"

class Loop(Statement):
    def __init__(self, kind, cond, head, body):
        self.kind = kind
        self.cond = cond
        self.body = body
        self.head = head

    def as_code(self, *, cond_str=None, postfix="\n"):
        head = "".join(label.as_code() for label in self.head.labels)
        head = "\n" if not head else head

        if cond_str is None:
            cond_str = f" ({self.cond.as_rvalue()})" if self.cond else ""
        body = textwrap.indent(self.body.as_code(), "\t")
        return head + textwrap.indent(f"{self.kind}{cond_str} {{\n{body}}}{postfix}", "\t")

class ForLoop(Loop):
    def __init__(self, init, cond, next_step, head, body):
        super().__init__("for", cond, head, body)
        self.init = init
        self.next_step = next_step

    def as_code(self):
        init = self.init.as_code() if self.init else ""
        cond = self.cond.as_rvalue() if self.cond else ""
        next_step = self.next_step.as_code() if self.next_step else ""
        return super().as_code(cond_str=f" ({init}; {cond}; {next_step})")

class WhileLoop(Loop):
    def __init__(self, cond, head, body):
        super().__init__("while", cond, head, body)

class DoLoop(Loop):
    def __init__(self, cond, head, body):
        super().__init__("do", cond, head, body)

    def as_code(self):
        return super().as_code(cond_str="", postfix=f" while ({self.cond.as_rvalue()});\n")

class InfiniteLoop(Loop):
    def __init__(self, body):
        super().__init__("for", None, body[0], body)

    def as_code(self):
        return super().as_code(cond_str=" (;;)")

class Block(list):
    def __init__(self):
        super().__init__()

    def as_code(self):
        s = ""
        for bb in self:
            if not isinstance(bb, BasicBlock):
                s += bb.as_code()
                continue

            labels = bb.labels
            for label in labels:
                s += label.as_code()

            if bb.inlined:
                continue

            if not labels:
                s += "\n"

            if not bb.empty():
                s += textwrap.indent(bb.as_code(), "\t")
        if s.endswith("\n\n"):
            s = s[:-1]
        return s