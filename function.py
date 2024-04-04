
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

    def data(self):
        contrib, offset = self.contrib
        length = self.symbols.Len
        return contrib._data[offset: offset+length]

    def disassemble(self):
        data = self.data()

        print(f"{self.source_file} {self.name} @ {self.address:08x}")
        for (start, line), (end, _) in pairwise(chain(self.lines.items(), [(self.length+1, None)])):
            insts = x86.disassemble(data[start:end], self.address + start)
            inst = insts[0]
            print(f"line {line}:")
            for inst in insts:
                print(f"      {inst.ip32:08x}    {inst}")
