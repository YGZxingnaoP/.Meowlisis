# Memory Recall Lab (memory_recall_lab)

> [中文](README.md) | English

> **This directory is experiment-only; it takes no part in running the main program.** Not a single line of the main program was changed.
> Goal: use real corpus to turn the two problems "indexing" and "matching/recall" into comparable, reproducible experiments,
> and arrive at **the best algorithm and parameters available today** instead of changing weights by gut feeling.

## 1. Why This Directory Exists

The main program's current recall (`func/catbrain/AbstractMem/load_abmem.py`) is one full linear scan plus a weighted sum.
Which link exactly breaks when "more records means less accurate", and what to replace it with, can't be answered by reading code alone — you need a ruler.

This directory is that ruler: real corpus + a hand-labelled eval set + multi-algorithm comparison + grid search.

## 2. Files

| File | Purpose |
|---|---|
| `lab_core.py` | Corpus loading, tokenization, four kinds of index (word inverted / character bigram / tag / entity / month), BM25 |
| `lab_algo.py` | Recall algorithms: current baseline, minimal fix, five-way hybrid, two BaiShou (白守) retrieval variants |
| `lab_eval.py` | Metrics, variant comparison table, coordinate-descent grid search; writes `lab_result.json` |
| `tune.py` | Targeted comparisons around the grid optimum; outputs a recall–precision–noise–size tradeoff table |
| `ablate_dict.py` | Single-point ablation: jieba user dictionary vs character-bigram channel |
| `sweep_gate.py` | Gate sweep: no count cap, just finding where the relevance line should sit |
| `verify_production.py` | Validates the actual behavior of the main program's implementation (`func/.../recall_index.py`) |
| `diagnose.py` | Per-query diagnosis: was a miss because "ranking didn't get it in", "the gate blocked it", or "the budget cut it off" |
| `probe.py` | Labeling aid: lists the candidate entries per query so a human can pick gold |
| `goldset.json` | **The eval set (single source of truth)**: 21 positives + 14 negatives |
| `lab_result.json` / `lab_tradeoff.json` | Dumped run results |

## 3. How to Run

```powershell
# use the runtime bundled with the project, not the system python
cd scripts\memory_recall_lab

..\..\runtime\311\python.exe lab_eval.py      # full comparison + grid search (~30 seconds)
..\..\runtime\311\python.exe tune.py          # tradeoff table around the optimum
..\..\runtime\311\python.exe ablate_dict.py   # user dictionary vs character bigram
..\..\runtime\311\python.exe diagnose.py      # per-query look at where misses come from (default recommended config)
```

Reads only `character/abstract_memory/meow-*.json`; writes nothing to `.temp/` or `logs/`, and calls no LLM.

## 4. How the Eval Set Was Built (and Its Limitations)

**Construction**

1. `probe.py` lists, for each query, the candidate entries that "contain any query term" (up to 8, ordered by number of matched terms and IDF).
   It deliberately **does not sort with the algorithm under test**, avoiding "the algorithm under test setting the questions for the algorithm under test".
2. Each entry is judged by hand as `must` (core answer) or `ok` (related but not the answer).
3. Three kinds of negative: pure pleasantries (随便 / "whatever", 晚安 / "good night", 哈哈哈 / "hahaha"), out-of-scope questions (现在几点 / "what time is it"), and **hard negatives**
   ("what model is my computer's graphics card" — the corpus has 5 entries mentioning 显卡 / graphics card but not one answers the model).

**Scale**: 21 positives + 14 negatives, 44 `must` entries in total.

**Ceiling**: `q02` (asking about "that Japanese song", target 《星降る海》) and `q04` (asking about "that meal", target 「小鱼干外卖」 / dried-fish takeout)
have **zero literal overlap** with the original record, so no lexical method can possibly recall them. Hence the theoretical ceiling on macro recall is about **0.905**, not 1.0.

**Limitations (you must know these)**

- Individual `must` judgements were made by me by hand, so they are subjective; but the `must` sets are small (mostly 1~4 entries), so a wrong call has limited impact.
- 432 corpus entries and 35 queries is small; the **direction** of the conclusions is reliable, the **specific thresholds** need re-checking on a bigger corpus.
- There is no vector/semantic channel (no embedding service on this machine), so gains from "semantic paraphrase" are unmeasured and the ceiling is underestimated.

## 5. Metric Definitions

All comparisons use the same budget, **top-k = 8**, to avoid the fake advantage of "more returned means more hits".

