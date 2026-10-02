"""Serve the entrypoint the way AgentCore Runtime expects (port 8080)."""

from agent_with_tools.entrypoint import app


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
