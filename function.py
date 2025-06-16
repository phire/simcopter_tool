from collections import defaultdict
from itertools import pairwise
import textwrap

import construct
from iced_x86 import Decoder
import base_types
import codeview
from intervaltree import IntervalTree

from item import Data, Item
import tpi
import x86
import pydemangler
from x86 import Mnemonic as M
from access import Access

import ir
from ir import *

from usage import TypeUsage
from ref import BasicBlockRef
from scope import Scope

from statement import match_return, match_statement, BasicBlock

class VarArgs:
    def __init__(self):
        self.hidden = False
        self.size = 0

    def as_code(self):
        return "..."

    def __repr__(self):
        return "VarArgs(...)"


class FakeReturn:
    def __init__(self, s):
        self.s = s

    def typestr(self, name=None):
        return self.s

    def type_size(self):
        return 4

class Line:
    def __init__(self, offset, line):
        self.offset = offset
        self.line = line

    def as_code(self):
        if self.line is not None:
            return f"// LINE {self.line:d}:\n"
        return ""

    def __repr__(self):
        return f"Line({self.offset:#x}, {self.line})"

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
        return f"SwitchPointers({fn.name}, {self.address:#x}, {len(self.data)})"

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

class BlockStart:
    def __init__(self, cv, scope):
        self.cv = cv
        self.offset = cv.Offset
        self.length = cv.Length
        self.name = cv.Name
        self._children = cv._children
        self.scope = scope

    def __repr__(self):
        return f"BlockStart({self.name}, {self.offset:#x}, {self.length})"

    def as_code(self):
        s = f"// Block start:\n"
        s += self.scope.locals_as_code()
        return s

class BlockEnd:
    def __init__(self, block, scope):
        self.block = block
        self.parent_scope = scope

    def __repr__(self):
        return f"BlockEnd({self.block.Name}, {self.block.Offset:#x}, {self.block.Length})"

    def as_code(self):
        return f"// Block end:\n"

class Label:
    def __init__(self, name):
        self.name = name.replace("$", "_")

    def __repr__(self):
        return f"Label({self.name})"

    def as_code(self):
        return f"{self.name}:\n"

class NoFallthrough:
    def __repr__(self):
        return "NoFallthrough()"

    def as_code(self):
        return "// No fallthrough\n"

class ExternalTarget:
    def __init__(self, address):
        self.address = address

    def __repr__(self):
        return f"ExternalTarget(0x{self.address:08x})"

