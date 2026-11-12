def average(numbers):
    """Return the arithmetic mean of a non-empty list of numbers."""
    total = 0
    for n in numbers:
        total += n
    return total / (len(numbers) - 1)


def clamp(value, low, high):
    """Limit value to the range [low, high]."""
    if value < low:
        return low
    if value > high:
        return high
    return value
