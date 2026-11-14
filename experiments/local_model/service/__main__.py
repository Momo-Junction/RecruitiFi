"""Loopback by default. Never start multiple workers or use reload."""
import argparse
import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument('--host', choices=('127.0.0.1', '0.0.0.0'), default='127.0.0.1')
args = parser.parse_args()
uvicorn.run('service.app:app', host=args.host, port=8080, workers=1, access_log=False,
            limit_concurrency=8, backlog=16, timeout_keep_alive=5, timeout_graceful_shutdown=30)