| Metric | Meaning |
|---|---|
| `recall_must` | Number of core answers recalled / total core answers (macro average) |
| `prec_rel` | Share of "core + related" among the recalled results (macro average) |
| `mrr` | Reciprocal rank of the first core answer |
| missed | Number of positives that returned 0 entries |
| noise | Average number of entries injected for negatives (ideal 0) |
| clean recall | Share of negatives that returned 0 entries (ideal 1) |
| avg items / chars | Average entries injected across all queries / average characters rendered in production format |
| `ms` | Time per recall |

Composite score = `F1(prec_rel, recall_must) − 0.3 × noise/8 − 0.02 × missed`.
F1 rather than a weighted sum: a weighted sum gets held hostage by units and weight choices, whereas F1 gives an equally low score to "high recall but all noise" (the current state) and to
"clean but misses answers" (character bigram only) — which is exactly what we want.

## 6. Conclusion: The Recommended Approach

### 6.1 Measured Comparison (432 corpus entries / 35 queries / top-8)

| Approach | recall | prec | mrr | missed | noise | clean recall | avg items | chars | ms |
|---|---|---|---|---|---|---|---|---|---|
| **Current (main program)** | **0.722** | 0.298 | 0.565 | 0 | **8.00** | 0.00 | 30.0 | 875 | 10.5 |
| **★ Recommended** (word + tag + entity + time) | 0.691 | **0.705** | **0.726** | 0 | **1.36** | 0.64 | **2.7** | **282** | **0.1** |
| Recall-first (recommended + character bigram) | 0.714 | 0.657 | 0.676 | 0 | 2.00 | 0.07 | 3.2 | 332 | 0.1 |
| Minimal fix (formula only) | 0.528 | 0.706 | 0.528 | 5 | 0.93 | 0.64 | 2.1 | 227 | 9.7 |
| Character bigram only | 0.325 | 0.861 | 0.476 | 9 | 0.71 | 0.64 | 0.9 | 95 | 2.6 |
| BaiShou-style short-circuit | 0.000 | 0.000 | 0.000 | 21 | 0.00 | 1.00 | 0.0 | 7 | 0 |
| BaiShou-style whole-sentence LIKE | 0.000 | 0.000 | 0.000 | 21 | 0.43 | 0.93 | 0.2 | 24 | 0 |

**In one sentence**: recall is essentially flat (0.722 → 0.691, **−4%**; 0.714, **−1%**, with the character bigram on),
precision 0.298 → 0.705 (**2.4×**), negative-set noise 8.0 entries → 1.36 entries (**−83%**),
injected size 875 → 282 characters (**−68%**), time 10.5 ms → 0.1 ms (**about 100×**).

> The "recommended" row above corresponds to the **frozen constant** `lab_algo.RECOMMENDED`;
> `tune.py`, `diagnose.py`, and `ablate_dict.py` all reference it directly and read no intermediate dump files.

> **Reproducibility**: the recall path contains "set → dict + tie-breaking sort", whose order depends on `PYTHONHASHSEED`.
> Without a fixed seed, the same config drifts by **±0.03** in recall from run to run — enough to rank a good approach below a bad one.
> So `lab_core.py` pins the seed to 0 on first import and restarts the process; no external setup needed.

### 6.1b How the Shipped Implementation Actually Performs

The lab is only the design space; what actually ships is `func/catbrain/AbstractMem/process/recall_index.py`.
`verify_production.py` imports the main program's implementation directly and runs the same goldset against it.

**No cap on the number of entries** — only one relevance gate remains, with `summary_top_limit` (30) as a last-resort backstop:

| Basis | recall | prec | mrr | missed | noise | avg items | max | chars | ms |
|---|---|---|---|---|---|---|---|---|---|
| Old approach (fixed budget of 30) | 0.722 | 0.298 | 0.565 | 0 | 8.00 | 30.0 | 30 | 875 | 10.5 |
| **New approach · full injection** | **0.865** | 0.492 | 0.629 | 0 | **1.71** | **5.8** | 19 | **611** | **0.12** |
| New approach · top-8 on the same basis | 0.746 | 0.493 | 0.621 | 0 | 1.71 | 4.5 | 8 | 472 | 0.12 |

Read both numbers: `top-8` is what makes the comparison against the old approach fair (the old approach also only counts the first 8 hits),
while `full injection` is what the model actually sees.

