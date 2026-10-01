"""Serve the entrypoint the way AgentCore Runtime expects (port 8080)."""

from minimal_agent.entrypoint import app


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
