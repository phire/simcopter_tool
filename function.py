
from itertools import pairwise, chain
import base_types
import codeview
from intervaltree import IntervalTree

import tpi
import x86
import pydemangler

from enum import Enum

class TypeUsage(Enum):
    Unknown = 0
    Argument = 1
    Return = 2
    Local = 3
    LocalStatic = 4
    GlobalData = 5
    Call = 6
    MemberImpl = 7


class Argument:
    def __init__(self, name, ty, offset):
        self.name = name
        self.ty = ty
        self.offset = offset

    def as_code(self):
        if self.name:
            return f"{self.ty.typestr()} {self.name}"
        return self.ty.typestr()

    def __repr__(self):
        return f"Argument({self.as_code()}, {self.offset:#x})"

class LocalVar:
    def __init__(self, name, ty, offset):
        self.name = name
        self.ty = ty
        self.offset = offset

    def as_code(self):
        if self.name:
            return f"{self.ty.typestr()} {self.name}"
        return self.ty.typestr()

    def __repr__(self):
        return f"LocalVar({self.as_code()}, {self.offset:#x})"

class LocalData:
    def __init__(self, name, ty, address):
        self.name = name
        self.ty = ty
        self.address = address

    def as_code(self):
        if self.name:
            return f"static const {self.ty.typestr()} {self.name}"
        return f"static const {self.ty.typestr()}"

    def __repr__(self):
        return f"LocalData({self.as_code()}, {self.offset:#x})"


class VarArgs:

    def as_code(self):
        return "..."

    def __repr__(self):
        return "VarArgs(...)"

