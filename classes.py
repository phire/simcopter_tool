#from tpi import *
import tpi
import base_types
import textwrap

def process_methods(c, methods, p):

    # todo: these methodlists are (sometimes?) shared by multiple classes
    for i, method in enumerate(methods.methodList.Type.Data):
        if method.index.value == 0:
            # I think this just reserves a slot in the vtable?
            #print("NoType method found in ", c.name)
            continue
        if not isinstance(method.index.Type, tpi.LfMemberFunction):
            print("Unknown method type", method.index.Type.__class__)
            breakpoint()
            continue
        mbr = MemberFunction(i, method, p)
        c.fields += [mbr]


class Class:
    def __init__(self, impl, p):
        self.name = impl.Name
        self.size = impl.Size
        self.packed = impl.properties.packed
        self.ctor = impl.properties.ctor
        self.fwdref = impl.properties.fwdref
        self.fields = []
        self.base = []

        self.vtable = None
        self.vtable_shape = None

        if self.fwdref:
            return

        assert impl.derivedList.value == 0, f"Class {self.name} has derivedList {impl.derivedList.value}"

        if impl.vshape.value != 0:
            self.vtable_shape = impl.vshape.Type.desc

        for field in impl.fieldList.Type.Data:
            match field.__class__:
                case tpi.LfOneMethod:
                    self.fields.append(Method(field, p))
                case tpi.LfMember:
                    self.fields.append(Member(field, p))
                case tpi.LfStaticMember:
                    self.fields.append(StaticMember(field, p))
                case tpi.LfBaseClass:
                    self.base += [BaseRef(field, p)]
                case tpi.LfVirtualBaseClass:
                    self.base += [BaseRef(field, p)]
                case tpi.LfNestedType:
                    self.fields.append(Nested(field, p))
                case tpi.LfIndirectVirtualBaseClass:
                    self.fields.append(VirtualBase(field, p))
                case tpi.LfMethod:
                    process_methods(self, field, p)
                case tpi.LfVFuncTab:
                    # ptr to vtable
                    assert isinstance(field.index.Type, tpi.LfPointer)
                    vtable = field.index.Type.Type # um... wtf?
                    assert vtable.value == impl.vshape.value

                case _:
                    print("Unknown field type", field.__class__)
                    breakpoint()

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


class BaseRef:
    def __init__(self, field, p):
        self.access = field.attr.access
        self.attr = field.attr
        self.virtual = False
        self.indirect = False
        self.ty = field.index.Type
        self.name = self.ty.Name
        match field.__class__:
            case tpi.LfBaseClass:
                pass
            case tpi.LfVirtualBaseClass:
                self.virtual = True
            case tpi.LfIndirectVirtualBaseClass:
                self.virtual = True
                self.indirect = True

    def as_code(self):
        c = f"{self.access} "
        if self.virtual:
            c += "virtual "
        if self.indirect:
            c += "<indirect> " # todo, what does this mean?
        return c + self.name



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
    def __init__(self, field, p):
        super().__init__(field, p)

    def as_code(self):
        c = self.attr_as_code()
        c += f"{self.ty.shortstr()} {self.name};\n"
        return c

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
        self.vtable = None

    def as_code(self):
        c = self.attr_as_code()
        if self.vtable is not None:
            c += f"// vtable: {self.vtable}\n"

        #assert self.func.calltype == tpi.CallingConvention.ThisCall
        if self.func.calltype != tpi.CallingConvention.ThisCall:
            c += f"// calltype: {self.func.calltype}\n"

        if self.vtable is not None:
            c += "// virtual\n"



        args = args_as_code(self.func.args)
        if self.attr.mprop != "vanilla":
            c += f"{self.attr.mprop} "

        c += f"{self.func.rvtype.shortstr()} {self.name}({args});\n"
        return c


class MemberFunction(Method):
    # I think member functions are virtual, and Direct methods are not
    def __init__(self, i, method, p):
        super().__init__(method, p)
        # todo: use vtable to get name, somehow

        self.vtable = i * 4
        if method.vbaseoffset is not None:
            self.vtable += method.vbaseoffset

class Nested(Field):
    def __init__(self, field, p):
        self.name = field.Name
        self.ty = field.index.Type
        self.access = None
        self.attr = None

    def as_code(self):
        return f"todo: Nested {self.name} {self.ty.Name};\n"


class VirtualBase(Field):
    def __init__(self, field, p):
        self.name = field.index.Type.Name
        self.ty = field.index.Type
        self.access = field.attr.access
        self.attr = field.attr


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



