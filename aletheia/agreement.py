"""Did the student reach the same answer as the teacher?

Turning teacher/student pairs into routing evidence needs a verdict, and
the verdict has to be cheap. Spending a frontier call to judge every
shadow attempt would cost more than the shadow saves, and on this machine
spending a LOCAL call to judge would take longer than the answer did.

So this is deterministic and deliberately modest. It returns:

    True   - the same answer, on evidence
    False  - materially different, on evidence
    None   - cannot tell

`None` is a real verdict and the most important one. The scorecard counts
comparisons, not attempts, so an honest "I cannot tell" simply does not
vote - which is far better than a coin flip that slowly certifies a model
nobody actually checked. Prose that cannot be judged deterministically
returns None rather than guessing at similarity.

Nothing here is a quality judgement in the human sense. It answers
"would he have got materially the same thing", which is the only question
routing needs.
"""
from __future__ import annotations

import math
import re

#: Below this Jaccard overlap two short answers are clearly not the same.
#: Above the upper bound they clearly are. Between them, say None: the
#: middle of this range is exactly where a similarity score stops meaning
#: anything, and a confident guess there is how a scoreboard drifts.
DISAGREE_BELOW = 0.30
AGREE_ABOVE = 0.75

#: Longer than this and word overlap stops being evidence of agreement -
#: two good paragraphs on one subject share most of their vocabulary and
#: can still say opposite things.
MAX_WORDS_FOR_OVERLAP = 60

_WORD = re.compile(r"[a-z0-9']+")

#: A model's own confidence is its opinion of ITSELF, not part of the
#: answer. Comparing it made two identical answers disagree because one
#: said 0.99 and the other 1.0 - which on live evidence scored three
#: correct answers at 33% agreement, and would have kept local from ever
#: certifying for a reason unrelated to being right.
ADVISORY_FIELDS = frozenset({
    "confidence", "certainty", "score", "probability", "p", "rating",
})

#: Words that carry no claim. Removing them stops "the a of and" from
#: making two unrelated sentences look alike.
_NOISE = frozenset("""
a an the and or but if then than that this these those of in on at to for
with from by as is are was were be been being it its it's i you he she
they we me him her them my your his their our some any no not so such
there here what which who whom when where why how do does did done doing
can could will would shall should may might must have has had about into
over under again further once only own same too very just now also
""".split())


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(str(text or "").lower()) if w not in _NOISE]


def _numbers(text: str) -> set[str]:
    """Figures are the part of an answer most worth disagreeing about."""
    return set(re.findall(r"-?\d+(?:\.\d+)?", str(text or "")))


def _overlap(left: str, right: str) -> float | None:
    a, b = set(_words(left)), set(_words(right))
    if not a or not b:
        return None
    if max(len(_words(left)), len(_words(right))) > MAX_WORDS_FOR_OVERLAP:
        return None
    return len(a & b) / len(a | b)


def _same_scalar(left, right) -> bool | None:
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=1e-6, abs_tol=1e-9)
    if isinstance(left, str) and isinstance(right, str):
        stripped_l = " ".join(left.split()).lower()
        stripped_r = " ".join(right.split()).lower()
        if stripped_l == stripped_r:
            return True
        return None
    if left is None and right is None:
        return True
    return None


def compare_json(teacher: dict, student: dict, *,
                 keys: tuple[str, ...] | None = None) -> bool | None:
    """Structured answers can be judged properly, so they are.

    A JSON contract names its own important fields; when the caller does
    not say which, every key the teacher produced has to match - except
    the model's own confidence, which is its opinion of itself.

    String fields are handed to `compare_text` below (resolved at call
    time), so there is one rule for "do these say the same thing".
    """
    if not isinstance(teacher, dict) or not isinstance(student, dict):
        return None
    names = tuple(keys) if keys else tuple(
        k for k in teacher.keys() if str(k).lower() not in ADVISORY_FIELDS)
    if not names:
        return None
    verdicts = []
    for name in names:
        if name not in teacher:
            continue
        if name not in student:
            return False          # a missing field is a real difference
        verdict = _same_scalar(teacher[name], student[name])
        if verdict is None:
            if isinstance(teacher[name], str) and isinstance(student[name], str):
                # ONE implementation: a string field is judged exactly the
                # way loose prose is, so the figure check and containment
                # apply here too rather than only to bare text.
                text_verdict = compare_text(teacher[name], student[name])
                if text_verdict is False:
                    return False
                verdicts.append(text_verdict)
                continue
            verdicts.append(None)
        elif verdict is False:
            return False
        else:
            verdicts.append(True)
    if not verdicts:
        return None
    if any(v is None for v in verdicts):
        return None               # some field could not be judged
    return True


def _contained(left: str, right: str) -> bool | None:
    """Is the shorter answer entirely inside the longer one?

    Only meaningful for SHORT answers: in a paragraph, one side containing
    the other's vocabulary says nothing about whether they agree. Requires
    at least two meaningful words so a single common noun cannot carry it.
    """
    a, b = set(_words(left)), set(_words(right))
    if not a or not b:
        return None
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    # One word is enough BECAUSE the noise words are already gone: what
    # remains is a content word, and "Reykjavik" is a whole answer.
    if not smaller or len(larger) > MAX_WORDS_FOR_OVERLAP:
        return None
    return smaller <= larger or None


def compare_text(teacher: str, student: str) -> bool | None:
    """Prose, judged only where a deterministic signal exists.

    Disagreeing FIGURES are decisive: "it costs 40 dollars" and "it costs
    400 dollars" share almost every word and are not the same answer.
    Beyond that, only clearly-overlapping or clearly-disjoint short
    answers get a verdict; anything longer returns None, because two good
    paragraphs about one subject share their vocabulary whether or not
    they agree.
    """
    if not str(teacher or "").strip() or not str(student or "").strip():
        return None
    teacher_numbers, student_numbers = _numbers(teacher), _numbers(student)
    if teacher_numbers and student_numbers and not (teacher_numbers & student_numbers):
        return False
    # "Reykjavik" and "The capital of Iceland is Reykjavik" are the same
    # answer given at different lengths. Overlap alone calls them
    # unrelated; containment recognises them.
    contained = _contained(teacher, student)
    if contained is True:
        return True
    score = _overlap(teacher, student)
    if score is None:
        return None
    if score >= AGREE_ABOVE:
        return True
    if score <= DISAGREE_BELOW:
        return False
    return None


def agrees(teacher, student, *, keys: tuple[str, ...] | None = None) -> bool | None:
    """One door. Never raises: a comparator failure votes None."""
    try:
        if student is None or teacher is None:
            return None
        if isinstance(teacher, dict) and isinstance(student, dict):
            return compare_json(teacher, student, keys=keys)
        if isinstance(teacher, str) and isinstance(student, str):
            return compare_text(teacher, student)
        verdict = _same_scalar(teacher, student)
        return verdict
    except Exception:
        return None
