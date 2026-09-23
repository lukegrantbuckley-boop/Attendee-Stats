"""Run the local site. Usage: python -m attendee_tracker.serve"""

from __future__ import annotations

import uvicorn

from attendee_tracker.config import load_dotenv, port


def main() -> None:
    load_dotenv()
    uvicorn.run(
        "attendee_tracker.app:app",
        host="0.0.0.0",
        port=port(),
        reload=False,
    )


if __name__ == "__main__":
    main()
