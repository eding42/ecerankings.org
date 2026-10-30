#!/usr/bin/env python3
"""Stage current conference works in an isolated cache without touching repo cache.

This is a review/refresh utility: it reads the venue registry, checks currently
registered conference editions against their declared OpenAlex source or
Crossref container/DOI scope, enriches Crossref records by DOI when affordable,
and only publishes complete validated edition files into --output.
"""
from __future__ import annotations
import argparse, hashlib, html, json, os, re, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = ROOT/'.tmp/refresh-2026-10-28/conferences'
API_OA = 'https://api.openalex.org'
API_CR = 'https://api.crossref.org'
MAILTO = 'eding2019@gmail.com'
OA_LIMIT_DEFAULT = 3000
BATCH = 100
DOI_PREFIX = re.compile(r'^https?://(?:dx\.)?doi\.org/', re.I)

class RefreshError(RuntimeError): pass


def norm_doi(value):
    if not value: return None
    d = DOI_PREFIX.sub('', str(value).strip()).lower()
    return d or None


def decode_crossref_text(value):
    if not isinstance(value,str): return value
    decoded=value
    for _ in range(3):
        newer=html.unescape(decoded)
        if newer==decoded: break
        decoded=newer
    return decoded.strip()


def usable_affiliation(authorship):
    return bool(authorship.get('institutions') or authorship.get('raw_affiliations') or authorship.get('raw_affiliation_strings'))


def coverage(work):
    authors = work.get('authorships') or []
    return sum(bool(usable_affiliation(a)) for a in authors), len(authors)


def trim_oa(w):
    authorships=[]
    for a in w.get('authorships') or []:
        author=a.get('author') or {}
        insts=[]
        for i in a.get('institutions') or []:
            insts.append({k:i.get(k) for k in ('id','display_name','country_code','type','lineage')})
        authorships.append({'author_id':author.get('id'),'author_name':author.get('display_name'),
                            'institutions':insts,'raw_affiliations':a.get('raw_affiliation_strings') or []})
    return {'id':w.get('id'),'doi':w.get('doi'),'title':w.get('title'),
            'publication_year':w.get('publication_year'),'type':w.get('type'),
            'source':'openalex','authorships':authorships}


def oa_key():
    # Do not print or place the credential in a URL. OpenAlex accepts Bearer auth.
    path=ROOT/'.env'
    if not path.exists(): return None
    for line in path.read_text().splitlines():
        if line.startswith('OPENALEX_API_KEY='):
            return line.split('=',1)[1].strip() or None
    return None


def request_json(url, headers=None, timeout=90, attempts=5, on_request=None):
    for n in range(attempts):
        try:
            if on_request: on_request()
            req=urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429,500,502,503,504) or n == attempts-1: raise
            ra=e.headers.get('Retry-After') if e.headers else None
            time.sleep(min(120,float(ra)) if ra else 2**n)
        except (urllib.error.URLError,TimeoutError, OSError, json.JSONDecodeError):
            if n == attempts-1: raise
            time.sleep(2**n)


def oa_page(url, key, state, timeout=90, attempts=5):
    hdr={'User-Agent':f'ecerankings-refresh (mailto:{MAILTO})'}
    if key: hdr['Authorization']='Bearer '+key
    def counted():
        if state['oa_calls'] >= state['oa_limit']:
            raise RefreshError('OpenAlex list-call budget exhausted')
        time.sleep(0.11)  # keep below the documented 10 requests/second rate
        state['oa_calls'] += 1
    return request_json(url,hdr,timeout=timeout,attempts=attempts,on_request=counted)


def crossref_page(params, state):
    params=dict(params); params['mailto']=MAILTO
    url=API_CR+'/works?'+urllib.parse.urlencode(params, safe=':,|*')
    def counted():
        time.sleep(0.3)
        state['crossref_calls']+=1
    return request_json(url, {'User-Agent':f'ecerankings-refresh (mailto:{MAILTO})'},on_request=counted)


def normalize_name(name):
    return re.sub(r'[^a-z0-9]+',' ',decode_crossref_text(name or '').lower()).strip()


def normalize_container(title):
    return re.sub(r'[^a-z0-9]+',' ',(title or '').lower()).strip()


def container_matches_scope(candidate, registered):
    """Match exact titles, plus numbered volumes in a registered proceedings family."""
    c=normalize_container(candidate); r=normalize_container(registered)
    if c==r: return True
    vol_re=r'\s+(?:volume|vol)\s+[0-9]+$'
    if not re.search(vol_re,r): return False
    return bool(re.search(vol_re,c) and re.sub(vol_re,'',c).strip()==re.sub(vol_re,'',r).strip())


