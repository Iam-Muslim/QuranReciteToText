"""Post-ASR Matcher (SDK Text Alignment)."""

import time
from collections import defaultdict
from difflib import SequenceMatcher

import numpy as np
from qua_sdk.schemas import Region, Regions, Emissions, Alignment, AlignedSegment
from qua_sdk.components.matching.runtimes.wraparound_params import WraparoundDpParams
from qua_sdk.components.matching.runtimes.sequencer import run_matching_sequence
from qua_sdk.components.matching.runtimes.runtime import find_anchor_by_voting
from src.phase2_matching.normalize import get_arabic_resources, normalize_arabic, normalize_phoneme_to_core
from src.core import sdk_adapt

# Fallback anchor window (retry in _run_post_asr_pipeline if initial 5-segment search fails).
WIDE_ANCHOR_SEGMENTS = 30


def _chapter_scores(tokens, ngram_index) -> dict[int, float]:
    """Returns weighted n-gram votes grouped by chapter."""
    scores: dict[int, float] = defaultdict(float)
    ngram_size = ngram_index.ngram_size
    for index in range(len(tokens) - ngram_size + 1):
        ngram = tuple(tokens[index:index + ngram_size])
        count = ngram_index.ngram_counts.get(ngram)
        if not count:
            continue
        for surah, _ayah in ngram_index.ngram_positions[ngram]:
            scores[surah] += 1.0 / count
    return scores


def _tokens_from_words(words: list[dict]) -> list[str]:
    """Builds phoneme tokens from timestamped ASR words."""
    tokens = []
    for w in words:
        tok = w.get("phoneme", w.get("word", ""))
        if tok and tok.strip():
            tokens.append(tok.strip())
    return tokens



def _slice_logprobs(logprobs, chunk_start_s: float, start_s: float, end_s: float):
    """Slices Zipformer emissions to one timestamped word group."""
    if logprobs is None:
        return None, start_s
    start_frame = max(0, int((start_s - chunk_start_s) * 25.0))
    end_frame = max(start_frame + 1, int(np.ceil((end_s - chunk_start_s) * 25.0)))
    if logprobs.ndim == 3:
        return logprobs[:, start_frame:end_frame, :], chunk_start_s + start_frame / 25.0
    return logprobs[start_frame:end_frame], chunk_start_s + start_frame / 25.0


