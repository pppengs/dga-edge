# Standards, table provenance and known divergences

Every threshold in this project is traceable. This file records where each table
came from and, where the literature disagrees, which reading was adopted and why.

A DGA tool whose tables cannot be traced is not reproducible. Nothing in
`dga_core/tables.py` was written from memory.

---

## 1. Summary

| Table | File | Primary basis | Transcribed from |
|---|---|---|---|
| IEC 60599 ratio method (direct band form) | `tables.py` | IEC 60599:2015 | MIT reference implementation (below) |
| IEC three-ratio **coded** method | `tables.py` | IEC 60599 | Two agreeing independent academic sources |
| Rogers ratio | `tables.py` | IEEE C57.104-2019 | MIT reference implementation |
| Doernenburg | `tables.py` | IEEE C57.104-2019 | MIT reference implementation |
| Duval Triangle 1 zones | `tables.py` | Duval (2002 revision) | MIT reference implementation |
| Condition grading (Table 1) | `tables.py` | IEEE C57.104-2019 | Two agreeing independent transcriptions |
| Successive-sample change (Table 3) | `tables.py` | IEEE C57.104-2019 | Two agreeing independent transcriptions |
| Rate of gas increase (Table 4) | `tables.py` | IEEE C57.104-2019 | One transcription of the standard's table |
| Sampling interval (Table 5) | `tables.py` | IEEE C57.104-2019 | One secondary source — guidance only |

### MIT reference implementation

`ToniMellin/dga-diagtool` — <https://github.com/ToniMellin/dga-diagtool> —
MIT licence, Copyright (c) 2022–2026 Toni Mellin. See `NOTICE` at the repository
root for the attribution required by that licence.

Files consulted:

- `diagnostic/diagnostic_calculation.py`
  - `iec_ratio_calculation()` → IEC 60599 (2015), direct band form
  - `rogers_ratio_calculation()` → IEEE C57.104-2019
  - `doernenburg_ratio_calculation()` → IEEE C57.104-2019
- `diagnostic/duval_triangle_1.py`
  - `TRIANGLE1_{PD,T1,T2,T3,DT,D1,D2}_{A,B,C}` → Duval Triangle 1 zone polygons

---

## 2. Duval Triangle 1

Ternary convention: **A = CH₄ (%)**, **B = C₂H₂ (%)**, **C = C₂H₄ (%)**, A + B + C = 100.

Implementation: ternary → Cartesian (A → (0,0), C → (1,0), B → (0.5, √3/2)),
then a ray-casting point-in-polygon test.

Zones and their vertex counts:

| Zone | Meaning | Vertices |
|---|---|---|
| PD | partial discharge | 4 |
| T1 | thermal fault, low range | 6 |
| T2 | thermal fault, medium range | 5 |
| T3 | thermal fault, high range | 5 |
| DT | mixed thermal/electrical | 9 |
| D1 | discharge, low energy | 5 |
| D2 | discharge, high energy | 6 |

**Zone test order matters.** `DT` overlaps the boundaries of `D1`, `D2` and the
thermal zones in the reference vertex data, so it is tested **last**; testing it
first would steal points from the other zones. Order is
`PD → T1 → T2 → T3 → D1 → D2 → DT`.

**Vertex handling.** A point landing exactly on a polygon vertex is classified
as inside. This is not theoretical: a sample with C₂H₂ = 0 and C₂H₄ = 0
normalises to exactly the CH₄ apex, and a strict half-open ray cast reports it
as outside. See `_VERTEX_EPS` in `methods.py`.

**No Normal zone.** Duval Triangle cannot report a healthy transformer. Every
input is forced into a fault zone. This is why the Cliango dataset (which
contains 34 Normal samples) scores so much worse for Duval than alan456 (which
contains none) — see `experiments/results/REPORT.md`.

---

## 3. IEC three-ratio coded method (三比值法)

Ratios: **l = C₂H₂/C₂H₄**, **i = CH₄/H₂**, **k = C₂H₄/C₂H₆**.

### 3.1 Coding table

| Ratio range | l = C₂H₂/C₂H₄ | i = CH₄/H₂ | k = C₂H₄/C₂H₆ |
|---|---|---|---|
| < 0.1 | 0 | **1** | 0 |
| 0.1 – 1 | 1 | 0 | 0 |
| 1 – 3 | 1 | 2 | 1 |
| ≥ 3 | 2 | 2 | 2 |

Note the **inverted** first code for `i = CH₄/H₂`: below 0.1 it codes 1, not 0.

### 3.2 Fault lookup table

| l | i | k | Fault | Description |
|---|---|---|---|---|
| 0 | 0 | 0 | Normal | normal ageing |
| 0 | 1 | 0 | PD | partial discharge, low energy density |
| 1 | 1 | 0 | PD | partial discharge, high energy density / corona |
| 1 | 0 | 1 | D1 | discharge of low energy, continuous sparking |
| 1 | 0 | 2 | D2 | discharge of high energy, arcing |
| 0 | 0 | 1 | T1 | thermal fault < 150 °C |
| 0 | 2 | 0 | T1 | thermal fault 150–300 °C |
| 0 | 2 | 1 | T2 | thermal fault 300–700 °C |
| 0 | 2 | 2 | T3 | thermal fault > 700 °C |

