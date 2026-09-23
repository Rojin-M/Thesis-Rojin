"""Exercise website control commands with isolated fake processes, never live sites."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]/'scripts/websites.sh'
FAKE = r'''
import json, os, sys
from pathlib import Path
from urllib.parse import urlsplit
p=Path(os.environ['SITE_TEST_STATE'])
s=json.loads(p.read_text())
tool=Path(sys.argv[0]).name
args=sys.argv[1:]
s['calls'].append([tool,*args])
ports={'exoplanet-academy':8765,'exoplanet-research':8766,'exoplanet-research-recovery':8767}
rc=0
if tool=='tmux':
    op=args[0]
    if op in ('has-session','display-message','send-keys','kill-session'):
        target=args[args.index('-t')+1]
        assert target.startswith('='), target
        target=target[1:].split(':')[0]
        if op=='has-session': rc=0 if target in s['sessions'] else 1
        elif op=='display-message': print('0')
        elif target not in s.get('stuck',[]):
            s['sessions'].remove(target)
            s['ports'].remove(ports[target])
    elif op=='new-session':
        name=args[args.index('-s')+1]
        s['sessions'].append(name)
        s['ports'].append(ports[name])
    else: raise AssertionError(op)
elif tool=='curl':
    port=urlsplit(args[-1]).port
    rc=0 if port in s['ports'] and port not in s.get('unhealthy',[]) else 7
elif tool=='python': rc=0 if int(args[-1]) in s['ports'] else 1
elif tool!='sleep': raise AssertionError(tool)
p.write_text(json.dumps(s))
sys.exit(rc)
'''


class WebsiteHelperTests(unittest.TestCase):
    def run_helper(self, args, sessions=(), ports=(), **extra):
        with tempfile.TemporaryDirectory(prefix='academy-site-control-') as tmp:
            root=Path(tmp)
            bindir=root/'bin'
            bindir.mkdir()
            (root/'.venv/bin').mkdir(parents=True)
            (root/'academy').mkdir()
            (root/'scripts').mkdir()
            for path in [*(bindir/name for name in ('tmux','curl','sleep')),root/'.venv/bin/python']:
                path.write_text('#!'+sys.executable+'\n'+FAKE)
                path.chmod(0o700)
            helper=root/'scripts/websites.sh'
            helper.write_text(SOURCE.read_text())
            state=root/'state.json'
            state.write_text(json.dumps(dict(sessions=list(sessions),ports=list(ports),calls=[],**extra)))
            env=dict(os.environ,PATH=str(bindir)+os.pathsep+os.environ['PATH'],SITE_TEST_STATE=str(state))
            result=subprocess.run(['bash',str(helper),*args],env=env,capture_output=True,text=True,timeout=15)
            return result,json.loads(state.read_text())

    def test_start_reuses_healthy_sites_and_preserves_workers(self):
        sessions=['exoplanet-academy','exoplanet-research','exoplanet-auto-watcher','exoplanet-model-comparisons']
        result,state=self.run_helper(['start'],sessions,[8765,8766])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(state['sessions'],sessions)
        self.assertFalse(any(c[1:2]==['new-session'] for c in state['calls']))

    def test_restart_research_stops_exact_session_before_starting_it(self):
        sessions=['exoplanet-academy','exoplanet-research','exoplanet-research-recovery','exoplanet-auto-watcher']
        result,state=self.run_helper(['restart','research'],sessions,[8765,8766,8767])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(set(state['sessions']),set(sessions))
        stop=next(i for i,c in enumerate(state['calls']) if c[1:2]==['send-keys'])
        start=next(i for i,c in enumerate(state['calls']) if c[1:2]==['new-session'])
        self.assertLess(stop,start)
        self.assertIn('=exoplanet-research:0.0',state['calls'][stop])

    def test_recovery_stop_cannot_match_main_research_session(self):
        result,state=self.run_helper(['stop','recovery'],['exoplanet-research','exoplanet-research-recovery'],[8766,8767])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(state['sessions'],['exoplanet-research'])
        self.assertEqual(state['ports'],[8766])

    def test_unmanaged_port_is_not_killed_or_replaced(self):
        result,state=self.run_helper(['restart','research'],[],[8766])
        self.assertEqual(result.returncode,1)
        self.assertIn('still occupied',result.stderr)
        self.assertEqual(state['ports'],[8766])
        self.assertFalse(any(c[1:2] in (['send-keys'],['kill-session'],['new-session']) for c in state['calls']))

    def test_default_stop_excludes_workers_and_recovery(self):
        sessions=['exoplanet-academy','exoplanet-research','exoplanet-auto-watcher','exoplanet-model-comparisons','exoplanet-research-recovery']
        result,state=self.run_helper(['stop'],sessions,[8765,8766,8767])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(state['sessions'],sessions[2:])
        self.assertEqual(state['ports'],[8767])

    def test_unfinished_stop_prevents_duplicate_restart(self):
        result,state=self.run_helper(['restart','research'],['exoplanet-research'],[8766],stuck=['exoplanet-research'])
        self.assertEqual(result.returncode,1)
        self.assertIn('has not exited',result.stderr)
        self.assertFalse(any(c[1:2]==['new-session'] for c in state['calls']))

    def test_start_from_stopped_launches_only_two_websites(self):
        result,state=self.run_helper(['start'])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(state['sessions'],['exoplanet-academy','exoplanet-research'])
        self.assertEqual(state['ports'],[8765,8766])

    def test_invalid_target_fails_without_changing_processes(self):
        result,state=self.run_helper(['stop','exoplanet-auto-watcher'],['exoplanet-auto-watcher'])
        self.assertEqual(result.returncode,2)
        self.assertEqual(state['sessions'],['exoplanet-auto-watcher'])
        self.assertEqual(state['calls'],[])


if __name__=='__main__':
    unittest.main(verbosity=2)
