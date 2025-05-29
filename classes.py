#from tpi import *
import tpi
import base_types
import textwrap
from intervaltree import IntervalTree

def process_methods(c, methods, p):
    # todo: these methodlists are (sometimes?) shared by multiple classes
    for method in methods.methodList.Type.Data:
        if method.index.value == 0:
            # TODO: is this the new constructor?
            #print("NoType method found in ", c.name)
            continue
        if not isinstance(method.index.Type, tpi.LfMemberFunction):
            print("Unknown method type", method.index.Type.__class__)
            breakpoint()
            continue
        mbr = MemberFunction(method, p)
        mbr.name = c.name
        c.fields += [mbr]


def process_field(field, c, p, base_offset=0):
    match field.__class__:
        case tpi.LfOneMethod:
            c.fields.append(Method(field, p))
        case tpi.LfMethod:
            # TODO: work out the difference is between LfMethod and LfOneMethod
            process_methods(c, field, p)
        case tpi.LfMember:
            size = field.index.type_size()

            m = Member(field, base_offset, p)
            if not size:
                size = 1

            c.members[m.offset:m.offset + size] = m
            c.offset = m.offset + size

            c.fields.append(m)
        case tpi.LfStaticMember:
            c.fields.append(StaticMember(field, p))
        case tpi.LfBaseClass:
            base = BaseRef(field, p)
            base.inherrit_fields(base_offset, c, p)

            c.base += [base]
        case tpi.LfVirtualBaseClass | tpi.LfIndirectVirtualBaseClass:
            base = BaseRef(field, p)
            c.base += [base]

            m = VirtualBase(field, p)
            size = 4
            if other := c.members.at(m.offset):
                other = other.pop().data
                if other.name != m.name:
                    breakpoint()
                return
            c.members[m.offset:m.offset + size] = m
            c.offset = m.offset + size
            c.fields.append(m)
        case tpi.LfNestedType:
            c.fields.append(Nested(field, p))

        case tpi.LfVFuncTab:
            # ptr to vtable
            assert isinstance(field.index.Type, tpi.LfPointer)

            ptr_size = field.index.Type.type_size()
            vtable = field.index.Type.Type # um... wtf?
            field = VFTable(field, vtable, f"{c.name}_vftable", p)
            c.members[c.offset:c.offset + ptr_size] = field
            c.vtable = vtable
            c.offset += ptr_size

        case _:
            print("Unknown field type", field.__class__)
            breakpoint()

class Class:
    def __init__(self, impl, p):
        self.impl = impl
        self.name = impl.Name
        self.size = impl.Size.value
        self.packed = impl.properties.packed
        self.ctor = impl.properties.ctor
        self.fwdref = impl.properties.fwdref
        self.fields = []
        self.base = []
        self.members = IntervalTree()
        self.inherited_from = []

        self.vtable = None
        self.vtable_shape = None

        if self.fwdref:
            return

        assert impl.derivedList.value == 0, f"Class {self.name} has derivedList {impl.derivedList.value}"

        if impl.vshape.value != 0:
            self.vtable_shape = impl.vshape.Type.desc

        self.offset = 0
        self.base_offset = 0

        for field in impl.fieldList.Type.Data:
            process_field(field, self, p)

        if self.offset == 0:
            self.offset = 1
        # elif self.offset & 3 and not self.packed:
        #     # align to 4 bytes
        #     self.offset += 4 - (self.offset & 3)

        # if self.size != self.offset:
        #     for m in sorted(self.members):
        #         print(f"{m.begin:02x}-{m.end:02x} : {m.data.ty.typestr()} {m.data.name}")
        #     if self.name not in ["ostream_withassign"]:
        #         breakpoint()

    def print_fields(self):
        for m in sorted(self.members):
            print(f"{m.begin:02x}-{m.end:02x} : {m.data.ty.typestr()} {m.data.name}")

    def as_code(self):
        access = None

        c = f"class {self.name}"
        if self.fwdref:
            return f"class {self.name};\n"

        bases = [f"{b.as_code()}" for b in self.base]

        if bases:
            c += f" : {', '.join(bases)}\n"

        c += "{\n"

        for field in self.fields:
            if access != field.access:
                access = field.access
                if access is not None:
                    c += f"{access}:\n"

            c += textwrap.indent(field.as_code(), "\t")

        c += "};\n"

        return c

    def access(self, prefix, offset, size):
        m = self.members.at(offset)
        if not m:
            return f"{prefix}<{self.name}+0x{offset:02x}>"
        # todo: For some reason these classes have multiple members at the same offset.
        #       I think this is correct, but I don't know why.
        if len(m) > 1 and self.name not in ["_DDBLTFX", "_DDPIXELFORMAT", "Behavior::Node"]:
            breakpoint()
        m = m.pop()

        var_offset = offset - m.begin

        return m.data.access_field(prefix, var_offset, size)


