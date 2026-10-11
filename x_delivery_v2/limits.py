"""Single source of truth for X-only volume and estimated API costs.

Do not use these settings for Discord or prediction generation.
The USD rate is the public X pricing for a standard link-free POST /2/tweets
request (checked 2026-10-11); the actual bill and credit balance are only
available in X's Developer Console.
"""

MAX_DAILY_X_PREDICTIONS = 30
MAX_RESULTS_PER_PREDICTION = 1
STANDARD_POST_CREATE_USD = 0.015
