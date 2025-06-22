import construct
from access import Access


class SwitchTable:
    def __init__(self, cv, offset, fn):
        self.fn = fn
        self.offset = offset
        self.cv = cv
        self.data = None  # will be set later
        self.pointers = None
        self.length = None

    def __repr__(self):
        return f"SwitchTable({self.fn.name}, {self.offset:#x}"

    def as_code(self):
        s = f"// Switch table\n"
        if not self.data:
            s += f"//   No data available yet\n"
        else:
            s += f"//  [{', '.join(f'{b}' for b in self.data)}]\n"
        return s


    def access(self, offset, size):
         return Access(size, f"_SwitchTable_{self.offset:x}[{offset//size}]", None, offset=offset)

    def populate(self, data, pointers):
        """ Now that we have the corresponding switch pointers, we can probably
            work out how long this table is"""
        self.pointers = pointers
        count = len(pointers.targets)
        assert count < 256
        for i, b in enumerate(data):
            if b >= count: break
        self.length = i
        self.data = data[:i]

class SwitchPointers:
    def __init__(self, offset, data, fn):
        self.fn = fn
        self.offset = offset
        self.targets = []
        end = offset + len(data)
        for i, t in enumerate(construct.GreedyRange(construct.Int32ul).parse(data)):
            element_offset = offset + i * 4
            if element_offset >= end:
                break
            if t < end:
                end = t

            if not (t >= fn.address and t < fn.address + fn.length): # should be within function bounds
                end = element_offset
                break

            self.targets.append(t)
        self.length = end - offset
        self.data = data[:self.length]

    def __repr__(self):
        return f"SwitchPointers({self.fn.name}, {self.address:#x}, {len(self.data)})"

    def as_code(self):
        s = f"// Switch pointers:\n"
        fn_addr = self.fn.address
        for t in self.targets:
            label = self.fn.getLabel(t - fn_addr)
            if not label:
                s += f"//   0x{t:08x} (no label)\n"
            else:
                s += f"//   {label.name}\n"
        return s


    def access(self, offset, size):
        return Access(size, f"_Switch_{self.offset:x}[{offset}]", None, offset=offset)