def enrich_crossref(works, call_state, key):
    """Batch DOI lookups, paging duplicate records and tolerating auxiliary failures."""
    by_doi={norm_doi(w.get('doi')):w for w in works if norm_doi(w.get('doi'))}
    dois=list(by_doi)
    call_state.setdefault('enrichment_partial_batches',[])
    call_state.setdefault('hydration_attempts',0)
    call_state.setdefault('hydration_successes',0)
    for off in range(0,len(dois),BATCH):
        if call_state['oa_calls'] >= call_state['oa_limit']:
            call_state['enrichment_budget_exhausted']=True
            call_state['enrichment_partial_batches'].append({'offset':off,'reason':'OpenAlex list-call budget exhausted'})
            break
        chunk=dois[off:off+BATCH]
        filt='doi:'+'|'.join(chunk)
        cursor='*'; seen_cursors=set(); candidates=Counter(); best={}
        try:
            while cursor:
                if cursor in seen_cursors: raise RefreshError('OpenAlex duplicate-DOI lookup repeated cursor')
                seen_cursors.add(cursor)
                url=API_OA+'/works?'+urllib.parse.urlencode({'filter':filt,'select':'doi,id,authorships','per-page':str(BATCH),'cursor':cursor,'mailto':MAILTO},safe=':,|*')
                payload=oa_page(url,key,call_state,timeout=30,attempts=1)
                for rec in payload.get('results') or []:
                    d=norm_doi(rec.get('doi'))
                    target=by_doi.get(d)
                    if not target: continue
                    oa=trim_oa(rec)
                    ta=target.get('authorships') or []; aa=oa.get('authorships') or []
                    target_names=[normalize_name(a.get('author_name')) for a in ta]
                    oa_names=[normalize_name(a.get('author_name')) for a in aa]
                    aligned=bool(ta) and target_names == oa_names
                    quality=(int(aligned),coverage(oa)[0],len(aa),int(bool(oa.get('id'))))
                    candidates[d]+=1
                    if d not in best or quality>best[d][0]: best[d]=(quality,oa,aligned)
                nxt=(payload.get('meta') or {}).get('next_cursor')
                count=(payload.get('meta') or {}).get('count')
                seen_records=sum(candidates.values())
                if seen_records < (count or 0) and not nxt:
                    raise RefreshError('OpenAlex duplicate-DOI lookup omitted continuation cursor')
                cursor=nxt
        except Exception as e:
            call_state['enrichment_partial_batches'].append({'offset':off,'doi_count':len(chunk),'error':f'{type(e).__name__}: {e}'})
        for d,(_,oa,aligned) in best.items():
            target=by_doi[d]
            if not aligned: continue
            ta=target.get('authorships') or []; aa=oa.get('authorships') or []
            target_names=[normalize_name(a.get('author_name')) for a in ta]
            oa_names=[normalize_name(a.get('author_name')) for a in aa]
            if target_names != oa_names: continue
            before=coverage(target); after=coverage(oa)
            if after[0] < before[0] or (before[1] and after[1] != before[1]): continue
            target['openalex_id']=oa.get('id')
            target['openalex_enrichment']={'matched_authors':len(ta),'coverage_before':before[0], 'coverage_after':after[0], 'duplicate_records_seen':candidates[d]}
            target['authorships']=[{**old,'author_id':new.get('author_id') or old.get('author_id'),
                                    'institutions':new.get('institutions') or old.get('institutions') or [],
                                    'raw_affiliations':old.get('raw_affiliations') or new.get('raw_affiliations') or []}
                                   for old,new in zip(ta,aa)]
    return works


def hydrate_truncated_openalex(works, call_state, key):
    """Hydrate native OpenAlex records with 100+ list authorships if possible."""
    call_state.setdefault('hydration_attempts',0)
    call_state.setdefault('hydration_successes',0)
    for w in works:
        if w.get('source')!='openalex' or len(w.get('authorships') or [])<100 or not w.get('id'):
            continue
        call_state['hydration_attempts']+=1
        wid=w['id'].rsplit('/',1)[-1]
        url=API_OA+'/works/'+urllib.parse.quote(wid,safe='')+'?'+urllib.parse.urlencode({'mailto':MAILTO})
        try:
            hdr={'User-Agent':f'ecerankings-refresh (mailto:{MAILTO})'}
            if key: hdr['Authorization']='Bearer '+key
            full=request_json(url,hdr)
            if full.get('id')!=w.get('id') or norm_doi(full.get('doi'))!=norm_doi(w.get('doi')):
                continue
            hydrated=trim_oa(full).get('authorships') or []
            if len(hydrated)>len(w['authorships']):
                w['authorships']=hydrated
                w['openalex_hydrated_authorships']=len(hydrated)
                call_state['hydration_successes']+=1
        except Exception:
            continue
    return works


