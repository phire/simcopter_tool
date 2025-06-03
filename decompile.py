
import time
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

