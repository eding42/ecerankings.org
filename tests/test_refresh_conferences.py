import importlib.util
import unittest
from unittest.mock import patch
import json
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('refresh_conferences',Path(__file__).parents[1]/'pipeline/refresh_conferences.py')
rc=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(rc)


class RefreshConferencesTests(unittest.TestCase):
    def test_norm_doi_normalizes_resolver_and_case(self):
        self.assertEqual(rc.norm_doi('HTTPS://DOI.ORG/10.1109/ABC.2024.1'),'10.1109/abc.2024.1')

    def test_crossref_records_keep_editions_year_and_raw_affiliations(self):
        w=rc.crossref_to_work({'DOI':'10.1109/x.2024.1','title':['Paper &#x2019; title'],'type':'proceedings-article',
            'issued':{'date-parts':[[2025]]},'author':[{'given':'J&#x00F6;rg','family':'Researcher','affiliation':[{'name':'&#x00C9;cole Polytechnique'}]}]},2024)
        self.assertEqual(w['publication_year'],2024)
        self.assertEqual(w['crossref_issued_year'],2025)
        self.assertEqual(w['title'],'Paper ’ title')
        self.assertEqual(w['provider_raw_title'],'Paper &#x2019; title')
        self.assertEqual(w['authorships'][0]['author_name'],'Jörg Researcher')
        self.assertEqual(w['authorships'][0]['raw_affiliations'],['École Polytechnique'])
        self.assertEqual(w['authorships'][0]['provider_raw_affiliations'],['&#x00C9;cole Polytechnique'])
        self.assertEqual(rc.normalize_name('J&#x00F6;rg Researcher'),rc.normalize_name('Jörg Researcher'))
        self.assertEqual(rc.decode_crossref_text('&amp;#x00C9;cole Polytechnique'),'École Polytechnique')

    def test_crossref_postpass_decodes_existing_work_and_preserves_provider_text(self):
        work={'source':'crossref','title':'Paper &amp; title','authorships':[{'author_id':'crossref:name:jane-smith',
            'author_name':'Jane Smith','institutions':[],'raw_affiliations':['&#x00C9;cole Polytechnique']}]}
        stats=rc.decode_crossref_work(work)
        self.assertEqual(work['title'],'Paper & title')
        self.assertEqual(work['provider_raw_title'],'Paper &amp; title')
        self.assertEqual(work['authorships'][0]['raw_affiliations'],['École Polytechnique'])
        self.assertEqual(work['authorships'][0]['provider_raw_affiliations'],['&#x00C9;cole Polytechnique'])
        self.assertEqual(stats['affiliation_strings'],1)

    def test_baseline_enrichment_carries_only_for_exact_doi_and_byline(self):
        baseline=[{'doi':'10.1/a','authorships':[{'author_name':'Jane Smith','author_id':'https://openalex.org/A1',
            'institutions':[{'id':'I1','display_name':'Example U'}],'raw_affiliations':['Old raw']}]}]
        works=[{'doi':'10.1/a','authorships':[{'author_name':'Jane Smith','author_id':'crossref:name:jane-smith',
            'institutions':[],'raw_affiliations':['Current raw']}]},
               {'doi':'10.1/b','authorships':[{'author_name':'Other Person','institutions':[],'raw_affiliations':[]}]}]
        with patch.object(rc,'read_works',return_value=baseline):
            stats=rc.preserve_aligned_baseline_enrichment(works,'conf',2024)
        self.assertEqual(works[0]['authorships'][0]['institutions'][0]['id'],'I1')
        self.assertEqual(works[0]['authorships'][0]['author_id'],'https://openalex.org/A1')
        self.assertEqual(works[0]['authorships'][0]['raw_affiliations'],['Current raw'])
        self.assertEqual(stats['baseline_doi_byline_matches'],1)
        self.assertEqual(stats['institutions_preserved'],1)

    def test_baseline_summary_uses_supplied_cache_root(self):
        import tempfile
        temp_parent=rc.ROOT/'.tmp/refresh-2026-10-28'; temp_parent.mkdir(parents=True,exist_ok=True)
        root=Path(tempfile.mkdtemp(dir=temp_parent))
        try:
            path=root/'example'/'2024'/'works.jsonl'
            rc.write_atomic(path,[{'authorships':[{'author_name':'Jane Smith','institutions':[{'id':'I1'}]}]}])
            summary=rc.baseline_summary('example',2024,root)
            self.assertTrue(summary['present'])
            self.assertEqual(summary['works'],1)
            self.assertEqual(summary['affiliation_slots'],1)
        finally:
            import shutil
            shutil.rmtree(root)

    def test_crossref_raw_pages_use_supplied_cache_root(self):
        import tempfile
        temp_parent=rc.ROOT/'.tmp/refresh-2026-10-28'; temp_parent.mkdir(parents=True,exist_ok=True)
        root=Path(tempfile.mkdtemp(dir=temp_parent))
        try:
            title='2016 Example Conference'
            entry={'source':'crossref','doi_prefix':'10.1234/example.2016','count':1,'container_title':title}
            page={'message':{'total-results':1,'items':[
                {'DOI':'10.1234/example.2016.1','title':['Paper'],'type':'proceedings-article',
                 'container-title':[title],'author':[],'issued':{'date-parts':[[2016]]}}
            ]}}
            with patch.object(rc,'crossref_page',return_value=page):
                works,meta=rc.api_works('cvpr',2016,entry,{},None,{'crossref_calls':0},root)
            cached=root/'cvpr'/'2016'/'page-00001.jsonl'
            self.assertTrue(cached.is_file())
            self.assertEqual(len(works),1)
            self.assertEqual(Path(meta['api_raw_page_cache']),cached.parent)
        finally:
            import shutil
            shutil.rmtree(root)

    def test_comma_title_crossref_query_pages_fuzzy_results_and_accepts_exact_scope_only(self):
        title='2016 IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP)'
        entry={'source':'crossref','doi_prefix':'10.1109/icassp.2016','count':2,'container_title':title}
        def record(doi,container):
            return {'DOI':doi,'title':['Paper'],'type':'proceedings-article','container-title':[container],
                    'author':[],'issued':{'date-parts':[[2016]]}}
        pages=[
            {'message':{'total-results':4,'next-cursor':'next','items':[
                record('10.1109/icassp.2016.1',title),
                record('10.1109/icassp.2016.2',title+' Workshop')]}},
            {'message':{'total-results':4,'items':[
                record('10.1109/other.2016.3',title),
                record('10.1109/icassp.2016.4','Other Conference')]}}
        ]
        calls=[]
        def page(params,state):
            calls.append(dict(params)); return pages.pop(0)
        with patch.object(rc,'crossref_page',page):
            works,meta=rc.api_works('icassp',2016,entry,{},None,{'crossref_calls':0})
        self.assertEqual(len(calls),2)
        self.assertIn('prefix:10.1109',calls[0]['filter'])
        self.assertIn('type:proceedings-article',calls[0]['filter'])
        self.assertEqual(calls[0]['query.container-title'],'ICASSP')
        self.assertNotIn('container-title:',calls[0]['filter'])
        self.assertEqual([w['doi'] for w in works],['https://doi.org/10.1109/icassp.2016.1'])
        self.assertEqual(meta['api_raw_count'],4)
        self.assertEqual(meta['api_count'],1)
        self.assertEqual(meta['api_rejected_raw_count'],3)

    def test_comma_title_registered_as_volume_two_accepts_other_registered_volume_family(self):
        title='Proceedings of the 28th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 2'
        entry={'source':'crossref','doi_prefix':'10.1145/3567955,10.1145/3575693','count':2,'container_title':title}
        def record(doi,container):
            return {'DOI':doi,'title':['Paper'],'type':'proceedings-article','container-title':[container],
                    'author':[],'issued':{'date-parts':[[2023]]}}
        pages=[{'message':{'total-results':4,'items':[
            record('10.1145/3567955.1','Proceedings of the 28th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 1'),
            record('10.1145/3575693.1',title),
            record('10.1145/3567955.2','Proceedings of the 28th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 1 Workshops'),
            record('10.1145/other.3','Proceedings of the 28th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 1')]} }]
        with patch.object(rc,'crossref_page',side_effect=lambda params,state:pages.pop(0)):
            works,meta=rc.api_works('asplos',2023,entry,{},None,{'crossref_calls':0})
        self.assertEqual([w['doi'] for w in works],['https://doi.org/10.1145/3567955.1','https://doi.org/10.1145/3575693.1'])
        self.assertEqual(meta['api_raw_count'],4)
        self.assertEqual(meta['api_count'],2)
        self.assertFalse(rc.container_matches_scope('Proceedings of the 28th ACM International Conference for Workshops, Volume 1',title))

    def test_exact_crossref_query_uses_cursor_and_reconciles_identical_duplicate_doi(self):
        title='2020 Conference on Example Research'
        entry={'source':'crossref','doi_prefix':'10.1234/example.2020','count':2,'container_title':title}
        def record(doi):
            return {'DOI':doi,'title':['Paper'],'type':'proceedings-article','container-title':[title],
                    'author':[{'given':'A','family':'Researcher'}],'issued':{'date-parts':[[2020]]}}
        duplicate=record('10.1234/example.2020.1')
        pages=[{'message':{'total-results':3,'next-cursor':'next','items':[duplicate,record('10.1234/example.2020.2')]}},
               {'message':{'total-results':3,'items':[duplicate]} }]
        calls=[]
        def page(params,state):calls.append(dict(params));return pages.pop(0)
        with patch.object(rc,'crossref_page',page):
            works,meta=rc.api_works('test-conf',2020,entry,{},None,{'crossref_calls':0})
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['cursor'],'*');self.assertEqual(calls[1]['cursor'],'next')
        self.assertNotIn('offset',calls[0])
        self.assertEqual(len(works),2)
        self.assertEqual(meta['api_raw_count'],3)
        self.assertEqual(meta['api_count'],2)
        self.assertEqual(meta['api_duplicate_raw_count'],1)
        self.assertEqual(meta['api_rejected_raw_count'],0)

    def test_exact_crossref_query_rejects_conflicting_duplicate_doi(self):
        title='2020 Conference on Example Research'
        entry={'source':'crossref','doi_prefix':'10.1234/example.2020','count':1,'container_title':title}
        a={'DOI':'10.1234/example.2020.1','title':['Paper'],'type':'proceedings-article','container-title':[title],'author':[]}
        b={**a,'title':['Different paper']}
        pages=[{'message':{'total-results':2,'next-cursor':'next','items':[a]}},
               {'message':{'total-results':2,'items':[b]}}]
        with patch.object(rc,'crossref_page',side_effect=lambda params,state:pages.pop(0)):
            with self.assertRaisesRegex(rc.RefreshError,'conflicting duplicate DOI'):
                rc.api_works('test-conf',2020,entry,{},None,{'crossref_calls':0})

    def test_oa_enrichment_refuses_name_mismatch(self):
        work={'doi':'https://doi.org/10.1109/x.1','authorships':[{'author_name':'Jane Smith','institutions':[], 'raw_affiliations':['known']}]}
        def page(url,key,state,**kwargs):
            state['oa_calls']+=1
            return {'meta':{'count':1},'results':[{'doi':'https://doi.org/10.1109/x.1','id':'https://openalex.org/W1',
                'authorships':[{'author':{'id':'A1','display_name':'Wrong Person'},'institutions':[{'id':'I1','display_name':'X'}]}]}]}
        with patch.object(rc,'oa_page',page):
            st={'oa_calls':0,'oa_limit':10}
            got=rc.enrich_crossref([work],st,'key')[0]
        self.assertFalse(got.get('openalex_id'))
        self.assertEqual(got['authorships'][0]['raw_affiliations'],['known'])

    def test_oa_enrichment_preserves_known_raw_coverage(self):
        work={'doi':'10.1109/x.1','authorships':[{'author_name':'Jane Smith','institutions':[], 'raw_affiliations':['known']}]}
        def page(url,key,state,**kwargs):
            state['oa_calls']+=1
            return {'meta':{'count':1},'results':[{'doi':'https://doi.org/10.1109/x.1','id':'https://openalex.org/W1',
                'authorships':[{'author':{'id':'A1','display_name':'Jane Smith'},'institutions':[]}]}]}
        with patch.object(rc,'oa_page',page):
            st={'oa_calls':0,'oa_limit':10}
            got=rc.enrich_crossref([work],st,'key')[0]
        self.assertFalse(got.get('openalex_id'))
        self.assertEqual(got['authorships'][0]['raw_affiliations'],['known'])

    def test_oa_alignment_normalizes_crossref_html_entity_author_name(self):
        work=rc.crossref_to_work({'DOI':'10.1109/x.1','title':['Paper'],'type':'proceedings-article',
            'author':[{'given':'J&#x00F6;rg','family':'Researcher'}]},2024)
        def page(url,key,state,**kwargs):
            state['oa_calls']+=1
            return {'meta':{'count':1},'results':[{'doi':'10.1109/x.1','id':'https://openalex.org/W1',
                'authorships':[{'author':{'display_name':'Jörg Researcher'},
                                'institutions':[{'id':'I1','display_name':'École Polytechnique'}]}]}]}
        with patch.object(rc,'oa_page',page):
            rc.enrich_crossref([work],{'oa_calls':0,'oa_limit':5},'key')
        self.assertEqual(work.get('openalex_id'),'https://openalex.org/W1')
        self.assertEqual(work['authorships'][0]['author_name'],'Jörg Researcher')

    def test_oa_duplicate_doi_pages_and_selects_richest_aligned_record(self):
        work={'doi':'10.1109/x.1','authorships':[{'author_name':'Jane Smith','institutions':[], 'raw_affiliations':['kept']}]}
        calls=[]
        def page(url,key,state,**kwargs):
            calls.append(url); state['oa_calls']+=1
            if 'cursor=*' in url:
                return {'meta':{'count':2,'next_cursor':'next'},'results':[{'doi':'10.1109/x.1','id':'https://openalex.org/W1',
                    'authorships':[{'author':{'display_name':'Jane Smith'},'institutions':[]}]}]}
            return {'meta':{'count':2,'next_cursor':None},'results':[{'doi':'10.1109/x.1','id':'https://openalex.org/W2',
                'authorships':[{'author':{'id':'A1','display_name':'Jane Smith'},'institutions':[{'id':'I1','display_name':'X'}]}]}]}
        with patch.object(rc,'oa_page',page):
            st={'oa_calls':0,'oa_limit':10}
            got=rc.enrich_crossref([work],st,'key')[0]
        self.assertEqual(len(calls),2)
        self.assertEqual(got.get('openalex_id'),'https://openalex.org/W2')
        self.assertEqual(got['authorships'][0]['raw_affiliations'],['kept'])
        self.assertEqual(got['authorships'][0]['institutions'][0]['id'],'I1')

    def test_oa_enrichment_midfetch_failure_keeps_crossref_and_marks_partial(self):
        work={'doi':'10.1109/x.1','source':'crossref','authorships':[{'author_name':'Jane Smith','institutions':[], 'raw_affiliations':['kept']}]}
        calls=0
        def page(url,key,state,**kwargs):
            nonlocal calls
            calls+=1; state['oa_calls']+=1
            if calls==1:
                return {'meta':{'count':2,'next_cursor':'next'},'results':[{'doi':'10.1109/x.1','id':'https://openalex.org/W1',
                    'authorships':[{'author':{'display_name':'Jane Smith'},'institutions':[]}]}]}
            raise RuntimeError('network interruption')
        with patch.object(rc,'oa_page',page):
            st={'oa_calls':0,'oa_limit':10}
            got=rc.enrich_crossref([work],st,'key')[0]
        self.assertEqual(got['authorships'][0]['raw_affiliations'],['kept'])
        self.assertTrue(st['enrichment_partial_batches'])

    def test_large_native_openalex_work_hydrates_when_identity_matches(self):
        work={'id':'https://openalex.org/W1','doi':'https://doi.org/10.1/x','source':'openalex',
              'authorships':[{'author_name':f'A{i}','institutions':[]} for i in range(100)]}
        full={'id':work['id'],'doi':work['doi'],'authorships':[{'author':{'display_name':f'A{i}'},'institutions':[]} for i in range(103)]}
        with patch.object(rc,'request_json',return_value=full):
            st={}; got=rc.hydrate_truncated_openalex([work],st,'key')[0]
        self.assertEqual(len(got['authorships']),103)
        self.assertEqual(st['hydration_successes'],1)

    def test_atomic_write_replaces_whole_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'works.jsonl'
            p.write_text('{"old":true}\n')
            rc.write_atomic(p,[{'doi':'10.1/a'}])
            self.assertEqual([json.loads(x) for x in p.read_text().splitlines()],[{'doi':'10.1/a'}])
            self.assertEqual(sorted(x.name for x in p.parent.iterdir()),['works.jsonl'])

    def test_jsonl_loader_does_not_split_unicode_line_separator(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'works.jsonl'
            rc.write_atomic(p,[{'source':'crossref','doi':'https://doi.org/10.1109/x.1',
                                'publication_year':2024,'title':'Unicode\u2028separator'}])
            self.assertEqual(len(rc.read_works(p)),1)
            cached=rc.load_cached_edition(p,'conf',2024,{'source':'crossref','doi_prefix':'10.1109'})
            self.assertEqual(cached[0]['title'],'Unicode\u2028separator')

    def test_conference_iterator_excludes_journal_venues(self):
        registry={'areas':{'a':{'venues':[
            {'key':'conf','kind':'conference','years':{'2024':{'source':'crossref'}}},
            {'key':'journal','kind':'journal','years':{'2024':{'source':'openalex'}}},
        ]}}}
        rows=list(rc.conferences(registry,(2016,2026)))
        self.assertEqual([(row[1],row[3]) for row in rows],[('conf',2024)])

if __name__=='__main__': unittest.main()