### 3.3 Sources

Two independent sources were used and they agree entry-by-entry:

- **[S1]** Lu & Chen, *Advanced Winding Models and Ontology-Based Fault
  Diagnosis*, University of Liverpool, 2014, Table 1.3.
  <https://livrepository.liverpool.ac.uk/19593/4/LuChe_July2014_19593.pdf>
- **[S2]** SSRG International Journal of Electrical and Electronics Engineering,
  Vol. 2 Issue 4, April 2015, Table 2 and Table 3.
  <https://www.internationaljournalssrg.org/IJEEE/2015/Volume2-Issue4/IJEEE-V2I4P101.pdf>

### 3.4 Known divergences (deliberately not resolved by guessing)

1. **D1/D2 code swap.** At least one secondary source lists (1,0,1) as
   *high-energy* and (1,0,2) as *low-energy*, i.e. the reverse of [S1] and [S2].
   We follow the two agreeing sources, which are also physically consistent: a
   higher C₂H₄/C₂H₆ ratio indicates a higher-energy fault.

2. **Uncovered code triples.** Some sources generalise "discharge of low energy"
   to `l ∈ {1,2}` and `k ∈ {1,2}`, which collides with the D2 entry at (1,0,2).
   Rather than invent a resolution, codes **(2,0,1)** and **(2,0,2)** return
   `ND` (no decision). This depresses the reported decision rate for the coded
   method, and that is the honest outcome.

3. **Third-ratio variant.** Older Chinese editions of GB/T 7252 use
   C₂H₂/C₂H₆ as the third ratio instead of C₂H₄/C₂H₆. That variant is **not**
   implemented.

4. **Edition drift.** IEC 60599 has been revised repeatedly (1999, 2015, 2022);
   the 2022 edition updated typical gas concentrations, ratio limits and the
   fault identification tables. This implementation covers the 2015-era tables
   as carried by the sources above. Verifying against the IEC 60599:2022 text
   itself is an outstanding task — see *Open items*.

---

## 4. IEC 60599 direct band form (`iec_ratio`)

A second, distinct IEC implementation is provided. It uses continuous ratio
bands rather than 0/1/2 codes:

| Fault | C₂H₂/C₂H₄ | CH₄/H₂ | C₂H₄/C₂H₆ |
|---|---|---|---|
| PD | — | < 0.1 | < 0.2 |
| D1 | > 1 | 0.1 – 0.5 | > 1 |
| D2 | 0.6 – 2.5 | 0.1 – 1 | > 2 |
| T1 | — | > 1 | < 1 |
| T2 | < 0.1 | > 1 | 1 – 4 |
| T3 | < 0.2 | > 1 | > 4 |

Both variants are reported side by side in the validation results because they
behave differently (the coded form decides on more samples, the band form is
more accurate when it does decide).

---

## 5. Rogers ratio (IEEE C57.104-2019)

Uses r₁ = CH₄/H₂, r₂ = C₂H₂/C₂H₄, r₅ = C₂H₄/C₂H₆, producing
Normal / PD / D1 / D2 / T1 / T2 / T3 or ND.

Note this is the **1991 revision as standardised in IEEE C57.104**, not the
original 1978 Rogers four-ratio method with twelve diagnoses. The older form has
even wider divergence between reprints; it is intentionally out of scope.

---

## 6. Doernenburg (IEEE C57.104-2019)

Four ratios r₁ = CH₄/H₂, r₂ = C₂H₂/C₂H₄, r₃ = C₂H₂/CH₄, r₄ = C₂H₆/C₂H₂, with
pre-conditions on absolute gas levels. **Requires CO**, which most public
datasets do not carry, so this method is excluded from `DEFAULT_METHODS`.

---

## 7. IEEE C57.104-2019 condition monitoring

This is the *condition monitoring* half of the system (`dga_core/condition.py`),
as opposed to the fault-identification methods above. It answers "is anything
wrong, and how urgent is it?" rather than "which fault is it?".

### 7.1 Table 1 — condition limits (ppm)

| Gas | Condition 1 (≤) | Condition 2 | Condition 3 | Condition 4 (>) |
|---|---|---|---|---|
| H₂ | 100 | 101 – 700 | 701 – 1800 | 1800 |
| CH₄ | 120 | 121 – 400 | 401 – 1000 | 1000 |
| C₂H₂ | 1 | 2 – 9 | 10 – 35 | 35 |
| C₂H₄ | 50 | 51 – 100 | 101 – 200 | 200 |
| C₂H₆ | 65 | 66 – 100 | 101 – 150 | 150 |
| CO | 350 | 351 – 570 | 571 – 1400 | 1400 |
| CO₂ | 2500 | 2501 – 4000 | 4001 – 10000 | 10000 |
| **TDCG** | 720 | 721 – 1920 | 1921 – 4630 | 4630 |

