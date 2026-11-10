"""Reject ambiguous source identities before the daily CSV is rewritten."""


def require_unique_codes(rows):
    seen = set()
    for row in rows:
        code = str(row[4]).strip()
        if code in seen:
            raise ValueError(f"厚労省原表の識別コードが重複しています: {code}")
        seen.add(code)
