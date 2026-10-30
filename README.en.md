# Meowlisis!

[![中文](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-README-red?style=for-the-badge)](README.md) [![English](https://img.shields.io/badge/English-README-blue?style=for-the-badge)](README.en.md)

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> This project is open source under the [MIT License](LICENSE).

```
I started coding because I wanted someone to chat with while I make animations.
Then I couldn't find anyone, so I turned a little cat into a person awa
Updates come whenever they come — you can occasionally catch me in @YGZ醒脑片's livestream on Bilibili
```

## First Things First
- This is the GitHub source code area.
- All-in-one package: [Baidu Netdisk] Link: https://pan.baidu.com/s/1Ea-LSXFDMSUIN0o-9n4OBQ?pwd=0204 Code: 0204 
--Shared from a Baidu Netdisk super member v2
- Huge thanks to the open-source projects I took some cues from:
- The overall framework logic gave me some inspiration: [@worm128/AI-YinMei](https://github.com/worm128/AI-YinMei)
- TTS timbre optimization: [@High-Logic/Genie-TTS](https://github.com/High-Logic/Genie-TTS)
- My favorite catgirl project — I learned a lot from its memory module: [@Project-N-E-K-O/N.E.K.O](https://github.com/Project-N-E-K-O/N.E.K.O)
- TTS synthesis acceleration: this is the project where I first learned about GPU graph acceleration: [@chinokikiss/GSV-TTS-Lite](https://github.com/chinokikiss/GSV-TTS-Lite)
- WDA: it got the XCTest connection to an iPhone working — greatness needs no explanation: [@appium/WebDriverAgent](https://github.com/appium/WebDriverAgent)

## Features

[<img src="工作流程解析/【待完善】meowlisis工作流程.webp" width="600" alt="Meowlisis core feature flowchart (work in progress)">](工作流程解析/【待完善】meowlisis工作流程.webp)

*⚠️ Core feature flowchart (work in progress — click the image to view it full size)*

For the full feature, module, configuration and runtime documentation, see [Detailed module documentation](INSTRUCTION.en.md).

- Runtime: Windows 10/11, Python 3.11 (the project bundles its own runtime); dependencies are in requirements.txt
- Quick start: see "Runtime Environment" in the manual

## Some Original Algorithms
```Might not be original either — I just made it all up as I went, but take a look if you're curious```
### 1. Optimizing LLM Filler Words

```
Corresponding modules:
func/llm/narration/
```

Idea: when an LLM reply is "watery" (all boilerplate and filler), compress it automatically; when the reply is rich, keep the vocal tics intact, so the synthesized speech doesn't sound wordy or flat. The core is a three-layer structure: score → tier → streaming cleanup:

1. **Filler-word dictionaries → Trie**: `adjunct_word.json` holds deletable words (used for both scoring and deletion), `score_only_word.json` holds score-only words (persona vocal tics); both build a Trie with longest-match-first lookup, O(word length).
2. **EWMA smoothed scoring** (each round uses the source text before cleanup):
   - `Raw = max(0, density − penalty)`
   - `density = 100 − (W/L)×100`, and when `W/L ≥ density_threshold`, `density = 0` (W = total filler-word length, L = text length)
   - `penalty = min(length_penalty_cap, max(0, L − length_threshold) × length_penalty_rate)`
   - `S = λ·S_prev + (1−λ)·Raw`, where `λ = λ_down (Raw<S) / λ_up (Raw>S) / λ_equal (Raw=S)`
3. **Three-tier streaming cleanup** (the tier is set by S):
   - `S ≥ part_level_upper` → delete nothing (FULL)
   - `part_level_lower ≤ S < part_level_upper` → delete only categories ∈ {2,3,5} (PART)
   - `S < part_level_lower` → delete every deletable word (ALL)
   - Character-by-character `feed`: longest Trie match, deletable words are dropped according to the tier, a matched prefix is held back for now; `flush()` finishes it off.
4. **Punctuation tidying**: after cleanup, runs of punctuation collapse into a full stop, leftover sentence-initial punctuation is removed, and punctuation-only sentences are never sent; the text is then split at punctuation into clauses and streamed into TTS, so the pauses sound natural.

Related config: `config.yml → llm.narration`.

### 2. Hum-and-Continue Song Trigger

```
Corresponding modules:
func/toolbox/meowsongs/hum_detect/hum_detect.py
func/toolbox/meowsongs/pass_the_baton
func/pipeline/toolbox_audio.py
```

Idea: while the character is singing, the user hums along for a bit; the character works out which song it is and how far the humming got, then **sings the next few lines** (passing the baton), announces its thoughts and writes it into memory.

1. **Hum detection**: frame-by-frame RMS energy; `rms ≥ vad_energy_threshold` (SenseVoice config) counts as voiced and accumulates, while silence `≥ silence_threshold` marks the end of a segment; accumulating `≥ hum_collect_sec(7s)` decides immediately. pyin extracts F0 (65–800Hz) → MIDI pitch, and only voiced frames are counted. The criteria are:
   - voiced-frame ratio: `|voiced|/|f0| ≥ f0_voiced_ratio`
   - stable-frame ratio: `mean(|Δmidi| < f0_stable_half_step) ≥ f0_stable_ratio`
   - unique note count: `len(unique(round(midi))) ≥ f0_unique_notes`
2. **Song lock in 7 seconds (lock)**: yin extracts F0 (80–800Hz) to get the hummed pitch sequence, mean-centers it together with each song's cached vocal pitch (npy) as `midi' = midi − mean(midi)`, then runs a vectorized sliding-window cosine `score = max_i dot(w_i,q)/(‖w_i‖·‖q‖)`; it only locks `{title, offset = best_idx×HOP/SR}` when `score ≥ match_threshold` and the gap to the runner-up is `≥ min_margin`.
3. **Continue singing at segment end (sing)**: the whole hum is matched again in one go, and the aligned position is the offset. The LRC timeline locates the lyrics: `user_lyric` = the lyrics inside `[offset, offset+hum_duration]`; take `hum_lines` lines starting from the first line after `offset+hum_duration`; play `vocal[start_sec : end_sec]` (end = the start of the next line, or the end of the song if there is none).
4. **Memory and thoughts**: the lyrics the user hummed and the lyrics the AI sang are written into short-term/long-term/user memory (type=hum_song); once the continuation finishes playing, the toolbox LLM generates a comment from a template (song title plus the sung lines) and speaks it; if nothing was locked or the margin was too small, the candidate songs and a "don't start singing yet" note go to the LLM with a `[System]` prefix, and the character confirms in its own words whether the user really is singing.

Related config: `config.yml → meowsongs.pass_the_baton`.

### 3. Director (performance planning for proactive replies)

```
Corresponding modules:
func/llm_active/director
func/pipeline/msg_director.py
```

Idea: when the character speaks up after being idle, it doesn't just say something at random — it first lays out a performance plan that can be advanced step by step, then moves one step per turn.

1. **Planning**: `director_plan` outputs steps, each with goal (what this step should achieve), move (what to do), expect (the expected reaction), and if_not (what to do if it doesn't happen).
2. **Execution**: while the Director is active, user turns are taken over by `msg_director.py`, reusing the main-chain reply logic; each turn advances or completes exactly one step.
3. **Advancing and wrapping up**: `director_step` marks done / adjust / advance / clear; missed marks accumulate as `stall_turns` and trigger a catch-up judgement; it wraps up when everything is done or the user clearly refuses.
4. **Material**: the planning stage can read `character/memory` and reuse the Bilibili video material pool.
5. **Persistence and prompt**: state goes to `.temp/director_topic/main.json`, archived to `character/director_topic/main/` on clear; `director_block.py` renders the current plan as a "current conversation arc" block spliced into system_prompt.
6. **QQ simplified version**: `func/toolbox/napcat/director` has its own state, judge and prompt block, and takes no part in group bubble-in.

Related config: `config.yml → llm_active.director`, `napcat.director_qq`.

## To do list
1. Configure matching reference audio for each prompt
2. Finish the under-construction parts

## Related Docs
- Plugin system: [plugins/plugins.en.md](plugins/plugins.en.md)
- CatPaws service: [.vendor/.CatPaws/README.en.md](.vendor/.CatPaws/README.en.md)
- Phone UI: [.vendor/.cam/README.en.md](.vendor/.cam/README.en.md)
