"""Run the attraction mock API on port 9004."""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    from .app import app

    uvicorn.run(app, host="127.0.0.1", port=9004, reload=False)
