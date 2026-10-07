"""Small MAST CAOM API client; fixed HTTPS endpoints and bounded public LC scope."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import signal
import time

import requests
from urllib3.exceptions import HTTPError as TransportError

from .protocol import ValidationError, canonical_json, utc_now

INVOKE = 'https://mast.stsci.edu/api/v0/invoke'
DOWNLOAD = 'https://mast.stsci.edu/api/v0.1/Download/file'
LC_NAME = re.compile(r'tess\d{13}-s(\d{4})-(\d{16})-(\d{4})-s_lc\.fits')
METADATA_CAP = 1024**2
MAX_PRODUCT_BYTES = 64 * 1024**2


@contextmanager
def wall_deadline(seconds):
    """Linux main-thread hard deadline, including slow headers and native calls.

    Nested calls preserve the earlier outer deadline. CLI/daemon only: HTTP
    handlers never run workers or acquire this process-global alarm.
    """
    if seconds <= 0:
        raise TimeoutError('Runtime budget exhausted')
    old_handler = signal.getsignal(signal.SIGALRM)
    old_remaining, old_interval = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def timeout(signum, frame):
        raise TimeoutError('Bounded watcher/dispatcher wall-clock deadline reached')
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, old_remaining) if old_remaining else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        remaining = old_remaining - (time.monotonic()-started)
        if old_remaining and remaining > 0:
            signal.setitimer(signal.ITIMER_REAL, remaining, old_interval)
        # An exhausted outer alarm already raised TimeoutError. Do not arm a
        # second alarm that could interrupt failure-receipt cleanup.


def public_release_time(mjd):
    try:
        value = float(mjd)
        if not math.isfinite(value) or not 50000 < value < 100000:
            raise ValueError()
        date = datetime(1858,11,17,tzinfo=timezone.utc) + timedelta(days=value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError('Missing or invalid archive public-release MJD') from exc
    if date > datetime.now(timezone.utc):
        raise ValidationError('Scheduled future observation is not a public release')
    return date.isoformat(timespec='microseconds').replace('+00:00','Z')


def filename(uri):
    if not isinstance(uri, str) or not uri.startswith('mast:TESS/product/'):
        raise ValidationError('Only public MAST TESS product URIs are allowed')
    name = uri[len('mast:TESS/product/'):]
    if not LC_NAME.fullmatch(name):
        raise ValidationError('Pilot supports only standard SPOC light-curve filenames')
    return name


def public_product_url(uri):
    """Exact public STScI cloud object for a validated standard SPOC light curve."""
    name = filename(uri)
    match = LC_NAME.fullmatch(name)
    groups = '/'.join(match[2][offset:offset + 4] for offset in range(0, 16, 4))
    return 'https://stpubdata.s3.us-east-1.amazonaws.com/tess/public/tid/s' + match[1] + '/' + groups + '/' + name


def observation_request(targets):
    return {'service':'Mast.Caom.Filtered', 'format':'json', 'page':1, 'pagesize':100,
        'params': {'columns':'*', 'filters':[{'paramName':k,'values':v} for k,v in {
            'obs_collection':['TESS'], 'provenance_name':['SPOC'], 'dataproduct_type':['timeseries'],
            'target_name':targets, 'dataRights':['PUBLIC']}.items()]}}


def product_request(obsid):
    if not str(obsid).isdigit():
        raise ValidationError('Invalid MAST observation identity')
    return {'service':'Mast.Caom.Products','format':'json','page':1,'pagesize':100,'params':{'obsid':str(obsid)}}


def decode_page(raw):
    try:
        page = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError('MAST returned invalid JSON') from exc
    if not isinstance(page, dict) or page.get('status') != 'COMPLETE':
        raise OSError('MAST query incomplete: ' + str(page.get('status') if isinstance(page,dict) else 'invalid')[:100])
    rows = page.get('data')
    if not isinstance(rows,list) or len(rows)>100 or any(not isinstance(r,dict) for r in rows):
        raise ValidationError('MAST response exceeds row bound or has invalid rows')
    paging = page.get('paging', {})
    complete = (isinstance(paging,dict) and {'page','pagesFiltered','rowsFiltered'} <= set(paging)
                and int(paging['page']) == 1 and int(paging['pagesFiltered']) <= 1
                and int(paging['rowsFiltered']) <= len(rows))
    return rows, complete


def select_observations(rows, targets, maximum):
    by_target = {}
    excluded = 0
    for row in rows:
        if (row.get('obs_collection') != 'TESS' or row.get('provenance_name') != 'SPOC'
                or str(row.get('dataRights','')).upper() != 'PUBLIC' or str(row.get('target_name')) not in targets):
            excluded += 1; continue
        try:
            name = filename(row.get('dataURL'))
            match = LC_NAME.fullmatch(name)
            public_release_time(row.get('t_obs_release'))
            if str(int(match[2])) != str(row['target_name']) or int(match[1]) != int(row['sequence_number']):
                raise ValidationError('Target/sector mismatch')
            product_request(row['obsid'])
        except (ValidationError, ValueError, KeyError, TypeError):
            excluded += 1; continue
        tic = str(row['target_name'])
        order = (float(row['t_obs_release']), int(row['sequence_number']), name)
        if tic not in by_target or order > by_target[tic][0]:
            by_target[tic] = (order,row)
    # Stable explicit target order; one latest ordinary-cadence LC per target.
    chosen = [by_target[t][1] for t in targets if t in by_target][:maximum]
    return chosen, {'excluded_observations': excluded, 'eligible_targets':len(by_target),
                    'selection_truncated':len(by_target)>maximum, 'policy':'latest_public_standard_SPOC_LC_per_explicit_TIC'}


def select_product(rows, observation):
    matches = []
    for row in rows:
        if row.get('dataURI') != observation['dataURL']:
            continue
        if (row.get('obs_collection') != 'TESS' or str(row.get('dataRights','')).upper() != 'PUBLIC'
                or row.get('productSubGroupDescription') != 'LC' or row.get('productType') != 'SCIENCE'
                or str(row.get('parent_obsid')) != str(observation['obsid'])):
            continue
        name = filename(row['dataURI'])
        if row.get('productFilename') != name:
            raise ValidationError('Product filename differs from public URI')
        size = row.get('size')
        if type(size) is not int or not 0 < size <= MAX_PRODUCT_BYTES:
            raise ValidationError('Unknown/oversized product: native adapter permits at most 64 MiB')
        if not row.get('prvversion'):
            raise ValidationError('Missing product processing version')
        if row not in matches:
            matches.append(row)
    if len(matches) != 1:
        raise ValidationError('Expected exactly one unambiguous public LC product for selected observation')
    return matches[0]


class MastClient:
    def __init__(self, ledger, session=None):
        self.ledger = ledger
        self.session = session or requests.Session()
        self.session.headers.update({'User-Agent':'Thesis-Rojin-bounded-research/1', 'Accept-Encoding':'identity'})

    def _transfer(self, method, url, cap, *, pilot_id=None, path=None, redirect_url=None, read_timeout=10, **kwargs):
        key = self.ledger.reserve(cap, 'science_product' if path else 'metadata', pilot_id)
        used, chunks, complete = 0, [], False
        handle = None
        try:
            if path:
                handle = Path(path).open('xb')
            with wall_deadline(60):
                with ExitStack() as responses:
                    response = responses.enter_context(self.session.request(
                        method, url, timeout=(5,read_timeout), allow_redirects=False, stream=True, **kwargs))
                    final_url, redirects = url, []
                    if redirect_url is not None and response.status_code in (301, 302, 303, 307, 308):
                        if (method != 'GET' or url != DOWNLOAD or path is None
                                or redirect_url != public_product_url(kwargs.get('params', {}).get('uri'))
                                or response.headers.get('Location') != redirect_url):
                            raise ValidationError('MAST redirect does not match the selected public cloud product')
                        if (response.headers.get('Content-Length') != '0'
                                or response.headers.get('Content-Encoding', 'identity').lower() not in ('identity', '')
                                or response.headers.get('Transfer-Encoding')):
                            raise ValidationError('MAST download redirect must have an explicitly empty body')
                        redirects.append({'url': url, 'status': response.status_code, 'location': redirect_url})
                        final_url = redirect_url
                        response = responses.enter_context(self.session.request(
                            'GET', final_url, timeout=(5,10), allow_redirects=False, stream=True))
                    if response.status_code != 200:
                        raise OSError('MAST HTTP ' + str(response.status_code))
                    if response.headers.get('Content-Encoding','identity').lower() not in ('identity',''):
                        raise ValidationError('Compressed network responses are unsupported for exact byte accounting')
                    length = response.headers.get('Content-Length')
                    if length is not None and (not length.isdigit() or int(length)>cap):
                        raise ValidationError('Response exceeds reserved byte cap')
                    sha = hashlib.sha256()
                    # raw.read avoids requesting a chunk beyond remaining allowance.
                    while used < cap:
                        chunk = response.raw.read(min(65536, cap-used), decode_content=False)
                        if not chunk:
                            break
                        used += len(chunk)
                        sha.update(chunk)
                        if handle:
                            handle.write(chunk)
                        else:
                            chunks.append(chunk)
                    if length is not None and used != int(length):
                        raise OSError('Truncated MAST response')
                    if used == cap and length is None:
                        raise ValidationError('Unframed response filled entire cap; completeness unverified')
                    if path and used != cap:
                        raise ValidationError('Product bytes differ from immutable MAST size')
                    receipt = {'url':final_url,'requested_url':url,'redirects':redirects,
                        'retrieved_at':utc_now(),'bytes':used,'sha256':sha.hexdigest(),
                        'etag':response.headers.get('ETag'), 'last_modified':response.headers.get('Last-Modified'),
                        'content_length':int(length) if length else None,'spending_id':key}
                    complete = True
            return (receipt if path else (b''.join(chunks),receipt))
        except TransportError as exc:
            raise OSError('MAST transport failed: ' + str(exc)) from exc
        finally:
            if handle:
                handle.flush()
                import os
                os.fsync(handle.fileno())
                handle.close()
            # For interrupted/failed transport use the entire reservation. Bytes in
            # socket buffers or an interrupted raw.read cannot be measured exactly.
            self.ledger.settle(key, used if complete else cap,
                receipt if complete else {'known_read_bytes':used,'failure_charge':'full_reserved_cap'},
                'complete' if complete else 'failed_conservative')

    def query(self, request):
        # A bounded archive-wide metadata sample can take longer to prepare than
        # a lookup of explicit TICs. The enclosing 60-second wall deadline stays.
        filters = request.get('params', {}).get('filters', [])
        broad = request.get('service') == 'Mast.Caom.Filtered' and not any(
            item.get('paramName') == 'target_name' for item in filters)
        raw, receipt = self._transfer('POST', INVOKE, METADATA_CAP, read_timeout=45 if broad else 10,
                                     data={'request':canonical_json(request)})
        return raw

    def download(self, product, path, pilot_id):
        filename(product['source_uri'])
        size = product['metadata']['size_bytes']
        receipt = self._transfer('GET', DOWNLOAD, size, pilot_id=pilot_id, path=path,
                                 params={'uri':product['source_uri']}, redirect_url=public_product_url(product['source_uri']))
        if receipt['bytes'] != size:
            raise ValidationError('Product bytes differ from immutable MAST size')
        receipt['source_uri'] = product['source_uri']
        return receipt
