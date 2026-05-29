"""
Per-image risk score computation.
"""

# Per-finding contribution to an image's risk score.
# Scores accumulate (capped at 100).
RISK_WEIGHTS = {
    "BBOX_CROP":            30,
    "EXPLICIT_CLIP":        30,
    "OFFPAGE":              25,
    "DPI_ANOMALY":          20,
    "TEXT_OVERLAY":         35,
    "OVERLAP_BACK_FULL":    35,
    "OVERLAP_BACK_PARTIAL": 15,
    "OVERLAP_FRONT_FULL":   20,
    "OVERLAP_FRONT_PARTIAL": 8,
    "SOFT_MASK":             5,
    "IMAGE_SMASK":           5,
    "COMPLEX_TRANSFORM":     5,
}

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
