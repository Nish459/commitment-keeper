def sentence_case(text: str) -> str:
    """Trim and capitalize the first letter only, so "Q3 deck" stays as written."""
    text = text.strip()
    return text[:1].upper() + text[1:]
