@echo off
rem ============================================================================
rem  Eriri (Sawamura Eriri) character-tag matrix - FAST mode, one click
rem
rem  What it does: 6 runs of Anima FAST (single-pass) sampling.
rem  Everything is LOCKED except the character tag:
rem      same seed / same artist / same canvas / same appearance anchors
rem  => any visual difference can only come from the character tag itself.
rem
rem  Run:  double-click this file, or:  scripts\run_eriri_tag_matrix.bat
rem  Output: .ComfyNode\output\eriri_matrix\   (opened at the end)
rem
rem  Tweak points:
rem    ARTIST  - artist style tag (default kantoku). Change to drawfag /
rem              soriham / nininikal, or leave empty ("") for no artist at all.
rem              KEEP IT THE SAME for every run, otherwise the face changes
rem              for a reason unrelated to the tag.
rem    SEED    - fixed so all 6 images are directly comparable.
rem ============================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

if not exist "runtime\python.exe" (
    echo [ERROR] runtime\python.exe not found. Run this from the project root.
    pause
    exit /b 1
)

set "ARTIST=kantoku"
set "SEED=111"
set "CANVAS=1024x1024"
set "OUTSUB=eriri_matrix"
set "COMMON=blonde hair, long hair, twintails, blue eyes, flat chest, school uniform, upper body, looking at viewer"
set "NEGBASE=worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, watermark"
set "NEGMATURE=worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, watermark, mature female, adult, onee-san, old, tall, milf"

set "ARGS=runtime\python.exe scripts\flash_pro_probe.py --mode fast --canvas %CANVAS% --seed %SEED% --no-dump-all --out-subdir %OUTSUB%"
rem ARTIST empty  -> no artist at all;  ARTIST set -> exactly that one artist, no random extra
if "%ARTIST%"=="" set "ARGS=%ARGS% --no-artist"
if not "%ARTIST%"=="" set "ARGS=%ARGS% --artist %ARTIST% --no-artist"

echo.
echo ##########  Art chunk: A / B / C / D / E / F  ##########
echo #  ARTIST = %ARTIST%     SEED = %SEED%     CANVAS = %CANVAS%
echo #  Only the character/series tag differs between runs.
echo.

echo ===== [1/6] A_canon : sawamura eriri + series  (danbooru order) =====
%ARGS% --label A_canon --negative "%NEGBASE%" --positive "1girl, solo, sawamura eriri, saenai heroine no sodatekata, %COMMON%"
echo.

echo ===== [2/6] B_west : eriri spencer sawamura  (western order) =====
%ARGS% --label B_west --negative "%NEGBASE%" --positive "1girl, solo, eriri spencer sawamura, %COMMON%"
echo.

echo ===== [3/6] C_bare : eriri  (ambiguous / bare tag) =====
%ARGS% --label C_bare --negative "%NEGBASE%" --positive "1girl, solo, eriri, %COMMON%"
echo.

echo ===== [4/6] D_nochar : no character tag at all  (appearance-only baseline) =====
%ARGS% --label D_nochar --negative "%NEGBASE%" --positive "1girl, solo, %COMMON%"
echo.

echo ===== [5/6] E_canon_neg : A + anti-mature negative  (face-age lever test) =====
%ARGS% --label E_canon_neg --negative "%NEGMATURE%" --positive "1girl, solo, sawamura eriri, saenai heroine no sodatekata, %COMMON%"
echo.

echo ===== [6/6] F_canon_cinema : A + production-like cinema paragraph =====
%ARGS% --label F_canon_cinema --negative "%NEGBASE%" --cinema "A girl stands in a sunlit classroom, smiling shyly at the camera. Her long blonde twintails catch the warm light. She is framed from the chest up, softly lit, playful and cheerful." --positive "1girl, solo, sawamura eriri, saenai heroine no sodatekata, %COMMON%"
echo.

echo ##########  Done.  ##########
echo.
echo Output folder:  .ComfyNode\output\%OUTSUB%\
echo.
echo How to read the results:
echo   A recognizable + B/C/D NOT          -^> model knows "sawamura eriri": a mis-spelled tag is the root cause
echo   A/B/C/D all about the same          -^> model barely uses the tag: the face comes from the anchors, not the tag
echo   C shows a DIFFERENT mature girl     -^> bare "eriri" is ambiguous and hits another character (explains the "onee-san face")
echo   E younger than A                    -^> anti-mature negative works (one-line config fix)
echo   F more mature than A                -^> the cinema paragraph outweighs the tag
echo.
dir /b /o-n ".ComfyNode\output\%OUTSUB%" 2>nul
echo.
start "" explorer ".ComfyNode\output\%OUTSUB%"
pause
