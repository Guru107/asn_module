from hypothesis import strategies as st

numeric_strings = st.from_regex(r"-?\d+(\.\d+)?", fullmatch=True)
scan_text = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -",
    min_size=0,
    max_size=64,
)
invoice_strings = st.from_regex(r"[A-Z0-9\-]{1,40}", fullmatch=True)
