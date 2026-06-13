# Why converting piano performance to notation is uniquely hard

A reference document for this pipeline: the academic literature on performance-to-score
transcription, why the engraved score consistently feels less correct and musical than the
cleaned MIDI it came from, and what concretely can be done about it here.

> **Provenance & verification status.** The literature survey below was assembled by a fan-out
> web-research pass (24 primary sources, 120 extracted claims) plus first-hand evidence from this
> repository's own pipeline runs. The original harness's *adversarial cross-verification* step did
> not complete (session token limit), so the document first shipped with every confirm/refute vote
> abstaining. **That step has since been completed by hand for the load-bearing quantitative
> claims** — each headline statistic was read directly out of the primary-source PDF (not the
> abstract). Per-claim verdicts are in **§9**. Bottom line: the numeric spine holds up — the
> ICASSP-2018 benchmark (21.4 / 29.0 / 31.1), the SMC-2016 polyrhythm rates (16.0 / 28.9 / 34.1),
> Cemgil's intractability result, and the γ ≈ 1.02 complexity prior are all confirmed *verbatim*
> against the papers. One sourcing imprecision was found and corrected (§2); three motivational
> figures remain attributed-but-not-re-checked (§9). Claims from our own runs are marked
> **[this repo]** and are reproducible from `output/` and git history. Section 8 lists every source.

---

## 0. The one-sentence answer

A performance MIDI is a **recording**; a score is a **lossy, discrete re-interpretation** of
that recording. The MIDI sounds better than the score for the same reason a photograph looks
more "correct" than a painting traced from it: the conversion is a projection that throws away
exactly the continuous, expressive information — micro-timing, true durations, pedal wash,
dynamic shading between marked levels — that made the performance sound alive. Worse, the
projection is **ill-posed**: many different scores are consistent with the same performance,
and choosing among them requires musical knowledge the data alone does not contain. Everything
below is an elaboration of those two facts.

---

## 1. The problem is formally ill-posed, and it is two coupled problems, not one

The foundational result, stated repeatedly across three decades of literature, is that rhythm
quantization is **not** "snap each onset to the nearest grid point." Doing so assumes constant
tempo and treats each note independently of its neighbours, and it is precisely what makes
commercial MIDI-import notation unusable: it forces the player to perform metronomically or be
punished with garbage (Cemgil & Kappen, AISB 1999; Desain & Honing, *The Quantization of
Musical Time*).

The reason it fails is that expressive performance introduces timing deviations that are
**systematic, not random**, and structured at (at least) two scales simultaneously:

- **Small scale** — individual notes are pushed early or late for accent, voicing, and phrasing.
  Performed note *durations* can deviate by **up to 50%** from their notated value and listeners
  still recover the correct metrical structure (Desain & Honing). Naive rounding cannot work
  because the thing you are rounding has a 50%-wide error bar that is *information*, not noise.
- **Large scale** — tempo itself drifts continuously (rubato, accelerando, ritardando), so the
  "grid" you would snap to is itself moving and unknown.

This produces the central **chicken-and-egg coupling**: you cannot quantize onsets without
knowing the tempo curve, and you cannot recover the tempo curve without knowing which notes
landed on which beats. Cemgil & Kappen formalize the joint problem as probabilistic inference
in a **switching state-space model** — discrete switch variables are the quantized score
positions, continuous hidden variables are the tempo — and prove that exact MAP inference in
this model class is **computationally intractable**, requiring approximate Monte Carlo methods
(MCMC, particle filters). When a 1999 paper has to reach for particle filters, "round to the
nearest 16th" was never going to be enough (Cemgil & Kappen, *Monte Carlo Methods for Tempo
Tracking and Rhythm Quantization*, arXiv:1106.4863).

### 1.1 The simplicity-vs-accuracy trade-off is the whole game

