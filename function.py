
from itertools import pairwise, chain
import base_types
import codeview

import tpi
import x86
import pydemangler

class Argument:
    def __init__(self, name, ty):
        self.name = name
        self.ty = ty

    def as_code(self):
        if self.name:
            return f"{self.ty.typestr()} {self.name}"
        return self.ty.typestr()

    def __repr__(self):
        return f"Argument({self.as_code()})"

class VarArgs:

    def as_code(self):
        return "..."

    def __repr__(self):
        return "VarArgs(...)"

class Function:
    def __init__(self, program, module, cv, lines, contrib):
        self.module = module
        self.source_file = module.sourceFile
        self.codeview = cv
        self.lines = lines
        self.name = cv.Name
        self.contrib = contrib
        self.p = program

        self.length = cv.Len
        segment = program.sections[cv.Segment]
        self.address = segment.va + cv.Offset

        self.syms = program.globals.fromSegmentOffset(cv.Segment, cv.Offset)

        if self.contrib:
            contrib, offset = self.contrib
            contrib.register(self, offset, self.length)
        elif module.library.name in ["LIBCMTD.lib"]:
            pass
        else:
            breakpoint()

        self.ty = find_type(program, self)
        self.args = []
        self.ret = None
        args = [Argument(x.Name, program.types.types[x.Type]) for x in self.codeview._children if isinstance(x, codeview.BpRelative)
            and x.Offset > 0 and x.Name not in ["__$ReturnUdt", "$initVBases"]]
        if self.ty:
            if args and isinstance(self.ty, tpi.LfMemberFunction) and self.ty.calltype != tpi.CallingConvention.ThisCall and args[0].name == "this":
                args = args[1:]  # remove 'this' pointer
                print(f"Warning: Function {self.name} is a member function, but has an extra 'this' pointer in args")
            if len(self.ty.args) > 1 and self.ty.args[-1].value == 0:
                args.append(VarArgs())  # add varargs if last arg is NoType
            if len(args) != len(self.ty.args):
                print(self.name)
                print(self.ty)
                print(self.codeview)
                print(args)
                breakpoint()
            self.args = args
            # for arg in self.ty.args:
            #     self.args.append(Argument(None, arg))

            self.ret = self.ty.rvtype.Type
        else:
            self.args = args



    def data(self):
        contrib, offset = self.contrib
        length = self.length
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

    def sig(self):
        if self.ty is None:
            if self.syms:
                #breakpoint()
                print(f"Function {self.name} has no type, but has a symbol: {self.syms[0].Name}")
                return pydemangler.demangle(self.syms[0].Name)
            return f"UNKNOWN_SIG void {self.name}(/* no symbols */)"
        args = [arg.as_code() for arg in self.args]

        return f"{self.ret.typestr()} {self.name}({', '.join(args)})"

    def as_code(self):
        s = f"// FUNCTION: {self.p.exename} 0x{self.address:08x}\n"

        s += f"{self.sig()} {{\n"
        for line, asm in self.disassemble():
            s += f"// LINE {line:d}:\n\tasm( \n"

            for asm_line in asm.split("\n")[:-1]:
                s += f"\"\t{asm_line}\"\n"
            s += ");\n"

        s += "}\n\n"
        return s

def find_type(p, func):
    if not func.codeview:
        return None

    try:
        TI = func.codeview.Type
        if TI == 0:
            return None
    except AttributeError:
        return None

    return p.types.types[TI]