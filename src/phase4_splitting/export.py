def segments_to_json(segments: list, include_words: bool = False) -> dict:
    """
    Utility function to convert a list of SegmentInfo objects into the final 
    master JSON payload dictionary.
    """
    return {"segments": [seg.to_json_dict(include_words=include_words) for seg in segments]}