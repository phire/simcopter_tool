#from tpi import *
from access import AccessMember
import tpi
import base_types
import textwrap
from intervaltree import IntervalTree

def process_methods(c, methods, p, base=None):
    for method in methods.methodList.Type.Data:
        if method.index.value == 0:
            # TODO: is this the new constructor?
            #print(f"NoType method found for {c.name}::{methods.Name}")
            continue
        if not isinstance(method.index.Type, tpi.LfMemberFunction):
            print("Unknown method type", method.index.Type.__class__)
            breakpoint()
            continue
        method.Name = methods.Name
        mbr = Method(c, method, p)
        mbr.parent = c


        if base == c:
            method.index.Type.classtype.Type._def_class = base
        c.fields += [mbr]


def process_field(field, c, p, base_offset=0, base=None):
    inherriting = c != base
    match field.__class__:
        case tpi.LfMethod:
            # We get a LfMethod when function overloading results in multiple methods with the same name.
            if not inherriting:
                process_methods(c, field, p, base)

        case tpi.LfOneMethod:
            # otherwise we get a LfOneMethod, which is a single method.
            if not inherriting:
                method = Method(c, field, p)
                method.parent = c
                c.fields.append(method)
                field.index.Type.classtype.Type._def_class = base

        case tpi.LfMember:
            size = field.index.type_size()

            m = Member(field, base_offset, p)
            if not size:
                size = 1

            c.members[m.offset:m.offset + size] = m
            c.offset = m.offset + size

            if not inherriting:
                c.fields.append(m)
                m.parent = c
        case tpi.LfStaticMember:
            if not inherriting:
                m = StaticMember(field, p)
                c.fields.append(m)
                m.parent = c
        case tpi.LfBaseClass:

            bbase = BaseRef(field, p)
            bbase.inherrit_fields(base_offset, c, p)

            if not inherriting:
                c.base += [bbase]
        case tpi.LfVirtualBaseClass | tpi.LfIndirectVirtualBaseClass:
            bbase = BaseRef(field, p)
            c.base += [bbase]

            m = VirtualBase(field, p)
            size = 4
            if other := c.members.at(m.offset):
                other = other.pop().data
                if other.name != m.name:
                    breakpoint()
                return
            c.members[m.offset:m.offset + size] = m
            c.offset = m.offset + size

            if not inherriting:
                c.fields.append(m)
        case tpi.LfNestedType:
            if not inherriting:
                c.fields.append(Nested(field, c, p))

        case tpi.LfVFuncTab:
            # ptr to vtable
            assert isinstance(field.index.Type, tpi.LfPointer)
            if inherriting:
                return


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
        self.p = p
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
        self.vtable_data = None

        if isinstance(impl, tpi.LfStruct):
            self.is_struct = True
        else:
            self.is_struct = False

        if self.fwdref:
            return

        assert impl.derivedList.value == 0, f"Class {self.name} has derivedList {impl.derivedList.value}"

        if impl.vshape.value != 0:
            self.vtable_shape = impl.vshape.Type.desc

        self.offset = 0
        self.base_offset = 0

        for field in impl.fieldList.Type.Data:
            process_field(field, self, p, 0, base=self)

        if self.offset == 0:
            self.offset = 1
        # elif self.offset & 3 and not self.packed:
        #     # align to 4 bytes
        #     self.offset += 4 - (self.offset & 3)

        # if self.size != self.offset:
        #     for m in sorted(self.members):
        #         print(f"{m.begin:02x}-{m.end:02x} : {m.data.ty.typestr(m.data.name)}")
        #     if self.name not in ["ostream_withassign"]:
        #         breakpoint()

    def __repr__(self):
        return f"<Class {self.name} size={self.size} fwdref={self.fwdref}>"

    def print_fields(self):
        for m in sorted(self.members):
            print(f"{m.begin:02x}-{m.end:02x} : {m.data.ty.typestr()} {m.data.name}")

    def as_code(self):
        access = None

        prefix = "class"
        if self.is_struct:
           access = "public"
           prefix = "struct"

        c = f"{prefix} {self.name}"

        if self.fwdref:
            return c + ";\n"

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

        if self.vtable_data:
            c = f"// VTABLE: {self.p.exename} {self.vtable_data.address:#010x}\n" + c

        return c

    def access(self, prefix, offset, size):
        if not isinstance(offset, int):
            # special case for accessing an array that is the first member
            m = self.members.at(0).pop()
            return m.data.access_field(prefix, offset, size)

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
                #print(f"Warning: BaseRef {self.name} is a forward reference, but has no definition.")
                pass
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
            process_field(field, c, p, self.offset + offset, base=self)

        #c.base_offset = c.offset