def crossref_to_work(item, year):
    authors=[]
    for a in item.get('author') or []:
        raw=[]
        for aff in a.get('affiliation') or []:
            name=aff.get('name')
            if name:
                decoded=decode_crossref_text(name)
                raw.append(decoded)
        given=a.get('given') or ''; family=a.get('family') or ''
        original_full=' '.join(x for x in (given,family) if x).strip()
        full=decode_crossref_text(original_full)
        slug=re.sub(r'[^a-z0-9]+','-',full.lower()).strip('-') or 'unknown'
        author={'author_id':'crossref:name:'+slug,'author_name':full or None,'institutions':[], 'raw_affiliations':raw}
        if original_full!=full: author['provider_raw_author_name']=original_full
        original_aff=[aff.get('name') for aff in a.get('affiliation') or [] if aff.get('name')]
        if original_aff!=raw: author['provider_raw_affiliations']=original_aff
        authors.append(author)
    doi=norm_doi(item.get('DOI'))
    titles=item.get('title') or []
    issued=(item.get('issued') or {}).get('date-parts') or [[None]]
    title_original=titles[0] if titles else None
    title=decode_crossref_text(title_original) if title_original else None
    work={'id':None,'doi':'https://doi.org/'+doi if doi else None,'title':title,
            'publication_year':year,'crossref_issued_year':issued[0][0] if issued and issued[0] else None,
            'type':item.get('type'),'source':'crossref','authorships':authors}
    if title_original is not None and title_original!=title: work['provider_raw_title']=title_original
    return work


