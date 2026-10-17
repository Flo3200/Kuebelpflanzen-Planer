"""CLI: python -m app.demo [--reset] [--seed N] [--orders N] [--staff N]"""

import argparse
import json

from app.demo.generator import DemoOptions, generate


def main() -> None:
    parser = argparse.ArgumentParser(description="Demodaten erzeugen (keine echten Kundendaten).")
    parser.add_argument("--reset", action="store_true", help="vorhandene Demo-Betriebe vorher löschen")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--orders", type=int, default=100, help="Aufträge pro Betrieb")
    parser.add_argument("--staff", type=int, default=10, help="Personal pro Betrieb")
    parser.add_argument("--no-measurements", action="store_true")
    args = parser.parse_args()
    report = generate(
        DemoOptions(
            seed=args.seed,
            orders_per_tenant=args.orders,
            staff_per_tenant=args.staff,
            measurements=not args.no_measurements,
        ),
        reset=args.reset,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