class Field:
    parent = None
    def __init__(self, field, p):
        try:
            self.name = field.Name
        except AttributeError:
            self.name = "<unknown>"
        try:
            self.ty = field.index.Type
        except AttributeError:
            pass
        self.access = field.attr.access
        self.attr = field.attr

        self.synthetic = field.attr.compgenx
        assert not (field.attr.pseudo or field.attr.noconstruct or field.attr.noinherit or field.attr.sealed)

    def attr_as_code(self):
        s = self.attr.str(map={'access': '', 'mprop': '', 'compgenx': ''})
        if s != "":
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
        suffix = ""
        if self.synthetic:
            suffix = " // synthetic"

        c += f"{self.ty.typestr(self.name)};{suffix}\n"

        return c

    def access_field(self, prefix, offset, size):
        prefix = AccessMember(prefix, self.name, self.ty)
        return self.ty.access(prefix, offset, size)

class StaticMember(Field):
    def __init__(self, field, p):
        super().__init__(field, p)

    def as_code(self):
        c = self.attr_as_code()
        c += f"static {self.ty.typestr(self.name)};\n"
        return c

def args_as_code(f):
    args = []
    for arg in f:
        args += [arg.typestr()]

    return ", ".join(args)

class Method(Field):
    def __init__(self, c, field, p):
        super().__init__(field, p)
        self.parent = c

        func = field.index.Type
        assert isinstance(func, tpi.LfMemberFunction)

        self.func = func
        self.vtable = field.vbaseoffset
        # TODO: collect vtable offsets from base classes
        func._field = self

    def is_virtual(self):
        return self.attr.mprop in ["virtual", "intro", "purevirt", "pureintro"]

    def as_code(self):
        c = self.attr_as_code()

        #assert self.func.calltype == tpi.CallingConvention.ThisCall
        if self.func.calltype != tpi.CallingConvention.ThisCall:
            c += f"// calltype: {self.func.calltype}\n"

        if str(self.func.funcattr):
            c += f"// funcattr: {self.func.funcattr}\n"

        args = args_as_code(self.func.args)

        pure = ""

        match self.attr.mprop:
          case "vanilla":
            pass
          case "virtual":
            c += "virtual "
            pure = " /* override */"
          case "static":
            c += "static "
          case "friend":
            c += "friend "
          case "intro": # Implies MTvirtual. The "introduction" of this virtual function
            c += "virtual "
          case "purevirt":
            c += "virtual "
            pure = " = 0 /* override */"
          case "pureintro": # likewise, implies MTpurevirt
            c += "virtual "
            pure = " = 0"

        suffix = ""
        if self.vtable is not None:
            suffix += f"vtable+{self.vtable:#x}"

        if self.synthetic:
            suffix = "synthetic"

        if suffix:
            suffix = f" // {suffix}"

        c += f"{self.func.rvtype.typestr()} {self.name}({args}){pure};{suffix}\n"
        return c


class Nested(Field):
    def __init__(self, field, c, p):
        self.name = field.Name
        self.ty = field.index.Type
        self.access = None
        self.attr = None
        self.parent = c

    def as_code(self):
        try:
            nested = self.ty.properties.isnested
            if not self.ty.Name.startswith(self.parent.name + "::"):
                nested = False
        except AttributeError:
            nested = False

        if nested:
            ty = self.ty
            s = ""
            if ty.properties.fwdref:
                s = "// (forward reference)"
                new_ty = ty._definition
                if hasattr(ty, '_def_class'):
                    ty = ty._def_class.impl
                else:
                    ty = new_ty
                # match self.ty.__class__:
                #     case tpi.LfClass:
                #         return f"class {self.name};\n"
                #     case tpi.LfStruct:
                #         return f"struct {self.name};\n"
                #     case _:
                #         print(f"Unknown nested type: {self.ty.__class__}")
                #         breakpoint()
            try:
                return ty.as_code()
            except AttributeError:
                return f"// TODO: Unknown nested type: {self.ty.__class__}\n// {ty.typestr(self.name)}\n"

        # if not nested, this is a using statement
        return f"using {self.name} = {self.ty.typestr()};\n"
        return f"// todo: Nested {self.name} {self.ty.typestr()};\n"


class VirtualBase(Field):
    def __init__(self, field, p):

        super().__init__(field, p)
        self.name = field.index.Type.Name
        self.ty = field.vbptr.Type
        self.offset = field.ptroffset.value

    def access_field(self, prefix, offset, size):
        # todo: Special Access Base
        prefix = AccessMember(prefix, self.name, self.ty)
        return self.ty.access(prefix, offset, size)

    def as_code(self):
        c = self.attr_as_code()
        c += f"{self.ty.typestr(self.name)};\n"
        if self.synthetic:
            c += f"// synthetic"
        return c


class VFTable(Member):
    def __init__(self, field, vtable, name, p):
        self.name = name
        self.ty = field.index.Type
        self.vtable = vtable
        self.synthetic = True

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

