
from program import Program
from coff import Executable

from itertools import pairwise, chain
import x86

if __name__ == "__main__":
    import sys

    pdb_file = "../debug_build_beta/COPTER_D.PDB"
    exe_file = "../debug_build_beta/COPTER_D.EXE"

    exe = Executable(exe_file)

    p = Program(pdb_file, exe)
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
