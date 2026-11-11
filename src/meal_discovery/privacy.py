"""Personal data minimization before text reaches a language model (LGPD).

Food discovery never needs a phone number, e-mail, CPF or card number. When a
user types one anyway, it is replaced by a placeholder before the message is
sent to any third-party model or written to an evaluation trace. Searches are
unaffected because catalog keywords never contain these patterns.
"""

import re

PATTERNS = [
    ("[email]", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("[cpf]", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("[cartão]", re.compile(r"\b(?:\d{4}[ -]){3}\d{4}\b|\b\d{13,19}\b")),
    ("[telefone]", re.compile(r"(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{2,3}\)?[ .-]?)?\d{4,5}[ .-]?\d{4}\b")),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Return the text with personal identifiers masked and the kinds found."""
    found = []
    for label, pattern in PATTERNS:
        text, count = pattern.subn(label, text)
        if count:
            found.append(label.strip("[]"))
    return text, found
