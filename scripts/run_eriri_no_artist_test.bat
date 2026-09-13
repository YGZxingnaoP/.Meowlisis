@echo off
rem ============================================================================
rem  Eriri - MODEL-ONLY test, NO artist tag at all
rem
rem  Purpose:
rem    Measure what the Anima model ITSELF does with the character tag, with
rem    zero artist-style influence. Then run the SAME settings for Utaha, so you
rem    can tell whether faces are still homogenized:
rem        Eriri vs Utaha look clearly different  -> the artist/style layer was
rem                                                  the homogenizer (an artist
rem                                                  tag carries that artist's
rem                                                  own "face template").
rem        Eriri vs Utaha still the same face     -> the model + aesthetic LoRA
rem                                                  is the homogenizer.
rem
rem  Everything else is locked: same seed / same canvas / same framing /
rem  same negative (except where noted). Only the character tag + anchors differ.
rem
rem  Run:  double-click this file, or:  scripts\run_eriri_no_artist_test.bat
rem  Output: .ComfyNode\output\eriri_noartist\   (opened at the end)
rem
rem  Tweak points:
rem    SEED   - fixed so all rows are directly comparable.
rem    CANVAS - 1024x1024 keeps the face large enough to judge.
rem    DOPRO  - 1 = also run one full PRO row at the end (~11 min extra),
rem              which shows whether stage 07 (upscale + face/eye redraw)
rem              flattens the face. 0 = fast rows only (~1.5 min each).
rem ============================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

if not exist "runtime\python.exe" (
    echo [ERROR] runtime\python.exe not found. Run this from the project root.
    pause
    exit /b 1
)

set "SEED=111"
set "CANVAS=1024x1024"
set "OUTSUB=eriri_noartist"
set "DOPRO=0"

rem ---- appearance anchors (identical in every row that uses them) ----
set "ANCH=blonde hair, long hair, twintails, blue eyes, flat chest, school uniform"
set "FRAME=upper body, looking at viewer"
set "CHAR=sawamura eriri, saenai heroine no sodatekata"

rem ---- negatives ----
set "NEGBASE=worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, watermark"
set "NEGMATURE=worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, watermark, mature female, adult, onee-san, old, tall, milf"

rem ---- NO artist anywhere: --no-artist, and no --artist flag ----
set "FASTARGS=runtime\python.exe scripts\flash_pro_probe.py --mode fast --canvas %CANVAS% --seed %SEED% --no-dump-all --out-subdir %OUTSUB% --no-artist"
set "PROARGS=runtime\python.exe scripts\flash_pro_probe.py --mode pro --canvas %CANVAS% --seed %SEED% --out-subdir %OUTSUB% --no-artist"

echo.
echo ##########  Eriri MODEL-ONLY test (no artist tag)  ##########
echo #  SEED = %SEED%    CANVAS = %CANVAS%    ARTIST = (none)
echo #  Check each run prints:  实际画师串 : ''
echo.

echo ===== [1/5] N1_tag_only : character tag ONLY, no appearance hints =====
echo        (pure model prior for the tag - what Anima thinks she looks like)
%FASTARGS% --label N1_tag_only --negative "%NEGBASE%" --positive "1girl, solo, %CHAR%, %FRAME%"
echo.

echo ===== [2/5] N2_tag_anchors : tag + full appearance anchors =====
%FASTARGS% --label N2_tag_anchors --negative "%NEGBASE%" --positive "1girl, solo, %CHAR%, %ANCH%, %FRAME%"
echo.

echo ===== [3/5] N3_anchors_face : N2 + age/face anchors + anti-mature negative =====
echo        (this is the config-level lever that already tested well in E)
%FASTARGS% --label N3_anchors_face --negative "%NEGMATURE%" --positive "1girl, solo, %CHAR%, cute face, petite, %ANCH%, %FRAME%"
echo.

echo ===== [4/5] N4_nolora : N3 with LoRA turned OFF (--lora-mul 0) =====
echo        (does the aesthetic LoRA wash out the character's own face?)
%FASTARGS% --label N4_nolora --lora-mul 0 --negative "%NEGMATURE%" --positive "1girl, solo, %CHAR%, cute face, petite, %ANCH%, %FRAME%"
echo.

echo ===== [5/5] N5_utaha_ref : REFERENCE character, identical settings =====
echo        (compare N3 vs N5: if the two faces are clearly different, the
echo         artist/style layer was what homogenized them; if not, it is the model)
%FASTARGS% --label N5_utaha_ref --negative "%NEGMATURE%" --positive "1girl, solo, kasumigaoka utaha, saenai heroine no sodatekata, mature face, tall, long black hair, purple eyes, school uniform, %FRAME%"
echo.

if "%DOPRO%"=="1" (
    echo ===== [6/6] N6_pro : N3 again in PRO mode (keeps per-stage dumps) =====
    echo        (compare 03_usdu_tiled vs 05_detailer_2_face vs 06_detailer_3_eye
    echo         to see whether stage 07 flattens the face)
    %PROARGS% --label N6_pro --negative "%NEGMATURE%" --positive "1girl, solo, %CHAR%, cute face, petite, %ANCH%, %FRAME%"
    echo.
)

echo ##########  Done.  ##########
echo.
echo Output folder:  .ComfyNode\output\%OUTSUB%\
echo.
echo How to read the results:
echo   N1 recognizable              -^> the model genuinely knows "sawamura eriri": the tag alone carries her look
echo   N1 vague, N2/N3 much better  -^> the tag needs appearance anchors alongside it (keep them in positive)
echo   N3 best of the fast rows     -^> anti-mature negative + face anchors is the cheap win
echo   N4 sharper/more distinct     -^> the aesthetic LoRA was washing out character identity: lower its strength
echo   N3 vs N5 clearly different   -^> NO artist needed for distinct faces: the artist tag was the homogenizer
echo   N3 vs N5 same-looking face   -^> homogenization comes from the model/style: needs per-character anchors or a character LoRA
echo.
dir /b /o-n ".ComfyNode\output\%OUTSUB%" 2>nul
echo.
start "" explorer ".ComfyNode\output\%OUTSUB%"
pause