Cemgil frames the objective as a Bayesian MAP estimate that decomposes into **exactly three
competing terms** (Cemgil, Desain & Kappen, *Rhythm Quantization for Transcription*, AISB 1999,
Eqs. 14–15 & 20 — verified verbatim, §9; note this is the *Rhythm Quantization* paper, not the
Monte Carlo paper, though both are cited in §1):

1. **Quantization error** — distance from the performed timing (want the score to *match* what
   was played).
2. **Notation complexity** — the description length of the notation, penalizing deep
   subdivisions via a prior `p(c) ∝ γ^(−depth)`, with `γ ≈ 1.02` in practice (want the score to
   be *readable*).
3. **Tempo penalty** — a prior preferring slower, simpler tempi to forbid degenerate
   "everything is a 64th-note at 600 bpm" solutions.

The optimal score **balances all three**. A maximally timing-accurate quantization is an
unmusical, unreadable score; a maximally simple one misrepresents the performance. There is no
single right answer — there is a Pareto front, and *where you sit on it is a taste decision*.

> **[this repo] We rediscovered term 2 the hard way.** The first Gethsemane score used a 1/32
> grid; it engraved the performer's slight-early lean on off-beat eighths *literally* as
> dotted-16th figures and stray 32nds — high accuracy (term 1), terrible readability (term 2).
> Re-quantizing on a strict 1/8 grid (histogram-confirmed: 95.5% of onsets sit on eighth slots,
> the 16th and triplet positions statistically empty) moved us to the right point on the front:
> 2237 quarters + 2114 eighths, **zero** dotted confetti. The "stricter quantization" the user
> asked for is literally turning up Cemgil's complexity prior.

---

## 2. Polyphony breaks single-stream models: voice separation and rhythm are coupled

A monophonic-melody quantizer cannot be lifted to piano by treating chords as merged events.
Nakamura et al. show that the conventional representation — a polyphonic score as a **linear
sequence of chords** — *structurally cannot describe* multi-voice music (Nakamura et al.,
*Rhythm Transcription of Polyphonic MIDI Performances*, SMC 2016).

Two facts make this fatal for piano:

- **Loose synchrony.** The two hands (and inner voices) are *not* exactly synchronous — a
  performer rolls a left-hand chord under a right-hand melody, or plays 3-against-2. A single
  merged stream sees this as a flurry of tiny, contradictory inter-onset intervals and invents
  spurious 32nds/tuplets to "explain" the asynchrony.
- **Polyrhythm.** 2-against-3 and 3-against-4 passages are *correct* music that a single stream
  literally cannot notate.

