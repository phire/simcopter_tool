import textwrap
import codeview
from intervaltree import IntervalTree

from item import Item, Data
from usage import TypeUsage


class Local:
    def __init__(self, name, ty, offset, size, scope, fn):
        self.name = name
        self.ty = ty
        self.bp_offset = offset
        self.size = size
        self.scope = scope
        self.fn = fn

    def __str__(self):
        return self.name

    def as_code(self, prefix=""):
        if self.name:
            return f"{prefix}{self.ty.typestr(self.name)}"
        return self.ty.typestr()

    def deref(self, offset, size):
        return self.ty.deref(self, offset, size)

    def access(self, offset, size):

        return self.ty.access(self, offset, size)

    def postfix(self):
        return ""

class LocalVar(Local):
    def as_code(self):
        prefix = f"{ f"/*bp-{-self.bp_offset:#x}*/" :12} "
        return super().as_code(prefix=prefix)

    def postfix(self):
        if self.size == 4:
            return ""
        return f" // {self.size:#x} bytes"

    def __repr__(self):
        return f"LocalVar({super().as_code()}, {self.bp_offset:#x})"

class Argument(Local):
    def __repr__(self):
        return f"Argument({self.as_code()}, {self.bp_offset:#x})"

class LocalData(Local):
    def __init__(self, name, ty, size, scope, fn, item):
        super().__init__(name, ty, 0, size, scope, fn)
        self.item: Item = item

    def as_code(self):
        return f"// StaticLocal: {self.item.address:#010x}\n" + self.item.as_code()

    def __repr__(self):
        return f"LocalData({self.item.ty.typestr(self.name)}, {self.item.access:#x})"

class LocalTypeDef:
    def __init__(self, name, ty):
        self.name = name
        self.ty = ty

    def as_code(self):
        return f"typedef {self.ty.typestr()} {self.name}"

    def __repr__(self):
        return f"TypeDef({self.name}, {self.ty.typestr()})"

    def postfix(self):
        return ""

class RefTo:
    def __init__(self, var, offset):
        self.var = var
        self.offset = offset

    def __str__(self):
        if isinstance(self.offset, int):
            offset = f"{self.offset:#x}"
        else:
            offset = str(self.offset)
        return f"{self.var}<+{offset}>"

    def as_asm(self):
        return f"{self.var.as_asm()}[{self.offset}]"

    def access(self, offset, size):
        breakpoint()
        assert self.offset == 0 and offset == 0 and size == 4
        return self

    def deref(self, offset, size):
        return self.var.access(self.offset + offset, size)


class FunctionRef:
    def __init__(self, fn, offset=0):
        self.fn = fn
        self.offset = offset

    def __repr__(self):
        return f"FunctionRef({self.fn.name})"

    def __eq__(self, other):
        if isinstance(other, FunctionRef):
            return self.fn == other.fn
        if isinstance(other, str):
            return self.fn.name == other
        if isinstance(other, int):
            return self.fn.address == other
        return False

    def as_code(self):
       if self.offset:
            return f"{self.fn.name}+{self.offset:#x}"
       return f"{self.fn.name}"

    def as_asm(self):
        return self.as_code()


class BasicBlockRef:
    def __init__(self, addr, label, scope):
        self.label = label
        self.addr = addr
        self.scope = scope

    def __repr__(self):
        return f"BasicBlockRef({self.label})"

    def as_code(self):
        return self.label.name

    def as_asm(self):
        return self.label.name

class Scope:
    def __init__(self, cv, p, fn, outer=None):
        if outer is not None:
            self.stack = outer.stack.copy()
        else:
            self.stack = IntervalTree()

        self.locals = [] # local declarations for this block

        for c in cv._children:
            if isinstance(c, codeview.BpRelative): # args and locals
                try: size = max(4, c.Type.type_size())
                except: size = 4

                if c.Name in ["this", "__$ReturnUdt", "$initVBases"]:
                    local = LocalVar(c.Name, c.Type, c.Offset, size, self, fn)
                    fn.local_vars.append(local)
                elif c.Offset < 0:
                    local = LocalVar(c.Name, c.Type, c.Offset, size, self, fn)
                    fn.local_vars.append(local)
                    fn.module.use_type(c.Type, fn, TypeUsage.Local)

                    self.locals.append(local)
                else:
                    local = Argument(c.Name, c.Type, c.Offset, size, self, fn)
                    fn.module.use_type(c.Type, fn, TypeUsage.Argument)
                    fn.args.append(local)

                self.stack[c.Offset:c.Offset + size] = local
            elif isinstance(c, codeview.LocalData): # static locals
                if not c.Type and c.Name == "": # this is a switch table
                    continue
                addr = p.getAddr(c.Segment, c.Offset)
                size = c.Type.type_size()

                item = p.getItem(addr)
                if not item:
                    # find contrib, it will be in this module
                    for ctrb in fn.module.sectionContribs:
                        if ctrb.Section == c.Segment and c.Offset >= ctrb.Offset and c.Offset < ctrb.Offset + ctrb.Size:
                            contrib = (ctrb, c.Offset - ctrb.Offset)
                            break
                    item = Data(c, p.getAddr(c.Segment, c.Offset), c.Type, contrib=contrib)

                local = LocalData(c.Name, c.Type, size, self, fn, item)
                fn.module.use_type(c.Type, fn, TypeUsage.LocalStatic)
                self.locals.append(local)
                fn.local_vars.append(local)
                fn.staticlocals[addr:addr + max(size, 1)] = local
            elif isinstance(c, codeview.UserDefinedType):
                local = LocalTypeDef(c.Name, c.Type)
                self.locals.append(local)

        self.fn = fn
        self.p = p
        self.locals.reverse()

    def locals_as_code(self):
        s = ""
        for local in self.locals:
            s += local.as_code() + ";" + local.postfix() + "\n"
        return textwrap.indent(s, "\t")

    def stack_ref(self, offset):
        var = self.stack.at(offset)
        if not var:
            return None
        assert len(var) == 1
        var = var.pop()

        local = var.data
        var_off = offset - var.begin

        return RefTo(local, var_off)

    def data_ref(self, addr):
        # might be a static local
        local = self.fn.staticlocals.at(addr)
        if local:
            local = local.pop()
            var_offset = addr - local.begin

            return RefTo(local.data, var_offset)

            # if offset_expr is not None:
            #     reg = offset_expr.expr.reg
            #     return f"{access} + [{reg}{offset_expr.scale_str()}]"
            return access

        # otherwise, try globals
        item: Item = self.p.getItem(addr)
        if item:
            if item == self.fn:
                return None
            var_offset = addr - item.address
            return RefTo(item, var_offset)
        return None


    def code_ref(self, pc, addr):
        fnoffset = addr - self.fn.address

        if fnoffset > 0 and fnoffset < self.fn.length:
            # within current function
            if label := self.fn.getLabel(fnoffset):
                return BasicBlockRef(addr, label, self)
            return None

        fn = self.p.getItem(addr)

        if fn:
            return FunctionRef(fn, addr - fn.address)
        return None

import function
