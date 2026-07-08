def try_parse_int(input_string: str) -> int | None:
    try:
        return int(input_string)
    except ValueError:
        return None


def parse_index_ranges(spec: str, count: int) -> list[int] | None:
    """Parse a comma-separated list of indices and inclusive ranges into an ordered
    index list, e.g. "0-1,3,5,7-9" -> [0, 1, 3, 5, 7, 8, 9].

    Every index must be in [0, count). Order is preserved as written; duplicates are
    kept. Returns None if any token is malformed or out of range (an error is
    printed by the caller).
    """
    indices: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if token == "":
            continue

        if "-" in token:
            start_str, sep, end_str = token.partition("-")
            start = try_parse_int(start_str.strip())
            end = try_parse_int(end_str.strip())
            if start is None or end is None or start > end:
                return None
            if not (0 <= start < count) or not (0 <= end < count):
                return None
            indices.extend(range(start, end + 1))
        else:
            idx = try_parse_int(token)
            if idx is None or not (0 <= idx < count):
                return None
            indices.append(idx)

    return indices


def mask_string_middle(input_string: str) -> str:
    REVEAL_COUNT = 3

    string_length = len(input_string)

    if string_length <= 2 * REVEAL_COUNT:
        return string_length * "*"

    start_revealed = input_string[:REVEAL_COUNT]
    end_revealed = input_string[-REVEAL_COUNT:]
    middle_stars = "*" * 3
    masked_string = start_revealed + middle_stars + end_revealed

    return masked_string
