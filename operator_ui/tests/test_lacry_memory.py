"""Persistent context and review boundaries; temporary storage, no hardware."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from flask import Flask
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lacry_memory import LacryMemory,register_memory_api
from lacry_agent import LacryAgent
from researcher_teaching import TeachingError
from sequences import Runner


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'memory.sqlite3';self.store=LacryMemory(self.path)

    def test_survives_restart_and_deduplicates(self):
        row=self.store.add('Home hub','Hamilton goes via Home.',status='approved')
        self.store.add('Home hub','Hamilton goes via Home.',status='approved')
        reopened=LacryMemory(self.path)
        self.assertEqual(reopened.search('Hamilton')[0]['id'],row['id'])
        self.assertEqual(reopened.status()['total'],1)

    def test_pending_and_archived_notes_never_enter_model_context(self):
        pending=self.store.add('Never do this','Hamilton pending advice')
        approved=self.store.add('Home','Hamilton via Home',status='approved',pinned=True)
        self.assertEqual([r['id'] for r in self.store.context('Hamilton')],[approved['id']])
        self.store.update(approved['id'],1,'archived')
        self.assertEqual(self.store.context('Hamilton'),[])
        self.assertEqual(len(self.store.search('Hamilton',developer=True)),2)
        self.store.update(pending['id'],1,'approved')
        self.assertEqual(self.store.search('Hamilton')[0]['id'],pending['id'])

    def test_revision_conflict_and_history_preserved(self):
        row=self.store.add('Old','Old content')
        updated=self.store.update(row['id'],1,'approved',body='Corrected content')
        self.assertEqual(updated['revision'],2)
        with self.assertRaises(TeachingError):self.store.update(row['id'],1,'archived')
        exported=self.store.export()
        self.assertEqual(len(exported['revisions']),2)
        self.assertFalse(exported['executable'])

    def test_seed_does_not_resurrect_or_overwrite_reviewed_notes(self):
        seed=Path(__file__).resolve().parents[1]/'lacry_memory_seed.json'
        self.store.seed(seed);row=self.store.search('two disk calibration')[0]
        self.store.update(row['id'],1,'archived');self.store.seed(seed)
        self.assertEqual(self.store.status()['counts']['archived'],1)
        self.assertEqual(self.store.status()['total'],8)

    def test_concurrent_writes_and_bounded_context(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda i:self.store.add(f'Entry {i}','Hamilton '+('x'*600),status='approved'),range(12)))
        self.assertEqual(self.store.status()['total'],12)
        rows=self.store.context('Hamilton',budget=2000)
        self.assertTrue(rows)
        self.assertLessEqual(sum(len(json.dumps(r,ensure_ascii=False)) for r in rows),2000)

    def test_outcomes_are_observations_and_secrets_are_redacted(self):
        fields=dict(run_id='run-one',sequence='lacry_plan',state='error',result={'ok':False,'api_key':'do-not-save','error':'failed'})
        self.store.observe_event('sequence_finished',fields,'audit/path.jsonl')
        self.store.observe_event('sequence_finished',fields,'audit/path.jsonl')
        row=self.store.search('lacry_plan')[0]
        self.assertEqual(row['status'],'observed');self.assertEqual(row['kind'],'observation')
        self.assertIn('failed_or_uncertain',row['body']);self.assertNotIn('do-not-save',row['body'])
        note=self.store.add('Secret','api_key=abc sk-ant-123456 Bearer abcd')
        self.assertNotIn('123456',note['body']);self.assertNotIn('abcd',note['body'])
        self.assertEqual(self.store.status()['total'],2)

    def test_model_notes_remain_pending_and_context_reaches_next_model_call(self):
        self.store.add('Station rule','Hamilton uses Home.',status='approved',pinned=True)
        run=Runner();backend=Mock();client=Mock()
        client.complete.return_value={'content':[{'type':'text','text':'Use Home.'}]}
        agent=LacryAgent(backend,Mock(),lambda:run,client=client,memory=self.store)
        agent.public=Mock(return_value={'ok':True})
        result,error=agent._run_tool('save_memory_note',dict(title='Suggestion',body='Pending suggestion'))
        self.assertFalse(error);self.assertEqual(json.loads(result)['status'],'pending')
        agent.send('What is the Hamilton route?')
        system=client.complete.call_args.args[0]['system']
        self.assertIn('Hamilton uses Home.',system);self.assertNotIn('Pending suggestion',system)
        backend.execute_step.assert_not_called()

    def test_developer_api_review_and_export(self):
        app=Flask(__name__);register_memory_api(app,self.store);client=app.test_client()
        result=client.post('/developer/api/lacry-memory',json={'title':'Route','body':'Via Home'}).get_json()
        row=result['item'];self.assertEqual(row['status'],'approved')
        response=client.post('/developer/api/lacry-memory/'+row['id'],json={'status':'archived','revision':1})
        self.assertEqual(response.status_code,200)
        stale=client.post('/developer/api/lacry-memory/'+row['id'],json={'status':'approved','revision':1})
        self.assertEqual(stale.status_code,409)
        exported=client.get('/developer/api/lacry-memory/export').get_json()
        self.assertEqual(exported['memories'][0]['status'],'archived')


if __name__=='__main__':unittest.main()
