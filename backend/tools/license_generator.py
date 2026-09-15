#!/usr/bin/env python
"""Offline key and license generator. Keep the private key off user devices."""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from apps.users.licensing import generate_keypair, sign_license  # noqa: E402


def _write_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def generate_keys(args: argparse.Namespace) -> None:
    private_key, public_key = generate_keypair()
    _write_secret(args.private_key, private_key)
    args.public_key.parent.mkdir(parents=True, exist_ok=True)
    args.public_key.write_text(public_key + "\n", encoding="utf-8")
    print(f"Private key: {args.private_key}")
    print(f"Public key:  {args.public_key}")
    print("Keep the private key secret and back it up securely.")


def _expiry(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise SystemExit("--expires-at must be YYYY-MM-DD or ISO-8601") from exc
        parsed = datetime.combine(parsed_date, time.max, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def issue(args: argparse.Namespace) -> None:
    expires_at = _expiry(args.expires_at)
    if args.license_type in {"trial", "subscription"} and not expires_at:
        raise SystemExit("trial and subscription licenses require --expires-at")
    private_key = args.private_key.read_text(encoding="utf-8").strip()
    payload = {
        "version": 1,
        "license_id": args.license_id or str(uuid.uuid4()),
        "product": args.product,
        "machine_code": args.machine_code.strip().upper(),
        "customer": args.customer,
        "edition": args.edition,
        "license_type": args.license_type,
        "issued_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        "expires_at": expires_at,
        "features": args.feature,
    }
    token = sign_license(payload, private_key)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(token + "\n", encoding="utf-8")
        print(f"License written to {args.output}")
    else:
        print(token)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Agent Studio offline license tool")
    commands = root.add_subparsers(dest="command", required=True)

    keys = commands.add_parser("generate-keys", help="create an Ed25519 key pair")
    keys.add_argument("--private-key", type=Path, default=Path("license-private.key"))
    keys.add_argument("--public-key", type=Path, default=Path("license-public.key"))
    keys.set_defaults(handler=generate_keys)

    license_command = commands.add_parser("issue", help="issue a machine-bound license")
    license_command.add_argument("--private-key", type=Path, required=True)
    license_command.add_argument("--machine-code", required=True)
    license_command.add_argument("--customer", required=True)
    license_command.add_argument("--product", default="agent-studio")
    license_command.add_argument("--edition", default="professional")
    license_command.add_argument(
        "--license-type",
        choices=("perpetual", "subscription", "trial"),
        default="perpetual",
    )
    license_command.add_argument("--expires-at")
    license_command.add_argument("--license-id")
    license_command.add_argument("--feature", action="append", default=[])
    license_command.add_argument("--output", type=Path)
    license_command.set_defaults(handler=issue)
    return root


def main() -> None:
    args = parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
