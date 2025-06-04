

from gsi import Visablity
import codeview
import pydemangler
import construct

class Item:
    sym = None
    export = None
    address = None
    name = None

    def __init__(self, sym, address, ty=None):
        self.sym = sym
        self.address = address
        self.name = sym.Name
        self.ty = ty
        try:
            self.length = ty.type_size()
        except:
            self.length = 1
        if hasattr(sym, 'contrib'):
            self.contrib = (sym.contrib, sym.contribOffset)
        else:
            self.contrib = (None, None)

    def post_process(self):
        # This is called after the module has been fully processed
        # and all symbols have been linked to types
        pass

    def data(self):
        try:
            contrib, offset = self.contrib
            return contrib._data[offset: offset+self.length]
        except AttributeError:
            return None

    def access(self, prefix, offset, size):
        return self.ty.access(prefix, offset, size)

class Data(Item):
    def __init__(self, sym, address, ty, contrib=None):
        super().__init__(sym, address, ty)
        if contrib is not None:
            self.contrib = contrib

    def initializer(self):
        if self.ty.getCon() is None:
            # If there is no construct, we cannot initialize it
            return "{ 0 /* todo */ }"
        if (data := self.data()) is None:
            return "{ 0 /* error */ }"

        parsed = self.ty.getCon().parse(data)

        return self.ty.initializer(parsed)

    def as_code(self):
        cls = getattr(self.ty, '_class', None)
        cls = getattr(self.ty, '_def_class', cls)
        s = self.ty.typestr(self.name)

        if isinstance(self.sym, codeview.LocalData):
            s = f"static {s}"

        if getattr(self.sym, 'visablity', None) == Visablity.Public:
            s = f"extern {s}"

        try:
            is_bss = self.contrib[0].is_bss()
        except AttributeError:
            s += "; // Contrib missing\n"
            return s
        if not is_bss:
            s += f" = {self.initializer()};\n"
        else:
            s += ";\n"

        return s

class ThunkItem(Item):
    def __init__(self, sym, address):
        self.sym = sym
        self.address = address
        self.length = sym.Len
        self.name = sym.Name

class StringLiterial(Item):
    def __init__(self, sym, address):
        super().__init__(sym, address)
        self.length = len(sym.contrib._data)
        data = sym.contrib._data[:-1]
        self.string = data.decode('utf-8')

    def as_code(self):
        return f'// string literal: "{self.string}"'

    def access(self, prefix, offset, size):
        breakpoint()
        return self.ty.access(prefix, offset, size)

class VFTable(Item):
    def __init__(self, sym, address, p):
        super().__init__(sym, address)
        class_name = pydemangler.demangle(sym.Name).split('::')[0].split(' ')[-1]
        self.class_name = class_name
        self.cls = None
        for c in p.classes.values():
            if c.name == class_name:
                c.vtable_data = self
                self.cls = c

        self.length = len(sym.contrib._data)
        ptrs = construct.Array(self.length // 4, construct.Int32ul).parse(sym.contrib._data)
        self.ptrs = ptrs
        self.fns = None
        self.p = p

    def access(self, prefix, offset, size):
        index = offset // 4
        assert size == 4 and index < len(self.ptrs)
        return self.fns[index]

    def post_process(self):
        self.fns = [self.p.getItem(addr) for addr in self.ptrs if addr != 0]


    def as_code(self):
        s = f"// vftable for {self.class_name} @ {self.address:#010x}\n"
        for i, fn in enumerate(self.fns):
            s += f"//   {i:02d}: {fn.name} @ 0x{fn.address:08x}\n"
        s += f"//   {len(self.fns)} entries\n"
        return s