def api_works(venue_key, year, entry, venue, key, state, raw_cache_root=None):
    raw_cache_root=Path(raw_cache_root) if raw_cache_root else STAGING_ROOT/'raw-crossref'
    if entry.get('source')=='openalex':
        sid=entry.get('id')
        if not sid: raise RefreshError(f'{venue_key}/{year}: OpenAlex entry missing source id')
        sid=sid.rsplit('/',1)[-1]
        filt=f'primary_location.source.id:{sid},type:!paratext'
        # Year is always part of the predicate. Some nominally edition-specific
        # source IDs carry records with publication-year metadata from other years.
        filt+=f',publication_year:{year}'
        cursor='*'; seen_cursors=set(); works=[]; seen_dois=set(); seen_fingerprints=set(); count_expected=None
        while cursor:
            if cursor in seen_cursors: raise RefreshError('OpenAlex repeated cursor')
            seen_cursors.add(cursor)
            if state['oa_calls']>=state['oa_limit']: raise RefreshError('OpenAlex call budget exhausted before source completed')
            params={'filter':filt,'select':'id,doi,title,publication_year,type,authorships','per-page':'100','cursor':cursor,'mailto':MAILTO}
            url=API_OA+'/works?'+urllib.parse.urlencode(params,safe=':,|*')
            payload=oa_page(url,key,state)
            meta=payload.get('meta') or {}; count_expected=meta.get('count',count_expected)
            results=payload.get('results') or []
            for row in results:
                w=trim_oa(row)
                if int(w.get('publication_year') or 0)!=int(year): raise RefreshError('OpenAlex result has wrong publication year')
                d=norm_doi(w.get('doi'))
                fp=d or ((w.get('title') or '').lower(),len(w['authorships']))
                if (d and d in seen_dois) or fp in seen_fingerprints: raise RefreshError('OpenAlex repeated work')
                if d: seen_dois.add(d)
                seen_fingerprints.add(fp); works.append(w)
            nxt=(payload.get('meta') or {}).get('next_cursor')
            if results and not nxt and len(works) != count_expected:
                raise RefreshError('OpenAlex page omitted continuation cursor before advertised count')
            if not results and nxt: raise RefreshError('OpenAlex returned empty page with continuation cursor')
            cursor=nxt
        if count_expected is not None and len(works)!=count_expected: raise RefreshError(f'OpenAlex count mismatch: got {len(works)} expected {count_expected}')
        # VLSI Tech 2021 is a mixed multi-decade source: year-filter is mandatory, then validate.
        if venue_key=='vlsi-tech' and year==2021 and len(works)!=79: raise RefreshError(f'VLSI Tech 2021 expected 79, got {len(works)}')
        return works, {'provider':'openalex','expected_count':count_expected,'api_count':len(works)}
    if entry.get('source')!='crossref': return [], {'provider':entry.get('source'),'expected_count':0,'api_count':0,'status':'no-source'}
    prefix=entry.get('doi_prefix'); explicit=entry.get('dois')
    if explicit:
        dois=list(explicit); works=[]
        for doi in dois:
            item=crossref_page({'filter':'doi:'+doi,'rows':'1'},state)['message']['items']
            matches=[x for x in item if norm_doi(x.get('DOI'))==norm_doi(doi)]
            if len(matches)!=1: raise RefreshError(f'{venue_key}/{year}: DOI singleton lookup mismatch for {doi}')
            works.append(crossref_to_work(matches[0],year))
        expected=len(dois)
    else:
        if not prefix or not entry.get('container_title'): raise RefreshError(f'{venue_key}/{year}: missing precise DOI/container metadata')
        prefixes=[p.strip().lower() for p in prefix.split(',')]
        title=entry['container_title']
        normalized_title=normalize_container(title)
        if ',' in title:
            # Crossref filter values use commas to delimit filter pairs, so a
            # comma-bearing exact container cannot be represented in filter=.
            # Constrain the fuzzy field search by owner prefix, work type, and
            # edition date, then enforce exact normalized title and registered
            # DOI-prefix membership locally on every returned record.
            owner_prefixes={p.split('/',1)[0] for p in prefixes}
            if len(owner_prefixes)!=1: raise RefreshError('comma-title query has multiple DOI owner prefixes')
            query_name=re.sub(r'\s*\([^)]*\)\s*',' ',title).strip()
            acronym_match=re.search(r'\(([^)]+)\)',title)
            query_term=acronym_match.group(1) if acronym_match else query_name
            filter_str=f"prefix:{next(iter(owner_prefixes))},from-pub-date:{year}-01-01,until-pub-date:{year}-12-31,type:proceedings-article"
            works=[]; cursor='*'; seen_cursors=set(); raw_count=0; raw_expected=None; accepted_dois=set(); page_number=0
            raw_cache_dir=raw_cache_root/venue_key/str(year)
            while cursor:
                if cursor in seen_cursors: raise RefreshError('Crossref fuzzy query repeated cursor')
                seen_cursors.add(cursor)
                msg=crossref_page({'filter':filter_str,'query.container-title':query_term,
                                   'rows':'500','cursor':cursor,
                                   'select':'DOI,title,author,issued,type,container-title'},state)['message']
                advertised=msg.get('total-results')
                if raw_expected is None: raw_expected=advertised
                elif advertised!=raw_expected: raise RefreshError('Crossref fuzzy advertised total changed during pagination')
                items=msg.get('items') or []
                if not items and cursor and raw_count < (raw_expected or 0):
                    raise RefreshError('Crossref fuzzy pagination ended before advertised total-results')
                page_number+=1
                if items and venue_key in ('asplos','icassp','sigcomm'):
                    write_atomic(raw_cache_dir/f'page-{page_number:05d}.jsonl',items)
                raw_count+=len(items)
                for item in items:
                    doi=norm_doi(item.get('DOI'))
                    if not any(container_matches_scope(x,title) for x in item.get('container-title') or []): continue
                    if not doi or not any(doi.startswith(p) for p in prefixes): continue
                    if doi in accepted_dois: raise RefreshError('Crossref repeated accepted DOI')
                    accepted_dois.add(doi); works.append(crossref_to_work(item,year))
                nxt=msg.get('next-cursor')
                if items and not nxt and raw_count < (raw_expected or 0):
                    raise RefreshError('Crossref fuzzy page omitted continuation cursor before advertised result count')
                cursor=nxt
            if raw_expected is not None and raw_count!=raw_expected:
                raise RefreshError(f'Crossref fuzzy raw pagination count mismatch: got {raw_count}, expected {raw_expected}')
            for w in works:
                d=norm_doi(w.get('doi'))
                if not d or not any(d.startswith(p) for p in prefixes): raise RefreshError('Crossref fuzzy DOI outside registered prefix')
            if entry.get('dois') and accepted_dois!={norm_doi(x) for x in entry['dois']}:
                raise RefreshError('Crossref fuzzy explicit DOI membership mismatch')
            return works, {'provider':'crossref','expected_count':entry.get('count') if entry.get('count') is not None else len(works),
                           'api_count':len(works),'api_raw_count':raw_count,'api_advertised_raw_count':raw_expected,
                           'api_rejected_raw_count':raw_count-len(works),'registered_count':entry.get('count'),
                           'query_mode':'fuzzy-container-title+owner-prefix+type+date','api_raw_pages':page_number,
                           'api_raw_page_cache':str(raw_cache_dir)}
        filter_str=f'container-title:{entry["container_title"]},from-pub-date:{year}-01-01,until-pub-date:{year}-12-31,type:proceedings-article'
        works=[]; cursor='*'; seen_cursors=set(); expected=None; raw_count=0; page_number=0
        accepted={}; duplicate_rows=0; rejected_rows=0
        raw_cache_dir=raw_cache_root/venue_key/str(year)
        while cursor:
            if cursor in seen_cursors: raise RefreshError('Crossref exact query repeated cursor')
            seen_cursors.add(cursor)
            msg=crossref_page({'filter':filter_str,'rows':'500','cursor':cursor,
                               'select':'DOI,title,author,issued,type,container-title'},state)['message']
            advertised=msg.get('total-results')
            if expected is None: expected=advertised
            elif advertised!=expected: raise RefreshError('Crossref advertised total changed during cursor pagination')
            items=msg.get('items') or []
            page_number+=1
            if items and venue_key in ('cvpr','iccv','icra'):
                write_atomic(raw_cache_dir/f'page-{page_number:05d}.jsonl',items)
            raw_count+=len(items)
            if expected is not None and raw_count>expected:
                raise RefreshError(f'Crossref cursor exceeded advertised raw count: {raw_count}>{expected}')
            for item in items:
                doi=norm_doi(item.get('DOI'))
                containers=[normalize_container(x) for x in item.get('container-title') or []]
                if normalize_container(entry['container_title']) not in containers:
                    raise RefreshError('Crossref exact-container query returned a differently titled record')
                if not doi or not any(doi.startswith(p) for p in prefixes):
                    rejected_rows+=1; continue
                signature=json.dumps(item,sort_keys=True,ensure_ascii=False,separators=(',',':'))
                if doi in accepted:
                    if accepted[doi][0]!=signature:
                        raise RefreshError(f'Crossref conflicting duplicate DOI: {doi}')
                    duplicate_rows+=1
                    continue
                accepted[doi]=(signature,crossref_to_work(item,year))
            nxt=msg.get('next-cursor')
            if expected is not None and raw_count==expected:
                cursor=None
            elif not items:
                raise RefreshError(f'Crossref cursor ended before advertised raw count: {raw_count}<{expected}')
            elif not nxt:
                raise RefreshError('Crossref exact page omitted next-cursor before advertised raw count')
            else:
                cursor=nxt
        if expected is not None and raw_count!=expected:
            raise RefreshError(f'Crossref raw pagination count mismatch: got {raw_count}, expected {expected}')
        works=[row[1] for row in accepted.values()]
        if raw_count!=len(works)+duplicate_rows+rejected_rows:
            raise RefreshError('Crossref raw rows do not reconcile to accepted, duplicate, and rejected records')
        expected_prefix=len(works)
    for w in works:
        d=norm_doi(w.get('doi'))
        if not d or (prefix and not any(d.startswith(p.strip().lower()) for p in prefix.split(','))): raise RefreshError('Crossref DOI outside registered prefix')
    if explicit and len(works)!=expected: raise RefreshError('Crossref explicit DOI count mismatch')
    meta={'provider':'crossref','expected_count':entry.get('count') if entry.get('count') is not None else len(works),
          'api_count':len(works),'registered_count':entry.get('count')}
    if entry.get('source')=='crossref' and not explicit:
        meta.update({'api_raw_count':expected,'api_advertised_raw_count':expected,'api_rejected_raw_count':rejected_rows,
                     'api_duplicate_raw_count':duplicate_rows,'api_raw_pages':page_number,
                     'api_raw_page_cache':str(raw_cache_dir),'query_mode':'exact-container+cursor'})
    return works,meta


