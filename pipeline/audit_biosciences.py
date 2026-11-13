import urllib.request, urllib.parse, json, os, sys
from collections import Counter

env = {}
if os.path.exists('.env'):
    for line in open('.env'):
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            env[k.strip()] = v.strip()

api_key = env.get('OPENALEX_API_KEY')

def api_get(endpoint, params):
    params = dict(params)
    params['mailto'] = 'eding2019@gmail.com'
    if api_key: params['api_key'] = api_key
    url = f'https://api.openalex.org{endpoint}?' + urllib.parse.urlencode(params, safe=":,|*!")
    req = urllib.request.Request(url, headers={'User-Agent': 'ecerankings/1.0 (mailto:eding2019@gmail.com)'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

venues = {
    'cell': {'id': 'S110447773', 'name': 'Cell', 'issn': '0092-8674'},
    'nature': {'id': 'S137773608', 'name': 'Nature', 'issn': '0028-0836'},
    'science': {'id': 'S3880285', 'name': 'Science', 'issn': '0036-8075'},
    'pnas': {'id': 'S125754415', 'name': 'Proceedings of the National Academy of Sciences (PNAS)', 'issn': '0027-8424'}
}

results = {}

for vkey, vinfo in venues.items():
    sid = vinfo['id']
    print(f"\n====================================\nAnalyzing {vinfo['name']} ({sid})\n====================================")
    
    # 1. Yearly counts (total and by type)
    # group_by=publication_year
    res_years = api_get('/works', {
        'filter': f'primary_location.source.id:{sid},publication_year:2016-2025',
        'group_by': 'publication_year'
    })
    year_counts = {item['key']: item['count'] for item in res_years.get('group_by', [])}
    
    # By type for 2021-2025
    res_types = api_get('/works', {
        'filter': f'primary_location.source.id:{sid},publication_year:2024',
        'group_by': 'type'
    })
    type_counts_2024 = {item['key']: item['count'] for item in res_types.get('group_by', [])}
    
    # Research articles only (type:article) by year
    res_articles = api_get('/works', {
        'filter': f'primary_location.source.id:{sid},publication_year:2016-2025,type:article',
        'group_by': 'publication_year'
    })
    article_year_counts = {item['key']: item['count'] for item in res_articles.get('group_by', [])}

    # Field / Domain breakdown (OpenAlex concepts or primary_topic.field or primary_topic.domain)
    # Let's inspect primary_topic.domain
    res_domain = api_get('/works', {
        'filter': f'primary_location.source.id:{sid},publication_year:2024,type:article',
        'group_by': 'primary_topic.domain.id'
    })
    domains_2024 = {item['key_display_name']: item['count'] for item in res_domain.get('group_by', [])}

    # primary_topic.field
    res_field = api_get('/works', {
        'filter': f'primary_location.source.id:{sid},publication_year:2024,type:article',
        'group_by': 'primary_topic.field.id'
    })
    fields_2024 = {item['key_display_name']: item['count'] for item in res_field.get('group_by', [])[:10]}

    # Top institutions (2022-2024, type:article)
    res_insts = api_get('/works', {
        'filter': f'primary_location.source.id:{sid},publication_year:2022-2024,type:article',
        'group_by': 'authorships.institutions.id'
    })
    top_insts = [{'name': item['key_display_name'], 'count': item['count']} for item in res_insts.get('group_by', [])[:15]]

    # Affiliation coverage sample on recent 100 works (2024, type:article)
    sample_works = api_get('/works', {
        'filter': f'primary_location.source.id:{sid},publication_year:2024,type:article',
        'per_page': 100,
        'select': 'id,title,authorships'
    })
    works_list = sample_works.get('results', [])
    works_with_affil = 0
    total_author_slots = 0
    affil_author_slots = 0
    for w in works_list:
        auths = w.get('authorships', [])
        has_aff = any(bool(a.get('institutions')) or bool(a.get('raw_affiliation_strings')) for a in auths)
        if has_aff:
            works_with_affil += 1
        for a in auths:
            total_author_slots += 1
            if a.get('institutions') or a.get('raw_affiliation_strings'):
                affil_author_slots += 1

    work_cov_pct = (works_with_affil / len(works_list) * 100) if works_list else 0
    slot_cov_pct = (affil_author_slots / total_author_slots * 100) if total_author_slots else 0

    results[vkey] = {
        'name': vinfo['name'],
        'id': sid,
        'issn': vinfo['issn'],
        'year_counts': year_counts,
        'article_year_counts': article_year_counts,
        'types_2024': type_counts_2024,
        'domains_2024': domains_2024,
        'fields_2024': fields_2024,
        'top_insts': top_insts,
        'sample_work_coverage': work_cov_pct,
        'sample_slot_coverage': slot_cov_pct,
        'sample_size': len(works_list)
    }

with open('/tmp/biosciences_venue_audit.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\nSaved full audit to /tmp/biosciences_venue_audit.json")
