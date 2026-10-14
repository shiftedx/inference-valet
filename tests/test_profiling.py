import argparse
import importlib.util
import pathlib
import sys
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('performance_profiler',ROOT/'scripts/profile-performance.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class ProfilerTests(unittest.TestCase):
    def test_restart_is_a_separate_memory_and_handle_segment(self):
        def sample(pid,cpu,rss,handles,active):
            return dict(active_requests=active,processes={'tray':dict(pid=pid,created=pid,
                one_core_percent=cpu,rss_mib=rss,handles=handles,threads=4)})
        rows=[sample(1,None,50,100,0),sample(1,.5,51,101,0),sample(2,None,30,70,0),sample(2,3,31,71,1)]
        result=p.summarize(rows)['tray']
        self.assertEqual(len(result['segments']),2)
        self.assertEqual([s['rss_growth_mib'] for s in result['segments']],[1,1])
        self.assertEqual([s['handles_growth'] for s in result['segments']],[1,1])
        self.assertEqual(result['idle_cpu_mean'],.5)
        self.assertEqual(result['cpu_mean'],1.75)

    def test_duration_and_interval_reject_unbounded_values(self):
        for value in ('nan','inf','0','-1'):
            with self.assertRaises(argparse.ArgumentTypeError):p.positive(value)

if __name__=='__main__':unittest.main()
