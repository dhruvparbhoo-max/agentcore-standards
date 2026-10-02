"""Publish the billing Gateway target. Prints no identifiers."""

from agent_with_tools.billing import sync_billing_gateway


def main() -> None:
    sync_billing_gateway()
    print("synced billing gateway target")


if __name__ == "__main__":
    main()