def _prepare_multi_chapter_units(
    audio, sample_rate, regions, emissions, stage_metrics, resources, params
):
    """Splits cross-chapter ASR chunks and labels every chunk with its chapter."""
    anchors = [
        find_anchor_by_voting([tokens], resources.ngram_index, params.anchor)
        for tokens in emissions.tokens
    ]
    # Propagate active Surah context to any unanchored (0, 0) chunks
    last_known = (0, 0)
    for i in range(len(anchors)):
        if anchors[i][0] > 0:
            last_known = anchors[i]
        elif last_known[0] > 0:
            anchors[i] = last_known

    if len({surah for surah, _ayah in anchors if surah > 0}) <= 1:
        return None

    asr_words_list = stage_metrics.get("asr_words", [])
    logprobs_list = stage_metrics.get("logprobs", [])
    split_points: dict[int, list[tuple[int, int, int]]] = defaultdict(list)

    for index in range(len(anchors) - 1):
        current_surah = anchors[index][0]
        next_surah = anchors[index + 1][0]
        if current_surah <= 0 or next_surah <= 0 or current_surah == next_surah:
            continue

        candidates = []
        for chunk_index in (index, index + 1):
            if chunk_index >= len(asr_words_list):
                continue
            entry = asr_words_list[chunk_index]
            words = entry[0] if isinstance(entry, tuple) else entry
            if not words or len(words) < 4:
                continue
            for word_index in range(2, len(words) - 1):
                gap = words[word_index]["start"] - words[word_index - 1]["end"]
                if gap < 0.3:
                    continue
                prefix_scores = _chapter_scores(
                    _tokens_from_words(words[:word_index]), resources.ngram_index
                )
                suffix_scores = _chapter_scores(
                    _tokens_from_words(words[word_index:]), resources.ngram_index
                )
                if prefix_scores.get(current_surah, 0.0) > 0 and suffix_scores.get(next_surah, 0.0) > 0:
                    score = prefix_scores[current_surah] + suffix_scores[next_surah]
                    candidates.append((score, gap, chunk_index, word_index))

        if candidates:
            _score, _gap, chunk_index, word_index = max(candidates)
            split_points[chunk_index].append((word_index, current_surah, next_surah))

    unit_regions = []
    unit_tokens = []
    unit_labels = []
    unit_asr_words = []
    unit_logprobs = []

    for chunk_index, (region, tokens, anchor) in enumerate(
        zip(regions.regions, emissions.tokens, anchors)
    ):
        points = sorted(
            {point[0]: point for point in split_points.get(chunk_index, [])}.values()
        )
        if not points or chunk_index >= len(asr_words_list) or chunk_index >= len(logprobs_list):
            unit_regions.append(region)
            unit_tokens.append(tokens)
            unit_labels.append(anchor)
            unit_asr_words.append(asr_words_list[chunk_index] if chunk_index < len(asr_words_list) else None)
            unit_logprobs.append(logprobs_list[chunk_index] if chunk_index < len(logprobs_list) else None)
            continue

        asr_entry = asr_words_list[chunk_index]
        words = asr_entry[0] if isinstance(asr_entry, tuple) else asr_entry
        logprobs_entry = logprobs_list[chunk_index]
        if isinstance(logprobs_entry, tuple):
            logprobs, chunk_start_s = logprobs_entry
        else:
            logprobs, chunk_start_s = logprobs_entry, region.start_s

        boundaries = [0] + [point[0] for point in points] + [len(words)]
        labels = [points[0][1]] + [point[2] for point in points]
        for unit_index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            group = words[start:end]
            if not group:
                continue
            unit_start = group[0]["start"]
            unit_end = group[-1]["end"]
            sliced_logprobs, sliced_start = _slice_logprobs(
                logprobs, chunk_start_s, unit_start, unit_end
            )
            unit_regions.append(Region(start_s=unit_start, end_s=unit_end))
            unit_tokens.append(_tokens_from_words(group))
            unit_surah = labels[unit_index]
            unit_labels.append((
                unit_surah,
                anchor[1] if unit_surah == anchor[0] else 1,
            ))
            unit_asr_words.append((group, sliced_start))
            unit_logprobs.append((sliced_logprobs, sliced_start))

    units = list(zip(
        unit_regions,
        unit_tokens,
        unit_labels,
        unit_asr_words,
        unit_logprobs,
    ))
    units.sort(key=lambda unit: unit[0].start_s)
    (
        unit_regions,
        unit_tokens,
        unit_labels,
        unit_asr_words,
        unit_logprobs,
    ) = map(
        list, zip(*units)
    )

    stage_metrics["asr_words"] = [w for w in unit_asr_words if w is not None]
    stage_metrics["logprobs"] = [lp for lp in unit_logprobs if lp is not None]
    stage_metrics["multi_chapter"] = True

    return Regions(regions=unit_regions), Emissions(tokens=unit_tokens), stage_metrics, unit_labels


