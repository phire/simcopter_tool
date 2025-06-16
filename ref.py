


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
    __match_args__ = ("fn",)
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
    def __init__(self, bb):
        self.bb = bb

    def __repr__(self):
        return f"BasicBlockRef({self.bb.label})"

    def as_code(self):
        return self.bb.label.name

    def as_asm(self):
        if not self.bb.label:
            raise ValueError("BasicBlockRef has no label")
        return self.bb.label.name

    def __eq__(self, other):
        if isinstance(other, BasicBlockRef):
            return self.bb == other.bb
        if isinstance(other, int):
            return self.bb.address == other
        return self.bb == other
