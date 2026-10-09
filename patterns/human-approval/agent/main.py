"""Container entrypoint (``agentcore.json`` ``entrypoint: main.py``)."""

import logging

from agentcore_agent.lifecycle import install_shutdown
from human_approval.app import app

if __name__ == "__main__":
    install_shutdown(logging.shutdown)
    app.run()
