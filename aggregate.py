"""Merge observed browser-session intervals; never count requested VUs as measured."""
import argparse
import json
from pathlib import Path


def aggregate(records, expected=20):
    by_worker = {}
    for record in records:
        shard = record['shard']
        if shard in by_worker:
            raise ValueError('Duplicate worker results')
        by_worker[shard] = record
    events = []
    errors = []
    navigations = 0
    origins = set()
    configurations = set()
    for record in by_worker.values():
        if record.get('origin_ip'):
            origins.add(record['origin_ip'])
        configurations.add((record.get('shards'), record.get('start_epoch'), json.dumps(record.get('profile'))))
        errors.extend(record.get('errors', []))
        navigations += len(record.get('navigation', []))
        last = record.get('last_observed', 0)
        for interval in record.get('intervals', []):
            begin = interval['start']
            end = min(interval.get('end') or last, last)
            if end > begin:
                events.extend([(begin, 1), (end, -1)])
    active = peak = 0
    previous = events[0][0] if events else 0
    duration = {1000: 0, 1500: 0, 2000: 0}
    for timestamp, delta in sorted(events, key=lambda x: (x[0], x[1])):
        for target in duration:
            if active >= target:
                duration[target] += timestamp - previous
        active += delta
        peak = max(peak, active)
        previous = timestamp
    all_completed = len(by_worker) == expected and all(r.get('completed') for r in by_worker.values())
    consistent = len(configurations) == 1
    distributed = len(origins) >= 2
    qualified = all_completed and consistent and distributed and not errors
    return {'workers_expected': expected, 'workers_received': len(by_worker),
            'distinct_observed_origins': len(origins), 'origins': sorted(origins),
            'all_workers_completed': all_completed, 'consistent_profile': consistent,
            'observed_peak_active_browser_sessions': peak,
            'seconds_at_or_above': {str(k): round(v, 3) for k, v in duration.items()},
            'successful_full_navigations': navigations, 'errors': errors,
            'qualified_pass': {str(k): qualified and duration[k] >= 60 for k in duration},
            'scope': 'Real Chromium contexts with isolated cookies/storage; home, catalog and product; no orders/payments. Peak is reconstructed from overlapping observed ready-session intervals; generator failures invalidate approval.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('--expected', type=int, default=20)
    args = parser.parse_args()
    records = [json.loads(p.read_text()) for p in Path(args.directory).rglob('worker_*.json')]
    result = aggregate(records, args.expected)
    Path('distributed_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
