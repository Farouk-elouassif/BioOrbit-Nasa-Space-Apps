"""At-least-once HTTP delivery; the receiver must deduplicate stable event IDs."""
import hashlib
import json
import logging
import math
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


class DeliveryError(RuntimeError):
    pass


class Client:
    def __init__(self, url, token=None, timeout=10., retries=3, backoff=.5, single=False, sleeper=time.sleep):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Endpoint must be HTTP(S), without embedded credentials')
        if not math.isfinite(timeout) or timeout <= 0 or retries < 0 or not math.isfinite(backoff) or backoff < 0:
            raise ValueError('Invalid HTTP retry configuration')
        self.url, self.token, self.timeout = url, token, timeout
        self.retries, self.backoff, self.single, self.sleep = retries, backoff, single, sleeper
        # Destination-specific delivery state; different endpoints replay independently.
        self.destination = hashlib.sha256(url.encode()).hexdigest()

    def send(self, events):
        if self.single and len(events) != 1:
            raise ValueError('Single mode requires exactly one event')
        payload = events[0] if self.single else {'schema_version': '1.0', 'events': events}
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
                   'Idempotency-Key': hashlib.sha256('|'.join(e['event_id'] for e in events).encode()).hexdigest()}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        expected = {e['event_id'] for e in events}
        for attempt in range(self.retries + 1):
            retry_after = None
            try:
                request = urllib.request.Request(self.url, data=body, headers=headers, method='POST')
                # Do not forward credentials via redirects.
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, *args, **kwargs):
                        return None
                with urllib.request.build_opener(NoRedirect).open(request, timeout=self.timeout) as response:
                    ack = json.loads(response.read(1_000_000))
                accepted = ack.get('accepted_event_ids')
                if not isinstance(accepted, list) or set(accepted) != expected:
                    raise DeliveryError('Receiver did not acknowledge the full batch; retained for replay')
                log.info('HTTP acknowledged %d events', len(events))
                return
            except urllib.error.HTTPError as exc:
                if exc.code != 429 and not 500 <= exc.code < 600:
                    code = exc.code
                    exc.close()
                    raise DeliveryError(f'Nonretryable HTTP {code}; events retained') from None
                header = exc.headers.get('Retry-After', '')
                try:
                    retry_after = min(30., max(0., float(header)))
                except ValueError:
                    pass
                reason = f'HTTP {exc.code}'
                exc.close()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                reason = type(exc).__name__
            except (ValueError, TypeError, AttributeError) as exc:
                raise DeliveryError('Malformed acknowledgment; events retained') from exc
            if attempt == self.retries:
                raise DeliveryError(f'Delivery failed after {attempt+1} attempts ({reason}); events retained')
            delay = retry_after if retry_after is not None else min(30., self.backoff * 2 ** attempt)
            log.warning('Delivery retry %d/%d: %s', attempt+1, self.retries, reason)
            self.sleep(delay)

    def flush(self, store, batch_size=500, max_batches=None):
        if batch_size < 1:
            raise ValueError('Batch size must be positive')
        sent = batches = 0
        while max_batches is None or batches < max_batches:
            events = store.pending(self.destination, 1 if self.single else batch_size)
            if not events:
                break
            self.send(events)
            store.acknowledge(self.destination, events)
            sent += len(events); batches += 1
        return sent
