
from collections import defaultdict
from itertools import pairwise, chain
import base_types
import codeview
from intervaltree import IntervalTree

import tpi
import x86
import pydemangler
import struct
from x86 import Mnemonic as M
from access import Access

import ir
from ir import *

from enum import Enum
from statement import match_statement, BasicBlock

class TypeUsage(Enum):
    Unknown = 0
    Argument = 1
    Return = 2
    Local = 3
    LocalStatic = 4
    GlobalData = 5
    Call = 6
    MemberImpl = 7
    BaseClass = 8


class Argument:
    def __init__(self, name, ty, offset):
        self.name = name
        self.ty = ty
        self.offset = offset

    def as_code(self):
        if self.name:
            return f"{self.ty.typestr(self.name)}"
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
            return f"static const {self.ty.typestr(self.name)}"
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

    def typestr(self, name=None):
        return self.s

class Line:
    def __init__(self, offset, line):
        self.offset = offset
        self.line = line

    def __repr__(self):
        return f"Line({self.offset:#x}, {self.line})"

class SwitchTable:
    def __init__(self, cv):
        self.cv = cv
        self.data = None  # will be set later

    def __repr__(self):
        return f"SwitchTable({self.cv.Offset:#x}, {self.cv.Length})"

    def access(self, name, offset, size):
        return Access(size, f"{name}[{offset//size}]", None, offset=offset)

class SwitchPointers:
    def __init__(self):
        self.data = None  # will be set later

    def __repr__(self):
        return "SwitchPointers()"

    def access(self, name, offset, size):
        return Access(size, f"{name}[{offset}]", None, offset=offset)

class BlockStart:
    def __init__(self, cv):
        self.cv = cv
        self.offset = cv.Offset
        self.length = cv.Length
        self.name = cv.Name
        self._children = cv._children
        self.scope = None  # will be set later

    def __repr__(self):
        return f"BlockStart({self.name}, {self.offset:#x}, {self.length})"

class Label:
    def __init__(self, name):
        self.name = name.replace("$", "_")

    def __repr__(self):
        return f"Label({self.name})"

