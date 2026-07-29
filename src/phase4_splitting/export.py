"""JSON export writers for download — segment-mode and verse-mode."""
import json
import tempfile

from src.core.segment_types import segments_to_json

# Segment fields surfaced to download / API consumers. The internal
# SegmentInfo carries UI-only state (merge_*, transcribed_text) that we never
# export; consumers project to canonical takes themselves via ``duplicated``.
PUBLIC_SEGMENT_KEYS = {
    "segment",
    "time_from",
    "time_to",
    "ref_from",
    "ref_to",
    "matched_text",
    "confidence",
    "has_missing_words",
    "has_repeated_words",
    "special_type",
    "error",
    "wrap_word_ranges",
    "repeated_ranges",
    "repeated_text",
    "split_group_id",
    # Preload dedup taxonomy.
    "duplicated",
    "duplicate_kind",
    "duplicate_context",
    "duplicated_by_segment",
}


def build_segment_export(json_data, include_words: bool = False,
                         source: str | None = None):
    """Build the segment-mode export **dict** (the shared download/API payload).

    Accepts either a List[SegmentInfo] (UI path) or a dict already shaped like
    ``{"segments": [...]}`` (API/legacy path). Returns ``None`` when there is
    nothing to export, else a dict ``{["_meta": ...,] "segments": [...]}``.

    Word timestamps are only included when ``include_words=True`` — set by the
    Animate All flow and the Preload API. Letter timestamps are always stripped
    (``words+chars`` is documented as disabled via API).

    ``source`` (optional) stamps a ``_meta = {view_mode: "segment", source}``
    block so a downstream consumer can distinguish a Preload segment-mode
    export from a generic live-alignment export.
    """
    def _sanitize_segment(seg):
        out = {k: seg.get(k) for k in PUBLIC_SEGMENT_KEYS if k in seg}
        if include_words and seg.get("words"):
            words = [
                {k: v for k, v in w.items() if k != "letters"}
                for w in seg["words"]
                if isinstance(w, dict)
            ]
            if words:
                out["words"] = words
        return out

    # A List[SegmentInfo] (UI / Preload-API path) serializes through
    # ``to_json_dict`` (letters already stripped there). A pre-built dict
    # (legacy/API path) is sanitized to the public key set.
    if isinstance(json_data, list):
        if not json_data:
            return None
        data = segments_to_json(json_data, include_words=include_words)
    else:
        if not json_data or not json_data.get("segments"):
            return None
        data = {
            **json_data,
            "segments": [
                _sanitize_segment(seg)
                for seg in json_data["segments"]
                if isinstance(seg, dict)
            ],
        }

    # Stamp the preload-mode discriminator only when the caller opts in.
    if source is not None:
        data = {"_meta": {"view_mode": "segment", "source": source}, **data}
    return data


def save_json_export(json_data, include_words: bool = False,
                     source: str | None = None):
    """Save segment-mode JSON results to a temp file for download.

    Thin wrapper over :func:`build_segment_export` (the shared payload builder)
    that writes the dict to a temp file. Returns the file path, or ``None`` when
    there is nothing to export.
    """
    data = build_segment_export(json_data, include_words=include_words, source=source)
    if data is None:
        return None
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
        return f.name


def save_json_export_verse_mode(
    segments,
    *,
    include_words: bool = False,
):
    """Save a verse-grouped JSON export for Preload's Verse view modes.

    Schema mirrors what the verse-mode renderer lays out: one entry per
    verse, segments inside in recitation order, each segment carrying any
    ``duplicated`` / ``duplicate_kind`` / ``duplicate_context`` /
    ``duplicated_by_segment`` flags that the dedup classifier stamped.

      ``{"_meta": {"view_mode": "verse", "source": "preload"},
         "verses": [{"ref": "<s:a>", "time_from": <s>, "time_to": <s>,
                     "segments": [<seg>, ...]}, ...]}``

    Hide vs Show repeats is a UI-side display toggle — both produce the
    SAME export bytes from the SAME segment list. Consumers decide whether
    to project to canonical takes themselves by reading the ``duplicated``
    field on each segment.

    Segments within a verse keep recitation order. Specials (Basmala /
    Isti'adha / transition tokens) interrupt the current verse group and
    surface under their own ``"ref"``.
    """
    from qua_sdk.domain import SPECIAL_NAMES as ALL_SPECIAL_REFS

    if not segments:
        return None

    groups: list[tuple[str, list[dict]]] = []
    cur_key: str | None = None
    cur_segs: list[dict] = []

    def _flush():
        if cur_key is not None and cur_segs:
            groups.append((cur_key, cur_segs))

    for seg in segments:
        d = seg.to_json_dict(include_words=include_words)
        is_special = (seg.matched_ref in ALL_SPECIAL_REFS) if seg.matched_ref else False
        if is_special:
            _flush()
            groups.append((seg.matched_ref, [d]))
            cur_key, cur_segs = None, []
            continue
        # Same-verse key from ref_from (e.g. "16:42:3" -> "16:42").
        ref_from = d.get("ref_from") or ""
        parts = ref_from.split(":", 2)
        verse_key = ":".join(parts[:2]) if len(parts) >= 2 else ref_from
        if verse_key != cur_key:
            _flush()
            cur_key, cur_segs = verse_key, []
        cur_segs.append(d)
    _flush()

    verses_out: list[dict] = []
    for ref, segs in groups:
        time_from = min((s.get("time_from", 0.0) for s in segs), default=0.0)
        time_to = max((s.get("time_to", 0.0) for s in segs), default=0.0)
        verses_out.append({
            "ref": ref,
            "time_from": time_from,
            "time_to": time_to,
            "segments": segs,
        })

    data = {
        "_meta": {"view_mode": "verse", "source": "preload"},
        "verses": verses_out,
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
        return f.name
