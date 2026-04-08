def ns_diff(new_val, old_val):
    """Calculates the difference between two counter strings."""
    try:
        diff = int(new_val) - int(old_val)
        return max(0, diff) # Counters should never go backwards
    except (ValueError, TypeError):
        return 0

def format_brate(bytes_per_sec):
    """Converts raw bytes/s into KB/s, MB/s, or GB/s."""
    rate = float(bytes_per_sec)
    if rate > 10**9:
        return f"{rate / 10**9:.2f} GB/s"
    elif rate > 10**6:
        return f"{rate / 10**6:.2f} MB/s"
    elif rate > 10**3:
        return f"{rate / 10**3:.2f} KB/s"
    else:
        return f"{rate:.2f} B/s"