
class Access:
    def __init__(self, size, lvalue, ty, offset=0):
        self.size = size
        self.lvalue = lvalue
        self.ty = ty
        self.offset = offset

    def __str__(self):
        return str(self.lvalue)

    def access(self, offset, size):
        if self.offset != 0:
            raise ValueError(f"Cannot access {self.name} with offset of {offset}")
        return self.ty.access(self, offset, size)

    def deref(self, offset, size):
        if self.offset != 0:
            raise ValueError(f"Cannot dereference {self.name} with offset of {offset}")
        return self.ty.deref(self, offset, size)

    def as_asm(self):
        try:
            return self.lvalue.as_asm()
        except AttributeError:
            return str(self.lvalue)

class AccessPointer(Access):
    def __init__(self, lvalue, ptr: bool):
        self.lvalue = lvalue
        self.ptr = ptr

    def __str__(self):
        return f"{self.lvalue}->" if self.ptr else f"{self.lvalue}."

    def as_asm(self):
        return f"{self.lvalue}->" if self.ptr else f"{self.lvalue}."

    #def access(self, offset, size):
    #    return self.ty.access(self, offset, size)

class ArrayAccess(Access):
    def __init__(self, lvalue, index, ty):
        if isinstance(lvalue, AccessPointer):
            lvalue = lvalue.lvalue
        self.lvalue = lvalue
        self.index = index
        self.element_type = ty

    def __str__(self):
        return f"{self.lvalue}[{self.index}]"

    def as_asm(self):
        try:
            s = self.lvalue.as_asm()
        except AttributeError:
            s = str(self.lvalue)
        return f"{s}[{self.index.as_asm()}]"

    def access(self, offset, size):
        return self.element_type.access(self, offset, size)

class AccessMember(Access):
    def __init__(self, lvalue, member_name, ty):
        self.lvalue = lvalue
        self.member_name = member_name
        self.member_type = ty

    def __str__(self):
        if isinstance(self.lvalue, AccessPointer):
            return f"{self.lvalue}{self.member_name}"
        return f"{self.lvalue}.{self.member_name}"

    def as_asm(self):
        try:
            s = self.lvalue.as_asm()
        except AttributeError:
            s = str(self.lvalue)
        if isinstance(self.lvalue, AccessPointer):
            return f"{s}{self.member_name}"
        return f"{s}.{self.member_name}"

    def access(self, offset, size):
        return self.member_type.access(self, offset, size)