class Function():
    def __init__(self, program, module, cv, lines, contrib):
        self.module = module
        self.source_file = module.sourceFile
        self.codeview = cv
        self.length = cv.Len
        self.name = cv.Name
        self.contrib = contrib
        self.p = program

        if lines.get(0) is None:
            assert lines == {}
            lines[0] = None

        lines[cv.Len] = None  # add a marker for the end of the function
        self.lines = lines

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
        self.prolog = None
        self.epilog = None
        self.targets = set()
        self.external_targets = set()

        self.labels = defaultdict(list)
        for (offset, line) in lines.items():
            self.labels[offset].append(Line(offset, line))

        self.scope = Scope(self.codeview, self.p, self)

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
                    address = program.getAddr(child.Segment, child.Offset)
                    offset = address - self.address
                    self.labels[offset].append(BlockStart(child))
                    self.labels[offset + child.Length].append(BlockEnd(child))
                    for inner_child in child._children:
                        HandleChild(inner_child)
                case codeview.LocalData():
                    address = program.getAddr(child.Segment, child.Offset)
                    if child.Type == 0 and child.Name == "":
                        # This is a switch table
                        offset = address - self.address
                        self.labels[offset].append(SwitchTable(child))

                        return
                    ty = program.types.types[child.Type]
                    self.module.use_type(ty, self, TypeUsage.LocalStatic)
                    self.local_vars.append(LocalData(child.Name, ty, address))

                case codeview.CodeLabel():
                    address = program.getAddr(child.Segment, child.Offset)
                    offset = address - self.address
                    self.labels[offset].append(Label(child.Name))


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


    def post_process(self):
        if self.contrib:
            self.parse_body()

    def data(self):
        contrib, offset = self.contrib
        length = self.length
        return contrib._data[offset: offset+length]


    def disassemble(self):
        data = self.data()

        labels = sorted(self.labels.items(), key=lambda x: x[0])

        lines = []

        for (start, label), (end, _) in pairwise(labels):
            addr = self.address + start
            size = end - start

            insts = []
            def newbasicblock(inst):
                nonlocal self, lines, addr, size, label, insts

                assert inst.op_kind(0) == x86.OpKind.NEAR_BRANCH32
                target = inst.near_branch32
                if target < self.address or target >= self.address + self.length:
                    self.external_targets.add(target)
                elif target != inst.next_ip32:
                    self.targets.add(target)
                lines.append((label, addr, size, insts))
                new_addr = inst.next_ip32
                size -= new_addr - addr
                addr = new_addr
                insts = []
                label = []

            for inst in x86.disassemble(data[start:end], addr):
                insts.append(inst)
                match inst.mnemonic:
                  case M.JMP if inst.op_kind(0) == x86.OpKind.MEMORY:
                    addr = inst.memory_displacement
                    if addr > self.address and addr < self.address + self.length:
                        lines.append((label, addr, size, insts))
                        start = inst.next_ip32 - self.address
                        insts = data[start:end]
                        label = [SwitchPointers()]
                        break
                    else:
                        breakpoint()
                  case M.JMP:
                    newbasicblock(inst)
                  case M.JA | M.JAE | M.JB | M.JBE | M.JE | M.JG | M.JGE | M.JL | \
                       M.JLE | M.JNE | M.JNO | M.JNP | M.JNS | M.JO | M.JP | M.JS:
                    newbasicblock(inst)
                  case M.JRCXZ, M.JCXZ, M.JECXZ:
                    assert False, "Unexpected jump instruction: " + inst.mnemonic.name
                #   case M.CALL:
                #     assert inst.op_kind(0) == x86.OpKind.NEAR_BRANCH32
                #     target = inst.near_branch32
                #     self.external_targets.add(target)

            if insts:
                lines.append((label, addr, size, insts))

        return lines



    def parse_body(self):
        scopes = []
        scope = self.scope

        ir.set_scope(scope)

        raw_lines = self.disassemble()
        bblocks = []
        for labels, addr, size, raw_insts in raw_lines:
            skip = False
            for label in labels:
                if isinstance(label, BlockStart):
                    scopes.append(scope)
                    scope = Scope(label.cv, self.p, self, scope)
                    label.scope = scope
                    ir.set_scope(scope)
                elif isinstance(label, BlockEnd):
                    scope = scopes.pop()
                    ir.set_scope(scope)
                elif isinstance(label, (SwitchPointers, SwitchTable)):
                    skip = True
                    label.data = raw_insts
                    scope.staticlocals[addr:addr + size] = (f"{label.__class__.__name__}{addr}", label)

                    bblocks.append(label)
            if skip:
                continue

            state = ir.State()
            insts = []
            for inst in raw_insts:
                # insert target labels, splitting basic blocks when needed
                if inst.ip32 in self.targets:
                    if insts:
                        bblocks.append(BasicBlock(insts, scope, labels))
                        labels = []
                        insts = []
                        state = ir.State()

                    labels.append(Label(f"_T{inst.ip32 - self.address:02x}"))
                insts.append(I.from_inst(inst, state))

            bblocks.append(BasicBlock(insts, scope, labels))

        self.prolog, tail  = match_prolog(bblocks.pop(0))
        if tail:
            bblocks.insert(0, tail)

        if self.prolog:
            head, self.epilog = match_epilog(bblocks.pop())
            assert head is not None
            bblocks.append(head)
        self.body = bblocks

        for bblock in self.body:
            continue
            if isinstance(labels and labels[0], (SwitchPointers, SwitchTable)):
                # skip switch tables
                continue
            stmt = match_statement(bblock)
            if stmt:
                for inst in insts:
                    print(inst.as_code(), end="")
                print(f"Statement: {stmt}")
                #breakpoint()


    def sig(self):
        args = [arg.as_code() for arg in self.args]
        modifiers = ""
        if isinstance(self.codeview, codeview.LocalProcedureStart):
            modifiers += "static "

        return f"{modifiers}{self.ret.typestr()} {self.name}({', '.join(args)})"

    def is_synthetic(self):
        if self.name.startswith("$E"):
            return True
        if isinstance(self.ty, tpi.LfMemberFunction):
            field = self.ty._field
            return field.synthetic
        return False



    def as_code(self):
        s = "// SYNTHETIC: " if self.is_synthetic() else "// FUNCTION: "
        if self.ty:
            TI = self.ty.TI
        else:
            TI = 0
        s += f"{self.p.exename} 0x{self.address:08x}\n"

        s += f"{self.sig()} {{\n"
        p = self.p

        intro = ""

        def cv_string(c):
            nonlocal p
            if isinstance(c, codeview.BpRelative):
                if c.Offset > 0:
                    return "" # skip args
                if c.Name in ["this"]:
                    return ""
                ty = p.types.types[c.Type]
                return f"\t{ty.typestr(c.Name)};\n" # // ebp-{0-c.Offset:x}h\n"
            elif isinstance(c, codeview.LocalData):
                addr = p.getAddr(c.Segment, c.Offset)

                ty = p.types.types[c.Type]
                return f"\tstatic const {ty.typestr(c.Name)} = {{ /* <data@0x{addr:08x}> */ }};\n"
            elif isinstance(c, codeview.UserDefinedType):
                ty = p.types.types[c.Type]
                return f"\t typedef {ty.typestr(c.Name)};\n"
            return ""

        for c in self.codeview._children:
            intro += cv_string(c)

        if intro:
            s += intro + "\n"

        if not self.prolog:
            s += "\t// Couldn't match prolog\n"
        elif self.prolog.cleanup_fn:
            s += f"\t// Function registers exception cleanup function at 0x{self.prolog.cleanup_fn.value:08x}\n"

        try:
            body = self.body
        except:
            body = []

        for bb in body:
            if not isinstance(bb, BasicBlock):
                if isinstance(bb, SwitchPointers):
                    s += f"// Switch pointers\n"
                if isinstance(bb, SwitchTable):
                    s += f"// Switch table\n"
                continue

            labels = bb.labels
            insts = bb.insts
            for label in labels:
                if isinstance(label, BlockStart):
                    s += f"// Block start:\n"
                    for c in label.cv._children:
                        s += cv_string(c)
                if isinstance(label, BlockEnd):
                    s += f"// Block end:\n"
                if isinstance(label, Label):
                    s += f"{label.name}:\n"
                if isinstance(label, Line) and label.line is not None:
                    s += f"// LINE {label.line:d}:\n"
            if not labels:
                s += "\n"

            for inst in insts:
                s += inst.as_code()

        if s[-2:] == "\n\n":
            s = s[:-1]

        if self.prolog and not self.epilog:
            s += "\t// Couldn't match epilog\n"

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
    def __init__(self, cv, p, fn, outer=None):
        if outer is not None:
            self.stack = outer.stack.copy()
            self.staticlocals = outer.staticlocals.copy()
        else:
            self.stack = IntervalTree()
            self.staticlocals = IntervalTree()

        def info(p, c):
            ty = p.types.types[c.Type]
            try:
                size = ty.type_size()
            except:
                size = 0
            if not size:
                print(f"Warning: Type {ty} has no size, using 4")
                size = 4
            return (c.Offset, c.Offset + size, c.Name, ty)

        stack = [info(p, c) for c in cv._children if isinstance(c, codeview.BpRelative)]
        for start, end, name, ty in stack:
            self.stack[start:end] = (name, ty)

        def handle_staticlocal(c):
            nonlocal p, self
            if c.Type == 0 and c.Name == "":
                return
            addr = p.getAddr(c.Segment, c.Offset)
            ty = p.types.types[c.Type]
            size = ty.type_size()

            if size == 0:
                # todo: get size from somewhere else?
                size = 1

            self.staticlocals[addr:addr + size] = (c.Name, ty)

        for c in cv._children:
            if isinstance(c, codeview.LocalData):
                handle_staticlocal(c)

        self.fn = fn
        self.p = p


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

    def data_access(self, addr, size, offset_expr=None):
        # might be a static local
        local = self.staticlocals.at(addr)
        if local:
            local = local.pop()
            name, ty = local.data
            offset = addr - local.begin

            if not offset and offset_expr:
                offset = offset_expr
                offset_expr = None
            access = ty.access(name, offset, size)

            if offset_expr is not None:
                reg = offset_expr.expr.reg
                return f"{access} + [{reg}{offset_expr.scale_str()}]"
            return access

        # otherwise, try globals
        item = self.p.getItem(addr)
        if item:
            offset = addr - item.address
            if not offset and offset_expr is not None:
                offset = offset_expr
            return item.ty.access(item.name, offset, size)
        return None

    def code_access(self, pc, addr):
        fnoffset = addr - self.fn.address

        if fnoffset > 0 and fnoffset < self.fn.length:
            # within current function
            if addr in self.fn.targets:

                return f"_T{fnoffset:02x}"
            return None

        fn = self.p.getItem(addr)
        if isinstance(fn, Function):
            return fn

        pass



