
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