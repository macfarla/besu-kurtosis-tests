#!/usr/bin/env python3
"""
Engine API proxy for reproducing the LayeredKeyValueStorage stall (besu-eth/besu#10498).

Matches the ethpandaops/rpc-snooper CLI interface so it can be used as a drop-in
replacement via kurtosis ethereum-package's snooper_params.image config.

Forwards all Engine API calls to the upstream EL except engine_forkchoiceUpdated*,
which are dropped (returns SYNCING). This causes world-state layers to accumulate
on the EL side without FCU advancing, reproducing the stall condition.

Usage (standalone):
    pip install aiohttp
    python3 engine-api-fcu-proxy.py -p 8561 http://besu-host:8551

Usage (as kurtosis snooper replacement, started by ethereum-package):
    python3 engine-api-fcu-proxy.py -b 0.0.0.0 -p 8561 http://el-1:8551

What to watch (in Besu logs with --logging=DEBUG):
    "adding layered world state for block" — layers accumulating
    "Returning SYNCING for engine_newPayload: N cached world state layers" — fix firing
"""

import argparse
import asyncio
import json
import logging
import time

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

stats = {"new_payload": 0, "fcu_dropped": 0, "start": time.time()}

FCU_SYNCING_RESPONSE = {
    "jsonrpc": "2.0",
    "result": {
        "payloadStatus": {"status": "SYNCING", "latestValidHash": None, "validationError": None},
        "payloadId": None,
    },
}


async def handle(request: web.Request, upstream: str) -> web.Response:
    body = await request.read()
    try:
        rpc = json.loads(body)
    except json.JSONDecodeError:
        return web.Response(status=400, text="invalid JSON")

    batch = rpc if isinstance(rpc, list) else [rpc]
    results = []

    for req in batch:
        method = req.get("method", "")
        req_id = req.get("id")

        if method.startswith("engine_forkchoiceUpdated"):
            stats["fcu_dropped"] += 1
            log.info("FCU DROPPED  method=%-40s  total_dropped=%d", method, stats["fcu_dropped"])
            results.append({**FCU_SYNCING_RESPONSE, "id": req_id})
        else:
            if method.startswith("engine_newPayload"):
                stats["new_payload"] += 1
                log.info("newPayload FORWARDED  count=%-4d  threshold=128", stats["new_payload"])
                if stats["new_payload"] == 128:
                    log.warning("Reached 128 newPayload calls — next call should return SYNCING from Besu")
            # Forward request, passing through all original headers (including CL's JWT)
            forward_headers = {k: v for k, v in request.headers.items()
                               if k.lower() not in ("host", "content-length")}
            async with aiohttp.ClientSession() as session:
                async with session.post(upstream, data=json.dumps(req), headers=forward_headers) as resp:
                    besu_body = await resp.read()
            try:
                result = json.loads(besu_body)
                # Log when Besu itself starts returning SYNCING (the fix firing)
                if method.startswith("engine_newPayload"):
                    status = (result.get("result") or {}).get("status", "")
                    if status == "SYNCING":
                        log.warning("Besu returned SYNCING for newPayload — layer cap reached, fix is working")
                results.append(result)
            except json.JSONDecodeError:
                results.append({"jsonrpc": "2.0", "id": req_id,
                                 "error": {"code": -32700, "message": "upstream parse error"}})

    response_body = json.dumps(results if isinstance(rpc, list) else results[0])
    return web.Response(text=response_body, content_type="application/json")


async def stats_printer():
    while True:
        await asyncio.sleep(30)
        elapsed = int(time.time() - stats["start"])
        log.info("STATS  elapsed=%ds  newPayload_forwarded=%d  fcu_dropped=%d",
                 elapsed, stats["new_payload"], stats["fcu_dropped"])


async def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-b", "--bind", default="0.0.0.0", help="Bind address")
    parser.add_argument("-p", "--port", type=int, default=8561, help="Listen port")
    parser.add_argument("upstream", help="Upstream EL engine URL, e.g. http://el-1:8551")
    args = parser.parse_args()

    log.info("FCU-dropping proxy: listening on %s:%d → %s", args.bind, args.port, args.upstream)
    log.info("engine_forkchoiceUpdated* will be DROPPED (returns SYNCING)")
    log.info("engine_newPayload* will be FORWARDED — watch for layer cap at 128")

    app = web.Application()
    app.router.add_post("/", lambda req: handle(req, args.upstream))
    app.router.add_post("/{tail:.*}", lambda req: handle(req, args.upstream))

    asyncio.create_task(stats_printer())

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.bind, args.port)
    await site.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
