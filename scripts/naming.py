from __future__ import annotations

import argparse
import re

_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _transliterate(text: str) -> str:
    result = []
    for char in text:
        lower = char.lower()
        if lower in _CYRILLIC_TO_LATIN:
            replacement = _CYRILLIC_TO_LATIN[lower]
            result.append(replacement.upper() if char.isupper() and replacement else replacement)
        else:
            result.append(char)
    return "".join(result)


def slugify(text: str) -> str:
    transliterated = _transliterate(text).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated)
    return slug.strip("-")


def build_clip_filename(index: int, title: str, extension: str = "mp4") -> str:
    return f"{index:04d}-{slugify(title)}.{extension}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a filesystem-safe clip filename from an index and a descriptive title"
    )
    parser.add_argument("index", type=int, help="1-based clip index")
    parser.add_argument("title", help="Short descriptive title, e.g. 'Boss Rage Quit'")
    parser.add_argument("--extension", default="mp4", help="File extension without the dot (default: mp4)")
    args = parser.parse_args()

    print(build_clip_filename(args.index, args.title, args.extension))


if __name__ == "__main__":
    main()
