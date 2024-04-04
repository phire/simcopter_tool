
from program import Program
from coff import Executable

import construct

import pickle, os, sys, copyreg
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

    pdb_file = "../debug_build_beta/COPTER_D.PDB"
    exe_file = "../debug_build_beta/COPTER_D.EXE"

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

            p = pickle.load(f)
    except Exception as e:
        print(f"Cache load failed because: {e}", file=sys.stderr)

        exe = Executable(exe_file)
        p = Program(pdb_file, exe)

        # dump to cache
        with open("cache.pkl", "wb") as f:
            depends = [m.__file__ for m in sys.modules.values() if hasattr(m, '__file__') and m.__file__ not in (__file__, None)]
            pickle.dump(((pdb_file, exe_file), depends), f)
            pickle.dump(p, f)


    for lib in p.libraries.values():
        if lib.is_dll() or lib.name in ["OLDNAMES.lib", "LIBCMTD.lib"]:
            continue
        #print(lib)

    game = p.libraries["game.lib"]
    police = game.modules["s3police.cpp"]
    createfn = police.functions["PoliceCarClass::CreateInstance"]

    #createfn.disassemble()

    scanfn = police.functions["PoliceCarClass::ScanForBadGuys"]
    #scanfn.disassemble()


    # for sym in p.unknownContribs:
    #     print(sym)
    #     for idx in range(sym.index - 1, 0, -1):
    #         try:
    #             contrib = p.globals[idx].contrib
    #             if contrib.module:
    #                 print(f"After {contrib.module.sourceFile}")
    #                 break
    #         except:
    #             try:
    #                 moduleId = p.globals[idx].getModuleId(p)
    #                 if moduleId:
    #                     print(f"After {p.modules[moduleId].sourceFile}")
    #                     break
    #             except AttributeError:
    #                 continue
    #     for idx in range(sym.index, len(p.globals)):
    #         try:
    #             contrib = p.globals[idx].contrib
    #             if contrib.module:
    #                 print(f"Before {contrib.module.sourceFile}\n")
    #                 break
    #         except:
    #             try:
    #                 moduleId = p.globals[idx].getModuleId(p)
    #                 if moduleId:
    #                     print(f"Before {p.modules[moduleId].sourceFile}\n")
    #                     break
    #             except AttributeError:
    #                 continue


    # for inc in includes.values():q
    #     print(inc.filename)
    #     for m in inc.modules:
    #         print(f"    {m.sourceFile or m.name }")