class FakeReturn:
    def __init__(self, s):
        self.s = s

    def typestr(self):
        return self.s

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

        self.args = []
        self.local_vars = []

        def HandleChild(child):
            nonlocal self, module

            match child:
                case codeview.BpRelative():
                    ty = program.types.types[child.Type]
                    if child.Offset > 0 and child.Name not in ["__$ReturnUdt", "$initVBases"]:
                        # This is an argument
                        self.module.use_type(ty, self, TypeUsage.Argument)
                        self.args.append(Argument(child.Name, ty, child.offsetof))

                    elif child.Offset < 0:
                        self.module.use_type(ty, self, TypeUsage.Local)
                        self.local_vars.append(LocalVar(child.Name, ty, child.Offset))
                    else:
                        self.module.use_type(ty, self, TypeUsage.Unknown)
                case codeview.BlockStart():
                    for inner_child in child._children:
                        HandleChild(inner_child)
                case codeview.LocalData():
                    ty = program.types.types[child.Type]
                    self.module.use_type(ty, self, TypeUsage.LocalStatic)
                    address = program.getAddr(child.Segment, child.Offset)
                    self.local_vars.append(LocalData(child.Name, ty, address))


        for x in self.codeview._children:
            HandleChild(x)

        if self.ty:
            if self.args and isinstance(self.ty, tpi.LfMemberFunction) and self.ty.calltype != tpi.CallingConvention.ThisCall and self.args[0].name == "this":
                self.args = self.args[1:]  # remove 'this' pointer
                print(f"Warning: Function {self.name} is a member function, but has an extra 'this' pointer in args")
            if len(self.ty.args) > 1 and self.ty.args[-1].value == 0:
                self.args.append(VarArgs())  # add varargs if last arg is NoType
            assert len(self.args) == len(self.ty.args)
            self.ret = self.ty.rvtype.Type
            module.use_type(self.ret, self, TypeUsage.Return)

            if isinstance(self.ty, tpi.LfMemberFunction):
                module.use_type(self.ty.classtype.Type, self, TypeUsage.MemberImpl)

        else:
            # the type is missing. We still know all the args from codeview
            # but we will need to extract the return type from the mangled name
            demangled = pydemangler.demangle(self.syms[0].Name)
            # get everything before the function name
            if '`' in demangled:
                front = demangled.split(self.name.split("`")[0])[0]
            else:
                front = demangled.split(self.name)[0]

            # filter out extra stuff
            extra = ("public:", "private:", "protected:", "__thiscall", "__cdecl", "virtual", "static")
            ret = " ".join([x for x in front.split(" ") if x not in extra])
            self.ret = FakeReturn(ret)

        for c in self.codeview._children:
            if isinstance(c, codeview.BpRelative) and c.Name == "__$ReturnUdt":
                # This is the return-value optimization.
                # But it's sometimes missing the return type, so patch it in.
                if c.Type == 0:
                    # We need to find a pointer typeinfo
                    try:
                        class_TI = self.ret.TI
                        _refs = self.ret._refs
                    except AttributeError:
                        continue
                    types = [program.types.types[x] for x in _refs]
                    ptr = [x for x in types if isinstance(x, tpi.LfPointer) and x.Type.value == class_TI]
                    if ptr:
                        c.Type = ptr[0].TI

    def data(self):
        contrib, offset = self.contrib
        length = self.length
        return contrib._data[offset: offset+length]

    def disassemble(self):
        data = self.data()

        lines = []
        for (start, line), (end, _) in pairwise(chain(self.lines.items(), [(self.length+1, None)])):
            addr = self.address + start
            size = end - start

            insts = x86.disassemble(data[start:end], addr)
            inst = insts[0]
            lines.append((line, addr, size, insts))

        return lines

    def sig(self):
        args = [arg.as_code() for arg in self.args]

        return f"{self.ret.typestr()} {self.name}({', '.join(args)})"

    def as_code(self):
        s = f"// FUNCTION: {self.p.exename} 0x{self.address:08x}\n"

        s += f"{self.sig()} {{\n"
        p = self.p

        inserts = []
        scope = Scope(self.codeview, p)
        scopes = []

        def Foo(c, inserts):
            s = ""
            if isinstance(c, codeview.BpRelative):
                if c.Offset > 0:
                    return s # skip args
                if c.Name in ["this"]:
                    return s
                #print(c)
                ty = p.types.types[c.Type]
                s += f"\t{ty.typestr()} {c.Name};\n" # // ebp-{0-c.Offset:x}h\n"
            elif isinstance(c, codeview.BlockStart):
                addr = p.getAddr(c.Segment, c.Offset)
                assert not c.Name
                inserts += [(addr, c)]
            elif isinstance(c, codeview.LocalData):
                addr = p.getAddr(c.Segment, c.Offset)

                if c.Type == 0 and c.Name == "":
                    s += f"\t // Switch table at 0x{addr:08x}\n"
                    return s

                ty = p.types.types[c.Type]
                s += f"\tstatic const {ty.typestr()} {c.Name} = {{ /* <data@0x{addr:08x}> */ }};\n"
            elif isinstance(c, codeview.CodeLabel):
                addr = p.getAddr(c.Segment, c.Offset)
                assert c.Flags == 0
                inserts += [(addr, c)]
            elif isinstance(c, codeview.UserDefinedType):
                ty = p.types.types[c.Type]
                s += f"\t typedef {ty.typestr()} {c.Name};\n"
            else:
                print(self.name)
                print(c)
            return s

        intro = ""

        for c in self.codeview._children:
            intro += Foo(c, inserts)

        inserts = sorted(inserts, key=lambda x: x[0])

        if intro:
            s += intro + "\n"

        for line, addr, size, insts in self.disassemble():
            s += f"// LINE {line:d}:\n"

            for inst in insts:
                while inserts:
                    at, thing = inserts[0]
                    if at == inst.ip32:
                        inserts.pop(0)

                        if isinstance(thing, codeview.BlockStart):
                            scopes.append(scope)
                            scope = Scope(thing, p, scope)

                            s += f"// Block start:\n"
                            for c in thing._children:
                                s += Foo(c, inserts)
                            inserts += [(at + thing.Length, BlockEnd(c))]
                            inserts = sorted(inserts, key=lambda x: x[0])
                        elif isinstance(thing, BlockEnd):
                            s += f"// Block end:\n"
                            scope = scopes.pop()
                        elif isinstance(thing, codeview.CodeLabel):
                            name = thing.Name.replace("$", "_")
                            s += f"{name}:\n"
                            pass

                    elif at < inst.ip32:
                        breakpoint()
                    else:
                        break

                inst_str = x86.toStr(inst, scope)

                s += f"\t__asm        {inst_str};\n"

        s += "}\n\n"
        return s

    def __repr__(self):
        return f"Function({self.sig()}, {self.address:#x})"

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

class BlockEnd:
    def __init__(self, block):
        self.block = block

class Scope:
    def __init__(self, cv, p, outer=None):
        if outer is not None:
            self.stack = outer.stack.copy()
        else:
            self.stack = IntervalTree()

        def info(p, c):
            ty = p.types.types[c.Type]
            try:
                size = ty.type_size()
            except:
                print(f"Warning: Type {ty} has no size, using 0")
                size = 4
            return (c.Offset, c.Offset + size, c.Name, ty)

        stack = [info(p, c) for c in cv._children if isinstance(c, codeview.BpRelative)]
        for start, end, name, ty in stack:
            self.stack[start:end] = (name, ty)


    def stack_access(self, offset, size):
        var = self.stack.at(offset)
        if not var:
            return None
        assert len(var) == 1
        var = var.pop()

        name, ty = var.data
        var_off = offset - var.begin

        if ty.TI == 0 and name == "__$ReturnUdt":
            return name
        try:
            return ty.access(name, var_off, size)
        except ValueError:
            return None
