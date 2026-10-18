"""Windowless tests for tray action policy and screen-edge placement."""
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_tray_menu import MenuItem,menu_bounds
spec=importlib.util.spec_from_file_location('context_model_launcher',ROOT/'ai-launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class ContextModelTests(unittest.TestCase):
    def test_profile_actions_recheck_busy_and_keep_their_own_key(self):
        sent=[];busy=[False];current=['two'];auto=[True]
        with patch.object(launcher,'PROFILES',{'one':{},'two':{}}),patch.object(launcher,'PROFILE_NAMES',{'one':'First','two':'Second'}):
            rows=launcher.tray_context_items(lambda *args:sent.append(args),lambda:busy[0],lambda:current[0],lambda:auto[0])
            load=rows[1];profiles=load.children()
            self.assertEqual([row.selected() for row in profiles],[False,True])
            profiles[0].command();profiles[1].command()
            self.assertEqual(sent,[('start','one'),('start','two')])
            busy[0]=True
            self.assertFalse(load.available());self.assertFalse(profiles[0].available())
            self.assertFalse(rows[-1].available());self.assertTrue(rows[2].available())
            auto[0]=False;self.assertFalse(rows[3].selected())
            rows[3].command();self.assertEqual(sent[-1],('auto-toggle',))

    def test_no_profiles_disable_loading_and_exit_never_unloads(self):
        sent=[]
        with patch.object(launcher,'PROFILES',{}):
            rows=launcher.tray_context_items(lambda *args:sent.append(args),lambda:False,lambda:None,lambda:True)
            self.assertFalse(rows[1].available())
            rows[-1].command();self.assertEqual(sent,[('quit',)])
            self.assertEqual(rows[-1].tooltip,'Keeps the model running.')

    def test_placement_clamps_all_edges_negative_monitors_and_tiny_work_areas(self):
        for work in ((0,0,1920,1040),(-1920,-800,0,240),(0,0,12,8)):
            for anchor in ((-3000,-2000),(0,0),(9999,9999)):
                width,height,x,y=menu_bounds(anchor,(600,4000),work)
                self.assertGreaterEqual(x,work[0]);self.assertGreaterEqual(y,work[1])
                self.assertLessEqual(x+width,work[2]);self.assertLessEqual(y+height,work[3])


if __name__=='__main__':unittest.main()