TDCG = H₂ + CH₄ + C₂H₆ + C₂H₄ + C₂H₂ + CO. **CO₂ is excluded** — it is not a
combustible gas.

**Sources.** Two independent transcriptions of Table 1 agree digit-for-digit:

- **[S3]** *Transformer Health Assessment*, Krueger (slide deck reproducing the
  IEEE Std C57.104 Table 1, including the per-condition sampling-interval table).
- **[S4]** A vendor DGA reference page independently reproducing the same
  Condition 1–4 table including the TDCG row.

### 7.2 Two findings worth recording

**(a) The TDCG row is not the column sum of the per-gas rows, and it never
binds.** The Condition-1 per-gas limits sum to **686 ppm**, but the Condition-1
TDCG limit is **720 ppm**. The same gap holds at every level:

| Level | Σ per-gas limit | TDCG limit |
|---|---|---|
| 1 | 686 | 720 |
| 2 | 1879 | 1920 |
| 3 | 4585 | 4630 |

Because Σ(per-gas C*k*) < TDCG C*k* for every *k*, **a sample whose worst
per-gas condition is k always has TDCG below the C*k* TDCG limit**. TDCG
therefore can never raise a sample's condition under Table 1 — the per-gas
limits are always stricter. This is asserted as a property test over 2000
random non-negative gas vectors
(`tests/test_condition.py::test_tdcg_never_raises_the_condition`) and is the
reason `limiting_gas` is never reported as `"TDCG"` in practice.

This does not make TDCG useless — it is a convenient single-number roll-up, and
the standard specifies it — but it must not be presented as an independent
escalation path.

**(b) Acetylene is by far the strictest channel.** C₂H₂ is Condition 2 at just
2 ppm and Condition 4 above 35 ppm, roughly two orders of magnitude below the
hydrogen thresholds. Any condition grading of in-service units is therefore
dominated by C₂H₂.

### 7.3 Tables 3 and 4 — change and rate

Table 3 is the maximum absolute change between two successive lab samples
(95th percentile), given separately for O₂/N₂ ≤ 0.2 and > 0.2. Table 4 is the
95th-percentile rate of increase in ppm/year over a 3–6 point series whose gas
levels are all below the Table 1 values, with columns for a 4–9 month and a
10–24 month span.

For C₂H₂ the standard specifies **"any increase"** rather than a numeric bound.
`dga_core` encodes this as the sentinel `IEEE_C57_104_ANY_INCREASE = -1.0` and
treats any strictly positive delta as significant.

`assess_rate()` uses a default of the **low-O₂/N₂ column** when the ratio is
unknown, which is the conservative choice for a sealed unit.

### 7.4 Deliberate design choice: rate escalates by at most one level

`monitor()` raises the condition by **exactly one** level when the rate of
change is significant, and never past Condition 4. The standard's position is
that an abnormal rate of change overrides absolute values; it is not a licence
to jump from Condition 1 to Condition 4 on a single rising interval. A rising
trend is a reason to sample sooner, not a reason to declare an emergency.
This is covered by
`tests/test_condition.py::test_rate_escalates_by_exactly_one_level` and
`::test_escalation_is_capped_at_condition_4`.

### 7.5 Not implemented: the 90th-percentile "typical concentration" tables

IEEE C57.104-2019 also carries typical-concentration tables (90th / 95th
percentile, conditioned on O₂/N₂ ratio and transformer age). Secondary sources
transcribing those tables **do not agree** on the values, so none of them were
implemented. Implementing them from a primary copy of the standard would be a
worthwhile addition — see *Open items*.

---

## 8. Open items

- [ ] Verify the coded IEC table against the IEC 60599:2022 text itself, and
      record whether 2022 changed any boundary.
- [ ] Confirm the (2,0,1) / (2,0,2) resolution against a primary source.
- [ ] Add the Duval Triangle 4 and 5 variants (different gas sets, aimed at
      non-mineral oils).
- [ ] Decide whether to implement the C₂H₂/C₂H₆ variant used by some Chinese
      regional standards.
- [ ] Add per-method uncertainty reporting (measurement error propagation into
      ratio bands), which IEC 60599 Annex discusses and which no open-source
      tool currently implements.
- [ ] Transcribe the IEEE C57.104-2019 Table 2 / Table 4 typical-concentration
      tables from a primary copy of the standard. Secondary transcriptions
      disagree, so they are deliberately absent — see §7.5.
- [ ] Verify Table 1, Table 3 and Table 4 against the IEEE C57.104-2019 text
      itself rather than against secondary transcriptions.
- [ ] Corroborate the per-condition sampling intervals (§7.1, currently from a
      single secondary source) against the standard.
