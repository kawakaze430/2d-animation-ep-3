"""Contracts for all eighty real screenplay shots and conserved cooking state."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'animation2d/episode03'
sys.path.insert(0,str(PACKAGE))
SPEC=importlib.util.spec_from_file_location('episode03_manifest',PACKAGE/'manifest.py')
manifest=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)
import state


class Episode03ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=manifest.compile_manifest()

    def test_all_eighty_shots_and_240_dialogue_turns_match_screenplay(self):
        self.assertEqual(len(self.data['shots']),80)
        self.assertEqual(self.data['shots'][0]['title'],'The breakfast we promised')
        self.assertEqual(sum(len(shot['dialogue']) for shot in self.data['shots']),240)
        source=manifest.source_shots()
        for number,(shot,text) in enumerate(zip(self.data['shots'],source)):
            self.assertEqual(shot['start'],number*15)
            self.assertEqual(shot['duration'],15)
            self.assertEqual([(turn['speaker'],turn['text']) for turn in shot['dialogue']],text['dialogue'])
            self.assertEqual(shot['source']['action'],text['fields']['Action'])
        self.assertEqual(self.data['shots'][-1]['start']+15,1200)

    def test_six_distinct_voices_and_existing_unchanged_reference_paths(self):
        self.assertEqual(set(self.data['characters']),set(state.CAST))
        self.assertEqual(len({actor['voice']['preset'] for actor in self.data['characters'].values()}),6)
        for actor in self.data['characters'].values():
            self.assertTrue((ROOT/actor['reference']['portrait']).is_file())
            self.assertTrue((ROOT/actor['reference']['sheet']).is_file())
            self.assertIn('assets/rigs/',actor['rig'])

    def test_state_persists_and_six_pairs_are_cooked_once(self):
        shots=self.data['shots']
        for previous,current in zip(shots,shots[1:]):
            self.assertEqual(previous['state_out'],current['state_in'])
        for number,total in ((52,2),(56,4),(57,6),(60,8),(61,10),(64,12)):
            self.assertEqual(shots[number-1]['state_out']['cooked_total'],total)
        self.assertEqual(shots[9]['state_out']['vase_location'],'decoration_shelf')
        self.assertTrue(all(shot['state_out']['vase_empty'] for shot in shots))
        self.assertEqual(shots[64]['state_out']['stove'],'OFF')
        self.assertEqual(shots[70]['state_out']['served'],{name:2 for name in state.CAST})
        self.assertEqual(shots[-1]['state_out']['eaten_total'],12)
        self.assertEqual(shots[-1]['state_out']['pan_butter_sixths_remaining'],0)

    def test_changed_dialogue_unknown_actor_voice_and_shot_timing_fail(self):
        mutations=[(lambda d:d['shots'][0]['dialogue'][0].update(text='Not the screenplay.'),'dialogue differs'),
                   (lambda d:d['shots'][0]['cast'].append('UNKNOWN'),'unknown or duplicate actor'),
                   (lambda d:d['characters']['DAN']['voice'].update(preset=d['characters']['MAYA']['voice']['preset']),'distinct voice'),
                   (lambda d:d['shots'][1].update(start=14),'continuous fifteen-second')]
        for mutate,message in mutations:
            candidate=deepcopy(self.data)
            mutate(candidate)
            with self.subTest(message=message),self.assertRaisesRegex(ValueError,message):
                manifest.validate_manifest(candidate)

    def test_mutated_food_counts_or_broken_continuity_fail(self):
        candidate=deepcopy(self.data)
        candidate['shots'][59]['state_out']['tray']=10
        with self.assertRaisesRegex(ValueError,'conservation failed'):
            manifest.validate_manifest(candidate)
        candidate=deepcopy(self.data)
        candidate['shots'][4]['state_in']['vase_location']='decoration_shelf'
        with self.assertRaisesRegex(ValueError,'previous shot'):
            manifest.validate_manifest(candidate)

    def test_impossible_raw_serving_extra_recipe_or_seventh_pair_fail(self):
        with self.assertRaises(ValueError):
            state.apply_event(state.initial_state(),{'type':'serve','actor':'DAN'})
        cooked=deepcopy(self.data['shots'][63]['state_out'])
        with self.assertRaises(ValueError):
            state.apply_event(cooked,{'type':'pour_pair'})
        for key,value in (('batch_count',2),('butter_total_tbsp',5),('vase_empty',False),('cooked_total',14)):
            candidate=state.initial_state();candidate[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                state.validate_state(candidate)

    def test_missing_production_rigs_are_explicit_blockers_not_invented_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            report=manifest.readiness(self.data,Path(directory))
        self.assertFalse(report['ready'])
        self.assertEqual(sum('separated production rig' in item for item in report['missing']),6)

    def test_editable_overrides_survive_regeneration_without_touching_story(self):
        before=(ROOT/'Episode_03/STORY.md').read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'overrides.json'
            file.write_text(json.dumps({'version':1,'shots':{'SHOT_002':{'camera':{'zoom':1.2},'actors':{'DAN':{'action':{'kind':'walk','target':[1200,650]}}}}}}))
            first=manifest.compile_manifest(overrides_path=file)
            second=manifest.compile_manifest(overrides_path=file)
        shot=first['shots'][1]
        self.assertEqual(shot['camera'],{'zoom':1.2,'center':[960,540]})
        self.assertEqual(shot['actors']['DAN']['action']['kind'],'walk')
        self.assertEqual(shot['actors']['DAN']['position'],self.data['shots'][1]['actors']['DAN']['position'])
        self.assertEqual(first,second)
        self.assertEqual(before,(ROOT/'Episode_03/STORY.md').read_bytes())

    def test_overrides_reject_unknown_shot_field_actor_or_duplicate_props(self):
        changes=[({'SHOT_999':{}},'unknown shot'),
                 ({'SHOT_001':{'state_out':{}}},'unknown override field'),
                 ({'SHOT_001':{'actors':{'ELLA':{'scale':.5}}}},'override actor must be visible'),
                 ({'SHOT_001':{'props':[{'id':'bowl'},{'id':'bowl'}]}},'duplicate prop')]
        for shots,message in changes:
            with self.subTest(message=message),tempfile.TemporaryDirectory() as directory:
                file=Path(directory)/'overrides.json'
                file.write_text(json.dumps({'version':1,'shots':shots}))
                with self.assertRaisesRegex(ValueError,message):
                    manifest.compile_manifest(overrides_path=file)

    def test_check_rejects_stale_compiled_manifest_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shots.json'
            path.write_text('{}\n')
            with patch.object(manifest,'PACKAGE',Path(directory)),patch.object(sys,'argv',['manifest.py','--check']):
                with self.assertRaisesRegex(ValueError,'shots.json is stale'):
                    manifest.main()
            self.assertEqual(path.read_text(),'{}\n')

    def test_generated_manifest_matches_current_sources_without_rewrite(self):
        before=(PACKAGE/'shots.json').read_bytes()
        result=subprocess.run([sys.executable,'-m','animation2d.episode03.manifest','--check'],
                              cwd=ROOT,check=False,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(before,(PACKAGE/'shots.json').read_bytes())
        self.assertIn('240 exact screenplay dialogue',result.stdout)


if __name__=='__main__':
    unittest.main()
