

from labels import Label
from statement import BasicBlock
from switch import SwitchPointers
import heapq

def is_bb(bb):
    return isinstance(bb, BasicBlock)

def find_backedges(body):
    # Body is already pretty much a control flow graph, but we want them sorted by visit order

    to_visit = [x for x in body.values() if is_bb(x) and not (x.fallfrom or x.incomming)]
    heapq.heapify(to_visit)

    backedges = set()
    visited = set()
    body_iter = iter(body.values())
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
                        backedges.add(out)
                        assert out.start < bb.start, f"Backedge from {out.start:#x} to {bb.start:#x}"
                    case BasicBlock() if (not out.fallfrom or out.fallfrom in visited) and out.incomming.issubset(visited):
                        # all incoming edges have been visited
                        heapq.heappush(to_visit, out)
            case SwitchPointers():
                fn_addr = bb.fn.address
                blocks = [bb.fn.getJumpDest(x - fn_addr).bb for x in bb.targets]
                heapq.heapify(blocks)
                heapq.merge(to_visit, blocks)
    for bb in body.values():
        assert bb in visited

    return list(backedges)

def find_loops(body):
    backedges = find_backedges(body)

    for bb in backedges:
        sources = [x for x in bb.incomming if x.branch_id > bb.branch_id]

        if any(isinstance(l, Label) and not l.name.startswith("_T") for l in bb.labels):
            # this is probably a goto...
            continue

        loop_head = bb
        loop_end = max(sources, key=lambda x: x.branch_id)

        if not loop_end.is_conditional() and loop_head.outgoing and loop_head.outgoing.start == loop_end.end:
            # this is a while loop

            loop_head.set_label(f"__WHILE_{bb.start:02x}")
        elif loop_end.is_conditional():
            # this is a do-while loop
            loop_head.set_label(f"__DO_{bb.start:02x}")
            loop_end.set_label(f"__DO_WHILE_{bb.start:02x}")
        elif not loop_head.fallfrom and loop_head.before.outgoing == loop_head.after:
            # it's a for loop.
            cond = loop_head.fallthrough
            initializer = loop_head.before

            initializer.set_label(f"_FOR_{bb.start:02x}")
            cond.set_label(f"_FOR_COND_{bb.start:02x}")
            loop_head.set_label(f"_FOR_NEXT_{bb.start:02x}")

        else:
            loop_head.set_label(f"_LOOP_{bb.start:02x}")

