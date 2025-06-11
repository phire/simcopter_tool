import os, subprocess, shutil

from coff import Executable
import pdb_parser
from program import Program

WINE_DIR = os.environ['HOME'] + '/simcopter/wine'
MSDEV_DIR = 'C:/msdev'
SRC_DIR = WINE_DIR + '/drive_c/temp/'
OUT_DIR = SRC_DIR + '/Debug/'


def compile_single(sourcecode):
    wine_bin = shutil.which('wine')
    env = {
        'WINEPREFIX': WINE_DIR,
        'WINEDEBUG': '-all',
        'MVK_CONFIG_LOG_LEVEL': "0",
        'INCLUDE': 'c:/msdev/include',
        'LIB': 'c:/msdev/lib',
        #'WINEPATH': "c:/temp/",
    }

    os.makedirs(WINE_DIR + '/drive_c/temp/', exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    source_file = WINE_DIR + '/drive_c/temp/temp.cpp'

    source_file_win = 'c:/temp/temp.cpp'
    cwd = WINE_DIR + '/drive_c/temp/'
    os.chdir(cwd)

    with open(source_file, 'w') as f:
        f.write(sourcecode)
        f.close()
    cpp = MSDEV_DIR + '/bin/cl.exe'
    link = MSDEV_DIR + '/bin/link.exe'
    objdir = '\\temp\\Debug\\'
    # TODO: /nologo /MTd /W3 /Gm /Zi /Od /Ob1 /I "Source" /I "Lib/DirectX2/INC" /I "Lib/STL" /D "WIN32" /D "_DEBUG" /D "_WINDOWS"

    opts = ['/nologo', '/MTd', '/W3', '/Gm', '/Gi-', '/GX-', '/Zi', '/Od', '/Ob1', '/Gy', '/Oi',
            f'/Fo{objdir}', f'/Fd{objdir}']

    cmd = [ wine_bin, cpp, *opts, source_file_win,]
    #print(f"Compiling {source_file_win} with command: {' '.join(cmd)}")

    out = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True)
    if out.returncode != 0:
        print(f"Compilation failed: {out.returncode}")
        print(out.stdout.decode())
        return None

    # TODO: link with -- kernel32.lib user32.lib gdi32.lib winspool.lib comdlg32.lib advapi32.lib shell32.lib ole32.lib oleaut32.lib uuid.lib odbc32.lib odbccp32.lib version.lib winmm.lib msacm32.lib Lib/DirectX2/LIB/ddraw.lib Lib/DirectX2/LIB/dsound.lib /nologo /subsystem:windows /incremental:no /pdb:"build_out/output/COPTER_D.pdb" /map:"build_out/intermediate/COPTER_D.map" /debug /machine:I386 /out:"build_out/output/COPTER_D.exe"

    exe_file = SRC_DIR + 'temp.exe'
    pdb_file = SRC_DIR + 'temp.pdb'

    exe = Executable(exe_file)
    data = pdb_parser.ProgramData(pdb_file, exe, timeit=False)
    p = Program(data)
    p.post_process(module=0)

    return p


if __name__ == "__main__":
    source_code = """
#include <iostream.h>

#include <stdio.h>
#include <string.h>

    static int global_var[4][4];

    int main(int matrix[4][4]) {

        int count = 0;
        unsigned char arr[4];
        arr[0] = 1;
        arr[1] = 2;
        arr[2] = 3;

        return count;
    }
"""

    p = compile_single(source_code)

    if not p:
        exit(1)

    print(p.modules[0].functions['main'].as_code())






