# Plain language and readability

Use short sentences, familiar words and direct verbs. Keep citations, margins
of error, reliability wording and program eligibility caveats. A low reading
grade cannot prove that a claim is clear or correct.

## Scoring contract (WO141 step 1 / WO185)

`scripts.readability.score(text, citation_spans=())` accepts plain text and
returns word, sentence and syllable counts plus an unrounded Flesch–Kincaid
grade: `0.39 * words / sentences + 11.8 * syllables / words - 15.59`.
Negative grades are retained. No threshold or collection gate is added here.

- Words are runs of Latin letters (English plus Hawaiian vowels with kahakō).
  Internal ʻokina and straight or curly apostrophes stay within a word.
  Hyphens separate words. Other symbols are separators.
- Numeric runs, including decimals and comma-separated digits, count as one
  word and one syllable; a percent sign adds nothing. Signs and currency
  symbols add nothing. This is a stable proxy, not spoken-number expansion.
- `{identifier}` and `{{ identifier }}` each count as one monosyllabic word.
  Identifiers start with an ASCII letter or underscore, followed by ASCII
  letters, digits or underscores. Other braces and brackets do not exempt prose.
- A run of `.`, `!`, `?` or a newline ends a sentence only if scored words
  precede it. A final fragment counts as a sentence. Blank lines and repeated
  punctuation add no sentences. Colons and semicolons do not end sentences.
  Decimal punctuation inside numeric tokens is not a boundary. Abbreviations
  receive no special treatment, so pass citations as spans rather than prose.
- Syllables use lowercase vowel groups `[aeiouy]+`, after removing apostrophes
  and folding kahakō vowels to plain vowels. Subtract one for terminal silent
  `e`, except consonant + `le`; subtract one for `ed`, except `ted`/`ded`;
  subtract one for `es`, except after `s`, `x`, `z`, `ch`, `sh`, or consonant +
  `l`. Clamp each token to at least one. This small heuristic is reproducible,
  not a pronunciation dictionary; irregular English words can be miscounted.
- Exclude exactly these case-sensitive, whole-word names from both words and
  syllables: Hawaiʻi, Kauaʻi, Lānaʻi, Molokaʻi, Oʻahu, Kahoʻolawe, Niʻihau.
  Normalize to Unicode NFC first. Variants without diacritics, lowercase names,
  longer words, Maui and other Hawaiian words receive no special exemption.
  An excluded-name-only fragment adds no sentence.
- Citation spans are explicit `[start, end)` Python character offsets into the
  original text, before normalization (not UTF-8 byte offsets). They must be
  nonempty, in bounds, sorted and disjoint; adjacency is allowed. Invalid spans
  raise `ValueError`. Replace spans with a space, so surrounding words cannot
  merge. Only declared spans are excluded; never infer citations from brackets,
  table IDs, URLs or source-like wording. Callers must identify citation-only
  text and must not exempt explanatory prose or caveats.
- Zero scored words returns zero sentences, zero syllables and `grade=None`.
  This includes blank, punctuation-only and fully excluded text. Consumers
  must treat this as unscorable, never as a passing grade of zero.

Recorded-answer interchange for the later collector: agent-eval work will
author JSONL, one object per answer, with `id` (a nonempty, unique stable string),
`kind` (`"answer"`), `text` (the original plain-text answer), and
`citation_spans` (a list of two-integer `[start, end]` pairs using the offsets
above; use `[]` when no citations occur). This step creates no answer file or
collector. Keep the original text unchanged when recording offsets.

## Editing glossary

| Term | Prefer in reader-facing prose |
|---|---|
| apportioned | estimated from ZIP codes **only when** ZIP-based data were allocated to a district; otherwise describe the actual allocation method |
| estimate | survey's best count or amount |
| margin of error | how far the survey count or amount may vary; keep the published margin and confidence level |
| coefficient of variation | how large the survey error is compared with the estimate; keep the defined reliability flag |
| vintage | years covered by the data |
| geography | area covered by the data |
| derived | calculated from published figures; name the calculation |
| eligibility | rules the agency uses to decide who can get help |

Direct district ACS tables are not estimated from ZIP codes. Do not describe
them as apportioned. Glossary suggestions do not replace required citations,
methods, uncertainty wording or the statement that the agency decides eligibility.
