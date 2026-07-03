"""
Risk score computation.

Two independent risk dimensions are computed:

  * Per-image risk (``compute_risk_scores``) scores each individual
    image placement from findings that are tied to a specific image
    (cropping, off-page, overlap, soft masks, DPI anomalies, ...).

  * Document risk (``compute_document_risk``) scores the *document*
    and its *pages* from findings that are not tied to any single
    image (text overlays, font anomalies) plus the presence of
    reviewer comments. These signals are properties of a page or the
    document as a whole, so they cannot be attributed to one image and
    are scored separately rather than being folded into image scores.

Each finding type contributes to exactly one of the two dimensions, so
nothing is double-counted and nothing is silently dropped.
"""

# Per-finding contribution to an image's risk score.
# Scores accumulate (capped at 100).
#
# Note: document/page-level finding types (TEXT_OVERLAY, FONT_ANOMALY)
# are deliberately NOT in this table. They are not tied to a single
# image, so they are scored by compute_document_risk instead.
RISK_WEIGHTS = {
    "BBOX_CROP":            30,
    "EXPLICIT_CLIP":        30,
    "OFFPAGE":              25,
    "DPI_ANOMALY":          20,
    "OVERLAP_BACK_FULL":    35,
    "OVERLAP_BACK_PARTIAL": 15,
    "OVERLAP_FRONT_FULL":   20,
    "OVERLAP_FRONT_PARTIAL": 8,
    "SOFT_MASK":             5,
    "IMAGE_SMASK":           5,
    "COMPLEX_TRANSFORM":     5,
}

# Per-finding contribution to a page's (and thus the document's) risk
# score. These are document/page-level signals that are not attributable
# to any single image. Scores accumulate per page (capped at 100).
DOC_RISK_WEIGHTS = {
    # page-level (carried in the per-page findings)
    "TEXT_OVERLAY":     35,  # overlaid text/annotation — strong alteration signal
    "FONT_ANOMALY":     15,  # out-of-place font — corroborating, higher FP rate
    "REDACT_UNAPPLIED": 35,  # marked-for-redaction content still recoverable
    # document-level (produced by analysis/doc_checks.py, not tied to a page)
    "SIGNED_THEN_MODIFIED":  35,  # bytes appended after the last signature
    "METADATA_DATE_ANOMALY": 25,  # ModDate precedes CreationDate
    "METADATA_MISMATCH":     15,  # Info dict vs XMP disagreement (per field)
    "MIXED_CAMERA":          15,  # images from 2+ distinct capture devices
    "VERSION_MISMATCH":       5,  # header vs Catalog version differ
    "XMP_ID_ANOMALY":         5,  # DocumentID == InstanceID
    "STRUCTURAL_WARNING":     5,  # qpdf structural warnings present
}

# The presence of any reviewer comments / markup annotations adds a small
# flat amount to the document score. This is informational: comments are
# not themselves evidence of manipulation, but they are worth surfacing.
COMMENT_RISK_WEIGHT = 5

RISK_SCORE_CAP = 100


def compute_risk_scores(findings, label_to_info):
    """
    Compute per-image risk scores from the findings list.

    Returns: {label: int_score_0_to_100}

    Scoring rules:
      - BBOX_CROP / EXPLICIT_CLIP applied to an image: +30 each
      - OFFPAGE: +25
      - OVERLAP where this image is the back image:
          FULL concealment    +35
          PARTIAL concealment +15
      - OVERLAP where this image is the front image:
          FULL concealment    +20 (it actively hides another image)
          PARTIAL concealment +8
      - SOFT_MASK / IMAGE_SMASK: +5 each
      - COMPLEX_TRANSFORM: +5 each
    """
    scores = {label: 0 for label in label_to_info}

    for f in findings:
        ftype = f["type"]
        image_field = f.get("image") or ""

        if ftype == "OVERLAP" and "_overlap" in f:
            ol = f["_overlap"]
            front = ol["front_label"]
            back = ol["back_label"]
            concealment = ol.get("concealment", "")

            if concealment.startswith("FULL"):
                scores[back] = scores.get(back, 0) \
                    + RISK_WEIGHTS["OVERLAP_BACK_FULL"]
                scores[front] = scores.get(front, 0) \
                    + RISK_WEIGHTS["OVERLAP_FRONT_FULL"]
            elif concealment.startswith("PARTIAL") \
                    or concealment.startswith("VARIABLE"):
                scores[back] = scores.get(back, 0) \
                    + RISK_WEIGHTS["OVERLAP_BACK_PARTIAL"]
                scores[front] = scores.get(front, 0) \
                    + RISK_WEIGHTS["OVERLAP_FRONT_PARTIAL"]
            continue

        # All other finding types are scored against the labels in
        # the image field. The field may contain a single label, a
        # comma-separated list (when a Form XObject contains multiple
        # images), or a slash-separated pair (which only happens for
        # OVERLAP, handled above).
        weight = RISK_WEIGHTS.get(ftype, 0)
        if weight == 0:
            continue

        for chunk in image_field.split("/"):
            for label in chunk.split(","):
                label = label.strip()
                if label in scores:
                    scores[label] += weight

    # Cap at 100
    return {label: min(s, RISK_SCORE_CAP)
            for label, s in scores.items()}


def compute_document_risk(all_findings, comments=None, doc_findings=None):
    """
    Compute page-level and document-level risk scores.

    These cover document/page-level finding types that are not tied to a
    single image (so the per-image scorer cannot attribute them), plus a
    small informational contribution for the presence of reviewer
    comments.

    Parameters:
      all_findings : {page_number: [finding dict, ...]}
                     the same per-page findings structure the engine
                     builds; the page number is taken from the dict key,
                     so individual findings need not carry a page field.
      comments     : optional list of extracted comment/markup dicts.
      doc_findings : optional list of DOCUMENT-level finding dicts
                     (metadata anomalies, signature coverage, structural
                     warnings, mixed cameras) that belong to no page.
                     Their weights add to the document score directly
                     and never to any page score.

    Returns (page_scores, doc_score):
      page_scores : {page_number: int 0..100} — each page's accumulated
                    document-level finding weight, capped at 100.
      doc_score   : int 0..100 — the most suspicious page's score, plus
                    the summed weights of document-level findings, plus
                    a flat amount if any reviewer comments are present,
                    capped at 100.

    The page component intentionally uses the maximum page score (not
    the sum across pages) so that one heavily-flagged page is not
    diluted by, nor inflated by the count of, other clean pages.
    Document-level findings are summed because each is an independent
    signal about the document itself.
    """
    page_scores = {}
    for page_num, findings in all_findings.items():
        score = 0
        for f in findings:
            score += DOC_RISK_WEIGHTS.get(f.get("type"), 0)
        page_scores[page_num] = min(score, RISK_SCORE_CAP)

    doc_score = max(page_scores.values(), default=0)
    for f in (doc_findings or []):
        doc_score += DOC_RISK_WEIGHTS.get(f.get("type"), 0)
    if comments:
        doc_score += COMMENT_RISK_WEIGHT
    doc_score = min(doc_score, RISK_SCORE_CAP)

    return page_scores, doc_score
