"""Server-side token administration. Issue prints the credential once; do not log stdout."""

import argparse
import asyncio
import os
import secrets

from .auth import digest
from .storage import Store


async def run(args):
    secret = os.environ["TOKEN_HASH_SECRET"].encode()
    if len(secret) < 32:
        raise ValueError("TOKEN_HASH_SECRET must contain at least 32 characters")
    store = await Store.connect(os.environ["DATABASE_URL"])
    try:
        if args.action == "issue":
            token = "tsp_" + secrets.token_urlsafe(32)
            token_id = await store.pool.fetchval(
                "INSERT INTO api_client_tokens (token_hash,tier,label) "
                "VALUES ($1,$2,$3) RETURNING id",
                digest(secret, token.encode()),
                args.tier,
                args.label,
            )
            print(f"id={token_id}\ntoken={token}")
        else:
            result = await store.pool.execute(
                "UPDATE api_client_tokens SET revoked_at=now() WHERE id=$1",
                args.id,
            )
            print(result)
    finally:
        await store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("--tier", choices=("free", "paid"), required=True)
    issue.add_argument("--label")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("id", type=int)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