def checksum(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()


def load_cached_edition(path, venue_key, year, entry):
    """Accept an interrupted-run cache file only when every row validates."""
    try:
        # JSON Lines records end at LF only. str.splitlines() also splits on
        # U+2028/U+2029, which can legally occur inside publisher text.
        works=[json.loads(line) for line in path.read_text().split('\n') if line.strip()]
        if not works: return None
        seen=set()
        for w in works:
            if int(w.get('publication_year') or 0)!=int(year): return None
            d=norm_doi(w.get('doi'))
            if d:
                if d in seen: return None
                seen.add(d)
            if entry.get('source')=='crossref':
                prefixes=[p.strip().lower() for p in (entry.get('doi_prefix') or '').split(',') if p.strip()]
                explicit={norm_doi(x) for x in (entry.get('dois') or [])}
                if not d or (explicit and d not in explicit) or (prefixes and not any(d.startswith(p) for p in prefixes)):
                    return None
                if w.get('source')!='crossref': return None
            elif w.get('source')!='openalex':
                return None
        if entry.get('source')=='crossref' and entry.get('dois') and seen!={norm_doi(x) for x in entry['dois']}:
            return None
        return works
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        return None


def read_works(path):
    try: return [json.loads(line) for line in path.read_text().split('\n') if line.strip()]
    except (OSError,ValueError,TypeError,json.JSONDecodeError): return []


def baseline_summary(venue_key, year, baseline_cache_root=None):
    p=(Path(baseline_cache_root) if baseline_cache_root else ROOT/'.tmp/refresh-2026-10-28/baseline/cache')/venue_key/str(year)/'works.jsonl'
    works=read_works(p)
    if not works: return {'present':p.exists(),'works':None,'affiliation_slots':None,'authorship_slots':None}
    aff=sum(coverage(w)[0] for w in works); authors=sum(coverage(w)[1] for w in works)
    return {'present':True,'works':len(works),'affiliation_slots':aff,'authorship_slots':authors,
            'affiliation_coverage_pct':round(100*aff/max(1,authors),2)}


def preserve_aligned_baseline_enrichment(works, venue_key, year, baseline_cache_root=None):
    """Carry forward only per-paper metadata with an exact DOI/byline match."""
    baseline=read_works((Path(baseline_cache_root) if baseline_cache_root else ROOT/'.tmp/refresh-2026-10-28/baseline/cache')/venue_key/str(year)/'works.jsonl')
    old_by_doi={norm_doi(w.get('doi')):w for w in baseline if norm_doi(w.get('doi'))}
    counts=Counter();
    for work in works:
        old=old_by_doi.get(norm_doi(work.get('doi')))
        if not old: continue
        current_auth=work.get('authorships') or []; old_auth=old.get('authorships') or []
        current_names=[normalize_name(a.get('author_name')) for a in current_auth]
        old_names=[normalize_name(a.get('author_name')) for a in old_auth]
        if not current_names or current_names!=old_names or any(not x for x in current_names): continue
        counts['baseline_doi_byline_matches']+=1
        for current,previous in zip(current_auth,old_auth):
            counts['aligned_authorships']+=1
            if not current.get('institutions') and previous.get('institutions'):
                current['institutions']=previous['institutions']; counts['institutions_preserved']+=1
            prior_id=previous.get('author_id')
            if prior_id and prior_id.startswith('http') and (current.get('author_id') or '').startswith('crossref:'):
                current['author_id']=prior_id; counts['openalex_author_ids_preserved']+=1
            prior_raw=previous.get('raw_affiliations') or previous.get('raw_affiliation_strings') or []
            if prior_raw and not (current.get('raw_affiliations') or current.get('raw_affiliation_strings')):
                current['raw_affiliations']=prior_raw; counts['raw_affiliations_fallback']+=len(prior_raw)
    return dict(counts)


def decode_crossref_work(work):
    """Decode Crossref HTML entities while retaining changed provider text."""
    stats={'titles':0,'author_names':0,'affiliation_strings':0,'author_ids':0}
    title=work.get('title')
    if isinstance(title,str):
        decoded=decode_crossref_text(title)
        if decoded!=title:
            work.setdefault('provider_raw_title',title); work['title']=decoded; stats['titles']+=1
    for author in work.get('authorships') or []:
        name=author.get('author_name')
        if isinstance(name,str):
            decoded=decode_crossref_text(name)
            if decoded!=name:
                author.setdefault('provider_raw_author_name',name); author['author_name']=decoded; stats['author_names']+=1
            if author.get('author_id','').startswith('crossref:name:'):
                slug=re.sub(r'[^a-z0-9]+','-',decoded.lower()).strip('-') or 'unknown'
                author_id='crossref:name:'+slug
                if author['author_id']!=author_id:
                    author.setdefault('provider_raw_author_id',author['author_id'])
                    author['author_id']=author_id; stats['author_ids']+=1
        raw=author.get('raw_affiliations') or []
        decoded_raw=[decode_crossref_text(x) for x in raw]
        if decoded_raw!=raw:
            author.setdefault('provider_raw_affiliations',raw)
            author['raw_affiliations']=decoded_raw; stats['affiliation_strings']+=sum(a!=b for a,b in zip(raw,decoded_raw))
    return stats


def crossref_decode_provenance(works):
    stats=Counter()
    for work in works:
        if work.get('provider_raw_title') is not None: stats['titles']+=1
        for author in work.get('authorships') or []:
            if author.get('provider_raw_author_name') is not None: stats['author_names']+=1
            if author.get('provider_raw_author_id') is not None: stats['author_ids']+=1
            provider=author.get('provider_raw_affiliations')
            if provider is not None:
                current=author.get('raw_affiliations') or []
                stats['affiliation_strings']+=sum(a!=b for a,b in zip(provider,current))
    return stats


def postprocess_completed_crossref_manifest(manifest_path, cache_root=None):
    """Decode existing completed Crossref cache entries and checkpoint each hash."""
    mp=Path(manifest_path); report=json.loads(mp.read_text()); root=Path(cache_root or STAGING_ROOT/'cache').resolve()
    aggregate=Counter(); files=0; records=0
    for row in report.get('results',[]):
        if row.get('status')!='complete' or row.get('provider')!='crossref' or not row.get('path'):
            continue
        path=Path(row['path']).resolve()
        if not path.is_relative_to(root): continue
        works=read_works(path)
        if not works: continue
        stats=Counter()
        for work in works: stats.update(decode_crossref_work(work))
        if sum(stats.values()): write_atomic(path,works)
        row['checksum_sha256']=checksum(path)
        provenance=crossref_decode_provenance(works)
        row['crossref_entity_decode']=dict(provenance)
        aggregate.update(provenance); files+=1; records+=len(works)
        report['crossref_decode_postpass']={'files_processed':files,'works_processed':records,'changes':dict(aggregate)}
        tmp=mp.with_suffix(mp.suffix+'.tmp'); tmp.write_text(json.dumps(report,indent=2)+'\n'); os.replace(tmp,mp)
    report['crossref_decode_postpass']={'files_processed':files,'works_processed':records,'changes':dict(aggregate)}
    tmp=mp.with_suffix(mp.suffix+'.tmp'); tmp.write_text(json.dumps(report,indent=2)+'\n'); os.replace(tmp,mp)
    return report['crossref_decode_postpass']


def write_atomic(path, works):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.refresh-',dir=path.parent,text=True)
    try:
        with os.fdopen(fd,'w') as f:
            for w in works: f.write(json.dumps(w,ensure_ascii=False,separators=(',',':'))+'\n')
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def conferences(registry, years):
    for area_key,area in registry['areas'].items():
        for venue in area.get('venues',[]):
            if venue.get('kind')!='conference': continue
            key=venue['key']
            if key in ('neurips','icml','iclr'): continue # ML excluded pending source-level validation
            for y,entry in (venue.get('years') or {}).items():
                yi=int(y)
                if years[0]<=yi<=years[1] and entry.get('source') in ('openalex','crossref'):
                    yield area_key,key,venue,yi,entry


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',default=str(STAGING_ROOT/'cache'))
    ap.add_argument('--baseline-cache',default=str(ROOT/'.tmp/refresh-2026-10-28/baseline/cache'))
    ap.add_argument('--raw-cache',default=str(STAGING_ROOT/'raw-crossref'))
    ap.add_argument('--report',default='data/refresh/conference-works-2026-10-28.json')
    ap.add_argument('--years',nargs=2,type=int,default=(2016,2026))
    ap.add_argument('--oa-call-limit',type=int,default=OA_LIMIT_DEFAULT)
    ap.add_argument('--venue',action='append')
    ap.add_argument('--no-enrich',action='store_true')
    ap.add_argument('--resume-report', help='Reuse previously complete edition files whose checksums match this report')
    args=ap.parse_args(argv)
    if args.oa_call_limit<0 or args.oa_call_limit>OA_LIMIT_DEFAULT: ap.error(f'OpenAlex call cap cannot exceed {OA_LIMIT_DEFAULT}')
    reg=json.load(open(ROOT/'data/areas.json')); key=oa_key(); state={'oa_calls':0,'oa_limit':args.oa_call_limit,'crossref_calls':0}
    previous={}; prior_oa_calls=prior_crossref_calls=0
    previous_rows=[]
    if args.resume_report:
        prev=json.load(open(args.resume_report))
        prior_oa_calls=prev.get('openalex_list_calls',0); prior_crossref_calls=prev.get('crossref_http_attempts',0)
        previous_rows=prev.get('results',[])
        previous={(r.get('venue'),int(r.get('year',0))):r for r in prev.get('results',[]) if r.get('status')=='complete'}
    conference_keys={v['key'] for a in reg['areas'].values() for v in a.get('venues',[]) if v.get('kind')=='conference'}
    extra_scope=[r for r in previous_rows if r.get('venue') not in conference_keys]
    rows=[]; blocked=[]
    rp=Path(args.report)
    def checkpoint():
        """Persist each validated/blocked edition so an interrupted run resumes cleanly."""
        snap={'schema_version':1,'generated_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'years':list(args.years),'output_cache':args.output,'openalex_call_limit':args.oa_call_limit,
              'openalex_list_calls':prior_oa_calls+state['oa_calls'],'openalex_calls_prior_run':prior_oa_calls,
              'openalex_calls_current_run':state['oa_calls'],'crossref_http_attempts':prior_crossref_calls+state['crossref_calls'],
              'crossref_attempts_prior_run':prior_crossref_calls,'crossref_attempts_current_run':state['crossref_calls'],
              'enrichment_budget_exhausted':state.get('enrichment_budget_exhausted',False),
              'enrichment_partial_batches':state.get('enrichment_partial_batches',[]),
              'large_authorship_hydration':{'attempts':state.get('hydration_attempts',0),'successes':state.get('hydration_successes',0)},
              'unexpected_extra_scope':{'description':'Non-conference venue-years fetched by the initial run due to a filter bug; their scratch directories were removed before resuming. Their incurred calls remain included above.',
                  'venue_year_rows':len(extra_scope),'venues':sorted({r.get('venue') for r in extra_scope})},
              'results':rows,'blocked_count':sum(r.get('status')=='blocked' for r in rows)}
        for r in rows:
            if r.get('status')!='complete': continue
            r['baseline_comparison']=baseline_summary(r['venue'],r['year'],args.baseline_cache)
            r['unhydrated_100plus_works']=sum(1 for w in read_works(Path(r['path']))
                                               if w.get('source')=='openalex' and len(w.get('authorships') or [])>=100)
        snap['large_authorship_hydration']['unhydrated_native_works']=sum(r.get('unhydrated_100plus_works',0) for r in rows if r.get('status')=='complete')
        rp.parent.mkdir(parents=True,exist_ok=True); tmp=rp.with_suffix(rp.suffix+'.tmp')
        tmp.write_text(json.dumps(snap,indent=2)+'\n'); os.replace(tmp,rp)
    for area,vkey,venue,year,entry in conferences(reg,args.years):
        if args.venue and vkey not in args.venue: continue
        item={'area':area,'venue':vkey,'year':year,'provider':entry.get('source'),'status':'incomplete'}
        out=Path(args.output)/vkey/str(year)/'works.jsonl'
        prior=previous.get((vkey,year))
        if prior:
            old_path=Path(prior.get('path',''))
            if old_path.is_file() and checksum(old_path)==prior.get('checksum_sha256'):
                rows.append({**prior,'reused_previous_output':True})
                checkpoint()
                continue
        cached=load_cached_edition(out,vkey,year,entry) if out.is_file() else None
        if cached is not None:
            if entry.get('source')=='openalex': cached=hydrate_truncated_openalex(cached,state,key)
            item.update({'provider':entry.get('source'),'expected_count':len(cached),'api_count':len(cached),
                         'registered_count':entry.get('count'),'reused_interrupted_cache':True,
                         'registered_count_delta':len(cached)-entry['count'] if entry.get('count') is not None else None})
            if entry.get('source')=='crossref':
                item.update({'affiliation_slots_before':sum(coverage(w)[0] for w in cached),
                             'affiliation_slots_after':sum(coverage(w)[0] for w in cached),
                             'doi_enriched_works':sum(bool(w.get('openalex_id')) for w in cached),
                             'enrichment_status':'not-resumed-cache'})
            item.update({'status':'complete','works':len(cached),'checksum_sha256':checksum(out),'path':str(out),
                         'affiliation_coverage_pct':round(100*sum(coverage(w)[0] for w in cached)/max(1,sum(coverage(w)[1] for w in cached)),2)})
            rows.append(item)
            checkpoint()
            print(f"{vkey}/{year}: complete ({len(cached)} works; reused interrupted cache)")
            continue
        try:
            works,meta=api_works(vkey,year,entry,venue,key,state,args.raw_cache)
            item.update(meta)
            if entry.get('source')=='openalex':
                works=hydrate_truncated_openalex(works,state,key)
            if entry.get('source')=='crossref':
                item['baseline_alignment_merge']=preserve_aligned_baseline_enrichment(works,vkey,year,args.baseline_cache)
            if entry.get('source')=='crossref' and not args.no_enrich:
                # Commit validated Crossref membership first. If auxiliary OA
                # enrichment is interrupted, resume can reuse this raw payload.
                write_atomic(out,works)
                partial_before=len(state.get('enrichment_partial_batches',[]))
                before=sum(coverage(w)[0] for w in works); works=enrich_crossref(works,state,key); after=sum(coverage(w)[0] for w in works)
                item['affiliation_slots_before']=before; item['affiliation_slots_after']=after
                item['doi_enriched_works']=sum(bool(w.get('openalex_id')) for w in works)
                new_partials=state.get('enrichment_partial_batches',[])[partial_before:]
                item['enrichment_status']='partial' if new_partials else 'complete'
                item['enrichment_partial_batches']=new_partials
            expected=entry.get('count')
            # Some registry counts are old/provisional. Exact API consistency is required; registration delta is reported.
            if expected is not None:
                item['registered_count_delta']=len(works)-expected
                if item['registered_count_delta']:
                    item['registered_count_delta_reason']='Current source query passed edition, DOI, prefix/container, and pagination checks; registered count is treated as dated metadata and the observed delta is reported without forcing a match.'
            if len(works)==0 and entry.get('source')!='none': raise RefreshError('source returned zero works')
            seen=set()
            for w in works:
                d=norm_doi(w.get('doi'))
                if d and d in seen: raise RefreshError('final DOI duplicate')
                if d: seen.add(d)
                if int(w.get('publication_year') or 0)!=year: raise RefreshError('final work has wrong edition year')
            write_atomic(out,works)
            item.update({'status':'complete','works':len(works),'checksum_sha256':checksum(out),'path':str(out),
                         'affiliation_coverage_pct':round(100*sum(coverage(w)[0] for w in works)/max(1,sum(coverage(w)[1] for w in works)),2)})
        except Exception as e:
            item.update({'status':'blocked','error':f'{type(e).__name__}: {e}'})
            blocked.append(item)
        rows.append(item)
        checkpoint()
        print(f"{vkey}/{year}: {item['status']} ({item.get('works',0)} works)")
    report={'schema_version':1,'generated_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'years':list(args.years),
            'output_cache':args.output,'openalex_call_limit':args.oa_call_limit,
            'openalex_list_calls':prior_oa_calls+state['oa_calls'],'openalex_calls_prior_run':prior_oa_calls,
            'openalex_calls_current_run':state['oa_calls'],'crossref_http_attempts':prior_crossref_calls+state['crossref_calls'],
            'crossref_attempts_prior_run':prior_crossref_calls,'crossref_attempts_current_run':state['crossref_calls'],
            'enrichment_budget_exhausted':state.get('enrichment_budget_exhausted',False),
            'enrichment_partial_batches':state.get('enrichment_partial_batches',[]),
            'large_authorship_hydration':{'attempts':state.get('hydration_attempts',0),'successes':state.get('hydration_successes',0)},
            'unexpected_extra_scope':{'description':'Non-conference venue-years fetched by the initial run due to a filter bug; their scratch directories were removed before resuming. Their incurred calls remain included above.',
                'venue_year_rows':len(extra_scope),'venues':sorted({r.get('venue') for r in extra_scope})},
            'results':rows,'blocked_count':len(blocked)}
    for r in rows:
        if r.get('status')!='complete': continue
        r['baseline_comparison']=baseline_summary(r['venue'],r['year'],args.baseline_cache)
        r['unhydrated_100plus_works']=sum(1 for w in read_works(Path(r['path']))
                                         if w.get('source')=='openalex' and len(w.get('authorships') or [])>=100)
    report['large_authorship_hydration']['unhydrated_native_works']=sum(r.get('unhydrated_100plus_works',0) for r in rows if r.get('status')=='complete')
    rp.parent.mkdir(parents=True,exist_ok=True); tmp=rp.with_suffix(rp.suffix+'.tmp'); tmp.write_text(json.dumps(report,indent=2)+'\n'); os.replace(tmp,rp)
    print(f"OpenAlex calls {state['oa_calls']}/{state['oa_limit']}; blocked {len(blocked)}; report {rp}")
    return 1 if blocked else 0

if __name__=='__main__': raise SystemExit(main())