class BaseRef:
    def __init__(self, field, p):

        self.virtual = False
        self.indirect = False

        match field.__class__:
            case tpi.LfBaseClass:
                pass
            case tpi.LfVirtualBaseClass:
                self.virtual = True
            case tpi.LfIndirectVirtualBaseClass:
                self.virtual = True
                self.indirect = True

        self.access = field.attr.access
        self.attr = field.attr

        self.ty = field.index.Type
        self.name = self.ty.Name
        if self.virtual:
            self.offset = field.ptroffset.value
            self.vbptr_ty = field.vbptr.Type
        else:
            # not virtual
            self.offset = field.offset.value
            self.vbptr_ty = None

        if self.ty.properties.fwdref:
            self.fwdref = True
            definition = self.ty._definition
            if definition is not None:
                self.ty = definition
            else:
                print(f"Warning: BaseRef {self.name} is a forward reference, but has no definition.")
        else:
            self.fwdref = False

        if self.ty.properties.fwdref:
            self.size = 0
        else:
            self.size = self.ty.type_size()


    def as_code(self):
        c = f"{self.access} "
        if self.virtual:
            c += "virtual "
        if self.indirect:
            c += "<indirect> " # todo, what does this mean?
        return c + self.name

    def inherrit_fields(self, offset, c, p):
        if self.name in c.inherited_from:
            return

        if self.ty.properties.fwdref:
            return

        c.inherited_from.append(self.name)

        assert not self.virtual
        for field in self.ty.fieldList.Type.Data:
            process_field(field, c, p, self.offset + offset)

        #c.base_offset = c.offset

class Field:
    def __init__(self, field, p):
        try:
            self.name = field.Name
        except AttributeError:
            self.name = "<unknown>"
        self.ty = field.index.Type
        self.access = field.attr.access
        self.attr = field.attr

    def attr_as_code(self):
        s = " "
        if self.attr.noconstruct:
            s += "noconstruct "
        if self.attr.noinherit:
            s += "noinherit "
        if self.attr.pseudo:
            s += "pseudo "
        if self.attr.sealed:
            s += "sealed "
        if s != " ":
            return "//" + s + "\n"
        return ""

class Member(Field):
    def __init__(self, field, base_offset, p):
        super().__init__(field, p)
        self.offset = field.offset.value + base_offset

    def type_size(self):
        return self.ty.type_size()

    def as_code(self):
        c = self.attr_as_code()
        c += f"{self.ty.shortstr()} {self.name};\n"
        return c

    def access_field(self, prefix, offset, size):
        return self.ty.access(prefix + self.name, offset, size)

class StaticMember(Field):
    def __init__(self, field, p):
        super().__init__(field, p)

    def as_code(self):
        c = self.attr_as_code()
        c += f"static {self.ty.shortstr()} {self.name};\n"
        return c

def args_as_code(f):
    args = []
    for arg in f:
        args += [arg.shortstr()]

    return ", ".join(args)

class Method(Field):
    def __init__(self, field, p):
        super().__init__(field, p)

        func = field.index.Type
        assert isinstance(func, tpi.LfMemberFunction)

        self.func = func
        self.vtable = field.vbaseoffset
        # TODO: collect vtable offsets from base classes

    def as_code(self):
        c = self.attr_as_code()
        if self.vtable is not None:
            c += f"// vtable: {self.vtable}\n"

        #assert self.func.calltype == tpi.CallingConvention.ThisCall
        if self.func.calltype != tpi.CallingConvention.ThisCall:
            c += f"// calltype: {self.func.calltype}\n"

        if str(self.func.funcattr):
            c += f"// funcattr: {self.func.funcattr}\n"

        args = args_as_code(self.func.args)
        if self.attr.mprop != "vanilla":
            c += f"{self.attr.mprop} "

        c += f"{self.func.rvtype.shortstr()} {self.name}({args});\n"
        return c


class MemberFunction(Method):
    # I think member functions are constructors???
    def __init__(self, method, p):
        super().__init__(method, p)

class Nested(Field):
    def __init__(self, field, p):
        self.name = field.Name
        self.ty = field.index.Type
        self.access = None
        self.attr = None

    def as_code(self):
        return f"todo: Nested {self.name} {self.ty.Name};\n"


class VirtualBase(Member):
    def __init__(self, field, p):
        self.name = field.index.Type.Name
        self.ty = field.vbptr.Type
        self.access = field.attr.access
        self.attr = field.attr
        self.offset = field.ptroffset.value

class VFTable(Member):
    def __init__(self, field, vtable, name, p):
        self.name = name
        self.ty = field.index.Type
        self.vtable = vtable

    def access_field(self, prefix, offset, size):
        if (size is None or size == 4) and offset == 0:
            return f"{prefix}<vftable>"
        raise ValueError(f"Cannot access VFTable {self.name} at offset {offset} with size {size}")



def parse_classes(p):
    class_names = set()

    # collect classes
    classes = {}

    for ty in p.types.types:
        if ty is None:
            continue
        if not isinstance(ty, tpi.LfClass):
            continue
        if ty.properties.fwdref:
            continue

        impl = ty
        TI = ty.TI

        types = p.types.byName[impl.Name]
        for t in types:
            # if t.properties.fwdref:
            #     t.decl = ty
            if not t.properties.fwdref and t.TI != TI:
                pass
                #print(f"Warning: {impl.Name} has multiple implementations {t.TI} != {TI}")

        #print(f"{name}: {impl} {fwd}")

        info = Class(impl, p)
        classes[TI] = info
        impl._class = info

        # if impl.Name == "CopterSparkalPalette":
        #     print("Found CopterSparkalPalette TI: ", TI)
        #     print(info.as_code())
        #     print(impl)
        #     breakpoint()

    return classes