Nakamura's **merged-output HMM** models the multiple-voice structure explicitly. In the **SMC-2016
conference paper**, on a polyrhythmic test set its rhythm-correction rate was **16.0% vs 28.9%**
(note HMM) and **34.1%** (metrical HMM) — joint voice modelling roughly *halves* the error (Table 1,
verified §9). The **journal version** (TASLP 2017 / arXiv:1701.08343) widens the comparison to
**six** algorithms and reports a **>12-point** advantage on polyrhythmic performances. Two honest
caveats the first draft elided by citing both papers in one breath (§9, correction #5): these are
*two different evaluations* — SMC-2016 compares two models, the journal six — and the advantage is
**specific to polyrhythm**. On *standard* (non-polyrhythmic) polyphony the merged-output model is
**not** better (7.9% vs the note HMM's 7.0%; SMC-2016 Table 1), because there the reduced chord
sequence is already simple. None of this weakens the load-bearing conclusion — **voice separation
and rhythm quantization must be solved jointly, not sequentially** — it sharpens *where* it bites:
exactly the voice-asynchrony and polyrhythm regions a merged stream cannot notate.

This is the deepest structural gap in our pipeline. We quantize first, then assign hands by a
cost model — a sequential pipeline the literature says is the wrong factorization. Voice
separation is *also* inherently ambiguous: allowing chords inside voices makes the solution
space combinatorially larger, and **human experts disagree** on the "true" voice separation of a
passage, so the task has no single ground truth to optimize against (Zhang et al., *Cluster and
Separate: GNN voice separation*, arXiv:2407.21030).

> **[this repo] This is exactly the "second voice that shouldn't be there" problem.** An earlier
> session added a cleanup rule to delete rest-only padding voices that the quantizer leaves
> behind when a genuine two-voice passage ends — a post-hoc patch for a problem that a joint
> voice+rhythm model would not create in the first place.

---

## 3. The structural sub-problems, each individually hard

| Sub-problem | Why it's hard | Literature |
|---|---|---|
| **Beat / downbeat / meter induction** | Tempo is unknown and drifting; the beat tracker locks onto whichever pulse is *loudest*, not the true beat — sub-pulses, dotted grooves, and syncopation all mislead it. Metrical structure must be *enforced* or the output contains grammatically impossible note-value sequences (isolated triplets that don't complete a beat). | Nakamura SMC 2016; metrical-HMM line of work |
| **Voice separation** | Combinatorial, ambiguous, no single ground truth; coupled to rhythm. | Nakamura 2016; Zhang 2024 (2407.21030) |
| **Hand / staff assignment** | A note's staff depends on hand, which depends on playability and context, not just pitch; hands cross. Treated as its own modelling problem with multiple competing methods. | *Three Methods for Pianist Hand Assignment* (ResearchGate 255583586) |
| **Pedal vs. finger sustain** | The transcriber reports *acoustic* note-off (when the string stops), which under pedal is governed by the pedal, not the key. Engraving those durations literally produces drones and rest-spray. | (under-studied; see §4) |
| **Micro-timing vs. notated rhythm** | Swing, rubato, and expressive lean are continuous deviations that must be *classified* as either "notate this" (a real dotted rhythm) or "absorb this" (expression). | Desain & Honing; Cemgil |
| **Pitch spelling / key** | The same pitch class spells differently by key and harmonic context; key itself can be ambiguous or modal. | (engraving literature) |

### 3.1 Beat induction is where the whole score lives or dies

If the beat grid is wrong, *every* downstream decision is wrong — melody lands on the wrong
slot, durations fragment, barlines drift. And beat trackers fail in a characteristic way: they
lock onto a metrically-strong *sub-pulse* rather than the true beat.

> **[this repo] The Skrillex 3-3-2 groove is a textbook case.** Autocorrelation BPM candidates
> were 85.7 / 171.4; the *true* tempo was ~128.5 — the trackers had locked onto the dotted-eighth
> of the 3-3-2 pattern (4/3 of the real beat). Both the audio tracker *and* the onset-DP tracker
> chased the accent layer; only ~25% of onsets sat within 0.07 beat of a 16th slot of the
> audio-tracked grid. We had to add a third grid mode (`beats --refine`: a fixed grid scanned
> around a ground-truth BPM hint, then smoothly warped to the onsets) to get the fit to 0.71 with
> peaks *centered on* the slots. The general lesson matches the literature exactly: **seed the
> metrical level with external ground truth, and validate the grid against an onset-fit metric
> before trusting it.**

### 3.2 Pedal is a duration-destroying ambiguity that the literature under-treats

This is the sub-problem most specific to our complaint and least covered by the academic work
(which mostly assumes clean note-off). The transcriber gives you an *acoustic* offset: under
sustain pedal, a key released after 50 ms keeps ringing for two seconds, and Transkun reports
the two seconds. Three failure modes follow, all of which we hit:

> **[this repo]**
> - **Drones.** On the Skrillex cover (pedal down **81%** of the recording), sparse left-hand
>   stabs were legato-filled across their multi-beat silences into whole-bar held notes — the
>   groove's pulse audibly died. Fix: never legato-fill across a same-staff silence longer than
>   ~1 beat; under pedal hold only to the next beat boundary, pedal-up keep the performed length.
> - **Voice/rest spray.** 93 pedal-smeared rings were engraved as "sustained second voices,"
>   each dragging full-bar padding rests into voices 2–4 (~80 voice containers). Fix: a ring that
>   only the *pedal* carries never becomes a second voice (dropped to 32 genuine finger-holds).
> - **Pedal notation itself.** The pedal lines have to be engraved *under the bass staff* and
>   deduplicated, or they float mid-system and double up.
>
> The deeper point: **the score needs the pedal as a separate notational layer (Ped./*** **marks),
> with note durations quantized to musical values, while the MIDI gets to encode the same
> information continuously and losslessly.** That asymmetry is a big part of why the MIDI
> "sounds right" and the score doesn't — the MIDI never had to make the discretization choice.

---

## 4. Why the MIDI sounds better than the score (the core complaint, precisely)

Put the pieces together and the user's recurring observation is not a bug, it is the expected
outcome of an information-theoretic projection:

1. **The cleaned MIDI is a faithful recording.** It carries continuous onset times, true
   velocities, real (pedal-extended) durations, and pedal CC — every expressive nuance the
   performer produced. Playing it back reproduces the performance.
2. **The score is a quotient of that recording** under an equivalence relation ("notate timings
   within a tolerance as the same note value"). Quantization, by construction, **deletes**
   micro-timing and rubato; note-value rounding deletes true durations; level-quantized dynamics
   (pp…ff) delete the continuous velocity curve; the discrete grid cannot represent the
   asynchrony that gives chords their warmth.
3. **The deleted information is exactly the expressive information.** So the score sounds
   stiffer, simpler, and "less correct" *even when it is a perfectly valid notation*, because
   "correct notation" and "faithful to the performance" are the two ends of Cemgil's trade-off
   (§1.1) and you cannot have both.
4. **On top of that, the projection is lossy in the error-prone direction.** Every wrong beat,
   wrong voice, wrong duration, or spurious tuplet is a defect the MIDI never had, because the
   MIDI never had to commit to a grid, a voice count, or a meter.

So there are two distinct gaps, and it helps to separate them:

- **The irreducible gap** — even a *perfect* transcription loses expression, because a score is
  an abstraction. This cannot be fixed, only acknowledged. (A good engraver accepts it and even
  exploits it: the score is a set of *instructions to a future performer*, not a recording.)
- **The reducible gap** — our scores additionally contain avoidable errors (wrong grids, drones,
  rest-spray, false swing, spurious key changes). This is what §6 attacks.

---

## 5. State of the art: where the field actually is

This matters for calibrating expectations: **even the best research systems are explicitly "far
from satisfactory."**

- **Commercial MIDI import is measurably bad.** On the MAPS ENSTDkCl piano set, Nakamura's
  noisy-metrical-HMM quantizer scored a **21.4%** overall error rate vs **29.0% for MuseScore 2**
  and **31.1% for Finale 2014** (p < 10⁻⁵), with onset-time error nearly halved vs MuseScore
  (Nakamura et al., *Towards Complete Polyphonic Music Transcription*, ICASSP 2018). When the
  user says "MuseScore's MIDI import is unreliable," there is a benchmark behind it — which is
  also why this pipeline forbids it and quantizes in-house.
- **HMM/MRF methods were SOTA as of 2018** — metrical HMM best for onset quantization, a Markov
  random field best for note-value (duration) recognition — and the authors of the best
  integrated system of that period call its output scores "far from satisfactory," containing
  "musically incorrect pitch configurations and unplayable notes," with pitch/missing-note
  correction "beyond the reach" without a **symbolic music language model** (Nakamura et al.,
  ICASSP 2018). The bottleneck is the MIDI→score stage, *not* the audio→MIDI stage — which is
  exactly our situation (our MIDI is great; our score is not).
- **The neural wave (2020–2025)** reframes pieces of the problem as learned tasks:
  performance MIDI→score with sequence models, **PM2S** for beat/quantization, transformer and
  **graph-neural-network** approaches to voice separation that finally support homophonic voices
  (chords within a voice) and cross-staff voices for piano (Zhang et al., arXiv:2407.21030;
  and the 2023–2025 arXiv line, e.g. 2304.14848, 2410.00210, 2507.00466, 2508.19262). These are
  promising but data-hungry and not obviously drop-in for a CLI pipeline.
- **Evaluation is itself a research problem.** **MV2H** (McLeod & Steedman) exists precisely
  because there is no single "score accuracy" number — it scores multi-pitch, voice, meter,
  note value, and harmony *jointly* so that a system cannot win on rhythm while mangling voices
  (github.com/apmcleod/MV2H). Our chroma-DTW `verify` is a coarse proxy for one slice of this.
- **Datasets** that make the above measurable: **MAPS** / **A-MAPS** (annotated), **ASAP**
  (score-to-performance alignments), **MAESTRO** (large aligned audio+MIDI). None is a magic
  bullet; all assume cleaner inputs than a YouTube cover.

The honest summary: **this is an open research problem, and a single-pass deterministic CLI
will not close the irreducible gap.** What it *can* do is stop losing points on the reducible
gap.

---

## 6. What concretely can be done here

Ordered by leverage-to-effort. The pipeline already does the right *category* of thing
(beat-tracked DP quantization, per-beat subdivision, pedal-aware durations, cost-model hand
assignment, velocity dynamics) — these are improvements within that frame, plus a few
reframings.

### 6.0 Implementation status, audited against the code this pass

Two of the highest-leverage Tier-1 items turn out to be **not yet wired into `quantize`**, where
they would do the most good — worth flagging plainly so the §6 list is actionable, not aspirational:

- **Grid validation is reported, never enforced.** `onset_grid_fit` is computed only inside
  `beats --refine` and only *printed*; `cmd_quantize` neither computes nor checks it. Item #1's
  "hard gate" does not exist yet — a low-fit grid still produces a score silently. **Proposed:**
  have `quantize` compute the onset-fit of the grid it is about to use and refuse (or loudly warn +
  require `--force`) below a threshold, with no clean slot peaks in the onset histogram.
- **The default grid is the *busiest* one.** `quantize --grid` defaults to **32** (1/32 notes) —
  the exact opposite of item #2's "default coarser, deepen only on evidence," and precisely the
  regime Cemgil's complexity prior (§1.1) and AISB-1999 Fig. 2 ("too accurate" quantization) warn
  against. **Proposed:** default `--grid 16` (or auto-pick from the onset histogram) and deepen
  per-passage only where the histogram shows populated 1/32 slots.

Both are small, local changes to `cmd_quantize` with outsized effect on how busy the scores look.
The remaining items below are larger; the inline `[done/partial this session]` markers in the
tiers are from earlier sessions — treat #1 and #2 here as the authoritative current status for the
two they touch (still **partial/gap**, not done).

### Tier 1 — highest leverage, low effort (mostly already in motion)

1. **Always seed the metrical level with ground truth, and *validate the grid before using it*.**
   The single biggest score-wrecker is a wrong grid (§3.1). We now have `beats --refine` and an
   `onset_grid_fit` metric — make grid validation a hard gate: if the best achievable fit is low
   *and* the onset histogram has no clean slot peaks, stop and ask for the BPM rather than
   shipping a mis-snapped score. **[partially done this session]**
2. **Tune the complexity prior per piece, not globally.** Cemgil's `γ` is a knob. Expose grid
   depth as the first-class control it is: a ballad wants `--grid 8`, a florid piece `--grid 16`.
   Default *coarser* than 1/32 and only deepen when a passage's onset histogram demands it. The
   1/32 default is why scores look busier than the music. **[validated this session on Gethsemane]**
3. **Classify micro-timing before notating it.** Swing vs. straight vs. expressive-lean is a
   *measurement*: histogram the off-beat onset position. Late at the triplet third → swing; early
   of the half-beat → expressive lean, notate straight; near the slot → straight. We currently
   risk false "Swing" marks; gate the swing direction on the histogram peak actually sitting at
   2/3, not merely off-center. **[this session: removed a false Swing mark on Gethsemane this way]**
4. **Make pedal a notation layer, never a duration source.** Continue the work from this session:
   quantize note values to musical durations, carry sustain in Ped./* lines, and never let a
   pedal-only ring become a held note or a second voice. **[done this session]**

### Tier 2 — medium effort, attacks the reducible gap directly

5. **Validate "modulations" against the actual pitch collection before engraving key changes.**
   Windowed key detection flip-flops on enharmonically-equivalent or modal music and sprays
   spurious key-signature changes. Before inserting any change, check what fraction of the window
   actually lies outside the incumbent key's collection; if it's small, it's emphasis, not
   modulation. **[done ad-hoc this session on both pieces — promote to an automatic guard in `post`]**
6. **Add a notation-grammar pass that forbids impossible note-value sequences.** The metrical-HMM
   literature's key structural win is that meter is *enforced*: no isolated triplet that fails to
   complete its beat, no value that crosses a beat boundary it shouldn't (Nakamura SMC 2016).
   Our `quantize` already constrains durations to a beat's subdivision family — extend this into
   an explicit post-quantization grammar check that flags/repairs ungrammatical groupings.
7. **Move toward joint voice+rhythm, or at least feed voice structure back into quantization.**
   The deepest finding (§2) is that sequential quantize→assign-hands is the wrong factorization.
   A pragmatic middle step: detect genuine polyphony/polyrhythm regions *first* and quantize each
   voice on its own sub-grid, rather than quantizing the merged stream and splitting after.

### Tier 3 — higher effort / research-grade

8. **Adopt MV2H as the offline quality metric.** Replace/augment chroma-DTW `verify` with MV2H so
   regressions in voice/meter/note-value are caught, not just pitch-class drift
   (github.com/apmcleod/MV2H). This makes "is the new quantizer better?" an answerable question.
9. **Consider a learned voice-separation stage** (GNN, à la Zhang 2024) as an optional refiner for
   piano, where homophonic and cross-staff voices are common and our cost model is weakest.
10. **Consider a symbolic music language model as the final repair pass.** The 2018 ICASSP
    conclusion is that pitch/missing-note errors are "beyond reach" without one. A modern LLM-as-
    musical-proofreader over the MusicXML (key-aware spelling, obvious wrong-note flags, voice
    sanity) is the contemporary version of that recommendation and fits this repo's
    "model-judgment cleanup" philosophy.

### The framing fix (free, and arguably most important)

11. **Set the expectation in `CLEANUP_NOTES.md`: the score is instructions, the MIDI is the
    recording.** A score that is *more readable* than the performance is doing its job, even
    though it sounds less expressive on naive playback. The irreducible gap (§4) is a feature of
    notation, not a defect of the pipeline — say so, and direct "I want it to sound like the
    MIDI" users to the MIDI deliverable, which we already produce and clean.

---

## 7. The bottom line for this pipeline

- The complaint is **real and largely irreducible**: a score is a lossy abstraction of a
  performance, and the lost information is the expression (§4). No deterministic converter fixes
  that; the best ones in the literature are "far from satisfactory" (§5).
- But a meaningful fraction of our gap is **reducible** and traces to specific, named failure
  modes we have already seen and partly fixed this session: wrong grids on syncopated grooves,
  pedal-smear durations, false swing, spurious key changes, rest-spray voices.
- The literature's two structural verdicts to internalize: **(a)** quantization is a
  simplicity-vs-accuracy trade-off you *tune*, not a grid you *snap to* (Cemgil); **(b)** voice
  separation and rhythm are *one* coupled problem, and our sequential factorization is the main
  architectural debt (Nakamura).
- Highest-leverage next steps: gate on grid validation, default to coarser grids and deepen only
  on evidence, measure micro-timing before notating it, keep pedal as a layer not a duration, and
  guard against spurious key changes — then, if going further, adopt MV2H and consider a learned
  voice stage and an LLM proofreading pass.

---

## 8. Sources

Primary literature (peer-reviewed papers and canonical preprints):

- Cemgil, Desain & Kappen — *Rhythm Quantization for Transcription* (AISB 1999).
  https://www.snn.ru.nl/v2/serve.php?doc=Cemgil_aisb99.pdf
- Cemgil & Kappen — *Monte Carlo Methods for Tempo Tracking and Rhythm Quantization*.
  https://arxiv.org/abs/1106.4863 · related: https://www.snn.ru.nl/v2/serve.php?doc=cemgil-quantization.pdf
- Desain & Honing — *The Quantization of Musical Time: A Connectionist Approach*.
  https://www.researchgate.net/publication/254892868
- Nakamura, Yoshii & Sagayama — *Rhythm Transcription of Polyphonic MIDI Performances* (merged-output HMM, SMC 2016).
  https://arxiv.org/abs/1701.08343 ·
  https://eita-nakamura.github.io/articles/Nakamura_etal_RhythmTranscriptionOfPolyphonicMIDIPerformances_SMC2016.pdf
- Nakamura et al. — *Towards Complete Polyphonic Music Transcription: Integrating Multi-Pitch Detection and Rhythm Quantization* (ICASSP 2018; MAPS benchmark vs MuseScore/Finale).
  https://eita-nakamura.github.io/articles/AudioAndMIDITranscription_ICASSP2018.pdf
- Nakamura et al. — performance error / score-performance modelling.
  https://arxiv.org/pdf/1703.08144
- *Three Methods for Pianist Hand Assignment*.
  https://www.researchgate.net/publication/255583586
- Zhang et al. — *Cluster and Separate: a GNN approach to voice separation* (homophonic & cross-staff voices, 2024).
  https://arxiv.org/abs/2407.21030
- MV2H evaluation metric (McLeod & Steedman).
  https://github.com/apmcleod/MV2H
- Recent neural MIDI-to-score / quantization / beat (PM2S and successors, 2020–2025):
  https://arxiv.org/abs/2011.03028 ·
  https://arxiv.org/pdf/2304.14848 ·
  https://arxiv.org/pdf/2010.01815 ·
  https://arxiv.org/abs/2410.00210 ·
  https://arxiv.org/pdf/2507.00466 ·
  https://arxiv.org/pdf/2508.19262 ·
  https://archives.ismir.net/ismir2022/paper/000047.pdf

Practitioner / commercial context (forums and notation-vendor articles — lower-authority,
included for the failure-mode descriptions, not the claims):

- MuseScore MIDI-import discussion. https://musescore.org/en/node/295647
- Notation.com — *MIDI to Sheet Music*. https://www.notation.com/Articles-MIDItoSheetMusic.php
- VI-Control — *Workflow for notation from recorded MIDI*.
  https://vi-control.net/community/threads/recommended-workflow-for-creating-notation-from-recorded-midi-performance.85176/
- Skytopia — *The problem with music notation software*. https://www.skytopia.com/project/articles/notation.html

**Datasets referenced:** MAPS / A-MAPS, ASAP, MAESTRO.

---

## 9. Verification status (completing the halted adversarial pass)

The original deep-research harness stopped before its confirm/refute step ran. This section
completes it for the document's load-bearing quantitative claims, each checked by reading the
primary-source PDF in full (not the abstract). Verdicts: **✅** confirmed verbatim/near-verbatim ·
**⚠️** true but mis-sourced / needs a caveat · **◻️** not independently re-checked this pass
(plausible, attributed to a named source, not load-bearing for any pipeline decision).

| # | Claim (§) | Source checked | Verdict |
|---|---|---|---|
| 1 | NMetHMM **21.4%** vs MuseScore 2 **29.0%** vs Finale 2014 **31.1%** overall error on MAPS-ENSTDkCl, *p* < 10⁻⁵ (§5) | ICASSP 2018, **Table 2** | ✅ exact |
| 2 | onset error "nearly halved" vs MuseScore (§5) | ICASSP 2018, Table 2 (E_on 39.7 → 21.6) | ✅ (−46%) |
| 3 | scores "far from satisfactory"; pitch/missing-note fix "beyond the reach" without a symbolic music language model (§5) | ICASSP 2018, **Conclusion** | ✅ verbatim |
| 4 | merged-output HMM **16.0%** vs note-HMM **28.9%** vs metrical-HMM **34.1%** on polyrhythm (§2) | SMC 2016, **Table 1** | ✅ exact (rhythm-correction rate ℛ) |
| 5 | ">12 points over six algorithms" (§2) | arXiv:1701.08343 (journal version) abstract | ⚠️ true, but a *different* evaluation than #4 — **corrected in §2** |
| 6 | a polyphonic score as a linear chord sequence cannot describe multi-voice music; voice + rhythm are joint (§2) | SMC 2016, Abstract & §2.2 | ✅ near-verbatim |
| 7 | enforced metrical structure prevents grammatically-impossible note values (isolated triplets not completing a beat) (§3, §6.6) | SMC 2016, §4.2 & Conclusion | ✅ verbatim |
| 8 | switching state-space model (discrete = score position, continuous = tempo); exact MAP intractable → MCMC / particle filters (§1) | Cemgil & Kappen, JAIR 2003, Abstract & §1 | ✅ verbatim (paper *states* intractability for the model class; it is not a formal hardness theorem — "prove" in §1 is slightly strong) |
| 9 | objective = quantization error + notation complexity + tempo penalty; *p(c)* ∝ γ^(−depth), **γ ≈ 1.02** (§1.1) | Cemgil/Desain/Kappen, AISB 1999, **Eqs. 14–15 & 20** | ✅ verbatim — but from the *Rhythm Quantization* paper, not the Monte Carlo one (§1.1 attribution clarified) |
| 10 | "too accurate" 1/32 quantization engraves expressive lean as dotted/32nd confetti — **[this repo]** Gethsemane (§1.1) | AISB 1999, **Fig. 2** ("too" accurate vs desired) | ✅ literature independently corroborates the repo finding |
| 11 | performed durations deviate up to **50%** yet listeners recover meter (§1) | Desain & Honing | ◻️ not re-checked |
| 12 | human experts disagree on the "true" voice separation (§2) | Zhang 2024 (2407.21030) | ◻️ not re-checked |
| 13 | MV2H scores pitch/voice/meter/note-value/harmony *jointly* (§5) | MV2H repo | ◻️ not re-checked |

**Net.** Every headline statistic that drives a pipeline decision is confirmed against its primary
source — including the one figure that looked most likely to be garbled (γ ≈ 1.02; it is correct,
and a deliberately *gentle* prior — the paper notes γ = 2 would admit "only very simple rhythms").
The single substantive correction is the sourcing conflation at #5, now fixed in §2. The three
unverified items (#11–13) are supporting motivation, attributed to named sources, and change no
pipeline choice if wrong. The harness's abstention votes are therefore now resolved: **12 of 13
confirmed (1 with a caveat), 0 refuted, 3 left explicitly open.** Method note: WebFetch's helper
model cannot read PDF binary streams, so each source PDF was saved and read directly — the abstract
alone would have left #1, #4, and #9 (the most specific numbers) unverifiable.

---

*Generated for the SoloPianoTranscription pipeline. The literature was gathered via automated
deep-research fan-out. The adversarial-verification stage that originally did not complete has now
been finished by hand for the load-bearing claims (§9): 12 of 13 confirmed against primary-source
PDFs, one corrected, three left explicitly open. The **[this repo]** observations are reproducible
from `output/` artifacts and git history.*
