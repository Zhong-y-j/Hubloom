"""Run the transport mock API on port 8101."""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    from .app import app

    uvicorn.run(app, host="127.0.0.1", port=8003, reload=False)