### 6.1c A Gate and a Cap Are Two Different Things

- **Gate**: `this entry's BM25 ≥ the batch's top score × recall_gate_ratio`; anything below the line doesn't appear.
- **Cap**: truncation by count. **Removed**; only `summary_top_limit` remains as a backstop.

`sweep_gate.py` sweeps the gate with "no count cap":

| gate_ratio | avg items | max | recall | prec | noise | chars |
|---|---|---|---|---|---|---|
| 0.00 (any hit counts) | 8.9 | **70** | 0.881 | 0.431 | 1.71 | 931 |
| 0.02 | 5.9 | 19 | 0.865 | 0.497 | 1.71 | 614 |
| 0.30 (current default) | 5.8 | 19 | 0.865 | 0.492 | 1.71 | 611 |
| 0.45 | 5.3 | 19 | 0.865 | 0.538 | 1.71 | 555 |
| 0.50 | 4.7 | 19 | 0.833 | 0.641 | 1.64 | 493 |
| 0.60 | 4.2 | 19 | 0.730 | 0.630 | 1.64 | 439 |

Three conclusions:

1. **Between 0.02 and 0.45 the gate is on a plateau**, with recall completely identical (0.865). What really limits the count here is the tag channel,
   not the word-channel gate — `q11 "what do you think of my values"` injects 19 entries, exactly the number of corpus entries carrying the 价值观 (values) tag.
2. **ratio=0 runs away**: `q07「异环音乐教室…」` ("Otherworld music classroom…") injects 70 entries in one go (73 corpus entries mention 异环),
   chars 931, precision down to 0.431. "Only exclude when relevance is absurdly low" still needs a line drawn for what counts as "absurdly".
3. **Above 0.5 recall really starts dropping** (0.865 → 0.833 → 0.730). The default is 0.30: on the inside edge of the plateau,
   more forgiving on unfamiliar corpus, while avoiding the runaway at 0.

One more: **the core anchors (entity/month hits) are bad on their own** — routing only through the core path gives recall of just 0.345;
the workhorse has always been the keyword/tag supplementary path. So the core path keeps a fixed 5-entry cap and is not opened up.

### 6.2 Recommended Configuration

```python
k1 = 0.9            # BM25 term-frequency saturation
b  = 0.5            # BM25 length normalization
field_weights = {"event": 1.0, "tags": 0.5, "joint": 0.3}

# Query cleanup (four steps, all deterministic, no model)
drop stopwords → drop pure numbers → drop nickname fragments → drop words with df > 10% of the corpus

# Channels
word BM25  +  tag IDF  +  exact entity  +  retrospective time window
(character bigram off by default; turn it on when you need more recall, at the cost of doubling negative noise)

# Fusion: symmetric RRF
score(d) = Σ_channels 1 / (rank(d) + 60)

# Gates
word channel: bm25 ≥ 0.5 × the batch's top score   # relative threshold, scales automatically with corpus size
tag channel: the tag's IDF ≥ 3.5                   # suppresses topic-named tags like 「日常 / 闲聊」 (daily / chit-chat)
entity/time: any hit passes
character bigram (if on): IDF sum over the line AND at least 2 bigrams hit

# Budget
core (entity/time) ≤3 + supplementary ≤5 = hard cap of 8
fall back to 1 when everything dies
```

### 6.3 Three Key Design Points (All Forced by Measurements)

**① Relevance must be a continuous quantity, not a boolean.**
The current `hits / 1.0` makes "one matching word = full marks", so the gate does nothing and ranking is handed to the priors.
BM25 uses `idf × tf/(tf + k1·(1−b+b·|d|/avg|d|))`, so a rare word like 「英语六级」 (CET-6) automatically gets high weight,
while a word like 「主人」 (master) that appears in 86% of records automatically tends toward zero.

**② The gate must use a relative threshold, not a fixed constant.**
Fixed thresholds (0.15 / 0.4 / 2.0) inevitably fail when the corpus grows from 432 to 4320:
the candidate set gets bigger, the score distribution shifts right as a whole, and a fixed line either lets everything through or blocks everything.
Switching to "50% of this batch's top score" or "the P75 of this batch's candidates" makes the threshold scale with corpus size —
this is the key move that cures "more records means less accurate".