class Prolog:
    def __init__(self, line, stack_adjust, this_local=None, cleanup_fn=None):
        self.line = line
        self.stack_adjust = stack_adjust
        self.this_local = this_local
        self.cleanup_fn = cleanup_fn

    def __repr__(self):
        s = f"Prolog(line={self.line}, stack_adjust={self.stack_adjust}"
        if self.this_local is not None:
            s += f", this={self.this_local})"
        if self.cleanup_fn is not None:
            s += f", cleanup_fn={self.cleanup_fn}"
        return s + ")"

def match_prolog(bblock):

    insts = bblock.insts

    match insts:
        case [I("push", "ebp"), I("mov", ("ebp", "esp")), *tail]:
            pass
        case _:
            #breakpoint()
            return None, bblock

    match tail:
        case [I("push", Const(-1)),
              I("push", Const() as cleanup_fn),
              I("mov", ("eax",  SegOverride("fs", MemDisp(0)))),
              I("push", "eax"),
              I("mov", (SegOverride("fs", MemDisp(0)), "esp")),
              I("sub", ("esp", Const(4))),
              *tail]:
            pass
        case [I("push", Const(-1)),
              I("push", Const() as cleanup_fn),
              I("mov", ("eax",  SegOverride("fs", MemDisp(0)))),
              I("push", "eax"),
              I("mov", (SegOverride("fs", MemDisp(0)), "esp")),
              *tail]:
            # without extra sub esp, 4
            pass
        case tail:
            cleanup_fn = None

    match tail:
        case [I("sub", ("esp", Const() as stack_adjust)), *tail]:
            pass
        case [I("mov", ("eax", Const() as stack_adjust)), I("call", 0x0056AC60), *tail]:
            pass
        case tail:
            stack_adjust = 0

    match tail:
        case [I("push", "ebx"), I("push", "esi"), I("push", "edi"),
              I("mov", (LocalAddr as this_local, "ecx")),
              *tail]:
                pass
        case [I("push", "ebx"), I("push", "esi"), I("push", "edi"),
              *tail]:
                this_local = None
        case tail:
            return None, bblock

    new_bblock = None
    if tail:
        new_bblock = BasicBlock(tail, bblock.scope, list())
    return Prolog(bblock.labels, stack_adjust, this_local, cleanup_fn), new_bblock

class Epilog:
    def __init__(self, line, stack_adjust):
        self.line = line
        self.stack_adjust = stack_adjust

    def __repr__(self):
        return f"Epilog(stack_adjust={self.stack_adjust})"

def match_epilog(bblock):
    insts = bblock.insts

    match insts:
        case [*head, I("pop", "edi"), I("pop", "esi"), I("pop", "ebx"), I("leave", ()), I("ret", Const() as stack_adjust)]:
            pass
        case [*head,  I("pop", "edi"), I("pop", "esi"), I("pop", "ebx"), I("leave", ()), I("ret")]:
            stack_adjust = 0
        case _:
            breakpoint()
            return bblock, None


    new_bblock = BasicBlock(head, bblock.scope, bblock.labels)
    return new_bblock, Epilog(bblock.labels, stack_adjust)



