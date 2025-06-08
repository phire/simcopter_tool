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
    BaseClass = 8
    GlobalDataAlt = 9

import tpi

class Usage:
    def __init__(self, ty, other, mode: TypeUsage, module):
        while True:
            match ty:
                case tpi.LfPointer():
                    ty = ty.Type
                    mode = self.Ptr(ty, mode)
                case tpi.LfModifier():
                    ty = ty.Type
                    mode = self.Modifier(ty, mode)
                case tpi.LfArray():
                    ty = ty.Type
                    mode = self.Array(ty, mode)
                case _:
                    break
        self.ty = ty
        self.other = other
        self.mode = mode
        self.module = module

    class Modifier:
        def __init__(self, modifier_ty, mode):
            self.modifier_ty = modifier_ty
            self.mode = mode

        def __repr__(self):
            return f"Modifier({self.modifier_ty.typestr()}, {self.mode!r})"

    class Ptr:
        def __init__(self, ptr_ty, mode):
            self.ptr_ty = ptr_ty
            self.mode = mode

        def __repr__(self):
            return f"Ptr({self.ptr_ty.typestr()}, {self.mode!r})"

    class Array:
        def __init__(self, array_ty, mode):
            self.array_ty = array_ty
            self.mode = mode

        def __repr__(self):
            return f"Array({self.array_ty.typestr()}, {self.mode!r})"

    def __repr__(self):
        return f"Usage({self.ty.typestr()}, {self.other!r} {self.mode!r})"
