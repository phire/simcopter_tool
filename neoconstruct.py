
"""
A wrapper around construct that allows for a more object oriented approach to defining structures.
"""

import inspect, ast, textwrap, tokenize, io, re, copy, types, functools
from io import BytesIO

import construct as cs

def _parse_doccomment(str, before):
    """Parses Spinx style doc comments (prefixed with #:)

        before: if True, the line must only contain the doc comment
    """
    io = BytesIO(str.encode('utf-8'))
    for tok in tokenize.tokenize(io.readline):
        if tok.type == tokenize.ENCODING:
            continue
        if tok.type == tokenize.COMMENT and tok.string.startswith("#:"):
            return tok.string[2:].strip()
        if before:
            # We found something that wasn't a comment
            return None
    return None

def _get_attribute_docs(cls):
    "python doesn't have anyway to access attribute doc strings, short of parsing the source code"
    docs = {}

    try:
        src = inspect.getsource(cls)
    except OSError:
        return docs

    tree = ast.parse(textwrap.dedent(src))
    cls_tree = [e for e in ast.walk(tree) if isinstance(e, ast.ClassDef)][0]
    lines = src.splitlines()

    needs_docstring = None

    for expr in cls_tree.body:
        if isinstance(expr, ast.AnnAssign):
            name = expr.target.id
            lineno = expr.lineno - 1 # lineno is 1-based

            # check for comment on this line
            doc = _parse_doccomment(lines[lineno], False)
            if not doc and lineno > 0:
                # or on the previous line
                doc = _parse_doccomment(lines[lineno-1], True)

            docs[name] = doc
            needs_docstring = None if doc else name
            continue
        elif isinstance(expr, ast.Expr) and needs_docstring:
            # find strings that follow assignments
            value = expr.value.value
            if isinstance(value, str):
                docs[needs_docstring] = value.strip()
        prev = None

    return docs


def hybrid_classmethod(func):
    """Like @classmethod, but also has access to self as second arg"""
    class HybridDescriptor:
        def __init__(self, func):
            self.func = func

        def __get__(self, instance, cls):
            clsmethod = types.MethodType(self.func, cls)
            if instance is None:
                return functools.partial(clsmethod, None)
            return types.MethodType(clsmethod, instance)

    return HybridDescriptor(func)

class NeoConstruct(object):
    @classmethod
    def _parsereport(cls, stream, context, path):
        obj = cls._parse(stream, context, path)
        return obj


    @classmethod
    def parse(cls, data, **contextkw):
        return cls.parse_stream(BytesIO(data), **contextkw)

    @classmethod
    def parse_stream(cls, stream, **contextkw):
        r"""
        Parse a stream. Files, pipes, sockets, and other streaming sources of data are handled by this method. See parse().
        """
        context = Container(**contextkw)
        context._parsing = True
        context._building = False
        context._sizing = False
        context._params = context
        try:
            return cls._parsereport(stream, context, "(parsing)")
        except CancelParsing:
            pass


class NeoStruct(NeoConstruct):
    @classmethod
    def _parse(cls, stream, context, path):
        obj = cls.__new__(cls)

        for sc in cls.subcons:
            val = sc._parsereport(stream, context, path)
            if sc.name:
                setattr(obj, sc.name, val)
                context[sc.name] = val

        return obj

    @hybrid_classmethod
    def sizeof(cls, self):
        print(f"sizeof {cls}, {self}")


class NeoObject:
    pass

def _process_struct(cls, **kwargs):
    if 'short_name' in kwargs:
        cls.short_name = kwargs.pop("short_name")
    else:
        cls.short_name = re.sub('[a-z]', '', cls.__name__)
        if len(cls.short_name) > 5:
            cls.short_name = cls.short_name[:3] + cls.short_name[-2:]

    cls_annotations = inspect.get_annotations(cls)
    docsstrings = _get_attribute_docs(cls)
    cls_dict = object.__getattribute__(cls, "__dict__")

    # Collect struct fields
    subcons = []
    for name, ann in cls_annotations.items():
        if not isinstance(ann, cs.Construct) or ann is cs.Construct:
            continue

        subcon = ann

        default_value = cls_dict.get(name, None)
        if isinstance(default_value, cs.Construct):
            raise ValueError(f"default value for {name} should not be a Construct")

        if default_value:
            subcon = Default(subcon, default_value)

        doc = docsstrings.get(name, None)
        subcons.append(cs.Renamed(subcon, newname=name, newdocs=doc))

    for name, value in cls_dict.items():
        if name in cls_annotations or name.startswith("__") or inspect.isfunction(value):
            continue
        if isinstance(value, cs.Construct):
            raise ValueError(f"Attempting to assign the Construct {value} to {attr}. Use `name: {value}` instead (or use an explicit type annotation of Construct to suppress this error)")

    # calculate sizes/offsets
    offsets = {}

    off = 0
    for subcon in subcons:
        size = subcon.sizeof()
        if size is None:
            size = FuncPath(lambda obj: obj.sizeof())

        offsets[subcon] = off, size
        off = size + off

    cls.subcons = subcons
    cls.offsets = offsets

    # Add NeoStruct as base class
    cls = type(cls.__name__, (NeoStruct, cls), {})

    return cls

def struct(cls=None, **kwargs):
    def wrap(cls):
        return _process_struct(cls, **kwargs)

    if cls is None:
        return wrapper
    return wrap(cls)

if __name__ == "__main__":
    # example:

    from construct import *

    @struct
    class Example:
        #: This is field a. I like it
        a: Int32ul = 0

        b: Int32ul #: field b is cool too

        c = 2 #: this isn't for hhhh
        hhhh: Int32ul = 3
        """Trailing docstring"""

    e = Example.parse(b"\x55\x00\x00\x00\x44\x00\x00\x00\x66\x00\x00\x00")