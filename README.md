# VAT-validator

Desktop tool for validating EU VAT numbers in bulk against the official [VIES service](https://ec.europa.eu/taxation_customs/vies/) operated by the European Commission.

Built in Python during an internship to replace manual one-by-one validation on the VIES website.

---

## What it does

1. Load an Excel file containing VAT or NIF numbers
2. The app detects the relevant column automatically
3. Validates each number concurrently against VIES via SOAP
4. Results appear in **Validated** and **Pending** tabs as they come in
5. Export results to Excel at any point

---

## Features

- **Auto-detection** of VAT/NIF columns in any Excel layout
- **Concurrent validation** — 2 workers running in parallel with 2 req/s rate limiting
- **Resilient retry logic** — exponential backoff, throttling tolerance, 120s deadline per number
- **Manual fallback** — copies the VAT number and opens the VIES website for numbers that can't be resolved automatically
- **Activity log** — per-request status (OK / WARN / ERROR) with manual export
- **Flexible export** — all results, validated only, or pending only

---

## VAT Status Types

| Status | Meaning |
|---|---|
| `VALID` | Confirmed valid by VIES |
| `INVALID` | Confirmed invalid by VIES |
| `THROTTLED` | VIES rate limit hit — queued for retry |
| `TIMEOUT` | Request timed out — queued for retry |
| `PENDING_MAX` | Max retries reached — needs manual review |
| `INVALID_FORMAT` | Doesn't match expected VAT format for its country |
| `ERROR` | Unexpected error from VIES |

---

## Architecture

```
vat_validator/
├── models.py        # Data classes: VATRecord, ValidationResult
├── validator.py     # SOAP client for the VIES service
├── vies_client.py   # Low-level SOAP requests and response parsing
├── retry_logic.py   # Retry queue with exponential backoff
├── retry_policy.py  # Configurable retry parameters
├── scheduler.py     # Concurrent worker orchestration
├── excel_handler.py # Excel read/write and column detection
├── callbacks.py     # UI update callbacks from worker threads
├── config.py        # App configuration and defaults
└── ui/              # Tkinter interface (tabs, log, export buttons)
```

---

## Installation

```bash
git clone https://github.com/davidmartinezmuelas-tech/VAT-validator.git
cd VAT-validator
pip install -r requirements.txt
python main.py
```

**Requirements:** Python 3.10+

---

## Configuration

See `example_config.py` for all available parameters:

```python
MAX_WORKERS = 2          # Concurrent validation threads
REQUESTS_PER_SECOND = 2  # Rate limit to avoid VIES throttling
REQUEST_TIMEOUT = 10     # Seconds before a single request times out
VALIDATION_DEADLINE = 120 # Max seconds to spend on one VAT number (all retries)
```

---

## Notes

VIES is an external service run by the EU. It occasionally returns `MS_MAX_CONCURRENT_REQ` or times out under load — this is expected. The retry logic handles it automatically for most cases. Numbers that exceed the deadline are flagged as `PENDING_MAX` for manual review via the built-in fallback.
