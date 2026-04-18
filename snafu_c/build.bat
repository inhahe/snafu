@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 (
    echo vcvarsall failed
    exit /b 1
)
cd /d "D:\visual studio projects\snafulang\snafu_c"

set SRCS=snafu_main.cpp snafu_value.cpp snafu_scope.cpp snafu_lexer.cpp snafu_parser.cpp snafu_eval.cpp snafu_prelude.cpp snafu_python.cpp
set BASE_FLAGS=/O2 /std:c++17 /W3 /EHsc /D_CRT_SECURE_NO_WARNINGS /D_CRT_NONSTDC_NO_DEPRECATE

REM Try to find Python include and lib directories
set PYINC=
set PYLIB=
set PYVER=
for /f "tokens=*" %%i in ('python -c "import sysconfig; print(sysconfig.get_path('include'))" 2^>nul') do set PYINC=%%i
for /f "tokens=*" %%i in ('python -c "import sysconfig, os; libdir = sysconfig.get_config_var('LIBDIR'); stdlib = os.path.dirname(sysconfig.get_path('stdlib')); print(libdir if libdir else os.path.join(stdlib, 'libs'))" 2^>nul') do set PYLIB=%%i
for /f "tokens=*" %%i in ('python -c "import sys; print(f'python{sys.version_info.major}{sys.version_info.minor}')" 2^>nul') do set PYVER=%%i

if defined PYINC if defined PYLIB if defined PYVER (
    echo Compiling C++ with Python bridge...
    echo   Python include: %PYINC%
    echo   Python lib:     %PYLIB%
    cl %BASE_FLAGS% /DSNAFU_HAS_PYTHON /I"%PYINC%" /Fe:snafu.exe %SRCS% /link /LIBPATH:"%PYLIB%" %PYVER%.lib
    if errorlevel 1 (
        echo Compilation with Python failed, falling back to build without Python...
        goto no_python
    )
    echo Build successful (with Python bridge)
    goto end
)

:no_python
echo Compiling C++ without Python bridge...
cl %BASE_FLAGS% /Fe:snafu.exe %SRCS%
if errorlevel 1 (
    echo Compilation failed
    exit /b 1
)
echo Build successful (without Python bridge)

:end
