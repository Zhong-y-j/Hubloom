"""Run the attraction mock API on port 8103."""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    from .app import app

    uvicorn.run(app, host="127.0.0.1", port=8103, reload=False)
