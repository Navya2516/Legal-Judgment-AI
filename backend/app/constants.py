"""Fixed text shown to users. Kept in one place so the API and UI always agree."""

DISCLAIMER_TEXT = (
    "This system provides educational explanations of court judgments to help "
    "you understand them. It is not legal advice and does not create a "
    "lawyer-client relationship. Automated summaries and translations can contain "
    "mistakes, so always check important details against the original judgment. "
    "Laws, procedures and filing deadlines change, so please verify current law "
    "and time limits independently and consult a qualified advocate before "
    "taking any legal step."
)

TRANSLATION_NOTICE_TEXT = (
    "This is an automatic machine translation of the English explanation. Machine "
    "translation can contain mistakes, especially for legal terms. The quoted "
    "evidence stays in the original English so you can check it against the "
    "judgment. For anything important, read the original judgment or ask a "
    "qualified advocate."
)

# Headings and small labels the screen needs. They are translated together with
# the summary so the frontend can show a fully localised page.
LABELS_EN = {
    "plain_summary": "Plain summary",
    "facts": "Facts",
    "issues": "Issues",
    "holding": "Holding (what the court decided)",
    "reasoning": "Reasoning",
    "final_order": "Final order",
    "provisions": "Legal provisions",
    "pages": "Pages",
    "original_quote": "Original words from the judgment (English)",
}


# ---- Phase 7: case continuation ("what happens next") ----

CONTINUATION_AVENUES_INTRO = (
    "The routes below are general information about how Indian courts commonly work. "
    "They do not come from this judgment."
)

CONTINUATION_AVENUES_NOTICE = (
    "This is general information, not advice about what you should do. Whether a route is "
    "open in a particular case, and the time limit for it, depend on the type of case and "
    "on the law as it stands today. Time limits are strict, are usually short, and are counted "
    "from the date of the judgment. Speak to a qualified advocate promptly."
)

LABELS_CONTINUATION_EN = {
    "continuation": "What happens next",
    "court_level": "Court that gave this judgment",
    "disposition": "How the court disposed of the case",
    "directions": "What the court ordered",
    "deadlines": "Time limits and dates stated in the judgment",
    "further_proceedings": "What happens next in this case",
    "avenues": "General information: routes people commonly consider after a judgment",
    "pages": "Pages",
    "original_quote": "Original words from the judgment (English)",
    "court.supreme_court": "Supreme Court",
    "court.high_court": "High Court",
    "court.trial_court": "Trial or district-level court",
    "court.tribunal": "Tribunal or commission",
    "court.unknown": "Not identified",
    "outcome.allowed": "Allowed",
    "outcome.partly_allowed": "Partly allowed",
    "outcome.dismissed": "Dismissed",
    "outcome.disposed_of": "Disposed of",
    "outcome.remanded": "Sent back to a lower court",
    "outcome.reference_answered": "Reference answered",
    "outcome.other": "Other",
}