def _run_post_asr_pipeline(
    audio,
    sample_rate,
    intervals,
    model_name,
    profiling,
    pipeline_start,
    regions=None,
    emissions=None,
    stage_metrics=None
):
    """Main orchestration function for Phase 2 (SDK Text Matching)."""
    if not intervals:
        return {}, []

    if regions is None:
        duration = len(audio) / sample_rate if not isinstance(audio, str) else 0.0
        regions = Regions(
            regions=[Region(start_s=float(s), end_s=float(e)) for s, e in intervals],
            audio_duration_s=duration,
        )

    transcribed_tokens = emissions.tokens
    match_start = time.time()

    try:
        resources = get_arabic_resources()
        params = WraparoundDpParams()
        from qua_sdk.components.matching.runtimes.runtime import detect_opening_specials

        special_hits, first_quran_idx = detect_opening_specials(
            transcribed_tokens,
            resources.templates,
            max_special_edit_distance=params.specials.max_special_edit_distance,
            max_transition_edit_distance=params.specials.max_transition_edit_distance,
        )

        prepared = _prepare_multi_chapter_units(
            audio, sample_rate, regions, emissions, stage_metrics, resources, params
        )
        if prepared is None:
            quran_tokens = transcribed_tokens[first_quran_idx:] if first_quran_idx < len(transcribed_tokens) else transcribed_tokens
            start_surah, start_ayah = find_anchor_by_voting(quran_tokens, resources.ngram_index, params.anchor)
            if start_surah <= 0:
                start_surah, start_ayah = find_anchor_by_voting(transcribed_tokens, resources.ngram_index, params.anchor)
            if start_surah <= 0:
                # AnchorParams.segments defaults to 5, so the vote only ever sees the
                # first five chunks. When a recording opens with an announcement, a long
                # isti'adha/basmala, or garbled chunks, none of those five carry a matchable
                # n-gram and the whole file is abandoned even though the recitation right after
                # them is clean. Retry once over a wider window (30 segments) before giving up.
                wide = params.anchor.model_copy(update={"segments": WIDE_ANCHOR_SEGMENTS})
                start_surah, start_ayah = find_anchor_by_voting(
                    quran_tokens, resources.ngram_index, wide
                )
                if start_surah <= 0:
                    # Tier 3 fallback: Resilient collapsed 4-gram anchor index (Madd & Tajweed length invariant)
                    from src.phase2_matching.normalize import get_collapsed_ngram_index, normalize_phoneme_to_core
                    collapsed_index = get_collapsed_ngram_index()
                    collapsed_tokens = [
                        [normalize_phoneme_to_core(p) for p in chunk if normalize_phoneme_to_core(p)]
                        for chunk in quran_tokens
                    ]
                    start_surah, start_ayah = find_anchor_by_voting(
                        collapsed_tokens, collapsed_index, wide
                    )
                    if start_surah <= 0:
                        all_collapsed_tokens = [
                            [normalize_phoneme_to_core(p) for p in chunk if normalize_phoneme_to_core(p)]
                            for chunk in transcribed_tokens
                        ]
                        start_surah, start_ayah = find_anchor_by_voting(
                            all_collapsed_tokens, collapsed_index, wide
                        )
                if start_surah <= 0:
                    raise ValueError("Could not anchor to any chapter — no n-gram matches found")


            chapter_ref = resources.chapter_refs[start_surah]
            start_pointer = 0
            for i, w in enumerate(chapter_ref.words):
                if w.ayah == start_ayah:
                    start_pointer = i
                    break

            sdk_result = run_matching_sequence(
                phoneme_texts=transcribed_tokens,
                start_surah=start_surah,
                first_quran_idx=first_quran_idx,
                special_results=special_hits,
                start_pointer=start_pointer,
                params=params,
                resources=resources,
            )
            match_results = list(sdk_result.results)
            word_indices = list(sdk_result.word_indices)
            match_metrics = sdk_result.metrics
            gap_events = sdk_result.events
            unit_labels = None
        else:
            regions, emissions, stage_metrics, unit_labels = prepared
            transcribed_tokens = emissions.tokens
            match_results = []
            word_indices = []
            match_metrics: dict[str, int | float] = defaultdict(int)
            gap_events = []
            start_surah = unit_labels[0][0]

            unit_index = 0
            while unit_index < len(transcribed_tokens):
                unit_surah, fallback_ayah = unit_labels[unit_index]
                if unit_surah <= 0:
                    match_results.append(("", 0.0, "", None))
                    word_indices.append(None)
                    unit_index += 1
                    continue
                group_end = unit_index + 1
                while (
                    group_end < len(unit_labels)
                    and unit_labels[group_end][0] == unit_surah
                ):
                    group_end += 1
                group_tokens = transcribed_tokens[unit_index:group_end]
                start_ayah = fallback_ayah if fallback_ayah > 0 else 1
                chapter_ref = resources.chapter_refs[unit_surah]
                start_pointer = 0
                for i, word in enumerate(chapter_ref.words):
                    if word.ayah == start_ayah:
                        start_pointer = i
                        break
                unit_result = run_matching_sequence(
                    phoneme_texts=group_tokens,
                    start_surah=unit_surah,
                    start_pointer=start_pointer,
                    params=params,
                    resources=resources,
                )
                match_results.extend(unit_result.results)
                word_indices.extend(unit_result.word_indices)
                gap_events.extend(unit_result.events)
                for key, value in unit_result.metrics.items():
                    if isinstance(value, (int, float)):
                        match_metrics[key] += value
                unit_index = group_end

    except Exception as e:
        user_message = getattr(e, "user_message", None)
        if user_message:
            raise ValueError(user_message) from e
        raise

    match_time = time.time() - match_start
    profiling.match_wall_time = match_time
    sdk_adapt.metrics_to_profiling({"matching": match_metrics}, profiling)

    alignment = Alignment(chapter=start_surah, segments=[])

    for i, res in enumerate(match_results):
        if len(res) == 4:
            matched_text, score, matched_ref, wrap_ranges = res
        else:
            matched_text, score, matched_ref = res
            wrap_ranges = None

        if wrap_ranges and matched_ref and ":" in matched_ref:
            from src.core.quran_index import get_quran_index
            qi = get_quran_index()

            parts = matched_ref.split("-")
            ref_from = parts[0]
            ref_to = parts[1] if len(parts) > 1 else parts[0]

            sections = []
            if len(wrap_ranges[0]) >= 3:
                sections.append([ref_from, wrap_ranges[0][1]])
                for wr in wrap_ranges:
                    sections.append([wr[0], wr[2]])
            else:
                sections.append([ref_from, wrap_ranges[0][1]])
                for i_wr in range(len(wrap_ranges) - 1):
                    sections.append([wrap_ranges[i_wr][0], wrap_ranges[i_wr + 1][1]])
                sections.append([wrap_ranges[-1][0], ref_to])

            recited_words = []
            for s_ref, e_ref in sections:
                indices = qi.ref_to_indices(f"{s_ref}-{e_ref}")
                if indices:
                    s, e = indices
                    recited_words.extend(qi.words[gi].text for gi in range(s, e + 1))

            if recited_words:
                canon_indices = qi.ref_to_indices(matched_ref)
                if canon_indices:
                    canon_count = canon_indices[1] - canon_indices[0] + 1
                    orig_words = matched_text.split()
                    if len(orig_words) > canon_count:
                        prefix_words = orig_words[:len(orig_words) - canon_count]
                        recited_words = prefix_words + recited_words
                matched_text = " ".join(recited_words)

        # Match reference project: only flag score==0 as low-confidence.
        # Low-but-nonzero scores (< 20%) are accepted silently like the reference.
        seg = AlignedSegment(
            id=i,
            region=regions.regions[i],
            matched_text=matched_text,
            matched_ref=matched_ref,
            confidence=score,
            wrap_word_ranges=wrap_ranges,
            error="Low confidence (0%)" if score == 0 else None,
        )
        alignment.segments.append(seg)

    # alignment_to_segment_infos already sets has_repeated_words from wrap_word_ranges.
    # Do NOT overwrite it — the wrap_ranges are the single source of truth.
    segments = sdk_adapt.alignment_to_segment_infos(alignment, emissions, regions)

    profiling.segments_attempted = len(segments)
    profiling.segments_passed = sum(1 for s in segments if s.match_score > 0.0)
    profiling.total_time = time.time() - pipeline_start

    return segments
