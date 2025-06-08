
import time
import codeview
from pdb_parser import ProgramData
from coff import Executable

import construct

import pickle, os, sys
from collections import OrderedDict

def better_getstate(self):
    ret = OrderedDict(self)
    try:
        del ret["_io"]
    except KeyError:
        pass
    try:
        del ret["_stream"]
    except KeyError:
        pass

    return ret

# monkey patch container to filter out all io objects
construct.Container.__getstate__ = better_getstate

if __name__ == "__main__":
    import sys

    sys.setrecursionlimit(5000)

    pdb_file = "../debug_build_beta/COPTER_D.PDB"
    exe_file = "../debug_build_beta/COPTER_D.EXE"

    print("loading cache...    ", file=sys.stderr, end='', flush=True)
    now = time.time()

    try:
        # check if we have a cache
        modified = os.path.getmtime('cache.pkl')
        with open("cache.pkl", "rb") as f:
            cached_file, depends = pickle.load(f)
            if cached_file != (pdb_file, exe_file):
                raise Exception(f"wrong file")

            for file in depends:
                if os.path.getmtime(file) > modified:
                    raise Exception(f"{file} has been modified")

            cached_data = pickle.load(f)
            elapsed = int((time.time() - now) * 1000)
            print(f"done, {elapsed} ms", file=sys.stderr)

    except Exception as e:
        print(f"Cache load failed because: {e}", file=sys.stderr)

        exe = Executable(exe_file)
        cached_data = ProgramData(pdb_file, exe)

        # dump to cache
        with open("cache.pkl", "wb") as f:
            depends = [m.__file__ for m in sys.modules.values() if hasattr(m, '__file__') and m.__file__ not in (__file__, None)]
            pickle.dump(((pdb_file, exe_file), depends), f)
            pickle.dump(cached_data, f)

# avoid importing things until after the cache is loaded
# otherwise they will get counted as dependencies

from program import Program
from dump import dump

if __name__ == "__main__":
    print("processing...    ", file=sys.stderr, end='', flush=True)
    now = time.time()

    p = Program(cached_data)

    elapsed = int((time.time() - now) * 1000)
    print(f"done, {elapsed} ms", file=sys.stderr)

    print("post-processing...    ", file=sys.stderr, end='', flush=True)
    now = time.time()

    p.post_process()

    elapsed = int((time.time() - now) * 1000)
    print(f"done, {elapsed} ms", file=sys.stderr)

    game = p.libraries["game.lib"]
    police = game.modules["s3police.cpp"]
    createfn = police.functions["PoliceCarClass::CreateInstance"]

    #createfn.disassemble()

    scanfn = police.functions["PoliceCarClass::ScanForBadGuys"]
    #scanfn.disassemble()

    dump(p, "gen")

    # all_TIs = set()
    # for m in p.modules:
    #     if m.idx == 0:
    #         all_TIs = set()
    #     # TIs = set()
    #     # for i in m.all_items:
    #     #     if i.ty and i.ty.TI >= 0x1000 and i.ty.TI not in all_TIs and isinstance(Function):
    #     #         TIs.add(i.ty.TI)
    #     #         all_TIs.add(i.ty.TI)
    #     TIs = set()
    #     for t in m.raw_types:
    #         if t.TI < 0x1000:
    #             continue

    #         if any(m.idx != u.module.idx for u in t._usage):
    #             continue
    #         TIs.add(t.TI)
    #     offsets = sorted([c.Offset for c in m.sectionContribs if c.Section == 1])
    #     low_off = 0
    #     if offsets:
    #         low_off = offsets[0]

    #     if not len(TIs):
    #          print(f"{low_off:06x} - {m.library.name}:{m.name}")
    #          continue
    #     lowest = sorted(TIs)[0]
    #     highest = sorted(TIs)[-1]


    #     print(f"{low_off:06x} - {m.library.name}:{m.name}: {" ".join(f"{i:x}" for i in sorted(TIs))}")


    # for g in p.globals.symbols:
    #     if isinstance(g, codeview.PublicData):
    #         continue
    #     try:
    #         if id := g.getModuleId(p):
    #             module = p.modules[id].name
    #         else:
    #             print(g)
    #             module = "<unknown>"

    #     except AttributeError:
    #         module = "<no-getid>"

    #     addr = "<no--addr>"
    #     try:
    #         if g.Segment and g.Segment != 7:
    #             addr = f"{p.getAddr(g.Segment, g.Offset):#010x}"
    #     except AttributeError:
    #         pass

    #     try:
    #         TI = g.Type.TI
    #     except AttributeError:
    #         TI = 0

    #     cls = g.__class__.__name__

    #     print(f"{addr} {TI:4x} {module} {cls} {g.Name}, {g.refcount} refs")


    # for inc in includes.values():
    #     print(inc.filename)
    #     for m in inc.modules:
    #         print(f"    {m.sourceFile or m.name }")

    #for t in p.types.types:
    #    print(t)

    # cdebugwin = p.types.byName["CDebugWindow"][1]
    # print(cdebugwin)

    x = p.libraries["x.lib"]
    b = p.libraries["COPTER_D"]

    # for (kl, l) in p.libraries.items():
    #     if kl == "":
    #         kl = "<root>"
    #     for (k, m) in l.modules.items():
    #         for f in m.functions:
    #             print(f"{kl} {k}, {f}")

    # dbg = b.modules["sparkal\debug.cpp"]
    # outputString = dbg.functions["CDebugWindow::OutputString"]
    # outputString.disassemble()

    # for (k, v) in sorted(p.types.byName.items(), key=lambda x: 200 - len(x[1])):
    #     if len(v) <= 2 or k == "__unnamed":
    #         continue
    #     print(f"\n{k}: {len(v)}")
    #     defs = []
    #     for t in v:
    #         if hasattr(t, '_def_class'):
    #             defs.append(t)
    #     print(" ".join([f"{t.TI:04x}" for t in v]))
    #     for t in defs:
    #         cls = t._def_class
    #         print(f" {t.TI:04x} ({t.properties}) def: {cls.impl.TI:04x} size: {cls.size:#x}")