**③ Tags must be their own channel, not stuffed into BM25.**
Tags are highly collinear with topics (three of the top four most frequent tags are topic names), and stuffing them into BM25 drags `idf` close to 0,
flattening all 19 「价值观」 entries (measured: the target record was pushed to BM25 ranks 16/18, i.e. effectively dead).
As its own channel, a hit on a rare tag that occurs only once is a strong signal — 72% of them get hit.

## 7. Ablation: What Didn't Work, and Why

All of these were **shot down by measurement**; recorded here so nobody steps on them again.

| Attempt | Result | Why |
|---|---|---|
| **Character bigram as its own channel** | F1 0.698 → 0.685; negative noise 1.36 → 2.00; clean recall 0.64 → 0.07 | For a single-bigram query (「晚安」 / "good night"), hitting one bigram and normalizing by the query's own IDF gives 1.0 — the same saturation disease as `hits/1.0`. The "at least 2 bigrams" constraint still isn't enough; it lets negatives through indiscriminately. It did lift recall from 0.691 to 0.714, at the cost of flooding 13 of the 14 negatives with noise |
| **Pouring the tag vocabulary into the jieba user dictionary** | F1 0.698 → 0.657 | All 272 tag phrases were treated as single words, swallowing matchable substrings instead (e.g. 「介绍认识」 merged into one word, so searching for 「认识」 finds nothing) |
| **Keeping only the character-bigram path** | Highest precision at 0.861, but recall 0.325 and 9 missed | It's good at exactly matching known fragments, not at recalling from scratch |
| **BaiShou-style "short-circuit as soon as a name hits"** | Recall 0.000, all 21 positives missed | No query in the eval set contains a registered nickname; once the name doesn't hit, nothing is recalled at all |
| **BaiShou-style whole-sentence substring LIKE** | Recall 0.000, all 21 missed | Chinese has no spaces, so matching a whole sentence as a phrase almost never intersects (which also explains why BaiShou's "hybrid retrieval" is equivalent to pure vector search in Chinese) |
| **"Minimal fix" that only changes the formula** | Recall 0.691 → 0.528, 5 missed | The formula is right now, but it's still an O(N) linear scan with no IDF/tag channel; proof that **indexing is not optional** |
| **Character bigram alone** | Precision 0.861 (the best of all), but recall 0.325 and 9 missed | Good at exactly matching known fragments, not at recalling from scratch |
| **Turning the tag channel off** | F1 0.698 → 0.668 | It's the only path that rescues tag-semantic queries like 「价值观 / 哲思」 (values / philosophy) |
| **Switching the gate to an absolute P75** | F1 0.693 → 0.633 | Absolute thresholds aren't robust to distribution shift; relative ratios are steadier |
| **Turning the entity/time channels off** | No change | The eval set has no "name a specific person" or "this time last year" style queries — **the value of these two paths is simply not covered by this eval**, so you can't conclude they're useless from this |

## 8. Notes for Wiring This Into the Main Program

1. **The index must hang off the existing write-path lock.** The main program's `save()` rewrites a whole month (`load_abmem.py:120-147`);
   a concurrent index update would read a half-updated state.
2. **The injection format needs slimming too.** Of the current 104 characters per line, about 48% is `[topic｜tags｜participants｜time]` metadata;
   this experiment's `chars` column is computed in the production format and already includes it, so 283 characters is the real value including metadata.
3. **Don't touch the write path.** Across 432 memory entries there are 0 exact duplicate groups and 0 near-duplicate pairs — write quality is good.
4. **`joint` field key drift**: 425/478 participant entries use the `id` key, while `joint_util.resolve()` reads only `meowid`.
   The lab's `_joint_of()` reads both keys; the main program needs the same fix (otherwise the entity channel fails on 89% of older records).
5. **The switch must go through shadow mode**: run old and new side by side first, log only without taking effect, and verify on real conversations,
   because dropping the injected count from 30 to 3 changes model behavior — that's the biggest risk in this change, and it's not an algorithmic one.

## 9. If You Want to Keep Going

- **Add a vector channel**: there's no embedding service on this machine, so semantic paraphrase (「英语六级」 ↔ 「六级考试」) is uncovered.
  A small local model (10ms-ish on CPU) should be able to recover those 2 hard negatives and 2 zero-overlap positives.
- **Grow the eval set**: it's 35 queries now. Expanding to 150+ and adding "name a specific person" / "this time last year" style queries
  is what it takes to validate the real value of the entity/time channels.
- **Scale the corpus**: bring in history beyond `.temp/public_short_mem.json` and measure behavior at 2000+ entries.
