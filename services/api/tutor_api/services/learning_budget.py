"""Time available for extra practice after comparable school work."""


def remaining_minutes(weekly_minutes: int, school_minutes: int) -> int:
    """Return the remaining minutes from validated nonnegative inputs."""
    return max(0, weekly_minutes - school_minutes)
