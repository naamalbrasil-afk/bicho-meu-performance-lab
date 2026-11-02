"""Browser load test for the authorized Bicho Meu storefront only.

Each worker keeps its original network origin throughout the run. A 403, 429,
5xx, content failure or generator exhaustion stops the worker, which causes
the GitHub matrix to cancel the other workers. Never rotate origins to retry.
"""
import argparse
import asyncio
import ipaddress
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import time
from urllib.parse import urlparse

BASE = "https://bichomeu.lojavirtualnuvem.com.br"
PATHS = ("/", "/produtos/", "/produtos/camiseta-brisa/")
PHASES = ((100, 60), (250, 60), (500, 60), (1000, 180), (1500, 120), (2000, 120))
TOTAL_SECONDS = sum(seconds for _, seconds in PHASES)


def allocation(total, shard, shards):
    return total // shards + int(shard < total % shards)


def phase_at(elapsed):
    boundary = 0
    for target, seconds in PHASES:
        if elapsed < boundary + seconds:
            return target, boundary, seconds
        boundary += seconds
    return 0, TOTAL_SECONDS, 0


def resources():
    memory = {}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            if key in ('MemAvailable', 'MemTotal'):
                memory[key] = int(value.split()[0])
        return {'load_1m': os.getloadavg()[0], 'cpus': os.cpu_count() or 1,
                'available_memory_fraction': memory['MemAvailable'] / memory['MemTotal']}
    except (OSError, KeyError, ValueError):
        return {'unavailable': True}


