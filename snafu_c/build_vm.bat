@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 (
    echo vcvarsall failed
    exit /b 1
)
cd /d "D:\visual studio projects\snafulang\snafu_c"

echo.
echo === Building snafu (tree-walker) ===
cl /O2 /std:c++17 /W3 /EHsc /D_CRT_SECURE_NO_WARNINGS /D_CRT_NONSTDC_NO_DEPRECATE /Fe:snafu.exe snafu_main.cpp snafu_value.cpp snafu_scope.cpp snafu_lexer.cpp snafu_parser.cpp snafu_eval.cpp snafu_prelude.cpp
if errorlevel 1 (
    echo Tree-walker build failed
    exit /b 1
)
echo Tree-walker build successful

echo.
echo === Building snafu_vm (bytecode VM) ===
cl /O2 /std:c++17 /W3 /EHsc /D_CRT_SECURE_NO_WARNINGS /D_CRT_NONSTDC_NO_DEPRECATE /Fe:snafu_vm.exe snafu_vm_main.cpp snafu_bytecode.cpp snafu_value.cpp snafu_scope.cpp snafu_lexer.cpp snafu_parser.cpp snafu_eval.cpp snafu_prelude.cpp
if errorlevel 1 (
    echo Bytecode VM build failed
    exit /b 1
)
echo Bytecode VM build successful
echo.
echo Both builds completed successfully
