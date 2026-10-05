"""Safe, actionable operator guidance; never include credentials or raw responses."""

GUIDANCE = {
    "NOT_YET_PUBLISHED": "The dated file was not found. Check the exchange trading calendar and publication time, then retry that date or upload the official final file.",
    "SOURCE_ACCESS_BLOCKED": "The exchange denied access (403/406). Verify permitted source access; use an official-file upload if available. Repeated automatic retries will not fix access restrictions.",
    "BLOCKED_ADMIN_REQUIRED": "An earlier request was denied. Review exchange access before a manual retry.",
    "RATE_LIMITED_RETRY_LATER": "The source requested a wait. Check the retry-after time in file details and rerun after it expires.",
    "SOURCE_RATE_LIMITED": "The source rate limit is active. Wait for its retry-after deadline before rerunning.",
    "TRADING_CALENDAR_REQUIRED": "Update the source calendar year and official holiday dates in Price sources & recovery.",
    "INVALID_BHAVCOPY_CONTENT": "The download is not a valid final UDiFF CSV/ZIP. Check the source URL and the returned file format.",
    "WRONG_TRADE_DATE": "The file contains another trading date. Choose the correct date or upload its matching official file.",
    "UNMAPPED_IDENTIFIER": "Add the verified exchange symbol, BSE code or ISIN to the company, then retry.",
    "IDENTIFIER_CONFLICT": "More than one company matches this identifier. Review company mappings before retrying.",
    "QUEUE_UNAVAILABLE": "Check Redis and the Celery worker, then retry the job. The request was not delivered.",
    "WORKER_TIMEOUT": "The worker did not finish within the expected window. Check worker health and logs using this run ID before retrying.",
    "SOURCE_UNAVAILABLE": "The exchange could not be reached. Check connectivity and permitted access, then retry later.",
    "PARSING_REVIEW_REQUIRED": "Review the retained original filing and its taxonomy in Results review & recovery before publishing.",
    "NO_TRACKED_IDENTIFIERS": "No verified company identifiers are mapped for this exchange. Add mappings before running discovery.",
    "SOURCE_DISABLED": "Enable this exchange source in its configuration before running this job.",
    "NOT_A_TRADING_SESSION": "No close is expected for this date according to the configured exchange calendar.",
    "ALREADY_IMPORTED": "The scheduled file has already been imported. A manual run can check for exchange corrections.",
    "PAUSED": "Resume this job before running it.",
}


def guidance(code):
    if code and code.startswith(("BSE: ", "NSE: ")):
        code = code.split(": ", 1)[1]
    if code in ("SUCCESS", "PARTIAL"):
        return "Validated records were retained. For partial imports, review the rejected-row report below."
    return GUIDANCE.get(
        (code or "").split(":")[0],
        "Inspect the source/record and error code below. Correct the source mapping or configuration before retrying; previously published data is retained.",
    )