async def run(args):
    from playwright.async_api import async_playwright
    stop = asyncio.Event()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    record = {'shard': args.shard, 'shards': args.shards, 'start_epoch': args.start,
              'profile': [list(x) for x in PHASES], 'origin_ip': None,
              'completed': False, 'stop_reason': None, 'active': 0,
              'intervals': [], 'navigation': [], 'errors': [], 'heartbeats': []}
    intervals = {}
    tasks = []

    def fail(reason, detail=None):
        if not record['stop_reason']:
            record['stop_reason'] = reason
            record['errors'].append({'at': time.time(), 'reason': reason, 'detail': detail})
        stop.set()

    def save():
        record['last_observed'] = time.time()
        record['intervals'] = list(intervals.values())
        target = out / f"worker_{args.shard}.json"
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        temporary.replace(target)

    async def pause(seconds):
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0, seconds))
        except asyncio.TimeoutError:
            pass

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: fail('execution_cancelled'))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            probe = await browser.new_context()
            page = await probe.new_page()
            response = await page.goto('https://api.ipify.org?format=json', timeout=30000)
            if not response or response.status != 200:
                raise RuntimeError('Cannot verify the browser network origin')
            origin = json.loads(await page.locator('body').inner_text())['ip']
            ipaddress.ip_address(origin)
            record['origin_ip'] = origin
            await probe.close()

            async def inspect_response(response):
                if urlparse(response.url).hostname != urlparse(BASE).hostname:
                    return
                if response.status in (403, 429) or response.status >= 500:
                    headers = {}
                    for name in ('server', 'via', 'retry-after', 'cf-ray', 'x-request-id', 'x-trace-id'):
                        value = await response.header_value(name)
                        if value:
                            headers[name] = value
                    fail(f'http_{response.status}', {'url': response.url, 'headers': headers})

            async def navigate(page, path, session):
                if stop.is_set():
                    return
                before = time.time()
                response = await page.goto(BASE + path, wait_until='load', timeout=45000)
                if not response or response.status != 200:
                    fail('main_document_http', {'path': path, 'status': response.status if response else None})
                    return
                if urlparse(page.url).hostname != urlparse(BASE).hostname:
                    fail('unexpected_redirect', {'path': path})
                    return
                if path == '/':
                    valid = 'Bicho Meu' in await page.title()
                elif path == '/produtos/':
                    valid = await page.locator('.product-item[data-product-type="list"]').count() > 0
                else:
                    valid = await page.locator('#single-product').count() == 1 and 'Camiseta Brisa' in await page.locator('h1').inner_text()
                if not valid:
                    fail('unexpected_content', {'path': path, 'title': await page.title()})
                    return
                metrics = await page.evaluate('''() => {
                  const n = performance.getEntriesByType('navigation')[0];
                  return n ? {ttfb_ms:n.responseStart-n.requestStart,
                    load_ms:n.loadEventEnd,dom_ms:n.domContentLoadedEventEnd} : {};
                }''')
                record['navigation'].append({'at': time.time(), 'session': session, 'path': path,
                                              'status': response.status,
                                              'wall_seconds': time.time() - before, **metrics})
                if path != '/':
                    await page.mouse.wheel(0, 700)
                    await pause(1)

            async def session(number):
                context = None
                session_id = f'{args.shard}:{number}'
                rng = random.Random(args.shard * 10000 + number)
                try:
                    context = await browser.new_context(viewport={'width': 390, 'height': 844} if number % 2 else {'width': 1366, 'height': 900})
                    page = await context.new_page()
                    page.on('response', inspect_response)
                    await navigate(page, '/', session_id)
                    if stop.is_set():
                        return
                    intervals[session_id] = {'session': session_id, 'start': time.time(), 'end': None}
                    record['active'] += 1
                    step = 1
                    while not stop.is_set() and time.time() < args.start + TOTAL_SECONDS:
                        await pause(rng.uniform(20, 40))
                        if not stop.is_set() and time.time() < args.start + TOTAL_SECONDS:
                            await navigate(page, PATHS[step % len(PATHS)], session_id)
                            step += 1
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    fail('browser_or_navigation_error', {'session': session_id, 'error': type(error).__name__, 'message': str(error)[:250]})
                finally:
                    if session_id in intervals and intervals[session_id]['end'] is None:
                        intervals[session_id]['end'] = time.time()
                        record['active'] -= 1
                    if context:
                        await context.close()

            if args.smoke:
                context = await browser.new_context()
                page = await context.new_page()
                page.on('response', inspect_response)
                for path in PATHS:
                    await navigate(page, path, 'smoke')
                    if stop.is_set():
                        break
                await context.close()
                record['completed'] = not stop.is_set()
            else:
                if time.time() > args.start + 10:
                    raise RuntimeError('Worker setup missed the synchronized start; test invalid')
                await pause(args.start - time.time())
                resource_strikes = latency_strikes = 0
                while not stop.is_set() and time.time() < args.start + TOTAL_SECONDS:
                    now = time.time()
                    target, phase_start, duration = phase_at(now - args.start)
                    desired = allocation(target, args.shard, args.shards)
                    previous = 0 if phase_start == 0 else allocation(phase_at(phase_start - .01)[0], args.shard, args.shards)
                    ramp_fraction = min(1, max(0, (now - args.start - phase_start) / 30))
                    allowed = previous + math.ceil((desired - previous) * ramp_fraction)
                    while len(tasks) < allowed and not stop.is_set():
                        tasks.append(asyncio.create_task(session(len(tasks))))
                        await pause(.15)
                    usage = resources()
                    exhausted = not usage.get('unavailable') and (usage['available_memory_fraction'] < .12 or usage['load_1m'] > usage['cpus'] * 3)
                    resource_strikes = resource_strikes + 1 if exhausted else 0
                    recent = [x.get('load_ms', 0) for x in record['navigation'][-50:]]
                    slow = len(recent) >= 40 and sorted(recent)[int((len(recent) - 1) * .95)] > 15000
                    latency_strikes = latency_strikes + 1 if slow else 0
                    record['heartbeats'].append({'at': now, 'target_global': target, 'active': record['active'], 'resource': usage})
                    save()
                    print(json.dumps({'shard': args.shard, 'target': target, 'active': record['active'], 'navigation_ok': len(record['navigation']), 'errors': len(record['errors'])}), flush=True)
                    if resource_strikes >= 3:
                        fail('load_generator_exhaustion', usage)
                    if latency_strikes >= 3:
                        fail('browser_load_p95_above_15s')
                    await pause(5)
                normal_end = not stop.is_set()
                stop.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                record['completed'] = normal_end
        except Exception as error:
            fail('generator_setup_error', {'error': type(error).__name__, 'message': str(error)[:250]})
        finally:
            save()
            await browser.close()
    return 0 if record['completed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--shards', type=int, default=20)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--output', default='results')
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards <= 20:
        parser.error('Invalid shard allocation')
    raise SystemExit(asyncio.run(run(args)))