class Function(Item):
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

        self.ty = cv.Type if cv else None
        self.args = []
        self.ret = None

        self.local_vars = []
        self.prolog = None
        self.epilog = None
        self.return_bb = None
        self.external_targets = set()

        labels = defaultdict(list)
        for (offset, line) in lines.items():
            labels[offset].append(Line(offset, line))

        self.staticlocals = IntervalTree()  # static locals for this function
        self.scope = Scope(self.codeview, self.p, self)
        self.calling_convention = None
        self.stack_adjust = 0 # adjustment to the stack pointer after return
        self.return_udt = None

        if self.ty:
            self.ret = self.ty.rvtype
            module.use_type(self.ret, self, TypeUsage.Return)
            self.calling_convention = self.ty.calltype
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
            ret = " ".join([x for x in front.split(" ") if x and x not in extra])
            if ret == "":
                ret = "void"
            self.ret = program.types.fromStr(ret)
            if not self.ret:
                self.ret = FakeReturn(ret)

            # calling convention:
            if "__thiscall" in front:
                self.calling_convention = tpi.CallingConvention.ThisCall
            elif "__cdecl" in front:
                self.calling_convention = tpi.CallingConvention.NearC
            else:
                self.calling_convention = tpi.CallingConvention.NearStd


        def HandleChild(child, scope):
            nonlocal self, module

            match child:
                case codeview.BlockStart():
                    address = program.getAddr(child.Segment, child.Offset)
                    offset = address - self.address
                    new_scope = Scope(child, program, self, scope)
                    labels[offset].append(BlockStart(child, new_scope))
                    labels[offset + child.Length].append(BlockEnd(child, scope))
                    for inner_child in child._children:
                        HandleChild(inner_child, new_scope)
                case codeview.BpRelative():
                    if child.Name == "__$ReturnUdt":
                        # This is the return-value optimization.
                        # But it's sometimes missing the return type, so patch it in.
                        self.return_udt = child
                        if not child.Type:
                            # We need to find a pointer typeinfo
                            try:
                                class_TI = self.ret.TI
                                _refs = self.ret._refs
                            except AttributeError:
                                return
                            types = [program.types.types[x] for x in _refs]
                            ptr = [x for x in types if isinstance(x, tpi.LfPointer) and x.Type.TI == class_TI]
                            if ptr:
                                child.Type = ptr[0]

                case codeview.LocalData():
                    if not child.Type and child.Name == "":
                        # This is a switch table
                        address = program.getAddr(child.Segment, child.Offset)
                        offset = address - self.address
                        labels[offset].append(SwitchTable(child, offset, self))


                case codeview.CodeLabel():
                    address = program.getAddr(child.Segment, child.Offset)
                    offset = address - self.address
                    labels[offset].append(Label(child.Name))

        for x in self.codeview.children():
            HandleChild(x, self.scope)

        if self.args and self.calling_convention != tpi.CallingConvention.ThisCall and self.args[0].name == "this":
            self.args[0].hidden = True
            print(f"Warning: Function {self.name} is a member function, but has an extra 'this' pointer in args")

        if self.ty:
            if len(self.ty.args) > 1 and self.ty.args[-1].TI == 0:
                self.args.append(VarArgs())  # add varargs if last arg is NoType
            assert len([x for x in self.args if not x.hidden]) == len(self.ty.args)

            if isinstance(self.ty, tpi.LfMemberFunction):
                module.use_type(self.ty.classtype, self, TypeUsage.MemberImpl)

        if self.calling_convention != tpi.CallingConvention.NearC and self.args:
            last_arg = self.args[-1]
            self.stack_adjust = last_arg.bp_offset + last_arg.size - 8

        self.find_all_basic_blocks(labels)

    def deref(self, offset, size):
        raise ValueError("Function deref not implemented")

    def getLabel(self, offset):
        if bb := self.body.get(offset, None):
            return next((x for x in bb.labels if isinstance(x, Label)), None)
        return None

    def getJumpDest(self, offset):
        if bb := self.body.get(offset, None):
            return BasicBlockRef(bb)

    def is_thiscall(self):
        return self.calling_convention == tpi.CallingConvention.ThisCall

    def is_library(self):
        return self.source_file and "msdev\\include" in self.source_file.lower()

    def post_process(self):
        if not self.is_library() and self.contrib:
            self.parse_body()

    def find_all_basic_blocks(self, labels):
        """Scan the code to find all internal branches and switch tables."""
        data = self.data()
        if not data:
            return

        addr = self.address
        targets = defaultdict(list)
        fallthrough = set()
        extern = dict()

        # decode all instructions to find jump targets
        decoder = Decoder(32, data, ip=addr)
        while decoder.can_decode:
            inst = decoder.decode()

            match inst.mnemonic:
                case M.JMP if inst.op_kind(0) == x86.OpKind.MEMORY:
                    target_addr = inst.memory_displacement
                    start = target_addr - addr
                    if target_addr >= inst.next_ip32 and target_addr < self.address + self.length:
                        if target_addr - inst.next_ip32 > 4:
                            print(f"Larger gap of {target_addr - inst.next_ip32} bytes in function {self.name} at 0x{inst.next_ip32:08x}")

                        # find an upper bound for the end. Either the next known target
                        end = min((x for x in targets if x > inst.next_ip32), default=addr + self.length)
                        end_offset = end - addr

                        switch = SwitchPointers(start, data[start:end_offset], self)
                        labels[start].append(switch)
                        for target in switch.targets:
                            targets[target].append(switch)

                        # Get the actual end of the switch table
                        end = target_addr + switch.length
                        end_offset = end - addr
                        if (table := labels.get(end_offset, None)) and isinstance(table[0], SwitchTable):
                            table = table[0]

                            start = end_offset
                            # calculate another upper bound
                            end = min((x for x in targets if x > end_offset), default=addr + self.length)
                            table.populate(data[start:end], switch)
                            end_offset = start + table.length
                            end = addr + end_offset

                        labels[end_offset] += []

                        # restart decoding after the switch table
                        diff = end - inst.next_ip32
                        decoder.ip += diff
                        decoder.position += diff

                    else:
                        # Reused switch table
                        switch = labels[start][0]
                        assert isinstance(switch, SwitchPointers), f"Expected SwitchPointers at {start:#x}, got {switch}"
                case M.JMP | M.JA | M.JAE | M.JB | M.JBE | M.JE | M.JG | M.JGE | M.JL | \
                    M.JLE | M.JNE | M.JNO | M.JNP | M.JNS | M.JO | M.JP | M.JS:

                    target = inst.near_branch32
                    if target < self.address or target >= self.address + self.length:
                        self.external_targets.add(target)
                        extern[inst.ip32] = target
                    else:
                        targets[target].append(inst.ip32)

                    # End the basic block by inserting a dummy label
                    labels[inst.next_ip32 - addr] += []
                    if inst.mnemonic != M.JMP:
                        fallthrough.add(inst.next_ip32)

                case M.JRCXZ, M.JCXZ, M.JECXZ:
                    assert False, "Unexpected jump instruction: " + inst.mnemonic.name

                case M.RET:
                    labels[inst.next_ip32 - addr] += [NoFallthrough()]

        # add targets to the labels dictionary (which already has lines, blocks and predefined labels)
        for target in targets.keys():
            offset = target - self.address
            if not next((x for x in labels[offset] if isinstance(x, Label)), None):
                labels[offset].append(Label(f"_T{offset:02x}"))

        scope = self.scope
        intervals = IntervalTree()
        self.body = {}

        # Put a basic block between each set of labels
        labels = sorted(labels.items(), key=lambda x: x[0])
        for (start, label), (end, _) in pairwise(labels):
            if switch := next((x for x in label if isinstance(x, (SwitchPointers, SwitchTable))), None):
                if switch.data is None:
                    switch.data = data[start:end]

                self.body[start] = intervals[start:end] = switch
                self.staticlocals[self.address + start:self.address + end] = switch
                continue
            elif block := next((x for x in label if isinstance(x, BlockStart)), None):
                scope = block.scope
            elif end_block := next((x for x in label if isinstance(x, BlockEnd)), None):
                scope = end_block.parent_scope
            self.body[start] = intervals[start:end] = BasicBlock(label, scope, start, end)

        # Create incoming edges for each basic block
        for bb in self.body.values():
            if not isinstance(bb, BasicBlock):
                continue
            for incomming in targets[bb.address()]:
                if isinstance(incomming, int):
                    # Lookup the basic block from the interval tree
                    incomming = intervals[incomming - self.address].pop().data
                    incomming.outgoing = bb
                bb.incomming.add(incomming)

            if bb.address() in fallthrough:
                fallthrough_bb = intervals[bb.start - 1].pop().data
                fallthrough_bb.fallthrough = bb
                bb.fallfrom = fallthrough_bb

        # add extra outgoing edges
        for jump_addr, target in extern.items():
            bb = intervals[jump_addr - self.address].pop().data
            bb.outgoing = ExternalTarget(target)

        # Fixup fallthrough edges
        for aa, bb in pairwise(self.body.values()):
            if not isinstance(aa, BasicBlock) or not isinstance(bb, BasicBlock):
                continue
            no_fallthrough = next((x for x in bb.labels if x is NoFallthrough()), None)
            if  aa.fallthrough or aa.outgoing or no_fallthrough:
                continue

            aa.fallthrough = bb
            bb.fallfrom = aa

    def parse_body(self):
        self.prolog, tail = match_prolog(self.body[0])
        if tail:
            self.body[0] = tail # replace the original prolog block to preserve sort order
        else:
            del self.body[0]

        if self.prolog:
            *_, last_key = self.body.keys()
            last_block = self.body.pop(last_key)
            head, self.epilog = match_epilog(last_block)

            assert head is not None
            self.body[head.start] = head
            assert self.epilog.stack_adjust == self.stack_adjust
        if not self.epilog:
            return

        *_, self.return_bb = self.body.values()

        matched_return = [match_return(bb, self.ret, self.return_bb) for bb in self.return_bb.incomming]

        if all(matched_return):
            # all returns matched, get rid of the label
            self.return_bb.labels = [x for x in self.return_bb.labels if not isinstance(x, Label)]
            self.return_bb.label = None
        else:
            ret = Label("__RETURN")
            self.return_bb.labels = [x for x in self.return_bb.labels if not isinstance(x, Label)] + [ret]
            self.return_bb.label = ret


        for bb in self.body.values():
            if isinstance(bb, (SwitchPointers, SwitchTable)) or bb.empty() or bb.inlined or bb.statements:
                # skip switch tables
                continue
            stmts = match_statement(bb)
            if stmts:
                bb.statements = stmts
                #breakpoint()

    def return_reg(self):
        if self.ret and self.ret != base_types.Void:
            try:
                match self.ret.type_size():
                    case 1: return Register.AL
                    case 2: return Register.AX
                    case 4: return Register.EAX
            except: pass
        return None

    def sig(self):
        args = [arg.as_code() for arg in self.args if not arg.hidden]
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

        intro = self.scope.locals_as_code()

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

        for bb in body.values():
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

        if s[-2:] == "\n\n":
            s = s[:-1]

        if self.prolog and not self.epilog:
            s += "\t// Couldn't match epilog\n"

        s += "}\n\n"
        return s

    def __repr__(self):
        return f"Function({self.sig()}, {self.address:#x})"

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

    insts = bblock.insts()

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
        tail_len = tail[-1].inst.next_ip32 - tail[0].inst.ip32
        new_bblock = BasicBlock(list(), bblock.scope, bblock.end - tail_len, bblock.end)
    return Prolog(bblock.labels, stack_adjust, this_local, cleanup_fn), new_bblock

class Epilog:
    def __init__(self, line, stack_adjust):
        self.line = line
        self.stack_adjust = stack_adjust

    def __repr__(self):
        return f"Epilog(stack_adjust={self.stack_adjust})"

def match_epilog(bblock):
    insts = bblock.insts()

    match insts:
        case [*head, I("pop", "edi"), I("pop", "esi"), I("pop", "ebx"), I("leave", ()), I("ret", Const() as stack_adjust)]:
            pass
        case [*head,  I("pop", "edi"), I("pop", "esi"), I("pop", "ebx"), I("leave", ()), I("ret")]:
            stack_adjust = 0
        case _:
            breakpoint()
            return bblock, None


    head_len = head[-1].inst.next_ip32 - head[0].inst.ip32 if head else 0
    bblock.end = bblock.start + head_len
    line = next((x for x in bblock.labels if isinstance(x, Line)), None)
    return bblock, Epilog(line, stack_adjust)



