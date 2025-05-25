
from itertools import pairwise, chain
import x86

class Function:
    def __init__(self, program, module, symbols, lines, contrib):
        self.module = module
        self.source_file = module.sourceFile
        self.symbols = symbols
        self.lines = lines
        self.name = symbols.Name
        self.contrib = contrib

        self.length = symbols.Len
        segment = program.sections[symbols.Segment]
        self.address = segment.va + symbols.Offset

        if self.contrib:
            contrib, offset = self.contrib
            contrib.register(self, offset, self.length)
        elif module.library.name in ["LIBCMTD.lib"]:
            pass
        else:
            breakpoint()


    def data(self):
        contrib, offset = self.contrib
        length = self.symbols.Len
        return contrib._data[offset: offset+length]

    def disassemble(self):
        data = self.data()

        lines = []
        for (start, line), (end, _) in pairwise(chain(self.lines.items(), [(self.length+1, None)])):
            insts = x86.disassemble(data[start:end], self.address + start)
            inst = insts[0]
            s = ""
            for inst in insts:
                s += f"      {inst.ip32:08x}    {inst}\n"
            lines.append((line, s))

        return lines
